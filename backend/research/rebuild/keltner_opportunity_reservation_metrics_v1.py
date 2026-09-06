"""Pure accounting for the one causal D opportunity-reservation repair.

P, D and N are immutable references. M-N measures the new repair; M-P and M-D
show accumulated economics. This module neither reads prices nor runs a trading
rule. Outcome attribution is descriptive and cannot become an execution input.
"""
from copy import deepcopy
import math

from backend.research.rebuild import keltner_cumulative_entry_metrics_v1 as previous

shared = previous.shared
bridge = previous.bridge
build_stage = previous.build_stage
EPS = 1e-7  # PR1196/1197 comparison error, not a new economic threshold.
GOAL = {
    **deepcopy(previous.GOAL),
    'inherited_N_comparison_definition': previous.GOAL['both_comparisons'],
    'both_comparisons': 'M versus N is the repair comparison; M versus P and D preserve cumulative context',
    'comparison_purpose': 'M_MINUS_N_REPAIR_PRIMARY; M_MINUS_D_AND_P_CUMULATIVE_CONTEXT',
    'reservation_comparison_type': 'ENTRY_FILTER; CAUSAL_D_OPPORTUNITY_RESERVATION',
    'comparison_error_bps': EPS,
    'repair_2025': 'closed net, closed cost2 and hypothetical terminal net increase; '
                   'terminal cost2 does not decrease; grouped loss-run and marked DD do not worsen; '
                   'inherited large-winner retention floor is met',
    'preservation_2026': 'closed net/cost2 and hypothetical terminal net/cost2 do not decrease; '
                         'grouped loss-run and marked DD do not worsen; '
                         'inherited large-winner retention floor is met; equality is preserved',
    'unchanged_period_cancels_other_period_improvement': False,
    'partial_workcopy_is_absolute_economic_PASS': False,
    'automatic_research_or_operating_baseline_promotion': False,
}


def stage_values(stage):
    """Keep all prior fields, including open marks and exact calendar units."""
    result = previous.stage_values(stage)
    m = stage['metrics']
    result.update({
        'closed_cost2x_expectancy_bps_per_trade': m['cost2x']['expectancy_bps_per_trade'],
        'open_gross_mark_bps_hypothetical': m['terminal_totals_bps']['gross_bps'] - m['base_cost']['gross_bps'],
        'open_cost2x_net_mark_bps_hypothetical': m['terminal_totals_bps']['cost2x_net_bps'] - m['cost2x']['net_bps'],
        'terminal_cost_bps_hypothetical': m['terminal_totals_bps']['cost_bps'],
        'terminal_funding_bps_hypothetical': m['terminal_totals_bps']['funding_bps'],
    })
    return result


def _same_calendar(*stages):
    calendars = [stage['comparison_calendar_ms'] for stage in stages]
    if any(value != calendars[0] for value in calendars[1:]):
        raise ValueError('RESERVATION_COMPARISON_CALENDAR_MISMATCH')


def _numeric_equal(a, b):
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=0, abs_tol=EPS)


