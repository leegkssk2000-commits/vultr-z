"""Synthetic-only passive BE observer parity and refutation tests.

All bars and counterfactual callbacks in this file are invented fixtures. They
are not a candidate rule, SSOT policy, saved K117 prices or economic evidence.
The frozen engine only executes these small fixtures, never native signals.
"""
from copy import deepcopy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import unittest

import pandas as pd


HERE = Path(__file__).resolve().parent
ENGINE_SHA = "d1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1"
POSITIVE_SHA = "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2"
TF = 1_800_000
COST = 14.0  # Synthetic frozen reference cost, not a deployed configuration.


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def frozen_path(name, digest):
    candidates = []
    if os.environ.get("K117_FROZEN_SOURCE_DIR"):
        candidates.append(Path(os.environ["K117_FROZEN_SOURCE_DIR"]) / name)
    candidates.extend([
        HERE.parents[4] / "backend/research/rebuild" / name,
        HERE.parents[5] / "evidence/k126_risk_ssot" / name,
    ])
    for path in candidates:
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            return path
    raise RuntimeError("PINNED_SYNTHETIC_TEST_SOURCE_REQUIRED:" + name + ":" + digest)


ENGINE_PATH = frozen_path("scalp7_execution_v2.py", ENGINE_SHA)
POSITIVE_PATH = frozen_path("scalp7_positive_lanes_v2.py", POSITIVE_SHA)
execution = load_module("k117_test_frozen_execution", ENGINE_PATH)
positive = load_module("k117_test_frozen_positive", POSITIVE_PATH)
observer_module = load_module("k117_test_be_observer", HERE / "be_observer.py")
SOURCE = ENGINE_PATH.read_text()


def bars(values, *, offsets=None):
    """First bar is a synthetic signal bar; all timestamps are UTC-aligned."""
    records = []
    for index, (opened, high, low, closed) in enumerate(values):
        start = (offsets[index] if offsets is not None else index) * TF
        records.append({
            "open_ts_ms": start, "close_ts_ms": start + TF,
            "available_ts_ms": start + TF, "segment_id": 0,
            "open": float(opened), "high": float(high),
            "low": float(low), "close": float(closed), "volume": 1.0,
        })
    return pd.DataFrame.from_records(records)


def mirror(values):
    return [(200 - o, 200 - low, 200 - high, 200 - close)
            for o, high, low, close in values]


def signal(side=1, *, max_hold=25):
    return {
        "identity": positive.KELTNER_PARENT, "lane": "keltner_holygrail",
        "symbol": "SYNTHETIC-USDT", "timeframe_min": 30,
        "signal_open_ts_ms": 0, "signal_ts_ms": TF, "segment_id": 0,
        "side": side, "stop_price": 90.0 if side == 1 else 110.0,
        "max_hold_bars": max_hold, "take_profit_r": None,
        "partial_take_profit_r": 2.0, "partial_fraction": 0.10,
        "meta": {"be_arm_r": 1.0, "frozen_cost_bps": COST},
    }


def execute(frame, *, sig=None, callback=None, observed=True):
    sig = deepcopy(sig or signal())
    callback = callback or positive.exit_update
    records, index = execution._frame_records(frame, 30)
    observer = observer_module.BEObserver()
    function = observer_module.instrument_single(
        execution._single, source_text=SOURCE, observer=observer, enabled=observed,
    )
    result = function(sig, frame.copy(deep=True), records, index, COST, callback)
    return result, observer.flat_events


def events(records, kind):
    return [row for row in records if row["kind"] == kind]


def toy_early_fee_be(position, bar, history):
    """Refutation fixture only: move existing fee-BE to the first close."""
    update = positive.exit_update(position, bar, history)
    if int(position["hold_bars"]) == 1:
        proposed = position["entry_price"] * (1 + position["side"] * (COST + 2) / 10_000)
        old = update.get("next_stop", position["stop_price"])
        update["next_stop"] = max(old, proposed) if position["side"] == 1 else min(old, proposed)
        update["reason"] = "SYNTHETIC_REFUTATION_EARLY_PROTECTION_NOT_A_RULE"
    return update


