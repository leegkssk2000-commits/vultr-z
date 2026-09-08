"""Synthetic-only D2 semantic checks, no native evaluator and no market files."""
import ast
import copy
import os
from pathlib import Path
import unittest

# Compile only dependency-free rule functions. This remains runnable when the
# target Freqtrade/pandas compiled installation itself is blocked.
source_path = Path(__file__).with_name("D2Independent.py")
tree = ast.parse(source_path.read_text())
keep = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.Assign)):
        keep.append(node)
    elif isinstance(node, ast.ImportFrom) and node.module in ("copy", "__future__"):
        keep.append(node)
    elif isinstance(node, ast.Import) and all(x.name == "math" for x in node.names):
        keep.append(node)
namespace = {}
exec(compile(ast.Module(body=keep, type_ignores=[]), str(source_path), "exec"), namespace)
ema = namespace["bounded_ema"]
prepare = namespace["prepare_causal"]
new = namespace["new_position"]
step = namespace["step_completed"]
BAR = namespace["BAR"]


def row(index, close=102, high=106, low=98, opened=101):
    return {"bar_open_ts": index * BAR, "bar_close_ts": (index + 1) * BAR,
            "open": opened, "high": high, "low": low, "close": close, "volume": 10.0}


class D2Synthetic(unittest.TestCase):
    def test_ema_is_bounded_and_prefix_causal(self):
        values = [100.0 + (i % 7) for i in range(240)]
        bounded = ema(values, 20)
        self.assertEqual(bounded[:120], ema(values[:120], 20))
        changed = list(values)
        changed[0] = 900000.0
        self.assertEqual(bounded[100:], ema(changed, 20)[100:])
        a = 2 / 21
        self.assertEqual(ema([100.0, 110.0], 20)[1], a * 110 + (1 - a) * 100)

    def test_first_suppression_does_not_exit_or_rearm(self):
        p = new(4, 10, 100.0, 101.0)
        reason, trace = step(p, row(11, close=99.0), 11, 100.0, 98.0, 100 * BAR)
        self.assertIsNone(reason)
        self.assertEqual(p["low_exit_state"]["status"], namespace["SUPPRESSED"])
        reason, _ = step(p, row(12, close=103.0), 12, 100.0, 98.0, 100 * BAR)
        self.assertIsNone(reason)
        reason, _ = step(p, row(13, close=97.0), 13, 100.0, 98.0, 100 * BAR)
        self.assertEqual(reason, "POST_SUPPRESSION_STRUCTURE_FAILURE_NEXT_OPEN")
        self.assertEqual(p["low_exit_state"]["index"], 11)

    def test_ema_priority_over_additional_failure(self):
        p = new(4, 10, 100.0, 101.0)
        step(p, row(11, close=99), 11, 100, 98, 100 * BAR)
        reason, _ = step(p, row(12, close=97), 12, 97.5, 98, 100 * BAR)
        self.assertEqual(reason, "EMA20_NOT_ABOVE_EMA50_NEXT_OPEN")

    def test_first_allowed_low_uses_original_priority(self):
        p = new(4, 10, 100, 101)
        reason, _ = step(p, row(11, close=97), 11, 100, 98, 100 * BAR)
        self.assertEqual(reason, "CONTEXT_SIGNAL_LOW_INVALIDATION_NEXT_OPEN")
        self.assertEqual(p["low_exit_state"]["status"], namespace["ALLOWED"])

    def test_suppression_vetoes_extension_and_timeout_stays_close_target(self):
        p = new(4, 10, 100, 101)
        step(p, row(11, close=99), 11, 100, 98, 100 * BAR)
        for j in range(12, 22):
            reason, _ = step(p, row(j, close=105), j, 100, 98, 100 * BAR)
            self.assertIsNone(reason)
        self.assertFalse(p["extension_allowed"])
        reason, trace = step(p, row(22, close=106, high=110), 22, 100, 98, 100 * BAR)
        self.assertEqual(reason, "ORIGINAL_TIME_STOP_CLOSE")
        self.assertEqual(trace[0]["price"], 106)
        self.assertTrue(trace[0]["native_target_only"])
        self.assertEqual(trace[0]["ft_fill_semantics"], "FOLLOWING_OPEN_NOT_NATIVE_CLOSE")

    def test_runner_extension_and_boundary_censor(self):
        p = new(4, 10, 95, 101)
        for j in range(11, 22):
            step(p, row(j, close=105), j, 100, 98, 35 * BAR)
        self.assertTrue(p["extension_allowed"])
        self.assertEqual(p["final_exit_index"], 34)
        for j in range(22, 34):
            step(p, row(j, close=105), j, 100, 98, 35 * BAR)
        reason, trace = step(p, row(34, close=105), 34, 100, 98, 35 * BAR)
        self.assertIsNone(reason)
        self.assertEqual(trace[0]["kind"], "STRICT_END_TIMEOUT_CENSORED")

    def test_actual_callback_gap_rejected(self):
        p = new(4, 10, 100, 101)
        with self.assertRaisesRegex(ValueError, "CALLBACK_GAP"):
            step(p, row(12), 12, 100, 98, 100 * BAR)

    def test_raw_and_reference_prefix_invariance(self):
        # Artificial waveform, never decoded from a trading file.
        rows = []
        for j in range(360):
            price = 100 + j * 0.08 + (2 if j % 9 == 0 else -2 if j % 9 == 1 else 0)
            rows.append(row(j, close=price, high=price + 1, low=price - 1, opened=price))
        full = prepare(rows, 0, 500 * BAR)
        prefix = prepare(rows[:300], 0, 500 * BAR)
        self.assertEqual([s for s in full["raw_signals"] if s["signal_index"] < 300], prefix["raw_signals"])
        self.assertEqual([e for e in full["reference_events"] if e["index"] < 300], prefix["reference_events"])
        for event in full["opportunity_events"]:
            self.assertEqual(event["decision_index"] - event["original_signal_index"], 6)
        self.assertGreater(len(full["reference_events"]), 0)


