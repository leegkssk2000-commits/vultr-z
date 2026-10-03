"""Synthetic arithmetic regressions; no historical replay or strategy imports."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import kp_saved_evidence_closeout_v1 as audit


def fixture(side: int = 1, partial: bool = False, fallback: bool = False) -> dict:
    entry, risk, cost = 100.0, 2.0, 14.0
    atr = risk / 1.2 if fallback else 2.0
    stop = entry + side if fallback else entry - side * risk
    exit_price = entry + side * 3
    gross = (0.1 * 400 + 0.9 * 300) if partial else 300.0
    signal = {"identity": audit.CANDIDATE, "symbol": "BTC-USDT", "side": side,
              "timeframe_min": 30, "take_profit_r": None, "partial_take_profit_r": 2.0,
              "partial_fraction": 0.1, "max_hold_bars": 25, "stop_price": stop,
              "meta": {"entry_cost_gate": {"atr_price": atr, "min_ratio": 4.5},
                       "frozen_cost_bps": cost, "fallback_stop_atr_mult": 1.2, "be_arm_r": 1.0}}
    return {"identity": audit.CANDIDATE, "symbol": "BTC-USDT", "side": side, "signal": signal,
            "timeframe_min": 30, "entry_prices": {"BTC-USDT": entry}, "exit_prices": {"BTC-USDT": exit_price},
            "entry_ts_ms": 2000, "signal_ts_ms": 1000, "exit_ts_ms": 3000, "outcome_available_ts_ms": 3000,
            "execution_profile": "UTC_NEXT_OPEN_STOP_FIRST_GAPS_UNRESOLVED_V2",
            "mfe_mae_semantics": "AFTER_STOP_CHECK_CONSERVATIVE_NO_INTRABAR_PATH", "order_authority": "BLOCKED",
            "partition": "rolling", "window_label": "rolling_1", "mfe_R": 2.5 if partial else 1.5,
            "cost_bps": cost, "gross_bps": gross, "net_bps": gross - cost, "reason": "MAX_HOLD_NEXT_OPEN"}


class AmountAuditTests(unittest.TestCase):
    def test_long_without_partial(self):
        result = audit.reconstruct_amount(fixture())
        self.assertAlmostEqual(result["gross_bps_model_derived"], 300)
        self.assertFalse(result["partial_inferred_from_saved_model_state"])

    def test_long_partial(self):
        result = audit.reconstruct_amount(fixture(partial=True))
        self.assertAlmostEqual(result["partial_gross_bps_model_derived"], 40)
        self.assertAlmostEqual(result["terminal_gross_bps_model_derived"], 270)
        self.assertIsNone(result["partial_timestamp_ms"])
        self.assertFalse(result["partial_original_event_recovered"])

    def test_short_partial(self):
        result = audit.reconstruct_amount(fixture(side=-1, partial=True))
        self.assertAlmostEqual(result["gross_bps_model_derived"], 310)
        self.assertAlmostEqual(result["partial_price_model_derived"], 96)

    def test_gap_fallback_stop(self):
        result = audit.reconstruct_amount(fixture(partial=True, fallback=True))
        self.assertTrue(result["entry_fallback_applied"])
        self.assertAlmostEqual(result["gross_bps_model_derived"], 310)

    def test_exact_two_r_is_partial(self):
        row = fixture(partial=True)
        row["mfe_R"] = 2.0
        self.assertTrue(audit.reconstruct_amount(row)["partial_inferred_from_saved_model_state"])

    def test_no_backsolving_from_gross(self):
        row = fixture(partial=True)
        row["gross_bps"] += 1
        row["net_bps"] += 1
        with self.assertRaisesRegex(ValueError, "GROSS_AMOUNT_MISMATCH"):
            audit.reconstruct_amount(row)

    def test_missing_partial_flag_cannot_silently_pass(self):
        row = fixture(partial=True)
        row["mfe_R"] = 1.99
        with self.assertRaisesRegex(ValueError, "GROSS_AMOUNT_MISMATCH"):
            audit.reconstruct_amount(row)

    def test_cost_adjusted_breakeven_flip(self):
        row = fixture()
        row.update(mfe_R=1.1, reason="STOP_FIRST", gross_bps=16.0, net_bps=2.0)
        row["exit_prices"]["BTC-USDT"] = 100.16
        result = audit.reconstruct_amount(row)
        self.assertTrue(result["fee_be_plus2_price_match"])
        self.assertTrue(result["net_positive_1x_to_nonpositive_2x"])
        self.assertEqual(result["net_2x_bps"], -12)
        self.assertFalse(result["cost_multiplier_is_leverage"])

    def test_partial_then_fee_be_terminal_price_is_counted_separately(self):
        row = fixture(partial=True)
        row["signal"]["stop_price"] = 99.5
        row["exit_prices"]["BTC-USDT"] = 100.16
        row.update(reason="STOP_FIRST", gross_bps=24.4, net_bps=10.4)
        result = audit.reconstruct_amount(row)
        self.assertTrue(result["fee_be_plus2_price_match"])
        self.assertTrue(result["partial_inferred_from_saved_model_state"])
        self.assertTrue(result["net_positive_1x_to_nonpositive_2x"])
        self.assertNotAlmostEqual(result["net_1x_bps"], 2.0)
        report = audit.analyze([row])
        self.assertEqual(report["cost_flip"]["fee_be_plus2_matches"], 1)
        self.assertEqual(report["cost_flip"]["fee_be_plus2_without_partial_matches"], 0)

    def test_wrong_identity_and_tf(self):
        for key, value in (("identity", "legacy_keltner"), ("timeframe_min", 60)):
            row = fixture(); row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit.reconstruct_amount(row)

    def test_changed_partial_policy_rejected(self):
        row = fixture(partial=True); row["signal"]["partial_fraction"] = .2
        with self.assertRaisesRegex(ValueError, "FROZEN_LIFECYCLE_CHANGED"):
            audit.reconstruct_amount(row)

    def test_cost_source_mismatch(self):
        row = fixture(); row["cost_bps"] = 15
        with self.assertRaisesRegex(ValueError, "COST_BINDING_CHANGED"):
            audit.reconstruct_amount(row)

    def test_nonfinite_rejected(self):
        row = fixture(); row["mfe_R"] = float("nan")
        with self.assertRaises(ValueError): audit.reconstruct_amount(row)
        with self.assertRaises(ValueError): audit.strict_load(b'{"x":Infinity}')

    def test_duplicate_json_and_trades_rejected(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON_KEY"):
            audit.strict_load(b'{"x":1,"x":2}')
        with self.assertRaisesRegex(ValueError, "DUPLICATE_TRADE"):
            audit.analyze([fixture(), fixture()])

    def test_timestamp_order_and_type(self):
        for value in (500, True):
            row = fixture(); row["entry_ts_ms"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.reconstruct_amount(row)

    def test_validation_not_counted_as_rolling(self):
        row = fixture(); row.update(partition="validation", window_label="validation")
        result = audit.analyze([row])
        self.assertEqual(result["saved_rows"], 1)
        self.assertEqual(result["rolling_rows"], 0)
        self.assertIsNone(result["g4_formal_pass"])
        self.assertFalse(result["g5_execution_started"])
        self.assertIsNone(result["account_dd"])

    def test_wrong_engine_semantics(self):
        row = fixture(); row["mfe_mae_semantics"] = "BEFORE_STOP_CHECK"
        with self.assertRaisesRegex(ValueError, "WRONG_MFE_SEMANTICS"):
            audit.reconstruct_amount(row)

    def test_corrupt_pinned_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / audit.LEDGER
            path.parent.mkdir(parents=True); path.write_bytes(b"not the saved ledger")
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_CHANGED"):
                audit.pinned(Path(tmp), audit.LEDGER)

    def test_cost_scenario_is_not_new_strategy_or_event_recovery(self):
        result = audit.analyze([fixture(partial=True)])
        self.assertEqual(result["new_market_full_runs"], 0)
        self.assertEqual(result["signal_generation_calls"], 0)
        self.assertEqual(result["raw_partial_event_rows_recovered"], 0)
        self.assertTrue(result["post_outcome_cohorts"]["reached_2R_partial"]["selection_is_post_outcome"])
        with self.assertRaises(ValueError): audit.metrics([fixture()], 20)


if __name__ == "__main__":
    unittest.main()
