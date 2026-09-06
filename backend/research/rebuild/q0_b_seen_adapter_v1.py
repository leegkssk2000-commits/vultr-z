"""Bounded inputs and unchanged Q0 execution for one seen-period replication.

This is a separate research permission; sealed DEV loaders and guards are
unchanged. The adapter has no CLI, data acquisition, optimization or writes.
It reuses the original channel execution, costs, daily marks and entry weights.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path

from backend.research.rebuild import break_channel_source_v1 as source
from backend.research.rebuild import q0_risk_entry_v1 as original
from backend.research.rebuild import q0_risk_entry_weights_v1 as weights

old = source.old
structure = source.structure
DAY, BAR = structure.DAY, structure.INTERVAL
EVIDENCE_TYPE = 'SEEN_DATA_REPLICATION'
SOURCE_START = 1734595200000
ORIGINAL_START = 1738108800000
EVAL_START, EVAL_END = 1778198400000, 1788566400000
REFERENCE = {'N': 38, 'ddof': 1, 'first_available_at': 1734825600000,
             'last_available_at': 1738022400000,
             'sigma_ref': 0.03290943045427639}
SYMBOLS = ('1000PEPE-USDT', 'BCH-USDT', 'BTC-USDT', 'ETH-USDT',
           'HYPE-USDT', 'LINK-USDT', 'SOL-USDT')


def _prefix(path, start, end):
    """Decode exactly the approved prefix, including the final mark bar only."""
    if (type(start) is not int or type(end) is not int or start >= end
            or start % BAR or end % BAR):
        raise RuntimeError('SEEN_PREFIX_BOUNDS_INVALID')
    count = (end - start) // BAR
    rows = old.probe.prefix_rows(Path(path), count)
    old.common.evaluate_development_events(
        rows, [], split_start_ms=start, split_end_ms=end,
        interval_ms=BAR, hold_bars=1)
    if rows[0]['bar_open_ts'] != start or rows[-1]['bar_close_ts'] != end:
        raise RuntimeError('SEEN_PREFIX_COVERAGE')
    return rows


def _partition_access(rows, splits, start, end):
    """Original split names are usage labels, never independence claims."""
    counts = {}
    for name in ('development', 'validation', 'purged_OOS'):
        left, right = splits[name]
        counts[name] = sum(left <= r['bar_open_ts'] < right for r in rows)
    counts['embargo'] = len(rows) - sum(counts.values())
    warmup = sum(r['bar_close_ts'] <= start for r in rows)
    evaluation = sum(start <= r['bar_open_ts'] < end for r in rows)
    if warmup + evaluation != len(rows):
        raise RuntimeError('SEEN_WARMUP_EVALUATION_ACCOUNTING')
    return {'decoded_rows': len(rows), 'original_partition_decoded_rows': counts,
            'decoded_validation_rows': counts['validation'],
            'decoded_OOS_rows': counts['purged_OOS'],
            'warmup_rows': warmup, 'evaluation_rows': evaluation,
            'first_open_ms': rows[0]['bar_open_ts'],
            'last_close_ms': rows[-1]['bar_close_ts'],
            'decoded_prefix_sha256': old.digest(rows),
            'rows_after_evaluation_end_decoded': 0,
            'raw_archive_decoded': False, 'full_file_checksum_opaque': True,
            'warmup_economic_evaluation': False,
            'evidence_type': EVIDENCE_TYPE, 'independent': False}


def load_seen_inputs(data_dir, contract):
    """Use frozen canonical 4h files and original research cost authority.

