"""Synthetic source, aggregation, causality and fill tests; no DEV data."""
import copy
import unittest

from backend.research.rebuild import break_channel_structure_v1 as channel


I = channel.INTERVAL
D = channel.DAY


def bars(n=36, start=0):
    return [{"bar_open_ts": (i + start) * I,
             "bar_close_ts": (i + start + 1) * I,
             "open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.0, "volume": 10.0} for i in range(n)]


def daily(closes):
    rows = bars(len(closes) * 6)
    for i, value in enumerate(closes):
        for row in rows[i * 6:(i + 1) * 6]:
            row.update(open=value, high=value + 1, low=value - 1, close=value)
    return channel.aggregate_daily(rows)["daily"]


def generate(closes, prep=True, start=0, end=None):
    ds = daily(closes)
    return channel.generate_signals(ds, eval_start_ms=start,
        eval_end_ms=end or (len(closes) + 1) * D, require_preparation=prep)


def signal(index=5, direction="UP", lower=98.0, upper=100.5):
    return {"direction": direction, "signal_index": index,
            "signal_ts": (index + 1) * I, "lower": lower, "upper": upper,
            "anchor_ts": (index + 1) * I - D,
            "preparation": True, "confirmation_days": 2}


def replay(rows=None, signals=None, start=0, end=None):
    rows = bars() if rows is None else rows
    signals = [signal()] if signals is None else signals
    return channel.replay(rows, {"signals": signals}, eval_start_ms=start,
                          eval_end_ms=end or rows[-1]["bar_close_ts"])


class DailyChannelTests(unittest.TestCase):
    def test_source_cb1_formula_uses_prior_closes_and_percentage_units(self):
        actual = channel.channel([100.0, 100.2])
        self.assertTrue(actual["preparation"])
        self.assertAlmostEqual(actual["channel_width_fraction"], 0.002)
        self.assertAlmostEqual(actual["upper"], 100.5)
        self.assertAlmostEqual(actual["lower"], 99.699)
        rows = bars(30)
        for row in rows:
            row.update(high=900.0, low=1.0)
        ds = channel.aggregate_daily(rows)["daily"]
        for i, close in enumerate([100.0, 100.2, 101.0, 102.0, 101.0]):
            ds[i]["close"] = close
        s = channel.generate_signals(ds, eval_start_ms=0,
                                     eval_end_ms=5 * D)["signals"][0]
        self.assertAlmostEqual(s["upper"], 100.5)
        self.assertAlmostEqual(s["lower"], 99.699)

    def test_utc_six_bar_aggregation_drops_both_edge_partial_days(self):
        rows = bars(24, start=2)
        result = channel.aggregate_daily(rows)
        self.assertEqual(result["audit"]["complete_utc_days"], 3)
        self.assertEqual(result["audit"]["partial_day_4h_rows"], 6)
        self.assertEqual([p["rows"] for p in result["audit"]["partial_days"]], [4, 2])
        first = result["daily"][0]
        self.assertEqual((first["bar_open_ts"], first["bar_close_ts"]), (D, 2 * D))
        self.assertEqual((first["source_first_index"], first["source_last_index"]), (4, 9))
        self.assertEqual(first["volume"], 60.0)
        self.assertEqual(result["audit"]["synthetic_rows"], 0)

    def test_aggregation_preserves_close_at_end_but_ignores_later_4h_rows(self):
        result = channel.aggregate_daily(bars(26), split_end_ms=4 * D)
        self.assertEqual(len(result["daily"]), 4)
        self.assertEqual(result["daily"][-1]["bar_close_ts"], 4 * D)
        self.assertEqual(result["audit"]["after_common_end_4h_rows"], 2)

    def test_source_gaps_duplicate_order_and_nonfinite_fail_before_signals(self):
        cases = []
        rows = bars(); del rows[8]; cases.append(rows)
        rows = bars(); rows[8] = copy.deepcopy(rows[7]); cases.append(rows)
        rows = bars(); rows[8], rows[9] = rows[9], rows[8]; cases.append(rows)
        rows = bars(); rows[8]["volume"] = float("nan"); cases.append(rows)
        for rows in cases:
            with self.subTest(rows=rows[8]):
                with self.assertRaises(RuntimeError):
                    channel.aggregate_daily(rows)

    def test_two_close_up_confirmation_uses_frozen_original_band(self):
        result = generate([100.0, 100.2, 103.0, 100.6, 100.0])
        up = [s for s in result["signals"] if s["direction"] == "UP"]
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0]["signal_ts"], 4 * D)
        self.assertEqual(up[0]["anchor_ts"], 3 * D)
        self.assertAlmostEqual(up[0]["upper"], 100.5)
        self.assertLess(up[0]["confirmation_close"], 100.2 * 1.005)

    def test_q_minus_removes_only_preparation_and_keeps_same_thresholds(self):
        close = [100.0, 102.0, 103.0, 104.0, 103.0]
        q, minus = generate(close), generate(close, prep=False)
        self.assertFalse(any(s["direction"] == "UP" for s in q["signals"]))
        up = next(s for s in minus["signals"] if s["direction"] == "UP")
        self.assertFalse(up["preparation"])
        self.assertAlmostEqual(up["upper"], 100.5)
        self.assertAlmostEqual(up["lower"], 101.49)
        prepared = [100.0, 100.2, 101.0, 102.0, 102.0]
        self.assertEqual(generate(prepared)["signals"], generate(prepared, prep=False)["signals"])

    def test_crossed_bands_reject_conflicting_up_attempt_even_without_prep(self):
        result = generate([100.0, 110.0, 103.0, 104.0, 102.0], prep=False)
        self.assertFalse(any(s["direction"] == "UP" for s in result["signals"]))
        self.assertTrue(any(t.get("reason") == "CROSSED_BAND_CONFLICT" for t in result["trace"]))

    def test_bearish_confirmation_uses_frozen_band_without_preparation(self):
        close = [100.0, 110.0, 99.0, 101.0, 103.0]
        q, minus = generate(close), generate(close, prep=False)
        down = [s for s in q["signals"] if s["direction"] == "DOWN"]
        self.assertEqual(down, [s for s in minus["signals"] if s["direction"] == "DOWN"])
        self.assertEqual(len(down), 1)
        self.assertAlmostEqual(down[0]["lower"], 109.45)
        self.assertFalse(down[0]["preparation"])

    def test_failed_attempt_cancels_and_does_not_restart_that_day(self):
        result = generate([100.0, 100.0, 101.0, 100.4, 101.0, 102.0, 100.0])
        cancelled = next(t for t in result["trace"]
                         if t["kind"] == "ATTEMPT_CANCELLED" and t["direction"] == "UP")
        same_day_starts = [t for t in result["trace"] if t["kind"] == "ATTEMPT_STARTED"
                           and t["direction"] == "UP" and t["ts"] == cancelled["ts"]]
        self.assertEqual(same_day_starts, [])
        self.assertFalse(any(s["signal_ts"] == cancelled["ts"] for s in result["signals"]))

    def test_prefix_causality_and_close_at_end_not_a_signal(self):
        close = [100.0, 100.2, 103.0, 100.6, 98.0, 97.0, 104.0, 110.0]
        prefix = generate(close[:5], end=6 * D)
        full = generate(close, end=9 * D)
        self.assertEqual(prefix["signals"], [s for s in full["signals"] if s["signal_ts"] <= 5 * D])
        cutoff = generate(close, end=4 * D)
        self.assertFalse(any(s["signal_ts"] >= 4 * D for s in cutoff["signals"]))
        started_later = generate(close, start=4 * D, end=9 * D)
        self.assertTrue(all(s["signal_ts"] >= 4 * D for s in started_later["signals"]))

    def test_daily_gap_or_bad_mode_is_rejected(self):
        ds = daily([100.0] * 6); del ds[2]
        with self.assertRaisesRegex(RuntimeError, "DAILY_GAP"):
            channel.generate_signals(ds, eval_start_ms=0, eval_end_ms=7 * D)
        with self.assertRaisesRegex(RuntimeError, "BOOL"):
            generate([100.0] * 5, prep=1)


