"""Synthetic calendar, cost, censor, attribution and decision tests only."""
from copy import deepcopy
import unittest

from backend.research.rebuild import parallel_exit_metrics_v1 as m
from backend.research.rebuild.test_break_channel_q1_metrics_v1 import valuation_fixture
from backend.research.rebuild.test_break_channel_source_v1 import COSTS, policy
from backend.research.rebuild.test_break_channel_metrics_v1 import events


def fixture(offset=0):
    closed, opened, rows = valuation_fixture()
    if offset:
        for r in rows['TEST']:
            r['bar_open_ts'] += offset
            r['bar_close_ts'] += offset
        for t in closed + opened:
            for key in ('signal_ts', 'entry_ts', 'exit_ts', 'mark_ts'):
                if key in t:
                    t[key] += offset
        closed = [m.source.charge(t, 'TEST', 'SYNTHETIC', policy(), COSTS, rows['TEST']) for t in closed]
        opened = [m.source.charge_open(t, 'TEST', 'SYNTHETIC', policy(), COSTS, rows['TEST']) for t in opened]
    return closed, opened, rows


def stage(closed, opened, rows, start=0, end=3 * m.DAY):
    p = policy()
    p['development_interval_ms'] = [start, end]
    return m.build_stage(closed, opened, events(closed, opened), rows, COSTS, p, ['TEST'], start, end)


def decision_inputs():
    parent = {'metrics': {
        'base_cost': {'net_bps': 100, 'completed_T': 10, 'PF': 1.2, 'realized_payoff': 2,
                      'expectancy_bps_per_trade': 10},
        'cost2x': {'net_bps': 50}, 'total_exposure_symbol_days': 10, 'open_observations': {'T': 0}},
        'diagnostics': {'lane_simultaneous_close_group_streaks': {'max_loss_trade_sum_bps': 90}},
        'marked_diagnostics': {'marked_DD_trade_sum_bps': 100}}
    child = deepcopy(parent)
    child['metrics']['base_cost'].update(net_bps=150, expectancy_bps_per_trade=15)
    child['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'] = 80
    attribution = {'closed_net_delta_bps': 50, 'marked_delta_bps_not_realized': 50,
                   'large_winner': {'amount_retention_lower': .95}}
    uncertainty = {'child_minus_parent_95pct_interval_bps_per_day': [.1, .5]}
    return parent, child, attribution, uncertainty


