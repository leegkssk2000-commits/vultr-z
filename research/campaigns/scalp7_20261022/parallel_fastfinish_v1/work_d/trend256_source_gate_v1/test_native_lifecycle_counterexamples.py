#!/usr/bin/env python3
"""Tests of archived source counterexamples, not economic or repaired strategy tests.

Run with --native-source PATH or WORK_D_NATIVE_SOURCE=PATH. No downloads/imports
of the native module are performed, and no actual trade ledger is loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("native_lifecycle_counterexamples.py")
SPEC = importlib.util.spec_from_file_location("work_d_native_counterexamples", MODULE_PATH)
DIAG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DIAG
SPEC.loader.exec_module(DIAG)
NATIVE_SOURCE = Path(os.environ["WORK_D_NATIVE_SOURCE"]) if os.environ.get("WORK_D_NATIVE_SOURCE") else None


class ArchivedNativeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if NATIVE_SOURCE is None:
            raise RuntimeError("Supply --native-source PATH or WORK_D_NATIVE_SOURCE; no implicit native import/download")
        cls.source = NATIVE_SOURCE
        cls.before_hash = hashlib.sha256(cls.source.read_bytes()).hexdigest()
        cls.report = DIAG.run_diagnostics(cls.source)
        cls.checks = cls.report["checks"]

    @classmethod
    def tearDownClass(cls):
        if hashlib.sha256(cls.source.read_bytes()).hexdigest() != cls.before_hash:
            raise AssertionError("Native source changed during read-only diagnostics")

    def test_exact_sha_and_transform_only_provenance(self):
        provenance = self.report["provenance"]
        self.assertEqual(provenance["native_source_sha256"], DIAG.NATIVE_SHA256)
        self.assertEqual(provenance["compiled_native_functions"], ["transform"])
        self.assertFalse(provenance["native_module_imported"])
        self.assertFalse(provenance["native_main_or_build_parent_executed"])
        self.assertTrue(all(provenance["source_lines"].values()))
        self.assertGreater(provenance["transform_line_end"], provenance["transform_line_start"])

    def test_adverse_delayed_entry_makes_above_bar_sl_fill(self):
        observed = self.checks["long_adverse_entry_beyond_initial_stop"]["observed"]
        self.assertEqual(observed["entry"], 80)
        self.assertEqual(observed["exit"], 85)
        self.assertGreater(observed["exit"], observed["exit_bar_high"])
        self.assertEqual(observed["reason"], "SL")
        self.assertAlmostEqual(observed["gross_bps"], 625)
        self.assertAlmostEqual(observed["net_bps"], 607.75)

    def test_later_gap_uses_stop_even_when_outside_bar(self):
        observed = self.checks["later_bar_gap_through_stop"]["observed"]
        self.assertEqual(observed["entry"], 100)
        self.assertEqual(observed["exit"], 85)
        self.assertEqual(observed["exit_ts"], DIAG.BASE_MS + 3 * DIAG.HOUR_MS)
        self.assertAlmostEqual(observed["gross_bps"], -1500)
        bar = self.report["synthetic_bars"]["later_gap"][3]
        self.assertGreater(observed["exit"], bar["high"])

    def test_timeout_close_price_is_stamped_at_bar_open(self):
        observed = self.checks["timeout_close_value_with_bar_open_timestamp"]["observed"]
        bar = self.report["synthetic_bars"]["timeout"][-1]
        self.assertEqual(observed["exit"], bar["close"])
        self.assertEqual(observed["exit_ts"], bar["ts_ms"])
        self.assertEqual(observed["timestamp_lead_ms_relative_to_synthetic_bar_close"], 3_600_000)

    def test_short_history_is_closed_before_full_timeout(self):
        check = self.checks["short_available_horizon_forced_to_timeout"]
        self.assertEqual(check["expected_native_behavior"]["configured_timeout_bars"], 48)
        self.assertEqual(check["expected_native_behavior"]["available_bar_index_distance_after_delayed_entry"], 2)
        self.assertEqual(check["observed"]["not_closed_after_delay_count"], 0)
        self.assertEqual(check["observed"]["reason"], "TIMEOUT")

    def test_changed_entry_exit_copy_parent_aggregate_cost(self):
        observed = self.checks["parent_cost_copied_after_changed_entry_and_exit"]["observed"]
        self.assertEqual(observed["new_entry"], 102)
        self.assertEqual(observed["new_exit"], 110)
        self.assertEqual(observed["parent_cost_bps"], observed["new_cost_bps"])
        self.assertEqual(observed["new_entry_ts"] - observed["parent_entry_ts"], DIAG.HOUR_MS)
        self.assertAlmostEqual(observed["new_net_bps"], observed["new_gross_bps"] - 17.25)

    def test_open_rejected_records_remain_unreplayed_and_management_annotations_inert(self):
        state = self.checks["inherited_open_and_rejected_state_not_replayed"]["observed"]
        self.assertTrue(all(state["fields_equal_parent"].values()))
        self.assertEqual(state["synthetic_fetch_symbols"], ["BTC-USDT"])
        management = self.checks["partial_trailing_annotations_not_executed_by_transform"]["observed"]
        self.assertTrue(all(management["execution_fields_unchanged"].values()))
        self.assertEqual(management["management_field_literals_present"], [])

    def test_synthetic_only_and_no_multiple_trade_policy_claim(self):
        for key in ("actual_price_rows_used", "market_api_calls", "new_economic_full_runs",
                    "archived_trades_repriced", "orders"):
            self.assertEqual(self.report[key], 0)
        self.assertEqual(len(self.checks), 7)
        self.assertEqual(self.report["authority"]["order_authority"], "BLOCKED")
        function, _ = DIAG.extract_transform(self.source)
        parent = DIAG.parent_fixture()
        parent["trades"].append(dict(parent["trades"][0]))
        with self.assertRaisesRegex(ValueError, "NO_MULTI_TRADE_POLICY_AUTHORITY"):
            DIAG.invoke(function, self.report["synthetic_bars"]["timeout"], parent)

    def test_changed_native_bytes_are_rejected_before_ast_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp) / "source.py"
            changed.write_bytes(self.source.read_bytes() + b"\nraise RuntimeError('MUST_NOT_EXECUTE')\n")
            with self.assertRaisesRegex(ValueError, "NATIVE_SOURCE_SHA256_MISMATCH"):
                DIAG.run_diagnostics(changed)

    def test_optional_output_is_exclusive_and_json_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "counterexamples.json"
            self.assertEqual(DIAG.main(["--native-source", str(self.source), "--output", str(output)]), 0)
            raw = output.read_bytes()
            saved = json.loads(raw)
            self.assertEqual(saved, self.report)
            with self.assertRaises(FileExistsError):
                DIAG.main(["--native-source", str(self.source), "--output", str(output)])
            self.assertEqual(output.read_bytes(), raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--native-source", type=Path)
    options, rest = parser.parse_known_args()
    if options.native_source is not None:
        NATIVE_SOURCE = options.native_source
    unittest.main(argv=[sys.argv[0], *rest])
