from __future__ import annotations

import unittest

from backend.research.rebuild.g4_scalp_round1_native_economics_v1 import (
    CONTRACT_PATH,
    FAST_CHILD_PATH,
    LANE_ORDER,
    POLICY_COST_BPS,
    COST2_BPS,
    read_json,
    simulate_exit,
    summarize_trades,
    terminal_state,
)


EXPECTED_NATIVE = {
    "alpha_combo", "ema_ribbon_scalp", "fvg_revert", "grid_rebalance",
    "liquidity_sweep", "mfi_rsi_div", "obv_trend", "pivot_reversal",
    "range_fade", "rbreaker_like", "rsi_swing_fail", "scalp_snap",
    "session_bias", "sr_levels", "vol_spike_fade",
}
EXPECTED_FAST_PARENTS = {
    "anchor_vwap_trend", "bb_revert", "break_and_continue", "keltner_trend",
    "squeeze_break", "supertrend_pullback", "trend_ma_macd", "trend_rider", "vwap_revert",
}


class G4ScalpRound1NativeEconomicsTests(unittest.TestCase):
    def test_contract_native15_window_universe_and_cost(self) -> None:
        c = read_json(CONTRACT_PATH)
        self.assertEqual(set(c["native_round1"]), EXPECTED_NATIVE)
        self.assertEqual(set(LANE_ORDER), EXPECTED_NATIVE)
        self.assertEqual(c["window"]["start_utc_inclusive"], "2026-03-12T14:00:00Z")
        self.assertEqual(c["window"]["end_utc_exclusive"], "2026-09-12T14:00:00Z")
        self.assertEqual(c["universe"]["symbols"], ["BTC-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT"])
        self.assertEqual(POLICY_COST_BPS, 14.0)
        self.assertEqual(COST2_BPS, 28.0)
        self.assertEqual(c["cost"]["round_trip_bps"], 14.0)
        self.assertEqual(c["cost"]["cost2_round_trip_bps"], 28.0)

    def test_same_bar_sl_tp_is_pessimistic_sl_first(self) -> None:
        rows = [
            {"ts_ms": 0, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0},
            {"ts_ms": 300000, "open": 100.0, "high": 103.0, "low": 97.0, "close": 101.0, "volume": 1.0},
        ]
        px, ts, reason, idx = simulate_exit(rows, entry_i=1, timeout_bars=1, side="long", sl=98.0, tp=102.0)
        self.assertEqual(px, 98.0)
        self.assertEqual(reason, "SL")
        self.assertEqual(idx, 1)
        self.assertEqual(ts, 600000)

    def test_summary_metrics_are_profitability_first(self) -> None:
        trades = [
            {"exit_ts": 10, "signal_ts": 1, "symbol": "BTC-USDT", "net_bps": 20.0, "gross_bps": 34.0, "net_R": 0.5, "hold_minutes": 20.0},
            {"exit_ts": 20, "signal_ts": 2, "symbol": "ETH-USDT", "net_bps": -10.0, "gross_bps": 4.0, "net_R": -0.25, "hold_minutes": 40.0},
            {"exit_ts": 30, "signal_ts": 3, "symbol": "BTC-USDT", "net_bps": 40.0, "gross_bps": 54.0, "net_R": 1.0, "hold_minutes": 60.0},
        ]
        m = summarize_trades(trades, 10.0)
        self.assertEqual(m["closed_T"], 3)
        self.assertAlmostEqual(m["T_per_day"], 0.3)
        self.assertAlmostEqual(m["net_pnl_bps"], 50.0)
        self.assertAlmostEqual(m["net_R_per_day"], 0.125)
        self.assertAlmostEqual(m["win_rate"], 2 / 3)
        self.assertAlmostEqual(m["profit_factor"], 6.0)
        self.assertAlmostEqual(m["payoff"], 3.0)
        self.assertAlmostEqual(m["cost2_net_bps"], (34.0 + 4.0 + 54.0) - 28.0 * 3)
        self.assertAlmostEqual(m["top_symbol_share"], 2 / 3)

    def test_terminal_state_contract(self) -> None:
        sparse = {"closed_T": 29, "net_pnl_bps": 100.0, "net_R_per_day": 1.0, "profit_factor": 2.0, "profit_factor_unbounded": False}
        self.assertEqual(terminal_state(sparse), "ROUND1_SPARSE_DESCRIPTIVE")
        fail = {"closed_T": 30, "net_pnl_bps": -1.0, "net_R_per_day": -0.01, "profit_factor": 0.99, "profit_factor_unbounded": False}
        self.assertEqual(terminal_state(fail), "ROUND1_ECONOMIC_FAIL")
        positive = {"closed_T": 30, "net_pnl_bps": 1.0, "net_R_per_day": 0.01, "profit_factor": 1.01, "profit_factor_unbounded": False}
        self.assertEqual(terminal_state(positive), "ROUND1_POSITIVE_ECONOMICS")

    def test_fast_child_freeze_exact9_and_no_outcome_selection(self) -> None:
        x = read_json(FAST_CHILD_PATH)
        parents = {row["parent_strategy_id"] for row in x["children"].values()}
        self.assertEqual(parents, EXPECTED_FAST_PARENTS)
        self.assertEqual(len(x["children"]), 9)
        self.assertTrue(x["frozen_before_round1_economics"])
        self.assertFalse(x["global_rules"]["outcome_or_pnl_used"])
        self.assertTrue(x["global_rules"]["only_timeframe_and_timeout_overridden"])
        for child in x["children"].values():
            self.assertNotIn("net_pnl", child)
            self.assertNotIn("win_rate", child)
            self.assertNotIn("profit_factor", child)
            self.assertLessEqual(int(child["hard_timeout_minutes"]), 720)

    def test_authority_stays_research_only(self) -> None:
        c = read_json(CONTRACT_PATH)
        a = c["authority"]
        self.assertFalse(a["selection_authority"])
        self.assertFalse(a["promotion_authority"])
        self.assertEqual(a["execution_authority"], "NONE")
        self.assertEqual(a["order_authority"], "BLOCKED")
        self.assertEqual(a["live_trade_authority"], "BLOCKED")
        self.assertEqual(a["paid_ai"], 0)
        self.assertEqual(a["deploy"], 0)
        self.assertEqual(a["g5_credit_change"], 0)


if __name__ == "__main__":
    unittest.main()
