"""Offline binding/gap tests only: no candles, policy replay, or profit fixtures."""
from __future__ import annotations

import builtins
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import source_binding_gate as gate
import saved_summary_review as review


class SourceBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(__file__).resolve().parent
        cls.summary = json.loads((cls.base / "inputs/a4_summary.json").read_bytes())
        cls.parent = json.loads((cls.base / "inputs/parent236.json").read_bytes())
        cls.packet = json.loads((cls.base / "SOURCE_EXACT_FALSIFICATION.json").read_bytes())

    def test_actual_frozen_inputs_are_terminal_and_byte_preserved(self):
        paths = [self.base / "inputs/a4_summary.json", self.base / "inputs/parent236.json"]
        before = [path.read_bytes() for path in paths]
        result = gate.audit(self.base)
        self.assertEqual([path.read_bytes() for path in paths], before)
        self.assertTrue(result["binding_valid"])
        self.assertFalse(result["candidate_ready"])
        self.assertEqual(result["status"], "NO_SOURCE_EXACT_CAUSAL_CHILD")
        self.assertEqual(result["source_objects_verified"], 15)
        self.assertEqual(result["missing_source_fields"], list(gate.CONTRACT_FIELDS))
        self.assertIsNone(result["economic_command"])
        self.assertFalse(result["raw_117_membership_recovered"])
        self.assertIn("NOT_ECONOMIC_REPLAY_PARITY", result["parent_preservation"])

    def test_diagnostic_does_not_import_engine_or_network_modules(self):
        original = builtins.__import__
        forbidden = {"backend", "requests", "urllib", "http", "socket", "pandas", "numpy", "subprocess"}
        attempted = []

        def guarded(name, *args, **kwargs):
            attempted.append(name)
            if name.split(".")[0] in forbidden:
                self.fail("Offline gate imported " + name)
            return original(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=guarded):
            result = gate.audit(self.base)
        self.assertEqual(result["economic_runs"], 0)
        self.assertEqual(result["market_api_calls"], 0)

    def test_recovered_legacy_enum_does_not_become_an_exit_rule(self):
        raw = (self.base / "inputs/source" / gate.LEGACY_PATH).read_bytes()
        self.assertIn(b'EXIT_LONG = "exit_long"', raw)
        facts = gate.legacy_source_facts(raw)
        self.assertEqual(facts["strategy_actions"], ["add", "enter", "hold"])
        self.assertEqual(facts["decide_intents"], ["ENTER_LONG", "HOLD"])
        self.assertFalse(facts["exit_or_trail_update_action_present"])
        self.assertNotIn("stop", facts["position_state_keys"])
        self.assertIn("cfg.trail_atr_mult", facts["proposed_initial_geometry"]["long_sl"])
        with self.assertRaisesRegex(gate.BindingError, "LEGACY_SOURCE_SHA256"):
            gate.legacy_source_facts(raw.replace(b'action="hold"', b'action="exit"', 1))

    def test_each_missing_contract_field_must_be_explicit_and_cannot_claim_complete(self):
        for field in gate.CONTRACT_FIELDS:
            with self.subTest(field=field, mutation="removed"):
                packet = copy.deepcopy(self.packet)
                del packet["source_contract"][field]
                with self.assertRaisesRegex(gate.BindingError, "SOURCE_CONTRACT_FIELDS_REQUIRED"):
                    gate.validate_packet(packet)
            with self.subTest(field=field, mutation="claimed_complete"):
                packet = copy.deepcopy(self.packet)
                packet["source_contract"][field]["complete"] = True
                with self.assertRaisesRegex(gate.BindingError, "UNSUPPORTED_SOURCE_COMPLETION_CLAIM"):
                    gate.validate_packet(packet)

    def test_complete_checkboxes_do_not_manufacture_a_candidate(self):
        packet = copy.deepcopy(self.packet)
        for item in packet["source_contract"].values():
            item["complete"] = True
            item["evidence"] = "We now have a rule."
        with self.assertRaisesRegex(gate.BindingError, "UNSUPPORTED_SOURCE_COMPLETION_CLAIM"):
            gate.validate_packet(packet)

    def test_gap_requires_bound_provenance_and_actual_explanation(self):
        for replacement, error in (([], "UNBOUND_GAP_PROVENANCE"),
                                   (["unreviewed/source.py@invented"], "UNBOUND_GAP_PROVENANCE")):
            packet = copy.deepcopy(self.packet)
            packet["source_contract"]["activation"]["provenance"] = replacement
            with self.assertRaisesRegex(gate.BindingError, error):
                gate.validate_packet(packet)
        packet = copy.deepcopy(self.packet)
        packet["source_contract"]["activation"]["evidence"] = "  "
        with self.assertRaisesRegex(gate.BindingError, "MISSING_GAP_EVIDENCE"):
            gate.validate_packet(packet)

    def test_no_outcome_or_identity_labels_can_be_execution_features(self):
        for label in ("final_MFE", "Net_R", "month", "symbol", "winner_trade_keys", "loss_outcome",
                      "exit_reason", "trade_key", "PnL", "MAE"):
            with self.subTest(label=label):
                packet = copy.deepcopy(self.packet)
                packet["execution_features"] = [label]
                with self.assertRaisesRegex(gate.BindingError, "OUTCOME_DERIVED_EXECUTION_FEATURE"):
                    gate.validate_packet(packet)
        with self.assertRaisesRegex(gate.BindingError, "NO_EXECUTION_FEATURES_WITHOUT_CHILD"):
            gate.validate_execution_features(["prior_closed_bar_atr"])

    def test_k117_native87_latest240_and_other_timeframes_rejected(self):
        for key, value in (("strategy_id", "K117"), ("completed_trades", 87),
                           ("completed_trades", 240), ("receipt_sha256", "latest-receipt")):
            parent = copy.deepcopy(self.parent)
            parent[key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(gate.BindingError, "PARENT_IDENTITY"):
                gate.validate_identity(self.summary, parent)
        for interval in ("15m", "30m", "1H", None):
            parent = copy.deepcopy(self.parent)
            parent["source"]["interval"] = interval
            with self.subTest(interval=interval), self.assertRaisesRegex(gate.BindingError, "PARENT_TIMEFRAME"):
                gate.validate_identity(self.summary, parent)

    def test_exact_candidate_hash_and_trade_identity_must_match(self):
        for key in ("candidate_sha256", "trade_identity_sha256", "parent_receipt_sha256"):
            summary = copy.deepcopy(self.summary)
            candidate = next(c for c in summary["strategies"]["supertrend_pullback"]["candidates"]
                             if c["candidate_id"] == gate.IDENTITY["candidate_id"])
            candidate[key] = "0" * 64
            with self.subTest(key=key), self.assertRaisesRegex(gate.BindingError, "SUBSET_IDENTITY"):
                gate.validate_identity(summary, self.parent)

    def test_terminal_status_does_not_grant_execution_authority(self):
        for key, value in (("economic_command", "python run_full.py"),
                           ("same_parent_new_exit_candidate_ready", True),
                           ("new_rule_freeze_created", True), ("owner", "C")):
            packet = copy.deepcopy(self.packet)
            packet["owner_handoff"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(gate.BindingError, "TERMINAL_HANDOFF"):
                gate.validate_packet(packet)
        parent = copy.deepcopy(self.parent)
        parent["order_authority"] = "ALLOWED"
        with self.assertRaisesRegex(gate.BindingError, "AUTHORITY"):
            gate.validate_identity(self.summary, parent)

    def test_raw_membership_claim_cannot_be_substituted_for_missing_rows(self):
        packet = copy.deepcopy(self.packet)
        packet["raw_data_gaps"]["saved_117_trade_id_list_in_recovered_packet"] = True
        with self.assertRaisesRegex(gate.BindingError, "RAW_DATA_SCOPE"):
            gate.validate_packet(packet)

    def test_raw_bytes_are_pinned_even_if_parsed_json_is_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "summary.json"
            path.write_bytes((self.base / "inputs/a4_summary.json").read_bytes() + b"\n")
            self.assertEqual(json.loads(path.read_bytes()), self.summary)
            with self.assertRaisesRegex(gate.BindingError, "FILE_SHA256_MISMATCH"):
                gate.load_pinned(path, gate.IDENTITY["summary_file_sha256"])
            with self.assertRaisesRegex(gate.BindingError, "GIT_BLOB_MISMATCH"):
                gate.load_pinned(self.base / "inputs/a4_summary.json", gate.IDENTITY["summary_file_sha256"], "0" * 40)

    def test_source_manifest_cannot_repin_or_omit_an_original(self):
        records = copy.deepcopy(self.packet["source_objects"])
        records[0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(gate.BindingError, "SOURCE_PIN"):
            gate.validate_source_records(records)
        with self.assertRaisesRegex(gate.BindingError, "SOURCE_RECORD_COUNT"):
            gate.validate_source_records(self.packet["source_objects"][:-1])

    def test_altered_immutable_source_is_rejected_without_importing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "source"
            shutil.copytree(self.base / "inputs/source", copied)
            path = copied / gate.LEGACY_PATH
            path.write_bytes(path.read_bytes() + b"\nraise RuntimeError('must never execute')\n")
            with self.assertRaisesRegex(gate.BindingError, "SOURCE_SHA256"):
                gate.audit(self.base, source_root=copied)

    def test_cli_exit_zero_is_terminal_and_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "diagnostic.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gate.main(["--base", str(self.base), "--output", str(output)]), 0)
            raw = output.read_bytes()
            self.assertEqual(json.loads(raw)["status"], gate.STATUS)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gate.main(["--base", str(self.base), "--output", str(output)]), 2)
            self.assertEqual(output.read_bytes(), raw)

    def test_saved_initial_risk_is_directional_for_long_and_short(self):
        for side, direction in (("long", 1), ("short", -1)):
            row = next(row for row in self.parent["trades"] if row["side"] == side)
            risk = review.risk_geometry(row)
            expected = direction * (row["entry"] - row["intent_geometry"]["sl"]) / row["entry"] * 10000
            self.assertGreater(expected, 0)
            self.assertAlmostEqual(risk["initial_risk_bps"], expected)
            self.assertAlmostEqual(risk["net1_initial_risk_R"], row["net_bps"] / expected)
            self.assertAlmostEqual(risk["net2_initial_risk_R"],
                                   (row["gross_bps"] - 2 * row["realized_cost_bps"]) / expected)
            invalid = copy.deepcopy(row)
            invalid["intent_geometry"]["sl"] = row["entry"] + direction
            self.assertEqual(review.risk_geometry(invalid)["state"], "INVALID_NONPOSITIVE_DIRECTIONAL_INITIAL_RISK")

    def test_saved_aggregate_one_omission_requires_unique_match(self):
        # Use saved outcomes solely to test retrospective aggregate ambiguity.
        # No candles or trading implementation are fabricated.
        first = self.parent["trades"][0]
        day = review.utc(first["entry_ts"])[:10]
        second = next(row for row in self.parent["trades"]
                      if review.utc(row["entry_ts"])[:10] == day and row["net_bps"] != first["net_bps"])
        groups = [{"group": day, "trade_count": 2, "net_R": (first["net_bps"] + second["net_bps"]) / 100}]
        child = [{"group": day, "trade_count": 1, "net_R": second["net_bps"] / 100}]
        inferred = review.infer_day_membership([first, second], groups, child)
        self.assertEqual(inferred[review.trade_identity(first)]["membership"], "EXCLUDED")
        self.assertEqual(inferred[review.trade_identity(second)]["membership"], "RETAINED")
        duplicate = copy.deepcopy(first)
        duplicate["intent_sha"] = "ambiguous-aggregate-fixture-only"
        groups[0]["net_R"] = first["net_bps"] * 2 / 100
        child[0]["net_R"] = first["net_bps"] / 100
        ambiguous = review.infer_day_membership([first, duplicate], groups, child)
        self.assertEqual(len(ambiguous), 2)
        self.assertTrue(all(item["membership"] == "UNKNOWN" for item in ambiguous.values()))
        self.assertTrue(all(item["authority"] == "AGGREGATE_INFERRED_MEMBERSHIP/NOT_SOURCE_ADMISSION"
                            for item in list(inferred.values()) + list(ambiguous.values())))

    def test_actual_saved_review_preserves_236_rows_32_of_64_wins_and_5_unresolved(self):
        parent_before, summary_before = copy.deepcopy(self.parent), copy.deepcopy(self.summary)
        files = [self.base / "inputs/parent236.json", self.base / "inputs/a4_summary.json"]
        bytes_before = [path.read_bytes() for path in files]
        result = review.review(self.parent, self.summary)
        self.assertEqual(result["parent"]["T"], 236)
        self.assertEqual(result["parent"]["positive_net_count"], 64)
        self.assertEqual(result["child_summary_only"]["positive_net_count"], 32)
        self.assertEqual(result["retention"]["positive_net_trade_count_pct"], 50)
        self.assertAlmostEqual(result["retention"]["all_trade_count_pct"], 100 * 117 / 236)
        stage = result["signal_entry_exit_stage_audit"]
        self.assertEqual(stage["open_unresolved"], 5)
        self.assertEqual(stage["open_outcomes"], "UNKNOWN_NOT_IMPUTED")
        self.assertEqual(stage["raw_intents"], stage["completed"] + stage["open_unresolved"] + stage["ownership_rejected"])
        self.assertEqual(result["aggregate_membership_inference"]["count_by_membership"],
                         {"EXCLUDED": 47, "RETAINED": 53, "UNKNOWN": 136})
        self.assertLessEqual(result["parent_row_arithmetic_max_error_bps"], review.TOLERANCE_BPS)
        self.assertEqual(review.utc(0), "1970-01-01T00:00:00Z")
        self.assertEqual((self.parent, self.summary), (parent_before, summary_before))
        self.assertEqual([path.read_bytes() for path in files], bytes_before)


if __name__ == "__main__":
    unittest.main()
