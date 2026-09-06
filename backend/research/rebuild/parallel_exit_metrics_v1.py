"""Pure reporting for the two frozen exit studies; never loads market data.

Reuses sealed closed/open accounting and origin attribution. UTC marks include
the native calendar's partial first/last day without inventing a future price.
Outcome cohorts and retention labels are report-only, never execution features.
"""
from collections import defaultdict
from datetime import datetime, timezone
import math

from backend.research.rebuild import break_channel_metrics_v1 as shared
from backend.research.rebuild import break_channel_q1_metrics_v1 as bridge
from backend.research.rebuild import break_channel_source_v1 as source
from backend.research.rebuild import q0_b_seen_metrics_v1 as seen

DAY = shared.DAY
BAR = source.BAR
VALUE_FIELDS = bridge.VALUE_FIELDS
GOAL = {
    'minimum_closed_T': 6,
    'large_winner_capped_retention_min': 0.90,
    'large_winner_floor_source': 'break_channel_q1_v1.GOAL; inherited DEV design prior only',
    'absolute': 'closed net/E>0, PF>1, realized payoff>=1, cost2 net>0',
    'increment': 'closed and closed-plus-hypothetical-terminal net must both increase',
    'risk': 'grouped closed loss-run and UTC marked DD must not worsen',
    'strong_evidence': 'paired UTC daily-bucket delta95 lower>0; no unresolved positions',
    'both_comparisons': 'fixed-entry and full replay must each meet study criteria',
    'periods': 'separate reused-data results; no automatic combined or operating adoption',
    'block_days': 30, 'resamples': 1000, 'seed': 1178,
    'formal_SSOT_modified': False,
}


