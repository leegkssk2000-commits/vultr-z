"""Synthetic accounting only; no new market replay or candidate measurement."""
from copy import deepcopy
import unittest

from backend.research.rebuild import keltner_opportunity_reservation_metrics_v1 as m
from backend.research.rebuild.test_parallel_exit_metrics_v1 import fixture, stage
from backend.research.rebuild.test_break_channel_source_v1 import COSTS


def decision_inputs(*, negative=False, unchanged=False):
    closed, opened, rows = fixture()
    base = stage(closed, opened, rows)
    b = base['metrics']
    net = -100 if negative else 100
    b['base_cost'].update(net_bps=net, gross_bps=net + 40, completed_T=10,
                          PF=.8 if negative else 1.2, realized_payoff=2,
                          expectancy_bps_per_trade=net / 10)
    b['cost2x'].update(net_bps=net - 40, expectancy_bps_per_trade=(net - 40) / 10)
    b['terminal_totals_bps'].update(net_bps=net - 20, cost2x_net_bps=net - 80)
    b['closed_plus_hypothetical_terminal_mark_bps'] = net - 20
    base['marked_diagnostics']['marked_DD_trade_sum_bps'] = 100
    base['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'] = 90
    child = deepcopy(base)
    amount = 0 if unchanged else 50
    cb = child['metrics']
    cb['base_cost']['net_bps'] += amount
    cb['base_cost']['gross_bps'] += amount
    cb['base_cost']['expectancy_bps_per_trade'] += amount / 10
    cb['cost2x']['net_bps'] += amount
    cb['cost2x']['expectancy_bps_per_trade'] += amount / 10
    cb['terminal_totals_bps']['net_bps'] += amount
    cb['terminal_totals_bps']['gross_bps'] += amount
    cb['terminal_totals_bps']['cost2x_net_bps'] += amount
    cb['closed_plus_hypothetical_terminal_mark_bps'] += amount
    child['daily'][-1]['value'] += amount
    if not unchanged:
        child['marked_diagnostics']['marked_DD_trade_sum_bps'] -= 10
        child['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'] -= 10
    attribution = {'closed_net_delta_bps': amount, 'marked_delta_bps_not_realized': amount,
                   'large_winner': {'amount_retention_lower': 1.0}}
    uncertainty = {'child_minus_parent_95pct_interval_bps_per_day': [0 if unchanged else -.1, .5]}
    return base, child, attribution, uncertainty


def comparison_set(decision):
    result = {}
    for base in ('P', 'D', 'N'):
        copied = deepcopy(decision)
        copied['comparison_role'] = base + ('_PRIMARY' if base == 'N' else '_CONTEXT')
        result[base + '_to_M'] = {'decision': copied}
    return result


