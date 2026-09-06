"""Pure accounting for one cumulative Keltner ENTRY_FILTER study.

The original parent P and unadopted exit workbench D remain sealed. N keeps D's
exits and changes entry eligibility only. This module loads no price files and
never uses the retrospective outcome groups below as execution features.
"""
from copy import deepcopy

from backend.research.rebuild import parallel_exit_metrics_v1 as previous

shared = previous.shared
bridge = previous.bridge
build_stage = previous.build_stage
GOAL = {
    **deepcopy(previous.GOAL),
    'both_comparisons': 'full N versus P and full N versus unadopted D; common eligible D origins are descriptive',
    'comparison_type': 'ENTRY_FILTER',
    'prior_D_status_preserved': True,
    'partial_workbench_is_formal_adoption': False,
}


def study_decision(base_stage, new_stage, attribution, uncertainty):
    """Retain PR1196 numerical criteria without claiming an exit-only study."""
    p, c = base_stage['metrics'], new_stage['metrics']
    base = c['base_cost']
    defined = all(base[key] is not None for key in ('expectancy_bps_per_trade', 'PF', 'realized_payoff'))
    absolute = {
        'positive_closed_net': base['net_bps'] > 0,
        'positive_expectancy': base['expectancy_bps_per_trade'] is not None and base['expectancy_bps_per_trade'] > 0,
        'PF_above_one': base['PF'] is not None and base['PF'] > 1,
        'payoff_at_least_one': base['realized_payoff'] is not None and base['realized_payoff'] >= 1,
        'positive_closed_cost2x_net': c['cost2x']['net_bps'] > 0,
    }
    increments = {
        'closed_net_increased': attribution['closed_net_delta_bps'] > 1e-7,
        'terminal_net_increased': attribution['marked_delta_bps_not_realized'] > 1e-7,
    }
    loss = lambda stage: stage['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps']
    retention = attribution['large_winner']['amount_retention_lower']
    lower = uncertainty['child_minus_parent_95pct_interval_bps_per_day'][0]
    risk = {
        'grouped_loss_run_not_worse': loss(new_stage) <= loss(base_stage) + 1e-7,
        'marked_DD_not_worse': new_stage['marked_diagnostics']['marked_DD_trade_sum_bps'] <=
                              base_stage['marked_diagnostics']['marked_DD_trade_sum_bps'] + 1e-7,
        'large_winner_amount_preserved': retention is not None and retention >= GOAL['large_winner_capped_retention_min'],
        'positive_daily_delta95_lower': lower is not None and lower > 0,
        'no_unresolved_positions': p['open_observations']['T'] == c['open_observations']['T'] == 0,
    }
    if base['completed_T'] < GOAL['minimum_closed_T'] or not defined:
        decision = 'INSUFFICIENT'
    elif not all(absolute.values()) or not all(increments.values()):
        decision = 'REJECT'
    elif not all(risk.values()):
        decision = 'TRADEOFF'
    else:
        decision = 'IMPROVED'
    # A partial observation is retained even if the absolute economics reject.
    # It changes neither D's old verdict nor the operating/research baseline.
    partial = {key: value for key, value in {**increments, **risk}.items()
               if key not in ('positive_daily_delta95_lower', 'no_unresolved_positions')}
    return {
        'decision': decision, 'comparison_type': 'ENTRY_FILTER',
        'absolute_economic_checks': absolute, 'increment_checks': increments,
        'risk_and_evidence_checks': risk,
        'failed_checks': [key for group in (absolute, increments, risk) for key, value in group.items() if not value],
        'partial_workbench_observations': partial,
        'partial_workbench_checks_met': all(partial.values()),
        'partial_workbench_is_economic_PASS': False,
        'loss_reduction': base['net_bps'] < 0 and attribution['closed_net_delta_bps'] > 1e-7,
        'closed_net_delta_bps': attribution['closed_net_delta_bps'],
        'terminal_net_delta_bps': attribution['marked_delta_bps_not_realized'],
        'grouped_loss_run_delta_bps_descriptive': loss(new_stage) - loss(base_stage),
        'exposure_delta_symbol_days': c['total_exposure_symbol_days'] - p['total_exposure_symbol_days'],
        'source_overlap_is_economic_gate': False, 'formal_pass': False,
        'operating_adoption': False, 'independent': False,
        'prior_D_verdict_changed': False, 'code_PASS_is_economic_PASS': False,
        'open_censoring_blocks_strong_verdict': not risk['no_unresolved_positions'],
    }


