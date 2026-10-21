"""Synthetic-only C3 behavior tests; no historical price source is opened."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "backend").is_dir())
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("c3_test_subject", HERE / "adapter.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

import pandas as pd
from backend.research.rebuild import scalp7_execution_v2 as engine

SYMBOL = "BTC-USDT"
STEP = 900_000


def fixture(tail=None):
    prices = []
    for hour in range(3):
        for quarter in range(4):
            o = 95 + 5 * hour + quarter
            prices.append((o, o + 2, o - 1, o + 1))
    prices.extend([(109, 112, 108, 111), (110, 111.5, 109, 111), (111, 114, 110, 113)])
    prices.extend(tail or [])
    return pd.DataFrame([
        {"open_ts_ms": i * STEP, "close_ts_ms": (i + 1) * STEP,
         "available_ts_ms": (i + 1) * STEP, "segment_id": "synthetic-A",
         "open": x[0], "high": x[1], "low": x[2], "close": x[3]}
        for i, x in enumerate(prices)
    ])


def run(frame, signals=None, cost=15.0):
    own = {SYMBOL: frame}
    return engine.replay(adapter.generate_signals(own) if signals is None else signals,
                         own, {SYMBOL: cost}, identity=adapter.IDENTITY,
                         exit_update=adapter.exit_update)


class TestC3(unittest.TestCase):
    def test_spec_matches_frozen_module(self):
        spec = json.loads((HERE / "SPEC.json").read_text())
        self.assertEqual(spec["identity"], adapter.IDENTITY)
        self.assertEqual(spec["timeframe_min"], adapter.TIMEFRAME_MIN)
        self.assertFalse(spec["source_exact"])

    def test_first_signal_closed_bar_and_independent_hour_context(self):
        signals = adapter.generate_signals({SYMBOL: fixture()})
        self.assertEqual(len(signals), 1)
        s = signals[0]
        self.assertEqual(s["signal_ts_ms"], 15 * STEP)
        self.assertEqual(s["stop_price"], 108)
        self.assertEqual(s["meta"]["mother_open_ts_ms"], 12 * STEP)
        self.assertEqual([r["close_ts_ms"] for r in s["meta"]["hour_context"]],
                         [4 * STEP, 8 * STEP, 12 * STEP])
        self.assertTrue(all(r["available_ts_ms"] <= 12 * STEP
                            for r in s["meta"]["hour_context"]))

    def test_empty_and_no_signal(self):
        empty = fixture().iloc[:0]
        self.assertEqual(run(empty)["signal_count"], 0)
        x = fixture().iloc[:14]
        self.assertEqual(run(x)["closed_trade_count"], 0)
        self.assertEqual(run(x)["signal_count"], 0)

    def test_no_hour_uptrend(self):
        x = fixture()
        x.loc[:3, ["open", "high", "low", "close"]] += 20
        self.assertEqual(adapter.generate_signals({SYMBOL: x}), [])

    def test_equal_inside_edge_is_not_strict_inside(self):
        x = fixture()
        x.loc[13, "high"] = 112
        self.assertEqual(adapter.generate_signals({SYMBOL: x}), [])

    def test_wick_only_break_is_not_signal(self):
        x = fixture()
        x.loc[14, "close"] = 112
        self.assertEqual(adapter.generate_signals({SYMBOL: x}), [])

    def test_breakdown_then_recovery_is_not_continuation(self):
        x = fixture()
        x.loc[14, "low"] = 107
        self.assertEqual(adapter.generate_signals({SYMBOL: x}), [])

    def test_first_entry_target_and_exact_fee_debit(self):
        x = fixture([(113, 124, 112, 120)])
        result = run(x)
        self.assertEqual(len(result["trades"]), 1)
        t = result["trades"][0]
        self.assertEqual(t["entry_ts_ms"], 15 * STEP)
        self.assertEqual(t["entry_prices"][SYMBOL], 113)
        self.assertEqual(t["exit_prices"][SYMBOL], 123)
        self.assertEqual(t["reason"], "TARGET")
        self.assertAlmostEqual(t["net_bps"], (123 / 113 - 1) * 10000 - 15)
        stress = run(x, cost=30)["trades"][0]
        self.assertEqual(t["entry_prices"], stress["entry_prices"])
        self.assertAlmostEqual(t["net_bps"] - stress["net_bps"], 15)

    def test_stop_loss(self):
        t = run(fixture([(113, 114, 107, 110)]))["trades"][0]
        self.assertEqual(t["reason"], "STOP_FIRST")
        self.assertEqual(t["exit_prices"][SYMBOL], 108)
        self.assertLess(t["net_bps"], 0)

    def test_stop_before_target_same_bar(self):
        t = run(fixture([(113, 130, 107, 124)]))["trades"][0]
        self.assertEqual(t["reason"], "STOP_FIRST")
        self.assertEqual(t["exit_prices"][SYMBOL], 108)

    def test_gap_stop_actual_open(self):
        t = run(fixture([(113, 115, 112, 114), (106, 110, 104, 108)]))["trades"][0]
        self.assertEqual(t["reason"], "OPEN_GAP_STOP")
        self.assertEqual(t["exit_prices"][SYMBOL], 106)

    def test_entry_gap_invalidates_frozen_stop(self):
        result = run(fixture([(107, 109, 106, 108)]))
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["rejections"], {"ENTRY_INVALIDATES_STOP": 1})

    def test_no_retroactive_recovery_after_stop(self):
        result = run(fixture([(113, 114, 107, 110), (110, 140, 109, 130)]))
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"][0]["exit_prices"][SYMBOL], 108)

    def test_end_unresolved_not_fabricated_exit(self):
        result = run(fixture([(113, 114, 112, 113)]))
        self.assertEqual(result["trades"], [])
        self.assertEqual(len(result["unresolved"]), 1)
        self.assertEqual(result["unresolved"][0]["state"], "UNRESOLVED_GAP_OR_END")

    def test_price_gap_preserves_unresolved_ownership(self):
        x = fixture([(113, 114, 112, 113), (113, 124, 112, 120)])
        x.loc[16, ["open_ts_ms", "close_ts_ms", "available_ts_ms"]] += STEP
        result = run(x)
        self.assertEqual(result["trades"], [])
        self.assertEqual(len(result["unresolved"]), 1)

    def test_no_next_bar_rejected(self):
        self.assertEqual(run(fixture())["rejections"], {"NO_NEXT_BAR": 1})

    def test_duplicate_event_rejected(self):
        x = fixture([(113, 124, 112, 120)])
        signal = adapter.generate_signals({SYMBOL: x})
        result = run(x, signals=signal + signal)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["rejections"], {"DUPLICATE_SIGNAL": 1})

    def test_time_exit_next_open_and_no_close_at_last_bar(self):
        x = fixture([(113, 114, 112, 113)] * 16)
        self.assertEqual(len(run(x)["unresolved"]), 1)
        x = fixture([(113, 114, 112, 113)] * 16 + [(114, 115, 113, 114)])
        t = run(x)["trades"][0]
        self.assertEqual(t["reason"], "MAX_HOLD_NEXT_OPEN")
        self.assertEqual(t["exit_ts_ms"], 31 * STEP)
        self.assertEqual(t["exit_prices"][SYMBOL], 114)

    def test_missing_hour_constituent_blocks_context(self):
        x = fixture().drop(index=7).reset_index(drop=True)
        self.assertEqual(adapter.generate_signals({SYMBOL: x}), [])

    def test_late_hour_constituent_blocks_context(self):
        x = fixture()
        x.loc[7, "available_ts_ms"] += 3 * STEP
        self.assertEqual(adapter.generate_signals({SYMBOL: x}), [])

    def test_delayed_trigger_is_not_backfilled(self):
        x = fixture()
        x.loc[14, "available_ts_ms"] += 1
        self.assertEqual(adapter.generate_signals({SYMBOL: x}), [])

    def test_duplicate_candle_fails_validation(self):
        x = pd.concat([fixture(), fixture().iloc[-1:]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            adapter.generate_signals({SYMBOL: x})

    def test_missing_segment_fails_validation(self):
        for bad in (None, "", "  "):
            x = fixture()
            x.loc[4, "segment_id"] = bad
            with self.assertRaisesRegex(ValueError, "SEGMENT_REQUIRED"):
                adapter.generate_signals({SYMBOL: x})

    def test_future_append_cannot_change_emitted_prefix(self):
        prefix = fixture()
        x = fixture([(113, 114, 112, 113), (113, 200, 40, 150)])
        signals = adapter.generate_signals({SYMBOL: x})
        self.assertEqual([s for s in signals if s["signal_ts_ms"] <= 15 * STEP],
                         adapter.generate_signals({SYMBOL: prefix}))

    def test_expired_setup_requires_new_pattern(self):
        x = fixture().iloc[:14].copy()
        tail = fixture([(113, 124, 112, 120)]).iloc[:0]
        for i in range(14, 20):
            tail.loc[len(tail)] = {"open_ts_ms": i * STEP, "close_ts_ms": (i + 1) * STEP,
                "available_ts_ms": (i + 1) * STEP, "segment_id": "synthetic-A",
                "open": 111, "high": 112, "low": 109, "close": 111 if i < 19 else 113}
        tail.loc[tail.index[-1], "high"] = 114
        self.assertEqual(adapter.generate_signals({SYMBOL: pd.concat([x, tail], ignore_index=True)}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
