"""Artificial-price integration: source priority, fills and independent reuse."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import fsum
from unittest.mock import patch
import unittest

from backend.research.rebuild import squeeze_sprint_execution_v1 as e
from backend.research.rebuild.test_c63_c70_trader_management_v1 import fixture, COST, rows_of


SLOTS = ('S1-02', 'S1-03', 'S1-04', 'S1-07')


def price(bars, index, close=None, op=None):
    old = bars[index]
    close = old.close if close is None else close
    op = old.open if op is None else op
    bars[index] = replace(old, open=op, close=close,
                          high=max(close, op) + 1, low=min(close, op) - 1)


def run_position(slots, *, bars=None, signal=None, features=None, n=150):
    b, s, f = fixture(n=n)
    return e.position(b if bars is None else bars, s if signal is None else signal,
                      'M1', f if features is None else features,
                      (len(b) if bars is None else len(bars)) * e.BAR, COST, slots)


def run_replay(entries, slots, *, bars=None, features=None, n=150):
    b, signal, f = fixture(n=n)
    b = b if bars is None else bars
    f = f if features is None else features
    signals = [dict(signal, signal_index=j-1, signal_ts=j*e.BAR,
                    setup_id='SYNTHETIC:' + str(j)) for j in entries]
    allowed = dict(eligible=True, reason=None, range_context=dict(rescued=False))
    with patch.object(e.tm.native, 'm1_setups', return_value=(signals, [], f)), \
         patch.object(e.tm.c63, 'context', return_value=allowed), \
         patch.object(e.tm, 'c70_context', side_effect=lambda original, daily: original):
        return e.replay(rows_of(b), slots=slots, eval_start_ms=0,
                        eval_end_ms=len(b) * e.BAR, cost=COST)


def divergence_fixture(n=150):
    b, s, f = fixture(n=n)
    for j, value in ((79, 101.), (80, 101.), (81, 110.)):
        if j < n:
            price(b, j, value)
    return b, s, f


def forced_observation(slot, rows, index, entry_index, entry_price,
                       runner_active, state, net_progress_bps):
    return dict(trigger=True, reason='SYNTHETIC_COMPONENT_CLOSE',
                source_slot=slot, axis=e.components.REGISTRY[slot]['axis'],
                features=dict(actual_partial_filled=runner_active, index=index))


class AuthorityAndControlTests(unittest.TestCase):
    def test_empty_control_position_is_exact_parent_delegation(self):
        b, s, f = fixture()
        sentinel = (None, {'parent': True}, [])
        with patch.object(e.tm, 'position', return_value=sentinel) as original:
            self.assertIs(e.position(b, s, 'M1', f, len(b)*e.BAR, COST, ()), sentinel)
            original.assert_called_once_with(b, s, 'M1', f, len(b)*e.BAR, COST)

    def test_empty_control_replay_is_exact_parent_delegation(self):
        sentinel = {'parent': True}
        with patch.object(e.cap, 'replay', return_value=sentinel) as original:
            self.assertIs(e.replay([], slots=(), eval_start_ms=0, eval_end_ms=1, cost=COST), sentinel)
            original.assert_called_once_with([], eval_start_ms=0, eval_end_ms=1, cost=COST)

    def test_only_one_or_two_distinct_orthogonal_slots(self):
        for slots in ((s,) for s in SLOTS):
            self.assertEqual(e.validate_slots(slots), slots)
        for slots in (('S1-02', 'S1-04'), ('S1-03', 'S1-04'), ('S1-04', 'S1-07')):
            self.assertEqual(e.validate_slots(slots), slots)
        for slots in ((), ('S1-02', 'S1-03'), ('S1-02', 'S1-07'),
                      ('S1-03', 'S1-07'), ('S1-04', 'S1-04'),
                      ('S1-04', 'S1-02'), ('S1-02', 'S1-03', 'S1-04'), ('S1-08',)):
            with self.assertRaises(ValueError):
                e.validate_slots(slots)

    def test_closed_and_wrong_scopes_rejected(self):
        for state in ('FROZEN_STAGE2_FIRST_FULL', 'FROZEN_STAGE3_FIRST_FULL',
                      'FROZEN_CHALLENGE_FIRST_FULL'):
            e.assert_authorized(e.SCOPE, state)
        with self.assertRaises(ValueError):
            e.assert_authorized(e.SCOPE, 'REPORT_ONLY')
        with self.assertRaises(ValueError):
            e.assert_authorized(e.cap.SCOPE, 'FROZEN_STAGE2_FIRST_FULL')


class ExecutionPriorityTests(unittest.TestCase):
    def test_d3_same_open_partial_and_sma10_safety_preserved_for_all_slots(self):
        b, s, f = fixture()
        for j in range(60):
            price(b, j, 150., 150.)
        original = e.tm.position(b, s, 'M1', f, len(b)*e.BAR, COST)[0]
        for slot in SLOTS:
            closed, opened, trace = run_position((slot,), bars=b, signal=s, features=f)
            self.assertIsNone(opened)
            self.assertEqual(closed['tm_legs'], original['tm_legs'])
            self.assertEqual([leg['index'] for leg in closed['tm_legs']], [78, 78])
            self.assertEqual(closed['exit_reason'], 'D3_SMA10_SAFETY_CLOSE_NEXT_OPEN')
            self.assertEqual(closed['partial_count'], 1)
            self.assertFalse(any(t['kind'] == 'HELD_CLOSE_OBSERVATION' and t['index'] >= 78 for t in trace))

    def test_native_floor_wins_over_additive_component(self):
        b, s, f = fixture()
        price(b, 60, 89.)
        with patch.object(e.components, 'observe', side_effect=forced_observation):
            closed, _, _ = run_position(('S1-04',), bars=b, signal=s, features=f)
        self.assertEqual(closed['exit_reason'], 'FIXED_FLOOR_CLOSE_NEXT_OPEN')
        self.assertEqual(closed['exit_index'], 61)

    def test_native_momentum_wins_before_partial(self):
        b, s, f = fixture()
        f[60]['momentum'] = 0.
        with patch.object(e.components, 'observe', side_effect=forced_observation):
            closed, _, _ = run_position(('S1-04',), bars=b, signal=s, features=f)
        self.assertEqual(closed['exit_reason'], 'MOMENTUM_NONPOSITIVE_CLOSE_NEXT_OPEN')
        self.assertEqual(closed['partial_count'], 0)

    def test_runner_breakeven_wins_over_component_after_partial(self):
        b, s, f = fixture()
        price(b, 78, 100.)
        original_observe = e.components.observe
        def postfill_force(*args):
            return forced_observation(*args) if args[5] else original_observe(*args)
        with patch.object(e.components, 'observe', side_effect=postfill_force):
            closed, _, _ = run_position(('S1-03',), bars=b, signal=s, features=f)
        self.assertEqual(closed['exit_reason'], 'RUNNER_BREAKEVEN_CLOSE_NEXT_OPEN')
        self.assertEqual(closed['exit_index'], 79)
        self.assertEqual(closed['partial_count'], 1)

    def test_native_sma10_wins_over_additive_component(self):
        b, s, f = fixture()
        price(b, 83, 101.)
        original_observe = e.components.observe
        def at83_force(*args):
            return forced_observation(*args) if args[2] == 83 else original_observe(*args)
        with patch.object(e.components, 'observe', side_effect=at83_force):
            closed, _, _ = run_position(('S1-03',), bars=b, signal=s, features=f)
        self.assertEqual(closed['exit_reason'], 'RUNNER_SMA10_CLOSE_NEXT_OPEN')
        self.assertEqual(closed['exit_index'], 84)

    def test_existing_missing_daily_history_safety_wins_over_replacement(self):
        b, s, f = fixture()
        original_daily = e.daily_observation
        def missing_at83(bars, index):
            observation = original_daily(bars, index)
            if index == 83:
                observation['sma10'] = None
            return observation
        for slot in ('S1-02', 'S1-07'):
            with patch.object(e, 'daily_observation', side_effect=missing_at83):
                closed, _, _ = run_position((slot,), bars=b, signal=s, features=f)
            self.assertEqual(closed['exit_reason'], 'RUNNER_DAILY_HISTORY_SAFETY_CLOSE_NEXT_OPEN')
            self.assertEqual(closed['exit_index'], 84)


class ActualComponentPathTests(unittest.TestCase):
    def test_carter_fourth_close_fills_next_observed_gap_open(self):
        b, s, f = fixture()
        for j in range(60, 64):
            price(b, j, 100.)
        price(b, 64, op=97.)
        closed, _, trace = run_position(('S1-04',), bars=b, signal=s, features=f)
        self.assertEqual(closed['exit_reason'], 'CARTER_FOUR_BAR_NET_NONPOSITIVE_CLOSE_NEXT_OPEN')
        self.assertEqual(closed['exit_index'], 64)
        self.assertEqual(closed['exit_price'], 97.)
        self.assertEqual(closed['partial_count'], 0)
        self.assertEqual(closed['exit_trigger']['signal_index'], 63)
        self.assertEqual(closed['tm_legs'][0]['qty'], 1)

    def test_raschke_actual_runner_activation_then_next_open_exit(self):
        b, s, f = divergence_fixture()
        price(b, 82, op=97.)
        closed, _, trace = run_position(('S1-03',), bars=b, signal=s, features=f)
        self.assertEqual(closed['exit_reason'], 'RASCHKE_NEW_CLOSE_HIGH_LOWER_3_10_OSCILLATOR_NEXT_OPEN')
        self.assertEqual(closed['exit_index'], 82)
        self.assertEqual(closed['exit_price'], 97.)
        self.assertEqual([leg['index'] for leg in closed['tm_legs']], [78, 82])
        observations = [t for t in trace if t['kind'] == 'HELD_CLOSE_OBSERVATION']
        self.assertTrue(all(not t['component_observations'][0]['trigger'] for t in observations if t['index'] < 78))
        self.assertTrue(all(t['component_observations'][0]['features']['actual_partial_filled'] for t in observations if t['index'] >= 78))

    def test_basso_and_luk_replacement_really_change_parent_runner_exit(self):
        b, s, f = fixture()
        for j in range(90, len(b)):
            price(b, j, 105.)
        original = e.tm.position(b, s, 'M1', f, len(b)*e.BAR, COST)[0]
        for slot, reason in (('S1-02', 'BASSO_SMA5_BELOW_SMA10_CLOSE_NEXT_OPEN'),
                             ('S1-07', 'MARTIN_LUK_DAILY_EMA9_CLOSE_NEXT_OPEN')):
            closed, _, _ = run_position((slot,), bars=b, signal=s, features=f)
            self.assertEqual(closed['exit_reason'], reason)
            self.assertEqual(closed['partial_count'], 1)
            self.assertNotEqual(closed['exit_index'], original['exit_index'])
            self.assertEqual(closed['exit_index'] % 6, 0)

    def test_pending_component_boundary_marks_remaining_quantity_without_fill(self):
        b, s, f = divergence_fixture(n=82)
        closed, opened, trace = run_position(('S1-03',), bars=b, signal=s, features=f)
        self.assertIsNone(closed)
        self.assertEqual(opened['censor_reason'], 'PENDING_EXIT_OUTSIDE_WINDOW')
        self.assertFalse(opened['terminal_liquidation'])
        self.assertEqual(opened['pending_exit_trigger']['signal_index'], 81)
        self.assertEqual(opened['tm_legs'][-1]['status'], 'O')
        self.assertAlmostEqual(opened['tm_legs'][-1]['qty'], 2/3)
        self.assertEqual(opened['tm_legs'][-1]['price'], b[81].close)
        self.assertFalse(trace[-1]['slot_released'])

    def test_closed_and_terminal_campaign_quantity_conservation_all_slots(self):
        for slot in SLOTS:
            for n in (78, 82, 150):
                b, s, f = fixture(n=n)
                if n >= 90:
                    for j in range(90, n):
                        price(b, j, 105.)
                closed, opened, _ = run_position((slot,), bars=b, signal=s, features=f)
                raw = closed or opened
                self.assertAlmostEqual(fsum(leg['qty'] for leg in raw['tm_legs']), 1)
                self.assertEqual(raw['assembled_qty'], 1)
                if closed:
                    self.assertEqual(raw['remaining_qty'], 0)
                else:
                    self.assertAlmostEqual(raw['remaining_qty'], raw['tm_legs'][-1]['qty'])

    def test_valid_orthogonal_pair_preserves_profitable_carter_and_runner_path(self):
        b, s, f = divergence_fixture()
        single = run_position(('S1-03',), bars=b, signal=s, features=f)[0]
        pair = run_position(('S1-03', 'S1-04'), bars=b, signal=s, features=f)[0]
        self.assertEqual(pair['tm_legs'], single['tm_legs'])
        self.assertEqual(pair['component_slots'], ['S1-03', 'S1-04'])


class CapacityAndIsolationTests(unittest.TestCase):
    def test_actual_partial_and_final_fills_never_release_capacity_early(self):
        b, s, f = divergence_fixture()
        result = run_replay([60, 78, 79, 82, 83], ('S1-03',), bars=b, features=f)
        self.assertEqual([x['admission'] for x in result['events']], [True, False, True, False, True])
        self.assertEqual([e.cap.allocation(x) for x in sorted(result['trades'] + result['open_positions'], key=lambda x: x['entry_index'])],
                         [Fraction(1), Fraction(1, 3), Fraction(2, 3)])
        self.assertTrue(all(x['active_after_open'] <= 1 for x in result['capacity_timeline']))

    def test_other_campaign_path_equals_its_own_lifecycle_no_collateral_exit(self):
        b, s, f = divergence_fixture()
        result = run_replay([60, 79], ('S1-03',), bars=b, features=f)
        by_entry = {x['entry_index']: x for x in result['trades'] + result['open_positions']}
        self.assertEqual(by_entry[60]['exit_index'], 82)
        signal = dict(s, signal_index=78, signal_ts=79*e.BAR, setup_id='SYNTHETIC:79')
        own_closed, own_open, _ = run_position(('S1-03',), bars=b, signal=signal, features=f)
        self.assertEqual(by_entry[79]['tm_legs'], (own_closed or own_open)['tm_legs'])
        self.assertFalse(any(leg['status'] == 'C' and leg['index'] == 82 for leg in by_entry[79]['tm_legs']))

    def test_future_mutation_preserves_pre_mutation_fills_and_close_decisions(self):
        b, s, f = fixture()
        changed = deepcopy(b)
        for j in range(100, len(b)):
            price(changed, j, 50., 50.)
        def prefix(trace):
            return [row for row in trace if row['ts'] < 100*e.BAR]
        for slot in SLOTS:
            original = run_position((slot,), bars=b, signal=s, features=f)[2]
            mutated = run_position((slot,), bars=changed, signal=s, features=f)[2]
            truncated = run_position((slot,), bars=b[:100], signal=s, features=f[:100])[2]
            self.assertEqual(prefix(original), prefix(mutated))
            self.assertEqual(prefix(original), prefix(truncated))


if __name__ == '__main__':
    unittest.main()
