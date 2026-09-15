"""Causal-boundary and evidence-integrity tests; no economic strategy runs."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.research.rebuild import economic7_walkforward_v1 as wf

DAY = wf.DAY_MS
BASE = 1_704_067_200_000  # 2024-01-01 UTC
RULE = "a" * 64
CODE = "b" * 40
COST = "c" * 64


class WalkForwardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "calendar.json"

    def calendar(
        self, exposure: str = "OBSERVED_DEVELOPMENT", **changes: Any
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "candidate_id": "FROZEN_TEST",
            "rule_hash": RULE,
            "code_sha": CODE,
            "source": "repo:unit_fixture",
            "exposure_manifest": {
                "source": "repo:inspection_receipt",
                "sha256": "d" * 64,
                "inspected_at_ms": BASE - DAY,
                "inspection_inventory_complete": True,
                "intervals": [
                    {
                        "start_ms": BASE,
                        "end_ms": BASE + 100 * DAY,
                        "exposure": exposure,
                        "receipt": "repo:inspection_receipt#fixture",
                    }
                ],
            },
            "cost_authority": {
                "source": "repo:cost_fixture",
                "sha256": COST,
                "equation": "gross_minus_fee_minus_slippage_minus_funding",
            },
            "windows": [
                {
                    "window_id": "W001",
                    "train_start_ms": BASE,
                    "train_end_ms": BASE + 10 * DAY,
                    "oos_start_ms": BASE + 12 * DAY,
                    "oos_end_ms": BASE + 42 * DAY,
                    "embargo_ms": 2 * DAY,
                    "purge_ms": DAY,
                }
            ],
        }
        params.update(changes)
        with patch.object(wf.time, "time_ns", return_value=(BASE - DAY) * 1_000_000):
            return wf.preregister_calendar(self.path, **params)

    def row(
        self,
        identity: str = "A",
        *,
        entry: int = 20,
        exit_day: int = 21,
        net: float = 90.0,
        symbol: str = "BTC-USDT",
        strategy: str = "test",
    ) -> dict[str, Any]:
        gross = net + 3.0
        return {
            "trade_id": identity,
            "strategy": strategy,
            "symbol": symbol,
            "source": "repo:test_trade",
            "candidate_id": "FROZEN_TEST",
            "rule_hash": RULE,
            "code_sha": CODE,
            "cost_authority_sha256": COST,
            "instrument_kind": "SINGLE_LEG_LINEAR_USDT",
            "status": "CLOSED",
            "side": "LONG",
            "entry_ts_ms": BASE + entry * DAY,
            "exit_ts_ms": BASE + exit_day * DAY,
            "outcome_available_at_ms": BASE + exit_day * DAY,
            "entry_price": 100.0,
            "exit_price": 100.0 * (1 + gross / 10_000),
            "gross_bps": gross,
            "fee_bps": 2.0,
            "slippage_bps": 1.0,
            "funding_bps": 0.0,
            "pnl_weight": 1.0,
            "net_bps": net,
        }

    def pair_row(
        self,
        identity: str = "PAIR",
        *,
        entry: int = 20,
        exit_day: int = 21,
    ) -> dict[str, Any]:
        long_entry, short_entry = 100.0, 200.0
        long_exit, short_exit = 101.0, 198.0
        gross = 10_000 * (
            0.5 * (long_exit / long_entry - 1)
            + 0.5 * (short_entry - short_exit) / short_entry
        )
        return {
            "trade_id": identity,
            "strategy": "mr_v1",
            "source": "repo:test_pair_trade",
            "candidate_id": "FROZEN_TEST",
            "rule_hash": RULE,
            "code_sha": CODE,
            "cost_authority_sha256": COST,
            "instrument_kind": "TWO_LEG_MARKET_NEUTRAL_USDT",
            "status": "CLOSED",
            "side": "MARKET_NEUTRAL",
            "long_symbol": "DOGE-USDT",
            "short_symbol": "ETH-USDT",
            "entry_ts_ms": BASE + entry * DAY,
            "exit_ts_ms": BASE + exit_day * DAY,
            "outcome_available_at_ms": BASE + exit_day * DAY,
            "long_entry_price": long_entry,
            "short_entry_price": short_entry,
            "long_exit_price": long_exit,
            "short_exit_price": short_exit,
            "long_weight": 0.5,
            "short_weight": 0.5,
            "gross_bps": gross,
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
            "funding_bps": 0.0,
            "pnl_weight": 1.0,
            "net_bps": gross - 6.0,
        }

    def evaluate(
        self,
        calendar: dict[str, Any],
        records: list[dict[str, Any]],
        *,
        end_day: int = 100,
        complete: bool = True,
        thresholds: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        manifest = {
            "records_sha256": wf.digest(records),
            "source": "repo:producer_receipt",
            "complete": complete,
            "start_ms": BASE,
            "end_ms": BASE + end_day * DAY,
            "record_count": len(records),
            "candidate_id": "FROZEN_TEST",
            "rule_hash": RULE,
            "code_sha": CODE,
        }
        return wf.evaluate_ledger(
            calendar,
            records,
            evaluated_at_ms=BASE + 101 * DAY,
            ledger_manifest=manifest,
            thresholds=thresholds,
        )

    def test_registration_is_hash_bound_and_exclusive(self) -> None:
        calendar = self.calendar()
        self.assertEqual(json.loads(self.path.read_text()), calendar)
        with self.assertRaises(FileExistsError):
            self.calendar()
        calendar["windows"][0]["oos_end_ms"] += DAY
        result = self.evaluate(calendar, [self.row()])
        self.assertEqual(result["state"], "HOLD")
        self.assertIn("calendar hash/schema mismatch", result["errors"])

    def test_train_uses_closed_labels_before_purge_and_oos_has_no_overlap(self) -> None:
        calendar = self.calendar()
        rows = [
            self.row("TRAIN", entry=2, exit_day=9),
            self.row("LEAK", entry=3, exit_day=15),
            self.row("PURGE", entry=8, exit_day=10),
            self.row("BOUNDARY", entry=11, exit_day=13),
            self.row("OOS", entry=12, exit_day=13),
            self.row("LATER", entry=40, exit_day=45),
        ]
        window = self.evaluate(calendar, rows)["windows"][0]
        self.assertEqual(window["train_eligible_ids"], ["TRAIN"])
        self.assertEqual(set(window["train_purged_ids"]), {"LEAK", "PURGE"})
        self.assertEqual(window["oos_closed_ids"], ["OOS"])
        self.assertEqual(window["oos_censored_ids"], ["LATER"])
        self.assertEqual(set(window["boundary_overlap_ids"]), {"LEAK", "BOUNDARY"})
        self.assertEqual(window["state"], "HOLD")

    def test_calendar_denominator_costs_drawdown_and_concentration(self) -> None:
        calendar = self.calendar()
        rows = [
            self.row("A", entry=20, exit_day=21, net=90),
            self.row("B", entry=21, exit_day=22, net=-20, symbol="ETH-USDT"),
            self.row("C", entry=22, exit_day=23, net=30, symbol="ETH-USDT"),
            self.row("D", entry=23, exit_day=24, net=-10),
        ]
        report = self.evaluate(calendar, rows)
        metric = report["metrics"]
        self.assertEqual(metric["calendar_days"], 30)
        self.assertAlmostEqual(metric["T_per_day"], 4 / 30)
        self.assertEqual(metric["WR"], 0.5)
        self.assertEqual(metric["avg_win_bps"], 60)
        self.assertEqual(metric["avg_loss_bps"], -15)
        self.assertEqual(metric["payoff"], 4)
        self.assertEqual(metric["PF"], 4)
        self.assertEqual(metric["net_bps"], 90)
        self.assertEqual(metric["cost_bps_per_T"], 3)
        self.assertEqual(metric["DD_bps"], 20)
        self.assertEqual(metric["EdgeDensity_bps_per_day"], 3)
        self.assertEqual(metric["positive_month_ratio"], 0.5)
        self.assertEqual(metric["monthly"]["2024-02"]["T"], 0)
        self.assertEqual(metric["single_winner_share_of_winning_bps"], 0.75)
        self.assertEqual(metric["net_without_best_trade_bps"], 0)
        self.assertIn("SINGLE_TRADE_DEPENDENCE", report["promotion_blockers"])
        self.assertEqual(report["promotion_authority"], "BLOCKED")

    def test_observed_180d_never_becomes_fresh(self) -> None:
        calendar = self.calendar()
        report = self.evaluate(calendar, [self.row()])
        self.assertEqual(report["windows"][0]["exposure"], "HISTORICAL_DEVELOPMENT")
        self.assertEqual(report["fresh_closed_T"], 0)
        self.assertIn(
            "DEVELOPMENT_OR_UNKNOWN_HISTORY_IS_NOT_FRESH_OOS",
            report["promotion_blockers"],
        )

    def test_old_data_without_complete_inspection_is_unknown(self) -> None:
        calendar = self.calendar("UNTOUCHED_AT_REGISTRATION")
        calendar["exposure_manifest"]["inspection_inventory_complete"] = False
        calendar["calendar_sha256"] = wf.digest(
            {k: v for k, v in calendar.items() if k != "calendar_sha256"}
        )
        report = self.evaluate(calendar, [self.row()])
        self.assertEqual(report["windows"][0]["exposure"], "UNKNOWN_HOLD")
        self.assertIsNone(report["metrics"])

    def test_observed_overlap_overrides_untouched_declaration(self) -> None:
        calendar = self.calendar("UNTOUCHED_AT_REGISTRATION")
        calendar["exposure_manifest"]["intervals"].append(
            {
                "start_ms": BASE + 20 * DAY,
                "end_ms": BASE + 21 * DAY,
                "exposure": "OBSERVED_DEVELOPMENT",
                "receipt": "repo:known180d",
            }
        )
        calendar["calendar_sha256"] = wf.digest(
            {k: v for k, v in calendar.items() if k != "calendar_sha256"}
        )
        self.assertEqual(
            self.evaluate(calendar, [self.row()])["windows"][0]["exposure"],
            "HISTORICAL_DEVELOPMENT",
        )

    def test_fresh_registration_cannot_be_backdated(self) -> None:
        calendar = self.calendar("FRESH_FORWARD")
        calendar["written_at_ms"] = BASE + 20 * DAY
        calendar["calendar_sha256"] = wf.digest(
            {k: v for k, v in calendar.items() if k != "calendar_sha256"}
        )
        self.assertEqual(
            self.evaluate(calendar, [self.row()])["windows"][0]["exposure"],
            "UNKNOWN_HOLD",
        )

    def test_valid_fresh_remains_promotion_blocked(self) -> None:
        report = self.evaluate(self.calendar("FRESH_FORWARD"), [self.row()])
        self.assertEqual(report["fresh_closed_T"], 1)
        self.assertEqual(report["promotion_authority"], "BLOCKED")

    def test_market_neutral_two_leg_trade_is_cost_checked(self) -> None:
        report = self.evaluate(self.calendar(), [self.pair_row()])
        self.assertEqual(report["invalid_record_count"], 0)
        metric = report["metrics"]
        self.assertIsNotNone(metric)
        self.assertEqual(metric["T"], 1)
        self.assertAlmostEqual(metric["net_bps"], 94.0)
        self.assertAlmostEqual(metric["symbol_net_bps"]["DOGE-USDT|ETH-USDT"], 94.0)
        self.assertEqual(metric["cost_bps_per_T"], 6.0)

    def test_market_neutral_two_leg_integrity_failures_hold(self) -> None:
        calendar = self.calendar()
        mutations = [
            ("gross_bps", 1.0),
            ("long_weight", 0.7),
            ("short_symbol", "DOGE-USDT"),
            ("side", "LONG"),
            ("long_exit_price", 0.0),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                row = self.pair_row()
                row[field] = value
                report = self.evaluate(calendar, [row])
                self.assertEqual(report["state"], "HOLD")
                self.assertEqual(report["invalid_record_count"], 1)

    def test_missing_cost_or_tampered_gross_holds_entire_result(self) -> None:
        calendar = self.calendar()
        for field, value in (
            ("funding_bps", None),
            ("fee_bps", None),
            ("slippage_bps", None),
            ("gross_bps", 1.0),
            ("net_bps", 99.0),
            ("entry_price", 0.0),
            ("code_sha", "e" * 40),
            ("instrument_kind", "PAIR"),
        ):
            with self.subTest(field=field):
                row = self.row()
                row[field] = value
                report = self.evaluate(calendar, [row])
                self.assertEqual(report["state"], "HOLD")
                self.assertIsNone(report["metrics"])
                self.assertEqual(report["invalid_record_count"], 1)

    def test_delayed_outcome_is_not_a_train_label(self) -> None:
        calendar = self.calendar()
        delayed = self.row("DELAYED", entry=2, exit_day=8)
        delayed["outcome_available_at_ms"] = BASE + 10 * DAY
        result = self.evaluate(calendar, [delayed, self.row()])
        self.assertEqual(result["windows"][0]["train_eligible_ids"], [])
        self.assertEqual(result["windows"][0]["train_purged_ids"], ["DELAYED"])

    def test_carry_in_exposure_cannot_report_complete_portfolio(self) -> None:
        calendar = self.calendar()
        rows = [self.row("CARRY", entry=11, exit_day=15), self.row("NEW")]
        result = self.evaluate(calendar, rows)
        self.assertEqual(result["state"], "HOLD")
        self.assertEqual(
            result["metrics"]["coverage_status"], "PURGED_BOUNDARY_SUBSET_NOT_PORTFOLIO"
        )
        self.assertIn(
            "CARRY_IN_EXPOSURE_EXCLUDED_FROM_PURGED_DIAGNOSTICS",
            result["windows"][0]["issues"],
        )

    def test_zero_risk_record_cannot_inflate_trade_frequency(self) -> None:
        calendar = self.calendar()
        row = self.row(net=-3)
        row["pnl_weight"] = 0.0
        self.assertIsNone(self.evaluate(calendar, [row])["metrics"])

    def test_future_unavailable_or_missing_outcome_holds(self) -> None:
        calendar = self.calendar()
        for available in (None, BASE + 20 * DAY, BASE + 102 * DAY):
            row = self.row()
            row["outcome_available_at_ms"] = available
            self.assertIsNone(self.evaluate(calendar, [row])["metrics"])

    def test_short_and_risk_weight_are_cost_checked(self) -> None:
        calendar = self.calendar()
        row = self.row()
        row.update(
            side="SHORT", exit_price=98.0, pnl_weight=0.5, gross_bps=100.0, net_bps=97.0
        )
        self.assertEqual(self.evaluate(calendar, [row])["metrics"]["net_bps"], 97)

    def test_open_rows_have_no_invented_close_or_pnl(self) -> None:
        calendar = self.calendar()
        row = self.row()
        row.update(status="OPEN", exit_ts_ms=None, exit_price=None)
        for field in ("gross_bps", "fee_bps", "slippage_bps", "funding_bps", "net_bps"):
            del row[field]
        report = self.evaluate(calendar, [row])
        self.assertEqual(report["state"], "HOLD")
        self.assertEqual(report["metrics"]["T"], 0)
        self.assertIsNone(report["metrics"]["net_bps_per_T"])
        self.assertEqual(report["windows"][0]["oos_censored_ids"], ["A"])

    def test_duplicate_trade_and_incomplete_coverage_are_holds(self) -> None:
        calendar = self.calendar()
        row = self.row()
        duplicate = self.evaluate(calendar, [row, copy.deepcopy(row)])
        self.assertIsNone(duplicate["metrics"])
        self.assertTrue(any("duplicate" in e for e in duplicate["errors"]))
        self.assertIsNone(self.evaluate(calendar, [row], complete=False)["metrics"])
        self.assertIsNone(self.evaluate(calendar, [row], end_day=30)["metrics"])

    def test_simultaneous_exit_drawdown_does_not_depend_on_row_order(self) -> None:
        calendar = self.calendar()
        rows = [
            self.row("A", exit_day=21, net=-30),
            self.row("B", exit_day=21, net=50),
            self.row("C", exit_day=22, net=-10),
        ]
        first = self.evaluate(calendar, rows)["metrics"]
        second = self.evaluate(calendar, list(reversed(rows)))["metrics"]
        self.assertEqual(first, second)
        self.assertEqual(first["DD_bps"], 10)
        self.assertTrue(first["loss_streak_is_upper_bound_due_to_simultaneous_exits"])
        self.assertEqual(first["max_loss_streak"], 2)

    def test_thresholds_require_explicit_source_and_do_not_grant_authority(
        self,
    ) -> None:
        calendar = self.calendar()
        gates = [
            {
                "metric": "PF",
                "operator": ">=",
                "limit": 1.25,
                "unit": "ratio",
                "source": "repo:SSOT",
                "source_sha256": "e" * 64,
            },
            {"metric": "net_bps_per_T", "operator": ">=", "limit": 8, "unit": "bps/T"},
        ]
        rows = [self.row("WIN", net=30), self.row("LOSS", net=-10)]
        report = self.evaluate(calendar, rows, thresholds=gates)
        self.assertEqual([g["verdict"] for g in report["gates"]], ["PASS", "HOLD"])
        self.assertEqual(report["promotion_authority"], "BLOCKED")

    def test_calendar_factory_never_overlaps_oos_or_uses_partial_tail(self) -> None:
        windows = wf.rolling_windows(
            start_ms=BASE, end_ms=BASE + 95 * DAY, train_days=30, oos_days=30
        )
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0]["oos_end_ms"], windows[1]["oos_start_ms"])
        with self.assertRaises(ValueError):
            wf.rolling_windows(
                start_ms=BASE,
                end_ms=BASE + 95 * DAY,
                train_days=30,
                oos_days=30,
                step_days=20,
            )

    def test_malformed_nested_schema_returns_hold(self) -> None:
        pristine = self.calendar()
        for field, value in (
            ("cost_authority", None),
            ("exposure_manifest", []),
            ("windows", [None]),
        ):
            calendar = copy.deepcopy(pristine)
            calendar[field] = value
            calendar["calendar_sha256"] = wf.digest(
                {k: v for k, v in calendar.items() if k != "calendar_sha256"}
            )
            result = self.evaluate(calendar, [self.row()])
            self.assertEqual(result["state"], "HOLD")
            self.assertIsNone(result["metrics"])
        calendar = copy.deepcopy(pristine)
        calendar["exposure_manifest"]["intervals"] = ["bad"]
        calendar["calendar_sha256"] = wf.digest(
            {k: v for k, v in calendar.items() if k != "calendar_sha256"}
        )
        self.assertEqual(self.evaluate(calendar, [self.row()])["state"], "HOLD")

    def test_one_window_cannot_drive_core_evidence(self) -> None:
        windows = wf.rolling_windows(
            start_ms=BASE, end_ms=BASE + 90 * DAY, train_days=30, oos_days=30
        )
        calendar = self.calendar(windows=windows)
        rows = [
            self.row("FIRST", entry=31, exit_day=32, net=90),
            self.row("SECOND", entry=61, exit_day=62, net=-10),
        ]
        report = self.evaluate(calendar, rows)
        self.assertEqual(report["rolling_summary"]["positive_window_ratio"], 0.5)
        self.assertEqual(report["rolling_summary"]["net_without_best_window_bps"], -10)
        self.assertIn("SINGLE_WINDOW_DEPENDENCE", report["promotion_blockers"])

    def test_exit_at_oos_boundary_is_censored_without_double_count(self) -> None:
        calendar = self.calendar()
        report = self.evaluate(
            calendar, [self.row("BOUNDARY_EXIT", entry=41, exit_day=42)]
        )
        self.assertEqual(report["metrics"]["T"], 0)
        self.assertEqual(report["windows"][0]["oos_censored_ids"], ["BOUNDARY_EXIT"])


if __name__ == "__main__":
    unittest.main()