def compare(base_stage, new_stage, base_closed, base_open, new_closed, new_open,
            rows, costs, start, end):
    """Symmetric origin comparison with native full replay and unchanged costs."""
    if any(stage['comparison_calendar_ms'] != [start, end] for stage in (base_stage, new_stage)):
        raise ValueError('ENTRY_COMPARISON_CALENDAR_MISMATCH')
    attribution = bridge.symmetric_attribution(base_closed, base_open, new_closed, new_open)
    attribution['comparison_type'] = 'ENTRY_FILTER'
    uncertainty = shared.paired_daily_uncertainty(base_stage['daily'], new_stage['daily'],
        block_days=GOAL['block_days'], resamples=GOAL['resamples'], seed=GOAL['seed'])
    uncertainty.update(independent=False, partial_native_edge_buckets_included=True,
                       daily_unit='UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION')
    return {
        'comparison_type': 'ENTRY_FILTER', 'attribution': attribution, 'uncertainty': uncertainty,
        'net_decomposition': previous.net_decomposition(base_closed, base_open, new_closed, new_open, attribution),
        'decision': study_decision(base_stage, new_stage, attribution, uncertainty),
        'same_calendar_windows': previous.same_calendar_windows(base_stage, new_stage,
            base_closed, base_open, new_closed, new_open, rows, costs, start, end),
        'same_entry_exit_only_comparison_claimed': False,
        'excluded_opportunities_are_zero_profit_wins': False,
    }


def stage_values(stage):
    """Report fields with explicit closed/open and trade-sum units."""
    m = stage['metrics']
    b = m['base_cost']
    return {
        'closed_T': b['completed_T'], 'open_T': m['open_observations']['T'],
        'entries_T': m['entries_including_censored_T'],
        'win_rate': b['win_rate'], 'PF': b['PF'],
        'mean_win_bps': b['average_win_bps'], 'mean_loss_bps': b['average_loss_bps'],
        'realized_payoff': b['realized_payoff'],
        'net_expectancy_bps_per_closed_trade': b['expectancy_bps_per_trade'],
        'closed_gross_bps': b['gross_bps'], 'closed_net_bps': b['net_bps'],
        'closed_cost2x_net_bps': m['cost2x']['net_bps'],
        'closed_cost_bps': m['closed_cost_totals_bps']['cost_bps'],
        'closed_fee_bps': m['closed_cost_totals_bps']['fee_bps'],
        'closed_funding_bps': m['closed_cost_totals_bps']['funding_bps'],
        'terminal_net_bps_hypothetical': m['closed_plus_hypothetical_terminal_mark_bps'],
        'terminal_cost2x_net_bps_hypothetical': m['terminal_totals_bps']['cost2x_net_bps'],
        'open_net_mark_bps_hypothetical': m['terminal_totals_bps']['net_bps'] - b['net_bps'],
        'marked_DD_trade_sum_bps': stage['marked_diagnostics']['marked_DD_trade_sum_bps'],
        'grouped_max_loss_trade_sum_bps': stage['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'],
        'exposure_symbol_days': m['total_exposure_symbol_days'],
        'max_simultaneous_symbols': m['exposure']['max_simultaneous_symbols'],
        'entries_per_30_days': m['frequency']['entries_per_30_calendar_days'],
        'max_completed_recovery_days': stage['marked_diagnostics']['max_completed_recovery_days'],
        'open_underwater_days': stage['marked_diagnostics']['open_underwater_days'],
    }


def cumulative_table(p, d, n, p_to_d=None, p_to_n=None, d_to_n=None):
    """P/D/N rows use one calendar; retention uses the named completed base."""
    if not p['comparison_calendar_ms'] == d['comparison_calendar_ms'] == n['comparison_calendar_ms']:
        raise ValueError('CUMULATIVE_TABLE_CALENDAR_MISMATCH')
    values = {label: stage_values(stage) for label, stage in (('P', p), ('D', d), ('N', n))}
    if p_to_d is not None and p_to_n is not None:
        for kind in ('winner', 'large_winner'):
            field = kind + '_amount_retention_vs_P_lower'
            total = p_to_d['attribution'][kind]['parent_positive_bps']
            values['P'][field] = 1.0 if total else None
            values['D'][field] = p_to_d['attribution'][kind]['amount_retention_lower']
            values['N'][field] = p_to_n['attribution'][kind]['amount_retention_lower']
    if d_to_n is not None:
        for kind in ('winner', 'large_winner'):
            field = kind + '_amount_retention_vs_D_lower'
            values['P'][field] = None
            total = d_to_n['attribution'][kind]['parent_positive_bps']
            values['D'][field] = 1.0 if total else None
            values['N'][field] = d_to_n['attribution'][kind]['amount_retention_lower']
    delta = lambda a, b: a - b if a is not None and b is not None else None
    return [{
        'metric': key, **{label: values[label][key] for label in values},
        'N_minus_D': delta(values['N'][key], values['D'][key]),
        'N_minus_P': delta(values['N'][key], values['P'][key]),
    } for key in values['P']]


