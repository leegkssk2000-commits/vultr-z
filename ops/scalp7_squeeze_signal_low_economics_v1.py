"""Bounded Squeeze successor comparison, reusing the frozen Scalp7 engine.

No workflow, schedule, order interface, rejected-child replay, or parameter sweep.
The default operation is a saved-trade trigger scan. The sole coordinator must
reconcile the existing claim/budget and finish Keltner before calling compare().
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild import scalp7_source_data_v2 as source
from ops import scalp7_dual_native_funnel_v1 as native
from ops import scalp7_keltner_fresh_touch_successor_v1 as keltner
from ops import scalp7_squeeze_regime_overlay_child_v1 as overlay
from ops import scalp7_squeeze_signal_low_successor_v1 as preparation

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'research/campaigns/scalp7_20261013/dual_streak_v1/SQUEEZE_SIGNAL_LOW_COMPARISON_V2.json'
SYMBOLS = {'BTC-USDT', 'DOGE-USDT', 'ETH-USDT', 'LINK-USDT', 'SOL-USDT', 'XRP-USDT'}
SUCCESSOR = preparation.SQUEEZE_SUCCESSOR
REQUIRED_SOURCE_PINS = frozenset({
    'backend/research/rebuild/scalp7_execution_v2.py',
    'backend/research/rebuild/scalp7_positive_lanes_v2.py',
    'backend/research/rebuild/scalp7_rolling_context_v2.py',
    'backend/research/rebuild/scalp7_source_data_v2.py',
    'backend/research/rebuild/economic7_canonical_history_v1.py',
    'backend/research/rebuild/scalp7_metrics_v2.py',
    'ops/scalp7_dual_native_funnel_v1.py',
    'ops/scalp7_keltner_fresh_touch_successor_v1.py',
    'ops/scalp7_squeeze_regime_overlay_child_v1.py',
    'ops/scalp7_squeeze_signal_low_successor_v1.py',
    'research/campaigns/scalp7_20261013/dual_streak_v1/streak_successor_policies.py',
    'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json',
    'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json',
    'research/campaigns/scalp7_20261012/dual_frequency_v1/SQUEEZE_TREND_DISPERSED_OVERLAY_CHILD_V1.json',
})


def _verify_source_pins(contract, root):
    sha256 = contract.get('frozen_source_sha256', {})
    git_blobs = contract.get('frozen_source_git_blob_sha1', {})
    if set(sha256) & set(git_blobs) or set(sha256) | set(git_blobs) != REQUIRED_SOURCE_PINS:
        raise ValueError('FROZEN_DEPENDENCY_COVERAGE_INCOMPLETE_OR_AMBIGUOUS')
    for algorithm, pins in (('sha256', sha256), ('git_blob_sha1', git_blobs)):
        for name, expected in pins.items():
            raw = (root / name).read_bytes()
            actual = (hashlib.sha256(raw).hexdigest() if algorithm == 'sha256' else
                      hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())
            if actual != expected:
                raise ValueError('FROZEN_SOURCE_CHANGED:' + name)


def _digest(value: Mapping[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop('receipt_sha256', None)
    return hashlib.sha256((json.dumps(unsigned, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()).hexdigest()


def _publish(report: dict[str, Any], output: Path) -> dict[str, Any]:
    report['receipt_sha256'] = _digest(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse accidental replacement of a completed comparison.
    with output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n')
    return report


def _single_successor(signal, frame, records, index, cost, traces):
    """Original engine; preserve gap-stop priority and its occupancy timestamp.

