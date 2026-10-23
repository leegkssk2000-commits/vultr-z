#!/usr/bin/env python3
"""Offline receipt-cohort guard. No evaluator imports, network, or trading authority.

A valid binding certifies these saved bytes and structural joins only. It does not
certify raw bars, fills, live PnL, temporal availability, or a strategy edge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import zipfile

CANDIDATE = 'trend_rider_delayed_fill_long_only_v1'
PARENT = 'trend_rider_one_bar_delayed_fill_v1'
TERMINAL = 'CURRENT_TRENDRIDER_NO_CAUSAL_CHILD'


class GuardError(ValueError):
    pass


def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False, default=str).encode()).hexdigest()


def canonical_sha(record):
    return stable({k: v for k, v in record.items() if k != 'receipt_sha256'})


def require(condition, message):
    if not condition:
        raise GuardError(message)


def verified_receipt(record, expected=None):
    require(isinstance(record, dict), 'RECEIPT_OBJECT_REQUIRED')
    require(record.get('receipt_sha256') == canonical_sha(record), 'RECEIPT_DIGEST_MISMATCH')
    if expected is not None:
        require(record['receipt_sha256'] == expected, 'PINNED_RECEIPT_MISMATCH')


def blocked_authority(record):
    for k, v in {'execution_authority': 'NONE', 'order_authority': 'BLOCKED',
                 'live_trade_authority': 'BLOCKED', 'selection_authority': False,
                 'promotion_authority': False, 'protected_mutations': 0}.items():
        require(record.get(k) == v, 'AUTHORITY_MISMATCH:' + k)
    require(record.get('exchange_order_submitted', False) is False, 'ORDER_SUBMITTED')


def _ms(value):
    return int(datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).timestamp() * 1000)


def _close(a, b):
    try:
        return math.isfinite(float(a)) and math.isfinite(float(b)) and math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-7)
    except (ValueError, TypeError, OverflowError):
        return False


def load_pinned_bundle(root, cohort_name):
    root = Path(root)
    manifest = json.loads((root / 'PINNED_INPUTS.json').read_text())
    require(cohort_name in manifest['cohorts'], 'UNPINNED_COHORT')
    pin = manifest['cohorts'][cohort_name]
    archive = root / pin['path']
    require(hashlib.sha256(archive.read_bytes()).hexdigest() == pin['archive_sha256'], 'ARCHIVE_SHA_MISMATCH')
    result = {}
    with zipfile.ZipFile(archive) as z:
        require(len(z.namelist()) == len(set(z.namelist())), 'DUPLICATE_ARCHIVE_MEMBERS')
        require(set(z.namelist()) == {i['name'] for i in pin['archive_inventory']}, 'ARCHIVE_INVENTORY_MISMATCH')
        for item in pin['archive_inventory']:
            raw = z.read(item['name'])
            require(len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'], 'ARCHIVE_MEMBER_SHA_MISMATCH')
        for role, item in pin['members'].items():
            raw = z.read(item['name'])
            require(hashlib.sha256(raw).hexdigest() == item['raw_sha256'], 'MEMBER_SHA_MISMATCH:' + role)
            result[role] = json.loads(raw)
            verified_receipt(result[role], item['receipt_sha256'])
    return result


def validate_bundle(receipt, hardening, parent, native_parent, cohort_pin):
    for role, obj in [('receipt', receipt), ('hardening', hardening), ('parent', parent), ('native_parent', native_parent)]:
        verified_receipt(obj, cohort_pin['members'][role]['receipt_sha256'])
        blocked_authority(obj)
    require(receipt.get('schema_version') == 'zel.a1.trend_rider.long_only_exact_parent_economics.v1', 'CHILD_SCHEMA_MISMATCH')
    require(receipt.get('challenger_id') == CANDIDATE and receipt.get('strategy_id') == 'trend_rider', 'CHILD_IDENTITY_MISMATCH')
    require(parent.get('challenger_id') == PARENT and receipt.get('parent_challenger_id') == PARENT, 'PARENT_IDENTITY_MISMATCH')
    require(receipt.get('evaluation_mode') == parent.get('evaluation_mode') == 'prospective', 'PROSPECTIVE_REQUIRED')
    require(receipt.get('parent_receipt_sha256') == parent['receipt_sha256'], 'PARENT_RECEIPT_JOIN_MISMATCH')
    require(receipt.get('prospective_boundary_utc') == receipt.get('boundary_utc') == cohort_pin['boundary_utc'], 'BOUNDARY_MISMATCH')
    # Parent boundary is legitimately Aug 21; frozen long-only child is Aug 22.
    require(parent['boundary_utc'] == native_parent['boundary_utc'], 'NATIVE_PARENT_BOUNDARY_MISMATCH')
    require(parent['execution_snapshots'] == native_parent['execution_snapshots'], 'NATIVE_PARENT_SNAPSHOT_MISMATCH')
    require(parent['source'] == native_parent['source'], 'NATIVE_PARENT_SOURCE_MISMATCH')
    original_by_intent = {x['intent_sha']: x for x in native_parent['trades']}
    require(len(original_by_intent) == len(native_parent['trades']), 'NATIVE_PARENT_DUPLICATE_INTENT')
    for delayed in parent['trades']:
        original = original_by_intent.get(delayed.get('parent_intent_sha'))
        require(original is not None, 'NATIVE_PARENT_INTENT_MISSING')
        require(delayed['parent_entry_ts'] == original['entry_ts'], 'NATIVE_PARENT_ENTRY_MISMATCH')
        for key in ('symbol', 'side', 'signal_ts', 'feature_sha', 'config_sha', 'policy_sha',
                    'intent_geometry', 'realized_cost_bps', 'cost_snapshot_sha'):
            require(delayed.get(key) == original.get(key), 'NATIVE_PARENT_ROW_JOIN_MISMATCH:' + key)
    for k in ('policy_sha', 'config_sha', 'cost_authority_sha256'):
        require(receipt.get(k) == cohort_pin[k], 'PIN_MISMATCH:' + k)
        require(hardening.get(k) == receipt[k], 'HARDENING_JOIN_MISMATCH:' + k)
        require(parent.get(k) == receipt[k], 'PARENT_JOIN_MISMATCH:' + k)
    require(stable(receipt['source']) == cohort_pin['source_sha256'], 'SOURCE_METADATA_MISMATCH')
    require(receipt['source'].get('interval') == '1h', 'TIMEFRAME_MISMATCH')
    symbols = {x['symbol'] for x in receipt['source']['symbols']}
    require(len(symbols) == len(receipt['source']['symbols']) == 12, 'SOURCE_SYMBOLS_MISMATCH')
    require(receipt['source_quality_gate'].get('state') == 'PASS', 'STORED_SOURCE_GATE_NOT_PASS')
    require(receipt.get('integrity_defects') == [] and receipt.get('leakage_lookahead') == 0, 'STORED_INTEGRITY_NOT_CLEAR')
    rows = receipt['trades']
    require(len(rows) == receipt['completed_trades'] == cohort_pin['trade_count'], 'TRADE_COUNT_MISMATCH')
    require(len(parent['trades']) == parent['completed_trades'] == receipt['parent_completed_trades'], 'PARENT_COUNT_MISMATCH')
    expected = [x for x in parent['trades'] if x['side'] == 'long' and x['entry_ts'] >= _ms(receipt['boundary_utc'])]
    require(rows == expected, 'EXACT_PARENT_LONG_SUBSET_MISMATCH')
    keys = [(x['symbol'], x['side'], x['signal_ts'], x['entry_ts']) for x in rows]
    require(len(keys) == len(set(keys)), 'DUPLICATE_EVENT_PROXY')
    snapshots = receipt['execution_snapshots']
    for row in rows:
        for key in ('entry', 'exit', 'gross_bps', 'realized_cost_bps', 'net_bps'):
            require(isinstance(row.get(key), (int, float)) and not isinstance(row[key], bool), 'ROW_NUMERIC_INVALID:' + key)
        require(row['side'] == 'long' and row['symbol'] in symbols, 'ROW_IDENTITY_MISMATCH')
        require(_ms(receipt['boundary_utc']) <= row['signal_ts'] < row['entry_ts'] <= row['exit_ts'], 'ROW_TIME_ORDER_MISMATCH')
        require(row['entry_delay_bars'] == 1 and row['entry_ts'] - row['signal_ts'] == 7200000, 'DELAY_MISMATCH')
        require(row['cost_snapshot_sha'] == snapshots[row['symbol']]['snapshot_sha256'], 'COST_SNAPSHOT_JOIN_MISMATCH')
        require(row['policy_sha'] == receipt['policy_sha'], 'ROW_POLICY_MISMATCH')
        require(row['feature_sha'] == row['intent_geometry']['feature_sha'], 'FEATURE_HASH_JOIN_MISMATCH')
        require(float(row['entry']) > 0 and float(row['exit']) > 0, 'ROW_PRICE_INVALID')
        require(_close(row['gross_bps'], (row['exit'] / row['entry'] - 1) * 10000), 'GROSS_ARITHMETIC_MISMATCH')
        require(float(row['realized_cost_bps']) >= 0, 'NEGATIVE_STORED_COST')
        require(_close(row['net_bps'], row['gross_bps'] - row['realized_cost_bps']), 'NET_ARITHMETIC_MISMATCH')
    require(_close(sum(x['net_bps'] for x in rows), receipt['metrics']['net_pnl_bps']), 'METRIC_NET_MISMATCH')
    require(_close(sum(x['gross_bps'] for x in rows), receipt['metrics']['gross_pnl_bps']), 'METRIC_GROSS_MISMATCH')
    require(hardening.get('strategy_id') == receipt['strategy_id'], 'HARDENING_STRATEGY_MISMATCH')
    require(hardening.get('candidate_receipt_sha256') == receipt['receipt_sha256'], 'HARDENING_RECEIPT_JOIN_MISMATCH')
    require(hardening.get('candidate_trade_count') == len(rows), 'HARDENING_COUNT_MISMATCH')
    require(hardening.get('boundary_utc') == receipt['boundary_utc'], 'HARDENING_BOUNDARY_MISMATCH')
    h4, h5 = hardening['h4_receipt'], hardening['h5_receipt']
    verified_receipt(h4); verified_receipt(h5)
    window = stable({'boundary': receipt['boundary_utc'], 'latest_exit': max(x['exit_ts'] for x in rows), 'symbols': sorted(symbols), 'trade_count': len(rows)})
    require(h4['window_sha256'] == h5['holdout_window_sha256'] == window, 'HARDENING_WINDOW_MISMATCH')
    require(h4['candidate_trade_count'] == len(rows) and h4['cost_model_sha256'] == receipt['cost_authority_sha256'], 'H4_COHORT_MISMATCH')
    require(hardening['candidate_integrity']['state'] == 'PASS', 'HARDENING_INTEGRITY_NOT_PASS')
    # Fail closed: these archives contain feature digests, not matching bodies or
    # original OHLC prefixes with completed-bar availability. No causal child.
    return {
        'integrity': 'PASS_PINNED_RECEIPT_BINDING',
        'qualification': 'SAVED_BYTES_AND_STRUCTURAL_JOINS_ONLY',
        'cohort': cohort_pin['label'], 'trade_count': len(rows),
        'native_receipt_sha256': receipt['receipt_sha256'],
        'hardening_receipt_sha256': hardening['receipt_sha256'],
        'native_source_checkout': cohort_pin['actual_checkout_sha'],
        'source_feature_gate': 'SOURCE_FEATURE_BLOCKED',
        'first_missing_input': 'FULL_FEATURESNAPSHOT_MATCHING_EACH_ORIGINAL_SIGNAL_FEATURE_SHA_WITH_RAW_PREFIX_AND_COMPLETED_BAR_AVAILABLE_TS',
        'feature_digest_count': sum(bool(x.get('feature_sha')) for x in rows),
        'feature_body_count': 0, 'completed_bar_availability_verified': False,
        'stored_SL_exit_not_equal_sealed_SL_count': sum(x['reason'] == 'SL' and x['exit'] != x['intent_geometry']['sl'] for x in rows),
        'SL_geometry_qualification': 'SAVED_VALUES_ONLY; refreshed delayed ATR stop may differ from copied parent geometry; no raw-bar causal proof',
        'native_parent_join': 'PINNED_ARCHIVE_PLUS_SOURCE_SNAPSHOTS_PARENT_INTENT_AND_PRESERVED_ROW_FIELDS',
        'h4_state': h4['state'], 'h4_passed_control_count': h4['passed_control_count'],
        'h4_same_windows_costs_trade_budget_verified': h4['same_windows_costs_trade_budget_verified'],
        'h4_control_results': h4['control_results'],
        'h4_unit': 'NATIVE_NET_BPS_DIVIDED_BY_100_NOT_STOP_RISK_R',
        'h4_inner_candidate_digest_verifiable': False,
        'h4_inner_candidate_digest_reason': 'REPLAY_SUMMARY_AND_RAW_CONTROL_VECTORS_NOT_ARCHIVED',
        'h5_state': h5['state'], 'h5_blockers': h5['blockers'],
        'h5_regime_labels': 'UNSEALED_DIAGNOSTIC_FROM_SEPARATE_FETCH_NOT_ENTRY_FEATURE_BODY',
        'terminal': TERMINAL, 'candidate_child': None,
        'economic_full': 'NOT_RUN', 'native_replay': 'NOT_RUN', 'account_dd': None,
        'selection_authority': False, 'promotion_authority': False,
        'execution_authority': 'NONE', 'order_authority': 'BLOCKED',
    }


def validate_summary(summary, receipt, hardening, pin):
    verified_receipt(summary, pin['members']['summary']['receipt_sha256'])
    blocked_authority(summary)
    require(summary.get('candidate_id', summary.get('challenger_id')) == CANDIDATE, 'SUMMARY_IDENTITY_MISMATCH')
    require(summary['fresh_trade_count'] == len(receipt['trades']), 'SUMMARY_COUNT_MISMATCH')
    require(summary['fresh_metrics'] == receipt['metrics'], 'SUMMARY_METRICS_MISMATCH')
    require(summary.get('fresh_boundary_utc', summary.get('fresh_boundary')) == receipt['boundary_utc'], 'SUMMARY_BOUNDARY_MISMATCH')
    if 'h4_state' in summary:
        require(summary['h4_state'] == hardening['h4_receipt']['state'] and summary['h5_state'] == hardening['h5_receipt']['state'], 'SUMMARY_HARDENING_STATE_MISMATCH')
    else:
        require(summary['fresh_hardening_state'] == hardening['state'], 'SUMMARY_FRESH_HARDENING_MISMATCH')
    return {'state': 'PASS_SAME_ARCHIVE_SUMMARY_JOIN', 'summary_native_candidate_hash_field_present': False,
            'qualification': 'ARCHIVE_PIN_PLUS_IDENTITY_BOUNDARY_COUNT_METRIC_EQUALITY; native summary lacks direct fresh receipt digest'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inputs-root', type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    from attribution import build_attribution, compare_snapshots
    pins = json.loads((args.inputs_root / 'PINNED_INPUTS.json').read_text())
    bundles = {}; output = {'schema': 'work_d.current_trendrider.structural_guard.v1', 'terminal': TERMINAL, 'cohorts': {}}
    for name, pin in pins['cohorts'].items():
        b = load_pinned_bundle(args.inputs_root, name); bundles[name] = b
        guard = validate_bundle(b['receipt'], b['hardening'], b['parent'], b['native_parent'], pin)
        summary = validate_summary(b['summary'], b['receipt'], b['hardening'], pin)
        output['cohorts'][name] = {'guard': guard, 'summary_join': summary, 'attribution': build_attribution(b['receipt'], name)}
    output['snapshot_comparison'] = compare_snapshots(bundles['current255']['receipt'], bundles['later256']['receipt'])
    output['separate_lanes'] = []
    for lane in pins['separate_lanes']:
        raw = (args.inputs_root / lane['path']).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == lane['sha256'], 'SEPARATE_LANE_SHA_MISMATCH')
        output['separate_lanes'].append({**lane, 'joined_to_current_trendrider': False})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(json.dumps({'terminal': TERMINAL, 'output_sha256': hashlib.sha256(args.out.read_bytes()).hexdigest(),
                      'cohorts': {k: v['guard']['trade_count'] for k, v in output['cohorts'].items()}}))


if __name__ == '__main__':
    main()