def study_decision(base_stage, new_stage, attribution, uncertainty, *, role='N_PRIMARY'):
    """Absolute economics, repair observation and evidence remain separate.

The legacy verdict is preserved even when an unchanged negative period rejects.
That rejection is never used to erase a different period's measured repair.
"""
    if role not in ('N_PRIMARY', 'D_CONTEXT', 'P_CONTEXT'):
        raise ValueError('UNSUPPORTED_RESERVATION_COMPARISON_ROLE')
    _same_calendar(base_stage, new_stage)
    legacy = previous.study_decision(base_stage, new_stage, attribution, uncertainty)
    p, m = stage_values(base_stage), stage_values(new_stage)
    delta = {key: m[key] - p[key] if m[key] is not None and p[key] is not None else None for key in p}
    enough = (m['closed_T'] >= GOAL['minimum_closed_T'] and
              all(m[key] is not None for key in ('net_expectancy_bps_per_closed_trade', 'PF', 'realized_payoff')))
    absolute = ('INSUFFICIENT' if not enough else 'CLOSED_ABSOLUTE_CHECKS_MET'
                if all(legacy['absolute_economic_checks'].values()) else 'REJECT')
    retention = attribution['large_winner']['amount_retention_lower']
    economic_keys = ('closed_net_bps', 'closed_cost2x_net_bps',
                     'terminal_net_bps_hypothetical', 'terminal_cost2x_net_bps_hypothetical')
    economic = {key + '_not_worse': delta[key] >= -EPS for key in economic_keys}
    risk = {
        'grouped_loss_run_not_worse': delta['grouped_max_loss_trade_sum_bps'] <= EPS,
        'marked_DD_not_worse': delta['marked_DD_trade_sum_bps'] <= EPS,
        'large_winner_amount_preserved': retention is not None and
                                        retention >= GOAL['large_winner_capped_retention_min'],
    }
    recovery = {
        'closed_net_increased': delta['closed_net_bps'] > EPS,
        'closed_cost2x_net_increased': delta['closed_cost2x_net_bps'] > EPS,
        'terminal_net_increased': delta['terminal_net_bps_hypothetical'] > EPS,
        'terminal_cost2x_not_worse': delta['terminal_cost2x_net_bps_hypothetical'] >= -EPS,
        **risk,
    }
    preservation = {**economic, **risk}
    daily_p, daily_m = base_stage['daily'], new_stage['daily']
    if [r['mark_ts'] for r in daily_p] != [r['mark_ts'] for r in daily_m]:
        raise ValueError('RESERVATION_DAILY_CALENDAR_MISMATCH')
    unchanged = (all(_numeric_equal(p[key], m[key]) for key in p) and
                 all(_numeric_equal(a['value'], b['value']) for a, b in zip(daily_p, daily_m)))
    improving_core = (any(delta[key] > EPS for key in economic_keys) or
                      delta['grouped_max_loss_trade_sum_bps'] < -EPS or delta['marked_DD_trade_sum_bps'] < -EPS)
    if unchanged:
        incremental = 'UNCHANGED'
    elif not enough:
        incremental = 'INSUFFICIENT'
    elif all(preservation.values()) and improving_core:
        incremental = 'IMPROVED_OBSERVATION'
    elif improving_core:
        incremental = 'TRADEOFF'
    else:
        incremental = 'DETERIORATED_OR_NO_CORE_IMPROVEMENT'
    return {
        **legacy,
        'comparison_role': role,
        'legacy_study_decision': legacy['decision'],
        'absolute_economic_decision': absolute,
        'incremental_decision': incremental,
        'incremental_values': delta,
        'same_economic_values_and_daily_path_within_existing_error': unchanged,
        'recovery_2025_checks': recovery,
        'recovery_2025_checks_met': enough and all(recovery.values()),
        'preservation_2026_checks': preservation,
        'preservation_2026_checks_met': enough and all(preservation.values()),
        'absolute_economic_PASS_claimed': False,
        'partial_workcopy_is_formal_adoption': False,
        'legacy_verdicts_rewritten': False,
        'reference_clock_has_economic_position_or_cost': False,
        'uncertainty_or_open_blockers_are_waived': False,
    }


def compare(base_stage, new_stage, base_closed, base_open, new_closed, new_open,
            rows, costs, start, end, *, role='N_PRIMARY'):
    """Reuse prior attribution, same-calendar windows and fixed bootstrap."""
    result = previous.compare(base_stage, new_stage, base_closed, base_open,
                              new_closed, new_open, rows, costs, start, end)
    result['decision'] = study_decision(base_stage, new_stage, result['attribution'],
                                        result['uncertainty'], role=role)
    result.update(comparison_role=role, occupancy_mechanism='CAUSAL_D_OPPORTUNITY_RESERVATION',
                  legacy_numerical_goals_unchanged=True,
                  reference_reservations_are_model_trades=False)
    return result


def reservation_table(p, d, n, m, comparisons=None):
    """All metrics P/D/N/M; retention is capped against each named reference.

comparisons keys are P_to_D, P_to_N, D_to_N, P_to_M, D_to_M, N_to_M.
Absent older comparator pairs stay unavailable, rather than being manufactured.
"""
    _same_calendar(p, d, n, m)
    values = {name: stage_values(s) for name, s in (('P', p), ('D', d), ('N', n), ('M', m))}
    comparisons = comparisons or {}
    for base in ('P', 'D', 'N'):
        direct = comparisons.get(base + '_to_M')
        if direct is None:
            continue
        for kind in ('winner', 'large_winner'):
            field = kind + '_amount_retention_vs_' + base + '_lower'
            for name in values:
                cmp = comparisons.get(base + '_to_' + name)
                values[name][field] = (1.0 if direct['attribution'][kind]['parent_positive_bps'] else None) if name == base else (
                    cmp['attribution'][kind]['amount_retention_lower'] if cmp else None)
    difference = lambda a, b: a - b if a is not None and b is not None else None
    return [{'metric': key, **{label: fields[key] for label, fields in values.items()},
             **{'M_minus_' + base: difference(values['M'][key], values[base][key]) for base in ('N', 'D', 'P')}}
            for key in values['P']]


# Alias keeps the runner's prior table naming convenient without altering it.
cumulative_table = reservation_table