The frozen engine executes a pending close before testing a next-open gap stop.
Only a NEW structural exit needs arbitration here: an original stop already
crossed at that same open wins. Both fill at the actual open, but the parent stop
retains ownership through that bar. Changing just the exit label after a pooled
replay would miss the resulting downstream entry difference.
"""
    pending: dict[str, Any] = {}

    def callback(position, bar, history):
        update = preparation.native_exit_update(position, bar, history)
        if update.get('reason') == preparation.EXIT_REASON:
            pending.update(
                observed_at_ms=int(bar['available_ts_ms']),
                expected_open_ms=int(bar['close_ts_ms']),
                stop_price=max(float(position['stop_price']),
                               float(update['next_stop']) if update.get('next_stop') is not None else float(position['stop_price'])),
                signal_low=float(position['signal']['meta'][preparation.BINDING]['low']),
            )
        return update

    row, unresolved, until, rejection = execution._single(
        signal, frame, records, index, cost, callback, positive.entry_update,
    )
    if not pending:
        return row, unresolved, until, rejection
    record = {
        'symbol': signal['symbol'],
        'signal_ts_ms': int(signal['signal_ts_ms']),
        'signal_open_ts_ms': int(signal['signal_open_ts_ms']),
        'entry_ts_ms': int(signal['signal_open_ts_ms']) + positive.TIMEFRAME_MS,
        'invalidation_available_ts_ms': pending['observed_at_ms'],
        'frozen_signal_low': pending['signal_low'],
        'actual_exit_ts_ms': None,
        'disposition': 'UNRESOLVED_NEXT_OPEN',
    }
    if row is not None and row['reason'] == preparation.EXIT_REASON:
        exit_ts = int(row['exit_ts_ms'])
        if exit_ts != pending['expected_open_ms'] or pending['observed_at_ms'] > exit_ts:
            raise ValueError('SUCCESSOR_NEXT_OPEN_CAUSALITY_DRIFT')
        exit_bar = records[index[exit_ts]]
        opened = float(exit_bar['open'])
        if float(row['exit_prices'][signal['symbol']]) != opened:
            raise ValueError('SUCCESSOR_NONACTUAL_OPEN_FILL')
        if opened <= pending['stop_price']:
            # At equality the resting stop is hit too: retain conservative
            # original stop ownership, not a synthetic intrabar stop-price fill.
            row = deepcopy(row)
            gap = opened < pending['stop_price']
            row['reason'] = 'OPEN_GAP_STOP' if gap else 'STOP_FIRST'
            row['hold_bars'] += 1
            row['exit_ts_ms'] = exit_ts if gap else int(exit_bar['close_ts_ms'])
            row['outcome_available_ts_ms'] = exit_ts if gap else int(exit_bar['available_ts_ms'])
            row['hold_minutes'] = (row['exit_ts_ms'] - row['entry_ts_ms']) / 60_000
            row['outcome_time_precision'] = 'BAR_CLOSE' if row['outcome_available_ts_ms'] > row['exit_ts_ms'] else 'OPEN'
            until = max(int(exit_bar['close_ts_ms']), int(exit_bar['available_ts_ms']))
            record['disposition'] = 'ORIGINAL_STOP_WINS_AT_STRUCTURAL_EXIT_OPEN'
        else:
            record['disposition'] = 'STRUCTURAL_EXIT_AT_ACTUAL_OPEN'
        record['actual_exit_ts_ms'] = int(row['exit_ts_ms'])
        record['ownership_until_ms'] = until
    elif unresolved is None:
        raise ValueError('SUCCESSOR_PENDING_EXIT_WITHOUT_TERMINAL_EVIDENCE')
    traces.append(record)
    return row, unresolved, until, rejection


def replay_window(signals, frames, costs, *, enabled=True):
    """Same identity-local ownership/order as frozen replay; no pooled account NAV.

