"""Synthetic Q0 channel-return exit, ownership and boundary tests only."""
from copy import deepcopy
import unittest

from backend.research.rebuild import break_channel_structure_v1 as q0
from backend.research.rebuild import parallel_exit_q0_v1 as child
from backend.research.rebuild.test_break_channel_structure_v1 import bars, signal

I, D = q0.INTERVAL, q0.DAY


def high_rows(n=36):
    rows = bars(n)
    for row in rows[6:]:
        row.update(open=110.0, high=111.0, low=109.0, close=110.0)
    return rows


def loss_close(rows, index, close=100.5):
    rows[index].update(low=min(99.0, close), close=close)


def replay(rows=None, signals=None, *, end=None, **kwargs):
    rows = high_rows() if rows is None else rows
    signals = [signal()] if signals is None else signals
    return child.replay(rows, {"signals": signals}, eval_start_ms=0,
                        eval_end_ms=end or rows[-1]["bar_close_ts"], **kwargs)


class ChannelExitTimingTests(unittest.TestCase):
    def test_equal_entry_upper_triggers_at_first_held_close_and_fills_next_open(self):
        rows = high_rows(); loss_close(rows, 6)
        rows[7].update(open=103.0, low=101.0, close=104.0)
        out = replay(rows)
        trade = out["trades"][0]
        self.assertEqual((trade["entry_index"], trade["exit_index"]), (6, 7))
        self.assertEqual((trade["exit_ts"], trade["exit_price"]), (7 * I, 103.0))
        self.assertEqual(trade["exit_reason"], child.EXIT_REASON)
        self.assertEqual(trade["hold_ms"], I)
        self.assertEqual(trade["entry_channel_exit_trigger"]["close"], 100.5)
        self.assertEqual(out["audit"]["channel_loss_triggers"], 1)
        self.assertEqual(len(out["trades"]), 1)

    def test_entry_price_below_upper_does_not_trigger_until_a_held_close(self):
        rows = high_rows(); rows[6].update(open=100.0, low=99.0)
        out = replay(rows)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["audit"]["channel_loss_triggers"], 0)
        self.assertEqual(out["open_positions"][0]["entry_price"], 100.0)

    def test_initial_signal_close_and_pre_entry_prices_are_not_exit_triggers(self):
        rows = high_rows()
        self.assertLess(rows[5]["close"], signal()["upper"])
        out = replay(rows)
        self.assertEqual(out["trades"], [])
        observations = [t for t in out["trace"] if t["kind"] == "ENTRY_CHANNEL_CLOSE_OBSERVED"]
        self.assertEqual(min(t["index"] for t in observations), 6)

    def test_later_up_channel_never_updates_frozen_upper_or_stop(self):
        rows = high_rows()
        out = replay(rows, [signal(), signal(11, lower=105.0, upper=115.0)])
        self.assertEqual(out["trades"], [])
        observation = out["open_positions"][0]
        self.assertEqual(observation["channel_upper"], 100.5)
        self.assertEqual(observation["entry_stop_price"], 98.0)
        self.assertTrue(all(t["frozen_entry_channel_upper"] == 100.5
                            for t in out["trace"] if "frozen_entry_channel_upper" in t))

    def test_same_bar_original_stop_suppresses_later_close_trigger(self):
        rows = high_rows(); loss_close(rows, 7, 99.0); rows[7]["low"] = 97.0
        out = replay(rows)
        self.assertEqual(out["trades"][0]["exit_reason"], "PROTECTIVE_STOP_INTRABAR")
        self.assertEqual(out["trades"][0]["exit_ts"], 8 * I)
        self.assertEqual(out["audit"]["channel_loss_triggers"], 0)
        self.assertFalse(any(t["kind"] == "ENTRY_CHANNEL_CLOSE_OBSERVED" and t["index"] == 7
                             for t in out["trace"]))

    def test_original_gap_stop_precedes_pending_channel_order(self):
        rows = high_rows(); loss_close(rows, 7)
        rows[8].update(open=97.0, high=111.0, low=96.0, close=110.0)
        trade = replay(rows)["trades"][0]
        self.assertEqual((trade["exit_reason"], trade["exit_price"], trade["exit_ts"]),
                         ("PROTECTIVE_STOP_GAP_OPEN", 97.0, 8 * I))
        self.assertIsNotNone(trade["entry_channel_exit_trigger"])

    def test_original_bear_exit_precedes_channel_exit_at_same_open(self):
        rows = high_rows(); loss_close(rows, 11)
        trade = replay(rows, [signal(), signal(11, "DOWN")])["trades"][0]
        self.assertEqual(trade["exit_reason"], "BEARISH_CONFIRMED_NEXT_OPEN")
        self.assertEqual((trade["exit_ts"], trade["exit_price"]), (12 * I, 110.0))
        self.assertTrue(trade["entry_channel_exit_trigger"]["original_bearish_exit_pending"])

    def test_gap_precedes_both_pending_exit_orders(self):
        rows = high_rows(); loss_close(rows, 11)
        rows[12].update(open=97.0, high=111.0, low=96.0, close=110.0)
        trade = replay(rows, [signal(), signal(11, "DOWN")])["trades"][0]
        self.assertEqual((trade["exit_reason"], trade["exit_price"]),
                         ("PROTECTIVE_STOP_GAP_OPEN", 97.0))

    def test_pending_channel_open_exit_precedes_that_bars_later_low(self):
        rows = high_rows(); loss_close(rows, 7)
        rows[8].update(open=106.0, high=9000.0, low=1.0, close=5000.0)
        trade = replay(rows)["trades"][0]
        self.assertEqual((trade["exit_reason"], trade["exit_price"]),
                         (child.EXIT_REASON, 106.0))
        self.assertAlmostEqual(trade["mfe_bps"], (111.0 / 110.0 - 1.0) * 10000.0)
        changed = deepcopy(rows); changed[8].update(high=112.0, low=105.0, close=109.0)
        self.assertEqual(trade, replay(changed)["trades"][0])

    def test_parent_entry_gap_cancellation_is_unchanged(self):
        rows = high_rows(); rows[6].update(open=97.0, low=96.0)
        out = replay(rows)
        self.assertEqual(out["trades"] + out["open_positions"], [])
        self.assertEqual(out["events"][0]["exclusion_reason"], "ENTRY_OPEN_NOT_ABOVE_PROTECTIVE_STOP")


