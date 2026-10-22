"""Offline synthetic arithmetic tests plus the complete pinned receipts when present.

Set TREND256_RECEIPT and optionally TREND123_RECEIPT to original artifact files.
The normal local evidence/ layout is found automatically. No network/replay.
"""
import ast
import copy
import hashlib
import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import trend256_attribution as subject


def row(name, gross, cost=0, entry=0, exit=1):
    return {"symbol": name, "signal_ts": entry, "entry_ts": entry,
            "exit_ts": exit, "side": "long", "intent_sha": name,
            "gross_bps": gross, "realized_cost_bps": cost,
            "net_bps": str(Decimal(str(gross)) - Decimal(str(cost)))}


def fixture_path(variable, relative):
    explicit = os.environ.get(variable)
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise AssertionError(variable + " does not name a file")
        return path
    archived_name = {"TREND256_RECEIPT": "long_only_prospective.json",
                     "TREND123_RECEIPT": "liquid6_child.json"}.get(variable)
    if archived_name:
        archived = Path(__file__).resolve().parent / "inputs" / archived_name
        if archived.is_file():
            return archived
    for root in (Path.cwd(), *Path(__file__).resolve().parents):
        path = root / relative
        if path.is_file():
            return path
    return None


class ArithmeticTests(unittest.TestCase):
    def test_cost_2x_is_not_cost_3x(self):
        r = row("X", 30, 8)
        self.assertEqual(subject.net(r, 1), Decimal(22))
        self.assertEqual(subject.net(r, 2), Decimal(14))
        self.assertNotEqual(subject.net(r, 2), Decimal(r["net_bps"]) - 2 * Decimal(8))
        with self.assertRaises(subject.InputError):
            subject.net(r, 3)

    def test_complete_256_synthetic_rows_are_all_counted(self):
        rows = [row(str(i), 20 if i < 64 else -2, 1, i, i + 1) for i in range(256)]
        before = copy.deepcopy(rows)
        one, two = subject.metrics(rows, 1), subject.metrics(rows, 2)
        self.assertEqual(one["trades"], 256)
        self.assertEqual((one["wins"], one["losses"]), (64, 192))
        self.assertEqual(one["net_sum_trade_bps"], Decimal(640))
        self.assertEqual(two["net_sum_trade_bps"], Decimal(384))
        self.assertEqual(one["win_rate"], Decimal("0.25"))
        self.assertEqual(rows, before)

    def test_original_and_close_order_have_different_drawdown(self):
        rows = [row("A", -10, exit=1), row("B", 20, exit=3), row("C", -10, exit=2)]
        stats = subject.metrics(rows, 1)["chronology"]
        self.assertEqual(stats["original_row_order"]["maximum_drawdown_sum_trade_bps"], 10)
        self.assertEqual(stats["exit_bar_order_individual"]["maximum_drawdown_sum_trade_bps"], 20)
        self.assertEqual(stats["original_row_order"]["maximum_consecutive_negative_observations"], 1)
        self.assertEqual(stats["exit_bar_order_individual"]["maximum_consecutive_negative_observations"], 2)
        self.assertFalse(stats["portfolio_NAV"])

    def test_simultaneous_outcomes_are_not_an_intrabar_order(self):
        rows = [row("A", -10, exit=1), row("B", 10, exit=1)]
        stats = subject.metrics(rows, 1)["chronology"]
        self.assertEqual(stats["exit_bar_order_individual"]["maximum_drawdown_sum_trade_bps"], 10)
        self.assertEqual(stats["exit_bar_cohort_net"]["maximum_drawdown_sum_trade_bps"], 0)
        self.assertEqual(stats["exit_bar_cohort_net"]["cohort_count"], 1)
        self.assertEqual(stats["exit_bar_cohort_net"]["maximum_consecutive_negative_observations"], 0)
        self.assertFalse(stats["exit_bar_cohort_net"]["within_bar_drawdown_observable"])
        self.assertEqual(subject.metrics(list(reversed(rows)), 1)["chronology"]["exit_bar_cohort_net"], stats["exit_bar_cohort_net"])

    def test_flat_resets_streak_and_no_losses_has_null_pf(self):
        stats = subject.path_statistics([Decimal(-1), Decimal(0), Decimal(-1)])
        self.assertEqual(stats["maximum_consecutive_negative_observations"], 1)
        self.assertIsNone(subject.metrics([row("A", 1)], 1)["profit_factor"])
        empty = subject.metrics([], 1)
        self.assertEqual(empty["trades"], 0)
        self.assertIsNone(empty["net_per_trade_bps"])

    def test_saved_decimal_precision_is_not_rounded_to_default_28(self):
        rows = [row(str(i), "1.123456789012345678901234567890123456789", 0, i, i + 1) for i in range(256)]
        self.assertEqual(subject.metrics(rows, 1)["gross_sum_trade_bps"], Decimal("287.604937987160493798716049379871604937984"))

    def test_nonfinite_and_boolean_numbers_are_rejected(self):
        for value in (True, False, "NaN", "Infinity", "-Infinity"):
            with self.assertRaises(subject.InputError):
                subject.decimal(value)

    def test_retrospective_top_winner_contribution_is_not_filtered_run(self):
        rows = [row("A", 20), row("B", 10), row("C", -25)]
        result = subject.concentration(rows, 1)
        self.assertTrue(result["not_candidate_deletion"])
        self.assertEqual(result["top_winners"][0]["descriptive_leave_out_net_trade_bps"], -15)
        self.assertEqual(result["top_winners"][0]["share_of_signed_total_net"], 4)
        self.assertEqual(len(rows), 3)


class CompleteReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = fixture_path("TREND256_RECEIPT", "evidence/trend_d/long256/long_only_prospective.json")
        if cls.path is None:
            raise unittest.SkipTest("Original 256-row artifact absent; set TREND256_RECEIPT for integration tests")
        cls.receipt = subject.load_verified(cls.path)
        cls.reports = subject.build_attribution(cls.receipt)
        cls.summary = cls.reports["SUMMARY.json"]

    def test_raw_and_semantic_binding_match_native_signer(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), subject.PINS["long256"]["raw_sha256"])
        unsigned = {k: v for k, v in self.receipt.items() if k != "receipt_sha256"}
        self.assertEqual(subject.stable(unsigned), subject.PINS["long256"]["receipt_sha256"])
        source = fixture_path("TREND256_SIGNING_SOURCE", "evidence/trend_d/source/a1_trend_rider_exact_parent_repair_batch_v1.py")
        if source is not None:
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), subject.SIGNING_SOURCE["file_sha256"])
            parsed = ast.parse(source.read_text())
            function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == "stable")
            namespace = {"hashlib": hashlib, "json": json, "Any": object}
            # Only this pure native hashing function; no imports or evaluator body.
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
            self.assertEqual(namespace["stable"](unsigned), self.receipt["receipt_sha256"])

    def test_all_256_and_all_winners_preserved_unchanged(self):
        before = copy.deepcopy(self.receipt)
        output = subject.build_attribution(self.receipt)
        audit = output["ROWS_AUDIT.json"]
        self.assertEqual(len(audit), 256)
        self.assertEqual([r["saved_row"] for r in audit], self.receipt["trades"])
        self.assertEqual(self.receipt, before)
        self.assertEqual(len(self.summary["all_closed_rows_preserved"]["all_1x_winner_identity_sha256s"]), 64)
        self.assertEqual(len(self.summary["all_closed_rows_preserved"]["all_2x_winner_identity_sha256s"]), 63)
        audit[0]["saved_row"]["intent_geometry"]["sl"] = -1
        self.assertEqual(self.receipt, before)

    def test_actual_totals_cost_crossing_and_largest_winner_fragility(self):
        one, two = self.summary["cost_1x"], self.summary["cost_2x_posthoc"]
        self.assertEqual(one["net_sum_trade_bps"], Decimal("6146.9109585705522999"))
        self.assertEqual(two["net_sum_trade_bps"], Decimal("1461.1031437385846069"))
        self.assertEqual(two["cost_sum_trade_bps"], one["cost_sum_trade_bps"] * 2)
        self.assertEqual((one["wins"], two["wins"]), (64, 63))
        crossings = self.summary["cost_crossings"]
        self.assertEqual(len(crossings["gross_positive_net_1x_nonpositive"]), 1)
        self.assertEqual(len(crossings["net_1x_positive_net_2x_nonpositive"]), 1)
        top = self.summary["concentration_2x_posthoc"]["top_winners"][0]
        self.assertEqual(top["descriptive_leave_out_net_trade_bps"], Decimal("-1861.2724153752602991"))

    def test_october_59_is_exit_month_not_entry_month(self):
        months = self.reports["MONTHLY_OUTCOMES.json"]
        entry = {r["group"]: r for r in months["entry_month_utc"]}
        close = {r["group"]: r for r in months["exit_bar_month_utc"]}
        self.assertEqual(entry["2026-10"]["cost_1x"]["trades"], 53)
        self.assertEqual(close["2026-10"]["cost_1x"]["trades"], 59)
        self.assertEqual(close["2026-10"]["cost_1x"]["net_sum_trade_bps"], Decimal("-3999.7998973202735932"))
        for key in ("entry_month_utc", "exit_bar_month_utc"):
            self.assertEqual(sum(r["cost_1x"]["trades"] for r in months[key]), 256)
        for key in ("entry_day_utc", "exit_bar_day_utc"):
            groups = self.reports["DAILY_OUTCOMES.json"][key]
            self.assertEqual(sum(r["cost_1x"]["trades"] for r in groups), 256)

    def test_actual_chronologies_have_explicit_trade_vs_cohort_units(self):
        chronology = self.summary["cost_1x"]["chronology"]
        self.assertEqual(chronology["original_row_order"]["maximum_consecutive_negative_observations"], 33)
        self.assertEqual(chronology["exit_bar_order_individual"]["maximum_consecutive_negative_observations"], 40)
        self.assertEqual(chronology["exit_bar_cohort_net"]["maximum_consecutive_negative_observations"], 24)
        self.assertEqual(chronology["exit_bar_cohort_net"]["cohort_count"], 156)
        for key in ("original_row_order", "exit_bar_order_individual", "exit_bar_cohort_net"):
            self.assertEqual(chronology[key]["terminal_sum_trade_bps"], self.summary["cost_1x"]["net_sum_trade_bps"])

    def test_self_signed_modified_identity_is_rejected(self):
        for mutation in (lambda r: r["trades"].pop(),
                         lambda r: r["trades"][0].update({"exit_ts": r["trades"][0]["exit_ts"] + 1}),
                         lambda r: r.update({"cost_authority_sha256": "different"})):
            changed = copy.deepcopy(self.receipt)
            mutation(changed)
            changed["receipt_sha256"] = subject.stable({k: v for k, v in changed.items() if k != "receipt_sha256"})
            with self.assertRaisesRegex(subject.InputError, "RECEIPT_IDENTITY_MISMATCH"):
                subject.build_attribution(changed)

    def test_reformatted_raw_file_is_rejected_even_if_semantics_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            altered = Path(tmp) / "receipt.json"
            altered.write_text(json.dumps(self.receipt))
            with self.assertRaisesRegex(subject.InputError, "RAW_FILE_IDENTITY_MISMATCH"):
                subject.load_verified(altered)

    def test_open_and_rejected_rows_are_explicitly_inherited_parent_scope(self):
        inherited = self.summary["inherited_parent_scope_not_closed_long_subset"]
        self.assertEqual(inherited["native_policy_ownership"]["admitted_completed_trade_count"], 301)
        self.assertEqual(inherited["open_intents_count"], 1)
        self.assertEqual(inherited["rejected_intents_count"], 1889)
        self.assertTrue(inherited["open_intents_hash_matches_native"])
        self.assertTrue(inherited["rejected_intents_hash_matches_native"])
        self.assertEqual(self.summary["cost_1x"]["trades"], 256)

    def test_missing_causal_features_and_recovery_are_not_invented(self):
        self.assertEqual(self.summary["candidate_state"], "NO_CAUSAL_CHILD")
        self.assertEqual(self.summary["candidate_count"], 0)
        self.assertFalse(self.summary["source_feature_gate"]["group_labels_are_runtime_inputs"])
        for row_audit in self.reports["ROWS_AUDIT.json"]:
            labels = row_audit["retrospective_outcomes_not_execution_features"]
            for field in ("MFE", "MAE", "recovery_winner", "intrabar_fill_ts", "outcome_available_ts"):
                self.assertIsNone(labels[field])

    def test_four_entry_below_stop_rows_remain_in_saved_ledger(self):
        ids = self.summary["entry_below_frozen_long_stop"]["row_identity_sha256s"]
        self.assertEqual(len(ids), 4)
        audit = self.reports["ROWS_AUDIT.json"]
        affected = [r for r in audit if r["row_identity_sha256"] in ids]
        self.assertTrue(all(r["saved_row"]["reason"] == "SL" for r in affected))
        self.assertEqual(sum(r["retrospective_outcomes_not_execution_features"]["winner_1x"] for r in affected), 3)
        self.assertEqual(len(audit), 256)

    def test_exclusive_output_and_source_files_unchanged(self):
        before = self.path.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new_output"
            subject.run(self.path, output)
            saved = {p.name: p.read_bytes() for p in output.iterdir()}
            self.assertEqual(set(saved), {"SUMMARY.json", "ROWS_AUDIT.json", "DAILY_OUTCOMES.json", "MONTHLY_OUTCOMES.json"})
            self.assertEqual(len(json.loads(saved["ROWS_AUDIT.json"])), 256)
            with self.assertRaises(FileExistsError):
                subject.run(self.path, output)
            self.assertEqual(saved, {p.name: p.read_bytes() for p in output.iterdir()})
        self.assertEqual(self.path.read_bytes(), before)

    def test_liquid_lineage_and_scaled_units_are_separate(self):
        path = fixture_path("TREND123_RECEIPT", "evidence/trend_d/liquid123/child.json")
        if path is None:
            self.skipTest("Original separate 123-row artifact absent")
        receipt = subject.load_verified(path, "liquid123")
        note = subject.liquid_identity_note(receipt)
        self.assertFalse(note["merged_with_long256"])
        self.assertFalse(note["overlap_or_blend_reconstructed"])
        self.assertEqual(note["input_binding"]["completed_trades"], 123)
        self.assertEqual(note["portfolio_risk_scales_in_rows"], ["0.3333333333333333"])
        self.assertIn("instrument_gross_bps", receipt["trades"][0])
        with self.assertRaises(subject.InputError):
            subject.build_attribution(receipt)


if __name__ == "__main__":
    unittest.main()