class ReservationDecisionTests(unittest.TestCase):
    def test_inherited_numbers_and_original_goal_are_unmodified(self):
        saved = deepcopy(m.previous.GOAL)
        for key in saved:
            if key != 'both_comparisons':
                self.assertEqual(m.GOAL[key], saved[key])
        self.assertEqual(m.GOAL['inherited_N_comparison_definition'], saved['both_comparisons'])
        self.assertEqual((m.GOAL['minimum_closed_T'], m.GOAL['large_winner_capped_retention_min'],
                          m.GOAL['block_days'], m.GOAL['resamples'], m.GOAL['seed']), (6, .9, 30, 1000, 1178))
        self.assertEqual(m.EPS, 1e-7)
        m.study_decision(*decision_inputs())
        self.assertEqual(m.previous.GOAL, saved)

    def test_repair_observation_does_not_override_open_and_uncertainty(self):
        data = decision_inputs()
        original = deepcopy(data)
        result = m.study_decision(*data)
        self.assertEqual(result['legacy_study_decision'], 'TRADEOFF')
        self.assertEqual(result['absolute_economic_decision'], 'CLOSED_ABSOLUTE_CHECKS_MET')
        self.assertEqual(result['incremental_decision'], 'IMPROVED_OBSERVATION')
        self.assertTrue(result['recovery_2025_checks_met'])
        self.assertTrue(result['open_censoring_blocks_strong_verdict'])
        self.assertFalse(result['uncertainty_or_open_blockers_are_waived'])
        for key in ('formal_pass', 'operating_adoption', 'independent', 'absolute_economic_PASS_claimed'):
            self.assertFalse(result[key])
        self.assertEqual(data, original)

    def test_negative_equal_2026_is_absolute_reject_and_unchanged_preserved(self):
        result = m.study_decision(*decision_inputs(negative=True, unchanged=True))
        self.assertEqual(result['decision'], 'REJECT')
        self.assertEqual(result['absolute_economic_decision'], 'REJECT')
        self.assertEqual(result['incremental_decision'], 'UNCHANGED')
        self.assertTrue(result['preservation_2026_checks_met'])
        self.assertFalse(result['recovery_2025_checks_met'])

    def test_cost2_damage_risk_damage_and_profit_cut_prevent_retention(self):
        for damage in ('cost2', 'terminal_cost2', 'DD', 'loss_run', 'large_profit'):
            p, n, a, u = decision_inputs()
            if damage == 'cost2':
                n['metrics']['cost2x']['net_bps'] = p['metrics']['cost2x']['net_bps'] - 1
            elif damage == 'terminal_cost2':
                n['metrics']['terminal_totals_bps']['cost2x_net_bps'] = p['metrics']['terminal_totals_bps']['cost2x_net_bps'] - 1
            elif damage == 'DD':
                n['marked_diagnostics']['marked_DD_trade_sum_bps'] = 101
            elif damage == 'loss_run':
                n['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'] = 91
            else:
                a['large_winner']['amount_retention_lower'] = .89999
            with self.subTest(damage=damage):
                result = m.study_decision(p, n, a, u)
                self.assertFalse(result['recovery_2025_checks_met'])
                self.assertFalse(result['preservation_2026_checks_met'])
                self.assertEqual(result['incremental_decision'], 'TRADEOFF')

    def test_absolute_loss_reduction_never_becomes_economic_pass(self):
        result = m.study_decision(*decision_inputs(negative=True))
        self.assertEqual(result['absolute_economic_decision'], 'REJECT')
        self.assertEqual(result['incremental_decision'], 'IMPROVED_OBSERVATION')
        self.assertTrue(result['loss_reduction'])

    def test_insufficient_sample_preserves_undefined_fields(self):
        p, n, a, u = decision_inputs()
        n['metrics']['base_cost']['completed_T'] = 5
        result = m.study_decision(p, n, a, u)
        self.assertEqual(result['absolute_economic_decision'], 'INSUFFICIENT')
        self.assertFalse(result['recovery_2025_checks_met'])

    def test_same_totals_but_different_daily_path_are_not_unchanged(self):
        p, n, a, u = decision_inputs(unchanged=True)
        n['daily'][0]['value'] += 1
        n['daily'][1]['value'] -= 1
        result = m.study_decision(p, n, a, u)
        self.assertFalse(result['same_economic_values_and_daily_path_within_existing_error'])
        self.assertNotEqual(result['incremental_decision'], 'UNCHANGED')

    def test_comparator_role_and_calendar_must_be_explicit_valid(self):
        with self.assertRaisesRegex(ValueError, 'COMPARISON_ROLE'):
            m.study_decision(*decision_inputs(), role='NEW_FORMAL_BASELINE')
        p, n, a, u = decision_inputs()
        n['comparison_calendar_ms'][1] += m.previous.previous.BAR
        with self.assertRaisesRegex(ValueError, 'CALENDAR_MISMATCH'):
            m.study_decision(p, n, a, u)

    def test_2026_equality_does_not_erase_2025_repair_or_negative_absolute(self):
        repaired = m.study_decision(*decision_inputs())
        preserved = m.study_decision(*decision_inputs(negative=True, unchanged=True))
        result = m.candidate_decision({'DEV2025': comparison_set(repaired), 'SEEN2026': comparison_set(preserved)})
        self.assertEqual(result['decision'], 'REJECT')
        self.assertTrue(result['partial_workcopy_retained'])
        self.assertEqual(result['workcopy_decision'], 'PARTIAL_DEVELOPMENT_WORKCOPY_RETAINED')
        self.assertEqual(result['incremental_decision_by_period']['SEEN2026'], 'UNCHANGED')
        self.assertFalse(result['research_child_reference_supported'])
        self.assertFalse(result['automatic_research_baseline_replacement'])

    def test_period_damage_or_missing_context_cannot_be_hidden(self):
        repaired = m.study_decision(*decision_inputs())
        p, n, a, u = decision_inputs(negative=True, unchanged=True)
        n['marked_diagnostics']['marked_DD_trade_sum_bps'] += 1
        harmed = m.study_decision(p, n, a, u)
        values = {'DEV2025': comparison_set(repaired), 'SEEN2026': comparison_set(harmed)}
        self.assertFalse(m.candidate_decision(values)['partial_workcopy_retained'])
        del values['SEEN2026']['P_to_M']
        with self.assertRaisesRegex(ValueError, 'P_D_N_COMPARISONS'):
            m.candidate_decision(values)
        with self.assertRaisesRegex(ValueError, 'TWO_FROZEN_PERIODS'):
            m.candidate_decision({})

    def test_contextual_comparator_cannot_be_mislabeled_primary(self):
        repaired = m.study_decision(*decision_inputs())
        values = {'DEV2025': comparison_set(repaired), 'SEEN2026': comparison_set(repaired)}
        values['DEV2025']['P_to_M']['decision']['comparison_role'] = 'N_PRIMARY'
        with self.assertRaisesRegex(ValueError, 'COMPARATOR_ROLE_MISMATCH'):
            m.candidate_decision(values)


