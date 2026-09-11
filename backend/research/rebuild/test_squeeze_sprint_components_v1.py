"""Synthetic source-rule, session, prefix and per-entry state acceptance."""
from copy import deepcopy
import unittest

from backend.research.rebuild import squeeze_sprint_components_v1 as e


def rows(prices, start=0):
    return [dict(bar_open_ts=start + j * e.BAR,
                 bar_close_ts=start + (j + 1) * e.BAR,
                 open=float(p), high=float(p) + 1, low=float(p) - 1,
                 close=float(p), volume=1.) for j, p in enumerate(prices)]


def day_rows(closes):
    return rows([p for p in closes for _ in range(6)])


def call(slot, data, index=None, *, entry=0, runner=True, state=None, net=1.):
    return e.observe(slot, data, len(data) - 1 if index is None else index,
                     entry, data[entry]['open'], runner, {} if state is None else state, net)


class SourceRegistryTests(unittest.TestCase):
    def test_only_four_source_grounded_slots_and_frozen_periods(self):
        self.assertEqual(set(e.REGISTRY), {'S1-02', 'S1-03', 'S1-04', 'S1-07'})
        self.assertEqual((e.REGISTRY['S1-02']['fast_sma'], e.REGISTRY['S1-02']['slow_sma']), (5, 10))
        self.assertEqual((e.REGISTRY['S1-03']['fast_sma'], e.REGISTRY['S1-03']['slow_sma']), (3, 10))
        self.assertEqual(e.REGISTRY['S1-04']['initial_thrust_bars'], 4)
        self.assertEqual(e.REGISTRY['S1-07']['ema_period'], 9)
        self.assertEqual([e.REGISTRY[s]['mode'] for s in sorted(e.REGISTRY)],
                         ['REPLACE_RUNNER', 'ADD_EXIT', 'ADD_EXIT', 'REPLACE_RUNNER'])

    def test_unknown_control_slot_fails(self):
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_SOURCE_COMPONENT'):
            call('S1-08', rows([100]))


class DailyComponentTests(unittest.TestCase):
    def test_basso_daily_average_state_not_current_price_sma10(self):
        data = day_rows([120] * 5 + [100] * 4 + [115])
        result = call('S1-02', data)
        self.assertTrue(result['trigger'])
        self.assertGreater(result['features']['close'], result['features']['sma10'])
        self.assertAlmostEqual(result['features']['sma5'], 103)
        self.assertAlmostEqual(result['features']['sma10'], 111.5)

    def test_basso_equality_does_not_trigger(self):
        self.assertFalse(call('S1-02', day_rows([100] * 10))['trigger'])

    def test_actual_partial_required_for_both_runner_replacements(self):
        data = day_rows([120] * 9 + [100])
        for slot in ('S1-02', 'S1-07'):
            self.assertTrue(call(slot, data, runner=True)['trigger'])
            self.assertFalse(call(slot, data, runner=False)['trigger'])

    def test_intraday_bar_never_substitutes_for_daily_close(self):
        data = day_rows([120] * 10) + rows([90] * 5, start=10 * e.DAY)
        for slot in ('S1-02', 'S1-07'):
            result = call(slot, data)
            self.assertFalse(result['trigger'])
            self.assertFalse(result['features']['is_daily_close'])
            self.assertEqual(result['features']['completed_days'], 10)
            self.assertEqual(result['features']['last_daily_available_at'], 10 * e.DAY)

    def test_leading_partial_utc_day_excluded(self):
        data = rows([200] * 4 + [100] * 60, start=2 * e.BAR)
        result = call('S1-02', data)
        self.assertEqual(result['features']['leading_partial_bars'], 4)
        self.assertEqual(result['features']['completed_days'], 10)
        self.assertEqual(result['features']['sma10'], 100)

    def test_missing_history_explicit_no_shorter_average(self):
        for slot, days in (('S1-02', 9), ('S1-07', 8)):
            result = call(slot, day_rows([100] * days))
            self.assertFalse(result['trigger'])
            self.assertFalse(result['features']['history_available'])
            self.assertTrue(result['features']['data_safety_required'])

    def test_ema9_native_sma_seed_then_alpha_two_tenths(self):
        data = day_rows(list(range(101, 110)) + [120])
        first = call('S1-07', data, 53)
        second = call('S1-07', data, 59)
        self.assertEqual(first['features']['ema9'], 105)
        self.assertAlmostEqual(second['features']['ema9'], 108)
        self.assertIn('SMA_FIRST9', second['features']['ema_seed'])

    def test_ema_equality_does_not_trigger_and_full_nine_days_required(self):
        result = call('S1-07', day_rows([100] * 9))
        self.assertTrue(result['features']['history_available'])
        self.assertFalse(result['trigger'])


