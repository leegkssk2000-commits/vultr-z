"""Synthetic policy/causality tests; no historical DEV data is accessed."""
import copy
import unittest

from backend.research.rebuild import supertrend_flip_direction_dev_v1 as direction


INTERVAL = 14_400_000


def bars(n=10):
    return [{"bar_open_ts": i * INTERVAL,
             "bar_close_ts": (i + 1) * INTERVAL,
             "open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.0, "volume": 10.0} for i in range(n)]


def replay(rows, bull=(0,), bear=(2,), **kwargs):
    return direction.replay_direction(
        rows, bull, bear, split_start_ms=0,
        split_end_ms=kwargs.pop("split_end_ms", len(rows) * INTERVAL),
        **kwargs)


class DirectionPolicy(unittest.TestCase):
    def test_next_open_signal_identity_and_entry_bar_bear(self):
        result = replay(bars(), bear=(1,))
        trade = result["trades"][0]
        self.assertEqual((trade["signal_index"], trade["entry_index"],
                          trade["exit_index"]), (0, 1, 2))
        self.assertEqual(trade["signal_ts"], INTERVAL)
        self.assertEqual(trade["entry_ts"], INTERVAL)
        self.assertEqual(trade["exit_ts"], 2 * INTERVAL)
        self.assertEqual(trade["hold_ms"], INTERVAL)
        self.assertEqual(trade["side"], "long")

    def test_next_open_gap_is_filled_but_later_exit_bar_range_is_not_used(self):
        rows = bars()
        rows[3].update(open=130.0, low=120.0, high=99999.0, close=140.0)
        trade = replay(rows)["trades"][0]
        self.assertEqual(trade["exit_price"], 130.0)
        self.assertAlmostEqual(trade["gross_bps"], 3000.0)
        self.assertAlmostEqual(trade["mfe_bps"], 3000.0)
        self.assertAlmostEqual(trade["mae_bps"], -100.0)
        rows[3].update(high=999999.0, low=0.01, close=200.0)
        self.assertEqual(trade, replay(rows)["trades"][0])

    def test_missing_time_bar_is_rejected_even_without_signals(self):
        rows = bars()
        del rows[4]
        with self.assertRaisesRegex(RuntimeError, "GAP_DUPLICATE_OR_ORDER"):
            replay(rows, bull=(), bear=(), split_end_ms=10 * INTERVAL)

    def test_invalid_signal_sequences_and_contradictory_flips_fail(self):
        for bull, bear, error in [((0, 0), (2,), "DUPLICATE_OR_ORDER"),
                                   ((True,), (2,), "SIGNAL_INDEX_INVALID"),
                                   ((0,), (10,), "SIGNAL_INDEX_INVALID"),
                                   ((0,), (0,), "CONTRADICTORY_FLIP")]:
            with self.subTest(bull=bull, bear=bear):
                with self.assertRaisesRegex(RuntimeError, error):
                    replay(bars(), bull=bull, bear=bear)

    def test_closed_trade_matches_shared_geometry_when_no_price_gap(self):
        rows = bars()
        rows[2].update(close=105.0, high=106.0)
        rows[3].update(open=105.0, close=105.0, low=104.0, high=106.0)
        actual = replay(rows)["trades"][0]
        expected = direction.old.common.evaluate_development_events(
            rows, [0], split_start_ms=0, split_end_ms=10 * INTERVAL,
            interval_ms=INTERVAL, hold_bars=2)["trades"][0]
        for field in expected:
            if field != "exit_index":
                self.assertEqual(actual[field], expected[field], field)

    def test_exit_bar_close_can_schedule_new_long_without_extra_cooldown(self):
        result = replay(bars(15), bull=(0, 3), bear=(2, 5))
        self.assertEqual([t["signal_index"] for t in result["trades"]], [0, 3])
        self.assertEqual([t["entry_index"] for t in result["trades"]], [1, 4])
        self.assertEqual([t["exit_index"] for t in result["trades"]], [3, 6])

    def test_full_occupancy_and_fixed_origin_diagnostics_are_distinct(self):
        rows = bars(15)
        full = replay(rows, bull=(0, 2, 6), bear=(4, 8))
        fixed = replay(rows, bull=(0, 2, 6), bear=(4, 8), fixed_origins=True)
        self.assertEqual([t["signal_index"] for t in full["trades"]], [0, 6])
        self.assertEqual([t["signal_index"] for t in fixed["trades"]], [0, 2, 6])
        self.assertEqual(full["events"][1]["exclusion_reason"], "SIGNAL_DURING_OPEN")
        self.assertTrue(all(t["fixed_origin_diagnostic"] for t in fixed["trades"]))

    def test_unfinished_position_is_marked_without_fabricated_exit_or_cost(self):
        result = replay(bars(), bear=())
        self.assertEqual(result["trades"], [])
        position = result["open_positions"][0]
        self.assertEqual(position["mark_index"], 8)
        self.assertEqual(position["mark_ts"], 9 * INTERVAL)
        self.assertEqual(position["hold_ms"], 8 * INTERVAL)
        self.assertEqual(position["gross_mark_bps"], 0.0)
        self.assertEqual(position["status"], "CENSORED")
        self.assertFalse(position["terminal_liquidation"])
        self.assertIsNone(position["pending_exit_signal_index"])
        self.assertFalse(set(position) & {"exit_ts", "exit_price", "exit_index",
                                         "gross_bps", "net_bps", "cost_bps"})
        self.assertEqual(result["events"][0]["status"], "CENSORED")
        self.assertFalse(any(t["kind"] == "EXIT_NEXT_OPEN" for t in result["trace"]))

    def test_final_decoded_open_fills_confirmed_exit_without_final_hlc(self):
        rows = bars()
        rows[9].update(open=120.0, high=99999.0, low=0.001, close=130.0)
        result = replay(rows, bear=(8,))
        self.assertEqual(result["open_positions"], [])
        trade = result["trades"][0]
        self.assertEqual(trade["exit_index"], 9)
        self.assertEqual(trade["exit_ts"], 9 * INTERVAL)
        self.assertEqual(trade["exit_price"], 120.0)
        self.assertAlmostEqual(trade["mfe_bps"], 2000.0)
        self.assertAlmostEqual(trade["mae_bps"], -100.0)

    def test_confirmed_exit_without_observed_next_open_remains_pending(self):
        # Shared validation permits an already isolated contiguous prefix.
        # No next bar may be invented beyond this actual input availability.
        result = replay(bars(9), bear=(8,), split_end_ms=10 * INTERVAL)
        self.assertEqual(result["trades"], [])
        position = result["open_positions"][0]
        self.assertEqual(position["pending_exit_signal_index"], 8)
        self.assertEqual(position["mark_ts"], 9 * INTERVAL)
        self.assertTrue(result["trace"][-1]["pending_exit"])

    def test_last_decoded_close_is_not_signal_or_mark_input(self):
        rows = bars()
        result = replay(rows, bear=(9,))
        self.assertEqual(result["trades"], [])
        self.assertIsNone(result["open_positions"][0]["pending_exit_signal_index"])
        rows[9].update(open=200.0, high=900.0, low=1.0, close=800.0)
        self.assertEqual(result, replay(rows, bear=(9,)))

    def test_no_future_dependency_for_completed_fills_or_trace(self):
        prefix = bars()
        a = replay(prefix)
        extended = bars(20)
        for row in extended[4:]:
            row.update(open=300.0, close=400.0, high=500.0, low=250.0)
        b = replay(extended, bear=(2, 15))
        self.assertEqual(a["trades"], b["trades"])
        self.assertEqual(a["trace"], b["trace"])

    def test_open_full_position_blocks_later_origins(self):
        full = replay(bars(), bull=(0, 2), bear=())
        fixed = replay(bars(), bull=(0, 2), bear=(), fixed_origins=True)
        self.assertEqual(len(full["open_positions"]), 1)
        self.assertEqual(len(fixed["open_positions"]), 2)
        self.assertEqual(full["events"][1]["exclusion_reason"], "SIGNAL_DURING_OPEN")

    def test_input_objects_are_preserved_and_final_entry_is_excluded(self):
        rows, bull, bear = bars(), [0, 9], [2]
        before = copy.deepcopy((rows, bull, bear))
        result = replay(rows, bull=bull, bear=bear)
        self.assertEqual((rows, bull, bear), before)
        self.assertEqual(result["events"][1]["exclusion_reason"],
                         "ENTRY_OUTSIDE_USABLE_BARS")

    def test_invalid_fixed_mode_or_final_row_integrity_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "BOOL_REQUIRED"):
            replay(bars(), fixed_origins=1)
        rows = bars()
        rows[-1]["high"] = float("nan")
        with self.assertRaisesRegex(RuntimeError, "NONFINITE_BAR_VALUE"):
            replay(rows, bull=(), bear=())


if __name__ == "__main__":
    unittest.main()
