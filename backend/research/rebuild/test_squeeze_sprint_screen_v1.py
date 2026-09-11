"""Artificial fixed-admission screen tests; no historical screen or FULL run."""
from copy import deepcopy
from dataclasses import replace
from math import fsum
from unittest.mock import patch
import unittest

from backend.research.rebuild import squeeze_sprint_screen_v1 as s
from backend.research.rebuild import c70_tm_capreuse_account_v1 as account
from backend.research.rebuild.test_c63_c70_trader_management_v1 import fixture, COST, POLICY
from backend.research.rebuild.test_chart_mechanism_execution_v1 import rows_of


def parent(bars, signal, features, numerator=1, denominator=1):
    """Build artificial saved evidence before any screen is invoked."""
    closed, opened, trace = s.tm.position(bars, signal, 'M1', features,
                                          bars[-1].open_ts + s.tm.BAR, COST)
    raw = closed if closed is not None else opened
    raw.update(allocation_numerator=numerator, allocation_denominator=denominator,
               allocated_normalized_qty=numerator / denominator,
               capacity_reuse_entry=denominator > 1)
    event = dict(signal, admission=True, status='COMPLETED' if closed else 'CENSORED',
                 exclusion_reason=None, entry_normalized_qty=numerator / denominator)
    return dict(trades=[raw] if closed else [], open_positions=[raw] if opened else [],
                trace=trace, events=[event], capacity_timeline=[dict(ts=raw['entry_ts'], active_after_open=numerator / denominator)],
                audit=dict(comparison_mode='SYNTHETIC_PARENT'))


def raw_of(rr):
    return (rr['trades'] + rr['open_positions'])[0]


def forced(at):
    def observe(slot, rows, j, ei, price, runner, state, net):
        return dict(trigger=j == at, reason='SYNTHETIC_COMPONENT_CLOSE' if j == at else None,
                    features=dict(data_safety_required=False), source_slot=slot,
                    axis=s.comp.REGISTRY[slot]['axis'])
    return observe


def execute(rr, bars, slot='S1-04'):
    return s.screen_symbol(rr, rows_of(bars), COST, bars[-1].open_ts + s.tm.BAR, slot)