class ChronologicalChannelReplayTests(unittest.TestCase):
    def test_daily_to_four_hour_lineage_with_partial_warmup_prefix(self):
        rows = bars(40, start=2)
        closes = {1:100.0, 2:100.2, 3:101.0, 4:102.0, 5:103.0, 6:103.0}
        for row in rows:
            value = closes.get(row["bar_open_ts"] // D, 100.0)
            row.update(open=value, high=value+0.1, low=value-0.1, close=value)
        aggregate = channel.aggregate_daily(rows, split_end_ms=7 * D)
        bundle = channel.generate_signals(aggregate["daily"], eval_start_ms=D,
                                         eval_end_ms=7 * D)
        result = channel.replay(rows, bundle, eval_start_ms=D, eval_end_ms=7 * D)
        opened = result["open_positions"][0]
        self.assertEqual((opened["signal_index"], opened["entry_index"]), (27, 28))
        self.assertEqual((opened["signal_ts"], opened["entry_ts"], opened["mark_ts"]), (5 * D, 5 * D, 7 * D))
        self.assertEqual(opened["entry_signal_metadata"]["prior_start_ts"], D)
        self.assertEqual(opened["entry_signal_metadata"]["prior_end_ts"], 3 * D)
        self.assertAlmostEqual(opened["entry_stop_price"], 99.699)

    def test_next_open_entry_opposite_exit_and_no_exit_bar_hlc(self):
        rows = bars()
        rows[12].update(open=120.0, high=200.0, low=90.0, close=110.0)
        signals = [signal(), signal(11, "DOWN")]
        trade = replay(rows, signals)["trades"][0]
        self.assertEqual((trade["signal_index"], trade["entry_index"], trade["exit_index"]), (5, 6, 12))
        self.assertEqual((trade["entry_ts"], trade["exit_ts"], trade["hold_ms"]), (D, 2 * D, D))
        self.assertEqual(trade["exit_reason"], "BEARISH_CONFIRMED_NEXT_OPEN")
        self.assertAlmostEqual(trade["gross_bps"], 2000.0)
        self.assertAlmostEqual(trade["mfe_bps"], 2000.0)
        rows[12].update(high=99999.0, low=0.01, close=130.0)
        self.assertEqual(trade, replay(rows, signals)["trades"][0])

    def test_protective_gap_precedes_pending_opposite_exit_and_fills_gap(self):
        rows = bars(); rows[12].update(open=97.0, high=98.0, low=96.0, close=97.0)
        trade = replay(rows, [signal(), signal(11, "DOWN")])["trades"][0]
        self.assertEqual(trade["exit_reason"], "PROTECTIVE_STOP_GAP_OPEN")
        self.assertEqual(trade["exit_price"], 97.0)
        self.assertEqual(trade["exit_ts"], 2 * D)
        self.assertEqual(trade["entry_stop_price"], 98.0)

    def test_intrabar_stop_price_and_conservative_time_excursion_bounds(self):
        rows = bars(); rows[7].update(low=97.0, high=150.0)
        trade = replay(rows)["trades"][0]
        self.assertEqual(trade["exit_price"], 98.0)
        self.assertEqual(trade["exit_reason"], "PROTECTIVE_STOP_INTRABAR")
        self.assertEqual(trade["exit_ts"], 8 * I)
        self.assertEqual(trade["hold_ms"], 2 * I)
        self.assertTrue(trade["intrabar_stop_timing_unknown"])
        self.assertIn("POSSIBLY_POST_STOP", trade["excursion_semantics"])

    def test_entry_same_bar_stop_uses_shared_one_held_bar(self):
        rows = bars(); rows[6]["low"] = 97.0
        trade = replay(rows)["trades"][0]
        self.assertEqual(trade["hold_ms"], I)
        expected = channel.old.common.evaluate_development_events(
            rows, [5], split_start_ms=0, split_end_ms=len(rows) * I,
            interval_ms=I, hold_bars=1)["trades"][0]
        for key in ("signal_index", "entry_index", "entry_price", "entry_ts", "mfe_bps", "mae_bps"):
            self.assertEqual(trade[key], expected[key])

    def test_entry_gap_cancel_no_trade_no_rescheduling(self):
        rows = bars(); rows[6].update(open=97.0, high=98.0, low=96.0, close=97.0)
        result = replay(rows)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["open_positions"], [])
        self.assertEqual(result["events"][0]["exclusion_reason"], "ENTRY_OPEN_NOT_ABOVE_PROTECTIVE_STOP")
        self.assertEqual(result["audit"]["exit_and_cancel_counts"]["entry_open_stop_cancellations"], 1)

    def test_held_signal_is_excluded_and_never_queued_after_stop(self):
        rows = bars(); rows[13]["low"] = 97.0
        result = replay(rows, [signal(), signal(11), signal(17)])
        self.assertEqual(result["events"][1]["exclusion_reason"], "SIGNAL_DURING_OPEN")
        self.assertEqual([t["entry_index"] for t in result["trades"] + result["open_positions"]], [6, 18])

    def test_both_confirmed_at_same_close_exit_priority_cash_cancels_entry(self):
        both = [signal(11, "DOWN"), signal(11)]
        cash = replay(signals=both)
        self.assertEqual(cash["events"][0]["exclusion_reason"], "OPPOSITE_SIGNAL_PRIORITY")
        self.assertEqual(cash["trades"] + cash["open_positions"], [])
        long = replay(signals=[signal()] + both)
        self.assertEqual(long["trades"][0]["exit_index"], 12)
        self.assertEqual(long["open_positions"], [])
        self.assertEqual(long["audit"]["exit_and_cancel_counts"]["simultaneous_confirmation_conflicts"], 1)

    def test_terminal_open_mark_at_common_end_no_exit_or_cost_fields(self):
        rows = bars(30); rows[23].update(close=105.0, high=106.0)
        result = replay(rows, [signal(17)], end=4 * D)
        self.assertEqual(result["trades"], [])
        opened = result["open_positions"][0]
        self.assertEqual((opened["entry_ts"], opened["mark_ts"], opened["hold_ms"]), (3 * D, 4 * D, D))
        self.assertEqual(opened["mark_price"], 105.0)
        self.assertAlmostEqual(opened["gross_mark_bps"], 500.0)
        self.assertFalse(opened["terminal_liquidation"])
        self.assertFalse(any(k in opened for k in ("exit_ts", "exit_price", "net_bps", "cost_bps")))
        self.assertEqual(result["events"][0]["status"], "CENSORED")
        changed = copy.deepcopy(rows)
        for row in changed[24:]:
            row.update(open=5000.0, high=6000.0, low=4000.0, close=5500.0)
        self.assertEqual(result, replay(changed, [signal(17)], end=4 * D))

    def test_stop_in_bar_closing_at_common_end_is_executed_without_force_close(self):
        rows = bars(30); rows[23]["low"] = 97.0
        result = replay(rows, [signal(17)], end=4 * D)
        self.assertEqual(result["trades"][0]["exit_ts"], 4 * D)
        self.assertEqual(result["trades"][0]["exit_reason"], "PROTECTIVE_STOP_INTRABAR")
        self.assertEqual(result["audit"]["forced_terminal_liquidations"], 0)

    def test_future_close_signal_or_non_daily_timestamp_is_rejected(self):
        for signals in ([signal(23)], [signal(6)], [signal(5), signal(5)]):
            with self.subTest(signals=signals):
                with self.assertRaises(RuntimeError):
                    replay(bars(30), signals, end=4 * D)

    def test_no_trade_baseline_and_input_immutability(self):
        rows = bars(); saved = copy.deepcopy(rows)
        signals = [signal(), signal(11, "DOWN")]; old_signals = copy.deepcopy(signals)
        replay(rows, signals)
        self.assertEqual(rows, saved); self.assertEqual(signals, old_signals)
        empty = replay(rows, [])
        self.assertEqual(empty["trades"] + empty["open_positions"] + empty["events"], [])
        self.assertEqual(empty["audit"]["short_entries"], 0)


if __name__ == "__main__":
    unittest.main()