class MarkAndAttributionTests(unittest.TestCase):
    def test_daily_aligned_values_equal_sealed_original(self):
        closed, opened, rows = fixture()
        expected = m.source.daily_valuation(closed, opened, rows, COSTS, 0, 3 * m.DAY)
        actual = m.daily_valuation(closed, opened, rows, COSTS, 0, 3 * m.DAY)
        for old, new in zip(expected, actual):
            for key in ('date', 'mark_ts', 'value', 'gross_delta_bps', 'cumulative_net_mark_bps',
                        'cumulative_gross_mark_bps', 'full_cost_bps_at_valuation',
                        'modeled_funding_bps_at_valuation', 'active_marked_positions', 'valuation_phase'):
                self.assertEqual(old[key], new[key])

    def test_native_partial_edges_have_actual_UTC_marks_and_exact_terminal(self):
        offset = 2 * m.BAR
        closed, opened, rows = fixture(offset)
        result = stage(closed, opened, rows, offset, offset + 3 * m.DAY)
        self.assertEqual([r['mark_ts'] for r in result['daily']],
                         [m.DAY, 2 * m.DAY, 3 * m.DAY, 3 * m.DAY + offset])
        self.assertEqual([r['interval_hours'] for r in result['daily']], [16, 24, 24, 8])
        self.assertEqual([r['date'] for r in result['daily']], ['1970-01-01', '1970-01-02', '1970-01-03', '1970-01-04'])
        target = closed[0]['net_bps'] + opened[0]['hypothetical_liquidation_net_mark_bps']
        self.assertAlmostEqual(sum(r['value'] for r in result['daily']), target)
        self.assertEqual(result['metrics']['open_observations']['T'], 1)
        self.assertEqual(result['metrics']['base_cost']['completed_T'], 1)

    def test_terminal_future_open_never_changes_value(self):
        closed, opened, rows = fixture()
        expected = stage(closed, opened, rows)
        rows['TEST'][18].update(open=.0001, close=9000000, high=90000000, low=.00001)
        self.assertEqual(stage(closed, opened, rows), expected)

    def test_terminal_cost_corruption_fails_and_missing_price_is_not_interpolated(self):
        closed, opened, rows = fixture()
        corrupted = deepcopy(opened)
        for key in ('gross_mark_bps', 'hypothetical_liquidation_net_mark_bps',
                    'hypothetical_liquidation_cost2x_net_mark_bps'):
            corrupted[0][key] += 1
        with self.assertRaisesRegex(RuntimeError, 'TERMINAL_OPEN_MARK_PARITY'):
            stage(closed, corrupted, rows)
        rows['TEST'] = [r for r in rows['TEST'] if r['bar_close_ts'] != 3 * m.DAY]
        with self.assertRaisesRegex(RuntimeError, 'MISSING_COMPLETED_REPORT_MARK_PRICE'):
            stage(closed, opened, rows)

    def test_zero_trades_preserve_calendar_cost_and_no_account_claim(self):
        result = stage([], [], {})
        self.assertEqual(result['metrics']['base_cost']['completed_T'], 0)
        self.assertEqual(result['metrics']['terminal_totals_bps']['net_bps'], 0)
        self.assertEqual(len(result['daily']), 3)
        self.assertEqual(result['metrics']['exposure']['calendar_days_by_simultaneous_symbols'], {'0': 3})
        compared = m.compare(result, result, [], [], [], [], {}, {}, 0, 3 * m.DAY)
        self.assertEqual(compared['decision']['decision'], 'INSUFFICIENT')
        self.assertFalse(compared['decision']['formal_pass'])

    def test_identical_stage_has_exact_bridge_and_same_calendar_windows(self):
        offset = 2 * m.BAR
        closed, opened, rows = fixture(offset)
        s = stage(closed, opened, rows, offset, offset + 3 * m.DAY)
        original = deepcopy((closed, opened, rows))
        result = m.compare(s, s, closed, opened, closed, opened, rows, COSTS, offset, offset + 3 * m.DAY)
        self.assertEqual(result['attribution']['counts']['CC'], 1)
        self.assertEqual(result['attribution']['counts']['OO'], 1)
        self.assertEqual(result['attribution']['closed_net_delta_bps'], 0)
        self.assertEqual(result['attribution']['marked_delta_bps_not_realized'], 0)
        self.assertTrue(result['same_calendar_windows'])
        for window in result['same_calendar_windows']:
            self.assertEqual(window['child_minus_parent']['net_bps'], 0)
            self.assertFalse(window['different_maxima_subtraction_is_causal_attribution'])
            self.assertTrue(window['overlapping_windows_must_not_be_summed'])
        self.assertEqual((closed, opened, rows), original)

    def test_partial_windows_telescope_including_cost_and_funding(self):
        offset = 2 * m.BAR
        closed, opened, rows = fixture(offset)
        end = offset + 3 * m.DAY
        daily = m.daily_valuation(closed, opened, rows, COSTS, offset, end)
        prices = m._prices(rows, offset, end)
        call = lambda a, b: m._window(closed, opened, prices, COSTS, offset, end, a, b, daily)
        whole, a, b = call(offset, end), call(offset, m.DAY), call(m.DAY, end)
        for key in m.VALUE_FIELDS:
            self.assertAlmostEqual(whole['totals'][key], a['totals'][key] + b['totals'][key])
        self.assertEqual(whole['parity'], 'PASS')

    def test_actual_recovery_clock_not_date_count(self):
        start = 2 * m.BAR
        daily = [{'date': '1970-01-01', 'value': -10, 'mark_ts': m.DAY},
                 {'date': '1970-01-02', 'value': 20, 'mark_ts': 2 * m.DAY},
                 {'date': '1970-01-03', 'value': -5, 'mark_ts': 2 * m.DAY + 2 * m.BAR}]
        result = m.marked_diagnostics(daily, start)
        self.assertEqual(result['marked_DD_trade_sum_bps'], 10)
        self.assertAlmostEqual(result['max_completed_recovery_days'], 5 / 3)
        self.assertAlmostEqual(result['open_underwater_days'], 1 / 3)
        self.assertEqual(result['worst_window'], {'start_ms': start, 'end_ms': m.DAY})

    def test_paired_uncertainty_is_deterministic_and_not_independent(self):
        from datetime import date, timedelta
        parent = [{'date': (date(2025, 1, 1) + timedelta(days=i)).isoformat(), 'value': float(i % 3)} for i in range(40)]
        child = [{**r, 'value': r['value'] + .5} for r in parent]
        kwargs = {key: m.GOAL[key] for key in ('block_days', 'resamples', 'seed')}
        a = m.shared.paired_daily_uncertainty(parent, child, **kwargs)
        self.assertEqual(a, m.shared.paired_daily_uncertainty(parent, child, **kwargs))
        self.assertEqual(a['child_minus_parent_95pct_interval_bps_per_day'], [.5, .5])
        self.assertIsNone(a['N_effective'])
        self.assertIn('NOT_PROVEN_INDEPENDENT', a['limitations'])

    def test_signed_decomposition_includes_winner_flip_and_zero_parent(self):
        from backend.research.rebuild.test_break_channel_metrics_v1 import trade
        parent = [trade(0, -100), trade(1, 80), trade(2, 0), trade(3, 30)]
        child = [trade(0, 20), trade(1, -40), trade(2, -5), trade(4, 10)]
        attribution = m.bridge.symmetric_attribution(parent, [], child, [])
        result = m.net_decomposition(parent, [], child, [], attribution)
        self.assertEqual(result['common_loser_improvement_bps'], 120)
        self.assertEqual(result['common_winner_profit_cut_bps'], 80)
        self.assertEqual(result['common_winner_flipped_loss_bps'], 40)
        self.assertEqual(result['common_zero_parent_net_delta_bps'], -5)
        self.assertEqual(result['closed_net_delta_bps'], -25)
        self.assertEqual(result['parity'], 'PASS')
        self.assertTrue(result['cost_saving_already_in_net_do_not_add_again'])


