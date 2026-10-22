"""Synthetic algebra plus optional exact117 saved-ledger checks; no price replay."""
from decimal import Decimal
from pathlib import Path
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import protection_accounting as accounting
import saved_ledger_audit as audit

BASELINE = Path(os.environ.get("K117_BASELINE_DIR", str(Path(__file__).resolve().parents[6] / "evidence/k117/baseline")))


def inputs(**changes):
    result = dict(entry_price="100", side=1, stop_price="100.16", remaining_fraction="1",
                  realized_gross_bps="0", frozen_reference_cost_bps="14", extra_carry_bps="0",
                  unit=accounting.UNIT)
    result.update(changes)
    return result


class AccountingTests(unittest.TestCase):
    def test_long_short_existing_cost_aware_BE(self):
        for side, stop in ((1, "100.16"), (-1, "99.84")):
            result = accounting.protection_at_price(**inputs(side=side, stop_price=stop))
            self.assertEqual(Decimal(result["net1x_bps"]), 2)
            self.assertTrue(result["not_a_fill_or_guaranteed_floor"])

    def test_partial_realized_amount_uses_original_notional(self):
        result = accounting.protection_at_price(**inputs(realized_gross_bps="20", remaining_fraction="0.9"))
        self.assertEqual(Decimal(result["remaining_terminal_gross_bps"]), Decimal("14.4"))
        self.assertEqual(Decimal(result["net1x_bps"]), Decimal("20.4"))
        self.assertFalse(result["candidate"])

    def test_inverse_with_partial_is_algebra_only_not_stop_change(self):
        for side in (-1, 1):
            args = inputs(side=side, realized_gross_bps="20", remaining_fraction="0.5", extra_carry_bps="1")
            del args["stop_price"]
            inverse = accounting.inverse_floor_price(**args, target_net_bps="2")
            self.assertIsNone(inverse["stop_update"])
            result = accounting.protection_at_price(**args, stop_price=inverse["price"])
            self.assertEqual(Decimal(result["net1x_bps"]), 2)
            self.assertEqual(inverse["execution_feasibility"], "NOT_ESTABLISHED")

    def test_stress_is_posthoc_and_not_an_execution_input(self):
        result = accounting.stress_after_outcome("16", "14", "0.9", multiplier="2")
        self.assertEqual(Decimal(result["net_bps"]), Decimal("-13.8"))
        self.assertEqual(result["classification"], "POSTHOC_STRESS_NOT_EXECUTION_INPUT")
        with self.assertRaises(TypeError):
            accounting.protection_at_price(**inputs(), multiplier=2)

    def test_fraction_unit_nonfinite_and_negative_cost_checks(self):
        for changes in ({"remaining_fraction": "1.1"}, {"remaining_fraction": "-0.1"},
                        {"unit": "USDT"}, {"side": True}, {"entry_price": "0"},
                        {"realized_gross_bps": "NaN"}, {"extra_carry_bps": "-1"}):
            with self.assertRaises(ValueError):
                accounting.protection_at_price(**inputs(**changes))

    def test_zero_remaining_has_no_inverse_price(self):
        result = accounting.protection_at_price(**inputs(remaining_fraction="0", realized_gross_bps="30"))
        self.assertEqual(Decimal(result["net1x_bps"]), 16)
        args = inputs(remaining_fraction="0"); del args["stop_price"]
        with self.assertRaisesRegex(ValueError, "NO_REMAINING"):
            accounting.inverse_floor_price(**args, target_net_bps="2")

    def test_amount_conversion_requires_explicit_actual_quantity_unit(self):
        common = dict(trade_bps="20", entry_price="100", quote_currency="SYNTHETIC_QUOTE")
        base = accounting.quote_amount(**common, initial_quantity="2", quantity_unit="BASE_ASSET", base_units_per_contract="1")
        contracts = accounting.quote_amount(**common, initial_quantity="20", quantity_unit="CONTRACTS", base_units_per_contract="0.1")
        for field in ("initial_notional_quote", "amount_quote"):
            self.assertEqual(Decimal(base[field]), Decimal(contracts[field]))
        self.assertEqual(base["quote_currency"], contracts["quote_currency"])
        self.assertEqual(Decimal(base["amount_quote"]), Decimal("0.4"))
        self.assertFalse(base["account_NAV_claim"])
        with self.assertRaises(ValueError):
            accounting.quote_amount(**common, initial_quantity="1", quantity_unit="REMAINING_FRACTION", base_units_per_contract="1")


