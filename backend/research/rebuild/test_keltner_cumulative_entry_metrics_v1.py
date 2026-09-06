"""Synthetic cumulative-entry accounting and unchanged decision criteria."""
from copy import deepcopy
import unittest

from backend.research.rebuild import keltner_cumulative_entry_metrics_v1 as m
from backend.research.rebuild.test_parallel_exit_metrics_v1 import fixture, stage, decision_inputs
from backend.research.rebuild.test_break_channel_metrics_v1 import trade, opened
from backend.research.rebuild.test_break_channel_source_v1 import COSTS


def t(i, net):
    return {**trade(i, net), 'entry_price': 100.0}


class EntryDecisionTests(unittest.TestCase):
    def test_unchanged_numeric_goal_and_old_module_unmodified(self):
        old = deepcopy(m.previous.GOAL)
        for key in ('minimum_closed_T', 'large_winner_capped_retention_min',
                    'absolute', 'increment', 'risk', 'strong_evidence', 'block_days', 'resamples', 'seed'):
            self.assertEqual(m.GOAL[key], old[key])
        result = m.study_decision(*decision_inputs())
        self.assertEqual(result['decision'], 'IMPROVED')
        self.assertEqual(result['comparison_type'], 'ENTRY_FILTER')
        for key in ('formal_pass', 'operating_adoption', 'independent', 'prior_D_verdict_changed'):
            self.assertFalse(result[key])
        self.assertEqual(m.previous.GOAL, old)

    def test_negative_absolute_is_reject_despite_partial_gain(self):
        p, n, a, u = decision_inputs()
        n['metrics']['base_cost'].update(net_bps=-20, expectancy_bps_per_trade=-2, PF=.9)
        n['metrics']['cost2x']['net_bps'] = -70
        result = m.study_decision(p, n, a, u)
        self.assertEqual(result['decision'], 'REJECT')
        self.assertTrue(result['loss_reduction'])
        self.assertTrue(result['partial_workbench_checks_met'])
        self.assertFalse(result['partial_workbench_is_economic_PASS'])

    def test_cost_stress_gain_retention_and_open_do_not_disappear(self):
        for key in ('cost2', 'increment', 'retention', 'open', 'uncertainty', 'risk'):
            p, n, a, u = decision_inputs()
            if key == 'cost2':
                n['metrics']['cost2x']['net_bps'] = 0
            elif key == 'increment':
                a['closed_net_delta_bps'] = 0
            elif key == 'retention':
                a['large_winner']['amount_retention_lower'] = .89999
            elif key == 'open':
                n['metrics']['open_observations']['T'] = 1
            elif key == 'uncertainty':
                u['child_minus_parent_95pct_interval_bps_per_day'][0] = 0
            else:
                n['marked_diagnostics']['marked_DD_trade_sum_bps'] = 101
            with self.subTest(key=key):
                expected = 'REJECT' if key in ('cost2', 'increment') else 'TRADEOFF'
                self.assertEqual(m.study_decision(p, n, a, u)['decision'], expected)

    def test_too_few_trades_does_not_become_an_entry_PASS(self):
        p, n, a, u = decision_inputs()
        n['metrics']['base_cost']['completed_T'] = 5
        self.assertEqual(m.study_decision(p, n, a, u)['decision'], 'INSUFFICIENT')

    def test_separate_period_and_comparator_verdicts_no_sum_rescue(self):
        wrap = lambda decision: {'decision': {'decision': decision}}
        result = m.candidate_decision({
            'DEV2025': {'versus_P': wrap('IMPROVED'), 'versus_D': wrap('IMPROVED')},
            'SEEN2026': {'versus_P': wrap('REJECT'), 'versus_D': wrap('TRADEOFF')},
        })
        self.assertEqual(result['decision'], 'REJECT')
        self.assertEqual(result['by_period_and_base']['SEEN2026']['versus_D'], 'TRADEOFF')
        self.assertFalse(result['research_child_reference_supported'])
        self.assertFalse(result['prior_P_D_verdicts_changed'])
        with self.assertRaisesRegex(ValueError, 'MISSING_CUMULATIVE'):
            m.candidate_decision({})