class ReservationAccountingTests(unittest.TestCase):
    def test_synthetic_shared_charge_full_stage_table_candidate_and_report_integration(self):
        from backend.research.rebuild import keltner_opportunity_reservation_v1 as runner
        from backend.research.rebuild import parallel_exit_keltner_v1 as d
        from backend.research.rebuild import keltner_cumulative_entry_adapter_v1 as n
        from backend.research.rebuild.test_parallel_exit_keltner_v1 import bars, bundle
        from backend.research.rebuild.test_break_channel_source_v1 import policy
        rows = bars(45)
        rows[0]['close'] = 99.0
        b = bundle(rows, [0, 3, 12, 13, 14, 18, 27, 30, 42])
        end = 45 * d.BAR
        p = policy(); p['development_interval_ms'] = [0, end]
        raw = {
            'P': d.replay(rows, b, eval_start_ms=0, eval_end_ms=end, enable_change=False),
            'D': d.replay(rows, b, eval_start_ms=0, eval_end_ms=end, enable_change=True),
            'N': n.replay(rows, b, eval_start_ms=0, eval_end_ms=end),
        }
        views = {label: runner.prior.previous.charge_result(value, 'TEST', d.LANE, label,
                                                           p, COSTS, rows) for label, value in raw.items()}
        views['M'] = runner.replay({'TEST': rows}, {'TEST': b}, COSTS, p, 0, end)
        stages = {label: m.build_stage(v['trades'], v['open_observations'], v['events'],
                                       {'TEST': rows}, COSTS, p, ['TEST'], 0, end) for label, v in views.items()}
        comparisons = {}
        for base in ('P', 'D', 'N'):
            before, after = views[base], views['M']
            comparisons[base + '_to_M'] = m.compare(stages[base], stages['M'],
                before['trades'], before['open_observations'], after['trades'], after['open_observations'],
                {'TEST': rows}, COSTS, 0, end, role=base + ('_PRIMARY' if base == 'N' else '_CONTEXT'))
        context = dict(comparisons)
        for base, child in (('P', 'D'), ('P', 'N'), ('D', 'N')):
            before, after = views[base], views[child]
            context[base + '_to_' + child] = m.previous.compare(stages[base], stages[child],
                before['trades'], before['open_observations'], after['trades'], after['open_observations'],
                {'TEST': rows}, COSTS, 0, end)
        table = m.reservation_table(*(stages[k] for k in ('P', 'D', 'N', 'M')), context)
        questions = m.summarize_cumulative(*(stages[k] for k in ('P', 'D', 'N', 'M')), 'SYNTHETIC')
        decision = m.candidate_decision({'DEV2025': comparisons, 'SEEN2026': deepcopy(comparisons)})
        report = runner.report({'results': {'SYNTHETIC': {'table': table, 'questions': questions,
            'common_D_regression': {'status': 'SYNTHETIC_ONLY'},
            'funnel_by_symbol': views['M']['admission'], 'comparisons': comparisons}}, 'decision': decision}).decode()
        self.assertIn('| SYNTHETIC / closed_net_bps |', report)
        self.assertIn('winner_amount_retention_vs_N_lower', report)
        self.assertIn('incremental_decision', report)
        self.assertEqual(stages['M']['metrics']['base_cost']['completed_T'], 2)
        self.assertEqual(stages['M']['metrics']['open_observations']['T'], 1)
        self.assertEqual(len(views['M']['reference_opportunities']), 4)
        self.assertEqual(stages['M']['metrics']['closed_cost_totals_bps']['cost_bps'],
                         sum(t['cost_bps'] for t in views['M']['trades']))
        self.assertFalse(decision['formal_pass'])

    def test_compare_reuses_old_attribution_uncertainty_and_same_calendar_windows(self):
        closed, opened, rows = fixture()
        s = stage(closed, opened, rows)
        args = (s, s, closed, opened, closed, opened, rows, COSTS, 0, 3 * m.previous.previous.DAY)
        saved = deepcopy(args)
        old, new = m.previous.compare(*args), m.compare(*args)
        for key in ('attribution', 'uncertainty', 'same_calendar_windows', 'net_decomposition'):
            self.assertEqual(old[key], new[key])
        self.assertEqual(new['decision']['incremental_decision'], 'UNCHANGED')
        self.assertEqual(new['attribution']['counts']['OO'], 1)
        self.assertFalse(new['reference_reservations_are_model_trades'])
        self.assertEqual(args, saved)

    def test_four_way_table_keeps_all_old_fields_and_each_named_retention(self):
        closed, opened, rows = fixture()
        s = stage(closed, opened, rows)
        compared = m.compare(s, s, closed, opened, closed, opened, rows, COSTS, 0, 3 * m.previous.previous.DAY)
        comparisons = {key: compared for key in ('P_to_D', 'P_to_N', 'D_to_N', 'P_to_M', 'D_to_M', 'N_to_M')}
        table = m.reservation_table(s, s, s, s, comparisons)
        index = {row['metric']: row for row in table}
        self.assertTrue(set(m.previous.stage_values(s)) <= set(index))
        for kind in ('winner', 'large_winner'):
            for base in ('P', 'D', 'N'):
                name = kind + '_amount_retention_vs_' + base + '_lower'
                self.assertEqual(index[name]['M'], 1)
        self.assertIsNone(index['winner_amount_retention_vs_N_lower']['P'])
        for row in table:
            for base in ('N', 'D', 'P'):
                if row[base] is not None and row['M'] is not None:
                    self.assertEqual(row['M_minus_' + base], 0)

    def test_gain_summary_is_unclipped_and_keeps_terminal_deficits(self):
        p, d, _, _ = decision_inputs()
        n, child = deepcopy(d), deepcopy(d)
        # Synthetic arithmetic-only stage values: P=100, D=150, N=170, M=190.
        n['metrics']['base_cost']['net_bps'] = 170
        child['metrics']['base_cost']['net_bps'] = 190
        child['metrics']['terminal_totals_bps']['cost2x_net_bps'] = -40
        result = m.summarize_cumulative(p, d, n, child, 'SYNTHETIC')
        self.assertEqual(result['N_increment_over_D_retained_fraction'], 2)
        self.assertAlmostEqual(result['N_cumulative_increment_over_P_retained_fraction'], 90 / 70)
        self.assertEqual(result['M_remaining_hypothetical_terminal_cost2x_deficit_bps'], 40)
        self.assertFalse(result['future_guarantee_or_execution_feature'])
        d['metrics']['base_cost']['net_bps'] = 180
        self.assertIsNone(m.summarize_cumulative(p, d, n, child, 'SYNTHETIC')['N_increment_over_D_retained_fraction'])

    def test_table_and_summary_reject_mismatched_calendar(self):
        p, n, _, _ = decision_inputs()
        n['comparison_calendar_ms'][0] += 1
        with self.assertRaisesRegex(ValueError, 'CALENDAR_MISMATCH'):
            m.reservation_table(p, p, p, n)
        with self.assertRaisesRegex(ValueError, 'CALENDAR_MISMATCH'):
            m.summarize_cumulative(p, p, p, n, 'SYNTHETIC')


if __name__ == '__main__':
    unittest.main()
