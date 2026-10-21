"""Synthetic-only contract tests; no source candles or network access."""
import importlib.util
from pathlib import Path
import unittest
import pandas as pd
from backend.research.rebuild import scalp7_execution_v2 as engine

spec = importlib.util.spec_from_file_location("work_c_c2", Path(__file__).with_name("adapter.py"))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
TF = 1_800_000


def frame(extra=()):
    # Old low at index5 (age15 at the break), fixed20-bar box[90,110].
    prices = [(100, 110 if i == 3 else 104, 90 if i == 5 else 96, 100) for i in range(20)]
    prices += [(92, 94, 87, 89), (91, 96, 88, 94)] + list(extra)
    return pd.DataFrame([dict(open_ts_ms=i * TF, close_ts_ms=(i + 1) * TF,
        available_ts_ms=(i + 1) * TF, segment_id="s0",
        **dict(zip(("open", "high", "low", "close"), p))) for i, p in enumerate(prices)])


def replay(f, signals=None):
    return engine.replay(a.generate_signals({"BTC-USDT": f}) if signals is None else signals,
                         {"BTC-USDT": f}, {"BTC-USDT": 15.0},
                         exit_update=a.exit_update, entry_update=a.entry_update)


class FailedDownsideTests(unittest.TestCase):
    def test_first_entry_next_open_and_target_next_open(self):
        f = frame([(95, 103, 93, 101), (102, 103, 100, 102)])
        s = a.generate_signals({"BTC-USDT": f})
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["signal_ts_ms"], 22 * TF)
        self.assertEqual(s[0]["stop_price"], 87)
        t = replay(f)["trades"][0]
        self.assertEqual((t["entry_ts_ms"], t["exit_ts_ms"]), (22 * TF, 23 * TF))
        self.assertEqual(t["reason"], "FROZEN_MIDPOINT_CLOSE")
        self.assertEqual(t["exit_prices"]["BTC-USDT"], 102)

    def test_no_signal_no_completed_break(self):
        f = frame(); f.loc[20, ["open", "high", "low", "close"]] = [92, 94, 87, 91]
        self.assertEqual(replay(f)["signal_count"], 0)

    def test_wick_recovery_is_not_close_recovery(self):
        f = frame(); f.loc[21, ["open", "high", "low", "close"]] = [89, 96, 88, 89]
        self.assertEqual(a.generate_signals({"BTC-USDT": f}), [])

    def test_recent_low_not_old_reference(self):
        f = frame(); f.loc[19, "low"] = 90
        self.assertEqual(a.generate_signals({"BTC-USDT": f}), [])

    def test_midpoint_reached_before_entry_cancels(self):
        f = frame(); f.loc[21, ["open", "high", "low", "close"]] = [91, 102, 88, 101]
        self.assertEqual(a.generate_signals({"BTC-USDT": f}), [])

    def test_stop_first_even_when_target_close_reached(self):
        f = frame([(95, 105, 86, 102), (103, 104, 101, 102)])
        t = replay(f)["trades"][0]
        self.assertEqual(t["reason"], "STOP_FIRST")
        self.assertEqual(t["exit_prices"]["BTC-USDT"], 87)
        self.assertLess(t["net_bps"], 0)

    def test_gap_stop_at_worse_open(self):
        f = frame([(95, 97, 92, 94), (84, 88, 82, 86)])
        t = replay(f)["trades"][0]
        self.assertEqual(t["reason"], "OPEN_GAP_STOP")
        self.assertEqual(t["exit_prices"]["BTC-USDT"], 84)

    def test_midpoint_wick_does_not_fill(self):
        f = frame([(95, 103, 92, 96)])
        r = replay(f)
        self.assertEqual(r["closed_trade_count"], 0)
        self.assertEqual(len(r["unresolved"]), 1)

    def test_recovery_failure_exits_next_open(self):
        f = frame([(95, 97, 88, 89), (88, 90, 87.5, 89)])
        t = replay(f)["trades"][0]
        self.assertEqual(t["reason"], "RECOVERY_FAILED_CLOSE")
        self.assertEqual(t["exit_prices"]["BTC-USDT"], 88)

    def test_end_is_unresolved_not_fake_close(self):
        r = replay(frame([(95, 97, 92, 94)]))
        self.assertEqual(r["trades"], [])
        self.assertEqual(len(r["unresolved"]), 1)

    def test_gap_after_entry_unresolved(self):
        f = frame([(95, 97, 92, 94), (95, 97, 92, 94), (95, 103, 92, 101)])
        r = replay(f.drop(index=23).reset_index(drop=True))
        self.assertEqual(r["trades"], [])
        self.assertEqual(len(r["unresolved"]), 1)

    def test_entry_gap_rejected(self):
        f = frame([(95, 97, 92, 94), (95, 97, 92, 94)])
        r = replay(f.drop(index=22).reset_index(drop=True))
        self.assertEqual(r["rejections"].get("ENTRY_GAP"), 1)

    def test_entry_gap_above_midpoint_rejected(self):
        r = replay(frame([(101, 103, 99, 102)]))
        self.assertEqual(r["rejections"].get("ENTRY_OUTSIDE_RECOVERY_REWARD_INTERVAL"), 1)

    def test_duplicate_event_and_cost_once(self):
        f = frame([(95, 103, 93, 101), (102, 103, 100, 102)])
        s = a.generate_signals({"BTC-USDT": f}); r = replay(f, s + s)
        self.assertEqual(r["rejections"].get("DUPLICATE_SIGNAL"), 1)
        self.assertEqual(r["closed_trade_count"], 1)
        self.assertAlmostEqual(r["trades"][0]["gross_bps"] - r["trades"][0]["net_bps"], 15)

    def test_delayed_reference_bar_resets_history(self):
        f = frame(); f.loc[15, "available_ts_ms"] += 1
        self.assertEqual(a.generate_signals({"BTC-USDT": f}), [])

    def test_delayed_recovery_bar_never_backdates(self):
        f = frame(); f.loc[21, "available_ts_ms"] += 1
        self.assertEqual(a.generate_signals({"BTC-USDT": f}), [])

    def test_missing_pre_entry_bar_resets_setup(self):
        f = frame().drop(index=10).reset_index(drop=True)
        self.assertEqual(a.generate_signals({"BTC-USDT": f}), [])

    def test_prefix_invariance(self):
        f = frame([(95, 103, 93, 101), (102, 103, 100, 102)])
        original = a.generate_signals({"BTC-USDT": f.iloc[:22]})
        f.loc[22:, ["open", "high", "low", "close"]] *= 10
        self.assertEqual(a.generate_signals({"BTC-USDT": f})[:1], original)

    def test_timeout_requires_next_open(self):
        f = frame([(95, 97, 92, 94)] * 13)
        t = replay(f)["trades"][0]
        self.assertEqual(t["reason"], "MAX_HOLD_NEXT_OPEN")
        self.assertEqual(t["hold_bars"], 12)

    def test_no_next_bar_is_not_trade(self):
        self.assertEqual(replay(frame())["rejections"].get("NO_NEXT_BAR"), 1)

    def test_malformed_duplicate_and_nonfinite_rejected(self):
        f = frame()
        with self.assertRaises(ValueError):
            a.generate_signals({"BTC-USDT": pd.concat([f, f.iloc[-1:]])})
        f.loc[2, "close"] = float("nan")
        with self.assertRaises(ValueError):
            a.generate_signals({"BTC-USDT": f})

    def test_missing_segment_rejected(self):
        f = frame(); f["segment_id"] = None
        with self.assertRaisesRegex(ValueError, "SEGMENT_ID_REQUIRED"):
            a.generate_signals({"BTC-USDT": f})

    def test_late_recovery_expires(self):
        f = frame([(89, 91, 88, 89), (89, 91, 88, 89), (91, 96, 90, 94)])
        f.loc[21, ["open", "high", "low", "close"]] = [89, 91, 88, 89]
        self.assertEqual(a.generate_signals({"BTC-USDT": f}), [])


if __name__ == "__main__":
    unittest.main()
