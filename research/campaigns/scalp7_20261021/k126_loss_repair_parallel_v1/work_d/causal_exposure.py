"""Saved K126 lifecycle events and all-cohort exposure audit; no strategy replay.

Reuses the completed Work D normalizer, without rerunning its coverage tables.
Native outcome ordering is for historical reporting only, never allocation.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path

CURRENT_REF = '81a12c422ee9329996d2f6b983267d2def490d4b'
DIAG_REF = '4a5985e362959f8460726fb56780fc10eab04a8b'
CURRENT_ID = 'scalp7_k126_native_pullback_invalidation_next_open_v1'
LINEAGE_ID = 'scalp7_keltner_hg_fresh_touch_after_reject_utc30m_v1'
REUSE_SHA = '1b0a7bedc97d75f14498518e5d5783a4907d1368a2d21891f98838e6ec6e8e56'
PINS = {
    'current/ROWS.json.gz': '5f45180aa762dc091c16e8fa2d208dcf027c16f795d9533911d2c11d73a30c77',
    'current/SUMMARY.json': 'a69e1cce4b5dffe004d49820ced626962795952f2e7b06226eb71ad77b8f7812',
    'diagnostic/ENTRY_GEOMETRY_ALL126.json': 'ed98e2ee712cdb57339d61fa7c823d46e39b20fd839c0b048985e38ec337e388',
    'diagnostic/RAW_PATHS_ALL126.json.gz': '68fda12ccefab90d2d6529cd6883ab4ec9fb34a954c790ce3d26db57cb6d929f',
    'diagnostic/INPUT_MANIFEST.json': 'fadf94fae0685f746a26848c15327595e1c6d17cdf46bf746e53db99f8487028',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def key(t):
    return (t['symbol'], int(t['side']), int(t['signal_ts_ms']))


def native_order(t):
    return (t['outcome_available_ts_ms'], t['exit_ts_ms'], t['symbol'],
            t['identity'], t['signal_ts_ms'])


def load_reused_normalizer(path):
    if sha(Path(path).read_bytes()) != REUSE_SHA:
        raise ValueError('COMPLETED_D_NORMALIZER_CHANGED')
    spec = importlib.util.spec_from_file_location('completed_d_contribution', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_inputs(root):
    root = Path(root)
    values = {}
    for name, pin in PINS.items():
        raw = (root / name).read_bytes()
        if sha(raw) != pin:
            raise ValueError('PIN_MISMATCH:' + name)
        decoded = gzip.decompress(raw) if name.endswith('.gz') else raw
        values[name] = json.loads(decoded)
    rawrows = gzip.decompress((root / 'current/ROWS.json.gz').read_bytes())
    if sha(rawrows) != values['current/SUMMARY.json']['rows_sha256']:
        raise ValueError('UNCOMPRESSED_ROWS_MISMATCH')
    return values


def audit_inputs(payload, geometry, paths, normalizer):
    source = {'label': 'CURRENT_K126', 'array': 'trades', 'partition': 'rolling',
              'identity': CURRENT_ID, 'identity_field': 'management_comparison_identity',
              'lineage_identity': LINEAGE_ID, 'expected_rows': 126,
              'source_execution_profile': 'UTC_NEXT_OPEN_STOP_FIRST_GAPS_UNRESOLVED_V2'}
    normalized, audit = normalizer.normalize(source, payload)
    if len(normalized) != 126 or audit['duplicate_lifecycle_rows'] or payload['unresolved']:
        raise ValueError('CURRENT126_CARDINALITY_OR_UNRESOLVED')
    trades = payload['trades']
    by_key = {key(t): t for t in trades}
    geom = {tuple(g['key']): g for g in geometry}
    rawpaths = {tuple(p['trade_key']): p for p in paths}
    if len(geom) != len(geometry) or len(rawpaths) != len(paths):
        raise ValueError('DUPLICATE_DIAGNOSTIC_KEY')
    if set(by_key) != set(geom) or set(by_key) != set(rawpaths):
        raise ValueError('DIAGNOSTIC126_KEY_SET_MISMATCH')
    for k, t in by_key.items():
        g = geom[k]
        for field in ('entry_ts_ms', 'outcome_available_ts_ms', 'side', 'symbol'):
            if t[field] != g[field]:
                raise ValueError('GEOMETRY_BINDING:' + field)
        if not math.isclose(t['entry_prices'][t['symbol']], g['entry_price'], abs_tol=1e-12):
            raise ValueError('ENTRY_PRICE_BINDING')
        if not math.isclose(t['net_bps'], g['outcome_labels_NOT_FEATURES']['net1x'], abs_tol=1e-9):
            raise ValueError('OUTCOME_LABEL_BINDING')
        if not math.isclose(g['initial_risk_price'], t['side']*(g['entry_price']-g['initial_stop']), abs_tol=1e-12):
            raise ValueError('INITIAL_RISK_BINDING')
        bars = rawpaths[k]['bars']
        if not bars or len({b['open_ts_ms'] for b in bars}) != len(bars):
            raise ValueError('EMPTY_OR_DUPLICATE_RAW_PATH')
        last = -1
        for b in bars:
            if not last < b['open_ts_ms'] < b['close_ts_ms'] <= b['available_ts_ms']:
                raise ValueError('RAW_PATH_CLOCK')
            last = b['open_ts_ms']
        if not any(b['available_ts_ms'] <= t['entry_ts_ms'] for b in bars):
            raise ValueError('NO_ENTRY_KNOWN_RAW_PREFIX')
    return audit


def known_summary(rows, ordinal):
    return {'native_outcome_refs': [ordinal[key(t)] for t in sorted(rows, key=native_order)],
            'loss_count': sum(t['net_bps'] < 0 for t in rows),
            'win_count': sum(t['net_bps'] > 0 for t in rows),
            'loss_trade_bps': math.fsum(t['net_bps'] for t in rows if t['net_bps'] < 0),
            'win_trade_bps': math.fsum(t['net_bps'] for t in rows if t['net_bps'] > 0),
            'unit': 'equal_notional_trade_bps_NOT_QUOTE_BUDGET'}


def build_stream(trades, geometry, paths):
    """Final labels enter the stream only at OUTCOME_KNOWN, after tied entries."""
    geom = {tuple(g['key']): g for g in geometry}
    pathmap = {tuple(p['trade_key']): p for p in paths}
    ordered = sorted(trades, key=native_order)
    ordinal = {key(t): i for i, t in enumerate(ordered)}
    moments = sorted({t[f] for t in trades for f in
                      ('entry_ts_ms', 'exit_ts_ms', 'outcome_available_ts_ms')})
    events, batches, entry_snapshots = [], [], []
    for stamp in moments:
        entering = [t for t in ordered if t['entry_ts_ms'] == stamp]
        exits = [t for t in ordered if t['exit_ts_ms'] == stamp]
        outcomes = [t for t in ordered if t['outcome_available_ts_ms'] == stamp]
        known = [t for t in ordered if t['outcome_available_ts_ms'] < stamp]
        # Keep risk reserved at tied outcome times: no global phase contract exists.
        existing = [t for t in ordered if t['entry_ts_ms'] < stamp <= t['outcome_available_ts_ms']]
        for t in entering:
            k = key(t); g = geom[k]
            candidates = [u for u in entering if u['side'] == t['side']]
            open_side = [u for u in existing if u['side'] == t['side']]
            known_same_window = [u for u in known if u['window_label'] == t['window_label']]
            previous_symbol = [u for u in known if u['symbol'] == t['symbol'] and u['side'] == t['side']]
            exposures = []
            for u in open_side:
                ug = geom[key(u)]
                prefix = [b for b in pathmap[key(u)]['bars'] if b['available_ts_ms'] <= stamp]
                b = max(prefix, key=lambda b: b['available_ts_ms']) if prefix else None
                exposures.append({'key': list(key(u)), 'initial_stop_price': ug['initial_stop'],
                    'entry_price': ug['entry_price'], 'initial_risk_price': ug['initial_risk_price'],
                    'last_completed_close': b['close'] if b else None,
                    'mark_available_ts_ms': b['available_ts_ms'] if b else None,
                    'actual_remaining_quantity': None, 'current_stop_price': None,
                    'remaining_risk_quote': None, 'status': 'REQUIRED_INPUT_DYNAMIC_STATE'})
            snapshot = {'decision_ts_ms': stamp, 'trade_key': list(k),
                'window_label': t['window_label'], 'side': t['side'],
                'existing_same_direction': exposures,
                'same_time_same_direction_request_keys': [list(key(u)) for u in candidates],
                'batch_members_are_unordered_for_admission': True,
                'known_outcomes_strictly_earlier': known_summary(known, ordinal),
                'known_same_window_outcomes': known_summary(known_same_window, ordinal),
                'earlier_window_outcome_refs_for_audit_not_automatic_policy_carry':
                    [ordinal[key(u)] for u in known if u['window_label'] != t['window_label']],
                'same_time_outcome_keys_excluded_from_decision': [list(key(u)) for u in outcomes],
                'previous_closed_same_symbol_side_keys': [list(key(u)) for u in previous_symbol],
                'canonical_setup_id': None, 'same_setup_reentry': 'REQUIRED_INPUT_SETUP_INSTANCE_ID',
                'entry_known': {'price': g['entry_price'], 'initial_stop_price': g['initial_stop'],
                    'initial_risk_price': g['initial_risk_price'],
                    'reference_cost_bps': t['signal']['meta']['frozen_cost_bps'],
                    'feature_available_ts_ms': t['signal']['meta']['feature_available_ts_ms']},
                'admission_decision': 'NOT_EVALUATED_REQUIRED_INPUT_RISK_BUDGET_AND_QUANTITY'}
            entry_snapshots.append(snapshot)
        for phase, rows, field in [('ENTRY', entering, 'entry_ts_ms'),
                                   ('EXIT_RECORDED', exits, 'exit_ts_ms'),
                                   ('OUTCOME_KNOWN', outcomes, 'outcome_available_ts_ms')]:
            for t in rows:
                e = {'event_id': '|'.join(map(str, (*key(t), phase))), 'kind': phase,
                     'ts_ms': t[field], 'trade_key': list(key(t)), 'window_label': t['window_label'],
                     'native_outcome_ordinal_for_report_only': ordinal[key(t)]}
                if phase == 'ENTRY':
                    e['snapshot_index'] = next(i for i, s in enumerate(entry_snapshots) if tuple(s['trade_key']) == key(t))
                elif phase == 'EXIT_RECORDED':
                    e['available_ts_ms'] = t['outcome_available_ts_ms']
                    e['precision'] = t.get('outcome_time_precision')
                    e['release_budget_from_this_record_alone'] = False
                else:
                    e['report_labels_now_available'] = {
                        'gross_trade_bps': t['gross_bps'], 'final_cost_trade_bps': t['cost_bps'],
                        'net1x_trade_bps': t['net_bps'],
                        'net2x_trade_bps': t['gross_bps']-2*t['cost_bps']}
                events.append(e)
        if outcomes:
            signs = [t['net_bps'] for t in outcomes]
            kind = ('MIXED_SIGNS' if min(signs) < 0 < max(signs) else
                    'ALL_LOSSES' if max(signs) < 0 else 'NONNEGATIVE_OR_ZERO')
            batches.append({'ts_ms': stamp, 'keys_in_native_report_order': [list(key(t)) for t in outcomes],
                'kind': kind, 'row_count': len(outcomes),
                'net1x_trade_bps': math.fsum(signs),
                'net2x_trade_bps': math.fsum(t['gross_bps']-2*t['cost_bps'] for t in outcomes),
                'does_not_replace_native_loss_streak': True})
    return {'native_outcome_key_index': [list(key(t)) for t in ordered],
            'history_ref_semantics': 'native_outcome_refs index native_outcome_key_index; exact source reporting order, not admission priority',
            'events': events, 'entry_snapshots': entry_snapshots,
            'outcome_batches': batches, 'outcome_batch_counts': dict(Counter(b['kind'] for b in batches)),
            'event_counts': dict(Counter(e['kind'] for e in events)),
            'simultaneous_entry_outcome_timestamps': sorted({t['entry_ts_ms'] for t in trades} &
                                                          {t['outcome_available_ts_ms'] for t in trades})}


def all_directional_clusters(trades):
    """Connected positive-overlap components; include singletons for full coverage.

    Edges require same window/side and positive holding overlap. A connected
    component need not hold every member simultaneously; segments show exactly who did.
    """
    grouped = defaultdict(list)
    for t in trades:
        grouped[(t['window_label'], t['side'])].append(t)
    clusters = []
    for (window, side), members in sorted(grouped.items()):
        members = sorted(members, key=lambda t: (t['entry_ts_ms'], native_order(t)))
        components = []
        for t in members:
            if not components or t['entry_ts_ms'] >= max(u['outcome_available_ts_ms'] for u in components[-1]):
                components.append([t])
            else:
                components[-1].append(t)
        for comp in components:
            boundaries = sorted({t[f] for t in comp for f in ('entry_ts_ms', 'outcome_available_ts_ms')})
            segments = []
            for start, end in zip(boundaries, boundaries[1:]):
                active = [t for t in comp if t['entry_ts_ms'] <= start < t['outcome_available_ts_ms']]
                if len(active) >= 2:
                    segments.append({'start_ms': start, 'end_ms_exclusive': end,
                                     'keys': [list(key(t)) for t in active]})
            wins = [t for t in comp if t['net_bps'] > 0]
            losses = [t for t in comp if t['net_bps'] < 0]
            large = [t for t in wins if t['mfe_R'] >= 2]  # Existing diagnostic cohort only.
            coentries = defaultdict(list)
            for t in comp:
                coentries[t['entry_ts_ms']].append(list(key(t)))
            clusters.append({'cluster_id': f'{window}:{side}:{min(t["entry_ts_ms"] for t in comp)}',
                'window_label': window, 'side': side, 'keys': [list(key(t)) for t in comp],
                'count': len(comp), 'concurrent': len(comp) > 1,
                'peak_simultaneous': max([len(s['keys']) for s in segments] or [1]),
                'overlap_segments': segments,
                'coentry_batches': [{'ts_ms': stamp, 'keys': keys} for stamp, keys in coentries.items() if len(keys) > 1],
                'post_outcome_labels_NOT_ADMISSION_FEATURES': {
                    'cohort': 'ALL_WINNERS' if len(wins) == len(comp) else 'ALL_LOSSES' if len(losses) == len(comp) else 'MIXED',
                    'winner_count': len(wins), 'loser_count': len(losses),
                    'large_winner_keys': [list(key(t)) for t in large],
                    'net1x_trade_bps': math.fsum(t['net_bps'] for t in comp),
                    'net2x_trade_bps': math.fsum(t['gross_bps']-2*t['cost_bps'] for t in comp)}})
    concurrent = [c for c in clusters if c['concurrent']]
    return {'definition': 'Same window and direction, connected positive-overlap components; exact active segments retained.',
        'labels_are_posthoc_only': True, 'large_winner_definition_from_existing_run_compare': 'net1x > 0 AND mfe_R >= 2',
        'cluster_count': len(clusters), 'concurrent_cluster_count': len(concurrent),
        'concurrent_cohort_counts': dict(Counter(c['post_outcome_labels_NOT_ADMISSION_FEATURES']['cohort'] for c in concurrent)),
        'trade_coverage': sum(c['count'] for c in clusters),
        'winner_coverage': sum(c['post_outcome_labels_NOT_ADMISSION_FEATURES']['winner_count'] for c in clusters),
        'large_winner_coverage': sum(len(c['post_outcome_labels_NOT_ADMISSION_FEATURES']['large_winner_keys']) for c in clusters),
        'clusters': clusters}


def assemble(values, normalizer):
    payload = values['current/ROWS.json.gz']
    summary = values['current/SUMMARY.json']
    geometry = values['diagnostic/ENTRY_GEOMETRY_ALL126.json']
    paths = values['diagnostic/RAW_PATHS_ALL126.json.gz']
    audit = audit_inputs(payload, geometry, paths, normalizer)
    stream = build_stream(payload['trades'], geometry, paths)
    return {'schema': 'zel.work_d.k126.causal_exposure.v1',
        'classification': 'SAVED_LIFECYCLE_CAUSAL_STREAM_NOT_NEW_ECONOMICS',
        'baseline_ref': CURRENT_REF, 'diagnostic_ref': DIAG_REF, 'identity': CURRENT_ID,
        'input_sha256': PINS, 'normalizer_reused_sha256': REUSE_SHA, 'normalizer_audit': audit,
        'time_policy': 'ENTRY_BATCH_THEN_RECORDED_EXIT_THEN_OUTCOME_BATCH_WHEN_GLOBAL_ORDER_UNBOUND',
        'source_row_loss_metrics_copied_unchanged': summary['child'],
        'do_not_treat_outcome_batch_count_as_loss_streak_improvement': True,
        'admission_status': 'REQUIRED_INPUT', 'economic_FULL': 0, **stream}, all_directional_clusters(payload['trades'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', required=True, help='directory containing pinned current/ and diagnostic/ files')
    parser.add_argument('--output-dir', required=True, help='add-only output directory')
    parser.add_argument('--completed-d-normalizer', default=str(Path(__file__).resolve().parents[2] /
                        'portfolio_coverage_v1/work_d/contribution_report.py'))
    args = parser.parse_args()
    values = load_inputs(args.input_root)
    events, clusters = assemble(values, load_reused_normalizer(args.completed_d_normalizer))
    out = Path(args.output_dir)
    names = ['CAUSAL_EXPOSURE_EVENTS.json', 'DIRECTIONAL_COHORTS.json']
    if any((out / name).exists() for name in names):
        raise ValueError('ADD_ONLY_OUTPUT_ALREADY_EXISTS')
    out.mkdir(parents=True, exist_ok=True)
    for name, value in zip(names, [events, clusters]):
        with (out / name).open('x') as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(json.dumps({'event_counts': events['event_counts'], 'outcome_batches': len(events['outcome_batches']),
                      'trade_coverage': clusters['trade_coverage'], 'concurrent_clusters': clusters['concurrent_cluster_count'],
                      'cohorts': clusters['concurrent_cohort_counts'], 'economic_FULL': 0}))


if __name__ == '__main__':
    main()