def summarize_cumulative(p, d, n, period):
    """Observed gain retention is arithmetic, with no clipping or extrapolation."""
    if not p['comparison_calendar_ms'] == d['comparison_calendar_ms'] == n['comparison_calendar_ms']:
        raise ValueError('CUMULATIVE_SUMMARY_CALENDAR_MISMATCH')
    pp, dd, nn = [stage['metrics']['base_cost']['net_bps'] for stage in (p, d, n)]
    gain = dd - pp
    return {
        'period': period, 'independent': False,
        'D_minus_P_closed_net_bps': gain, 'N_minus_P_closed_net_bps': nn - pp,
        'N_minus_D_closed_net_bps': nn - dd,
        'D_observed_increment_retained_fraction': (nn - pp) / gain if gain > 1e-7 else None,
        'increment_fraction_basis': 'UNCLIPPED_FULL_REPLAY_CLOSED_NET_INCREMENT_OVER_P; OBSERVED_ONLY',
        'N_remaining_closed_net_deficit_bps': max(0.0, -nn),
        'N_remaining_closed_cost2x_deficit_bps': max(0.0, -n['metrics']['cost2x']['net_bps']),
        'N_remaining_hypothetical_terminal_net_deficit_bps': max(0.0, -n['metrics']['closed_plus_hypothetical_terminal_mark_bps']),
        'future_guarantee_or_execution_feature': False,
        'prior_D_status_changed': False, 'formal_pass': False, 'operating_adoption': False,
    }