@unittest.skipUnless((BASELINE / "ROWS.json.gz").exists(), "set K117_BASELINE_DIR to exact immutable input directory")
class SavedLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload, cls.summary, cls.freeze = audit.checked_inputs(BASELINE)
        cls.evidence = audit.build_evidence(cls.payload, cls.summary)

    def test_exact117_and_all71_winners_exported_without_new_trace_claim(self):
        result = self.evidence
        self.assertEqual(len(result["rows"]), 117)
        self.assertEqual(result["all117_coverage"]["win1x"], 71)
        self.assertEqual(len(result["winner_counterexample_scope"]["large36_keys"]), 36)
        self.assertEqual(len(result["winner_counterexample_scope"]["ordinary35_keys"]), 35)
        self.assertFalse(result["event_trace_executed"])
        self.assertTrue(all(r["required_native_trace"]["BE_first_arm_ts_ms"] is None for r in result["rows"]))
        self.assertEqual(result["K126_large34_preservation_quoted_from_summary_not_recomputed"], self.summary["cohorts"]["large_winners"])

    def test_28_split_25_BE_24_two_bps_one_partial_algebra_only(self):
        result = self.evidence["cost_cross_28"]
        self.assertEqual((result["T"], result["BE_terminal_match_T"], result["approximately_plus2_T"]), (28, 25, 24))
        inference = result["one_partial_algebra_inference"]
        self.assertEqual(len(inference), 1)
        self.assertTrue(inference[0]["matches_saved_gross_with_float_tolerance"])
        self.assertFalse(inference[0]["partial_fill_time_or_event_observed"])
        self.assertEqual(sorted(r["reason"] for r in result["remaining_three"]), ["HG_FROZEN_5BAR_MFE_SCRATCH", "HG_FROZEN_5BAR_MFE_SCRATCH", "MAX_HOLD_NEXT_OPEN"])

    def test_extra_carry_is_separate_and_stress_does_not_alter_entry_cost(self):
        rows = self.evidence["rows"]
        extra = [r for r in rows if r["cost_separation"]["extra_carry_scenario_bps"] > 0]
        self.assertEqual(len(extra), 4)
        self.assertAlmostEqual(sum(r["cost_separation"]["extra_carry_scenario_bps"] for r in extra), 5.4)
        self.assertTrue(all(r["entry_known"]["frozen_reference_cost_bps"] == r["cost_separation"]["raw_engine_reference_bps"] for r in rows))

    def test_wrong_cardinality_future_feature_and_duplicate_fail(self):
        for mutation in ("drop", "future", "duplicate"):
            payload = copy.deepcopy(self.payload)
            if mutation == "drop": payload["trades"].pop()
            elif mutation == "future": payload["trades"][0]["signal"]["meta"]["feature_available_ts_ms"] = payload["trades"][0]["entry_ts_ms"] + 1
            else: payload["trades"][1] = copy.deepcopy(payload["trades"][0])
            with self.assertRaises(ValueError):
                audit.build_evidence(payload, self.summary)

    def test_hash_change_rejected_and_output_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            for name in audit.CONTRACT["input_sha256"]:
                shutil.copyfile(BASELINE / name, temporary / name)
            with (temporary / "SUMMARY.json").open("ab") as handle:
                handle.write(b" ")
            with self.assertRaisesRegex(ValueError, "PINNED_INPUT_CHANGED"):
                audit.checked_inputs(temporary)
            out = temporary / "evidence.json"
            command = [sys.executable, str(audit.HERE / "saved_ledger_audit.py"), "--baseline-dir", str(BASELINE), "--output", str(out)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = out.read_bytes()
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(out.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
