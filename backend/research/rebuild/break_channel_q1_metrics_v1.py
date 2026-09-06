"""Pure Q0/Q1 EXIT_CHANGE accounting; no prices are loaded or candidates run.

Both sides can contain unresolved positions. Same-calendar mark contributions
are descriptive accounting, never execution features or independent trials.
"""
from __future__ import annotations

import math

from backend.research.rebuild import break_channel_metrics_v1 as shared
from backend.research.rebuild import break_channel_source_v1 as source

DAY = shared.DAY
COST_FIELDS = shared.COST_FIELDS
VALUE_FIELDS = ('gross_bps', 'net_bps', 'cost2x_net_bps', 'cost_bps', *COST_FIELDS)
GROUPS = ('CC', 'CO', 'OC', 'OO', 'removed_C', 'removed_O', 'new_C', 'new_O')
ORIGIN = source.prior.previous.source_key


def _same(actual, expected, label):
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-7):
        raise RuntimeError(label)


def _index(closed, opened):
    result = {}
    for status, rows in (('C', closed), ('O', opened)):
        for row in rows:
            key = ORIGIN(row)
            if key in result:
                raise RuntimeError('DUPLICATE_OR_RESOLVED_CENSORED_ORIGIN')
            result[key] = (status, row)
    return result


def _values(item, *, closed_only=False):
    if item is None or (closed_only and item[0] == 'O'):
        return dict.fromkeys(VALUE_FIELDS, 0.0)
    status, row = item
    if status == 'C':
        result = {field: row[field] for field in VALUE_FIELDS}
    else:
        result = {
            'gross_bps': row['gross_mark_bps'],
            'net_bps': row['hypothetical_liquidation_net_mark_bps'],
            'cost2x_net_bps': row['hypothetical_liquidation_cost2x_net_mark_bps'],
            'cost_bps': row['hypothetical_liquidation_cost_bps'],
            **{field: row['hypothetical_cost_components_bps'][field] for field in COST_FIELDS},
        }
    if any(not math.isfinite(value) for value in result.values()):
        raise RuntimeError('NONFINITE_ACCOUNTING_VALUE')
    _same(result['gross_bps'] - result['cost_bps'], result['net_bps'], 'NET_COST_IDENTITY')
    _same(result['gross_bps'] - 2 * result['cost_bps'], result['cost2x_net_bps'], 'COST2_IDENTITY')
    _same(sum(result[field] for field in COST_FIELDS), result['cost_bps'], 'COST_COMPONENT_IDENTITY')
    return result


def _totals(items, *, closed_only=False):
    rows = [_values(item, closed_only=closed_only) for item in items]
    return {field: sum(row[field] for row in rows) for field in VALUE_FIELDS}