class FrozenDecisionTests(unittest.TestCase):
    def test_positive_strong_improvement_is_research_only(self):
        result = m.study_decision(*decision_inputs())
        self.assertEqual(result['decision'], 'IMPROVED')
        self.assertFalse(result['formal_pass'])
        self.assertFalse(result['operating_adoption'])

    def test_less_negative_is_loss_reduction_and_economic_reject(self):
        p, c, a, u = decision_inputs()
        p['metrics']['base_cost']['net_bps'] = -100
        c['metrics']['base_cost'].update(net_bps=-50, expectancy_bps_per_trade=-5, PF=.9)
        result = m.study_decision(p, c, a, u)
        self.assertEqual(result['decision'], 'REJECT')
        self.assertTrue(result['loss_reduction'])

    def test_no_absolute_cost2_or_no_total_increment_reject(self):
        for mutation in ('cost2', 'closed', 'terminal'):
            p, c, a, u = decision_inputs()
            if mutation == 'cost2':
                c['metrics']['cost2x']['net_bps'] = -1
            elif mutation == 'closed':
                a['closed_net_delta_bps'] = 0
            else:
                a['marked_delta_bps_not_realized'] = -1
            with self.subTest(mutation=mutation):
                self.assertEqual(m.study_decision(p, c, a, u)['decision'], 'REJECT')

    def test_uncertainty_risk_retention_or_censor_blocks_strong_claim(self):
        for mutation in ('interval', 'loss', 'drawdown', 'retention', 'censor'):
            p, c, a, u = decision_inputs()
            if mutation == 'interval':
                u['child_minus_parent_95pct_interval_bps_per_day'][0] = 0
            elif mutation == 'loss':
                c['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'] = 100
            elif mutation == 'drawdown':
                c['marked_diagnostics']['marked_DD_trade_sum_bps'] = 101
            elif mutation == 'retention':
                a['large_winner']['amount_retention_lower'] = .8999
            else:
                c['metrics']['open_observations']['T'] = 1
            with self.subTest(mutation=mutation):
                self.assertEqual(m.study_decision(p, c, a, u)['decision'], 'TRADEOFF')

    def test_sample_insufficient_and_both_fixed_full_required(self):
        p, c, a, u = decision_inputs()
        c['metrics']['base_cost']['completed_T'] = 5
        self.assertEqual(m.study_decision(p, c, a, u)['decision'], 'INSUFFICIENT')
        wrap = lambda label: {'decision': {'decision': label}}
        result = m.candidate_decision(wrap('IMPROVED'), wrap('REJECT'))
        self.assertEqual(result['decision'], 'REJECT')
        self.assertFalse(result['research_child_reference_supported'])
        self.assertFalse(result['existing_Q0_or_operating_baseline_changed'])


if __name__ == '__main__':
    unittest.main()