The caller verifies the new contract/code seal before this method. Metadata
and full-file byte hashes are verified before any new OHLCV object is decoded.
Only canonical ohlcv/ files are allowed, never the longer raw_ohlcv/ archive.
"""
    if (contract['evaluation_interval_ms'] != [EVAL_START, EVAL_END]
            or contract['source_prefix_start_ms'] != SOURCE_START
            or contract['symbols'] != list(SYMBOLS)
            or contract['evidence_type'] != EVIDENCE_TYPE
            or contract['independent'] is not False
            or contract['reference'] != REFERENCE):
        raise RuntimeError('SEEN_AUTHORIZED_SCOPE_DRIFT')
    data_dir = Path(data_dir)
    policy = old.read(old.POLICY)
    dev = source.inputs.require_development(old.read(old.probe.STAGE), old.ROOT)
    manifest_path = data_dir / 'development_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    old.probe.verify_seal(manifest, 'SEEN_MANIFEST')
    old_probe = old.read(old.probe.POLICY)
    if (manifest['receipt_sha256'] != contract['manifest_sha256']
            or manifest['receipt_sha256'] != old_probe['manifest_sha256']
            or manifest['dataset_sha256'] != contract['dataset_sha256']
            or old.digest(manifest['dataset_files']) != manifest['dataset_sha256']
            or manifest['splits'] != dev['splits']
            or manifest['outcomes_computed'] is not False
            or set(manifest['symbols']) != set(SYMBOLS)
            or set(dev['cost_by_symbol']) != set(SYMBOLS)
            or dev['receipt_sha256'] != contract['cost_sha256']
            or policy['cost_binding_sha256'] != contract['cost_sha256']):
        raise RuntimeError('SEEN_DATA_COST_METADATA_IDENTITY')
    paths = {s: data_dir / ('ohlcv/' + s + '.json') for s in SYMBOLS}
    cost_paths = {s: data_dir / manifest['cost_snapshots'][s]['path'] for s in SYMBOLS}
    allowed = [manifest_path, *paths.values(), *cost_paths.values()]
    rows_by, access = {}, {}
    with old.probe.io_boundary(allowed, old.ROOT / 'seen_input_no_writes'):
        # Fail all source identities before starting even the first price decode.
        for symbol, path in paths.items():
            if old.file_sha(path) != manifest['dataset_files']['ohlcv/' + symbol + '.json']:
                raise RuntimeError('SEEN_SOURCE_BYTES_IDENTITY:' + symbol)
            ref, cost_path = manifest['cost_snapshots'][symbol], cost_paths[symbol]
            if old.file_sha(cost_path) != ref['sha256']:
                raise RuntimeError('SEEN_COST_BYTES_IDENTITY:' + symbol)
            snapshot = json.loads(cost_path.read_text())['snapshot']
            if snapshot['snapshot_sha256'] != old.digest({k: v for k, v in snapshot.items()
                                                         if k != 'snapshot_sha256'}):
                raise RuntimeError('SEEN_COST_SNAPSHOT_SEAL:' + symbol)
            cost = dev['cost_by_symbol'][symbol]
            if (cost['snapshot_sha256'] != snapshot['snapshot_sha256']
                    or cost['spread_bps'] != snapshot['charged_spread_round_trip_bps']
                    or cost['impact_bps'] != snapshot['charged_impact_round_trip_bps']
                    or cost['funding_p95_per_settlement_bps'] != snapshot['funding_p95_abs_bps']):
                raise RuntimeError('SEEN_COST_BINDING_PARITY:' + symbol)
        for symbol, path in paths.items():
            rows = _prefix(path, SOURCE_START, EVAL_END)
            rows_by[symbol] = rows
            access[symbol] = _partition_access(rows, manifest['splits'], EVAL_START, EVAL_END)
    policy = {**policy, 'batch_id': contract['batch_id'],
              'receipt_sha256': contract['receipt_sha256'],
              'combined_data_sha256': contract['data_sha256'],
              'cost_binding_sha256': contract['cost_sha256'],
              'development_interval_ms': [EVAL_START, EVAL_END],
              'code_files_sha256': contract['code_files_sha256']}
    return policy, dev, rows_by, access


def _bound_market_state(rows_by, symbols, start, end, reference_start, reference):
    """Keep original reference lineage while permitting a later entry calendar."""
    if not reference_start <= start < end:
        raise RuntimeError('SEEN_MARKET_REFERENCE_CALENDAR')
    state = weights.market_state(rows_by, symbols, reference_start, end)
    actual = {k: state['reference'][k] for k in ('N', 'ddof', 'first_available_at', 'last_available_at')}
    if actual != {k: reference[k] for k in actual}:
        raise RuntimeError('SEEN_ORIGINAL_REFERENCE_LINEAGE')
    if not math.isclose(state['sigma_ref'], reference['sigma_ref'], rel_tol=1e-12, abs_tol=1e-15):
        raise RuntimeError('SEEN_ORIGINAL_REFERENCE_SIGMA')
    # Use the fixed scalar even if a platform's stdev rounds at the last bit.
    state['sigma_ref'] = reference['sigma_ref']
    state['eval_start_ms'] = start
    state['audit']['returns_available_at_eval_start'] = sum(
        row['available_at'] <= start for row in state['returns'])
    state['reference_binding'] = {
        'source': original.CONTRACT, 'original_eval_start_ms': reference_start,
        'new_eval_start_ms': start, 'reestimated_from_new_warmup': False,
        'reference_rule': 'ORIGINAL_STRICT_PRE_EVALUATION_38_RETURNS',
        'frozen_reference': deepcopy(reference)}
    return state


def frozen_market_state(rows_by, symbols, start, end):
    return _bound_market_state(rows_by, symbols, start, end, ORIGINAL_START, REFERENCE)


def _evidence(row, evidence_type):
    if evidence_type is None:
        return row
    if evidence_type != EVIDENCE_TYPE:
        raise RuntimeError('SEEN_EVIDENCE_GRADE_REQUIRED')
    seal_key = 'trade_sha256' if 'trade_sha256' in row else 'observation_sha256'
    row.pop(seal_key, None)
    row.update(split=EVIDENCE_TYPE, evidence_type=EVIDENCE_TYPE,
               independent=False, formal_credit=0, operating_adoption=False)
    row[seal_key] = old.digest(row)
    return row


def replay_q0(rows_by, costs, policy, symbols, start, end, *, stage='Q', evidence_type=None):
    """Fresh flat Q0 ownership; prior channel attempts remain causally initialized.

