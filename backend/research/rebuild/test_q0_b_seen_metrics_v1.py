"""Synthetic accounting/report diagnostics; never reads the 2026 price pool."""
from copy import deepcopy
from inspect import signature
import unittest

from backend.research.rebuild import q0_b_seen_metrics_v1 as m
from backend.research.rebuild.test_q0_risk_entry_metrics_v1 import fixture
from backend.research.rebuild.test_break_channel_metrics_v1 import trade, START


class SeenAccountingTests(unittest.TestCase):
    def test_original_accounting_and_inputs_unchanged_except_evidence_label(self):
        args = fixture()[:-1]
        original_args = deepcopy(args)
        result = m.build(*args)
        base = m.accounting.build(*args)
        self.assertEqual(args, original_args)
        self.assertEqual(result['unit_metrics'], base['unit_metrics'])
        for key in ('control', 'invariants', 'attribution'):
            self.assertEqual(result[key], base[key])
        for name in m.NAMES:
            for key, value in base['stages'][name].items():
                self.assertEqual(result['stages'][name][key], value)
        self.assertEqual(result['evidence_type'], 'SEEN_DATA_REPLICATION')
        self.assertFalse(result['independent'])
        self.assertEqual(result['formal_credit'], 0)
        self.assertIn('SEEN_DATA_REUSE', result['uncertainty']['limitations'])
        self.assertNotIn('REUSED_DEV', result['uncertainty']['limitations'])
        self.assertEqual(base['uncertainty']['limitations'], m.accounting.build(*args)['uncertainty']['limitations'])

    def test_all_original_cohorts_cover_wins_losses_zero_and_differing_maxima(self):
        trades = [trade(0, -100), trade(1, 20), trade(2, -60), trade(3, 0), trade(4, 40)]
        keys = [m.ORIGIN(t) for t in trades]
        allocations = {'A_Q0': dict.fromkeys(keys, 1.), 'C_FIXED': dict.fromkeys(keys, .6),
                       'B_RISK': dict(zip(keys, [.1, 1., 1., 1., 1.]))}
        original = deepcopy(trades)
        result = m.cohort_diagnostics(trades, allocations)
        self.assertEqual(result['closed_cohort_coverage'], 'PASS')
        self.assertEqual([c['sign'] for c in result['original_A_cohorts']], [-1, 1, -1, 0, 1])
        self.assertEqual(sum(c['T'] for c in result['original_A_cohorts']), 5)
        worst = result['stage_worst_loss_cohorts']
        self.assertEqual(worst['A_Q0']['origin_keys'], [keys[0]])
        self.assertEqual(worst['B_RISK']['origin_keys'], [keys[2]])
        self.assertEqual(worst['A_Q0']['B_minus_A_net_bps'], 90)
        self.assertEqual(worst['B_RISK']['B_minus_C_net_bps'], -24)
        self.assertFalse(result['same_worst_origin_set_all_stages'])
        self.assertFalse(result['different_maxima_delta_is_causal_attribution'])
        self.assertEqual(trades, original)

    def test_atomic_simultaneous_group_sign_changes_keep_each_original_trade(self):
        trades = [trade(0, 100), trade(1, -50, 'ETH', entry=START, end=START + m.DAY),
                  trade(2, -20)]
        keys = [m.ORIGIN(t) for t in trades]
        allocations = {'A_Q0': dict.fromkeys(keys, 1.), 'C_FIXED': dict.fromkeys(keys, .5),
                       'B_RISK': dict(zip(keys, [.1, 1., 1.]))}
        result = m.cohort_diagnostics(trades, allocations)
        self.assertEqual([c['sign'] for c in result['original_A_cohorts']], [1, -1])
        self.assertEqual(result['original_A_cohorts'][0]['T'], 2)
        self.assertEqual(result['original_A_cohorts'][0]['stages']['B_RISK']['net_bps'], -40)
        self.assertEqual(len(result['stage_native_loss_runs']['B_RISK']), 1)
        self.assertEqual(result['stage_worst_loss_cohorts']['B_RISK']['T'], 3)
        self.assertEqual(result, m.cohort_diagnostics(list(reversed(trades)), allocations))

    def test_current_period_top3_comes_from_passed_ledger_never_prior_winner_ids(self):
        args = fixture()[:-1]
        result = m.build(*args)
        keys = [m.ORIGIN(t) for t in args[0] if t['net_bps'] > 0]
        for name in m.NAMES:
            retention = result['stages'][name]['current_period_top3_winner_retention']
            self.assertEqual(retention['origin_keys'], keys)
            self.assertFalse(retention['used_for_entry_weights'])
        b = result['stages']['B_RISK']['current_period_top3_winner_retention']
        self.assertAlmostEqual(b['amount_retention'], .25)

    def test_same_calendar_windows_bridge_full_marks_and_open_remains_open(self):
        result = m.build(*fixture()[:-1])
        self.assertTrue(result['same_calendar_windows'])
        for window in result['same_calendar_windows']:
            self.assertTrue(window['labels_are_post_outcome_analysis_only'])
            self.assertTrue(window['overlapping_windows_must_not_be_summed'])
            for name, stage in window['stages'].items():
                selected = [row for row in result['stages'][name]['daily']
                            if window['start_ms'] < row['mark_ts'] <= window['end_ms']]
                self.assertAlmostEqual(stage['totals']['delta']['net_bps'], sum(row['value'] for row in selected))
                self.assertEqual(stage['parity'], 'PASS')
        for stage in result['stages'].values():
            self.assertEqual(stage['metrics']['open_observations']['T'], 1)
            self.assertFalse(stage['ledger']['open'][0]['unit_trade']['actual_exit'])

    def test_drawdown_window_uses_marked_path_not_closed_loss_run(self):
        daily = [{'value': value, 'mark_ts': (i + 1) * m.DAY}
                 for i, value in enumerate([50, -10, 5, -40, 60, -1])]
        window, amount = m._max_dd_window(daily, 0)
        self.assertEqual(window, {'start_ms': m.DAY, 'end_ms': 4 * m.DAY})
        self.assertEqual(amount, 45)
        self.assertEqual(m._max_dd_window([{'value': 5, 'mark_ts': m.DAY}], 0), (None, 0.))

    def test_decision_uses_original_tolerance_and_cannot_award_independence(self):
        measured = m.build(*fixture()[:-1])
        b, c = (measured['stages'][name] for name in ('B_RISK', 'C_FIXED'))
        for stage in (b, c):
            stage['metrics']['terminal_net_amount_bps'] = 100
            stage['metrics']['terminal_cost2x_net_amount_bps'] = 50
            stage['marked_diagnostics']['marked_DD_trade_sum_bps'] = 20
            stage['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'] = 10
        b['metrics']['terminal_net_amount_bps'] = 110
        b['marked_diagnostics']['marked_DD_trade_sum_bps'] = 20.000001
        measured['uncertainty']['child_minus_parent_95pct_interval_bps_per_day'] = [1, 2]
        decision = m._decision(measured)
        self.assertFalse(decision['checks']['DD_not_worse_than_C'])
        self.assertEqual(decision['decision'], 'SEEN_PERIOD_TRADEOFF')
        b['marked_diagnostics']['marked_DD_trade_sum_bps'] = 20
        b['metrics']['base_cost'].update(completed_T=6, PF=2, realized_payoff=2)
        measured['invariants']['open_T'] = 0
        decision = m._decision(measured)
        self.assertEqual(decision['decision'], 'SEEN_PERIOD_SUPPORT')
        self.assertEqual(decision['original_technical_decision'], 'DEV_PROMISING_NO_CREDIT')
        self.assertFalse(decision['formal_pass'])
        self.assertFalse(decision['independent'])
        self.assertFalse(decision['operating_adoption'])
        self.assertEqual(decision['new_candidate_trials'], 0)
        self.assertEqual(decision['independent_comparison_uses'], 0)

    def test_inherited_minimum_and_censoring_limit_support_without_altering_goal(self):
        self.assertEqual(m.MINIMUM_CLOSED_T,
                         signature(m.accounting.shared.decide).parameters['minimum_closed_T'].default)
        measured = m.build(*fixture()[:-1])
        b, c = (measured['stages'][name] for name in ('B_RISK', 'C_FIXED'))
        for stage in (b, c):
            stage['metrics']['terminal_net_amount_bps'] = 100
            stage['metrics']['terminal_cost2x_net_amount_bps'] = 50
            stage['marked_diagnostics']['marked_DD_trade_sum_bps'] = 20
            stage['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'] = 10
        b['metrics']['terminal_net_amount_bps'] = 110
        measured['uncertainty']['child_minus_parent_95pct_interval_bps_per_day'] = [1, 2]
        result = m._decision(measured)
        self.assertTrue(result['study_goal_met'])
        self.assertEqual(result['original_technical_decision'], 'DEV_PROMISING_NO_CREDIT')
        self.assertEqual(result['decision'], 'SEEN_PERIOD_INSUFFICIENT')
        b['metrics']['base_cost'].update(completed_T=6, PF=2, realized_payoff=2)
        result = m._decision(measured)
        self.assertEqual(result['decision'], 'SEEN_PERIOD_INCONCLUSIVE')
        self.assertEqual(result['sample_sufficiency']['status'], 'UNRESOLVED_TERMINAL_POSITIONS')
        measured['invariants']['open_T'] = 0
        measured['dependence']['max_holding_days'] = 31
        result = m._decision(measured)
        self.assertEqual(result['decision'], 'SEEN_PERIOD_SUPPORT')
        self.assertTrue(result['sample_sufficiency']['holding_exceeds_bootstrap_block'])
        self.assertFalse(result['sample_sufficiency']['nominal_blocks_are_independent_samples'])
        self.assertIsNone(result['sample_sufficiency']['N_effective'])

    def test_close_clusters_reconcile_to_each_stage_without_asserting_independence(self):
        measured = m.build(*fixture()[:-1])
        clusters = measured['dependence']['simultaneous_close_clusters']
        for name in m.NAMES:
            self.assertAlmostEqual(sum(c['stages'][name]['net_bps'] for c in clusters),
                                   measured['stages'][name]['metrics']['base_cost']['net_bps'])
        self.assertEqual(sum(c['T'] for c in clusters), measured['invariants']['closed_T'])
        self.assertEqual(sum(c['unit_loss_T'] + c['unit_winner_T'] for c in clusters), 1)

    def test_zero_exposure_is_insufficient_without_invented_control(self):
        args = list(fixture()[:-1])
        args[0:3] = [[], [], []]
        args[-1] = {}
        measured = m.build(*args)
        self.assertEqual(measured['decision']['decision'], 'SEEN_PERIOD_INSUFFICIENT')
        self.assertEqual(measured['stages'], {})
        self.assertIsNone(measured['control']['k'])
        self.assertEqual(measured['unit_metrics']['base_cost']['completed_T'], 0)
        for values in measured['A_B_monetary_totals'].values():
            self.assertEqual(values['terminal']['net_bps'], 0)


if __name__ == '__main__':
    unittest.main()
