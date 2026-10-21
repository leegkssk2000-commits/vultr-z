"""Synthetic state/clock parity only; never loads the saved market frames."""
from copy import deepcopy
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.research.rebuild import scalp7_positive_lanes_v2 as native

SPEC = importlib.util.spec_from_file_location("work_c_origin_observer", Path(__file__).with_name("observer.py"))
o = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(o)
TF = o.TF_MS


def bar(i, *, side=1, low=98.0, high=103.0, close=101.0, adx=35.0, **extra):
    opening = i * TF
    values = {f"g{n}": 100.0 + side * (len(native.LONG_GMMA) - j) + side * i * 0.05
              for j, n in enumerate(native.LONG_GMMA)}
    return {**values, "g20": 100.0 + side * i * 0.05,
            "adx14": adx, "open_ts_ms": opening, "close_ts_ms": opening + TF,
            "available_ts_ms": opening + TF, "feature_available_ts_ms": opening + TF,
            "segment_id": "synthetic", "open": 101.0, "high": high, "low": low,
            "close": close, "hi20": 120.0, "lo20": 80.0, **extra}


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.state = native.HolyGrailState()
        self.watcher = o.OriginObserver("SYNTHETIC")

    def call(self, row, previous):
        original_state = deepcopy(self.state)
        original_row, original_previous = deepcopy(row), deepcopy(previous)
        expected = native._hg_event(original_state, deepcopy(row), deepcopy(previous))
        with patch.object(native, "_hg_event", wraps=native._hg_event) as wrapped:
            event, record = o.observed_hg_call(self.watcher, self.state, row, previous)
            self.assertEqual(wrapped.call_count, 1)
        self.assertEqual(event, expected)
        self.assertEqual(asdict(self.state), asdict(original_state))
        self.assertEqual(row, original_row)
        self.assertEqual(previous, original_previous)
        json.dumps(record, allow_nan=False)
        return event, record

    def touch(self):
        return self.call(bar(1), bar(0))

    def test_touch_has_native_origin_clock_and_parity(self):
        event, record = self.touch()
        self.assertIsNone(event)
        self.assertIn("NATIVE_EMA20_TOUCH", record["native_transitions"])
        self.assertEqual(record["origin_after_native"]["touch"]["available_ts_ms"], 2 * TF)
        self.assertEqual(record["origin_after_native"]["pull_low"]["price"], 98)
        self.assertLessEqual(record["native_inputs_asof"]["row_ohlc"]["low"], record["native_inputs_asof"]["ema20"])
        self.assertEqual(record["native_inputs_asof"]["previous_ohlc"]["high"], 103)

    def test_equal_raw_low_is_not_new_state_origin(self):
        self.touch()
        _, record = self.call(bar(2), bar(1))
        self.assertTrue(record["current_bar_equal_price_matches"]["low_equals_retained_pull_low"])
        self.assertEqual(record["origin_after_native"]["pull_low"]["open_ts_ms"], TF)

    def test_strict_extreme_update_has_new_origin(self):
        self.touch()
        _, record = self.call(bar(2, low=97, high=104), bar(1))
        self.assertEqual(record["origin_after_native"]["pull_low"]["open_ts_ms"], 2 * TF)
        self.assertEqual(record["origin_after_native"]["pull_high"]["open_ts_ms"], 2 * TF)
        self.assertEqual(record["origin_after_native"]["touch"]["open_ts_ms"], TF)

    def test_weak_state_retains_origin_without_accumulating_low(self):
        self.touch()
        _, record = self.call(bar(2, low=80, high=110, adx=27), bar(1))
        self.assertEqual(self.state.pull_low, 98)
        self.assertEqual(record["origin_after_native"]["pull_low"]["price"], 98)
        self.assertEqual(record["features_asof"]["weak_bars_retained_since_observed_touch"], 1)

    def test_flat_ema20_weak_state_also_retains(self):
        self.touch()
        _, record = self.call(bar(2, g20=100.05), bar(1))
        self.assertFalse(record["features_asof"]["strong"])
        self.assertEqual(self.state.stage, 1)

    def test_adx24_resets_all_state_and_origin(self):
        self.touch()
        _, record = self.call(bar(2, adx=24), bar(1))
        self.assertEqual(self.state.stage, 0)
        self.assertTrue(all(v is None for v in record["origin_after_native"].values()))

    def test_unordered_gmma_resets(self):
        self.touch()
        _, record = self.call(bar(2, g60=1000), bar(1))
        self.assertIn("NATIVE_WEAK_OR_UNORDERED_RESET", record["native_transitions"])
        self.assertEqual(self.state.side, 0)

    def test_opposite_side_retouch_origin_replaced(self):
        self.touch()
        _, record = self.call(bar(2, side=-1, low=95, high=103, close=98), bar(1))
        self.assertIn("NATIVE_SIDE_RESET", record["native_transitions"])
        self.assertIn("NATIVE_EMA20_TOUCH", record["native_transitions"])
        self.assertEqual(record["origin_after_native"]["touch"]["open_ts_ms"], 2 * TF)
        self.assertEqual(self.state.side, -1)

    def test_short_origin_accumulation(self):
        self.call(bar(1, side=-1), bar(0, side=-1))
        event, record = self.call(bar(2, side=-1, high=105, low=95, close=96), bar(1, side=-1))
        self.assertEqual(event, (-1, 105))
        self.assertEqual(record["origin_after_native"]["pull_high"]["open_ts_ms"], 2 * TF)

    def test_turn_preserves_pull_origin(self):
        self.touch()
        event, record = self.call(bar(2, high=106, close=105), bar(1))
        self.assertEqual(event, (1, 98))
        self.assertEqual(record["origin_after_native"]["pull_low"]["open_ts_ms"], TF)
        self.assertTrue(self.state.episode_traded)

    def test_accepted_episode_waits_then_rearms(self):
        self.touch()
        self.call(bar(2, high=106, close=105), bar(1))
        _, wait = self.call(bar(3, high=110), bar(2, high=106, close=105))
        self.assertIn("NATIVE_ACCEPTED_EPISODE_WAITING_REARM", wait["native_transitions"])
        _, rearm = self.call(bar(4, high=121), bar(3, high=110))
        self.assertIn("NATIVE_REARM_AFTER_NEW_20BAR_EXTREME", rearm["native_transitions"])
        self.assertEqual(self.state.stage, 0)
        _, retouch = self.call(bar(5), bar(4, high=121))
        self.assertEqual(retouch["origin_after_native"]["touch"]["open_ts_ms"], 5 * TF)

    def test_mid_episode_origin_unknown_not_price_guessed(self):
        self.state = native.HolyGrailState(side=1, stage=1, pull_low=98, pull_high=103)
        _, record = self.call(bar(1), bar(0))
        self.assertIsNone(record["origin_after_native"]["pull_low"])
        self.assertTrue(record["current_bar_equal_price_matches"]["low_equals_retained_pull_low"])

    def event_record(self):
        self.touch()
        _, record = self.call(bar(2, high=106, close=105), bar(1))
        return record

    def test_regime_ineligible_unconsumes_but_does_not_reset_origins(self):
        record = self.event_record()
        record["admission"] = {"state": "REGIME_INELIGIBLE_NO_RESET", "reason": "QUIET"}
        result = o.finalize_observations([record])[0]
        self.assertFalse(result["policy_state_after"]["episode_traded"])
        self.assertEqual(result["policy_state_after"]["stage"], 1)
        self.assertEqual(result["origin_after_policy"], record["origin_after_native"])

    def test_unknown_admission_is_not_explicit_rejection(self):
        record = self.event_record()
        record["admission"] = {"state": "UNKNOWN_NO_RESET", "reason": "NO_NEXT_BAR"}
        result = o.finalize_observations([record])[0]
        self.assertEqual(result["policy_state_after"]["stage"], 1)
        self.assertEqual(result["successor_transition"], "UNKNOWN_NO_RESET")

    def test_explicit_rejection_clears_origin_at_decision(self):
        record = self.event_record()
        self.state.episode_traded = False
        self.state.event_reset()
        record["admission"] = {"state": "REJECTED_RESET", "reason": "ENTRY_COST", "decision_ts_ms": 3 * TF,
                               "state_after_policy": o._safe(asdict(self.state))}
        result = o.finalize_observations([record])[0]
        self.assertTrue(all(x is None for x in result["origin_after_policy"].values()))
        self.assertEqual(result["decision_order"]["admission_decision_ts_ms"], 3 * TF)
        _, next_touch = self.call(bar(3), bar(2, high=106, close=105))
        self.assertGreater(next_touch["origin_after_native"]["touch"]["available_ts_ms"], 3 * TF)
        o.finalize_observations([record, next_touch])

    def test_acceptance_and_rearm_are_different_phases(self):
        record = self.event_record()
        record["admission"] = {"state": "ACCEPTED", "reason": None, "decision_ts_ms": 3 * TF,
                               "state_after_policy": o._safe(asdict(self.state))}
        result = o.finalize_observations([record])[0]
        self.assertEqual(result["successor_transition"], "ADMISSION_ACCEPTED_EPISODE_CONSUMED")
        self.assertEqual(result["policy_state_after"]["stage"], 1)

    def test_last_outside_window_is_unknown_not_assumed_unconsumed(self):
        record = self.event_record()
        record["admission"] = {"state": "OUTSIDE_EVALUATION_WINDOW", "reason": None}
        result = o.finalize_observations([record])[0]
        self.assertIsNone(result["policy_state_after"])
        self.assertIn("UNKNOWN", result["policy_state_certainty"])

    def test_outside_window_resolved_by_next_prestate(self):
        record = self.event_record()
        record["admission"] = {"state": "OUTSIDE_EVALUATION_WINDOW", "reason": None}
        self.state.episode_traded = False
        _, nxt = self.call(bar(3), bar(2, high=106, close=105))
        result = o.finalize_observations([record, nxt])[0]
        self.assertFalse(result["policy_state_after"]["episode_traded"])
        self.assertEqual(result["policy_state_certainty"], "OBSERVED_NEXT_NATIVE_PRESTATE")

    def test_finalizer_does_not_mutate_records(self):
        _, record = self.touch()
        saved = deepcopy(record)
        o.finalize_observations([record])
        self.assertEqual(saved, record)

    def test_unfinished_admission_fails_closed(self):
        record = self.event_record()
        with self.assertRaisesRegex(ValueError, "UNFINISHED"):
            o.finalize_observations([record])

    def test_policy_state_mismatch_fails_closed(self):
        record = self.event_record()
        record["admission"] = {"state": "REGIME_INELIGIBLE_NO_RESET", "reason": "QUIET"}
        _, nxt = self.call(bar(3), bar(2, high=106, close=105))
        with self.assertRaisesRegex(ValueError, "STATE_MISMATCH"):
            o.finalize_observations([record, nxt])

    def test_next_open_gap_price_is_not_an_observer_gate(self):
        self.touch()
        _, record = self.call(bar(2, high=140, low=130, close=135, open=134), bar(1))
        self.assertEqual(record["native_event_observed"], [1, 98])
        self.assertNotIn("reject", record)

    def test_first_adverse_then_recovery_retains_native_origin(self):
        self.touch()
        self.call(bar(2, low=94, close=99), bar(1))
        event, record = self.call(bar(3, low=100, high=110, close=108), bar(2, low=94, close=99))
        self.assertEqual(event, (1, 94))
        self.assertEqual(record["origin_after_native"]["pull_low"]["open_ts_ms"], 2 * TF)

    def test_strong_move_followed_by_normal_pullback_has_fresh_touch(self):
        self.call(bar(1, low=105, high=110, close=109), bar(0))
        _, record = self.call(bar(2, low=100, high=109, close=101), bar(1, low=105, high=110, close=109))
        self.assertEqual(record["origin_after_native"]["touch"]["open_ts_ms"], 2 * TF)

    def test_wide_distance_does_not_create_a_filter(self):
        self.call(bar(1, low=50), bar(0))
        event, record = self.call(bar(2, high=160, low=100, close=150), bar(1, low=50))
        self.assertEqual(event, (1, 50))
        self.assertEqual(record["origin_after_native"]["pull_low"]["price"], 50)

    def test_future_outcome_fields_do_not_change_trace(self):
        row, prior = bar(1), bar(0)
        _, clean = self.call(row, prior)
        state2, watcher2 = native.HolyGrailState(), o.OriginObserver("SYNTHETIC")
        row.update(final_mfe=99999, final_pnl=-99999, date="DO_NOT_USE", symbol="OTHER")
        _, decorated = o.observed_hg_call(watcher2, state2, row, prior)
        self.assertEqual(clean, decorated)

    def test_late_available_is_recorded_separately(self):
        _, record = self.call(bar(1, available_ts_ms=2 * TF + 1, feature_available_ts_ms=2 * TF + 2), bar(0))
        self.assertEqual(record["origin_after_native"]["touch"]["available_ts_ms"], 2 * TF + 2)
        self.assertEqual(record["origin_after_native"]["touch"]["close_ts_ms"], 2 * TF)

    def test_regime_raw_and_effective_availability_are_distinct(self):
        _, record = self.call(bar(1, regime="TREND_DISPERSED", regime_available_ts_ms=3 * TF,
                                  regime_fit_end_ts_ms=TF, regime_spec_sha256="a" * 64), bar(0))
        inputs = record["native_inputs_asof"]
        self.assertEqual(inputs["regime_as_supplied"]["regime_available_ts_ms"], 3 * TF)
        self.assertEqual(inputs["effective_native_regime"], "UNBOUND")
        self.assertEqual(inputs["effective_regime_available_ts_ms"], 0)

    def test_out_of_order_clock_and_coverage_gap_fail(self):
        self.touch()
        with self.assertRaisesRegex(ValueError, "COVERAGE_GAP"):
            self.watcher.observe(asdict(self.state), asdict(self.state), bar(3), bar(2), None)

    def test_future_previous_availability_fails(self):
        with self.assertRaisesRegex(ValueError, "NONCAUSAL_PREVIOUS"):
            self.watcher.observe(asdict(self.state), asdict(self.state), bar(1),
                                 bar(0, available_ts_ms=4 * TF, feature_available_ts_ms=4 * TF), None)

    def test_patch_restores_original_even_on_failure(self):
        from ops import scalp7_benchmark_observer_v1 as hook
        original = hook.HGObserver
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with o.observation_patch():
                self.assertIs(hook.HGObserver, o.OriginObserver)
                raise RuntimeError("fixture")
        self.assertIs(hook.HGObserver, original)

    def test_same_segment_label_new_observer_piece_does_not_join_across_gap(self):
        _, first = self.touch()
        other = o.OriginObserver("SYNTHETIC")
        other_state = native.HolyGrailState()
        _, second = o.observed_hg_call(other, other_state, bar(10), bar(9))
        self.assertEqual(first["segment_id"], second["segment_id"])
        self.assertEqual(second["observation_index"], 1)
        finalized = o.finalize_observations([first, second])
        self.assertEqual(len(finalized), 2)
        self.assertEqual(finalized[1]["origin_after_policy"]["touch"]["open_ts_ms"], 10 * TF)


if __name__ == "__main__":
    unittest.main()
