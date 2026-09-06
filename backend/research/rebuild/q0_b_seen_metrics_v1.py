"""New-period descriptive diagnostics around the unchanged Q0/B accounting.

All outcome-defined cohorts and windows are report labels only. They are built
after entry weights and never flow back into a signal, weight, or price loader.
"""
from collections import defaultdict
from copy import deepcopy

from backend.research.rebuild import q0_risk_entry_metrics_v1 as accounting
from backend.research.rebuild import q0_risk_entry_v1 as original

DAY = accounting.DAY
ORIGIN = accounting.ORIGIN
NAMES = ('A_Q0', 'B_RISK', 'C_FIXED')
# Inherited from break_channel_metrics_v1.decide(minimum_closed_T=6).
MINIMUM_CLOSED_T = 6
EVIDENCE = {'evidence_type': 'SEEN_DATA_REPLICATION', 'independent': False,
            'formal_credit': 0, 'operating_adoption': False}


def _cohorts(trades):
    """Consecutive same-sign simultaneous-close groups; zero breaks a loss run."""
    result = []
    for stamp, rows in sorted(accounting.shared.existing_risk.grouped(trades).items()):
        net = sum(t['net_bps'] for t in rows)
        sign = -1 if net < 0 else 1 if net > 0 else 0
        keys = sorted(ORIGIN(t) for t in rows)
        if not result or result[-1]['sign'] != sign or sign == 0:
            result.append({'cohort_id': len(result), 'sign': sign, 'start_exit_ms': stamp,
                           'end_exit_ms': stamp, 'exit_groups': 0, 'origin_keys': []})
        result[-1]['end_exit_ms'] = stamp
        result[-1]['exit_groups'] += 1
        result[-1]['origin_keys'].extend(keys)
    return result


def cohort_diagnostics(trades, allocations):
    """Tabulate every original cohort and each stage's own worst loss cohort."""
    index = {ORIGIN(t): t for t in trades}
    if len(index) != len(trades):
        raise RuntimeError('DUPLICATE_CLOSED_ORIGIN')

    def compare(cohort):
        keys = cohort['origin_keys']
        stages = {name: {field: sum(w[k] * index[k][field] for k in keys)
                         for field in accounting.VALUE_FIELDS}
                  for name, w in allocations.items()}
        return {**cohort, 'T': len(keys), 'stages': stages,
                'B_minus_A_net_bps': stages['B_RISK']['net_bps'] - stages['A_Q0']['net_bps'],
                'B_minus_C_net_bps': stages['B_RISK']['net_bps'] - stages['C_FIXED']['net_bps']}

    cohorts = [compare(c) for c in _cohorts(trades)]
    if sorted(k for c in cohorts for k in c['origin_keys']) != sorted(index):
        raise RuntimeError('ORIGINAL_COHORT_COVERAGE')
    native = {}
    for name, allocation in allocations.items():
        weighted, _ = accounting.weighted_copies(trades, [], {k: allocation[k] for k in index})
        runs = [c for c in _cohorts(weighted) if c['sign'] < 0]
        native[name] = [compare(c) for c in runs]
        for c in native[name]:
            c['defining_stage'] = name
        measured_max = max((-c['stages'][name]['net_bps'] for c in native[name]), default=0.)
        reference, _ = accounting.shared.existing_risk.streaks(
            accounting.shared.existing_risk.grouped(weighted))
        accounting._same(measured_max, reference['max_loss_trade_sum_bps'], 'NATIVE_LOSS_RUN_PARITY')
    worst = {name: (max(runs, key=lambda c: -c['stages'][name]['net_bps']) if runs else None)
             for name, runs in native.items()}
    return {'original_A_cohorts': cohorts, 'stage_native_loss_runs': native,
            'stage_worst_loss_cohorts': worst,
            'same_worst_origin_set_all_stages': len({tuple(c['origin_keys']) if c else () for c in worst.values()}) == 1,
            'basis': 'ALL_ORIGINAL_SIMULTANEOUS_EXIT_SIGN_COHORTS; SAME_ORIGINS_AND_CLOSE_TIMES',
            'different_maxima_delta_is_causal_attribution': False,
            'labels_are_post_outcome_analysis_only': True, 'closed_cohort_coverage': 'PASS'}


def _max_dd_window(daily, start):
    equity = peak = worst = 0.
    peak_stamp = start
    interval = None
    for row in daily:
        equity += row['value']
        if peak - equity > worst:
            worst = peak - equity
            interval = {'start_ms': peak_stamp, 'end_ms': row['mark_ts']}
        if equity >= peak:
            peak = equity
            peak_stamp = row['mark_ts']
    return interval, worst


