"""Pure accounting of sealed exit ledgers; never a replay or policy feature.

Streak maxima can occur over different calendar windows. Their differences are
not additive causal attribution. The bridges below compare identical windows,
retain every original exit timestamp and net simultaneous closes before testing
the sign of a group, exactly as the existing development diagnostics do.
"""
from collections import defaultdict
from datetime import datetime, timezone
from math import fsum, isfinite

from backend.research.rebuild import top5_external_metrics_v1 as diagnostics

TOLERANCE_BPS = 1e-7
ENTRY_FIELDS = ('lane_id', 'symbol', 'signal_ts', 'entry_ts', 'side')


def _entry(t):
    return tuple(t[k] for k in ENTRY_FIELDS)


def _iso(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()


def _index(trades):
    result = {}
    identities = set()
    for t in trades:
        k = _entry(t)
        if k in result or t['identity'] in identities:
            raise RuntimeError('RISK_AUDIT_DUPLICATE_ENTRY_OR_IDENTITY')
        if not isfinite(t['net_bps']) or t['exit_ts'] < t['entry_ts']:
            raise RuntimeError('RISK_AUDIT_INVALID_SEALED_TRADE')
        result[k] = t
        identities.add(t['identity'])
    return result


def _ref(t):
    return {**{k: t[k] for k in ENTRY_FIELDS}, 'identity': t['identity'],
            'exit_ts': t['exit_ts'], 'net_bps': t['net_bps']}


def _groups(trades):
    result = defaultdict(list)
    for t in trades:
        result[t['exit_ts']].append(t)
    # Keep the sealed ledger's within-timestamp order, including its floating
    # summation order, exactly as diagnostics.grouped does.
    return dict(sorted(result.items()))


def _group(ts, trades):
    return {'exit_ts': ts, 'utc': _iso(ts), 'T': len(trades),
            'net_trade_sum_bps': sum(t['net_bps'] for t in trades),
            'negative_trade_loss_bps': -fsum(min(0., t['net_bps']) for t in trades),
            'winner_offset_bps': fsum(max(0., t['net_bps']) for t in trades),
            'loss_T': sum(t['net_bps'] < 0 for t in trades),
            'win_T': sum(t['net_bps'] > 0 for t in trades),
            'trades': [_ref(t) for t in trades]}


def _run(groups):
    return {'start_ms': groups[0]['exit_ts'], 'end_ms': groups[-1]['exit_ts'],
            'start_utc': groups[0]['utc'], 'end_utc': groups[-1]['utc'],
            'length_groups': len(groups), 'T': sum(g['T'] for g in groups),
            'loss_trade_sum_bps': -fsum(g['net_trade_sum_bps'] for g in groups),
            'negative_trade_loss_bps': fsum(g['negative_trade_loss_bps'] for g in groups),
            'winner_offset_bps': fsum(g['winner_offset_bps'] for g in groups),
            'simultaneous_groups': sum(g['T'] > 1 for g in groups),
            'group_exit_timestamps': [g['exit_ts'] for g in groups]}


def population(trades):
    """All actual close groups and negative runs, including an unfinished run."""
    _index(trades)
    groups = [_group(ts, rows) for ts, rows in _groups(trades).items()]
    runs = []; current = []
    for group in groups:
        # Existing owner uses ordinary sum to determine sign. Preserve it even
        # in the pathological case of near-zero cancellation across symbols.
        sign_net = sum(t['net_bps'] for t in group['trades'])
        if sign_net < 0:
            current.append(group)
        elif current:
            runs.append(_run(current)); current = []
    if current:
        runs.append(_run(current))
    worst = max(runs, key=lambda r: r['loss_trade_sum_bps'], default=None)
    longest = max(runs, key=lambda r: r['length_groups'], default=None)
    existing, _ = diagnostics.streaks(diagnostics.grouped(trades))
    if abs((worst['loss_trade_sum_bps'] if worst else 0.) - existing['max_loss_trade_sum_bps']) > TOLERANCE_BPS:
        raise RuntimeError('RISK_AUDIT_EXISTING_STREAK_AMOUNT_PARITY')
    if (longest['length_groups'] if longest else 0) != existing['max_length_groups']:
        raise RuntimeError('RISK_AUDIT_EXISTING_STREAK_LENGTH_PARITY')
    return {'groups': groups, 'negative_runs': runs, 'worst_amount_run': worst,
            'longest_run': longest, 'existing_diagnostics_parity': 'PASS'}


def bridge(parent, child, start_ms=None, end_ms=None):
    """Additive accounting at original close times; no synthetic policy replay.

    I denotes the actual close falling inside the inclusive calendar window.
    Common amount = (child_net-parent_net)*I_child.
    Common timing = parent_net*(I_child-I_parent).
    New = child_net*I_child; excluded = -parent_net*I_parent.
    Summing these terms must equal child window net minus parent window net.
    """
    p = _index(parent); c = _index(child)
    common = sorted(p.keys() & c.keys())
    removed = sorted(p.keys() - c.keys()); new = sorted(c.keys() - p.keys())
    def inside(t):
        return (start_ms is None or start_ms <= t['exit_ts']) and (end_ms is None or t['exit_ts'] <= end_ms)
    amount = fsum((c[k]['net_bps'] - p[k]['net_bps']) * inside(c[k]) for k in common)
    timing = fsum(p[k]['net_bps'] * (int(inside(c[k])) - int(inside(p[k]))) for k in common)
    new_net = fsum(c[k]['net_bps'] for k in new if inside(c[k]))
    excluded = -fsum(p[k]['net_bps'] for k in removed if inside(p[k]))
    p_net = fsum(t['net_bps'] for t in parent if inside(t))
    c_net = fsum(t['net_bps'] for t in child if inside(t))
    residual = c_net - p_net - fsum((amount, timing, new_net, excluded))
    if abs(residual) > TOLERANCE_BPS:
        raise RuntimeError('RISK_AUDIT_SAME_WINDOW_ATTRIBUTION_PARITY')
    return {'scope': 'DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY',
            'start_ms': start_ms, 'end_ms': end_ms,
            'parent_closed_T': sum(inside(t) for t in parent),
            'child_closed_T': sum(inside(t) for t in child),
            'parent_net_bps': p_net, 'child_net_bps': c_net,
            'net_delta_bps': c_net - p_net,
            'common_exit_amount_change_at_child_close_bps': amount,
            'common_parent_net_timing_shift_bps': timing,
            'new_trade_net_bps': new_net, 'excluded_parent_net_effect_bps': excluded,
            'common_child_inside_T': sum(inside(c[k]) for k in common),
            'common_parent_inside_T': sum(inside(p[k]) for k in common),
            'new_inside_T': sum(inside(c[k]) for k in new),
            'excluded_inside_T': sum(inside(p[k]) for k in removed),
            'parity_residual_bps': residual, 'parity': 'PASS'}


def _resets(reference, child, start, end):
    rg = _groups(reference); cg = _groups(child); ci = _index(child)
    ri = _index(reference); out = []
    for ts, rows in rg.items():
        if not start <= ts <= end or sum(t['net_bps'] for t in rows) < 0:
            continue
        others = cg.get(ts, [])
        if others and sum(t['net_bps'] for t in others) >= 0:
            continue
        out.append({'original_reset_group': _group(ts, rows),
                    'child_same_timestamp_group': _group(ts, others),
                    'observation': 'NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME' if not others else 'NONNEGATIVE_RESET_ABSENT_AFTER_ACTUAL_SIMULTANEOUS_NETTING',
                    'reference_reset_kind': 'ZERO_NET_RESET' if sum(t['net_bps'] for t in rows) == 0 else 'POSITIVE_NET_RESET',
                    'same_timestamp_accounting_only': True,
                    'reference_entry_actual_child_outcomes': [
                        {'reference': _ref(t), 'child': _ref(ci[_entry(t)]) if _entry(t) in ci else None}
                        for t in rows],
                    'new_same_timestamp_trades': [_ref(t) for t in others if _entry(t) not in ri]})
    return out


def build(parent, fixed, full):
    """Analyze three sealed populations without re-executing the exit overlay."""
    pops = {'parent': parent, 'fixed': fixed, 'full': full}
    indexed = {n: _index(ts) for n, ts in pops.items()}
    if indexed['parent'].keys() != indexed['fixed'].keys():
        raise RuntimeError('RISK_AUDIT_FIXED_ENTRY_POPULATION_DRIFT')
    summaries = {n: population(ts) for n, ts in pops.items()}
    selected = []
    for name, summary in summaries.items():
        if summary['worst_amount_run'] is not None:
            run = summary['worst_amount_run']
            selected.append({'sources': [name], 'start_ms': run['start_ms'], 'end_ms': run['end_ms']})
    unions = []
    for w in sorted(selected, key=lambda w: (w['start_ms'], w['end_ms'])):
        if unions and w['start_ms'] <= unions[-1]['end_ms']:
            unions[-1]['end_ms'] = max(unions[-1]['end_ms'], w['end_ms'])
            unions[-1]['sources'].extend(w['sources'])
        else:
            unions.append({**w, 'sources': list(w['sources'])})
    pairs = {'fixed_minus_parent': (parent, fixed), 'full_minus_parent': (parent, full), 'full_minus_fixed': (fixed, full)}
    def window(w):
        start, end = w['start_ms'], w['end_ms']
        times = sorted({t['exit_ts'] for ts in pops.values() for t in ts if start <= t['exit_ts'] <= end})
        return {**w, 'start_utc': _iso(start), 'end_utc': _iso(end),
                'bridges': {n: bridge(a, b, start, end) for n, (a, b) in pairs.items()},
                'all_actual_close_group_timestamps': times,
                'group_bridges': [{'exit_ts': ts, 'utc': _iso(ts),
                                   'bridges': {n: bridge(a, b, ts, ts) for n, (a, b) in pairs.items()}}
                                  for ts in times],
                'nonnegative_reset_observations': {n: _resets(a, b, start, end) for n, (a, b) in pairs.items()}}
    return {'scope': 'SEALED_DEVELOPMENT_LEDGER_ACCOUNTING_ONLY',
            'basis': 'SIMULTANEOUS_EXIT_GROUP_NET; TRADE_BPS_SUM_NOT_ACCOUNT_RETURN',
            'maxima_difference_is_not_additive_causal_attribution': True,
            'original_trade_identities_and_timestamps_preserved': True,
            'new_replay_executed': False,
            'populations': summaries,
            'whole_development_bridges': {n: bridge(a, b) for n, (a, b) in pairs.items()},
            'selected_worst_windows': [window(w) for w in selected],
            'union_windows': [window(w) for w in unions],
            'parity': 'PASS'}