@unittest.skipUnless(os.environ.get("ZEL_TEST_RUNTIME") == "1", "actual runtime opt-in")
class D2FreqtradeCallbacks(unittest.TestCase):
    def test_timestamp_units_and_future_suffix_guard(self):
        import pandas as pd
        from datetime import datetime, timezone
        from D2Independent import D2Independent
        from types import SimpleNamespace
        dates = pd.date_range("2025-01-01", periods=3, freq="4h", tz="UTC")
        current = datetime(2025, 1, 1, 8, tzinfo=timezone.utc)
        strategy = D2Independent({"zel_start_ms": 0, "zel_end_ms": 99 * BAR})
        for unit in ("ns", "us", "ms"):
            frame = pd.DataFrame({"date": dates.as_unit(unit), "zel_index": [0, 1, 2]})
            strategy.dp = SimpleNamespace(get_analyzed_dataframe=lambda pair, tf: (frame, None))
            self.assertEqual(int(strategy._latest("SYNTH/USDT", current)["zel_index"]), 1)

    def test_actual_strategy_lifecycle_no_market_data(self):
        import pandas as pd
        from types import SimpleNamespace
        from D2Independent import D2Independent
        base = pd.Timestamp("2025-01-01", tz="UTC")
        data = pd.DataFrame({"date": pd.date_range(base, periods=270, freq="4h"),
                             "open": [100 + j * 0.1 for j in range(270)],
                             "close": [100 + j * 0.1 for j in range(270)],
                             "high": [101 + j * 0.1 for j in range(270)],
                             "low": [99 + j * 0.1 for j in range(270)], "volume": 100})
        strategy = D2Independent({"zel_start_ms": int(base.timestamp() * 1000),
                                  "zel_end_ms": int(base.timestamp() * 1000) + 270 * BAR})
        frame = strategy.populate_indicators(data, {"pair": "SYNTH/USDT"})
        frame = strategy.populate_entry_trend(frame, {"pair": "SYNTH/USDT"})
        frame = strategy.populate_exit_trend(frame, {"pair": "SYNTH/USDT"})
        strategy.dp = SimpleNamespace(get_analyzed_dataframe=lambda pair, tf: (frame, None))
        trade = SimpleNamespace(id=1, enter_tag="d2:240:246", open_rate=124.7, entry_side="buy", exit_side="sell")
        entry_time = frame.iloc[247]["date"].to_pydatetime()
        strategy.order_filled("SYNTH/USDT", trade, SimpleNamespace(ft_order_side="buy"), entry_time)
        self.assertIsNone(strategy.custom_exit("SYNTH/USDT", trade, entry_time, 124.7, 0.0))
        next_time = frame.iloc[248]["date"].to_pydatetime()
        self.assertIsNone(strategy.custom_exit("SYNTH/USDT", trade, next_time, 124.8, 0.0))
        self.assertEqual(strategy._held[1]["last_processed_index"], 247)
        self.assertEqual(strategy.audit["callback_errors"], [])


if __name__ == "__main__":
    unittest.main()
