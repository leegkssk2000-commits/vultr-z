"""Finite synthetic artifact/clock tests; no imported strategy or economic run."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit_saved_contract as audit


MODEL = '''raise RuntimeError("THIS_SOURCE_MUST_NEVER_EXECUTE")
def run_stage():
    end_ms = longleg["effective_closed_at"]
def new_short_leg():
    for i in range(s, s + 25):
        pass
def entry_loss_streak_circuit():
    return [x for x in completed if x["end_ms"] + H < at]
def build_candidates():
    candidate["instrument_source_cost_bps"] = float(r["realized_cost_bps"]) / origin_scale
def metrics_stage():
    return month(int(x["signal_ts"]))
'''
FILTER = '''P = Path(__file__).resolve().parent
def run():
    a = P / "RESULT.json"
    b = P / "ROBUSTNESS.json"
    c = x["instrument_source_cost_bps"]
'''


class SavedContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = {role: self.root / name for role, name in {
            "freeze": "FREEZE.json", "result": "RESULT.json", "robustness": "ROBUSTNESS.json",
            "traces_gzip": "TRACES.json.gz", "model_code": "model.py", "filter_code": "filter.py"}.items()}
        self.expected = {}
        self.freeze = {"schema": "zel.trendrider.unified_one_owner_causal_rescue.v1",
                       "stages": [{"id": "S3_CONFIRM_REVERSAL_SHORT", "short_limit_hours": 24}]}
        self.write("freeze", self.freeze)
        self.result = {"schema": "zel.trendrider.unified_one_owner_causal_rescue.result.v1",
                       "freeze_sha256": self.expected["freeze"],
                       "source_inputs": {"counts": {"EXACT_SIGNAL_DEDUPED": 97,
                           "DELAYED_INVALID_NATIVE_STOP_GEOMETRY": 4, "LIQUID_SELECTED": 119,
                           "DELAYED_SELECTED": 148}},
                       "source_timing": {"historical_real_received_at": "UNKNOWN"},
                       "stage_economics": {}}
        self.traces = {"schema": "zel.trendrider.unified.causal_exit_trace.v1",
                       "freeze_sha256": self.expected["freeze"], "not_canonical_trade_ledger": True,
                       "live_order_authority": "BLOCKED", "stages": {}}
        h = audit.HOUR_MS
        for i in range(5):
            name = "S" + str(i)
            legs = [{"opportunity_key": "candidate-0", "symbol": "BTC-USDT", "side": "long",
                     "entry_ts": 100*h, "exit_bar_ts": 101*h, "effective_closed_at": 102*h,
                     "reason": "SL"}]
            if i >= 3:
                legs.append({"opportunity_key": "candidate-0", "symbol": "BTC-USDT", "side": "short",
                             "entry_ts": 102*h, "exit_bar_ts": 126*h, "effective_closed_at": 127*h,
                             "reason": "SHORT_TIME24_CLOSED", "short_held_bar_count": 25})
            self.traces["stages"][name] = {
                "accepted": [{"key": "candidate-0", "symbol": "BTC-USDT", "legs": legs,
                              "end_ms": legs[-1]["effective_closed_at"]}],
                "rejected": [{"key": "candidate-" + str(j)} for j in range(1, 267)]}
            self.result["stage_economics"][name] = {
                "accepted_opportunities": 1, "admissions": {"rejected": 266},
                "reverse_short_legs": int(i >= 3)}
        self.write("result", self.result)
        self.robustness = {"schema": "zel.trendrider.unified_rescue.robustness.v1",
                           "source_freeze_sha256": self.expected["freeze"],
                           "source_result_sha256": self.expected["result"],
                           "fully_new_unseen_OOS": False, "realized_broker_fee_funding": False}
        self.write("robustness", self.robustness)
        self.write("traces_gzip", self.traces)
        self.write("model_code", MODEL)
        self.write("filter_code", FILTER)

    def write(self, role, value):
        if role.endswith("code"):
            raw = value.encode()
        else:
            raw = (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()
            if role == "traces_gzip":
                raw = gzip.compress(raw, mtime=0)
        self.paths[role].write_bytes(raw)
        self.expected[role] = hashlib.sha256(raw).hexdigest()

    def run_audit(self):
        return audit.audit_paths(**self.paths, expected_sha256=self.expected)

    def test_counts_clocks_and_static_contract_faults_without_execution(self):
        result = self.run_audit()
        self.assertEqual(result["artifact_integrity"], "PASS_HASH_SCHEMA_LINEAGE_AND_COUNTS")
        self.assertEqual(result["contract_conformance"], "FAIL")
        self.assertEqual(result["stage_counts"]["S4"]["short_limit_violations"], 1)
        short = result["frozen_24h_violations"][-1]
        self.assertEqual(short["stored_held_bar_count"], 25)
        self.assertEqual(short["effective_elapsed_ms"], 90_000_000)
        self.assertEqual(short["effective_elapsed_hours"], 25)
        self.assertTrue(result["static_code_findings"]["loss_circuit_extra_hour_on_effective_close"])
        self.assertTrue(result["static_code_findings"]["filter_baseline_uses_own_directory"])
        self.assertTrue(result["static_code_findings"]["filter_source_cost_is_realized_field_not_entry_asof_evidence"])
        self.assertEqual(result["activity"]["strategy_imports"], 0)
        self.assertFalse(result["source_admission"]["new_economic_allowed"])
        self.assertEqual(result["new_performance"]["status"], "NOT_RUN")
        self.assertTrue(all(v is None for k, v in result["new_performance"].items() if k != "status"))

    def test_pin_drift_blocks_before_source_parse_or_import(self):
        self.paths["model_code"].write_text("raise AssertionError('never execute or trust drift')")
        with self.assertRaisesRegex(audit.AuditError, "SOURCE_PIN_MISMATCH:model_code"):
            self.run_audit()

    def test_rehashed_wrong_lineage_is_not_accepted(self):
        self.traces["freeze_sha256"] = "0" * 64
        self.write("traces_gzip", self.traces)
        with self.assertRaisesRegex(audit.AuditError, "FREEZE_LINEAGE_MISMATCH:traces"):
            self.run_audit()

    def test_duplicate_or_changed_source_partition_rejected(self):
        self.traces["stages"]["S4"]["rejected"][0]["key"] = "candidate-0"
        self.write("traces_gzip", self.traces)
        with self.assertRaisesRegex(audit.AuditError, "STAGE_PARTITION_OR_DUPLICATE_CHANGED:S4"):
            self.run_audit()

    def test_frozen97_dedup_cannot_be_redeclared(self):
        self.result["source_inputs"]["counts"]["EXACT_SIGNAL_DEDUPED"] = 96
        self.write("result", self.result)
        self.robustness["source_result_sha256"] = self.expected["result"]
        self.write("robustness", self.robustness)
        with self.assertRaisesRegex(audit.AuditError, "FROZEN_SOURCE_COUNT_CHANGED:EXACT_SIGNAL_DEDUPED"):
            self.run_audit()

    def test_reversal_cannot_precede_long_close(self):
        self.traces["stages"]["S4"]["accepted"][0]["legs"][1]["entry_ts"] = 101*audit.HOUR_MS
        self.write("traces_gzip", self.traces)
        with self.assertRaisesRegex(audit.AuditError, "SHORT_ENTERED_BEFORE_LONG_CLOSED"):
            self.run_audit()

    def test_reported_hold_count_cannot_hide_25th_bar(self):
        self.traces["stages"]["S4"]["accepted"][0]["legs"][1]["short_held_bar_count"] = 24
        self.write("traces_gzip", self.traces)
        with self.assertRaisesRegex(audit.AuditError, "SHORT_HELD_COUNT_CLOCK_MISMATCH"):
            self.run_audit()

    def test_clean_synthetic_clocks_never_authorize_economics(self):
        for name in ("S3", "S4"):
            opportunity = self.traces["stages"][name]["accepted"][0]
            short = opportunity["legs"][1]
            short["short_held_bar_count"] = 24
            short["exit_bar_ts"] -= audit.HOUR_MS
            short["effective_closed_at"] -= audit.HOUR_MS
            opportunity["end_ms"] = short["effective_closed_at"]
        self.write("traces_gzip", self.traces)
        self.write("model_code", MODEL.replace('x["end_ms"] + H < at', 'x["end_ms"] < at').replace("s + 25", "s + 24"))
        result = self.run_audit()
        self.assertEqual(result["contract_conformance"], "NO_CHECKED_VIOLATION")
        self.assertEqual(result["frozen_24h_violations"], [])
        self.assertFalse(result["source_admission"]["new_economic_allowed"])
        self.assertEqual(result["new_performance"]["status"], "NOT_RUN")

    def test_cli_does_not_accept_synthetic_pins_as_real_source(self):
        with self.assertRaisesRegex(audit.AuditError, "SOURCE_PIN_MISMATCH:freeze"):
            audit.main(["--source-dir", str(self.root)])

    def test_cli_cannot_overwrite_existing_output(self):
        output = self.root / "immutable.json"
        output.write_text("preserve\n")
        with patch.object(audit, "audit_paths", return_value={"new_performance": audit.not_run()}):
            with self.assertRaises(FileExistsError):
                audit.main(["--source-dir", str(self.root), "--output", str(output)])
        self.assertEqual(output.read_text(), "preserve\n")


if __name__ == "__main__":
    unittest.main()