def toy_copy_cost2_into_be(position, bar, history):
    """Refutation fixture only: stress costs must not become an execution rule."""
    update = positive.exit_update(position, bar, history)
    if "next_stop" in update:
        proposed = position["entry_price"] * (1 + position["side"] * (2 * COST + 2) / 10_000)
        update["next_stop"] = max(update["next_stop"], proposed) if position["side"] == 1 else min(update["next_stop"], proposed)
        update["reason"] = "SYNTHETIC_REFUTATION_COST2_BUFFER_NOT_A_RULE"
    return update


class PassiveObserverTests(unittest.TestCase):
    def assert_parity(self, frame, **kwargs):
        before, unused = execute(frame, observed=False, **kwargs)
        after, trace = execute(frame, observed=True, **kwargs)
        self.assertEqual(unused, [])
        self.assertEqual(after, before)
        return after, trace

    def test_disabled_is_original_function_identity(self):
        observer = observer_module.BEObserver()
        wrapped = observer_module.instrument_single(execution._single, source_text=SOURCE,
                                                   observer=observer, enabled=False)
        self.assertIs(wrapped, execution._single)
        self.assertFalse(observer.records)

    def test_long_and_short_be_arm_next_bar_and_exact_return_parity(self):
        long = [(100, 101, 99, 100), (100, 111, 99, 110), (110, 111, 100.1, 100.2)]
        for side, values in [(1, long), (-1, mirror(long))]:
            with self.subTest(side=side):
                result, trace = self.assert_parity(bars(values), sig=signal(side))
                row = result[0]
                self.assertEqual(row["reason"], "STOP_FIRST")
                self.assertAlmostEqual(row["gross_bps"], 16.0, places=9)
                self.assertAlmostEqual(row["net_bps"], 2.0, places=9)
                self.assertEqual(row["hold_bars"], 2)
                self.assertEqual(len(events(trace, "CALLBACK_AFTER")), 1)
                self.assertEqual(len(events(trace, "STOP_APPLIED")), 1)
                arm = events(trace, "CALLBACK_AFTER")[0]
                self.assertTrue(arm["be_first_arm"])
                self.assertEqual(arm["available_ts_ms"], 2 * TF)
                start = events(trace, "BAR_START")[-1]
                self.assertEqual(start["bar_open_ts_ms"], 2 * TF)
                self.assertAlmostEqual(start["effective_stop"], 100 * (1 + side * 16 / 10_000))

    def test_same_bar_stop_precedes_favorable_extreme_be_and_partial(self):
        long = [(100, 101, 99, 100), (100, 140, 89, 120)]
        for side, values in [(1, long), (-1, mirror(long))]:
            with self.subTest(side=side):
                result, trace = self.assert_parity(bars(values), sig=signal(side))
                self.assertEqual(result[0]["reason"], "STOP_FIRST")
                self.assertEqual(result[0]["mfe_R"], 0.0)
                self.assertFalse(events(trace, "CALLBACK_AFTER"))
                self.assertFalse(events(trace, "PARTIAL_FILLED"))
                self.assertFalse(events(trace, "STOP_APPLIED"))

    def test_gap_after_be_uses_actual_next_open_and_can_be_negative(self):
        frame = bars([(100, 101, 99, 100), (100, 111, 99, 110), (99, 100, 98, 99)])
        result, trace = self.assert_parity(frame)
        row = result[0]
        self.assertEqual(row["reason"], "OPEN_GAP_STOP")
        self.assertEqual(row["exit_prices"]["SYNTHETIC-USDT"], 99.0)
        self.assertEqual(row["outcome_available_ts_ms"], 2 * TF)
        self.assertAlmostEqual(row["net_bps"], -114.0)
        self.assertEqual(len(events(trace, "TERMINAL")), 1)

    def test_missing_next_bar_retains_unresolved_ownership(self):
        frame = bars([(100, 101, 99, 100), (100, 111, 99, 110), (110, 112, 109, 111)],
                     offsets=[0, 1, 3])
        result, trace = self.assert_parity(frame)
        self.assertIsNone(result[0])
        self.assertEqual(result[1]["state"], "UNRESOLVED_GAP_OR_END")
        self.assertEqual(result[2], 2**63 - 1)
        self.assertFalse(events(trace, "TERMINAL"))
        self.assertEqual(len(events(trace, "UNRESOLVED")), 1)

    def test_entry_gap_remains_rejected_without_fabricated_position(self):
        frame = bars([(100, 101, 99, 100), (100, 111, 99, 110)], offsets=[0, 2])
        result, trace = self.assert_parity(frame)
        self.assertEqual(result, (None, None, -1, "ENTRY_GAP"))
        self.assertFalse(events(trace, "ENTRY"))
        self.assertEqual(len(events(trace, "REJECTED")), 1)

    def test_pending_exit_precedes_stop_and_mfe_on_next_bar(self):
        def pending(position, bar, history):
            update = positive.exit_update(position, bar, history)
            update.update(exit_next_open=True, reason="SYNTHETIC_ALREADY_DUE_EXIT")
            return update

        frame = bars([(100, 101, 99, 100), (100, 111, 99, 110), (89, 150, 88, 100)])
        result, trace = self.assert_parity(frame, callback=pending)
        row = result[0]
        self.assertEqual(row["reason"], "SYNTHETIC_ALREADY_DUE_EXIT")
        self.assertEqual(row["hold_bars"], 1)
        self.assertEqual(row["mfe_R"], 1.1)
        self.assertEqual(row["exit_prices"]["SYNTHETIC-USDT"], 89.0)
        self.assertEqual(events(trace, "BAR_START")[-1]["pending_exit_reason"], "SYNTHETIC_ALREADY_DUE_EXIT")

    def test_runner_request_survives_reason_override_but_pending_exit_has_precedence(self):
        def structural_pending(position, bar, history):
            update = positive.exit_update(position, bar, history)
            update.update(exit_next_open=True, reason="SYNTHETIC_STRUCTURAL_NEXT_OPEN")
            return update

        frame = bars([(100, 101, 99, 100), (100, 131, 99, 130), (117, 132, 116, 118)])
        result, trace = self.assert_parity(frame, callback=structural_pending)
        after = events(trace, "CALLBACK_AFTER")[0]
        self.assertTrue(after["runner_first_arm"])
        self.assertTrue(after["runner_branch_eligible_from_frozen_rule"])
        self.assertTrue(after["runner_request_consistent_with_frozen_rule"])
        self.assertTrue(after["final_reason_overrode_consistent_native_stop"])
        final_bar = events(trace, "BAR_START")[-1]
        self.assertFalse(final_bar["stop_effective_for_protective_check"])
        self.assertIsNone(final_bar["activation_of_request_event_seq"])
        terminal = events(trace, "TERMINAL")[0]
        self.assertEqual(terminal["precedence"], "PENDING_NEXT_OPEN_BEFORE_STOP")
        self.assertEqual(result[0]["reason"], "SYNTHETIC_STRUCTURAL_NEXT_OPEN")
        self.assertEqual(result[0]["exit_prices"]["SYNTHETIC-USDT"], 117.0)

    def test_partial_actual_fraction_and_remaining_gross_net_accounting(self):
        long = [(100, 101, 99, 100), (100, 121, 99, 120), (120, 121, 100, 101)]
        for side, values in [(1, long), (-1, mirror(long))]:
            with self.subTest(side=side):
                result, trace = self.assert_parity(bars(values), sig=signal(side))
                partial = events(trace, "PARTIAL_FILLED")[0]
                self.assertEqual(partial["partial_fraction"], 0.10)
                self.assertEqual(partial["remaining_before"], 1.0)
                self.assertEqual(partial["remaining_after"], 0.9)
                self.assertAlmostEqual(partial["realized_increment_bps"], 200.0)
                row = result[0]
                self.assertAlmostEqual(row["gross_bps"], 200 + 0.9 * 16, places=8)
                self.assertAlmostEqual(row["net_bps"], 200 + 0.9 * 16 - COST, places=8)
                # Cost is on the initial equal-notional trade, not multiplied by remaining twice.
                self.assertNotAlmostEqual(row["net_bps"], 200 + 0.9 * (16 - COST), places=6)
                state = events(trace, "STOP_APPLIED")[0]["position"]
                self.assertEqual(state["quantity_unit"], "FRACTION_OF_ORIGINAL_ENTRY_NOTIONAL")
                self.assertEqual(state["pnl_unit"], "ORIGINAL_EQUAL_NOTIONAL_TRADE_BPS")
                self.assertEqual(state["signal_frozen_cost_bps"], COST)
                self.assertEqual(state["cost_bps"], COST)
                self.assertTrue(state["future_carry_not_included"])
                self.assertTrue(state["cost2x_stress_is_not_execution_input"])
                self.assertAlmostEqual(state["net_at_exact_current_stop_fill_reference_bps"], row["net_bps"], places=8)

    def test_partial_then_runner_is_monotonic_and_not_double_counted(self):
        frame = bars([(100, 101, 99, 100), (100, 131, 99, 130), (130, 131, 117, 120)])
        result, trace = self.assert_parity(frame)
        self.assertTrue(events(trace, "CALLBACK_AFTER")[0]["runner_first_arm"])
        self.assertEqual(len(events(trace, "PARTIAL_FILLED")), 1)
        stop = events(trace, "STOP_APPLIED")[0]
        self.assertTrue(stop["monotonic"])
        self.assertAlmostEqual(stop["accepted_stop"], 118.5)
        self.assertAlmostEqual(result[0]["net_bps"], 200 + 0.9 * 1850 - COST, places=7)

    def test_invalid_partial_fraction_raises_identically_before_fill_event(self):
        def invalid(position, bar, history):
            update = positive.exit_update(position, bar, history)
            update["partial_fraction"] = 0.20
            return update

        frame = bars([(100, 101, 99, 100), (100, 121, 99, 120)])
        for observed in (False, True):
            with self.subTest(observed=observed):
                with self.assertRaisesRegex(ValueError, "PARTIAL_FILL_INVALID"):
                    execute(frame, callback=invalid, observed=observed)

    def test_callback_gets_only_closed_prefix_and_future_suffix_changes_nothing(self):
        observations = []

        def checked(position, bar, history):
            self.assertEqual(int(history.iloc[-1].open_ts_ms), int(bar["open_ts_ms"]))
            self.assertTrue((history.available_ts_ms <= bar["available_ts_ms"]).all())
            observations.append(len(history))
            return positive.exit_update(position, bar, history)

        original = [(100, 101, 99, 100), (100, 111, 99, 110),
                    (110, 111, 100.1, 100.2), (100, 150, 99, 140)]
        first, first_trace = execute(bars(original), callback=checked)
        original[-1] = (100, 500, 1, 300)
        second, second_trace = execute(bars(original), callback=checked)
        self.assertEqual(first, second)
        self.assertEqual(first_trace, second_trace)
        self.assertEqual(observations, [2, 2])

    def test_future_history_injected_into_callback_is_rejected(self):
        frame = bars([(100, 101, 99, 100), (100, 111, 99, 110), (110, 130, 109, 120)])

        def invalid(position, bar, history):
            return positive.exit_update(position, bar, frame)

        for observed in (False, True):
            with self.subTest(observed=observed):
                with self.assertRaisesRegex(ValueError, "POSITIVE_CLOSED_PREFIX_REQUIRED"):
                    execute(frame, callback=invalid, observed=observed)

    def test_late_completed_bar_is_unresolved_without_be_callback(self):
        frame = bars([(100, 101, 99, 100), (100, 111, 99, 110), (110, 112, 109, 111)])
        frame.loc[1, "available_ts_ms"] += 1
        result, trace = self.assert_parity(frame)
        self.assertIsNone(result[0])
        self.assertEqual(result[1]["position"]["unresolved_reason"], "LATE_BAR_AVAILABILITY")
        self.assertFalse(events(trace, "CALLBACK_AFTER"))

    def test_source_pin_rejects_modified_engine_for_enabled_observation(self):
        observer = observer_module.BEObserver()
        with self.assertRaises(ValueError):
            observer_module.instrument_single(execution._single, source_text=SOURCE + "\n",
                                              observer=observer, enabled=True)