class EntryAttributionTests(unittest.TestCase):
    def test_identical_ledger_has_zero_delta_and_entry_labels(self):
        closed, opened_, rows = fixture()
        s = stage(closed, opened_, rows)
        saved = deepcopy((s, closed, opened_, rows))
        result = m.compare(s, s, closed, opened_, closed, opened_, rows, COSTS, 0, 3 * m.previous.DAY)
        self.assertEqual(result['comparison_type'], 'ENTRY_FILTER')
        self.assertEqual(result['attribution']['comparison_type'], 'ENTRY_FILTER')
        self.assertEqual(result['decision']['comparison_type'], 'ENTRY_FILTER')
        self.assertEqual(result['attribution']['closed_net_delta_bps'], 0)
        self.assertEqual(result['attribution']['counts']['OO'], 1)
        self.assertFalse(result['same_entry_exit_only_comparison_claimed'])
        self.assertFalse(result['excluded_opportunities_are_zero_profit_wins'])
        for row in result['same_calendar_windows']:
            self.assertEqual(row['child_minus_parent']['net_bps'], 0)
            self.assertFalse(row['different_maxima_subtraction_is_causal_attribution'])
        self.assertEqual((s, closed, opened_, rows), saved)

    def test_mismatched_comparison_calendar_fails(self):
        closed, opened_, rows = fixture()
        s = stage(closed, opened_, rows)
        broken = deepcopy(s)
        broken['comparison_calendar_ms'][0] += m.previous.BAR
        with self.assertRaisesRegex(ValueError, 'COMPARISON_CALENDAR_MISMATCH'):
            m.compare(s, broken, closed, opened_, closed, opened_, rows, COSTS, 0, 3 * m.previous.DAY)

    def test_original_fixed_harm_filtering_and_new_profit_telescope(self):
        p = [t(0, -100), t(1, 50), t(2, -60)]
        d = [t(0, -70), t(1, -20), t(2, -60)]
        n = [t(1, -20), t(3, 10)]
        saved = deepcopy((p, d, n))
        result = m.original_entry_effects(p, [], d, [], n, [])
        self.assertEqual(result['prior_fixed_D_minus_P_closed_net_bps'], -40)
        self.assertEqual(result['N_original_origins_minus_prior_fixed_closed_net_bps'], 130)
        self.assertEqual(result['N_new_not_P_closed_totals_bps']['net_bps'], 10)
        self.assertEqual(result['N_minus_P_full_closed_net_bps'], 100)
        self.assertEqual(result['original_origin_net_decomposition']['common_closed_net_delta_bps'], 0)
        harmful = result['outcome_categories']['D_harmful_closed']
        self.assertEqual(harmful['D_fixed_minus_P_closed_net_bps'], -70)
        self.assertEqual(harmful['N_minus_D_fixed_closed_net_bps'], 0)
        self.assertEqual(harmful['N_closed_T'], 1)
        self.assertEqual(result['outcome_categories']['D_unchanged_closed']['N_absent_T'], 1)
        self.assertEqual(result['original_origin_change_attribution']['counts']['removed_C'], 2)
        self.assertFalse(result['absent_N_entry_is_zero_profit_trade_or_win'])
        self.assertFalse(result['new_opportunity_net_is_fixed_bonus'])
        self.assertEqual(result['parity'], 'PASS')
        self.assertEqual((p, d, n), saved)

    def test_common_open_is_not_removed_or_new_victory(self):
        p, d, n = [t(0, -20)], [t(0, -10)], [t(0, -10)]
        o = {**opened(1), 'entry_price': 100.0}
        result = m.original_entry_effects(p, [o], d, [o], n, [o])
        self.assertEqual(result['original_origin_change_attribution']['counts']['OO'], 1)
        self.assertEqual(result['original_origin_change_attribution']['counts']['removed_O'], 0)
        self.assertEqual(result['outcome_categories']['censor_transition']['N_open_T'], 1)
        self.assertEqual(result['N_new_not_P_open_T'], 0)

    def test_censor_conversion_is_separate_from_avoided_loss(self):
        p, d = [t(0, -20)], [t(0, -10)]
        o = {**opened(0), 'entry_price': 100.0}
        result = m.original_entry_effects(p, [], d, [], [], [o])
        self.assertEqual(result['original_origin_change_attribution']['counts']['CO'], 1)
        self.assertEqual(result['original_origin_change_attribution']['removed_completed_parent_loss_bps'], 0)
        self.assertEqual(result['original_origin_net_decomposition']['other_origin_group_signed_net_delta_bps']['CO'], 10)

    def test_fixed_reference_requires_all_original_origins_and_same_entry(self):
        p = [t(0, -100), t(1, 50)]
        with self.assertRaisesRegex(ValueError, 'PRESERVE_ALL_PARENT'):
            m.original_entry_effects(p, [], p[:1], [], p, [])
        d = deepcopy(p)
        d[0]['entry_price'] = 101
        with self.assertRaisesRegex(ValueError, 'FIXED_ENTRY_FILL_CHANGED'):
            m.original_entry_effects(p, [], d, [], p, [])


