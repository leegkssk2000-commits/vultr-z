"""SYNTHETIC_ONLY fixtures: numeric examples are not Z_POLICY/SSOT settings."""
import copy
import unittest
import report_adapter as report


def row(symbol="ETH-USDT", signal=10, qty="2", gross="20", cost="2", mfe="3"):
    signal += report.WINDOW_START_MS
    return {"symbol": symbol, "side": 1, "signal_ts_ms": signal,
            "entry_ts_ms": signal, "exit_ts_ms": signal + 10,
            "outcome_available_ts_ms": signal + 10,
            "quote_currency": "SYNTHETIC_QUOTE", "entry_quantity": qty,
            "quantity_unit": "BASE_ASSET", "base_units_per_contract": "1",
            "entry_price": "100", "entry_notional_quote": str(report.number(qty, "q") * 100),
            "admission_receipt_id": "synthetic-only-admission", "admission_risk_quote": "10",
            "gross_quote": gross, "cost_quote": cost, "mfe_R_analysis_only": mfe}


def run(rows, label="synthetic-control"):
    return {"classification": "ACTUAL_FULL_CHRONOLOGY", "owner": report.OWNER,
            "run_id": label, "identity": report.CURRENT_IDENTITY if label == "synthetic-control" else label,
            "opportunity_stream_complete": True,
            "unresolved": [], "risk_budget_audit_sha256": "4" * 64,
            "contract": {"baseline_commit": report.CURRENT_BASELINE,
                         "baseline_identity": report.CURRENT_IDENTITY,
                         "source_binding_sha256": "1" * 64, "window_binding_sha256": "2" * 64,
                         "cost_binding_sha256": "3" * 64, **copy.deepcopy(report.FIXED_INPUTS),
                         "risk_budget": {"risk_unit": "quote_currency_stop_distance_plus_reserve",
                                         "quote_currency": "SYNTHETIC_QUOTE", "source_ref": "5" * 40,
                                         "source_sha256": "6" * 64, "total_risk_limit_quote": "100",
                                         "directional_risk_limit_quote": {"1": "100", "-1": "100"}}},
            "rows": rows, "ledger_sha256": report.canonical_sha(rows)}