def original_entry_effects(parent_closed, parent_open, prior_fixed_closed, prior_fixed_open,
                          new_closed, new_open):
    """Separate D fixed-entry harm from N filtering and full occupancy effects.

    Parent outcome labels are reporting truth only. Missing N entries contribute
    no capital/PnL to totals; they are not zero-profit trades or added victories.
    Positions absent from P are reported separately and never a fixed bonus.
    """
    p = bridge._index(parent_closed, parent_open)
    d = bridge._index(prior_fixed_closed, prior_fixed_open)
    n = bridge._index(new_closed, new_open)
    if p.keys() != d.keys():
        raise ValueError('PRIOR_FIXED_MUST_PRESERVE_ALL_PARENT_ENTRY_ORIGINS')
    if any((p[k][1]['entry_ts'], p[k][1]['entry_price']) !=
           (d[k][1]['entry_ts'], d[k][1]['entry_price']) for k in p):
        raise ValueError('PRIOR_FIXED_ENTRY_FILL_CHANGED')
    kept_c = [t for t in new_closed if bridge.ORIGIN(t) in p]
    kept_o = [t for t in new_open if bridge.ORIGIN(t) in p]
    baseline_effect = bridge.symmetric_attribution(parent_closed, parent_open, prior_fixed_closed, prior_fixed_open)
    changed = bridge.symmetric_attribution(prior_fixed_closed, prior_fixed_open, kept_c, kept_o)
    changed['comparison_type'] = 'ENTRY_FILTER_ON_ORIGINAL_P_ORIGINS'
    categories = {name: [] for name in ('D_helpful_closed', 'D_harmful_closed', 'D_unchanged_closed', 'censor_transition')}
    rows = []
    for key in sorted(p):
        ps, pt = p[key]
        ds, dt = d[key]
        if ps == ds == 'C':
            delta = dt['net_bps'] - pt['net_bps']
            category = ('D_helpful_closed' if delta > 1e-7 else
                        'D_harmful_closed' if delta < -1e-7 else 'D_unchanged_closed')
        else:
            category = 'censor_transition'
        categories[category].append(key)
        item = n.get(key)
        values = {label: bridge._values(value, closed_only=True)
                  for label, value in (('P', p[key]), ('D_fixed', d[key]), ('N', item))}
        rows.append({
            'origin_key': key, 'symbol': pt['symbol'], 'category': category,
            'P_status': ps, 'D_fixed_status': ds, 'N_status': item[0] if item else 'ABSENT',
            'N_entry_present': item is not None,
            'closed_values': values,
            'D_fixed_minus_P_closed_net_bps': values['D_fixed']['net_bps'] - values['P']['net_bps'],
            'N_minus_D_fixed_closed_net_bps': values['N']['net_bps'] - values['D_fixed']['net_bps'],
            'N_minus_P_closed_net_bps': values['N']['net_bps'] - values['P']['net_bps'],
        })
    totals = {}
    for category, keys in categories.items():
        group_rows = [row for row in rows if row['origin_key'] in keys]
        totals[category] = {
            'original_P_T': len(keys),
            'N_absent_T': sum(row['N_status'] == 'ABSENT' for row in group_rows),
            'N_closed_T': sum(row['N_status'] == 'C' for row in group_rows),
            'N_open_T': sum(row['N_status'] == 'O' for row in group_rows),
            **{key: sum(row[key] for row in group_rows) for key in
               ('D_fixed_minus_P_closed_net_bps', 'N_minus_D_fixed_closed_net_bps', 'N_minus_P_closed_net_bps')},
        }
    new_items = [n[key] for key in sorted(n.keys() - p.keys())]
    new_totals = bridge._totals(new_items, closed_only=True)
    n_total = bridge._totals(list(n.values()), closed_only=True)
    p_total = bridge._totals(list(p.values()), closed_only=True)
    fixed_effect = baseline_effect['closed_net_delta_bps']
    original_effect = changed['closed_net_delta_bps']
    total_effect = n_total['net_bps'] - p_total['net_bps']
    bridge._same(fixed_effect + original_effect + new_totals['net_bps'], total_effect,
                 'P_FIXED_D_FILTERED_N_PLUS_NEW_FULL_REPLAY_BRIDGE')
    return {
        'basis': 'ORIGINAL_P_ORIGINS; D_FIXED_EXIT_EFFECT; N_FULL_REPLAY_REMAINDER_AND_NEW_OPPORTUNITIES',
        'prior_fixed_D_minus_P_closed_net_bps': fixed_effect,
        'N_original_origins_minus_prior_fixed_closed_net_bps': original_effect,
        'N_new_not_P_closed_totals_bps': new_totals,
        'N_new_not_P_closed_T': sum(status == 'C' for status, _ in new_items),
        'N_new_not_P_open_T': sum(status == 'O' for status, _ in new_items),
        'N_minus_P_full_closed_net_bps': total_effect,
        'original_origin_change_attribution': changed,
        'original_origin_net_decomposition': previous.net_decomposition(
            prior_fixed_closed, prior_fixed_open, kept_c, kept_o, changed),
        'outcome_categories': totals, 'per_original_origin': rows,
        'fixed_harm_retrospective_labels_are_execution_features': False,
        'absent_N_entry_is_zero_profit_trade_or_win': False,
        'new_opportunity_net_is_fixed_bonus': False, 'parity': 'PASS',
    }


def candidate_decision(period_comparisons):
    """Keep period/comparator verdicts separate; no old verdict is rewritten."""
    decisions = {period: {name: comparison['decision']['decision'] for name, comparison in comparisons.items()}
                 for period, comparisons in period_comparisons.items()}
    flattened = [value for comparisons in decisions.values() for value in comparisons.values()]
    if not flattened:
        raise ValueError('MISSING_CUMULATIVE_COMPARISONS')
    result = ('INSUFFICIENT' if 'INSUFFICIENT' in flattened else 'REJECT' if 'REJECT' in flattened
              else 'TRADEOFF' if 'TRADEOFF' in flattened else 'IMPROVED')
    return {
        'decision': result, 'comparison_type': 'ENTRY_FILTER', 'by_period_and_base': decisions,
        'research_child_reference_supported': result == 'IMPROVED',
        'preserve_partial_workbench_evidence': True,
        'prior_P_D_verdicts_changed': False, 'formal_pass': False, 'independent': False,
        'operating_adoption': False, 'code_PASS_is_economic_PASS': False,
    }
