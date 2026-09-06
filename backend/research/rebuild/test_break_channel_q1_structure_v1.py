"""Synthetic Q1 execution tests only; no source data or economic trial."""
from copy import deepcopy
import unittest

from backend.research.rebuild import break_channel_structure_v1 as q0
from backend.research.rebuild import break_channel_q1_structure_v1 as q1
from backend.research.rebuild.test_break_channel_structure_v1 import bars, signal

I, D = q0.INTERVAL, q0.DAY


def high_rows(n=36):
    rows = bars(n)
    for row in rows[6:]:
        row.update(open=110.0, high=111.0, low=109.0, close=110.0)
    return rows


def run(rows=None, signals=None, **kwargs):
    rows = high_rows() if rows is None else rows
    signals = [signal(), signal(11, lower=105.0), signal(23, "DOWN")] if signals is None else signals
    end = kwargs.pop("end", rows[-1]["bar_close_ts"])
    return q1.replay(rows, {"signals": signals}, eval_start_ms=0,
                     eval_end_ms=end, **kwargs)


class RatchetPositionTests(unittest.TestCase):
    def test_original_entry_initial_stop_and_metadata_preserved(self):
        rows = high_rows(); rows[12]["low"] = 104.0
        signals = [signal(), signal(11, lower=105.0), signal(23, "DOWN")]
        parent = q0.replay(rows, {"signals": signals}, eval_start_ms=0,
                           eval_end_ms=len(rows)*I)["trades"][0]
        child = run(rows, signals)["trades"][0]
        for field in ("signal_index", "signal_ts", "entry_index", "entry_ts",
                      "entry_price", "entry_stop_price", "entry_signal_metadata",
                      "channel_upper", "channel_lower", "channel_anchor_ts"):
            self.assertEqual(child[field], parent[field])
        self.assertEqual(child["entry_stop_price"], 98.0)
        self.assertEqual(child["effective_exit_stop_price"], 105.0)

    def test_higher_level_activates_only_next_open(self):
        rows = high_rows(); rows[11]["low"] = 104.0; rows[13]["low"] = 104.0
        out = run(rows)
        trade = out["trades"][0]
        self.assertEqual((trade["exit_index"], trade["exit_ts"], trade["exit_price"]),
                         (13, 14*I, 105.0))
        activation = next(t for t in out["trace"] if t["kind"] == "Q1_RATCHET_ACTIVATED_NEXT_OPEN")
        self.assertEqual((activation["index"], activation["ts"], activation["trigger_signal_ts"]),
                         (12, 12*I, 12*I))
        self.assertEqual(trade["exit_reason"], "Q1_RATCHET_STOP_INTRABAR")

    def test_gap_fills_observed_open_after_ratchet_activation(self):
        rows = high_rows(); rows[12].update(open=104.0, high=110.0, low=103.0, close=109.0)
        trade = run(rows)["trades"][0]
        self.assertEqual((trade["exit_index"], trade["exit_ts"], trade["exit_price"]), (12, 12*I, 104.0))
        self.assertEqual(trade["exit_reason"], "Q1_RATCHET_STOP_GAP_OPEN")
        self.assertFalse(trade["intrabar_stop_timing_unknown"])
        self.assertEqual(trade["hold_ms"], 6*I)

    def test_lower_and_equal_later_channels_never_lower_the_stop(self):
        signals = [signal(), signal(11, lower=105.0), signal(17, lower=101.0), signal(23, lower=105.0)]
        out = run(signals=signals)
        self.assertEqual(out["open_positions"][0]["effective_mark_stop_price"], 105.0)
        self.assertEqual(out["audit"]["ratchet_activations"], 1)
        observations = [t for t in out["trace"] if t["kind"] == "Q1_HELD_PREPARED_UP_OBSERVED"]
        self.assertEqual([t["update_scheduled"] for t in observations], [True, False, False])

    def test_initial_up_is_not_a_post_entry_ratchet(self):
        out = run(signals=[signal()])
        self.assertEqual(out["audit"]["ratchet_activations"], 0)
        self.assertFalse(any(t["kind"] == "Q1_HELD_PREPARED_UP_OBSERVED" for t in out["trace"]))

    def test_original_protective_stop_remains_before_any_reconfirmation(self):
        rows = high_rows(); rows[7]["low"] = 97.0
        trade = run(rows)["trades"][0]
        self.assertEqual((trade["exit_reason"], trade["exit_price"], trade["exit_ts"]),
                         ("PROTECTIVE_STOP_INTRABAR", 98.0, 8*I))

    def test_higher_stop_wins_when_both_levels_cross_intrabar(self):
        rows = high_rows(); rows[12]["low"] = 97.0
        trade = run(rows)["trades"][0]
        self.assertEqual((trade["exit_reason"], trade["exit_price"]), ("Q1_RATCHET_STOP_INTRABAR", 105.0))

    def test_bearish_next_open_precedes_later_intrabar_ratchet_touch(self):
        rows = high_rows(); rows[12]["low"] = 104.0
        signals = [signal(), signal(11, "DOWN"), signal(11, lower=105.0)]
        trade = run(rows, signals)["trades"][0]
        self.assertEqual((trade["exit_reason"], trade["exit_price"], trade["exit_ts"]),
                         ("BEARISH_CONFIRMED_NEXT_OPEN", 110.0, 12*I))
        self.assertEqual(trade["effective_exit_stop_price"], 105.0)

    def test_activated_gap_stop_precedes_pending_bearish_exit(self):
        rows = high_rows(); rows[12].update(open=104.0, high=110.0, low=103.0, close=109.0)
        signals = [signal(), signal(11, "DOWN"), signal(11, lower=105.0)]
        trade = run(rows, signals)["trades"][0]
        self.assertEqual(trade["exit_reason"], "Q1_RATCHET_STOP_GAP_OPEN")
        self.assertEqual(trade["exit_price"], 104.0)

    def test_gap_exit_cannot_read_that_bars_later_range_or_close(self):
        rows = high_rows(); rows[12].update(open=104.0, high=110.0, low=103.0, close=109.0)
        before = run(rows)["trades"][0]
        rows[12].update(high=9000.0, low=0.1, close=7000.0)
        self.assertEqual(before, run(rows)["trades"][0])
        self.assertAlmostEqual(before["mfe_bps"], (111.0 / 110.0 - 1) * 10000)

    def test_entry_gap_cancellation_preserved(self):
        rows = high_rows(); rows[6].update(open=97.0, high=111.0, low=96.0, close=110.0)
        out = run(rows, [signal()])
        self.assertEqual(out["trades"] + out["open_positions"], [])
        self.assertEqual(out["events"][0]["exclusion_reason"], "ENTRY_OPEN_NOT_ABOVE_PROTECTIVE_STOP")


