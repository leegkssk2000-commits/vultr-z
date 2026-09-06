"""Reporting adapter for the frozen Q0 prospective campaign only.

No replay, source acquisition, weight estimation, order execution or economic
adoption. Shared Q0 charges and risk accounting operate on the incremental raw
ledger. A/B daily marks are publishable only after their AFTER_OPEN data exist;
C is explicitly a recalculated ex-post analysis until the fixed campaign end.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from backend.research.rebuild import break_channel_source_v1 as source
from backend.research.rebuild import q0_risk_entry_metrics_v1 as accounting
from backend.research.rebuild import q0_b_seen_metrics_v1 as diagnostic_helpers

DAY, BAR = source.DAY, source.BAR
EVIDENCE = {'evidence_type': 'PROSPECTIVE_RESEARCH_OBSERVATION',
            'independent': False, 'independence_status': 'NOT_YET_ASSESSED',
            'formal_credit': 0, 'operating_adoption': False,
            'execution': 'NONE', 'order': 'BLOCKED', 'live': 'BLOCKED'}


def _label(row):
    key = 'trade_sha256' if 'trade_sha256' in row else 'observation_sha256'
    result = {k: deepcopy(v) for k, v in row.items() if k != key}
    result.update(EVIDENCE, split=EVIDENCE['evidence_type'])
    result[key] = source.old.digest(result)
    return result


def _unit(snapshot, rows, costs, symbols, policy):
    trades, opened, events = [], [], []
    for symbol in symbols:
        raw = snapshot[symbol]
        trades.extend(_label(source.charge(t, symbol, 'Q0', policy, costs, rows[symbol]))
                      for t in raw['trades'])
        opened.extend(_label(source.charge_open(t, symbol, 'Q0', policy, costs, rows[symbol]))
                      for t in raw['open_positions'])
        events.extend(dict(e, symbol=symbol, lane_id=source.LANE,
                           comparison_stage='Q0', scenario='Q0', **EVIDENCE)
                      for e in raw['events'])
    return trades, opened, events


def _daily(trades, opened, rows, costs, start, watermark, tend):
    # At an ordinary midnight the following bar open has not yet arrived.
    # Defer that point; don't publish a close mark and silently revise it later.
    end = watermark - BAR if watermark < tend and watermark % DAY == 0 else watermark
    if end <= start:
        return [], {}, None
    unit, paths = accounting._daily_inputs(trades, opened, rows, costs, start, end)
    # Closed/open classification may change list order at a later observation.
    # A fixed origin ordering makes summation bit-stable across that transition;
    # subsequent entries contribute only zeros to already-published timestamps.
    paths = {key: paths[key] for key in sorted(paths)}
    for index, row in enumerate(unit):
        for field in accounting.DAILY_FIELDS:
            row[field] = sum(path[index][field] for path in paths.values())
    return unit, paths, unit[-1]['mark_ts'] if unit else None


def _dependence(trades, opened):
    entries = defaultdict(list)
    for row in trades + opened:
        entries[row['entry_ts']].append(accounting.ORIGIN(row))
    closes = accounting.shared.existing_risk.grouped(trades)
    return {'entry_cluster_count': len(entries),
            'entry_clusters': [{'entry_ts': ts, 'T': len(keys), 'origin_keys': sorted(keys)}
                               for ts, keys in sorted(entries.items())],
            'simultaneous_close_clusters': [
                {'exit_ts': ts, 'T': len(rows), 'symbols': sorted({t['symbol'] for t in rows}),
                 'origin_keys': sorted(accounting.ORIGIN(t) for t in rows)}
                for ts, rows in sorted(closes.items())],
            'max_holding_days': max((t['hold_ms'] / DAY for t in trades + opened), default=0.),
            'N_effective': None, 'clusters_are_independent_samples': False}


def build(snapshot, rows_by_symbol, costs, observations_by_origin, symbols,
          start, watermark, tend, *, policy):
    """Charge/report current frozen campaign without rerunning a strategy.

    ``observations_by_origin`` is the consumer's immutable entry-time B map.
    Extra observations for pending/cancelled entries are not economic trades.
    Policy seals identify the original frozen code, cost and prospective spec.
    """
    if (set(snapshot) != set(symbols) or set(rows_by_symbol) != set(symbols)
            or set(costs) != set(symbols) or not symbols
            or any(type(value) is not int for value in (start, watermark, tend))
            or start % DAY or tend % DAY or watermark % BAR or start >= tend
            or watermark > tend):
        raise RuntimeError('OBSERVER_ACCOUNTING_SCOPE')
    for symbol in symbols:
        rows = rows_by_symbol[symbol]
        if not rows or rows[-1]['bar_close_ts'] != watermark:
            raise RuntimeError('OBSERVER_ACCOUNTING_WATERMARK:' + symbol)
        if snapshot[symbol]['audit']['common_end_mark_ts'] != watermark:
            raise RuntimeError('OBSERVER_ACCOUNTING_ENGINE_WATERMARK:' + symbol)
    p = {**policy, 'development_interval_ms': [start, watermark]}
    trades, opened, events = _unit(snapshot, rows_by_symbol, costs, symbols, p)
    items = accounting.bridge._index(trades, opened)
    if any(t['entry_ts'] < start or t['entry_ts'] >= tend
           or t.get('exit_ts', t.get('mark_ts')) > watermark
           for _, t in items.values()):
        raise RuntimeError('OBSERVER_ACCOUNTING_TRADE_OUTSIDE_CAMPAIGN')
    pending = [event for event in events if event['status'] == 'PENDING']
    report = {**EVIDENCE, 'calendar': {'start': start, 'watermark': watermark, 'tend': tend},
              'status': 'WAIT_T0' if watermark < start else 'OBSERVATION_IN_PROGRESS' if watermark < tend else 'WINDOW_ENDED_REVIEW_REQUIRED',
              'unit_execution': {'trades': trades, 'open_observations': opened, 'events': events},
              'invariants': {'signals_T': len(events), 'closed_T': len(trades), 'open_T': len(opened),
                             'pending_entry_T': len(pending), 'unit_ledger_and_costs_unchanged': True,
                             'new_or_removed_B_positions': 0, 'account_sizing_or_actual_fills_claimed': False},
              'dependence': _dependence(trades, opened), 'stages': {},
              'control': {'k': None, 'status': 'NOT_DEFINED_ZERO_HOLD', 'ex_post_analysis_only': True,
                          'executable_strategy': False, 'fed_back_to_candidate_weights_or_reference_volatility': False},
              'daily_marking': {'immutable_A_B_last_mark_ts': None,
                               'ordinary_UTC_midnight_waits_for_next_completed_4h_bar': True,
                               'C_daily_is_recalculated_ex_post_analysis': True,
                               'terminal_is_final_close_without_future_open': True},
              'economic_adoption': 'NOT_GRANTED', 'independent_comparison_consumed': False}
    if watermark <= start:
        if trades or opened:
            raise RuntimeError('OBSERVER_ACCOUNTING_PRE_T0_ECONOMIC_LEAK')
        report.update(unit_metrics=None, attribution={},
                      uncertainty={'status': 'INSUFFICIENT_NO_ELAPSED_EVALUATION'})
        return report
    if not set(items).issubset(observations_by_origin):
        raise RuntimeError('OBSERVER_MISSING_LOCKED_ENTRY_WEIGHT')
    observations = {key: observations_by_origin[key] for key in items}
    for key, (_, row) in items.items():
        observation = observations[key]
        if (observation.get('origin_key') != key or observation.get('entry_ts') != row['entry_ts']
                or observation.get('signal_ts') != row['signal_ts']
                or observation.get('available_at', watermark + 1) > row['signal_ts']
                or observation.get('fixed_until_exit') is not True):
            raise RuntimeError('OBSERVER_ENTRY_WEIGHT_TIME_OR_IDENTITY')
    b_weights = accounting._weights(items, observations)
    allocations = {'A_Q0': dict.fromkeys(items, 1.), 'B_RISK': b_weights}
    if sum(t['hold_ms'] for _, t in items.values()) > 0:
        k = accounting.control_weight(trades, opened, b_weights)
        allocations['C_FIXED'] = dict.fromkeys(items, k)
        report['control'].update(k=k, status='EX_POST_DEFINED_AT_CURRENT_WATERMARK',
                                 normalization='SUM_B_WEIGHT_TIMES_HOLD_MS_DIVIDED_BY_SUM_A_HOLD_MS')
    # PENDING is a waiting order, not a completed/censored economic position.
    measured_events = [event for event in events if event['status'] != 'PENDING']
    report['unit_metrics'] = accounting.shared.summarize(trades, opened, measured_events, p, symbols)
    unit_daily, paths, mark_ts = _daily(trades, opened, rows_by_symbol, costs, start, watermark, tend)
    report['daily_marking']['immutable_A_B_last_mark_ts'] = mark_ts
    report['unit_execution']['daily_valuation'] = unit_daily
    winners = sorted((t for t in trades if t['net_bps'] > 0),
                     key=lambda t: (-t['net_bps'], accounting.ORIGIN(t)))[:3]
    top_total = sum(t['net_bps'] for t in winners)
    for name, allocation in allocations.items():
        weighted_trades, weighted_open = accounting.weighted_copies(trades, opened, allocation)
        for row in weighted_trades:
            row['_accounting_weight'] = allocation[accounting.ORIGIN(row)]
        exp = accounting.exposure(trades, opened, allocation, start, watermark)
        metrics = accounting._metrics(trades, opened, weighted_trades, weighted_open,
                                      measured_events, p, symbols, exp)
        daily = accounting.weighted_daily(unit_daily, paths, allocation)
        diagnostics = accounting.shared.diagnostics(weighted_trades, start, watermark)
        marked = accounting.shared.daily_mark_diagnostics(daily)
        marked['status'] = 'OBSERVED_DAILY_MARKS' if daily else 'NOT_YET_A_FULL_MARKED_DAY'
        marked['basis'] = accounting.BASIS + '; NOT_ACCOUNT_MDD'
        obs = observations if name == 'B_RISK' else {
            key: {'weight': value, 'basis': 'ORIGINAL_Q0' if name == 'A_Q0' else 'EX_POST_ANALYSIS_ONLY'}
            for key, value in allocation.items()}
        total = sum(allocation[accounting.ORIGIN(t)] * t['net_bps'] for t in winners)
        monthly, by_symbol = accounting._period_paths(daily, paths, items, allocation) if daily else ({}, {})
        report['stages'][name] = {
            'metrics': metrics, 'diagnostics': diagnostics, 'marked_diagnostics': marked,
            'exposure': exp, 'daily': daily,
            'daily_history_immutable': name != 'C_FIXED' or watermark == tend,
            'ledger': accounting._public_ledger(trades, opened, allocation, obs),
            'by_mark_month': monthly, 'by_symbol_at_last_immutable_daily_mark': by_symbol,
            'original_profit_retention': accounting._retention(trades, allocation),
            'current_period_top3_winner_retention': {'T': len(winners),
                'origin_keys': [accounting.ORIGIN(t) for t in winners],
                'original_positive_amount_bps': top_total, 'preserved_amount_bps': total,
                'amount_retention': total / top_total if top_total else None,
                'post_outcome_diagnostic_only': True},
            'group_sign_changes_from_Q0': accounting._group_changes(trades, weighted_trades)}
        if watermark == tend:
            accounting._same(daily[-1]['cumulative_net_mark_bps'],
                             metrics['terminal_net_amount_bps'], 'OBSERVER_TERMINAL_NET_PARITY')
            accounting._same(daily[-1]['cumulative_cost2x_net_mark_bps'],
                             metrics['terminal_cost2x_net_amount_bps'], 'OBSERVER_TERMINAL_COST2_PARITY')
    report['attribution'] = {'B_minus_A': accounting.attribution(trades, opened,
                                                               allocations['A_Q0'], b_weights)}
    if 'C_FIXED' in allocations:
        report['attribution']['B_minus_C'] = accounting.attribution(trades, opened,
                                                                   allocations['C_FIXED'], b_weights)
        accounting._same(report['stages']['B_RISK']['exposure']['nominal_weighted_position_days'],
                         report['stages']['C_FIXED']['exposure']['nominal_weighted_position_days'],
                         'OBSERVER_C_EQUAL_EXPOSURE')
        report['cohorts'] = diagnostic_helpers.cohort_diagnostics(trades, allocations)
        b, c = report['stages']['B_RISK'], report['stages']['C_FIXED']
        loss_key = 'lane_simultaneous_close_group_streaks'
        report['B_minus_C_descriptive'] = {
            'terminal_net_amount_bps': b['metrics']['terminal_net_amount_bps'] - c['metrics']['terminal_net_amount_bps'],
            'terminal_cost2x_net_amount_bps': b['metrics']['terminal_cost2x_net_amount_bps'] - c['metrics']['terminal_cost2x_net_amount_bps'],
            'daily_marked_DD_amount_bps': b['marked_diagnostics']['marked_DD_trade_sum_bps'] - c['marked_diagnostics']['marked_DD_trade_sum_bps'],
            'maximum_grouped_loss_amount_bps': b['diagnostics'][loss_key]['max_loss_trade_sum_bps'] - c['diagnostics'][loss_key]['max_loss_trade_sum_bps'],
            'different_maximum_windows_are_not_causal_contributions': True,
            'economic_adoption': 'NOT_GRANTED'}
    a_daily = report['stages']['A_Q0']['daily']
    zeros = [dict(row, value=0.) for row in a_daily]
    uncertainty = {'A_absolute_vs_no_trade': accounting.shared.paired_daily_uncertainty(zeros, a_daily),
                   'B_minus_C': accounting.shared.paired_daily_uncertainty(
                       report['stages']['C_FIXED']['daily'], report['stages']['B_RISK']['daily'])
                       if 'C_FIXED' in report['stages'] else {'status': 'INSUFFICIENT_ZERO_HOLD'}}
    for comparison in uncertainty.values():
        comparison.update(independent=False, formal_credit=0,
                          not_a_sequential_PASS_test=True,
                          qualification='PROSPECTIVE_COMPLIANCE_AND_DEPENDENCE_REVIEW_PENDING')
    report['uncertainty'] = uncertainty
    report['B_activation'] = {'accepted_entry_T': len(items),
        'reduced_entry_T': sum(value < 1. for value in b_weights.values()),
        'minimum_weight': min(b_weights.values(), default=None),
        'maximum_weight': max(b_weights.values(), default=None),
        'entry_weight_observations': deepcopy(observations),
        'unit_win_rate_or_signal_predictive_power_changed': False}
    return report