class CumulativeTableTests(unittest.TestCase):
    def test_runner_to_table_and_original_origin_bridge_synthetic(self):
        from backend.research.rebuild import keltner_cumulative_entry_v1 as runner
        from backend.research.rebuild.test_parallel_exit_keltner_v1 import bars, bundle
        from backend.research.rebuild.test_break_channel_source_v1 import policy
        rows = bars(43)
        rows[0]['close'] = 99.0
        b = bundle(rows, [0, 3, 16, 35])
        b['ema20'][5] = 100.0
        b['ema20'][-1] = 100.0
        rows_by, bundles = {'TEST': rows}, {'TEST': b}
        end = 43 * m.previous.BAR
        p = policy(); p['development_interval_ms'] = [0, end]
        original = deepcopy((rows_by, bundles, p))
        parent = runner.previous.replay_stage('KELTNER', bundles, rows_by, COSTS, p, 0, end, 'P')
        prior = runner.previous.replay_stage('KELTNER', bundles, rows_by, COSTS, p, 0, end, 'FULL')
        disabled = runner.replay(rows_by, bundles, COSTS, p, 0, end, 'DISABLED', enabled=False)
        runner.assert_D_parity(disabled, prior)
        n = runner.replay(rows_by, bundles, COSTS, p, 0, end, 'N_FULL')
        self.assertEqual([t['signal_index'] for t in prior['trades']], [0, 16])
        self.assertEqual([t['signal_index'] for t in n['trades']], [3, 16])
        self.assertEqual(len(n['open_observations']), 1)
        self.assertEqual(n['open_observations'][0]['pending_exit_signal_ts'], end)
        views = [parent, prior, n]
        stages = [m.build_stage(v['trades'], v['open_observations'], v['events'], rows_by,
                               COSTS, p, ['TEST'], 0, end) for v in views]
        compare = lambda i, j: m.compare(stages[i], stages[j], views[i]['trades'],
            views[i]['open_observations'], views[j]['trades'], views[j]['open_observations'],
            rows_by, COSTS, 0, end)
        pd, pn, dn = compare(0, 1), compare(0, 2), compare(1, 2)
        table = {row['metric']: row for row in m.cumulative_table(*stages, pd, pn, dn)}
        self.assertEqual(table['closed_T']['N'], 2)
        self.assertEqual(table['open_T']['N'], 1)
        self.assertEqual(dn['attribution']['counts']['removed_C'], 1)
        self.assertEqual(dn['attribution']['counts']['new_C'], 1)
        self.assertEqual(dn['attribution']['counts']['OO'], 1)
        self.assertEqual(dn['attribution']['comparison_type'], 'ENTRY_FILTER')
        effect = m.original_entry_effects(parent['trades'], parent['open_observations'],
            prior['trades'], prior['open_observations'], n['trades'], n['open_observations'])
        self.assertAlmostEqual(effect['N_minus_P_full_closed_net_bps'], table['closed_net_bps']['N_minus_P'])
        self.assertAlmostEqual(effect['N_new_not_P_closed_totals_bps']['net_bps'], n['trades'][0]['net_bps'])
        self.assertEqual(effect['parity'], 'PASS')
        self.assertEqual((rows_by, bundles, p), original)

    def test_table_reports_actual_denominators_open_mark_and_separate_deltas(self):
        closed, opened_, rows = fixture()
        p = stage(closed, opened_, rows)
        comparison = m.compare(p, p, closed, opened_, closed, opened_, rows, COSTS, 0, 3 * m.previous.DAY)
        table = {r['metric']: r for r in m.cumulative_table(p, p, p, comparison, comparison, comparison)}
        self.assertEqual(table['closed_T']['N'], 1)
        self.assertEqual(table['open_T']['N'], 1)
        self.assertEqual(table['entries_T']['N'], 2)
        self.assertEqual(table['closed_net_bps']['N_minus_D'], 0)
        self.assertEqual(table['closed_net_bps']['N_minus_P'], 0)
        self.assertAlmostEqual(table['open_net_mark_bps_hypothetical']['N'],
                               opened_[0]['hypothetical_liquidation_net_mark_bps'])
        self.assertEqual(table['winner_amount_retention_vs_P_lower']['N'], 1)
        self.assertEqual(table['large_winner_amount_retention_vs_D_lower']['P'], None)

    def test_increment_retention_is_unclipped_observed_ratio(self):
        closed, opened_, rows = fixture()
        p = stage(closed, opened_, rows)
        d, n = deepcopy(p), deepcopy(p)
        p['metrics']['base_cost']['net_bps'] = -100
        d['metrics']['base_cost']['net_bps'] = 100
        n['metrics']['base_cost']['net_bps'] = 150
        n['metrics']['cost2x']['net_bps'] = -20
        result = m.summarize_cumulative(p, d, n, 'SYNTHETIC')
        self.assertEqual(result['D_observed_increment_retained_fraction'], 1.25)
        self.assertEqual(result['N_remaining_closed_cost2x_deficit_bps'], 20)
        self.assertFalse(result['future_guarantee_or_execution_feature'])
        d['metrics']['base_cost']['net_bps'] = -100
        self.assertIsNone(m.summarize_cumulative(p, d, n, 'SYNTHETIC')['D_observed_increment_retained_fraction'])

    def test_table_and_summary_reject_cross_calendar_comparison(self):
        closed, opened_, rows = fixture()
        p = stage(closed, opened_, rows)
        n = deepcopy(p)
        n['comparison_calendar_ms'][0] += m.previous.BAR
        with self.assertRaisesRegex(ValueError, 'TABLE_CALENDAR_MISMATCH'):
            m.cumulative_table(p, p, n)
        with self.assertRaisesRegex(ValueError, 'SUMMARY_CALENDAR_MISMATCH'):
            m.summarize_cumulative(p, p, n, 'SYNTHETIC')


if __name__ == '__main__':
    unittest.main()