def summarize_cumulative(p, d, n, m, period):
    """Unclipped observed gain retention; negative periods cannot be sum-rescued."""
    _same_calendar(p, d, n, m)
    values = {name: stage_values(s) for name, s in (('P', p), ('D', d), ('N', n), ('M', m))}
    net = {name: fields['closed_net_bps'] for name, fields in values.items()}
    fraction = lambda numerator, denominator: numerator / denominator if denominator > EPS else None
    return {
        'period': period, 'independent': False,
        **{a + '_minus_' + b + '_closed_net_bps': net[a] - net[b]
           for a, b in (('D', 'P'), ('N', 'D'), ('N', 'P'), ('M', 'N'), ('M', 'D'), ('M', 'P'))},
        'N_increment_over_D_retained_fraction': fraction(net['M'] - net['D'], net['N'] - net['D']),
        'N_cumulative_increment_over_P_retained_fraction': fraction(net['M'] - net['P'], net['N'] - net['P']),
        'D_increment_over_P_retained_fraction': fraction(net['M'] - net['P'], net['D'] - net['P']),
        'increment_fraction_basis': 'UNCLIPPED_OBSERVED_FULL_REPLAY_DELTA; NOT_RETROSPECTIVE_TRADE_SELECTION',
        'M_remaining_closed_net_deficit_bps': max(0, -net['M']),
        'M_remaining_closed_cost2x_deficit_bps': max(0, -values['M']['closed_cost2x_net_bps']),
        'M_remaining_hypothetical_terminal_net_deficit_bps': max(0, -values['M']['terminal_net_bps_hypothetical']),
        'M_remaining_hypothetical_terminal_cost2x_deficit_bps': max(0, -values['M']['terminal_cost2x_net_bps_hypothetical']),
        'prior_N_verdict_changed': False, 'formal_pass': False, 'operating_adoption': False,
        'future_guarantee_or_execution_feature': False,
    }


def candidate_decision(period_comparisons):
    """Retain the repair independently from unresolved absolute 2026 losses."""
    if set(period_comparisons) != {'DEV2025', 'SEEN2026'}:
        raise ValueError('RESERVATION_REQUIRES_TWO_FROZEN_PERIODS')
    required = {'N_to_M', 'D_to_M', 'P_to_M'}
    if any(not required <= set(comparisons) for comparisons in period_comparisons.values()):
        raise ValueError('RESERVATION_REQUIRES_P_D_N_COMPARISONS')
    decisions = {period: {key: item['decision'] for key, item in comparisons.items() if key in required}
                 for period, comparisons in period_comparisons.items()}
    for comparisons in decisions.values():
        for base in ('P', 'D', 'N'):
            expected = base + ('_PRIMARY' if base == 'N' else '_CONTEXT')
            if comparisons[base + '_to_M']['comparison_role'] != expected:
                raise ValueError('RESERVATION_COMPARATOR_ROLE_MISMATCH')
        if len({item['absolute_economic_decision'] for item in comparisons.values()}) != 1:
            raise ValueError('M_ABSOLUTE_DECISION_DEPENDS_ON_COMPARATOR')
    recovery = decisions['DEV2025']['N_to_M']['recovery_2025_checks_met']
    preservation = decisions['SEEN2026']['N_to_M']['preservation_2026_checks_met']
    absolute = {period: comparisons['N_to_M']['absolute_economic_decision'] for period, comparisons in decisions.items()}
    combined = ('INSUFFICIENT' if 'INSUFFICIENT' in absolute.values() else
                'REJECT' if 'REJECT' in absolute.values() else 'CLOSED_ABSOLUTE_CHECKS_MET')
    partial = recovery and preservation
    return {
        'decision': combined,
        'absolute_economic_decision_by_period': absolute,
        'incremental_decision_by_period': {period: comparisons['N_to_M']['incremental_decision']
                                           for period, comparisons in decisions.items()},
        'legacy_study_decision_by_period_and_reference': {period: {key: item['legacy_study_decision']
                                                                     for key, item in comparisons.items()}
                                                          for period, comparisons in decisions.items()},
        'recovery_2025_checks_met': recovery, 'preservation_2026_checks_met': preservation,
        'partial_workcopy_retained': partial,
        'workcopy_decision': 'PARTIAL_DEVELOPMENT_WORKCOPY_RETAINED' if partial else 'REPAIR_NOT_SUPPORTED_N_PRESERVED',
        'unchanged_2026_erases_2025_increment': False,
        'preserve_partial_workbench_evidence': True,
        'research_child_reference_supported': False,
        'automatic_research_baseline_replacement': False,
        'prior_P_D_N_verdicts_changed': False, 'formal_pass': False, 'independent': False,
        'operating_adoption': False, 'code_PASS_is_economic_PASS': False,
        'no_automatic_additional_candidate': True,
    }
