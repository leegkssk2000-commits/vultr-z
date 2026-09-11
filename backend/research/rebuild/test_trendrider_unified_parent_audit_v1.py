from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_unified_parent_audit_v1 as audit


def row(signal=1000, net=5, intent="a"):
    return {"symbol": "TEST-USDT", "signal_ts": signal, "entry_ts": signal + 1,
            "exit_ts": signal + 20, "side": "long", "intent_sha": intent,
            "entry": 10, "exit": 11, "reason": "TIMEOUT", "gross_bps": net + 1,
            "net_bps": net, "realized_cost_bps": 1}


def receipt(rows):
    doc = {"trades": rows, "execution_authority": "NONE", "order_authority": "BLOCKED",
           "live_trade_authority": "BLOCKED", "promotion_authority": False,
           "selection_authority": False}
    doc["receipt_sha256"] = audit.digest(doc)
    return doc


class ParentAuditTests(unittest.TestCase):
    def test_receipt_tamper_cannot_keep_original_digest(self):
        doc = receipt([row()])
        expected = doc["receipt_sha256"]
        doc["trades"][0]["net_bps"] = 999
        self.assertFalse(audit.verify_receipt(doc, expected, 1)["receipt_hash"])

    def test_duplicate_lane_intent_cannot_create_second_opportunity(self):
        doc = receipt([row(intent="parent"), row(intent="child")])
        checks = audit.verify_receipt(doc, doc["receipt_sha256"], 2)
        self.assertTrue(checks["receipt_hash"])
        self.assertFalse(checks["underlying_unique"])

    def test_overlap_ignores_lane_hash_but_rejects_economic_change(self):
        p, b = row(intent="parent"), row(intent="broad")
        self.assertEqual(audit.overlap_parity(audit.index_rows([p]), audit.index_rows([b])), [])
        b["realized_cost_bps"] = 2
        found = audit.overlap_parity(audit.index_rows([p]), audit.index_rows([b]))
        self.assertEqual(found[0]["different_fields"], ["realized_cost_bps"])

    def test_unknown_source_rejected_before_any_read(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(ValueError, "UNKNOWN_SOURCE_FORBIDDEN"):
                audit.read_authorized(Path("."), "research/data/prospective/fresh.json")

    def test_changed_authorized_file_rejected_before_json_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = audit.SOURCES["primary"][0]
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_text("not valid JSON")
            with self.assertRaisesRegex(ValueError, "FROZEN_SOURCE_FILE_HASH_MISMATCH"):
                audit.read_authorized(root, relative)

    def test_missing_features_hash_pointer_is_not_a_snapshot(self):
        self.assertFalse(all(audit.structural_snapshot_checks(None, None).values()))
        self.assertFalse(all(audit.structural_snapshot_checks({"feature_sha": "a" * 64}, None).values()))

    def test_future_observation_and_future_prefix_fail_independently(self):
        snapshot = dict(session_state="APAC", st_gap_state="EXPANDING", chase_state="COOLING_OR_FLAT",
                        atr_state="EXPANDING", geometry_balance="ST_GAP_GE_CHASE", directional_persistence_state=True)
        snapshot.update(observed_at_ms=1000, input_max_ts_ms=1000, source_sha256="a" * 64)
        # A structurally populated fixture still cannot prove native clock or feature values.
        self.assertFalse(all(audit.structural_snapshot_checks(snapshot, 1000).values()))
        future = deepcopy(snapshot)
        future["observed_at_ms"] = 1001
        self.assertFalse(audit.structural_snapshot_checks(future, 1000)["observable_by_decision"])
        future = deepcopy(snapshot)
        future["input_max_ts_ms"] = 1001
        self.assertFalse(audit.structural_snapshot_checks(future, 1000)["input_prefix_causal"])

    def test_outcome_column_injected_into_feature_snapshot_rejected(self):
        snapshot = {key: "STATE" for key in audit.FEATURE_FIELDS}
        snapshot.update(observed_at_ms=1000, input_max_ts_ms=1000, source_sha256="a" * 64, net_bps=999)
        self.assertFalse(audit.structural_snapshot_checks(snapshot, 1000)["only_decision_columns"])

    def test_holding_overlap_half_open_clock(self):
        first, touching, overlap = row(1000), row(1019), row(1001)
        self.assertEqual(first["exit_ts"], touching["entry_ts"])
        disjoint = audit.occupancy_diagnostic([first, touching])
        self.assertEqual(disjoint["same_symbol_overlapping_pairs"], 0)
        overlapping = audit.occupancy_diagnostic([first, overlap])
        self.assertEqual(overlapping["same_symbol_overlapping_pairs"], 1)
        self.assertEqual(overlapping["maximum_simultaneous_saved_trades_by_symbol"]["TEST-USDT"], 2)
        self.assertFalse(overlapping["shared_book_execution_proven"])

    def test_saved_metric_drawdown_preserves_receipt_order(self):
        values = [row(3000, 10), row(1000, -8), row(2000, 10)]
        self.assertEqual(audit.saved_metrics(values)["max_drawdown_bps"], 8)
        self.assertEqual(audit.saved_metrics(values)["net_pnl_bps"], 12)

    def test_real_frozen_receipts_pass_membership_but_cannot_authorize_economics(self):
        root = Path(__file__).resolve().parents[3]
        docs = audit.build_report(root)
        report = docs["PARENT_AUDIT.json"]
        self.assertEqual(report["saved_membership_parity"], "PASS")
        self.assertEqual(report["state"], "BLOCKED_PARENT_PARITY")
        self.assertFalse(report["economic_execution_authorized"])
        self.assertEqual(report["counts"], {"primary": 16, "broad": 30, "overlap": 15,
                                           "primary_only": 1, "broad_only": 15, "unique_union": 31})
        self.assertEqual(len(docs["OUTCOME_ANSWERS.json"]["rows"]), 46)
        self.assertEqual(len(docs["OPPORTUNITIES.json"]["rows"]), 31)
        self.assertTrue(all(value == 0 for value in report["executions"].values()))
        for document in ("OPPORTUNITIES.json", "DECISION_FEATURES.json"):
            for item in docs[document]["rows"]:
                self.assertFalse(set(audit.ANSWER_FIELDS) & set(item))
        for item in docs["DECISION_FEATURES.json"]["rows"]:
            self.assertTrue(item["decision_time_not_proven"])
            self.assertIsNone(item["decision_ts"])


if __name__ == "__main__":
    unittest.main()