class ScreenTests(unittest.TestCase):
    def test_no_signal_source_or_capacity_replay_callable(self):
        b, signal, f = fixture(n=100)
        rr = parent(b, signal, f)
        with (patch.object(s.tm, 'position', side_effect=AssertionError('SOURCE_REPLAY')),
                patch.object(s.tm, 'replay', side_effect=AssertionError('TM_REPLAY')),
                patch.object(s.cap, 'replay', side_effect=AssertionError('CAP_FULL')),
                patch.object(s.tm.native, 'm1_setups', side_effect=AssertionError('NEW_SIGNALS')),
                patch.object(s.cap, 'capacity', side_effect=AssertionError('CAPACITY_REPLAY'))):
            for slot in s.comp.REGISTRY:
                out = execute(rr, b, slot)
                self.assertEqual(out['audit']['comparison_mode'], s.MODE)
                self.assertEqual(out['audit']['source_lifecycle_replays'], 0)

    def test_add_exit_before_partial_removes_future_partial_and_runner(self):
        b, signal, f = fixture(n=100)
        rr = parent(b, signal, f)
        b[64] = replace(b[64], open=80., low=79.)
        with patch.object(s.comp, 'observe', side_effect=forced(63)):
            out = execute(rr, b)
        raw = raw_of(out)
        self.assertEqual(raw['exit_index'], 64)
        self.assertEqual(raw['exit_price'], 80.)
        self.assertEqual(raw['partial_count'], 0)
        self.assertFalse(raw['runner_activated'])
        self.assertEqual(raw['tm_legs'][0]['qty'], 1.)
        self.assertAlmostEqual(raw['mae_bps'], -2000.)
        self.assertTrue(raw['component_exit'])
        self.assertFalse(any(t['kind'] == 'PARTIAL_FILL' for t in out['trace']))

    def test_actual_carter_checkpoint_uses_net_and_does_not_rearm(self):
        b, signal, f = fixture(n=100)
        for j in range(60, 64):
            b[j] = replace(b[j], open=100., high=101., low=99., close=100.)
        rr = parent(b, signal, f)
        out = execute(rr, b)
        self.assertEqual(raw_of(out)['exit_index'], 64)
        self.assertEqual(out['audit']['component_exit_count'], 1)
        b, signal, f = fixture(n=100)
        for j in range(65, 76):
            b[j] = replace(b[j], open=101., high=102., low=99., close=100.)
        rr = parent(b, signal, f)
        out = execute(rr, b)
        self.assertFalse(raw_of(out)['component_exit'])
        self.assertEqual(raw_of(out)['tm_legs'], raw_of(rr)['tm_legs'])

    def test_source_final_priority_preserves_original_reason(self):
        b, signal, f = fixture(n=100)
        f[70]['momentum'] = 0.
        rr = parent(b, signal, f)
        with patch.object(s.comp, 'observe', side_effect=forced(70)):
            out = execute(rr, b)
        self.assertEqual(raw_of(out)['tm_legs'], raw_of(rr)['tm_legs'])
        self.assertEqual(raw_of(out)['exit_reason'], 'MOMENTUM_NONPOSITIVE_CLOSE_NEXT_OPEN')
        self.assertFalse(raw_of(out)['component_exit'])
        self.assertTrue(out['screen_trace'][-1]['source_exit_priority'])

    def test_due_source_partial_then_component_residual_same_actual_open(self):
        b, signal, f = fixture(n=100)
        rr = parent(b, signal, f, 1, 3)
        with patch.object(s.comp, 'observe', side_effect=forced(77)):
            out = execute(rr, b)
        raw = raw_of(out)
        self.assertEqual(raw['exit_index'], 78)
        self.assertEqual(raw['tm_legs'][0], raw_of(rr)['tm_legs'][0])
        self.assertEqual(raw['partial_count'], 1)
        self.assertAlmostEqual(raw['tm_legs'][-1]['qty'], 2 / 3)
        fills = [t for t in out['trace'] if t['index'] == 78]
        self.assertEqual([t['kind'] for t in fills], ['PARTIAL_FILL', 'FINAL_FILL'])
        self.assertAlmostEqual(fills[0]['normalized_fill_qty'], 1 / 9)
        self.assertEqual(fills[-1]['remaining_normalized_qty'], 0.)

    def test_pending_component_terminal_keeps_open_quantity_and_cost(self):
        b, signal, f = fixture(n=64)
        rr = parent(b, signal, f)
        with patch.object(s.comp, 'observe', side_effect=forced(63)):
            out = execute(rr, b)
        raw = raw_of(out)
        self.assertNotIn('exit_ts', raw)
        self.assertEqual(raw['remaining_qty'], 1.)
        self.assertFalse(raw['terminal_liquidation'])
        self.assertFalse(raw['component_exit'])
        self.assertEqual(raw['tm_legs'][-1]['status'], 'O')
        self.assertEqual(raw['pending_exit_trigger']['signal_ts'], 64 * s.tm.BAR)
        packet = dict(policy=POLICY, rows_by={'TEST': rows_of(b)}, costs={'TEST': COST})
        status, charged = account.campaign(raw, 'TEST', packet)
        self.assertEqual(status, 'O')
        self.assertGreater(charged['hypothetical_liquidation_cost_bps'], 0.)

    def test_replacement_can_extend_beyond_old_sma10_exit_without_new_entry(self):
        b, signal, f = fixture(n=150)
        for j in (130, 131):
            b[j] = replace(b[j], close=110., low=109.)
        b[132] = replace(b[132], open=107., low=106.)
        rr = parent(b, signal, f)
        self.assertEqual(raw_of(rr)['exit_reason'], 'RUNNER_SMA10_CLOSE_NEXT_OPEN')
        out = execute(rr, b, 'S1-02')
        raw = raw_of(out)
        self.assertNotIn('exit_ts', raw)
        self.assertEqual(raw['mark_index'], 149)
        self.assertEqual(raw['tm_legs'][0], raw_of(rr)['tm_legs'][0])
        self.assertTrue(raw['screen_changed'])
        self.assertFalse(raw['component_exit'])
        self.assertTrue(any(t.get('screen_fixed_trade_exit_suffix') for t in out['trace']))
        self.assertEqual(out['events'], rr['events'])
        packet = dict(policy=POLICY, rows_by={'TEST': rows_of(b)}, costs={'TEST': COST})
        _, old = account.campaign(raw_of(rr), 'TEST', packet)
        _, new = account.campaign(raw, 'TEST', packet)
        self.assertGreater(new['hypothetical_liquidation_cost_bps'], old['cost_bps'])

    def test_replacement_retains_d3_partial_plus_residual_safety(self):
        b, signal, f = fixture(n=100)
        for j in range(60):
            b[j] = replace(b[j], open=150., high=151., low=149., close=150.)
        rr = parent(b, signal, f)
        self.assertEqual(raw_of(rr)['exit_reason'], 'D3_SMA10_SAFETY_CLOSE_NEXT_OPEN')
        for slot in ('S1-02', 'S1-07'):
            out = execute(rr, b, slot)
            self.assertEqual(raw_of(out)['tm_legs'], raw_of(rr)['tm_legs'])
            self.assertEqual(out['screen_trace'], [])

    def test_replacement_is_inactive_without_actual_partial(self):
        b, signal, f = fixture(n=78)
        rr = parent(b, signal, f)
        self.assertEqual(raw_of(rr)['partial_count'], 0)
        for slot in ('S1-02', 'S1-07'):
            out = execute(rr, b, slot)
            self.assertEqual(raw_of(out)['tm_legs'], raw_of(rr)['tm_legs'])
            self.assertFalse(raw_of(out)['runner_activated'])

    def test_replacement_floor_and_breakeven_priority_and_gap(self):
        for close, expected in ((80., 'FIXED_FLOOR_CLOSE'), (99., 'RUNNER_BREAKEVEN_CLOSE')):
            b, signal, f = fixture(n=100)
            b[95] = replace(b[95], close=close, low=close - 1)
            b[96] = replace(b[96], open=75., low=74.)
            rr = parent(b, signal, f)
            with patch.object(s.comp, 'observe', side_effect=forced(95)):
                out = execute(rr, b, 'S1-02')
            raw = raw_of(out)
            self.assertEqual(raw['exit_reason'], expected + '_NEXT_OPEN')
            self.assertEqual(raw['exit_price'], 75.)
            self.assertFalse(raw['component_exit'])
            self.assertTrue(out['screen_trace'][-1]['source_exit_priority'])

    def test_replacement_component_only_exits_remaining_qty(self):
        b, signal, f = fixture(n=100)
        rr = parent(b, signal, f, 1, 9)
        with patch.object(s.comp, 'observe', side_effect=forced(89)):
            out = execute(rr, b, 'S1-07')
        raw = raw_of(out)
        self.assertEqual(raw['exit_index'], 90)
        self.assertTrue(raw['component_exit'])
        self.assertEqual(raw['tm_legs'][0], raw_of(rr)['tm_legs'][0])
        self.assertAlmostEqual(raw['tm_legs'][-1]['qty'], 2 / 3)
        self.assertEqual(s.cap.allocation(raw), s.cap.allocation(raw_of(rr)))
        packet = dict(policy=POLICY, rows_by={'TEST': rows_of(b)}, costs={'TEST': COST})
        status, charged = account.campaign(raw, 'TEST', packet)
        expected = fsum(l['qty'] * ((l['price'] / raw['entry_price'] - 1) * 10000 -
                                  s.tm.cost_at(COST, raw['entry_ts'], l['ts'])) for l in raw['tm_legs']) / 9
        self.assertEqual(status, 'C')
        self.assertAlmostEqual(charged['net_bps'], expected)
        self.assertEqual(len(charged['weighted_legs']), 2)

    def test_replacement_component_pending_at_boundary_does_not_fill(self):
        b, signal, f = fixture(n=96)
        rr = parent(b, signal, f)
        with patch.object(s.comp, 'observe', side_effect=forced(95)):
            out = execute(rr, b, 'S1-02')
        raw = raw_of(out)
        self.assertEqual(raw['tm_legs'][-1]['status'], 'O')
        self.assertAlmostEqual(raw['remaining_qty'], 2 / 3)
        self.assertEqual(raw['pending_component_exit']['signal_ts'], 96 * s.tm.BAR)
        self.assertFalse(raw['component_exit'])

    def test_allocation_events_and_inputs_are_immutable(self):
        b, signal, f = fixture(n=100)
        rr = parent(b, signal, f, 1, 3)
        original = deepcopy(rr)
        out = execute(rr, b, 'S1-03')
        self.assertEqual(rr, original)
        self.assertEqual(out['events'], original['events'])
        self.assertEqual(raw_of(out)['allocation_denominator'], 3)
        self.assertNotIn('capacity_timeline', out)
        self.assertEqual(out['saved_parent_capacity_timeline'], original['capacity_timeline'])
        self.assertIsNone(out['audit']['canonical_candidate_number'])

    def test_future_price_mutation_preserves_observed_prefix(self):
        b, signal, f = fixture(n=120)
        rr = parent(b, signal, f)
        changed = deepcopy(b)
        for j in range(96, len(changed)):
            changed[j] = replace(changed[j], open=101., high=102., low=99., close=100.5)
        for slot in ('S1-02', 'S1-03', 'S1-07'):
            first = execute(rr, b, slot)
            second = execute(rr, changed, slot)
            prefix = lambda out: [t for t in out['screen_trace'] if t['ts'] <= 96 * s.tm.BAR]
            self.assertEqual(prefix(first), prefix(second))

    def test_fixed_admissions_allow_proxy_overlap_without_capacity_replay(self):
        b, signal, f = fixture(n=160)
        for j in (130, 131):
            b[j] = replace(b[j], close=110., low=109.)
        first = parent(b, signal, f)
        second_signal = dict(signal, signal_index=133, signal_ts=134 * s.tm.BAR, setup_id='SECOND')
        second = parent(b, second_signal, f)
        both = dict(trades=first['trades'] + second['trades'],
                    open_positions=first['open_positions'] + second['open_positions'],
                    trace=first['trace'] + second['trace'], events=first['events'] + second['events'], audit={})
        out = execute(both, b, 'S1-02')
        raws = out['trades'] + out['open_positions']
        self.assertEqual({r['signal_index'] for r in raws}, {59, 133})
        active = sum(float(s.cap.remaining(r, 135 * s.tm.BAR)) for r in raws)
        self.assertGreater(active, 1.)
        self.assertEqual(out['audit']['occupancy_replays'], 0)

    def test_missing_saved_held_observation_is_integrity_error(self):
        b, signal, f = fixture(n=100)
        rr = parent(b, signal, f)
        rr['trace'] = [t for t in rr['trace'] if not (t['kind'] == 'HELD_CLOSE_OBSERVATION' and t['index'] == 63)]
        with self.assertRaisesRegex(ValueError, 'COMPLETE_SAVED_HELD_PREFIX'):
            execute(rr, b)

    def test_unknown_slot_and_mismatched_entry_are_rejected(self):
        b, signal, f = fixture(n=100)
        rr = parent(b, signal, f)
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_SOURCE_SLOT'):
            execute(rr, b, 'S1-01')
        raw_of(rr)['entry_price'] += 1
        with self.assertRaisesRegex(ValueError, 'SAVED_ENTRY_BINDING'):
            execute(rr, b)

    def test_json_roundtrip_keeps_screen_and_cash_identical(self):
        import json
        b, signal, f = fixture(n=110)
        rr = parent(b, signal, f, 1, 3)
        for slot in s.comp.REGISTRY:
            expected = execute(rr, b, slot)
            actual = execute(json.loads(json.dumps(rr)), b, slot)
            self.assertEqual(expected, actual)


if __name__ == '__main__':
    unittest.main()