class DivergenceTests(unittest.TestCase):
    def test_prior_entry_record_anchor_may_precede_actual_partial(self):
        data = rows([100] * 9 + [120, 100, 100, 121])
        state = {}
        for j in range(9, 12):
            self.assertFalse(call('S1-03', data, j, entry=9, runner=False, state=state)['trigger'])
        result = call('S1-03', data, 12, entry=9, runner=True, state=state)
        self.assertTrue(result['trigger'])
        self.assertEqual(result['features']['prior_record_index'], 9)
        self.assertLess(result['features']['oscillator'], result['features']['prior_record_oscillator'])

    def test_equal_close_cannot_replace_anchor(self):
        data = rows([100] * 9 + [120, 100, 120, 121])
        state = {}
        call('S1-03', data, 9, entry=9, state=state)
        call('S1-03', data, 10, entry=9, state=state)
        equal = call('S1-03', data, 11, entry=9, state=state)
        self.assertFalse(equal['trigger'])
        self.assertEqual(state['S1-03']['record_index'], 9)

    def test_oscillator_equality_does_not_trigger(self):
        data = rows(range(100, 116))
        state = {}
        call('S1-03', data, 10, entry=10, state=state)
        result = call('S1-03', data, 11, entry=10, state=state)
        self.assertEqual(result['features']['oscillator'], result['features']['prior_record_oscillator'])
        self.assertTrue(result['features']['new_strict_record'])
        self.assertFalse(result['trigger'])

    def test_no_hindsight_anchor_replacement_after_missing_warmup(self):
        data = rows([150] + [100] * 8 + [151, 152])
        result = call('S1-03', data, 9, entry=0)
        self.assertIsNone(result['features']['prior_record_oscillator'])
        self.assertFalse(result['trigger'])

    def test_first_post_partial_call_initializes_causal_entry_anchor(self):
        data = rows([100] * 9 + [120, 100, 100, 121])
        single = call('S1-03', data, 12, entry=9)
        state = {}
        for j in range(9, 13):
            sequential = call('S1-03', data, j, entry=9, runner=j == 12, state=state)
        self.assertEqual(single, sequential)


class InitialThrustTests(unittest.TestCase):
    def test_fourth_completed_bar_includes_entry_and_can_precede_partial(self):
        data = rows([100] * 10)
        state = {}
        for j in range(2, 5):
            self.assertFalse(call('S1-04', data, j, entry=2, runner=False, state=state, net=-1)['trigger'])
        result = call('S1-04', data, 5, entry=2, runner=False, state=state, net=0)
        self.assertTrue(result['trigger'])
        self.assertEqual(result['features']['held_bars'], 4)

    def test_cost_adjusted_net_inclusive_zero_boundary(self):
        data = rows([100, 101, 102, 103])
        self.assertTrue(call('S1-04', data, net=0)['trigger'])
        self.assertFalse(call('S1-04', data, net=1e-12)['trigger'])
        self.assertTrue(call('S1-04', data, net=-1e-12)['trigger'])

    def test_profitable_checkpoint_never_rearms(self):
        data = rows([100] * 8)
        state = {}
        self.assertFalse(call('S1-04', data, 3, state=state, net=1)['trigger'])
        for j in range(4, 8):
            self.assertFalse(call('S1-04', data, j, state=state, net=-100)['trigger'])

    def test_missed_checkpoint_does_not_invent_late_exit(self):
        result = call('S1-04', rows([100] * 8), 5, net=-100)
        self.assertFalse(result['trigger'])
        self.assertTrue(result['features']['checkpoint_missed'])


class CausalStateTests(unittest.TestCase):
    def test_future_mutation_and_truncation_identical_for_every_component(self):
        data = day_rows([120] * 10 + [100] * 3)
        changed = deepcopy(data)
        for row in changed[66:]:
            row.update(close=float('nan'), bar_open_ts=1)
        for slot in e.REGISTRY:
            original_state, changed_state, prefix_state = {}, {}, {}
            for j in range(60, 66):
                original = call(slot, data, j, entry=60, state=original_state)
                mutated = call(slot, changed, j, entry=60, state=changed_state)
                truncated = call(slot, data[:66], j, entry=60, state=prefix_state)
                self.assertEqual(original, mutated)
                self.assertEqual(original, truncated)
            self.assertEqual(original_state, changed_state)
            self.assertEqual(original_state, prefix_state)

    def test_independent_campaign_state_and_reuse_guard(self):
        data = rows([100] * 9 + [120, 100, 100, 121])
        left, right = {}, {}
        for j in range(9, 13):
            call('S1-03', data, j, entry=9, state=left)
        result = call('S1-03', data, 12, entry=12, state=right)
        self.assertFalse(result['trigger'])
        self.assertIsNone(result['features']['prior_record_index'])
        with self.assertRaisesRegex(ValueError, 'ANOTHER_LOT'):
            call('S1-03', data, 12, entry=12, state=left)

    def test_slots_namespace_state_without_cross_component_features(self):
        data = day_rows([120] * 9 + [100])
        state = {}
        for slot in e.REGISTRY:
            call(slot, data, entry=56, state=state)
        self.assertEqual(set(state), set(e.REGISTRY))
        self.assertNotIn('record_close', state['S1-02'])
        self.assertNotIn('record_close', state['S1-04'])

    def test_same_observation_idempotent_no_mutable_result_alias(self):
        data = rows([100] * 5)
        state = {}
        one = call('S1-04', data, 3, state=state, net=0)
        self.assertEqual(one, call('S1-04', data, 3, state=state, net=0))
        one['features']['held_bars'] = -10
        self.assertEqual(call('S1-04', data, 3, state=state, net=0)['features']['held_bars'], 4)

    def test_integrity_rejects_gap_close_timestamp_and_backwards_state(self):
        data = rows([100] * 5)
        gapped = deepcopy(data)
        del gapped[2]
        with self.assertRaisesRegex(ValueError, 'GAP_OR_DUPLICATE'):
            call('S1-04', gapped)
        malformed = deepcopy(data)
        malformed[2]['bar_close_ts'] += 1
        with self.assertRaisesRegex(ValueError, 'CLOSE_TIMESTAMP'):
            call('S1-04', malformed)
        state = {}
        call('S1-04', data, 3, state=state)
        with self.assertRaisesRegex(ValueError, 'BACKWARDS'):
            call('S1-04', data, 2, state=state)


if __name__ == '__main__':
    unittest.main()
