"""Synthetic notional/accounting tests; no historical data or candidate outcomes."""
from copy import deepcopy
import math
import unittest

from backend.research.rebuild import q0_risk_entry_metrics_v1 as m
from backend.research.rebuild.test_break_channel_metrics_v1 import trade, events, START
from backend.research.rebuild.test_break_channel_q1_metrics_v1 import valuation_fixture
from backend.research.rebuild.test_break_channel_source_v1 import COSTS, policy


def fixture():
    closed, opened, prices = valuation_fixture()
    p = policy()
    p['development_interval_ms'] = [0, 3 * m.DAY]
    weights = {m.ORIGIN(closed[0]): {'weight': .25, 'available_at': 0},
               m.ORIGIN(opened[0]): {'weight': .75, 'available_at': m.DAY}}
    windows = [{'label': 'all', 'start_ms': 0, 'end_ms': 3 * m.DAY},
               {'label': 'tail', 'start_ms': m.DAY, 'end_ms': 3 * m.DAY}]
    return closed, opened, events(closed, opened), prices, deepcopy(COSTS), p, ['TEST'], 0, 3 * m.DAY, weights, windows


class WeightedAccountingTests(unittest.TestCase):
    def test_preserve_unit_ledger_prices_hold_cost_floor_and_signs(self):
        args = fixture()
        original = deepcopy(args)
        result = m.build(*args)
        self.assertEqual(args, original)
        closed, opened, ev, _, _, p, symbols = args[:7]
        self.assertEqual(result['unit_metrics'], m.shared.summarize(closed, opened, ev, p, symbols))
        a, b = result['stages']['A_Q0'], result['stages']['B_RISK']
        self.assertEqual(a['metrics']['base_cost']['win_rate'], b['metrics']['base_cost']['win_rate'])
        self.assertNotEqual(a['metrics']['base_cost']['expectancy_bps_per_trade'],
                            b['metrics']['base_cost']['expectancy_bps_per_trade'])
        for stage in result['stages'].values():
            self.assertEqual(stage['ledger']['closed'][0]['unit_trade'], closed[0])
            self.assertEqual(stage['ledger']['open'][0]['unit_trade'], opened[0])
            self.assertEqual(stage['metrics']['raw_signals'], len(ev))
            self.assertEqual(stage['metrics']['open_observations']['T'], 1)
            self.assertEqual(stage['exposure']['unweighted_occupancy']['position_days'], 3)
        row = b['ledger']['closed'][0]
        self.assertGreaterEqual(row['unit_trade']['cost_bps'], 20)
        self.assertAlmostEqual(row['weighted_values']['cost_bps'], .25 * row['unit_trade']['cost_bps'])
        self.assertIn('NOT_ACCOUNT', row['basis'])

    def test_control_is_post_hoc_holding_weight_not_mean_trade_weight(self):
        result = m.build(*fixture())
        self.assertAlmostEqual(result['control']['k'], 7 / 12)
        self.assertNotEqual(result['control']['k'], .5)
        b, c = (result['stages'][key] for key in ('B_RISK', 'C_FIXED'))
        self.assertAlmostEqual(b['exposure']['nominal_weighted_position_days'], 1.75)
        self.assertAlmostEqual(c['exposure']['nominal_weighted_position_days'], 1.75)
        self.assertTrue(result['control']['ex_post_analysis_only'])
        self.assertFalse(result['control']['fed_back_to_candidate_weights_or_reference_volatility'])
        self.assertNotEqual(b['daily'], c['daily'])

    def test_scaled_shared_full_marks_and_funding_bridge_terminal_open_cost(self):
        args = fixture()
        result = m.build(*args)
        closed, opened, _, prices, costs = args[:5]
        one = m.source.daily_valuation(closed, [], prices, costs, 0, 3 * m.DAY)
        two = m.source.daily_valuation([], opened, prices, costs, 0, 3 * m.DAY)
        b = result['stages']['B_RISK']
        for i, actual in enumerate(b['daily']):
            for field in m.DAILY_FIELDS:
                self.assertAlmostEqual(actual[field], .25 * one[i][field] + .75 * two[i][field])
            self.assertEqual(actual['active_marked_positions'], one[i]['active_marked_positions'] + two[i]['active_marked_positions'])
        expected = .25 * closed[0]['net_bps'] + .75 * opened[0]['hypothetical_liquidation_net_mark_bps']
        self.assertAlmostEqual(b['metrics']['terminal_net_amount_bps'], expected)
        self.assertAlmostEqual(b['daily'][-1]['cumulative_net_mark_bps'], expected)
        self.assertAlmostEqual(b['metrics']['open_observations']['modeled_funding_accrued_bps'], .75 * opened[0]['modeled_funding_accrued_bps'])
        self.assertFalse(b['ledger']['open'][0]['unit_trade']['actual_exit'])
        self.assertNotIn('exit_ts', b['ledger']['open'][0]['unit_trade'])
        self.assertEqual(b['ledger']['open'][0]['unit_trade']['funding_settlements_elapsed'], opened[0]['funding_settlements_elapsed'])

    def test_c_constant_scaling_preserves_pf_and_scales_amount_drawdown(self):
        result = m.build(*fixture())
        a, c = (result['stages'][key] for key in ('A_Q0', 'C_FIXED'))
        k = result['control']['k']
        for key in ('terminal_net_amount_bps', 'terminal_cost2x_net_amount_bps'):
            self.assertAlmostEqual(c['metrics'][key], k * a['metrics'][key])
        self.assertAlmostEqual(c['marked_diagnostics']['marked_DD_trade_sum_bps'], k * a['marked_diagnostics']['marked_DD_trade_sum_bps'])
        self.assertEqual(c['metrics']['base_cost']['PF'], a['metrics']['base_cost']['PF'])
        for original, scaled in zip(a['daily'], c['daily']):
            self.assertAlmostEqual(scaled['value'], k * original['value'])
        self.assertAlmostEqual(c['original_profit_retention']['all_winners']['amount_retention'], k)

    def test_same_calendar_contributions_telescope_and_keep_preexisting_hold_labels(self):
        args = fixture()
        args[-1].append({'label': 'first', 'start_ms': 0, 'end_ms': m.DAY})
        result = m.build(*args)
        windows = {w['label']: w for w in result['windows']}
        for name in result['stages']:
            whole, first, tail = (windows[key]['stages'][name] for key in ('all', 'first', 'tail'))
            for field in m.VALUE_FIELDS:
                self.assertAlmostEqual(whole['totals']['delta'][field], first['totals']['delta'][field] + tail['totals']['delta'][field])
        rows = windows['tail']['stages']['B_RISK']['position_contributions']
        self.assertTrue(next(r for r in rows if r['entry_ts'] == 0)['entry_before_window'])
        new = next(r for r in rows if r['entry_ts'] == m.DAY)
        self.assertFalse(new['entry_before_window'])
        self.assertEqual(new['weight_available_at'], m.DAY)
        self.assertEqual(new['entry_weight'], .75)
        self.assertTrue(windows['tail']['overlapping_original_windows_must_not_be_summed_as_disjoint_periods'])

    def test_attribution_separates_saved_net_loss_foregone_profit_and_cost_bridge(self):
        ts = [trade(0, 100), trade(1, -60), trade(2, 0)]
        ids = [m.ORIGIN(t) for t in ts]
        a = dict.fromkeys(ids, 1)
        b = dict(zip(ids, [.5, .25, .1]))
        result = m.attribution(ts, [], a, b)
        self.assertEqual(result['loss_amount_reduction_bps_signed'], 45)
        self.assertEqual(result['foregone_winner_amount_bps_signed'], 50)
        self.assertEqual(result['closed_delta']['net_bps'], -5)
        self.assertEqual(result['closed_cost_amount_saving_bps_signed'], 43)
        self.assertAlmostEqual(result['terminal_delta']['gross_bps'] - result['terminal_delta']['cost_bps'], -5)
        self.assertEqual(result['new_T'], 0)
        self.assertEqual(result['removed_T'], 0)
        reverse = m.attribution(ts, [], b, a)
        self.assertEqual(reverse['closed_delta']['net_bps'], 5)

    def test_mixed_simultaneous_group_sign_can_change_without_any_trade_sign_change(self):
        ts = [trade(0, 100), trade(1, -50, 'ETH', entry=START, end=START + m.DAY)]
        w = {m.ORIGIN(ts[0]): .1, m.ORIGIN(ts[1]): 1}
        weighted, _ = m.weighted_copies(ts, [], w)
        self.assertEqual([t['net_bps'] > 0 for t in ts], [t['net_bps'] > 0 for t in weighted])
        changes = m._group_changes(ts, weighted)
        self.assertEqual(changes['changed_simultaneous_group_sign_T'], 1)
        self.assertEqual(changes['groups'][0]['original_group_net_bps'], 50)
        self.assertEqual(changes['groups'][0]['weighted_group_net_bps'], -40)
        diag = m.shared.diagnostics(weighted, START, START + 10 * m.DAY)
        self.assertEqual(diag['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'], 40)
        reversed_diag = m.shared.diagnostics(list(reversed(weighted)), START, START + 10 * m.DAY)
        self.assertEqual(diag, reversed_diag)

    def test_exposure_exit_entry_atomic_max_and_holding_integral(self):
        ts = [trade(0, entry=START, end=START + m.DAY),
              trade(1, entry=START + m.DAY, end=START + 2 * m.DAY)]
        w = {m.ORIGIN(ts[0]): .25, m.ORIGIN(ts[1]): .75}
        exp = m.exposure(ts, [], w, START, START + 2 * m.DAY)
        self.assertEqual(exp['unweighted_occupancy']['max_simultaneous_positions'], 1)
        self.assertEqual(exp['max_simultaneous_nominal_weighted_open_slots'], .75)
        self.assertEqual(exp['nominal_weighted_position_days'], 1)
        self.assertEqual(exp['mean_nominal_weighted_open_slots'], .5)

    def test_no_epsilon_zero_missing_negative_excess_and_nonfinite_weights_fail(self):
        args = fixture()
        first = next(iter(args[-2]))
        for invalid in (0, -1, 1.001, math.nan, math.inf, True):
            modified = deepcopy(args)
            modified[-2][first]['weight'] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'ENTRY_WEIGHT'):
                m.build(*modified)
        missing = deepcopy(args)
        del missing[-2][first]
        with self.assertRaisesRegex(ValueError, 'COVERAGE'):
            m.build(*missing)
        with self.assertRaisesRegex(ValueError, 'ZERO_TOTAL_HOLDING'):
            m.control_weight([], [], {})
        bad = deepcopy(args)
        bad[1][0]['mark_ts'] -= m.DAY
        with self.assertRaisesRegex(ValueError, 'OPEN_POSITION'):
            m.build(*bad)

    def test_period_symbol_terminal_bridges_and_paired_short_calendar_limitation(self):
        result = m.build(*fixture())
        for stage in result['stages'].values():
            target = stage['metrics']['terminal_net_amount_bps']
            self.assertAlmostEqual(sum(r['net_bps'] for r in stage['by_mark_month'].values()), target)
            self.assertAlmostEqual(sum(r['terminal_net_bps'] for r in stage['by_symbol_marked'].values()), target)
        u = result['uncertainty']
        self.assertEqual(u['block_days'], 30)
        self.assertEqual(u['resamples'], 1000)
        self.assertEqual(u['seed'], 1178)
        self.assertEqual(u['status'], 'INSUFFICIENT_CALENDAR')
        self.assertEqual(u['child_minus_parent_95pct_interval_bps_per_day'], [None, None])
        self.assertAlmostEqual(u['child_minus_parent_marked_delta_sum_bps'],
                               result['attribution']['B_minus_C']['terminal_delta']['net_bps'])


if __name__ == '__main__':
    unittest.main()