def symmetric_attribution(parent_closed, parent_open, child_closed, child_open):
    """Origin bridges include CC/CO/OC/OO without treating censoring as absence.

    C means completed, O means still open at the shared terminal boundary.
    Retention bounds concern capped profit of *completed parent winners* only;
    parent open marks cannot become retrospective winner labels.
    """
    p = _index(parent_closed, parent_open)
    c = _index(child_closed, child_open)
    groups = {name: [] for name in GROUPS}
    for key in sorted(p.keys() | c.keys()):
        name = (p[key][0] + c[key][0] if key in p and key in c
                else 'removed_' + p[key][0] if key in p else 'new_' + c[key][0])
        groups[name].append(key)
    details = {}
    for name, keys in groups.items():
        pp, cc = [p.get(key) for key in keys], [c.get(key) for key in keys]
        value = {'T': len(keys), 'origins': keys}
        for basis, closed_only in (('closed', True), ('marked', False)):
            pv = _totals(pp, closed_only=closed_only)
            cv = _totals(cc, closed_only=closed_only)
            value[basis] = {'parent': pv, 'child': cv,
                            'delta': {field: cv[field] - pv[field] for field in VALUE_FIELDS}}
        details[name] = value
    bridges = {}
    for basis, closed_only in (('closed', True), ('marked', False)):
        pv = _totals([p[key] for key in sorted(p)], closed_only=closed_only)
        cv = _totals([c[key] for key in sorted(c)], closed_only=closed_only)
        delta = {field: cv[field] - pv[field] for field in VALUE_FIELDS}
        components = {field: sum(value[basis]['delta'][field] for value in details.values())
                      for field in VALUE_FIELDS}
        for field in VALUE_FIELDS:
            _same(delta[field], components[field], basis.upper() + '_ORIGIN_BRIDGE:' + field)
        _same(delta['net_bps'], delta['gross_bps'] - delta['cost_bps'], basis.upper() + '_GROSS_COST_BRIDGE')
        bridges[basis] = {'parent': pv, 'child': cv, 'delta': delta,
                          'sum_group_contributions': components, 'parity': 'PASS'}
    result = {
        'comparison_type': 'EXIT_CHANGE', 'matching_basis': 'LANE_SYMBOL_SIGNAL_TS_SIDE',
        'groups': details, 'counts': {name: len(keys) for name, keys in groups.items()},
        'bridges': bridges,
        'closed_net_delta_bps': bridges['closed']['delta']['net_bps'],
        'marked_delta_bps_not_realized': bridges['marked']['delta']['net_bps'],
        'closed_cost_delta_bps': bridges['closed']['delta']['cost_bps'],
        'closed_funding_delta_bps': bridges['closed']['delta']['funding_bps'],
        'common_closed_cost_delta_bps': details['CC']['closed']['delta']['cost_bps'],
        'common_closed_funding_delta_bps': details['CC']['closed']['delta']['funding_bps'],
        'removed_completed_parent_loss_bps': -sum(min(0, p[k][1]['net_bps']) for k in groups['removed_C']),
        'removed_completed_parent_winner_bps': sum(max(0, p[k][1]['net_bps']) for k in groups['removed_C']),
        'new_completed_net_bps': details['new_C']['closed']['child']['net_bps'],
        'parent_open_T': len(parent_open), 'child_open_T': len(child_open),
        'censor_semantics': 'COMMON_OPEN_IS_PRESENT; MARKS_ARE_HYPOTHETICAL_NOT_REALIZED; PARENT_OPEN_NOT_WINNER_LABEL',
        'account_return_claimed': False,
    }
    # This immutable helper is valid only for the common, completed pair.
    result['resolved_common_effects'] = source.prior.previous.attribute(
        [p[k][1] for k in groups['CC']], [c[k][1] for k in groups['CC']])
    winners = sorted((k for k in p if p[k][0] == 'C' and p[k][1]['net_bps'] > 0),
                     key=lambda k: (-p[k][1]['net_bps'], k))
    for label, keys in (('winner', winners), ('large_winner', winners[:math.ceil(len(winners) * .1)])):
        total = sum(p[k][1]['net_bps'] for k in keys)
        retained = sum(min(p[k][1]['net_bps'], max(0, c[k][1]['net_bps']))
                       for k in keys if k in c and c[k][0] == 'C')
        uncertain = sum(p[k][1]['net_bps'] for k in keys if k in c and c[k][0] == 'O')
        marked = retained + sum(min(p[k][1]['net_bps'], max(0, c[k][1]['hypothetical_liquidation_net_mark_bps']))
                                for k in keys if k in c and c[k][0] == 'O')
        result[label] = {
            'parent_T': len(keys), 'parent_positive_bps': total, 'origins': keys,
            'resolved_preserved_bps': retained, 'unresolved_parent_positive_bps': uncertain,
            'amount_retention_lower': retained / total if total else None,
            'amount_retention_upper': (retained + uncertain) / total if total else None,
            'hypothetical_mark_capped_retention': marked / total if total else None,
            'parent_open_positions_excluded_from_winner_labels_T': len(parent_open),
            'bound_semantics': 'CAPPED_ORIGINAL_COMPLETED_PROFIT; NOT_BOUNDS_ON_FUTURE_TOTAL_PNL',
        }
    return result