class ChannelExitLifecycleTests(unittest.TestCase):
    def test_disabled_full_result_has_exact_parent_parity_including_trace_and_audit(self):
        rows = high_rows(); loss_close(rows, 7); rows[11]["low"] = 97.0
        signals = [signal(), signal(11), signal(17), signal(23, "DOWN"), signal(29)]
        expected = q0.replay(rows, {"signals": signals}, eval_start_ms=0, eval_end_ms=6 * D)
        self.assertEqual(replay(rows, signals, enable_change=False), expected)

    def test_when_condition_never_fires_native_trade_fields_are_unchanged(self):
        rows = high_rows(); rows[11]["low"] = 97.0
        signals = [signal(), signal(11), signal(23, "DOWN"), signal(29)]
        expected = q0.replay(rows, {"signals": signals}, eval_start_ms=0, eval_end_ms=6 * D)
        actual = replay(rows, signals)
        self.assertEqual(expected["events"], actual["events"])
        for key in ("trades", "open_positions"):
            self.assertEqual(len(expected[key]), len(actual[key]))
            for parent, candidate in zip(expected[key], actual[key]):
                for field, value in parent.items():
                    self.assertEqual(candidate[field], value, field)

    def test_trigger_bar_up_remains_occupied_and_is_not_resurrected(self):
        rows = high_rows(); loss_close(rows, 11)
        out = replay(rows, [signal(), signal(11), signal(17)])
        self.assertEqual([e["status"] for e in out["events"]], ["COMPLETED", "EXCLUDED", "CENSORED"])
        self.assertEqual(out["events"][1]["exclusion_reason"], "SIGNAL_DURING_OPEN")
        self.assertEqual([t["entry_index"] for t in out["trades"] + out["open_positions"]], [6, 18])

    def test_new_up_on_prior_intrabar_stop_close_can_enter_next_open(self):
        rows = high_rows(); rows[11]["low"] = 97.0
        out = replay(rows, [signal(), signal(11)])
        self.assertEqual([e["status"] for e in out["events"]], ["COMPLETED", "CENSORED"])
        self.assertEqual(out["open_positions"][0]["entry_index"], 12)

    def test_new_up_after_child_open_exit_can_enter_following_open(self):
        rows = high_rows(); loss_close(rows, 10)
        out = replay(rows, [signal(), signal(11)])
        self.assertEqual(out["trades"][0]["exit_index"], 11)
        self.assertEqual(out["open_positions"][0]["entry_index"], 12)

    def test_fixed_original_entries_and_full_new_occupancy_are_separate(self):
        rows = high_rows(); loss_close(rows, 7)
        signals = [signal(), signal(11), signal(23, "DOWN")]
        fixed = replay(rows, signals, fixed_signal_indices=[5])
        full = replay(rows, signals)
        self.assertEqual([t["signal_index"] for t in fixed["trades"]], [5])
        self.assertEqual([t["signal_index"] for t in full["trades"]], [5, 11])
        self.assertTrue(fixed["audit"]["fixed_origins_independent_diagnostic_positions"])
        self.assertEqual(full["audit"]["same_symbol_max_positions"], 1)

    def test_fixed_comparison_rejects_origins_parent_did_not_admit(self):
        signals = [signal(), signal(11)]
        for value in ([11], [5, 5], [True], [7]):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "FIXED_PARENT"):
                replay(signals=signals, fixed_signal_indices=value)

    def test_end_close_trigger_is_pending_open_mark_without_future_fill(self):
        rows = high_rows(30); loss_close(rows, 23)
        out = replay(rows, end=4 * D)
        self.assertEqual(out["trades"], [])
        observation = out["open_positions"][0]
        self.assertEqual((observation["mark_ts"], observation["mark_price"]), (4 * D, 100.5))
        self.assertEqual(observation["pending_exit_signal_ts"], 4 * D)
        self.assertEqual(observation["pending_exit_reason"], child.EXIT_REASON)
        self.assertFalse(observation["terminal_liquidation"])
        self.assertEqual(out["audit"]["pending_channel_exits_at_end"], 1)
        self.assertNotIn("exit_ts", observation)
        changed = deepcopy(rows)
        for row in changed[24:]:
            row.update(open=5000.0, high=6000.0, low=4000.0, close=5500.0)
        self.assertEqual(out, replay(changed, end=4 * D))

    def test_original_stop_at_end_remains_completed_not_forced_liquidated(self):
        rows = high_rows(30); rows[23].update(low=97.0, close=99.0)
        out = replay(rows, end=4 * D)
        self.assertEqual(out["open_positions"], [])
        self.assertEqual((out["trades"][0]["exit_ts"], out["trades"][0]["exit_reason"]),
                         (4 * D, "PROTECTIVE_STOP_INTRABAR"))
        self.assertEqual(out["audit"]["forced_terminal_liquidations"], 0)

    def test_changed_future_prices_signals_and_final_outcome_cannot_change_prior_exit(self):
        rows = high_rows(); loss_close(rows, 7)
        original = replay(rows)["trades"][0]
        changed = deepcopy(rows)
        for row in changed[9:]:
            row.update(open=2000.0, high=3000.0, low=1.0, close=2500.0)
        later = replay(changed, [signal(), signal(11), signal(17, "DOWN")])["trades"][0]
        self.assertEqual(original, later)

    def test_no_trade_input_immutability_invalid_enable_and_end_signal(self):
        rows = high_rows(); loss_close(rows, 7); signals = [signal()]
        before = deepcopy((rows, signals))
        replay(rows, signals)
        self.assertEqual((rows, signals), before)
        out = replay(rows, [])
        self.assertEqual(out["trades"] + out["open_positions"] + out["events"], [])
        with self.assertRaisesRegex(RuntimeError, "BOOL"):
            replay(enable_change=1)
        with self.assertRaisesRegex(RuntimeError, "FUTURE"):
            replay(signals=[signal(23)], end=4 * D)


if __name__ == "__main__":
    unittest.main()