class ReportTests(unittest.TestCase):
    def test_absent_A_runs_are_required_not_economic_result(self):
        got = report.compare_common_total_risk()
        self.assertEqual(got["state"], "REQUIRED_INPUT")
        self.assertIsNone(got["comparison"])
        self.assertFalse(got["new_profit_claim"])

    def test_saved_equal_notional_does_not_redefine_streak(self):
        rows = [{"symbol": "ETH-USDT", "side": 1, "signal_ts_ms": 10,
                 "management_comparison_identity": report.CURRENT_IDENTITY,
                 "gross_bps": 20, "cost_bps": 2, "mfe_R": 3}]
        metrics = {"cost1x": {"MaxLossStreak": 8}, "cost2x": {"MaxLossStreak": 13}}
        got = report.saved_equal_notional(rows, metrics)
        self.assertEqual(got["net1x_trade_bps"], "18")
        self.assertEqual(got["net2x_trade_bps"], "16")
        self.assertEqual(got["authoritative_original_row_metrics"], metrics)
        self.assertFalse(got["account_NAV"])

    def test_uniform_half_size_loss_reduction_is_scale_only(self):
        a = run([row(gross="-20")])
        b = run([row(qty="1", gross="-10", cost="1")], "synthetic-child")
        got = report.compare_common_total_risk(a, b)
        self.assertTrue(got["uniform_quantity_scale_only"])
        self.assertEqual(got["uniform_quantity_scale"], "0.5")
        self.assertFalse(got["alpha_improvement_claim"])
        self.assertEqual(got["totals"]["net1x_quote"]["delta"], "11")

    def test_full_chronology_added_removed_and_winner_loss(self):
        a = run([row(), row("SOL-USDT", 30, gross="-10")])
        b = run([row(qty="1", gross="10", cost="1"), row("LINK-USDT", 50)], "synthetic-child")
        got = report.compare_common_total_risk(a, b)
        self.assertEqual(got["T"], {"control": 2, "candidate": 2, "common": 1, "removed": 1, "added": 1})
        self.assertEqual(got["cohorts_analysis_only"]["large_winners"]["worsened_quote_T"], 1)
        self.assertFalse(got["uniform_quantity_scale_only"])
        self.assertTrue(got["totals"]["net2x_quote"]["attribution_reconciled"])

    def test_mismatched_shared_budget_rejected(self):
        a = run([row()]); b = copy.deepcopy(a)
        b["contract"]["risk_budget"]["total_risk_limit_quote"] = "50"
        with self.assertRaisesRegex(ValueError, "MATCHED_SOURCE"):
            report.compare_common_total_risk(a, b)

    def test_filtered_paired_or_hypothetical_rows_rejected(self):
        for kind in ("PAIRED_ONLY", "FILTERED_SAVED_LEDGER"):
            a = run([row()]); a["classification"] = kind
            with self.assertRaisesRegex(ValueError, "FULL_CHRONOLOGY"):
                report.compare_common_total_risk(a, run([row()]))
        a = run([dict(row(), hypothetical=True)])
        with self.assertRaisesRegex(ValueError, "PROXY_ROW"):
            report.compare_common_total_risk(a, run([row()]))

    def test_missing_quantity_is_required_and_units_cannot_be_assumed(self):
        r = row(); del r["entry_quantity"]
        got = report.compare_common_total_risk(run([r]), run([row()]))
        self.assertEqual(got["state"], "REQUIRED_INPUT")
        self.assertEqual(got["required_inputs"], ["entry_quantity"])
        r = row(); r["quantity_unit"] = "TRADE_BPS"
        with self.assertRaisesRegex(ValueError, "QUANTITY_UNIT"):
            report.compare_common_total_risk(run([r]), run([row()]))

    def test_duplicate_tampered_and_nonfinite_ledgers_fail(self):
        a = run([row(), row()])
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            report.compare_common_total_risk(a, run([row()]))
        a = run([row()]); a["rows"][0]["gross_quote"] = "99"
        with self.assertRaisesRegex(ValueError, "LEDGER_SHA"):
            report.compare_common_total_risk(a, run([row()]))
        with self.assertRaisesRegex(ValueError, "INVALID_NUMBER"):
            report.compare_common_total_risk(run([row(gross="NaN")]), run([row()]))

    def test_original_128_or_old126_baseline_cannot_be_mixed(self):
        a = run([row()]); a["contract"]["baseline_commit"] = "308bd2deb7acaaacf1adb582206e78262d72c9d1"
        with self.assertRaisesRegex(ValueError, "CURRENT126"):
            report.compare_common_total_risk(a, run([row()]))

    def test_contract_quantity_and_notional_validation(self):
        r = row(); r.update(entry_quantity="20", quantity_unit="CONTRACTS", base_units_per_contract="0.1")
        got = report.compare_common_total_risk(run([r]), run([row()]))
        self.assertTrue(got["uniform_quantity_scale_only"])
        r["entry_notional_quote"] = "2"
        with self.assertRaisesRegex(ValueError, "QUANTITY_NOTIONAL"):
            report.compare_common_total_risk(run([r]), run([row()]))

    def test_outside_window_entry_or_outcome_rejected(self):
        for name, value in (("entry_ts_ms", report.WINDOW_START_MS - 1),
                            ("outcome_available_ts_ms", report.WINDOW_END_MS + 1)):
            r = row()
            r[name] = value
            if name == "entry_ts_ms":
                r["signal_ts_ms"] = value
            with self.assertRaisesRegex(ValueError, "OUTSIDE_BOUND_WINDOW"):
                report.compare_common_total_risk(run([r]), run([row()]))

    def test_money_beyond_default_decimal_precision_reconciles_exactly(self):
        gross = "123456789012345678901234567890.12345678901234567890"
        a = run([row(gross=gross, cost="0.00000000000000000001"),
                 row("SOL-USDT", 30, gross="-123456789012345678901234567890", cost="0")])
        b = run(list(reversed(copy.deepcopy(a["rows"]))), "synthetic-child")
        got = report.compare_common_total_risk(a, b)
        self.assertEqual(got["totals"]["net1x_quote"]["control"], "0.12345678901234567889")
        self.assertEqual(got["totals"]["net1x_quote"]["candidate"], "0.12345678901234567889")
        self.assertEqual(report.number(got["totals"]["net1x_quote"]["delta"], "delta"), 0)
        self.assertTrue(got["totals"]["net1x_quote"]["attribution_reconciled"])


if __name__ == "__main__":
    unittest.main()