No warmup trade or pending order can carry across start. A confirmation at
start may fill that next open, but earlier confirmations are never replayed.
End-close marks are retained; signals/entries at end are forbidden by Q0.
"""
    if (sorted(rows_by) != sorted(symbols) or set(costs) != set(symbols)
            or type(start) is not int or type(end) is not int
            or start >= end or start % DAY or end % DAY):
        raise RuntimeError('SEEN_REPLAY_SCOPE')
    result = {key: [] for key in ('trades', 'open_observations', 'events',
                                  'daily_bars', 'daily_valuation', 'trace')}
    result['admission'] = {}
    for symbol in symbols:
        rows = rows_by[symbol]
        aggregate = structure.aggregate_daily(rows, split_end_ms=end)
        if not aggregate['daily'] or aggregate['daily'][-1]['bar_close_ts'] != end:
            raise RuntimeError('SEEN_COMPLETE_TERMINAL_DAY_REQUIRED:' + symbol)
        bundle = structure.generate_signals(aggregate['daily'], eval_start_ms=start,
                                            eval_end_ms=end, require_preparation=True)
        raw = structure.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end)
        result['trades'].extend(_evidence(source.charge(t, symbol, stage, policy, costs, rows), evidence_type)
                                for t in raw['trades'])
        result['open_observations'].extend(_evidence(source.charge_open(t, symbol, stage, policy, costs, rows), evidence_type)
                                           for t in raw['open_positions'])
        result['events'].extend(dict(e, symbol=symbol, lane_id=source.LANE,
                                     comparison_stage=stage, scenario=stage) for e in raw['events'])
        result['daily_bars'].extend(dict(d, symbol=symbol) for d in aggregate['daily'])
        for layer, trace in (('REPLAY', raw['trace']), ('SIGNAL', bundle['trace'])):
            result['trace'].extend(dict(t, symbol=symbol, comparison_stage=stage,
                                        trace_layer=layer) for t in trace)
        audit = deepcopy(raw['audit'])
        audit['signal_audit'] = deepcopy(bundle['audit'])
        audit['signal_audit']['common_calendar_reason_counts'] = dict(sorted(Counter(
            t['reason'] for t in bundle['trace'] if t.get('reason') and start <= t['ts'] < end).items()))
        result['admission'][symbol] = {'aggregation': aggregate['audit'], 'stages': {stage: audit}}
    result['daily_valuation'] = [dict(t, comparison_stage=stage) for t in source.daily_valuation(
        result['trades'], result['open_observations'], rows_by, costs, start, end)]
    return result


def verify_dev_parity(data_dir):
    """Replay only original DEV and compare sealed Q0 ledger and marked path."""
    contract = source.authorize()
    policy, dev, rows, _, access = source.inputs.load_inputs(Path(data_dir))
    start, end = contract['evaluation_interval_ms']
    policy = {**policy, 'batch_id': contract['batch_id'],
              'receipt_sha256': contract['receipt_sha256'],
              'development_interval_ms': [start, end],
              'code_files_sha256': {**policy['code_files_sha256'], **contract['code_files_sha256']}}
    actual = replay_q0(rows, dev['cost_by_symbol'], policy, contract['symbols'], start, end)
    q0 = old.read(source.OUTPUT + '/receipt.json')
    parent = original.load_parent(q0)
    for key in ('trades', 'open_observations', 'events', 'daily_bars', 'daily_valuation'):
        if actual[key] != parent[key]:
            raise RuntimeError('SEEN_ORIGINAL_Q0_REPLAY_PARITY:' + key)
    for symbol in contract['symbols']:
        if actual['admission'][symbol]['stages']['Q'] != q0['admission'][symbol]['stages']['Q']:
            raise RuntimeError('SEEN_ORIGINAL_Q0_ADMISSION_PARITY:' + symbol)
    market = frozen_market_state(rows, contract['symbols'], start, end)
    return {'status': 'PASS', 'original_Q0_replay': 'EXACT_LEDGER_EVENTS_DAILY_PARITY',
            'original_Q0_receipt_sha256': q0['receipt_sha256'],
            'matched_closed_T': len(actual['trades']),
            'matched_open_T': len(actual['open_observations']),
            'matched_signals': len(actual['events']),
            'sigma_ref': market['sigma_ref'], 'reference': market['reference'],
            'decoded_validation_rows': sum(x['decoded_validation_rows'] for x in access.values()),
            'decoded_OOS_rows': sum(x['decoded_OOS_rows'] for x in access.values()),
            'new_evaluation_consumed': False}