With enabled=False this must exactly reproduce the untouched overlay callbacks.
This is a synthetic-test control, not permission to rerun the rejected child.
"""
    prepared = {symbol: execution._frame_records(frame, 30) for symbol, frame in frames.items()}
    trades, unresolved, traces, admissions = [], [], [], []
    rejected: Counter[str] = Counter()
    seen, ownership = set(), {}
    selected = list(signals)
    for signal in selected:
        execution.validate_signal(signal)
        if signal['identity'] != positive.SQUEEZE_PARENT or signal.get('legs') or signal['side'] != 1 or signal['timeframe_min'] != 30:
            raise ValueError('SQUEEZE_PARENT_LONG_30M_REQUIRED')
    for original in sorted(selected, key=lambda x: (x['signal_ts_ms'], x['identity'], x['symbol'], x.get('side', 0))):
        identity, symbol, stamp = str(original['identity']), str(original['symbol']), int(original['signal_ts_ms'])
        key, owner = (identity, symbol, stamp), (identity, symbol)
        if key in seen:
            rejected['DUPLICATE_SIGNAL'] += 1
            continue
        seen.add(key)
        if stamp < ownership.get(owner, -1):
            rejected['POSITION_ALREADY_OWNED'] += 1
            continue
        frame, (records, index) = frames[symbol], prepared[symbol]
        cost = execution._cost(original, costs)
        if enabled:
            signal = preparation.bind_signal_low(original, frame)
            row, open_position, until, reason = _single_successor(signal, frame, records, index, cost, traces)
        else:
            signal = deepcopy(original)
            row, open_position, until, reason = execution._single(signal, frame, records, index, cost, positive.exit_update, positive.entry_update)
        if reason:
            rejected[reason] += 1
            continue
        ownership[owner] = until
        if row is not None:
            trades.append(row)
            admissions.append(int(row['entry_ts_ms']))
        if open_position is not None:
            unresolved.append(open_position)
            admissions.append(int(open_position['entry_ts_ms']))
    trades.sort(key=lambda x: (x['outcome_available_ts_ms'], x['identity'], x['symbol']))
    return {'trades': trades, 'unresolved': unresolved, 'rejections': dict(rejected), 'traces': traces, 'admitted_entry_ts_ms': admissions, 'signal_count': len(selected)}


def replay_windows(signals, frames, costs, windows):
    results = {'trades': [], 'unresolved': [], 'boundary_excluded': [], 'traces': [], 'admitted_entry_ts_ms': [], 'rejections_by_partition': {}}
    for window in windows:
        start, end = int(window['start_ms']), int(window['end_ms'])
        if start >= end:
            raise ValueError('INVALID_WINDOW')
        chosen = [s for s in signals if start <= int(s['signal_ts_ms']) < end]
        prefix = start - 200 * positive.TIMEFRAME_MS
        sliced = {symbol: frame[(frame.open_ts_ms >= prefix) & (frame.close_ts_ms <= end)].reset_index(drop=True) for symbol, frame in frames.items()}
        out = replay_window(chosen, sliced, costs)
        partition = str(window['partition'])
        counts = results['rejections_by_partition'].setdefault(partition, Counter())
        counts.update(out['rejections'])
        for key in ('trades', 'unresolved', 'traces'):
            for original in out[key]:
                row = deepcopy(original)
                row.update(window_label=window['label'], partition=partition)
                if key == 'trades' and int(row['outcome_available_ts_ms']) >= end:
                    row.update(window_end_ms=end, boundary_exclusion_reason='OUTCOME_AT_OR_AFTER_WINDOW_END_UNAVAILABLE')
                    results['boundary_excluded'].append(row)
                else:
                    results[key].append(row)
        results['admitted_entry_ts_ms'].extend({'partition': partition, 'entry_ts_ms': ts} for ts in out['admitted_entry_ts_ms'])
    results['rejections_by_partition'] = {p: dict(c) for p, c in results['rejections_by_partition'].items()}
    return results


def _relabel(row):
    out = deepcopy(row)
    out['identity'] = SUCCESSOR
    signal = out.get('signal') or out.get('position', {}).get('signal')
    if signal is not None:
        signal['identity'] = SUCCESSOR
        signal.setdefault('meta', {})['lifecycle_adapter_parent_identity'] = positive.SQUEEZE_PARENT
    return out



def exit_attribution(before, after, multiplier):
    """Post-run accounting only; never selects signals using final outcomes."""
    if multiplier not in (1.0, 2.0):
        raise ValueError('FROZEN_COST_VIEW_REQUIRED')
    def key(row):
        return (row['symbol'], int(row['signal_ts_ms']), int(row['entry_ts_ms']), int(row['side']))
    old, new = {key(r): r for r in before}, {key(r): r for r in after}
    if len(old) != len(before) or len(new) != len(after):
        raise ValueError('ATTRIBUTION_DUPLICATE_TRADE')
    def net(row):
        return float(row['gross_bps']) - multiplier * float(row['cost_bps'])
    buckets = {name: {'T': 0, 'net_delta_bps': 0.0} for name in ('loss_reduced', 'loss_worsened', 'winner_sacrificed', 'winner_improved', 'neutral_changed')}
    for k in sorted(old.keys() & new.keys()):
        a, b = net(old[k]), net(new[k])
        if a == b:
            continue
        name = ('loss_reduced' if b > a else 'loss_worsened') if a < 0 else ('winner_improved' if b > a else 'winner_sacrificed') if a > 0 else 'neutral_changed'
        buckets[name]['T'] += 1
        buckets[name]['net_delta_bps'] += b - a
    added = sum(net(new[k]) for k in sorted(new.keys() - old.keys()))
    removed = sum(net(old[k]) for k in sorted(old.keys() - new.keys()))
    decomposed = sum(v['net_delta_bps'] for v in buckets.values()) + added - removed
    delta = sum(map(net, after)) - sum(map(net, before))
    if abs(decomposed - delta) > 1e-8 * max(1.0, abs(delta)):
        raise ValueError('ATTRIBUTION_DOES_NOT_RECONCILE')
    return {'cost_multiplier': multiplier, 'common_trade_changes': buckets, 'added_T': len(new.keys() - old.keys()), 'added_net_bps': added, 'removed_T': len(old.keys() - new.keys()), 'removed_old_net_bps': removed, 'total_net_delta_bps': delta, 'post_run_diagnostic_only': True}


def load_inputs(source_root: Path, saved_result: Path):
    contract = json.loads(CONTRACT.read_text())
    if contract['successor_identity'] != SUCCESSOR or contract['source_inventory_sha256'] != native.EXPECTED_INVENTORY:
        raise ValueError('SUCCESSOR_CONTRACT_DRIFT')
    _verify_source_pins(contract, ROOT)
    frames = source.load_candles(source_root, 30, cache_dir=None)
    if set(frames) != SYMBOLS or {f.attrs.get('source_inventory_sha256') for f in frames.values()} != {native.EXPECTED_INVENTORY}:
        raise ValueError('EXACT_SOURCE_COHORT_REQUIRED')
    saved = json.loads(saved_result.read_text())
    scan = preparation.scan_saved_trend_triggers(frames, saved)
    return contract, frames, saved, scan


def comparison_effects(parent, saved_rows, child, replay):
    """Missing terminal outcomes are unknown, never removed/avoided losses."""
    complete = not replay['unresolved'] and not replay['boundary_excluded']
    return {
        'comparison_complete': complete,
        'completed_subset_only': not complete,
        'all_partition_unresolved': deepcopy(replay['unresolved']),
        'all_partition_boundary_excluded': deepcopy(replay['boundary_excluded']),
        'parent_to_successor': native._opportunity_comparison(parent, child) if complete else None,
        'saved_rejected_to_successor': native._opportunity_comparison(saved_rows, child) if complete else None,
        'exit_attribution_cost1x': exit_attribution(saved_rows, child, 1.0) if complete else None,
        'exit_attribution_cost2x': exit_attribution(saved_rows, child, 2.0) if complete else None,
    }


def compare(source_root: Path, saved_result: Path, output: Path, *, keltner_result: Path, claim_id: str):
    """One existing-authority comparison; caller owns admission, no self-dispatch.