def window_contributions(trades, opened, rows_by_symbol, costs, evaluation_start,
                         evaluation_end, window_start, window_end, *, daily=None):
    """Attribute changes over one frozen calendar window, not two local maxima.

    Match source.daily_valuation: initial zero before entries; intermediate marks
    after same-time open orders; terminal mark at the final close. Per-position
    mark differences sum to aggregate marked changes on those same boundaries.
    """
    if (evaluation_end <= evaluation_start or not evaluation_start <= window_start < window_end <= evaluation_end
            or any(ts % DAY for ts in (evaluation_start, evaluation_end, window_start, window_end))):
        raise ValueError('INVALID_OR_NONDAILY_WINDOW')
    items = _index(trades, opened)
    prices = {s: {r['bar_close_ts']: r['close'] for r in rows
                  if evaluation_start < r['bar_close_ts'] <= evaluation_end}
              for s, rows in rows_by_symbol.items()}
    for symbol, rows in rows_by_symbol.items():
        prices[symbol].update({r['bar_open_ts']: r['open'] for r in rows
                               if evaluation_start < r['bar_open_ts'] < evaluation_end})

    def boundary(item, ts):
        status, trade = item
        _values(item)  # Check stored final economics independently of mark recomputation.
        terminal = trade['exit_ts'] if status == 'C' else trade['mark_ts']
        if (trade['side'] != 'long' or not evaluation_start <= trade['entry_ts'] <= terminal <= evaluation_end
                or (status == 'O' and terminal != evaluation_end)):
            raise ValueError('UNSUPPORTED_SIDE_OR_POSITION_CALENDAR')
        if ts == evaluation_start or trade['entry_ts'] > ts:
            return {'state': 'INITIAL_PRE_ENTRY_BASELINE' if ts == evaluation_start else 'NOT_ENTERED',
                    **dict.fromkeys(VALUE_FIELDS, 0.0)}
        if status == 'C' and trade['exit_ts'] <= ts:
            return {'state': 'COMPLETED', **_values(item)}
        px = prices.get(trade['symbol'], {}).get(ts)
        if px is None:
            raise RuntimeError('MISSING_DAILY_VALUATION_PRICE')
        if not math.isfinite(px) or px <= 0 or not math.isfinite(trade['entry_price']) or trade['entry_price'] <= 0:
            raise RuntimeError('INVALID_VALUATION_PRICE')
        gross = (px / trade['entry_price'] - 1) * 10000
        parts = source.old.probe.cost_components(trade['entry_ts'], ts, costs[trade['symbol']])
        parts['frozen_floor_reserve_bps'] = max(0.0, 20.0 - parts['cost_bps'])
        cost = max(20.0, parts['cost_bps'])
        result = {'state': 'OPEN_AT_BOUNDARY', 'mark_price': px,
                  'gross_bps': gross, 'net_bps': gross - cost, 'cost2x_net_bps': gross - 2 * cost,
                  'cost_bps': cost, **{field: parts[field] for field in COST_FIELDS}}
        if status == 'O' and ts == evaluation_end:
            final = _values(item)
            for field in VALUE_FIELDS:
                _same(result[field], final[field], 'TERMINAL_OPEN_MARK_PARITY:' + field)
        return result

    contributions = []
    for key in sorted(items):
        item = items[key]
        a, b = boundary(item, window_start), boundary(item, window_end)
        contributions.append({'origin_key': key, 'symbol': item[1]['symbol'],
            'signal_ts': item[1]['signal_ts'], 'entry_ts': item[1]['entry_ts'],
            'terminal_status': item[0], 'start': a, 'end': b,
            'delta': {field: b[field] - a[field] for field in VALUE_FIELDS}})
    totals = {phase: {field: sum(t[phase][field] for t in contributions) for field in VALUE_FIELDS}
              for phase in ('start', 'end', 'delta')}
    aggregate = (source.daily_valuation(trades, opened, rows_by_symbol, costs, evaluation_start, evaluation_end)
                 if daily is None else daily)
    by_ts = {row['mark_ts']: row for row in aggregate}
    if len(by_ts) != len(aggregate) or sorted(by_ts) != list(range(evaluation_start + DAY, evaluation_end + 1, DAY)):
        raise RuntimeError('DAILY_BRIDGE_CALENDAR_MISMATCH')
    field_map = {'gross_bps': 'cumulative_gross_mark_bps', 'net_bps': 'cumulative_net_mark_bps',
                 'cost_bps': 'full_cost_bps_at_valuation', 'funding_bps': 'modeled_funding_bps_at_valuation'}
    bridge = {}
    for field, daily_field in field_map.items():
        a = 0.0 if window_start == evaluation_start else by_ts[window_start][daily_field]
        b = by_ts[window_end][daily_field]
        _same(totals['start'][field], a, 'DAILY_WINDOW_START_BRIDGE:' + field)
        _same(totals['end'][field], b, 'DAILY_WINDOW_END_BRIDGE:' + field)
        _same(totals['delta'][field], b - a, 'DAILY_WINDOW_DELTA_BRIDGE:' + field)
        bridge[field] = b - a
    delta_sum = sum(row['value'] for row in aggregate if window_start < row['mark_ts'] <= window_end)
    _same(totals['delta']['net_bps'], delta_sum, 'DAILY_WINDOW_INCREMENT_BRIDGE')
    _same(totals['delta']['net_bps'], totals['delta']['gross_bps'] - totals['delta']['cost_bps'], 'WINDOW_GROSS_COST_BRIDGE')
    return {
        'window_start_ms': window_start, 'window_end_ms': window_end,
        'evaluation_interval_ms': [evaluation_start, evaluation_end],
        'position_contributions': contributions, 'totals': totals,
        'daily_bridge_delta': bridge, 'daily_net_increment_sum_bps': delta_sum,
        'parity': 'PASS', 'account_return_claimed': False,
        'basis': 'SAME_CALENDAR_BOUNDARY_MARK_DIFFERENCES; FULL_ROUNDTRIP_COST_MARKS; NOT_LOCAL_MAXIMA_DIFFERENCE',
        'initial_phase': 'ZERO_PRE_ENTRY_BASELINE', 'intermediate_phase': 'AFTER_OPEN_ORDERS',
        'terminal_phase': 'FINAL_CLOSE_NO_FUTURE_OPEN',
    }