def _calendar(start, end):
    if end <= start or start % BAR or end % BAR:
        raise ValueError('INVALID_FOUR_HOUR_REPORT_CALENDAR')
    marks = list(range((start // DAY + 1) * DAY, end + 1, DAY))
    if not marks or marks[-1] != end:
        marks.append(end)
    return marks


def _prices(rows_by_symbol, start, end):
    prices = {}
    for symbol, rows in rows_by_symbol.items():
        values = {r['bar_close_ts']: r['close'] for r in rows
                  if start < r['bar_close_ts'] <= end}
        # Intermediate marks follow same-time open orders; terminal never sees
        # the excluded next open. This is the original Q0 mark convention.
        values.update({r['bar_open_ts']: r['open'] for r in rows
                       if start < r['bar_open_ts'] < end})
        prices[symbol] = values
    return prices


def _boundary(item, ts, prices, costs, start, end):
    status, trade = item
    final = bridge._values(item)
    terminal = trade['exit_ts'] if status == 'C' else trade['mark_ts']
    if (trade['side'] != 'long' or not start <= trade['entry_ts'] <= terminal <= end
            or (status == 'O' and terminal != end)):
        raise ValueError('UNSUPPORTED_POSITION_CALENDAR_OR_SIDE')
    if ts == start or trade['entry_ts'] > ts:
        return dict.fromkeys(VALUE_FIELDS, 0.0)
    if status == 'C' and terminal <= ts:
        return final
    px = prices.get(trade['symbol'], {}).get(ts)
    if px is None:
        raise RuntimeError('MISSING_COMPLETED_REPORT_MARK_PRICE')
    if not math.isfinite(px) or px <= 0 or not math.isfinite(trade['entry_price']) or trade['entry_price'] <= 0:
        raise RuntimeError('INVALID_REPORT_MARK_PRICE')
    gross = (px / trade['entry_price'] - 1) * 10000
    parts = source.old.probe.cost_components(trade['entry_ts'], ts, costs[trade['symbol']])
    parts['frozen_floor_reserve_bps'] = max(0.0, 20.0 - parts['cost_bps'])
    cost = max(20.0, parts['cost_bps'])
    value = {'gross_bps': gross, 'net_bps': gross - cost,
             'cost2x_net_bps': gross - 2 * cost, 'cost_bps': cost,
             **{key: parts[key] for key in shared.COST_FIELDS}}
    if status == 'O' and ts == end:
        for key in VALUE_FIELDS:
            bridge._same(value[key], final[key], 'TERMINAL_OPEN_MARK_PARITY:' + key)
    return value


def daily_valuation(trades, opened, rows_by_symbol, costs, start, end):
    """All eligible UTC day boundaries plus exact final partial-day close."""
    items = bridge._index(trades, opened)
    prices = _prices(rows_by_symbol, start, end)
    previous = dict.fromkeys(VALUE_FIELDS, 0.0)
    left = start
    result = []
    for ts in _calendar(start, end):
        values = [_boundary(item, ts, prices, costs, start, end) for item in items.values()]
        total = {key: sum(value[key] for value in values) for key in VALUE_FIELDS}
        result.append({
            'date': datetime.fromtimestamp((ts - 1) / 1000, timezone.utc).date().isoformat(),
            'mark_ts': ts, 'interval_start_ms': left, 'interval_hours': (ts - left) / 3_600_000,
            'value': total['net_bps'] - previous['net_bps'],
            'gross_delta_bps': total['gross_bps'] - previous['gross_bps'],
            'cost_delta_bps': total['cost_bps'] - previous['cost_bps'],
            'cumulative_net_mark_bps': total['net_bps'],
            'cumulative_gross_mark_bps': total['gross_bps'],
            'cumulative_cost2x_mark_bps': total['cost2x_net_bps'],
            'full_cost_bps_at_valuation': total['cost_bps'],
            'modeled_funding_bps_at_valuation': total['funding_bps'],
            'cost_components_bps_at_valuation': {key: total[key] for key in shared.COST_FIELDS},
            'active_marked_positions': sum(t['entry_ts'] <= ts and (status == 'O' or t['exit_ts'] > ts)
                                           for status, t in items.values()),
            'valuation_phase': 'AFTER_OPEN_ORDERS' if ts < end else 'FINAL_CLOSE_NO_FUTURE_OPEN',
            'basis': 'UTC_BUCKETS_WITH_NATIVE_PARTIAL_EDGES; HYPOTHETICAL_FULL_COST_OPEN_MARKS',
        })
        previous, left = total, ts
    terminal = bridge._totals(list(items.values()))
    for key in VALUE_FIELDS:
        bridge._same(previous[key], terminal[key], 'DAILY_TERMINAL_BRIDGE:' + key)
    return result


def marked_diagnostics(daily, start):
    """Same DD arithmetic as sealed helper; recovery duration uses exact times."""
    result = shared.daily_mark_diagnostics(daily)
    equity = peak = worst = 0.0
    peak_ts = start
    submerged = False
    recoveries = []
    window = None
    for row in daily:
        equity += row['value']
        if peak - equity > worst:
            worst = peak - equity
            window = {'start_ms': peak_ts, 'end_ms': row['mark_ts']}
        if equity >= peak:
            if submerged:
                recoveries.append((row['mark_ts'] - peak_ts) / DAY)
            peak, peak_ts, submerged = equity, row['mark_ts'], False
        else:
            submerged = True
    bridge._same(result['marked_DD_trade_sum_bps'], worst, 'MARKED_DD_ARITHMETIC_PARITY')
    result.update(max_completed_recovery_days=max(recoveries, default=0),
                  open_underwater_days=(daily[-1]['mark_ts'] - peak_ts) / DAY if submerged else 0,
                  worst_window=window,
                  completed_recovery_durations_days=recoveries,
                  recovery_clock='ACTUAL_ELAPSED_MS_INCLUDING_NATIVE_PARTIAL_EDGES')
    return result


def build_stage(trades, opened, events, rows_by_symbol, costs, policy, symbols, start, end):
    if policy['development_interval_ms'] != [start, end]:
        raise ValueError('REPORT_POLICY_CALENDAR_MISMATCH')
    metrics = shared.summarize(trades, opened, events, policy, symbols)
    terminal = bridge._totals(list(bridge._index(trades, opened).values()))
    metrics['terminal_totals_bps'] = terminal
    metrics['frequency'] = {
        'calendar_days': (end - start) / DAY,
        'entries_per_30_calendar_days': (len(trades) + len(opened)) * 30 * DAY / (end - start),
        'closed_trades_per_30_calendar_days': len(trades) * 30 * DAY / (end - start),
    }
    monthly_profit = {month: value['net_bps'] for month, value in metrics['by_exit_month'].items()}
    positive = sum(max(0, value) for value in monthly_profit.values())
    metrics['concentration']['by_exit_month_net_bps'] = monthly_profit
    metrics['concentration']['top_positive_month_share'] = (
        max((max(0, value) for value in monthly_profit.values()), default=0) / positive if positive else None)
    daily = daily_valuation(trades, opened, rows_by_symbol, costs, start, end)
    return {'metrics': metrics, 'diagnostics': shared.diagnostics(trades, start, end),
            'daily': daily, 'marked_diagnostics': marked_diagnostics(daily, start),
            'comparison_calendar_ms': [start, end], 'independent': False,
            'closed_loss_cohorts': seen._cohorts(trades),
            'calendar_partial_edge_hours': [daily[0]['interval_hours'], daily[-1]['interval_hours']]}


def _window(trades, opened, prices, costs, start, end, left, right, daily):
    contributions = []
    for origin, item in sorted(bridge._index(trades, opened).items()):
        a = _boundary(item, left, prices, costs, start, end)
        b = _boundary(item, right, prices, costs, start, end)
        delta = {key: b[key] - a[key] for key in VALUE_FIELDS}
        if any(abs(value) > 1e-12 for value in delta.values()):
            contributions.append({'origin_key': origin, 'symbol': item[1]['symbol'],
                                  'signal_ts': item[1]['signal_ts'], 'terminal_status': item[0],
                                  'delta': delta})
    totals = {key: sum(t['delta'][key] for t in contributions) for key in VALUE_FIELDS}
    marked_delta = sum(row['value'] for row in daily if left < row['mark_ts'] <= right)
    bridge._same(totals['net_bps'], marked_delta, 'SAME_CALENDAR_WINDOW_BRIDGE')
    return {'totals': totals, 'position_contributions': contributions, 'parity': 'PASS'}


def same_calendar_windows(parent_stage, child_stage, pc, po, cc, co, rows, costs, start, end):
    """All parent sign cohorts and both worst DD/loss runs on identical marks."""
    boundaries = [start, *_calendar(start, end)]
    requested = defaultdict(list)
    for name, stage in (('PARENT', parent_stage), ('CHILD', child_stage)):
        window = stage['marked_diagnostics']['worst_window']
        if window:
            requested[(window['start_ms'], window['end_ms'])].append(name + '_WORST_MARKED_DD')
        cohorts = stage['closed_loss_cohorts']
        if name == 'CHILD':
            index = bridge._index(cc, co)
            losing = [c for c in cohorts if c['sign'] < 0]
            cohorts = ([min(losing, key=lambda c: sum(index[k][1]['net_bps'] for k in c['origin_keys']))]
                       if losing else [])
        for cohort in cohorts:
            # Include a loss closing exactly at a mark by choosing the earlier
            # boundary strictly before its first exit, as in the sealed study.
            left = max((ts for ts in boundaries if ts < cohort['start_exit_ms']), default=start)
            right = min((ts for ts in boundaries if ts >= cohort['end_exit_ms']), default=end)
            if left < right:
                requested[(left, right)].append(name + '_COHORT_' + str(cohort['cohort_id']))
    prices = _prices(rows, start, end)
    result = []
    for (left, right), labels in sorted(requested.items()):
        p = _window(pc, po, prices, costs, start, end, left, right, parent_stage['daily'])
        c = _window(cc, co, prices, costs, start, end, left, right, child_stage['daily'])
        result.append({'start_ms': left, 'end_ms': right, 'labels': labels,
                       'parent': p, 'child': c,
                       'child_minus_parent': {key: c['totals'][key] - p['totals'][key] for key in VALUE_FIELDS},
                       'post_outcome_analysis_only': True,
                       'different_maxima_subtraction_is_causal_attribution': False,
                       'overlapping_windows_must_not_be_summed': True})
    return result


def study_decision(parent_stage, child_stage, attribution, uncertainty):
    p, c = parent_stage['metrics'], child_stage['metrics']
    base = c['base_cost']
    defined = all(base[key] is not None for key in ('expectancy_bps_per_trade', 'PF', 'realized_payoff'))
    absolute = {
        'positive_closed_net': base['net_bps'] > 0,
        'positive_expectancy': base['expectancy_bps_per_trade'] is not None and base['expectancy_bps_per_trade'] > 0,
        'PF_above_one': base['PF'] is not None and base['PF'] > 1,
        'payoff_at_least_one': base['realized_payoff'] is not None and base['realized_payoff'] >= 1,
        'positive_closed_cost2x_net': c['cost2x']['net_bps'] > 0,
    }
    increments = {'closed_net_increased': attribution['closed_net_delta_bps'] > 1e-7,
                  'terminal_net_increased': attribution['marked_delta_bps_not_realized'] > 1e-7}
    loss = lambda stage: stage['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps']
    retention = attribution['large_winner']['amount_retention_lower']
    lower = uncertainty['child_minus_parent_95pct_interval_bps_per_day'][0]
    risk = {
        'grouped_loss_run_not_worse': loss(child_stage) <= loss(parent_stage) + 1e-7,
        'marked_DD_not_worse': child_stage['marked_diagnostics']['marked_DD_trade_sum_bps'] <=
                              parent_stage['marked_diagnostics']['marked_DD_trade_sum_bps'] + 1e-7,
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
    return {'decision': decision, 'comparison_type': 'EXIT_CHANGE',
            'absolute_economic_checks': absolute, 'increment_checks': increments,
            'risk_and_evidence_checks': risk,
            'failed_checks': [key for group in (absolute, increments, risk) for key, value in group.items() if not value],
            'loss_reduction': base['net_bps'] < 0 and attribution['closed_net_delta_bps'] > 1e-7,
            'closed_net_delta_bps': attribution['closed_net_delta_bps'],
            'terminal_net_delta_bps': attribution['marked_delta_bps_not_realized'],
            'grouped_loss_run_delta_bps_descriptive': loss(child_stage) - loss(parent_stage),
            'exposure_delta_symbol_days': c['total_exposure_symbol_days'] - p['total_exposure_symbol_days'],
            'source_overlap_is_economic_gate': False, 'formal_pass': False,
            'operating_adoption': False, 'independent': False, 'code_PASS_is_economic_PASS': False,
            'open_censoring_blocks_strong_verdict': not risk['no_unresolved_positions']}


def net_decomposition(parent_closed, parent_open, child_closed, child_open, attribution):
    """Signed closed-net bridge; profit cutting and new losses stay separate."""
    p, c = bridge._index(parent_closed, parent_open), bridge._index(child_closed, child_open)
    effects = dict.fromkeys(('common_loser_improvement_bps', 'common_loser_deterioration_bps',
        'common_winner_profit_cut_bps', 'common_winner_flipped_loss_bps',
        'common_winner_profit_added_bps', 'common_zero_parent_net_delta_bps'), 0.0)
    for origin in attribution['groups']['CC']['origins']:
        pv, cv = p[origin][1]['net_bps'], c[origin][1]['net_bps']
        if pv < 0:
            effects['common_loser_improvement_bps'] += max(0, cv - pv)
            effects['common_loser_deterioration_bps'] += max(0, pv - cv)
        elif pv > 0:
            effects['common_winner_profit_cut_bps'] += max(0, pv - max(0, cv))
            effects['common_winner_flipped_loss_bps'] += max(0, -cv)
            effects['common_winner_profit_added_bps'] += max(0, cv - pv)
        else:
            effects['common_zero_parent_net_delta_bps'] += cv
    common = (effects['common_loser_improvement_bps'] - effects['common_loser_deterioration_bps']
              - effects['common_winner_profit_cut_bps'] - effects['common_winner_flipped_loss_bps']
              + effects['common_winner_profit_added_bps'] + effects['common_zero_parent_net_delta_bps'])
    bridge._same(common, attribution['groups']['CC']['closed']['delta']['net_bps'], 'COMMON_SIGNED_NET_BRIDGE')
    other = {name: attribution['groups'][name]['closed']['delta']['net_bps'] for name in bridge.GROUPS if name != 'CC'}
    bridge._same(common + sum(other.values()), attribution['closed_net_delta_bps'], 'FULL_SIGNED_NET_BRIDGE')
    return {**effects, 'other_origin_group_signed_net_delta_bps': other,
            'common_closed_net_delta_bps': common,
            'closed_net_delta_bps': attribution['closed_net_delta_bps'], 'parity': 'PASS',
            'cost_saving_already_in_net_do_not_add_again': True,
            'loser_improvement_can_include_new_positive_profit': True,
            'censor_changes_separate_from_avoided_losses': True}


def compare(parent_stage, child_stage, parent_closed, parent_open, child_closed, child_open,
            rows_by_symbol, costs, start, end):
    attribution = bridge.symmetric_attribution(parent_closed, parent_open, child_closed, child_open)
    uncertainty = shared.paired_daily_uncertainty(parent_stage['daily'], child_stage['daily'],
        block_days=GOAL['block_days'], resamples=GOAL['resamples'], seed=GOAL['seed'])
    uncertainty.update(independent=False, partial_native_edge_buckets_included=True,
                       daily_unit='UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION')
    return {'attribution': attribution, 'uncertainty': uncertainty,
            'net_decomposition': net_decomposition(parent_closed, parent_open, child_closed, child_open, attribution),
            'decision': study_decision(parent_stage, child_stage, attribution, uncertainty),
            'same_calendar_windows': same_calendar_windows(parent_stage, child_stage,
                parent_closed, parent_open, child_closed, child_open, rows_by_symbol, costs, start, end)}


def candidate_decision(fixed, full):
    decisions = [result['decision']['decision'] for result in (fixed, full)]
    decision = ('INSUFFICIENT' if 'INSUFFICIENT' in decisions else 'REJECT' if 'REJECT' in decisions
                else 'TRADEOFF' if 'TRADEOFF' in decisions else 'IMPROVED')
    return {'decision': decision, 'fixed_entry_decision': decisions[0], 'full_replay_decision': decisions[1],
            'research_child_reference_supported': decision == 'IMPROVED',
            'existing_Q0_or_operating_baseline_changed': False, 'formal_pass': False, 'independent': False}
