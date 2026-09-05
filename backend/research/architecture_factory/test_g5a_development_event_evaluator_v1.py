"""Synthetic regression coverage for the isolated development event helper."""
import copy
import unittest
from unittest.mock import patch

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import (
    evaluate_development_events,
)


STEP = 14_400_000
START = 1000 * STEP


def bars(count=20):
    return [
        {
            "bar_open_ts": START + index * STEP,
            "bar_close_ts": START + (index + 1) * STEP,
            "open": 100.0, "high": 110.0, "low": 90.0,
            "close": 102.0, "volume": 10.0,
        }
        for index in range(count)
    ]


class DevelopmentEventEvaluatorTests(unittest.TestCase):
    def evaluate(self, rows, signals, **overrides):
        arguments = {
            "split_start_ms": START, "split_end_ms": START + 20 * STEP,
            "interval_ms": STEP, "hold_bars": 6,
        }
        arguments.update(overrides)
        return evaluate_development_events(rows, signals, **arguments)

    def test_next_open_and_six_full_bars_use_close_timestamp(self):
        rows = bars()
        rows[0].update(open=75.0, high=85.0, low=70.0, close=80.0)
        trade = self.evaluate(rows, [0])["trades"][0]
        self.assertEqual(trade["signal_ts"], START + STEP)
        self.assertEqual(trade["entry_index"], 1)
        self.assertEqual(trade["entry_price"], 100.0)
        self.assertNotEqual(trade["entry_price"], rows[0]["close"])
        self.assertEqual(trade["exit_index"], 6)
        self.assertEqual(trade["exit_price"], rows[6]["close"])
        self.assertEqual(trade["entry_ts"], START + STEP)
        self.assertEqual(trade["exit_ts"], START + 7 * STEP)
        self.assertEqual(trade["hold_ms"], 24 * 60 * 60 * 1000)

    def test_long_and_short_gross_and_signed_excursions(self):
        for side, gross in (("long", 200.0), ("short", -200.0)):
            with self.subTest(side=side):
                trade = self.evaluate(bars(), [0], side=side)["trades"][0]
                self.assertAlmostEqual(trade["gross_bps"], gross)
                self.assertAlmostEqual(trade["mfe_bps"], 1000.0)
                self.assertAlmostEqual(trade["mae_bps"], -1000.0)

    def test_excursions_do_not_consume_post_exit_price_path(self):
        rows = bars()
        expected = self.evaluate(rows, [0])
        rows[7].update(high=10_000.0, low=0.01)
        self.assertEqual(self.evaluate(rows, [0]), expected)

    def test_one_bar_delay_moves_entry_and_preserves_holding_duration(self):
        rows = bars()
        rows[2]["open"] = 104.0
        trade = self.evaluate(rows, [0], entry_delay_bars=1)["trades"][0]
        self.assertEqual(trade["entry_index"], 2)
        self.assertEqual(trade["entry_price"], 104.0)
        self.assertEqual(trade["entry_ts"] - trade["signal_ts"], STEP)
        self.assertEqual(trade["exit_index"], 7)
        self.assertEqual(trade["hold_ms"], 6 * STEP)

    def test_split_end_exit_is_excluded_even_when_price_bar_is_present(self):
        result = self.evaluate(bars(), [13])
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["exclusions"], [{
            "signal_index": 13, "signal_ts": START + 14 * STEP,
            "reason": "SPLIT_END_INCOMPLETE_HOLD",
        }])

    def test_incomplete_holds_are_not_clamped_and_each_event_is_recorded(self):
        result = self.evaluate(bars(), [14, 17, 19])
        self.assertEqual(result["trades"], [])
        self.assertEqual([row["signal_index"] for row in result["exclusions"]], [14, 17, 19])
        self.assertEqual({row["reason"] for row in result["exclusions"]}, {"SPLIT_END_INCOMPLETE_HOLD"})

    def test_no_overlap_includes_exit_bar_and_delayed_entry_wait(self):
        result = self.evaluate(bars(), [0, 1, 6, 7, 8, 13, 14, 19])
        self.assertEqual([row["signal_index"] for row in result["trades"]], [0, 7])
        exclusions = {row["signal_index"]: row["reason"] for row in result["exclusions"]}
        for index in (1, 6, 8, 13):
            self.assertEqual(exclusions[index], "SIGNAL_DURING_OPEN")
        for index in (14, 19):
            self.assertEqual(exclusions[index], "SPLIT_END_INCOMPLETE_HOLD")
        delayed = self.evaluate(bars(), [0, 1, 2], entry_delay_bars=2)
        self.assertEqual(len(delayed["trades"]), 1)
        self.assertEqual([row["reason"] for row in delayed["exclusions"]], ["SIGNAL_DURING_OPEN"] * 2)

    def test_zero_signals_is_evaluated_empty_result_without_reject_or_pass(self):
        result = self.evaluate(bars(), [])
        self.assertEqual(result, {"trades": [], "exclusions": []})
        self.assertNotIn("NOT_RUN", str(result))
        self.assertNotIn("economic_pass", result)

    def test_future_or_holdout_appended_rows_block_even_with_no_signals(self):
        for signals in ([0], []):
            with self.subTest(signals=signals):
                with self.assertRaisesRegex(RuntimeError, "PARTITION_ROW_FORBIDDEN"):
                    self.evaluate(bars(21), signals)

    def test_bar_before_development_and_bar_crossing_end_are_blocked(self):
        before = bars()
        before[0]["bar_open_ts"] -= STEP
        before[0]["bar_close_ts"] -= STEP
        with self.assertRaisesRegex(RuntimeError, "PARTITION_ROW_FORBIDDEN"):
            self.evaluate(before, [1])
        with self.assertRaisesRegex(RuntimeError, "PARTITION_ROW_FORBIDDEN"):
            self.evaluate(bars(), [0], split_end_ms=START + 19 * STEP)

    def test_all_rows_are_validated_including_untraded_tail(self):
        for signals in ([0], []):
            with self.subTest(signals=signals):
                rows = bars()
                rows[-1]["volume"] = -1.0
                with self.assertRaisesRegex(RuntimeError, "BAR_VALUE_RANGE:volume"):
                    self.evaluate(rows, signals)

    def test_signal_order_uniqueness_type_and_range_are_required(self):
        for signals in ([0, 0], [2, 1], [-1], [20], [True], [1.0], [0, 20]):
            with self.subTest(signals=signals):
                with self.assertRaisesRegex(RuntimeError, "DEVELOPMENT_SIGNAL_"):
                    self.evaluate(bars(), signals)

    def test_zero_volume_is_valid_and_negative_volume_is_blocked(self):
        rows = bars()
        for row in rows:
            row["volume"] = 0.0
        self.assertEqual(len(self.evaluate(rows, [0])["trades"]), 1)
        rows[2]["volume"] = -0.01
        with self.assertRaisesRegex(RuntimeError, "BAR_VALUE_RANGE:volume"):
            self.evaluate(rows, [0])

    def test_nan_infinity_and_non_numeric_bar_values_are_blocked(self):
        for name in ("open", "high", "low", "close", "volume"):
            for value in (float("nan"), float("inf"), "100", None, True):
                with self.subTest(name=name, value=value):
                    rows = bars()
                    rows[-1][name] = value
                    with self.assertRaisesRegex(RuntimeError, "NONFINITE_BAR_VALUE"):
                        self.evaluate(rows, [0])

    def test_nonpositive_prices_and_invalid_ohlc_bounds_are_blocked(self):
        for name in ("open", "high", "low", "close"):
            rows = bars()
            rows[5][name] = 0.0
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "BAR_VALUE_RANGE"):
                self.evaluate(rows, [0])
        for update in ({"high": 99.0}, {"low": 103.0}, {"low": 115.0, "high": 110.0}):
            rows = bars()
            rows[5].update(update)
            with self.subTest(update=update), self.assertRaisesRegex(RuntimeError, "OHLC_BOUNDS_INVALID"):
                self.evaluate(rows, [0])

    def test_gap_duplicate_and_nonmonotonic_bars_are_blocked(self):
        rows = bars()
        for invalid in (rows[:8] + rows[9:], rows[:8] + [rows[7]] + rows[8:], rows[:8] + [rows[9], rows[8]] + rows[10:]):
            with self.assertRaisesRegex(RuntimeError, "GAP_DUPLICATE_OR_ORDER"):
                self.evaluate(invalid, [0])

    def test_timestamp_units_alignment_and_bar_duration_are_required(self):
        for name, value in (
            ("bar_open_ts", START / 1000),
            ("bar_open_ts", START + 1),
            ("bar_close_ts", START + STEP - 1),
            ("bar_close_ts", START + 2 * STEP),
        ):
            rows = bars()
            rows[0][name] = value
            with self.subTest(name=name, value=value), self.assertRaisesRegex(RuntimeError, "CLOCK"):
                self.evaluate(rows, [0])

    def test_invalid_execution_and_partition_parameters_are_blocked(self):
        invalid = (
            {"hold_bars": 0}, {"hold_bars": True}, {"hold_bars": 6.0},
            {"entry_delay_bars": -1}, {"side": "flat"},
            {"interval_ms": 3_600_000}, {"split_start_ms": START + 1},
            {"split_end_ms": START}, {"split_end_ms": START + 20 * STEP + 1},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(RuntimeError):
                self.evaluate(bars(), [0], **overrides)
        with self.assertRaisesRegex(RuntimeError, "ROWS_REQUIRED"):
            self.evaluate([], [])

    def test_identical_replay_preserves_inputs_and_requires_no_network(self):
        rows = bars()
        signals = [0, 2, 7, 19]
        original_rows, original_signals = copy.deepcopy(rows), list(signals)
        with patch("urllib.request.urlopen", side_effect=AssertionError("NETWORK_FORBIDDEN")):
            first = self.evaluate(rows, signals)
            second = self.evaluate(rows, signals)
        self.assertEqual(first, second)
        self.assertEqual(rows, original_rows)
        self.assertEqual(signals, original_signals)
        self.assertEqual(set(first), {"trades", "exclusions"})


if __name__ == "__main__":
    unittest.main()
