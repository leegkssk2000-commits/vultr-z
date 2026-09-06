"""Pure entry-notional accounting on an unchanged, sealed Q0 unit ledger.

The source valuation/cost and summary routines remain unchanged. Weighting is
applied to their monetary outputs, never to prices, time, orders or ownership.
No data loading, candidate signal replay, threshold selection or account sizing.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
import statistics

from backend.research.rebuild import break_channel_metrics_v1 as shared
from backend.research.rebuild import break_channel_q1_metrics_v1 as bridge
from backend.research.rebuild import break_channel_source_v1 as source

DAY = shared.DAY
ORIGIN = bridge.ORIGIN
VALUE_FIELDS = bridge.VALUE_FIELDS
DAILY_FIELDS = ('value', 'gross_delta_bps', 'cumulative_net_mark_bps',
                'cumulative_gross_mark_bps', 'full_cost_bps_at_valuation',
                'modeled_funding_bps_at_valuation')
OPEN_FIELDS = ('gross_mark_bps', 'modeled_funding_accrued_bps',
               'hypothetical_liquidation_cost_bps', 'hypothetical_liquidation_net_mark_bps',
               'hypothetical_liquidation_cost2x_net_mark_bps')
BASIS = 'FIXED_REFERENCE_NOTIONAL_WEIGHTED_AMOUNTS_IN_BPS_UNITS; NOT_ACCOUNT_RETURNS_OR_UNIT_TRADE_RETURNS'


def _same(a, b, name):
    if not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-7):
        raise RuntimeError(name)


def _weights(items, observations):
    if set(items) != set(observations):
        raise ValueError('WEIGHT_ORIGIN_COVERAGE_MISMATCH')
    result = {}
    for key in items:
        row = observations[key]
        weight = row['weight'] if isinstance(row, dict) else row
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or not 0 < weight <= 1:
            raise ValueError('ENTRY_WEIGHT_MUST_BE_FINITE_POSITIVE_AND_AT_MOST_ONE')
        result[key] = float(weight)
    return result


def weighted_copies(trades, opened, weights):
    """Ephemeral summary inputs. Public ledger retains original units separately."""
    items = bridge._index(trades, opened)
    w = _weights(items, weights)
    closed_copy, open_copy = deepcopy(trades), deepcopy(opened)
    for t in closed_copy:
        bridge._values(('C', t))
        for field in VALUE_FIELDS:
            t[field] *= w[ORIGIN(t)]
    for t in open_copy:
        bridge._values(('O', t))
        for field in OPEN_FIELDS:
            t[field] *= w[ORIGIN(t)]
        t['hypothetical_cost_components_bps'] = {
            field: value * w[ORIGIN(t)] for field, value in t['hypothetical_cost_components_bps'].items()}
    return closed_copy, open_copy


def exposure(trades, opened, weights, start, end):
    """Original occupancy plus half-open nominal-weighted holding integral."""
    original = shared.exposure_summary(trades, opened, start_ms=start, end_ms=end)
    items = bridge._index(trades, opened)
    w = _weights(items, weights)
    changes = defaultdict(float)
    changes[start] = changes[end] = 0.0
    total = 0.0
    for key, (status, t) in items.items():
        terminal = t['exit_ts'] if status == 'C' else t['mark_ts']
        total += w[key] * t['hold_ms']
        if terminal > t['entry_ts']:
            changes[t['entry_ts']] += w[key]
            changes[terminal] -= w[key]
    active = maximum = integrated = 0.0
    stamps = sorted(changes)
    intervals = []
    for i, ts in enumerate(stamps):
        active += changes[ts]
        if active < -1e-10:
            raise RuntimeError('NEGATIVE_WEIGHTED_EXPOSURE')
        maximum = max(maximum, active)
        if i + 1 < len(stamps):
            right = stamps[i + 1]
            integrated += active * (right - ts)
            intervals.append({'start_ms': ts, 'end_ms': right,
                              'nominal_weighted_open_slots': max(0.0, active)})
    _same(active, 0.0, 'WEIGHTED_EXPOSURE_UNCLOSED')
    _same(integrated, total, 'WEIGHTED_EXPOSURE_INTEGRAL_PARITY')
    return {'unweighted_occupancy': original,
            'nominal_weighted_position_days': total / DAY,
            'mean_nominal_weighted_open_slots': total / (end - start),
            'max_simultaneous_nominal_weighted_open_slots': maximum,
            'holding_intervals': intervals,
            'basis': 'FIXED_ENTRY_WEIGHT_TIMES_UNCHANGED_HOLDING_TIME; NOT_ACCOUNT_EXPOSURE'}


def control_weight(trades, opened, weights):
    items = bridge._index(trades, opened)
    w = _weights(items, weights)
    denominator = sum(t['hold_ms'] for _, t in items.values())
    if denominator <= 0:
        raise ValueError('FIXED_CONTROL_UNDEFINED_ZERO_TOTAL_HOLDING_TIME')
    numerator = sum(w[key] * t['hold_ms'] for key, (_, t) in items.items())
    k = numerator / denominator
    if not math.isfinite(k) or not 0 < k <= 1:
        raise ValueError('INVALID_POST_HOC_CONTROL_WEIGHT')
    return k


def _daily_inputs(trades, opened, rows, costs, start, end):
    unit = source.daily_valuation(trades, opened, rows, costs, start, end)
    paths = {}
    for key, (status, t) in bridge._index(trades, opened).items():
        paths[key] = source.daily_valuation([t] if status == 'C' else [],
                                          [t] if status == 'O' else [], rows, costs, start, end)
    for i, day in enumerate(unit):
        for field in DAILY_FIELDS:
            _same(sum(p[i][field] for p in paths.values()), day[field], 'UNIT_DAILY_POSITION_BRIDGE:' + field)
        if sum(p[i]['active_marked_positions'] for p in paths.values()) != day['active_marked_positions']:
            raise RuntimeError('UNIT_DAILY_OCCUPANCY_BRIDGE')
    return unit, paths


def weighted_daily(unit, paths, weights):
    """Only full-cost per-position marks are weighted; no scaling of mark price."""
    answer = []
    for i, original in enumerate(unit):
        row = deepcopy(original)
        for field in DAILY_FIELDS:
            row[field] = sum(weights[key] * path[i][field] for key, path in paths.items())
        row['nominal_weighted_active_marked_slots'] = sum(
            weights[key] * path[i]['active_marked_positions'] for key, path in paths.items())
        row['cumulative_cost2x_net_mark_bps'] = row['cumulative_gross_mark_bps'] - 2 * row['full_cost_bps_at_valuation']
        previous_cost2 = answer[-1]['cumulative_cost2x_net_mark_bps'] if answer else 0.0
        row['cost2x_net_delta_bps'] = row['cumulative_cost2x_net_mark_bps'] - previous_cost2
        row['basis'] = BASIS + '; FULL_HYPOTHETICAL_ROUNDTRIP_COST_ON_OPEN_MARKS'
        answer.append(row)
    return answer


def _public_ledger(trades, opened, weights, observations):
    out = {'closed': [], 'open': []}
    for target, status, rows in (('closed', 'C', trades), ('open', 'O', opened)):
        for row in rows:
            key = ORIGIN(row)
            out[target].append({'origin_key': key, 'status': status, 'entry_weight': weights[key],
                                'unit_trade': deepcopy(row),
                                'weighted_values': {field: weights[key] * value
                                                    for field, value in bridge._values((status, row)).items()},
                                'weight_observation': deepcopy(observations[key]), 'basis': BASIS})
    return out


def _retention(trades, weights):
    winners = sorted((t for t in trades if t['net_bps'] > 0), key=lambda t: (-t['net_bps'], ORIGIN(t)))
    answer = {}
    for label, selected in (('all_winners', winners), ('original_top_decile_winners', winners[:math.ceil(len(winners) * .1)])):
        original = sum(t['net_bps'] for t in selected)
        retained = sum(weights[ORIGIN(t)] * t['net_bps'] for t in selected)
        answer[label] = {'T': len(selected), 'origin_keys': [ORIGIN(t) for t in selected],
                         'original_positive_amount_bps': original, 'preserved_amount_bps': retained,
                         'foregone_amount_bps': original - retained,
                         'amount_retention': retained / original if original else None}
    return answer


def _group_changes(trades, weighted):
    parent = shared.existing_risk.grouped(trades)
    child = shared.existing_risk.grouped(weighted)
    sign = lambda x: -1 if x < 0 else 1 if x > 0 else 0
    changes = []
    for ts in sorted(parent):
        p = sum(t['net_bps'] for t in parent[ts])
        c = sum(t['net_bps'] for t in child[ts])
        if sign(p) != sign(c):
            changes.append({'exit_ts': ts, 'original_group_net_bps': p,
                            'weighted_group_net_bps': c, 'T': len(parent[ts]),
                            'origin_keys': [ORIGIN(t) for t in parent[ts]]})
    return {'changed_simultaneous_group_sign_T': len(changes), 'groups': changes,
            'individual_trade_signs_unchanged': True,
            'interpretation': 'MIXED_SIGN_SIMULTANEOUS_GROUP_REWEIGHTING_CAN_CHANGE_RUN_LABELS; NOT_SIGNAL_ACCURACY'}


def _metrics(trades, opened, weighted_trades, weighted_open, events, policy, symbols, exp):
    m = shared.summarize(weighted_trades, weighted_open, events, policy, symbols)
    # Preserve old summary arithmetic but remove ambiguous nominal-exposure labels.
    collections = [(m['base_cost'], weighted_trades), (m['cost2x'], weighted_trades)]
    collections += [(m['by_symbol'][s], [t for t in weighted_trades if t['symbol'] == s]) for s in symbols]
    collections += [(value, [t for t in weighted_trades if str(shared.shared.probe.stamp_year(t['entry_ts'])) == year])
                    for year, value in m['by_year'].items()]
    weights = {ORIGIN(t): t['_accounting_weight'] for t in weighted_trades}
    for stats, rows in collections:
        duration = sum(weights[ORIGIN(t)] * t['hold_ms'] for t in rows) / DAY
        stats['unweighted_occupancy_symbol_days'] = stats.pop('exposure_symbol_days')
        stats['unweighted_time_in_market_fraction'] = stats.pop('time_in_market_fraction')
        stats.pop('net_bps_per_exposure_day')
        stats['nominal_weighted_position_days'] = duration
        stats['net_amount_bps_per_nominal_weighted_day'] = stats['net_bps'] / duration if duration else None
        stats['basis'] = BASIS + '; EXPECTANCY_DENOMINATOR_IS_ORIGINAL_COMPLETED_T'
        stats['win_rate_is_unchanged_unit_trade_sign_frequency'] = True
    # Excursion prices were deliberately not reweighted; retain them only in unit metrics.
    for field in ('mean_mfe_bps', 'mean_mae_bps'):
        m['base_cost'].pop(field, None)
    m['unweighted_total_occupancy_position_days'] = m.pop('total_exposure_symbol_days')
    m['unweighted_exposure'] = m.pop('exposure')
    m['nominal_weighted_position_days'] = exp['nominal_weighted_position_days']
    m['open_observations']['unweighted_occupancy_position_days'] = m['open_observations'].pop('exposure_symbol_days')
    m['open_observations']['nominal_weighted_position_days'] = (
        exp['nominal_weighted_position_days'] - m['base_cost']['nominal_weighted_position_days'])
    m['terminal_net_amount_bps'] = m['closed_plus_hypothetical_terminal_mark_bps']
    m['terminal_cost2x_net_amount_bps'] = m['cost2x']['net_bps'] + m['open_observations']['hypothetical_liquidation_cost2x_net_mark_bps']
    m['basis'] = BASIS
    m['unit_return_and_signal_predictive_power_changed'] = False
    positive_month = {month: max(0.0, values['net_bps']) for month, values in m['by_exit_month'].items()}
    positive_sum = sum(positive_month.values())
    m['exit_month_positive_net_concentration'] = {
        'positive_month_net_bps': positive_month,
        'top_one_positive_month_share': max(positive_month.values(), default=0.0) / positive_sum if positive_sum else None,
        'basis': 'POSITIVE_MONTH_AGGREGATE_CLOSED_NET_AMOUNTS; DISTINCT_FROM_POSITIVE_INDIVIDUAL_WINNER_PROFITS'}
    return m


def _period_paths(daily, paths, items, weights):
    monthly = defaultdict(lambda: {'net_bps': 0.0, 'gross_bps': 0.0, 'cost2x_net_bps': 0.0,
                                  'cost_delta_bps': 0.0, 'funding_delta_bps': 0.0, 'days': 0})
    previous_cost = previous_funding = 0.0
    for row in daily:
        group = monthly[row['date'][:7]]
        group['net_bps'] += row['value']
        group['gross_bps'] += row['gross_delta_bps']
        group['cost2x_net_bps'] += row['cost2x_net_delta_bps']
        group['cost_delta_bps'] += row['full_cost_bps_at_valuation'] - previous_cost
        group['funding_delta_bps'] += row['modeled_funding_bps_at_valuation'] - previous_funding
        group['days'] += 1
        previous_cost, previous_funding = row['full_cost_bps_at_valuation'], row['modeled_funding_bps_at_valuation']
    by_symbol = defaultdict(lambda: {'terminal_net_bps': 0.0, 'terminal_gross_bps': 0.0,
                                    'terminal_cost2x_net_bps': 0.0, 'cost_bps': 0.0, 'funding_bps': 0.0})
    for key, path in paths.items():
        row = path[-1]
        group = by_symbol[items[key][1]['symbol']]
        w = weights[key]
        group['terminal_net_bps'] += w * row['cumulative_net_mark_bps']
        group['terminal_gross_bps'] += w * row['cumulative_gross_mark_bps']
        group['cost_bps'] += w * row['full_cost_bps_at_valuation']
        group['funding_bps'] += w * row['modeled_funding_bps_at_valuation']
        group['terminal_cost2x_net_bps'] += w * (row['cumulative_gross_mark_bps'] - 2 * row['full_cost_bps_at_valuation'])
    return dict(sorted(monthly.items())), dict(sorted(by_symbol.items()))


def attribution(trades, opened, parent_weights, child_weights):
    """All trades remain common. Net-sign and gross-minus-cost bridges are distinct."""
    items = bridge._index(trades, opened)
    delta = dict.fromkeys(VALUE_FIELDS, 0.0)
    closed = dict.fromkeys(VALUE_FIELDS, 0.0)
    loss_effect = win_effect = flat_effect = 0.0
    rows = []
    for key, (status, row) in items.items():
        values = bridge._values((status, row))
        d = {field: (child_weights[key] - parent_weights[key]) * value for field, value in values.items()}
        rows.append({'origin_key': key, 'status': status, 'delta': d})
        for field in VALUE_FIELDS:
            delta[field] += d[field]
            if status == 'C':
                closed[field] += d[field]
        if status == 'C':
            if row['net_bps'] < 0:
                loss_effect += d['net_bps']
            elif row['net_bps'] > 0:
                win_effect += d['net_bps']
            else:
                flat_effect += d['net_bps']
    _same(closed['net_bps'], loss_effect + win_effect + flat_effect, 'NET_SIGN_ATTRIBUTION_BRIDGE')
    _same(delta['net_bps'], delta['gross_bps'] - delta['cost_bps'], 'WEIGHTED_GROSS_COST_BRIDGE')
    return {'common_closed_T': len(trades), 'common_open_T': len(opened), 'removed_T': 0, 'new_T': 0,
            'new_trade_net_bps': 0.0, 'removed_trade_net_bps': 0.0,
            'closed_delta': closed, 'terminal_delta': delta,
            'loss_amount_reduction_bps_signed': loss_effect,
            'winner_amount_change_bps_signed': win_effect,
            'foregone_winner_amount_bps_signed': -win_effect,
            'closed_cost_amount_saving_bps_signed': -closed['cost_bps'],
            'cost_saving_already_in_net_sign_bridge': True,
            'position_contributions': rows, 'parity': 'PASS', 'basis': BASIS}


def weighted_window(unit_window, weights, daily, observations=None):
    positions = []
    for original in unit_window['position_contributions']:
        key = original['origin_key']
        observation = (observations or {}).get(key, {})
        row = {'origin_key': key, 'symbol': original['symbol'], 'entry_weight': weights[key],
               'entry_ts': original['entry_ts'],
               'entry_before_window': original['entry_ts'] < unit_window['window_start_ms'],
               'weight_available_at': observation.get('available_at') if isinstance(observation, dict) else None,
               'unit_contribution': deepcopy(original)}
        for phase in ('start', 'end', 'delta'):
            row[phase] = {field: weights[key] * original[phase][field] for field in VALUE_FIELDS}
        positions.append(row)
    totals = {phase: {field: sum(row[phase][field] for row in positions) for field in VALUE_FIELDS}
              for phase in ('start', 'end', 'delta')}
    left, right = unit_window['window_start_ms'], unit_window['window_end_ms']
    selected = [row for row in daily if left < row['mark_ts'] <= right]
    _same(totals['delta']['net_bps'], sum(row['value'] for row in selected), 'WEIGHTED_WINDOW_DAILY_BRIDGE')
    _same(totals['delta']['cost2x_net_bps'], sum(row['cost2x_net_delta_bps'] for row in selected), 'WEIGHTED_WINDOW_COST2_BRIDGE')
    return {'totals': totals, 'position_contributions': positions, 'parity': 'PASS',
            'basis': 'ORIGINAL_PINNED_CALENDAR_BOUNDARIES; NOT_DIFFERENT_EXTREMA_ATTRIBUTION'}


def build(trades, opened, events, rows_by_symbol, costs, policy, symbols, start, end,
          weights, pinned_windows=()):
    """Compute one A/B/C accounting comparison after the caller's prereg freeze.

    ``weights`` maps source keys to either positive scalars or precomputed causal
    observation dicts containing ``weight``. Window labels are original Q0
    outcome-derived analysis labels only and never influence these weights.
    """
    if end <= start or start % DAY or end % DAY or policy['development_interval_ms'] != [start, end]:
        raise ValueError('INVALID_DAILY_EVALUATION_CALENDAR')
    items = bridge._index(trades, opened)
    w = _weights(items, weights)
    for status, row in items.values():
        bridge._values((status, row))
        if row['side'] != 'long' or not math.isfinite(row['entry_price']) or row['entry_price'] <= 0:
            raise ValueError('INVALID_OR_UNSUPPORTED_UNIT_ENTRY_PRICE_OR_SIDE')
        if status == 'O' and row['mark_ts'] != end:
            raise ValueError('OPEN_POSITION_MUST_REMAIN_MARKED_AT_TERMINAL_BOUNDARY')
    unit_metrics = shared.summarize(trades, opened, events, policy, symbols)
    k = control_weight(trades, opened, w)
    unit_daily, paths = _daily_inputs(trades, opened, rows_by_symbol, costs, start, end)
    all_weights = {'A_Q0': dict.fromkeys(items, 1.0), 'C_FIXED': dict.fromkeys(items, k), 'B_RISK': w}
    stages = {}
    for name, allocation in all_weights.items():
        ts, os = weighted_copies(trades, opened, allocation)
        for row in ts:
            row['_accounting_weight'] = allocation[ORIGIN(row)]
        exp = exposure(trades, opened, allocation, start, end)
        daily = weighted_daily(unit_daily, paths, allocation)
        m = _metrics(trades, opened, ts, os, events, policy, symbols, exp)
        _same(daily[-1]['cumulative_net_mark_bps'], m['terminal_net_amount_bps'], 'WEIGHTED_TERMINAL_NET_PARITY')
        _same(daily[-1]['cumulative_cost2x_net_mark_bps'], m['terminal_cost2x_net_amount_bps'], 'WEIGHTED_TERMINAL_COST2_PARITY')
        monthly, by_symbol = _period_paths(daily, paths, items, allocation)
        marked = shared.daily_mark_diagnostics(daily)
        marked['basis'] = BASIS + '; DAILY_FULL_COST_MARKS_NOT_ACCOUNT_MDD'
        diag = shared.diagnostics(ts, start, end)
        diag['basis'] = BASIS + '; RECOMPUTED_SIMULTANEOUS_EXIT_GROUPS'
        dd = marked['marked_DD_trade_sum_bps']
        daily_sd = statistics.stdev(row['value'] for row in daily) if len(daily) > 1 else None
        observation = weights if name == 'B_RISK' else {key: {'weight': value, 'basis': 'ORIGINAL_Q0' if name == 'A_Q0' else 'EX_POST_EXPOSURE_NORMALIZATION_ANALYSIS_ONLY'} for key, value in allocation.items()}
        stages[name] = {'metrics': m, 'diagnostics': diag, 'marked_diagnostics': marked, 'exposure': exp,
                        'daily': daily, 'ledger': _public_ledger(trades, opened, allocation, observation),
                        'by_mark_month': monthly, 'by_symbol_marked': by_symbol,
                        'original_profit_retention': _retention(trades, allocation),
                        'group_sign_changes_from_Q0': _group_changes(trades, ts),
                        'descriptive_ratios': {
                            'terminal_net_per_nominal_weighted_day': m['terminal_net_amount_bps'] / exp['nominal_weighted_position_days'],
                            'terminal_net_to_marked_DD': m['terminal_net_amount_bps'] / dd if dd else None,
                            'daily_marked_amount_sample_sd': daily_sd,
                            'mean_daily_marked_amount_to_sample_sd': statistics.mean(row['value'] for row in daily) / daily_sd if daily_sd else None,
                            'annualization_or_account_Sharpe_claimed': False}}
    _same(stages['B_RISK']['exposure']['nominal_weighted_position_days'],
          stages['C_FIXED']['exposure']['nominal_weighted_position_days'], 'CONTROL_AVERAGE_EXPOSURE_PARITY')
    for field in unit_metrics['base_cost']:
        if field in stages['A_Q0']['metrics']['base_cost'] and isinstance(unit_metrics['base_cost'][field], (int, float)):
            _same(unit_metrics['base_cost'][field], stages['A_Q0']['metrics']['base_cost'][field], 'Q0_UNIT_METRIC_BASELINE_PARITY:' + field)
    windows = []
    for window in pinned_windows:
        unit = bridge.window_contributions(trades, opened, rows_by_symbol, costs, start, end,
                                           window['start_ms'], window['end_ms'], daily=unit_daily)
        windows.append({**deepcopy(window), 'stages': {
            name: weighted_window(unit, allocation, stages[name]['daily'], weights if name == 'B_RISK' else None)
            for name, allocation in all_weights.items()},
            'labels_are_post_outcome_analysis_only': True,
            'overlapping_original_windows_must_not_be_summed_as_disjoint_periods': True})
    return {'unit_metrics': unit_metrics, 'stages': stages,
            'control': {'k': k, 'normalization': 'SUM_B_WEIGHT_TIMES_HOLD_MS_DIVIDED_BY_SUM_A_HOLD_MS',
                        'ex_post_analysis_only': True, 'executable_strategy': False,
                        'fed_back_to_candidate_weights_or_reference_volatility': False},
            'windows': windows,
            'attribution': {'B_minus_A': attribution(trades, opened, all_weights['A_Q0'], w),
                            'B_minus_C': attribution(trades, opened, all_weights['C_FIXED'], w)},
            'uncertainty': shared.paired_daily_uncertainty(stages['C_FIXED']['daily'], stages['B_RISK']['daily'],
                                                        block_days=30, resamples=1000, seed=1178),
            'invariants': {'closed_T': len(trades), 'open_T': len(opened), 'signals_T': len(events),
                           'unit_ledger_and_costs_unchanged': True, 'entry_exit_prices_times_and_occupancy_unchanged': True,
                           'unit_trade_win_rate_and_expectancy_unchanged': True,
                           'no_new_closed_or_removed_positions': True, 'fixed_in_trade_weights': True,
                           'all_weights_positive_at_most_one': True, 'control_average_exposure_parity': 'PASS',
                           'full_unit_roundtrip_cost_floor_bps': 20, 'account_sizing_or_actual_fills_claimed': False,
                           'cost_scope': 'LINEAR_PRICE_TAKER_RESEARCH_MODEL_ONLY; FIXED_MINIMUM_FEES_OR_NONLINEAR_IMPACT_NOT_VALIDATED'}}