class SyntheticRefutationTests(unittest.TestCase):
    """Existence counterexamples only; no fitted rule or aggregate economic claim."""

    def compare_early(self, values, *, max_hold=25):
        frame = bars(values)
        incumbent, _ = execute(frame, sig=signal(max_hold=max_hold))
        hypothetical, _ = execute(frame, sig=signal(max_hold=max_hold), callback=toy_early_fee_be)
        self.assertIsNotNone(incumbent[0])
        self.assertIsNotNone(hypothetical[0])
        return incumbent[0], hypothetical[0]

    def test_early_protection_can_remove_an_ordinary_winner(self):
        incumbent, early = self.compare_early([
            (100, 101, 99, 100), (100, 105, 99, 104),
            (104, 106, 100, 105), (106, 107, 104, 106),
        ], max_hold=2)
        self.assertLess(incumbent["mfe_R"], 1.0)
        self.assertGreater(incumbent["net_bps"], early["net_bps"])
        self.assertGreater(incumbent["net_bps"], 0)

    def test_early_protection_can_remove_a_large_runner_winner(self):
        incumbent, early = self.compare_early([
            (100, 101, 99, 100), (100, 105, 99, 104),
            (104, 106, 100, 105), (105, 132, 104, 131), (130, 131, 119, 120),
        ])
        self.assertGreaterEqual(incumbent["mfe_R"], 3.0)
        self.assertGreater(incumbent["net_bps"], early["net_bps"])
        self.assertAlmostEqual(early["net_bps"], 2.0, places=8)

    def test_early_protection_can_remove_a_recovery_winner(self):
        incumbent, early = self.compare_early([
            (100, 101, 99, 100), (100, 105, 99, 104),
            (104, 106, 97, 98), (98, 113, 97, 112), (112, 114, 110, 113),
        ], max_hold=3)
        self.assertGreaterEqual(incumbent["mae_R"], 0.3)
        self.assertGreater(incumbent["net_bps"], early["net_bps"])
        self.assertGreater(incumbent["net_bps"], 0)

    def test_early_protection_can_also_avoid_a_later_loss(self):
        incumbent, early = self.compare_early([
            (100, 101, 99, 100), (100, 105, 99, 104),
            (104, 106, 99, 100), (98, 99, 89, 90),
        ])
        self.assertLess(incumbent["net_bps"], 0)
        self.assertGreater(early["net_bps"], incumbent["net_bps"])
        self.assertGreater(early["net_bps"], 0)

    def test_existing_native_one_r_be_precedes_later_initial_stop_breach_label(self):
        values = [
            (100, 101, 99, 100), (100, 111, 99, 110),
            (110, 111, 99, 100), (100, 101, 89, 90),
        ]
        result, trace = execute(bars(values))
        row = result[0]
        self.assertEqual(row["reason"], "STOP_FIRST")
        self.assertAlmostEqual(row["net_bps"], 2.0, places=8)
        self.assertTrue(events(trace, "CALLBACK_AFTER")[0]["be_first_arm"])
        initial_stop = events(trace, "ENTRY")[0]["position"]["initial_stop"]
        self.assertEqual(initial_stop, 90.0)
        # This later raw suffix is only a counterfactual label. It is never
        # passed to a native callback after the actual BE trade terminates.
        self.assertLess(values[-1][2], initial_stop)
        self.assertEqual(row["outcome_available_ts_ms"], 3 * TF)
        self.assertFalse(any(e.get("bar_open_ts_ms") == 3 * TF for e in trace))

    def test_copying_double_cost_buffer_can_cut_an_existing_runner(self):
        frame = bars([
            (100, 101, 99, 100), (100, 111, 99, 110),
            (110, 112, 100.2, 110), (110, 132, 109, 131), (130, 131, 119, 120),
        ])
        incumbent, _ = execute(frame)
        tightened, _ = execute(frame, callback=toy_copy_cost2_into_be)
        self.assertGreaterEqual(incumbent[0]["mfe_R"], 3.0)
        self.assertLess(tightened[0]["mfe_R"], 3.0)
        self.assertGreater(incumbent[0]["net_bps"], tightened[0]["net_bps"])
        self.assertAlmostEqual(tightened[0]["gross_bps"], 30.0, places=8)
        self.assertAlmostEqual(tightened[0]["net_bps"], 16.0, places=8)

    def test_cost2_level_beyond_completed_close_is_not_an_immediate_fill(self):
        frame = bars([
            (100, 101, 99, 100), (100, 111, 99, 100.2),
            (100.1, 100.2, 99, 99.5),
        ])
        result, trace = execute(frame, callback=toy_copy_cost2_into_be)
        requested = events(trace, "CALLBACK_AFTER")[0]
        self.assertGreater(requested["update"]["next_stop"], requested["completed_close"])
        self.assertEqual(result[0]["reason"], "OPEN_GAP_STOP")
        self.assertEqual(result[0]["exit_prices"]["SYNTHETIC-USDT"], 100.1)
        self.assertAlmostEqual(result[0]["net_bps"], -4.0, places=8)


if __name__ == "__main__":
    unittest.main()