def _windows(measured, cohorts, trades, opened, prices, costs, start, end, allocations, weights):
    requested = defaultdict(list)
    for name, stage in measured['stages'].items():
        window, dd = _max_dd_window(stage['daily'], start)
        accounting._same(dd, stage['marked_diagnostics']['marked_DD_trade_sum_bps'], 'MAX_DD_WINDOW_PARITY')
        if window:
            requested[(window['start_ms'], window['end_ms'])].append(name + '_MAX_MARKED_DD')
    for cohort in cohorts['original_A_cohorts']:
        # Include the first exit even when it falls exactly at a UTC boundary.
        left = max(start, ((cohort['start_exit_ms'] - 1) // DAY) * DAY)
        right = min(end, ((cohort['end_exit_ms'] + DAY - 1) // DAY) * DAY)
        if left < right:
            requested[(left, right)].append('A_COHORT_' + str(cohort['cohort_id']))
    result = []
    for (left, right), labels in sorted(requested.items()):
        unit = accounting.bridge.window_contributions(trades, opened, prices, costs, start, end,
                                                       left, right, daily=measured['stages']['A_Q0']['daily'])
        result.append({'labels': labels, 'start_ms': left, 'end_ms': right,
                       'stages': {name: accounting.weighted_window(unit, allocation,
                                  measured['stages'][name]['daily'], weights if name == 'B_RISK' else None)
                                  for name, allocation in allocations.items()},
                       'labels_are_post_outcome_analysis_only': True,
                       'basis': 'IDENTICAL_UTC_DAILY_BOUNDARIES; ALL_POSITION_MARKS; COHORT_CLOSE_SPANS_ROUNDED_OUTWARD',
                       'overlapping_windows_must_not_be_summed': True})
    return result


def _sample_sufficiency(measured):
    base = measured['stages']['B_RISK']['metrics']['base_cost']
    opened = measured['invariants']['open_T']
    minimum_met = base['completed_T'] >= MINIMUM_CLOSED_T
    defined = all(base[key] is not None for key in ('PF', 'realized_payoff', 'expectancy_bps_per_trade'))
    uncertainty = measured['uncertainty']
    dependence = measured.get('dependence', {})
    return {'status': 'INSUFFICIENT_CLOSED_SAMPLE' if not minimum_met or not defined
            else 'UNRESOLVED_TERMINAL_POSITIONS' if opened else 'DESCRIPTIVE_SEEN_SAMPLE_ONLY',
            'inherited_minimum_closed_T': MINIMUM_CLOSED_T,
            'minimum_source': 'break_channel_metrics_v1.decide.minimum_closed_T',
            'completed_T': base['completed_T'], 'minimum_closed_T_met': minimum_met,
            'closed_PF_payoff_and_expectancy_defined': defined,
            'unresolved_open_T': opened, 'terminal_mark_is_hypothetical_not_realized': bool(opened),
            'calendar_days': uncertainty['calendar_days'], 'block_days': uncertainty['block_days'],
            'nominal_calendar_blocks': uncertainty['approximate_calendar_blocks'],
            'nominal_blocks_are_independent_samples': False, 'N_effective': None,
            'maximum_holding_days': dependence.get('max_holding_days'),
            'holding_exceeds_bootstrap_block': dependence.get('max_holding_days', 0) > uncertainty['block_days'],
            'no_new_cluster_count_pass_threshold': True,
            'model_selection_and_data_reuse_corrected': False}


def _decision(measured):
    stages = measured['stages']
    b, c = stages['B_RISK'], stages['C_FIXED']
    loss = lambda stage: stage['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps']
    technical = original.study_decision(
        b['metrics']['terminal_net_amount_bps'], b['metrics']['terminal_cost2x_net_amount_bps'],
        c['metrics']['terminal_net_amount_bps'], b['marked_diagnostics']['marked_DD_trade_sum_bps'],
        c['marked_diagnostics']['marked_DD_trade_sum_bps'], loss(b), loss(c),
        measured['uncertainty']['child_minus_parent_95pct_interval_bps_per_day'])
    labels = {'DEV_PROMISING_NO_CREDIT': 'SEEN_PERIOD_SUPPORT', 'DEV_INCONCLUSIVE': 'SEEN_PERIOD_INCONCLUSIVE',
              'DEV_INCONCLUSIVE_TRADEOFF': 'SEEN_PERIOD_TRADEOFF', 'DEV_REJECT': 'SEEN_PERIOD_VULNERABILITY'}
    adequacy = _sample_sufficiency(measured)
    decision = labels[technical['decision']]
    if decision in ('SEEN_PERIOD_SUPPORT', 'SEEN_PERIOD_INCONCLUSIVE'):
        if adequacy['status'] == 'INSUFFICIENT_CLOSED_SAMPLE':
            decision = 'SEEN_PERIOD_INSUFFICIENT'
        elif adequacy['unresolved_open_T']:
            decision = 'SEEN_PERIOD_INCONCLUSIVE'
    return {**technical, **EVIDENCE, 'decision': decision, 'sample_sufficiency': adequacy,
            'original_technical_decision': technical['decision'],
            'technical_decision_scope': 'UNCHANGED_GOAL_ARITHMETIC_ON_NEW_SEEN_PERIOD_ONLY; ORIGINAL_DEV_STATES_PRESERVED',
            'independent_comparison': 'NOT_RUN', 'independent_comparison_uses': 0,
            'original_26_candidate_trials_unchanged': True, 'new_candidate_trials': 0}


def build(trades, opened, events, rows_by_symbol, costs, policy, symbols, start, end, weights):
    """Reuse all existing price/cost/holding accounting; add report-only cohorts."""
    if end <= start or start % DAY or end % DAY or policy['development_interval_ms'] != [start, end]:
        raise ValueError('INVALID_DAILY_EVALUATION_CALENDAR')
    items = accounting.bridge._index(trades, opened)
    allocation_b = accounting._weights(items, weights)
    if sum(t['hold_ms'] for _, t in items.values()) <= 0:
        monetary = {}
        for name, allocation in (('A_Q0', dict.fromkeys(items, 1.)), ('B_RISK', allocation_b)):
            ts, os = accounting.weighted_copies(trades, opened, allocation)
            monetary[name] = {'closed': accounting.bridge._totals([('C', t) for t in ts]),
                              'terminal': accounting.bridge._totals([('C', t) for t in ts] + [('O', t) for t in os])}
        return {**EVIDENCE, 'decision': {**EVIDENCE, 'decision': 'SEEN_PERIOD_INSUFFICIENT',
                    'reason': 'FIXED_CONTROL_UNDEFINED_ZERO_TOTAL_HOLDING_TIME', 'study_goal_met': False},
                'stages': {}, 'control': {'k': None, 'status': 'UNDEFINED_ZERO_EXPOSURE', 'ex_post_analysis_only': True},
                'unit_metrics': accounting.shared.summarize(trades, opened, events, policy, symbols),
                'unit_ledger': {'closed': deepcopy(trades), 'open': deepcopy(opened)}, 'A_B_monetary_totals': monetary,
                'invariants': {'closed_T': len(trades), 'open_T': len(opened), 'signals_T': len(events)},
                'attribution': {}, 'uncertainty': {'status': 'INSUFFICIENT_ZERO_EXPOSURE'}}
    measured = accounting.build(trades, opened, events, rows_by_symbol, costs, policy, symbols, start, end, weights)
    measured.update(EVIDENCE)
    measured['uncertainty']['limitations'] = measured['uncertainty']['limitations'].replace(
        'REUSED_DEV_AND_SELECTION_NOT_CORRECTED', 'SEEN_DATA_REUSE_AND_SELECTION_NOT_CORRECTED')
    measured['uncertainty'].update(EVIDENCE)
    allocations = {'A_Q0': dict.fromkeys(items, 1.), 'B_RISK': allocation_b,
                   'C_FIXED': dict.fromkeys(items, measured['control']['k'])}
    measured['cohorts'] = cohort_diagnostics(trades, allocations)
    measured['same_calendar_windows'] = _windows(measured, measured['cohorts'], trades, opened,
                                                rows_by_symbol, costs, start, end, allocations, weights)
    winners = sorted((t for t in trades if t['net_bps'] > 0), key=lambda t: (-t['net_bps'], ORIGIN(t)))[:3]
    total = sum(t['net_bps'] for t in winners)
    for name, stage in measured['stages'].items():
        preserved = sum(allocations[name][ORIGIN(t)] * t['net_bps'] for t in winners)
        stage['current_period_top3_winner_retention'] = {'T': len(winners), 'origin_keys': [ORIGIN(t) for t in winners],
            'original_positive_amount_bps': total, 'preserved_amount_bps': preserved,
            'amount_retention': preserved / total if total else None,
            'labels_are_current_period_outcomes_only': True, 'used_for_entry_weights': False}
    entries = defaultdict(list)
    for key, (_, trade) in items.items():
        entries[trade['entry_ts']].append(key)
    measured['dependence'] = {'entry_clusters': [{'entry_ms': stamp, 'T': len(keys), 'origin_keys': sorted(keys)}
                                                for stamp, keys in sorted(entries.items())],
        'entry_cluster_count': len(entries), 'max_simultaneous_entry_T': max(map(len, entries.values()), default=0),
        'max_holding_days': max((t['hold_ms'] / DAY for _, t in items.values()), default=0),
        'N_effective': None, 'thirty_day_blocks_proven_independent': False,
        'basis': 'SHARED_ENTRY_MARKET_WEIGHT_AND_CROSS_SYMBOL_LOSS_DEPENDENCE; NOT_INDEPENDENT_SAMPLE_COUNTS'}
    measured['dependence']['simultaneous_close_clusters'] = [
        {'exit_ms': stamp, 'T': len(cluster), 'symbol_count': len({t['symbol'] for t in cluster}),
         'symbols': sorted({t['symbol'] for t in cluster}), 'origin_keys': sorted(ORIGIN(t) for t in cluster),
         'unit_loss_T': sum(t['net_bps'] < 0 for t in cluster),
         'unit_winner_T': sum(t['net_bps'] > 0 for t in cluster),
         'stages': {name: {'net_bps': sum(allocation[ORIGIN(t)] * t['net_bps'] for t in cluster),
                           'cost2x_net_bps': sum(allocation[ORIGIN(t)] * t['cost2x_net_bps'] for t in cluster)}
                    for name, allocation in allocations.items()}}
        for stamp, cluster in sorted(accounting.shared.existing_risk.grouped(trades).items())]
    measured['decision'] = _decision(measured)
    return measured