The Keltner result binds the ordered prerequisite, not a new authority grant.
The claim ID must have been acquired by the existing coordinator before calling.
"""
    if not claim_id or output.exists():
        raise ValueError('EXISTING_UNIQUE_CLAIM_AND_UNUSED_OUTPUT_REQUIRED')
    prior = json.loads(keltner_result.read_text())
    if prior.get('receipt_sha256') != _digest(prior) or prior.get('state') != 'KELTNER_SUCCESSOR_USED_DEV_NATIVE_COMPARISON_COMPLETE' or prior.get('source_inventory_sha256') != native.EXPECTED_INVENTORY or prior.get('result', {}).get('successor_identity') != keltner.KELTNER_SUCCESSOR:
        raise ValueError('KELTNER_ORDERED_RESULT_REQUIRED')
    contract, frames, saved, scan = load_inputs(source_root, saved_result)
    base = {'schema': 'zel.scalp7.squeeze_signal_low_comparison.v1', 'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'successor_identity': SUCCESSOR, 'source_inventory_sha256': native.EXPECTED_INVENTORY, 'saved_rejected_receipt_sha256': preparation.SAVED_RECEIPT, 'claim_id': claim_id, 'keltner_result_receipt_sha256': prior['receipt_sha256'], 'contract_sha256': hashlib.sha256(CONTRACT.read_bytes()).hexdigest(), 'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'used_dev_only': True, 'fresh_or_oos': False, 'account_nav_or_mtm': False, 'saved_rejected_child_replayed': False, 'promotion': False, 'survivor_delta': 0, 'order_live_paper_deploy': 'BLOCKED', 'trigger_scan': scan}
    if scan['earlier_invalidation_count'] == 0:
        return _publish({**base, 'state': 'NO_EARLIER_STRUCTURAL_TRIGGER_NOT_ECONOMIC_PASS', 'new_candidate_native_comparisons': 0, 'economic_result': None}, output)
    campaign = json.loads((native.REPORT / 'CAMPAIGN_PREREGISTERED_V2.json').read_text())
    windows = campaign['windows']
    bound, fits = context.bind_context(frames, context.cross_features(frames), windows)
    fit_sha = hashlib.sha256(json.dumps(fits, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if saved.get('context_fit_sha256') != fit_sha:
        raise ValueError('SAVED_CONTEXT_FIT_MISMATCH')
    costs = json.loads(native.COST_PATH.read_text())['costs_bps']
    parent_path, parent_saved = native._load_saved(positive.SQUEEZE_PARENT)
    parent_signals = positive.generate_signals(bound, costs=costs, identities=(positive.SQUEEZE_PARENT,))
    parent_rows, parent_unresolved, _, _ = native._replay_parent(positive.SQUEEZE_PARENT, bound, costs, windows, parent_signals)
    if parent_rows != parent_saved['trades'] or parent_unresolved != parent_saved['unresolved']:
        raise ValueError('EXACT_PARENT_PARITY_FAILED')
    parent = [r for r in parent_rows if r['partition'] == 'rolling']
    if len(parent) != 25:
        raise ValueError('PARENT_ROLLING_T_MISMATCH')
    additions, census = overlay._added_trend_disperse_signals(bound, costs)
    old_contract = json.loads(overlay.CONTRACT.read_text())
    if census['source_conditioned_by_regime_rolling'] != old_contract['source_basis']['observed_rolling_source_conditioned_by_regime']:
        raise ValueError('FROZEN_SIGNAL_CENSUS_MISMATCH')
    signals = [*parent_signals, *additions]
    if len({(s['symbol'], s['signal_ts_ms'], s['signal_open_ts_ms']) for s in signals}) != len(signals):
        raise ValueError('DUPLICATE_SUCCESSOR_OPPORTUNITY')
    replay = replay_windows(signals, bound, costs, windows)
    child = [_relabel(r) for r in replay['trades'] if r['partition'] == 'rolling']
    unresolved = [_relabel(r) for r in replay['unresolved'] if r['partition'] == 'rolling']
    boundary = [_relabel(r) for r in replay['boundary_excluded'] if r['partition'] == 'rolling']
    traces = [r for r in replay['traces'] if r['partition'] == 'rolling']
    saved_rows = saved['trade_rows']
    result = {'parent': keltner._metrics(parent), 'saved_rejected_child': keltner._metrics(saved_rows), 'successor': keltner._metrics(child), **comparison_effects(parent, saved_rows, child, replay), 'trade_rows': child, 'unresolved': unresolved, 'boundary_excluded': boundary, 'causal_trace': traces, 'all_modeled_entries': native._daily_summary([r['entry_ts_ms'] for r in replay['admitted_entry_ts_ms'] if r['partition'] == 'rolling']), 'rejections': replay['rejections_by_partition'].get('rolling', {}), 'requires_independent_economic_disposition': True}
    state = 'USED_DEV_COMPARISON_COMPLETE_NOT_PROMOTED' if result['comparison_complete'] else 'INCOMPLETE_NO_ADOPTION'
    return _publish({**base, 'state': state, 'context_fit_sha256': fit_sha, 'parent_ledger_sha256': hashlib.sha256(parent_path.read_bytes()).hexdigest(), 'cost_snapshot_sha256': hashlib.sha256(native.COST_PATH.read_bytes()).hexdigest(), 'window': {'start_ms': native.START, 'end_exclusive_ms': native.END, 'calendar_days': 245, 'timeframe_min': 30}, 'new_candidate_native_comparisons': 1, 'economic_result': result}, output)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--saved-rejected-result', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare', action='store_true', help='Existing coordinator claim required; default is diagnostic only.')
    parser.add_argument('--keltner-result', type=Path)
    parser.add_argument('--claim-id')
    args = parser.parse_args()
    if args.compare:
        if args.keltner_result is None or not args.claim_id:
            parser.error('--compare requires the prior --keltner-result and acquired --claim-id')
        report = compare(args.source_root, args.saved_rejected_result, args.output, keltner_result=args.keltner_result, claim_id=args.claim_id)
    else:
        _, _, _, scan = load_inputs(args.source_root, args.saved_rejected_result)
        report = _publish({'schema': 'zel.scalp7.squeeze_signal_low_scan.v1', 'state': 'SAVED_SOURCE_TRIGGER_SCAN_COMPLETE', 'successor_identity': SUCCESSOR, 'source_inventory_sha256': native.EXPECTED_INVENTORY, 'saved_rejected_receipt_sha256': preparation.SAVED_RECEIPT, 'scan': scan, 'new_candidate_native_comparisons': 0, 'economic_result': None, 'promotion': False, 'order_live_paper_deploy': 'BLOCKED'}, args.output)
    print(report['state'], report['receipt_sha256'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