class RatchetLifecycleTests(unittest.TestCase):
    def test_post_ratchet_flattening_does_not_queue_old_blocked_up(self):
        rows = high_rows(); rows[12]["low"] = 104.0
        out = run(rows, [signal(), signal(11, lower=105.0), signal(17, lower=99.0)])
        self.assertEqual([e["status"] for e in out["events"]], ["COMPLETED", "EXCLUDED", "CENSORED"])
        self.assertEqual(out["events"][1]["exclusion_reason"], "SIGNAL_DURING_OPEN")
        self.assertEqual([t["entry_index"] for t in out["trades"] + out["open_positions"]], [6, 18])

    def test_stop_bar_close_new_up_is_admitted(self):
        rows = high_rows(); rows[11]["low"] = 97.0
        out = run(rows, [signal(), signal(11, lower=99.0)])
        self.assertEqual([e["status"] for e in out["events"]], ["COMPLETED", "CENSORED"])
        self.assertEqual(out["open_positions"][0]["entry_index"], 12)
        self.assertEqual(out["audit"]["ratchet_activations"], 0)

    def test_up_while_exit_pending_is_not_resurrected_at_next_open(self):
        signals = [signal(), signal(11, "DOWN"), signal(11, lower=105.0)]
        out = run(signals=signals)
        self.assertEqual(len(out["trades"]), 1)
        self.assertEqual(out["open_positions"], [])
        self.assertEqual(out["events"][1]["exclusion_reason"], "OPPOSITE_SIGNAL_PRIORITY")

    def test_disabled_full_economics_events_ownership_and_open_parity(self):
        rows = high_rows(); rows[11]["low"] = 97.0
        signals = [signal(), signal(11, lower=99.0), signal(17, lower=100.0), signal(23, "DOWN"), signal(29, lower=99.0)]
        expected = q0.replay(rows, {"signals": signals}, eval_start_ms=0, eval_end_ms=len(rows)*I)
        actual = run(rows, signals, enable_change=False)
        for field in ("trades", "open_positions", "events"):
            self.assertEqual(actual[field], expected[field])

    def test_enabled_without_ratchet_preserves_native_economics(self):
        rows = high_rows(); rows[11]["low"] = 97.0
        signals = [signal(), signal(11, lower=99.0), signal(23, "DOWN")]
        expected = q0.replay(rows, {"signals": signals}, eval_start_ms=0, eval_end_ms=len(rows)*I)
        actual = run(rows, signals)
        self.assertEqual(actual["events"], expected["events"])
        for a, b in zip(actual["trades"], expected["trades"]):
            for field in b:
                self.assertEqual(a[field], b[field])

    def test_fixed_origins_independent_include_every_specified_origin(self):
        signals = [signal(), signal(11, lower=105.0), signal(17, lower=106.0)]
        out = run(signals=signals, fixed_signal_indices=[5, 11, 17])
        self.assertEqual([e["status"] for e in out["events"]], ["CENSORED"] * 3)
        self.assertEqual([t["signal_index"] for t in out["open_positions"]], [5, 11, 17])
        self.assertTrue(out["audit"]["fixed_origins_independent_diagnostic_positions"])
        full = run(signals=signals)
        self.assertEqual([t["signal_index"] for t in full["open_positions"]], [5])

    def test_fixed_original_q0_set_and_full_replay_are_distinct(self):
        rows = high_rows(); rows[12]["low"] = 104.0
        signals = [signal(), signal(11, lower=105.0), signal(17, lower=99.0)]
        parent = q0.replay(rows, {"signals": signals}, eval_start_ms=0, eval_end_ms=len(rows)*I)
        origins = [t["signal_index"] for t in parent["trades"] + parent["open_positions"]]
        fixed = run(rows, signals, fixed_signal_indices=origins)
        full = run(rows, signals)
        self.assertEqual([t["signal_index"] for t in fixed["trades"]], [5])
        self.assertEqual(fixed["open_positions"], [])
        self.assertEqual([t["signal_index"] for t in full["open_positions"]], [17])

    def test_terminal_mark_remains_open_without_forced_exit(self):
        rows = high_rows(30)
        out = run(rows, [signal(), signal(11, lower=105.0)], end=4*D)
        observation = out["open_positions"][0]
        self.assertEqual((observation["mark_ts"], observation["mark_price"]), (4*D, 110.0))
        self.assertEqual(observation["effective_mark_stop_price"], 105.0)
        self.assertFalse(observation["terminal_liquidation"])
        self.assertFalse(any(k in observation for k in ("exit_ts", "net_bps", "cost_bps")))
        changed = deepcopy(rows)
        for row in changed[24:]:
            row.update(open=2000.0, high=3000.0, low=1000.0, close=2500.0)
        self.assertEqual(out, run(changed, [signal(), signal(11, lower=105.0)], end=4*D))

    def test_stop_on_last_held_bar_is_rule_exit_not_forced_liquidation(self):
        rows = high_rows(30); rows[23]["low"] = 104.0
        out = run(rows, [signal(), signal(11, lower=105.0)], end=4*D)
        self.assertEqual(out["trades"][0]["exit_ts"], 4*D)
        self.assertEqual(out["trades"][0]["exit_reason"], "Q1_RATCHET_STOP_INTRABAR")
        self.assertEqual(out["audit"]["forced_terminal_liquidations"], 0)

    def test_prefix_closed_trade_is_invariant_to_later_prices_and_signals(self):
        rows = high_rows(); rows[12]["low"] = 104.0
        earlier = run(rows, [signal(), signal(11, lower=105.0)], end=3*D)["trades"][0]
        changed = deepcopy(rows)
        for row in changed[18:]:
            row.update(open=1000.0, high=1001.0, low=999.0, close=1000.0)
        later = run(changed, [signal(), signal(11, lower=105.0), signal(23, lower=900.0)])["trades"][0]
        self.assertEqual(earlier, later)

    def test_invalid_fixed_origins_enable_and_future_signal_rejected(self):
        for value in ([5, 5], [7], [True]):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                run(fixed_signal_indices=value)
        with self.assertRaises(RuntimeError):
            run(enable_change=1)
        with self.assertRaises(RuntimeError):
            run(signals=[signal(23)], end=4*D)

    def test_no_trade_reference_and_input_immutability(self):
        rows = high_rows(); signals = [signal(), signal(11, lower=105.0)]
        before = deepcopy((rows, signals))
        run(rows, signals)
        self.assertEqual((rows, signals), before)
        out = run(rows, [])
        self.assertEqual(out["trades"] + out["open_positions"] + out["events"], [])


if __name__ == "__main__":
    unittest.main()
