"""Complete research comparison for the already-approved signal-low successor.

No new strategy identity, workflow, market API, parameter search or trading path.
The caller owns the existing approval, Keltner-before-Squeeze ordering and global
heavy lock. Default CLI mode only scans saved trades. Full mode executes the NEW
successor once; the rejected predecessor is NEVER replayed. Historical results
are development observations, not fresh evidence, account NAV or promotion.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from ops import scalp7_squeeze_signal_low_successor_v1 as policy

START, END, DAY = 1768262400000, 1789430400000, 86_400_000
SYMBOLS = {'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'DOGE-USDT', 'LINK-USDT', 'XRP-USDT'}
PINS = {
    'backend/research/rebuild/scalp7_execution_v2.py':
        'd1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1',
    'backend/research/rebuild/scalp7_positive_lanes_v2.py':
        'b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2',
    'ops/scalp7_squeeze_signal_low_successor_v1.py':
        '43895f24753b2325a908c546cc87a9d6c1b47f9c0856000e01376e0422613bcd',
    'research/campaigns/scalp7_20261013/dual_streak_v1/streak_successor_policies.py':
        '7d555b1bd18edd15ecdd90d8e1fbde47ccd45d4049680d3c8da2a1df579de790',
    'ops/scalp7_squeeze_regime_overlay_child_v1.py':
        'df6c3976d3a78f4ef2f9daff6cf4342eea9f6562abb7818fb9d39241ad8a8813',
}


def digest(value: Any) -> str:
    return hashlib.sha256((json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False) + '\n').encode()).hexdigest()


def key(row: Mapping[str, Any]) -> tuple[str, int, int]:
    return (str(row['symbol']), int(row['signal_ts_ms']), int(row['signal_open_ts_ms']))


def net(row: Mapping[str, Any], multiplier: float) -> float:
    gross, cost = float(row['gross_bps']), float(row['cost_bps'])
    if not math.isfinite(gross) or not math.isfinite(cost) or cost <= 0:
        raise ValueError('FINITE_GROSS_AND_POSITIVE_COST_REQUIRED')
    return gross - multiplier * cost


def saved_overlay(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    unsigned = dict(report)
    receipt = unsigned.pop('receipt_sha256', None)
    if receipt != policy.SAVED_RECEIPT or digest(unsigned) != policy.SAVED_RECEIPT:
        raise ValueError('SAVED_SQUEEZE_RECEIPT_MISMATCH')
    if (report['child_identity'] != policy.SAVED_OVERLAY or
            report['source_inventory_sha256'] != policy.INVENTORY):
        raise ValueError('SAVED_SQUEEZE_IDENTITY_OR_SOURCE_DRIFT')
    rows = report['trade_rows']
    if len(rows) != 57 or len({key(r) for r in rows}) != 57:
        raise ValueError('SAVED_SQUEEZE_T_OR_KEY_MISMATCH')
    for r in rows:
        if r['partition'] != 'rolling' or not START <= int(r['signal_ts_ms']) < END:
            raise ValueError('SAVED_SQUEEZE_WINDOW_DRIFT')
        if int(r['outcome_available_ts_ms']) >= END:
            raise ValueError('SAVED_SQUEEZE_UNAVAILABLE_OUTCOME')
        if not math.isclose(net(r, 1), float(r['net_bps']), rel_tol=0, abs_tol=1e-9):
            raise ValueError('SAVED_SQUEEZE_ARITHMETIC_MISMATCH')
    return deepcopy(rows)


def _label(value: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(value)
    out['identity'] = policy.SQUEEZE_SUCCESSOR
    for sig in (out.get('signal'), out.get('position', {}).get('signal')):
        if isinstance(sig, dict):
            sig['identity'] = policy.SQUEEZE_SUCCESSOR
            sig.setdefault('meta', {})['lifecycle_adapter_parent_identity'] = positive.SQUEEZE_PARENT
    return out


def _pending_stop_priority(row, until, signal, records, indexes, active_stop):
    """Resolve stop-at-next-open at that open, never in the prior-close callback.

    The frozen engine handles a pending market exit before a next-bar stop. This
    narrow adapter restores the successor's explicitly required existing-stop
    priority WITHOUT touching the frozen engine, changing prices, or looking at a
    future low. Only next OPEN and the active stop after callback updates are used.
    Its conservative release clock matches the original stop-first engine.
    """
    if row is None or row['reason'] != policy.EXIT_REASON:
        return row, until, None
    bar = records[indexes[int(row['exit_ts_ms'])]]
    # Use the position's actual stop after the last callback update, not a
    # reconstruction of the INITIAL admission geometry.
    stop, opening = float(active_stop), float(bar['open'])
    if not math.isfinite(stop) or stop <= 0:
        raise ValueError('ACTIVE_PENDING_EXIT_STOP_REQUIRED')
    if opening > stop:
        return row, until, None
    out = deepcopy(row)
    gap = opening < stop
    out['reason'] = 'OPEN_GAP_STOP' if gap else 'STOP_FIRST'
    out['exit_ts_ms'] = int(bar['open_ts_ms'] if gap else bar['close_ts_ms'])
    out['outcome_available_ts_ms'] = int(bar['open_ts_ms'] if gap else bar['available_ts_ms'])
    out['outcome_time_precision'] = ('BAR_CLOSE' if out['outcome_available_ts_ms'] > out['exit_ts_ms'] else 'OPEN')
    out['hold_bars'] += 1
    out['hold_minutes'] = (out['exit_ts_ms'] - out['entry_ts_ms']) / 60_000
    until = max(int(bar['close_ts_ms']), int(bar['available_ts_ms']))
    return out, until, {
        'symbol': signal['symbol'], 'signal_ts_ms': int(signal['signal_ts_ms']),
        'at_open_ms': int(bar['open_ts_ms']), 'frozen_stop': stop,
        'actual_open': opening, 'winner': out['reason'],
        'price_changed': False, 'ownership_released_at_ms': until,
    }


def replay_successor(signals, frames, costs, windows) -> dict[str, Any]:
    """All potential opportunities, chronological occupancy, native exact fills.

    Windows deliberately retain the parent's independent, flat-start semantics.
    Bars beyond end-exclusive are never borrowed for a synthetic fill. A gap or
    missing next bar keeps the native unresolved position and its ownership.
    """
    observed = set()
    for s in signals:
        execution.validate_signal(s)
        if (s['identity'] != positive.SQUEEZE_PARENT or s['side'] != 1 or
                s['timeframe_min'] != 30 or s.get('legs') or
                s['meta']['regime'] not in {'PANIC_DISPERSION', 'TREND_DISPERSED'}):
            raise ValueError('EXACT_SQUEEZE_CALLBACK_IDENTITY_REQUIRED')
        if key(s) in observed:
            raise ValueError('DUPLICATE_OPPORTUNITY')
        observed.add(key(s))
    labels = [w['label'] for w in windows]
    if len(set(labels)) != len(labels):
        raise ValueError('DUPLICATE_WINDOW')
    ordered = sorted(windows, key=lambda w: int(w['start_ms']))
    if any(int(w['start_ms']) >= int(w['end_ms']) for w in ordered):
        raise ValueError('INVALID_WINDOW')
    if any(int(a['end_ms']) > int(b['start_ms']) for a, b in zip(ordered, ordered[1:])):
        raise ValueError('OVERLAPPING_WINDOWS')
    trades, unresolved, censored, decisions, traces, stop_arbitrations = [], [], [], [], [], []
    partitions = {}
    for w in ordered:
        start, end = int(w['start_ms']), int(w['end_ms'])
        prepared = {}
        for symbol, f in frames.items():
            f = f[(f.open_ts_ms >= start - 200 * positive.TIMEFRAME_MS) &
                  (f.close_ts_ms <= end)].reset_index(drop=True)
            records, indexes = execution._frame_records(f, 30)
            prepared[symbol] = (f, records, indexes)
        owner_until = {}
        selected = sorted((s for s in signals if start <= int(s['signal_ts_ms']) < end),
                          key=lambda s: (s['signal_ts_ms'], s['identity'], s['symbol'], s['side']))
        counts = Counter(signals=len(selected))
        for original in selected:
            symbol, stamp = str(original['symbol']), int(original['signal_ts_ms'])
            decision = {'window_label': w['label'], 'partition': w['partition'],
                        'symbol': symbol, 'signal_ts_ms': stamp,
                        'signal_open_ts_ms': int(original['signal_open_ts_ms'])}
            if stamp < owner_until.get(symbol, -1):
                decision.update(state='REJECTED', reason='POSITION_ALREADY_OWNED')
                decisions.append(decision); counts['POSITION_ALREADY_OWNED'] += 1
                continue
            f, records, indexes = prepared[symbol]
            # Binding sees only a source bar that was available at this signal.
            # Missing source is an integrity error, not a silently skipped loss.
            s = policy.bind_signal_low(original, f)
            if float(s['meta']['frozen_cost_bps']) != float(costs[symbol]):
                raise ValueError('SIGNAL_COST_SNAPSHOT_DRIFT')
            trace_start = len(traces)
            pending = {}
            def callback(pos, bar, history):
                update = policy.native_exit_update(pos, bar, history, trace=traces)
                if update.get('reason') == policy.EXIT_REASON:
                    pending['active_stop'] = max(float(pos['stop_price']),
                        float(update['next_stop']) if update.get('next_stop') is not None else float(pos['stop_price']))
                return update
            row, opened, until, rejection = execution._single(
                s, f, records, indexes, execution._cost(s, costs), callback,
                positive.entry_update)
            if rejection:
                decision.update(state='REJECTED', reason=rejection)
                decisions.append(decision); counts[rejection] += 1
                continue
            row, until, arbitration = _pending_stop_priority(
                row, until, s, records, indexes, pending.get('active_stop'))
            if arbitration is not None:
                stop_arbitrations.append(dict(arbitration, window_label=w['label']))
            owner_until[symbol] = until
            decision.update(state='ACCEPTED', reason=None, ownership_until_ms=until)
            decision['entry_ts_ms'] = int((row or opened)['entry_ts_ms'])
            decisions.append(decision); counts['accepted'] += 1
            for t in traces[trace_start:]:
                t.update(window_label=w['label'], partition=w['partition'])
            if row is not None:
                value = _label(row)
                value.update(window_label=w['label'], partition=w['partition'])
                if int(value['outcome_available_ts_ms']) >= end:
                    value['boundary_exclusion_reason'] = 'OUTCOME_AT_OR_AFTER_WINDOW_END_UNAVAILABLE'
                    value['window_end_ms'] = end
                    censored.append(value); counts['boundary_excluded'] += 1
                else:
                    trades.append(value); counts['closed'] += 1
            if opened is not None:
                value = _label(opened)
                value.update(window_label=w['label'], partition=w['partition'], window_end_ms=end)
                unresolved.append(value); counts['unresolved'] += 1
        partitions[str(w['label'])] = dict(counts)
    trades.sort(key=lambda r: (r['outcome_available_ts_ms'], r['exit_ts_ms'],
                               r['symbol'], r['identity'], r['signal_ts_ms']))
    return {'trades': trades, 'unresolved': unresolved, 'boundary_excluded': censored,
            'decisions': decisions, 'causal_exit_traces': traces,
            'next_open_stop_arbitrations': stop_arbitrations, 'window_census': partitions,
            'opportunity_keys_sha256': digest(sorted(observed)),
            'old_candidate_replayed': False, 'account_nav_or_mtm': False}


def economic_summary(rows, start_ms, end_ms, multiplier) -> dict[str, Any]:
    if multiplier not in (1.0, 2.0) or end_ms <= start_ms:
        raise ValueError('FROZEN_COST_VIEW_OR_WINDOW_REQUIRED')
    rows = sorted(rows, key=lambda r: (r['outcome_available_ts_ms'], r['exit_ts_ms'],
                                     r['symbol'], r['identity'], r['signal_ts_ms']))
    if len({key(r) for r in rows}) != len(rows):
        raise ValueError('DUPLICATE_LEDGER_KEY')
    if any(not start_ms <= int(r['signal_ts_ms']) < end_ms or
           int(r['outcome_available_ts_ms']) >= end_ms for r in rows):
        raise ValueError('LEDGER_OUTSIDE_AVAILABLE_WINDOW')
    values = [net(r, multiplier) for r in rows]
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    # Serial streaks are observational, not a predictive runtime feature.
    streaks = {'win': [], 'loss': []}
    kind, run = None, []
    for value in values + [0.0]:
        current = 'win' if value > 0 else 'loss' if value < 0 else None
        if current != kind or current is None:
            if run: streaks[kind].append({'length': len(run), 'net_bps': sum(run)})
            kind, run = current, []
        if current: run.append(value)
    cohorts, daily = defaultdict(float), defaultdict(float)
    by_symbol, by_month = defaultdict(float), defaultdict(float)
    for row, value in zip(rows, values):
        cohorts[int(row['outcome_available_ts_ms'])] += value
        daily[(int(row['outcome_available_ts_ms']) - start_ms) // DAY] += value
        by_symbol[str(row['symbol'])] += value
        month = datetime.fromtimestamp(int(row['outcome_available_ts_ms'])/1000, timezone.utc).strftime('%Y-%m')
        by_month[month] += value
    equity, peak, dd = 0.0, 0.0, 0.0
    peak_at, underwater_at, recoveries = start_ms, None, []
    for stamp, value in sorted(cohorts.items()):
        equity += value
        if equity >= peak:
            if underwater_at is not None:
                recoveries.append(stamp - underwater_at)
            peak, peak_at, underwater_at = equity, stamp, None
        elif underwater_at is None:
            underwater_at = peak_at
        dd = max(dd, peak - equity)
    days = (end_ms - start_ms) / DAY
    day_count = math.ceil(days)
    positive_sum, negative_sum = sum(wins), -sum(losses)
    return {
        'T': len(rows), 'Gross_bps': sum(float(r['gross_bps']) for r in rows),
        'Cost_bps': sum(float(r['cost_bps']) * multiplier for r in rows),
        'Net_bps': sum(values), 'Net_bps_per_day': sum(values) / days,
        'Net_bps_per_T': sum(values) / len(values) if values else None,
        'WR_pct': 100 * len(wins) / len(values) if values else None,
        'PF': positive_sum / negative_sum if losses else None,
        'payoff': (positive_sum / len(wins)) / (negative_sum / len(losses)) if wins and losses else None,
        'MaxLossStreak': max((s['length'] for s in streaks['loss']), default=0),
        'WorstLossStreak_bps': min((s['net_bps'] for s in streaks['loss']), default=0.0),
        'MaxWinStreak': max((s['length'] for s in streaks['win']), default=0),
        'MedianWinStreak': median([s['length'] for s in streaks['win']]) if streaks['win'] else 0,
        'streaks': streaks,
        'winning_trades_in_runs_ge_2_share': sum(s['length'] for s in streaks['win'] if s['length'] >= 2) / len(wins) if wins else None,
        'worst_trade_bps': min(values) if values else None,
        'negative_trade_bps_sorted': sorted(losses),
        'net_bps_by_symbol': dict(sorted(by_symbol.items())),
        'net_bps_by_month': dict(sorted(by_month.items())),
        'max_completed_recovery_minutes': max(recoveries) / 60_000 if recoveries else None,
        'unrecovered_drawdown_at_end': underwater_at is not None,
        'ongoing_underwater_minutes': (end_ms - underwater_at) / 60_000 if underwater_at is not None else 0,
        'simultaneous_outcome_group_count': len(cohorts), 'DD_bps': dd, 'DD_kind': 'REALIZED_SIMULTANEOUS_OUTCOME_COHORT_TRADE_BPS',
        'worst_realized_day_bps': min([0.0, *daily.values()]),
        'calendar_days': days,
        'positive_realized_days': sum(daily.get(i, 0) > 0 for i in range(day_count)),
        'negative_realized_days': sum(daily.get(i, 0) < 0 for i in range(day_count)),
        'net_zero_realized_days': sum(daily.get(i, 0) == 0 for i in range(day_count)),
        'unrealized_pnl_included': False, 'account_nav_or_mtm': False,
    }


def attribution(before, after, multiplier) -> dict[str, Any]:
    old, new = {key(r): r for r in before}, {key(r): r for r in after}
    if len(old) != len(before) or len(new) != len(after):
        raise ValueError('DUPLICATE_ATTRIBUTION_KEY')
    common, added, removed = old.keys() & new.keys(), new.keys() - old.keys(), old.keys() - new.keys()
    details = []
    for k in sorted(common):
        a, b = net(old[k], multiplier), net(new[k], multiplier)
        details.append({'key': list(k), 'old_net_bps': a, 'new_net_bps': b,
                        'delta_bps': b - a, 'old_reason': old[k]['reason'],
                        'new_reason': new[k]['reason']})
    common_delta = sum(v['delta_bps'] for v in details)
    added_net = sum(net(new[k], multiplier) for k in added)
    removed_net = sum(net(old[k], multiplier) for k in removed)
    delta = sum(net(r, multiplier) for r in after) - sum(net(r, multiplier) for r in before)
    if not math.isclose(delta, common_delta + added_net - removed_net, rel_tol=1e-10, abs_tol=1e-8):
        raise ValueError('ATTRIBUTION_DOES_NOT_RECONCILE')
    positive = {k: net(r, multiplier) for k, r in old.items() if net(r, multiplier) > 0}
    largest_key = max(positive, key=positive.get) if positive else None
    retained = sum(min(v, max(0.0, net(new[k], multiplier))) for k, v in positive.items() if k in new)
    return {'common_T': len(common), 'added_T': len(added), 'removed_T': len(removed),
            'total_delta_bps': delta, 'common_delta_bps': common_delta,
            'added_net_bps': added_net, 'removed_reference_net_bps': removed_net,
            'loss_reduction_common_bps': sum(max(0.0, -v['old_net_bps'] - max(0.0, -v['new_net_bps']))
                                             for v in details if v['old_net_bps'] < 0),
            'winner_profit_retention': retained / sum(positive.values()) if positive else None,
            'lost_winner_profit_bps': sum(positive.values()) - retained,
            'largest_reference_winner_key': list(largest_key) if largest_key else None,
            'largest_reference_winner_retained': largest_key in new if largest_key else None,
            'largest_reference_winner_new_net_bps': net(new[largest_key], multiplier) if largest_key in new else None,
            'largest_reference_winner_original_net_bps': positive.get(largest_key),
            'common_details': details, 'added_keys': [list(k) for k in sorted(added)],
            'removed_keys': [list(k) for k in sorted(removed)],
            'after_unresolved_not_treated_as_avoided_loss': True}


def comparison_report(parent_rows, saved_rows, result, start_ms=START, end_ms=END):
    rolling = [r for r in result['trades'] if r['partition'] == 'rolling']
    incomplete = [r for k in ('unresolved', 'boundary_excluded') for r in result[k]]
    # A missing completed trade could be an unclosed loss, not an avoided loss.
    terminal = not incomplete
    views = {}
    for m in (1.0, 2.0):
        views[f'cost{int(m)}x'] = {
            'parent': economic_summary(parent_rows, start_ms, end_ms, m),
            'saved_rejected': economic_summary(saved_rows, start_ms, end_ms, m),
            'successor': economic_summary(rolling, start_ms, end_ms, m),
            'vs_parent': attribution(parent_rows, rolling, m),
            'vs_saved_rejected': attribution(saved_rows, rolling, m),
        }
        for k in ('vs_parent', 'vs_saved_rejected'):
            views[f'cost{int(m)}x'][k]['comparison_complete'] = terminal
    entries = [d['entry_ts_ms'] for d in result['decisions']
               if d['partition'] == 'rolling' and d['state'] == 'ACCEPTED']
    days = math.ceil((end_ms - start_ms) / DAY)
    dates = Counter((t - start_ms) // DAY for t in entries)
    return {
        'schema': 'zel.scalp7.squeeze_signal_low_comparison.v1',
        'state': 'USED_DEV_MEASURED_AWAITING_SSOT_ADJUDICATION' if terminal else 'INCOMPLETE_NO_ADOPTION',
        'candidate_id': policy.SQUEEZE_SUCCESSOR,
        'window': {'start_ms': start_ms, 'end_exclusive_ms': end_ms},
        'views': views, 'trade_rows': rolling,
        'all_partition_trade_rows': result['trades'],
        'unresolved': result['unresolved'], 'boundary_excluded': result['boundary_excluded'],
        'decisions': result['decisions'], 'causal_exit_traces': result['causal_exit_traces'],
        'next_open_stop_arbitrations': result['next_open_stop_arbitrations'],
        'window_census': result['window_census'],
        'accepted_entries': len(entries), 'entries_per_calendar_day': len(entries) / days,
        'zero_entry_days': sum(dates.get(i, 0) == 0 for i in range(days)),
        'days_ge_3_entries': sum(dates.get(i, 0) >= 3 for i in range(days)),
        'days_ge_4_entries': sum(dates.get(i, 0) >= 4 for i in range(days)),
        'comparison_complete': terminal, 'used_dev_only': True, 'fresh_or_oos': False,
        'account_nav_or_mtm': False, 'old_candidate_replayed': False,
        'promotion': False, 'survivor_count_delta': 0,
        'order_paper_live_deploy': 'BLOCKED',
    }


def _write_new(path: Path, value: dict[str, Any]) -> None:
    body = deepcopy(value)
    body['receipt_sha256'] = digest(value)
    with path.open('x', encoding='utf-8') as out:
        json.dump(body, out, sort_keys=True, indent=2, allow_nan=False)
        out.write('\n')


def run(source_root: Path, saved_path: Path, output_dir: Path, *, full: bool = False,
        benchmark_observations: bool = False, keltner_result: Path | None = None,
        claim_id: str | None = None):
    """Existing owner invokes this only under its approved execution admission.

    An existing output directory is a consumed/recovery checkpoint, never a cue to
    start over. No workflow trigger, secret, budget or global ownership is changed.
    """
    if not source_root.is_dir():
        raise FileNotFoundError('CANONICAL_SOURCE_ROOT_UNAVAILABLE')
    if output_dir.exists():
        raise FileExistsError('RECOVER_EXISTING_RESULT_DO_NOT_REPLAY')
    root = Path(__file__).resolve().parents[1]
    # Preserve the existing PR1449 admission and complete dependency guard.
    from ops import scalp7_squeeze_signal_low_economics_v1 as admission
    contract = json.loads(admission.CONTRACT.read_text())
    admission._verify_source_pins(contract, root)
    prior_receipt = None
    if full:
        if not claim_id or keltner_result is None:
            raise ValueError('EXISTING_CLAIM_AND_KELTNER_ORDERED_RESULT_REQUIRED')
        prior = json.loads(keltner_result.read_text())
        if (prior.get('receipt_sha256') != admission._digest(prior) or
                prior.get('state') != 'KELTNER_SUCCESSOR_USED_DEV_NATIVE_COMPARISON_COMPLETE' or
                prior.get('source_inventory_sha256') != policy.INVENTORY or
                prior.get('result', {}).get('successor_identity') != admission.keltner.KELTNER_SUCCESSOR):
            raise ValueError('KELTNER_ORDERED_RESULT_REQUIRED')
        prior_receipt = prior['receipt_sha256']
    for path, expected in PINS.items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != expected:
            raise ValueError('FROZEN_DEPENDENCY_CHANGED:' + path)
    # Reuse the native source, context and opportunity generators; never execute
    # overlay.run() or overlay._run_child() for the rejected predecessor.
    from backend.research.rebuild import scalp7_source_data_v2 as source
    from backend.research.rebuild import scalp7_rolling_context_v2 as context
    from ops import scalp7_dual_native_funnel_v1 as common
    from ops import scalp7_squeeze_regime_overlay_child_v1 as overlay
    saved = json.loads(saved_path.read_text())
    saved_rows = saved_overlay(saved)
    contract = json.loads((common.REPORT / 'CAMPAIGN_PREREGISTERED_V2.json').read_text())
    windows = contract['windows']
    costs = json.loads(common.COST_PATH.read_text())['costs_bps']
    frames = source.load_candles(source_root, 30, cache_dir=None)
    if set(frames) != SYMBOLS or {f.attrs.get('source_inventory_sha256') for f in frames.values()} != {policy.INVENTORY}:
        raise ValueError('EXACT_CANONICAL_COHORT_REQUIRED')
    bound, fits = context.bind_context(frames, context.cross_features(frames), windows)
    context_hash = hashlib.sha256(json.dumps(fits, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if context_hash != saved['context_fit_sha256']:
        raise ValueError('FROZEN_CONTEXT_FIT_MISMATCH')
    scan = policy.scan_saved_trend_triggers(frames, saved)
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_new(output_dir / 'TRIGGER_SCAN.json', scan)
    if benchmark_observations:
        from ops.scalp7_benchmark_observer_v1 import scan_saved_squeeze_paths
        try:
            diagnostic = scan_saved_squeeze_paths(frames, saved)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            diagnostic = {'state': 'DIAGNOSTIC_INCOMPLETE_NOT_ZERO',
                          'error_type': type(exc).__name__, 'error': str(exc),
                          'economic_runs': 0, 'profit_improvement': 'NOT_MEASURED'}
        _write_new(output_dir / 'BENCHMARK_OBSERVATIONS.json', diagnostic)
    if not full or scan['earlier_invalidation_count'] == 0:
        return {'state': 'SCAN_COMPLETE' if not full else 'NO_EARLIER_TRIGGER_NO_FULL',
                'scan': scan, 'economic_runs': 0, 'promotion': False}
    parent_path, saved_parent = common._load_saved(positive.SQUEEZE_PARENT)
    parent_signals = positive.generate_signals(bound, costs=costs, identities=(positive.SQUEEZE_PARENT,))
    additions, census = overlay._added_trend_disperse_signals(bound, costs)
    if census != saved['source_census']:
        raise ValueError('FROZEN_OPPORTUNITY_CENSUS_MISMATCH')
    for field, opportunities in [('parent_signal_count_by_partition', parent_signals),
                                 ('added_trend_disperse_signal_count_by_partition', additions)]:
        if overlay._partition_signal_count(opportunities, windows) != saved[field]:
            raise ValueError('FROZEN_PARTITION_SIGNAL_COUNT_MISMATCH')
    # Prove all SAVED accepted opportunities still have identical signal inputs.
    by_key = {key(s): s for s in parent_signals + additions}
    for r in saved_rows:
        sig = deepcopy(r['signal']); sig['identity'] = positive.SQUEEZE_PARENT
        sig['meta'].pop('lifecycle_adapter_parent_identity', None)
        if by_key.get(key(r)) != sig:
            raise ValueError('SAVED_ACCEPTED_SIGNAL_IDENTITY_DRIFT')
    freeze = {'candidate_id': policy.SQUEEZE_SUCCESSOR,
              'claim_id': claim_id, 'keltner_result_receipt_sha256': prior_receipt,
              'versioned_contract_sha256': hashlib.sha256(admission.CONTRACT.read_bytes()).hexdigest(),
              'saved_rejected_receipt': policy.SAVED_RECEIPT,
              'source_inventory_sha256': policy.INVENTORY,
              'context_fit_sha256': context_hash, 'windows': windows,
              'cost_snapshot_sha256': hashlib.sha256(common.COST_PATH.read_bytes()).hexdigest(),
              'parent_ledger_sha256': hashlib.sha256(parent_path.read_bytes()).hexdigest(),
              'opportunity_pool_sha256': digest(parent_signals + additions),
              'dependencies': {str(m.__file__): hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                               for m in (source, context, common, overlay, execution, positive, policy)},
              'comparison_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'candidate_comparisons_attempted': 1, 'old_candidate_replayed': False,
              'caller_must_hold_existing_owner_and_global_heavy': True,
              'frozen_at_utc': datetime.now(timezone.utc).isoformat()}
    _write_new(output_dir / 'STARTED_FREEZE.json', freeze)
    try:
        parent_rows, parent_open, _, _ = common._replay_parent(
            positive.SQUEEZE_PARENT, bound, costs, windows, parent_signals)
        if parent_rows != saved_parent['trades'] or parent_open != saved_parent['unresolved']:
            raise ValueError('EXACT_PARENT_PARITY_FAILED')
        parent_rolling = [r for r in parent_rows if r['partition'] == 'rolling']
        if len(parent_rolling) != 25:
            raise ValueError('PARENT_25T_PARITY_FAILED')
        result = replay_successor(parent_signals + additions, bound, costs, windows)
        report = comparison_report(parent_rolling, saved_rows, result)
        report.update(input_freeze_sha256=digest(freeze), saved_rejected_receipt=policy.SAVED_RECEIPT,
                      source_inventory_sha256=policy.INVENTORY, economic_runs=1,
                      parent_completed_trade_unresolved_pnl_parity=True)
        _write_new(output_dir / 'RESULT.json', report)
        return report
    except Exception as exc:
        _write_new(output_dir / 'FAILED.json', {'state': 'FAILED_AFTER_START_NO_AUTOMATIC_RETRY',
                   'error_type': type(exc).__name__, 'error': str(exc),
                   'input_freeze_sha256': digest(freeze), 'promotion': False})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--saved-overlay', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--full', action='store_true', help='Existing owner admission required; consumes the one approved S comparison.')
    parser.add_argument('--benchmark-observations', action='store_true',
                        help='Attach read-only H01 source observations; no new candidate.')
    parser.add_argument('--keltner-result', type=Path)
    parser.add_argument('--claim-id')
    args = parser.parse_args()
    report = run(args.source_root, args.saved_overlay, args.output_dir, full=args.full,
                 benchmark_observations=args.benchmark_observations,
                 keltner_result=args.keltner_result, claim_id=args.claim_id)
    print(json.dumps({'state': report['state'], 'economic_runs': report['economic_runs'],
                      'promotion': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
