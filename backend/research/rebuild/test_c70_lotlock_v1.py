"""Artificial-only independent-lot causality, capacity and cash acceptance."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import fsum
from unittest.mock import patch
import unittest

from backend.research.rebuild import c70_lotlock_v1 as e
from backend.research.rebuild import c70_lotlock_account_v1 as account
from backend.research.rebuild import c70_tm_capreuse_account_v1 as cap_account
from backend.research.rebuild.test_c63_c70_trader_management_v1 import (
    fixture, COST, POLICY, rows_of,
)


def run(entries, *, n=150, bars=None, features=None, enabled=True):
    """Replace only signal discovery on artificial prices; run actual managers."""
    b, signal, f = fixture(n=n)
    b = b if bars is None else bars
    f = f if features is None else features
    signals = [dict(signal, signal_index=j-1, signal_ts=j*e.tm.BAR,
                    setup_id=str(j)) for j in entries]
    obs = dict(eligible=True, reason=None, range_context=dict(rescued=False))
    with patch.object(e.tm.native, 'm1_setups', return_value=(signals, [], f)), \
         patch.object(e.tm.c63, 'context', return_value=obs), \
         patch.object(e.tm, 'c70_context', side_effect=lambda original, daily: original):
        return e.replay(rows_of(b), eval_start_ms=0,
                        eval_end_ms=len(b)*e.tm.BAR, cost=COST, enabled=enabled)


def reversal(n=150):
    b, s, f = fixture(n=n)
    for j in range(91, n):
        b[j] = replace(b[j], open=111., high=112., low=110., close=111.)
    return b, s, f


def by_entry(result):
    return {r['signal_index']+1: r
            for r in result['trades']+result['open_positions']}


def assert_parent_fields(case, actual, parent):
    for name, value in parent.items():
        case.assertEqual(actual[name], value, name)


class LotEnvelopeTests(unittest.TestCase):
    def test_off_delegates_exact_capreuse_without_wrapper_features(self):
        sentinel = {'exact': True}
        with patch.object(e.cap, 'replay', return_value=sentinel) as call:
            self.assertIs(e.replay([], eval_start_ms=0, eval_end_ms=1,
                                   cost=COST, enabled=False), sentinel)
            call.assert_called_once_with([], eval_start_ms=0, eval_end_ms=1, cost=COST)

    def test_enabled_flag_is_boolean(self):
        for value in (0, 1, 'false', None):
            with self.assertRaises(ValueError):
                e.replay([], eval_start_ms=0, eval_end_ms=1, cost=COST, enabled=value)

    def test_prepartial_and_rising_runner_exact_parent_paths(self):
        for n in (78, 90):
            on = run([60, 70, 78, 79], n=n)
            off = run([60, 70, 78, 79], n=n, enabled=False)
            for actual, prior in zip(on['events'], off['events'], strict=True):
                assert_parent_fields(self, actual, prior)
            self.assertEqual(by_entry(on).keys(), by_entry(off).keys())
            for entry, prior in by_entry(off).items():
                assert_parent_fields(self, by_entry(on)[entry], prior)
            self.assertEqual(on['audit']['lot_lock_triggers'], 0)

    def test_pending_partial_is_not_bank_or_peak(self):
        r = run([60], n=78)
        self.assertEqual(r['open_positions'][0]['partial_count'], 0)
        self.assertEqual(r['open_positions'][0]['pending_exit_trigger']['action'], 'PARTIAL')
        for row in r['lot_trace']:
            self.assertEqual(row['lot_realized_bank_net'], 0)
            self.assertIsNone(row['lot_peak_marked_net'])
            self.assertFalse(row['trigger'])

    def test_actual_gap_partial_net_after_costs_funds_only_own_bank(self):
        b, _, _ = fixture()
        b[78] = replace(b[78], open=113., high=114.)
        r = run([60, 79], bars=b)
        root = by_entry(r)[60]
        leg = root['tm_legs'][0]
        own = [t for t in r['lot_trace'] if t['signal_index'] == 59]
        equal_open = next(t for t in own if t['ts'] == leg['ts'])
        self.assertEqual(equal_open['lot_realized_bank_net'], 0)
        self.assertIsNone(equal_open['lot_peak_marked_net'])
        actual = next(t for t in own if t['first_partial_fill_ts'] is not None)
        expected = leg['qty']*((leg['price']/root['entry_price']-1)*10000
                               -e.tm.cost_at(COST, root['entry_ts'], leg['ts']))
        self.assertAlmostEqual(actual['lot_realized_bank_net'], expected)
        self.assertEqual(actual['first_partial_fill_ts'], 78*e.tm.BAR)

    def test_negative_gap_partial_never_borrows_profitable_other_bank(self):
        b, _, _ = fixture()
        b[78] = replace(b[78], open=95., low=94.)
        r = run([60, 79], bars=b)
        own = [t for t in r['lot_trace'] if t['signal_index'] == 59
               and t['first_partial_fill_ts'] is not None]
        self.assertTrue(own)
        self.assertTrue(any(t['lot_realized_bank_net'] > 0 for t in r['lot_trace']
                            if t['signal_index'] == 78))
        self.assertTrue(all(t['lot_realized_bank_net'] == 0 and not t['trigger']
                            for t in own))
        self.assertFalse(by_entry(r)[60]['lot_lock_exit'])

    def test_zero_net_partial_does_not_arm(self):
        b, s, f = fixture()
        _, raw, _ = e.tm.position(b, s, 'M1', f, len(b)*e.tm.BAR, COST)
        raw = deepcopy(raw)
        raw['tm_legs'][0]['price'] = raw['entry_price']
        with patch.object(e.tm, 'cost_at', return_value=0.):
            value = e.lot_value(raw, 79*e.tm.BAR, 50., COST)
        self.assertEqual(value['lot_realized_bank_net'], 0.)

    def test_giveback_fills_next_actual_open_including_gap(self):
        b, _, _ = reversal()
        b[92] = replace(b[92], open=108., low=107.)
        r = run([60], bars=b)
        trigger = next(t for t in r['lot_trace'] if t['trigger'])
        raw = by_entry(r)[60]
        self.assertEqual(raw['exit_index'], trigger['index']+1)
        self.assertEqual(raw['exit_ts'], trigger['ts'])
        self.assertEqual(raw['exit_price'], 108.)
        self.assertNotEqual(raw['exit_price'], trigger['price'])
        self.assertEqual(raw['exit_reason'], e.EXIT+'_NEXT_OPEN')
        self.assertEqual(raw['partial_count'], 1)

    def test_threshold_equality_is_inclusive(self):
        original = e.lot_value
        def controlled(raw, stamp, price, cost):
            value = original(raw, stamp, price, cost)
            if value['first_partial_fill_ts'] is not None:
                value.update(lot_realized_bank_net=100.,
                             lot_marked_net=1000. if stamp == 79*e.tm.BAR else 900.)
            return value
        with patch.object(e, 'lot_value', side_effect=controlled):
            r = run([60], n=90)
        trigger = next(t for t in r['lot_trace'] if t['trigger'])
        self.assertEqual(trigger['lot_marked_net'],
                         trigger['lot_peak_marked_net']-trigger['lot_realized_bank_net'])
        self.assertEqual(by_entry(r)[60]['exit_ts'], 80*e.tm.BAR)

    def test_root_trigger_preserves_other_lot_qty_runner_stops_and_entire_path(self):
        b, _, _ = reversal()
        on = run([60, 79], bars=b)
        off = run([60, 79], bars=b, enabled=False)
        root, reuse = by_entry(on)[60], by_entry(on)[79]
        self.assertTrue(root['lot_lock_exit'])
        self.assertFalse(reuse['lot_lock_exit'])
        self.assertEqual(e.allocation(reuse), Fraction(1, 3))
        assert_parent_fields(self, reuse, by_entry(off)[79])
        self.assertEqual([t for t in on['trace'] if t['signal_index'] == 78],
                         [t for t in off['trace'] if t['signal_index'] == 78])
        self.assertEqual(reuse['tm_legs'][0]['index'], 96)
        self.assertGreater(reuse['exit_index'], root['exit_index'])

    def test_management_never_reads_another_campaign(self):
        b, s, f = reversal()
        signal = dict(s, signal_index=78, signal_ts=79*e.tm.BAR, setup_id='79')
        trade, opened, trace = e.tm.position(b, signal, 'M1', f, len(b)*e.tm.BAR, COST)
        raw = trade if trade is not None else opened
        original = deepcopy(raw)
        observations = e.manage(raw, trace, b, COST, len(b)*e.tm.BAR)
        combined = run([60, 79], bars=b)
        actual = [t for t in combined['lot_trace'] if t['signal_index'] == 78]
        self.assertEqual(len(observations), len(actual))
        for direct, together in zip(observations, actual, strict=True):
            assert_parent_fields(self, together, direct)
        assert_parent_fields(self, by_entry(combined)[79], original)

    def test_native_floor_wins_simultaneous_lot_trigger_once(self):
        b, _, _ = reversal()
        b[91] = replace(b[91], close=80., low=79.)
        r = run([60, 79], bars=b)
        self.assertTrue(any(t['trigger'] for t in r['lot_trace']))
        for raw in by_entry(r).values():
            self.assertEqual(raw['exit_reason'], 'FIXED_FLOOR_CLOSE_NEXT_OPEN')
            self.assertFalse(raw['lot_lock_exit'])
            self.assertAlmostEqual(fsum(l['qty'] for l in raw['tm_legs']), 1.)
            self.assertEqual(sum(t['kind'] == 'FINAL_FILL' for t in r['trace']
                                 if t['signal_index'] == raw['signal_index']), 1)

    def test_BE_wins_simultaneous_lot_trigger_once(self):
        b, _, _ = reversal()
        b[91] = replace(b[91], close=99., low=98.)
        r = run([60], bars=b)
        raw = by_entry(r)[60]
        self.assertTrue(any(t['trigger'] for t in r['lot_trace']))
        self.assertEqual(raw['exit_reason'], 'RUNNER_BREAKEVEN_CLOSE_NEXT_OPEN')
        self.assertFalse(raw['lot_lock_exit'])
        self.assertEqual(len(raw['tm_legs']), 2)

    def test_completed_daily_SMA10_wins_simultaneous_lot_trigger(self):
        b, _, _ = fixture()
        b[131] = replace(b[131], close=110., low=109.)
        b[132] = replace(b[132], open=107., low=106.)
        r = run([60], bars=b)
        raw = by_entry(r)[60]
        self.assertTrue(any(t['trigger'] and t['index'] == 131 for t in r['lot_trace']))
        self.assertEqual(raw['exit_index'], 132)
        self.assertEqual(raw['exit_price'], 107.)
        self.assertEqual(raw['exit_reason'], 'RUNNER_SMA10_CLOSE_NEXT_OPEN')
        self.assertFalse(raw['lot_lock_exit'])
        self.assertEqual(len(raw['tm_legs']), 2)

    def test_prepartial_native_momentum_unchanged(self):
        b, _, f = fixture()
        f[70]['momentum'] = 0.
        on = run([60], bars=b, features=f)
        off = run([60], bars=b, features=f, enabled=False)
        assert_parent_fields(self, by_entry(on)[60], by_entry(off)[60])
        self.assertEqual(by_entry(on)[60]['exit_reason'], 'MOMENTUM_NONPOSITIVE_CLOSE_NEXT_OPEN')
        self.assertEqual(on['audit']['lot_lock_triggers'], 0)

    def test_terminal_trigger_keeps_remaining_mark_and_pending_decision(self):
        b, _, _ = reversal(n=92)
        r = run([60], n=92, bars=b)
        raw = r['open_positions'][0]
        self.assertIn('pending_lot_envelope', raw)
        self.assertEqual(len(r['trades']), 0)
        self.assertFalse(raw['lot_lock_exit'])
        self.assertAlmostEqual(raw['remaining_qty'], 2/3)
        self.assertFalse(raw['terminal_liquidation'])
        self.assertEqual(raw['tm_legs'][-1]['status'], 'O')
        self.assertEqual(raw['tm_legs'][-1]['ts'], 92*e.tm.BAR)

    def test_future_mutation_and_truncation_leave_completed_peak_prefix_unchanged(self):
        b, _, f = reversal()
        changed = deepcopy(b)
        for j in range(100, len(b)):
            changed[j] = replace(changed[j], open=50., high=500., low=1., close=50.)
        full = run([60, 79, 93, 110], bars=b)
        future = run([60, 79, 93, 110], bars=changed)
        short = run([60, 79, 93], n=100, bars=b[:100], features=f[:100])
        prefix = lambda r: [t for t in r['lot_trace'] if t['ts'] < 100*e.tm.BAR]
        self.assertEqual(prefix(full), prefix(future))
        self.assertEqual(prefix(full), prefix(short))
        decisions = lambda r: [{k: v for k, v in t.items() if k != 'status'}
                               for t in r['events'] if t['signal_ts'] < 100*e.tm.BAR]
        self.assertEqual(decisions(full), decisions(future))
        self.assertEqual(decisions(full), decisions(short))

    def test_missing_native_bar_is_integrity_failure(self):
        b, _, _ = fixture()
        del b[70]
        with self.assertRaises(ValueError):
            run([60, 79], bars=b)

    def test_previous_scopes_report_only_blocked_current_first_full_allowed(self):
        for scope in (e.tm.SCOPE, e.cap.SCOPE,
                      'C70_CUMULATIVE_PROFITLOCK_AFTER_PR1262_V1', e.SCOPE):
            with self.assertRaises(ValueError):
                e.assert_authorized(scope, 'REPORT_ONLY')
            if scope != e.SCOPE:
                with self.assertRaises(ValueError):
                    e.assert_authorized(scope, 'FROZEN_AUTHORIZED_FIRST_FULL')
        e.assert_authorized(e.SCOPE, 'FROZEN_AUTHORIZED_FIRST_FULL')


class LotCapacityTests(unittest.TestCase):
    def test_partial_fill_equal_timestamp_not_yet_available(self):
        r = run([60, 78, 79])
        self.assertFalse(r['events'][1]['admission'])
        self.assertEqual(r['events'][1]['available_capacity'], 0.)
        self.assertTrue(r['events'][2]['admission'])
        self.assertEqual(r['events'][2]['available_fraction'], [1, 3])

    def test_lot_trigger_does_not_release_until_actual_fill_other_lot_survives(self):
        b, _, _ = reversal()
        r = run([60, 79, 92, 93], bars=b)
        events = {x['signal_index']+1: x for x in r['events']}
        self.assertFalse(events[92]['admission'])
        self.assertEqual(events[92]['available_fraction'], [0, 1])
        self.assertTrue(events[93]['admission'])
        self.assertEqual(events[93]['available_fraction'], [2, 3])
        self.assertEqual(e.allocation(by_entry(r)[93]), Fraction(2, 3))
        self.assertGreater(by_entry(r)[79]['exit_index'], by_entry(r)[93]['entry_index'])
        self.assertTrue(events[93]['capacity_reuse_entry'])
        self.assertTrue(all(t['active_after_open'] <= 1 for t in r['capacity_timeline']))

    def test_equal_open_reserved_quantity_not_upsized_by_lot_exit(self):
        b, _, _ = reversal()
        r = run([60, 92, 93], bars=b)
        self.assertEqual(e.allocation(by_entry(r)[92]), Fraction(1, 3))
        self.assertEqual(e.allocation(by_entry(r)[93]), Fraction(2, 3))
        self.assertAlmostEqual(r['events'][1]['active_after_entry'], 1/3)

    def test_repeat_tiny_rational_reuse_obeys_same_source_lifecycle(self):
        b, s, f = fixture(n=170)
        entries = [60, 79, 97, 115, 133, 151]
        r = run(entries, n=170, bars=b)
        self.assertEqual([e.allocation(by_entry(r)[j]) for j in entries],
                         [Fraction(1, 3**n) for n in range(len(entries))])
        for entry in entries:
            signal = dict(s, signal_index=entry-1, signal_ts=entry*e.tm.BAR,
                          setup_id=str(entry))
            trade, opened, _ = e.tm.position(b, signal, 'M1', f, len(b)*e.tm.BAR, COST)
            assert_parent_fields(self, by_entry(r)[entry], trade if trade is not None else opened)
        self.assertTrue(by_entry(r)[151]['runner_activated'])
        self.assertTrue(all(t['active_after_open'] <= 1 for t in r['capacity_timeline']))
        for observation in r['lot_trace']:
            qty = e.allocation(by_entry(r)[observation['signal_index']+1])
            for name in ('lot_realized_bank_net', 'lot_realized_net',
                         'lot_remaining_mark_net', 'lot_marked_net',
                         'lot_peak_marked_net', 'remaining_qty'):
                value = observation[name]
                if value is None:
                    self.assertIsNone(observation['normalized_'+name])
                else:
                    self.assertAlmostEqual(observation['normalized_'+name], float(qty)*value)

    def test_unit_trigger_homogeneous_under_exact_fractional_allocation(self):
        b, s, f = reversal()
        trade, opened, trace = e.tm.position(b, s, 'M1', f, len(b)*e.tm.BAR, COST)
        raw = trade if trade is not None else opened
        tiny, tiny_trace = deepcopy(raw), deepcopy(trace)
        tiny.update(allocation_numerator=1, allocation_denominator=3**20)
        full_trace = e.manage(raw, trace, b, COST, len(b)*e.tm.BAR)
        tiny_obs = e.manage(tiny, tiny_trace, b, COST, len(b)*e.tm.BAR)
        self.assertEqual(full_trace, tiny_obs)
        self.assertEqual(raw['tm_legs'], tiny['tm_legs'])
        self.assertEqual(raw['exit_ts'], tiny['exit_ts'])

    def test_entry_gap_rejection_keeps_available_capacity(self):
        b, _, _ = fixture()
        b[79] = replace(b[79], open=85., low=84.)
        r = run([60, 79, 80], bars=b)
        self.assertEqual(r['events'][1]['exclusion_reason'], 'GAP_INVALIDATES_FIXED_SETUP')
        self.assertEqual(r['events'][1]['entry_normalized_qty'], 0.)
        self.assertEqual(r['events'][2]['available_fraction'], [1, 3])


class LotCashTests(unittest.TestCase):
    def charged(self, result, bars):
        packet = dict(policy=POLICY, costs={'TEST': COST}, rows_by={'TEST': rows_of(bars)})
        return account.charge({'TEST': result}, packet,
                              dict(start_ms=0, runoff_end_ms=len(bars)*e.tm.BAR))

    def test_partials_and_lot_exit_count_one_WR_campaign_per_entry(self):
        b, _, _ = reversal()
        r = run([60, 79], bars=b)
        result = self.charged(r, b)
        self.assertEqual(len(result['trades']), 2)
        self.assertEqual(sum(len(t['weighted_legs']) for t in result['trades']), 4)
        wins = sum(t['net_bps'] > 0 for t in result['trades'])
        self.assertEqual(result['metrics']['base_cost']['win_rate'], wins/2)
        for raw, row in zip(r['trades'], result['trades'], strict=True):
            q = float(e.allocation(raw))
            expected = q*fsum(l['qty']*((l['price']/raw['entry_price']-1)*10000
                            -e.tm.cost_at(COST, raw['entry_ts'], l['ts'])) for l in raw['tm_legs'])
            self.assertAlmostEqual(row['net_bps'], expected)
            self.assertAlmostEqual(row['fee_bps'], 10*q)
            self.assertAlmostEqual(fsum(l['qty'] for l in row['weighted_legs']), q)
            self.assertAlmostEqual(row['cost2x_net_bps'], row['gross_bps']-2*row['cost_bps'])
        snapshot = account.snapshot(result, result)
        self.assertEqual(snapshot['lot_lock_trigger_count'], 1)
        self.assertEqual(snapshot['lot_lock_exited_campaigns'], 1)
        self.assertAlmostEqual(snapshot['lot_lock_exit_normalized_qty'], 2/3)
        self.assertEqual(snapshot['other_lot_collateral_exit_qty'], 0.)
        closed = next(t for t in result['trades'] if t['lot_lock_exit'])
        self.assertEqual(closed['exit_trigger']['lot_signal_index'], closed['signal_index'])

    def test_capacity_followup_bridge_conserves_net_without_other_lot_collateral(self):
        b, _, _ = reversal()
        for j in range(110, len(b)):
            price = 111.+(j-109)*.2
            b[j] = replace(b[j], open=b[j-1].close, high=price+1.,
                           low=b[j-1].close-1., close=price)
        child = self.charged(run([60, 79, 92, 93], bars=b), b)
        raw_parent = run([60, 79, 92, 93], bars=b, enabled=False)
        packet = dict(policy=POLICY, costs={'TEST': COST}, rows_by={'TEST': rows_of(b)})
        parent = cap_account.charge({'TEST': raw_parent}, packet,
                                    dict(start_ms=0, runoff_end_ms=len(b)*e.tm.BAR))
        bridge = account.risk_bridge(parent, child)
        self.assertAlmostEqual(bridge['residual_bps'], 0.)
        self.assertAlmostEqual(bridge['totals']['other_lot_collateral_net_bps'], 0.)
        expected = child['metrics']['terminal_net_bps']-parent['metrics']['terminal_net_bps']
        self.assertAlmostEqual(bridge['terminal_delta_bps'], expected)
        self.assertTrue(any(abs(t['capacity_followup_gross_bps']) > 0
                            for t in bridge['details']))

    def test_terminal_pending_runner_keeps_quantity_cost_funding_and_mark(self):
        b, _, _ = reversal(n=92)
        r = run([60, 79], n=92, bars=b)
        result = self.charged(r, b)
        self.assertEqual(len(result['trades']), 0)
        self.assertEqual(len(result['open_observations']), 2)
        self.assertIsNone(result['metrics']['base_cost']['win_rate'])
        for raw, row in zip(r['open_positions'], result['open_observations'], strict=True):
            q = float(e.allocation(raw))
            values = account.a.bridge._values(('O', row))
            expected = q*fsum(l['qty']*((l['price']/raw['entry_price']-1)*10000
                             -e.tm.cost_at(COST, raw['entry_ts'], l['ts'])) for l in raw['tm_legs'])
            funding = q*fsum(l['qty']*(l['ts']//(2*e.tm.BAR)
                            -raw['entry_ts']//(2*e.tm.BAR)) for l in raw['tm_legs'])
            self.assertAlmostEqual(values['net_bps'], expected)
            self.assertAlmostEqual(values['funding_bps'], funding)
            self.assertAlmostEqual(values['fee_bps'], 10*q)
            self.assertAlmostEqual(fsum(l['qty'] for l in row['weighted_legs']), q)
        self.assertAlmostEqual(result['metrics']['daily'][-1]['cumulative_net_mark_bps'],
                               result['metrics']['terminal_net_bps'])


if __name__ == '__main__':
    unittest.main()
