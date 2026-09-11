"""Issue1284: archived observed WS prefix plus bounded closed REST witness.

No heuristic timestamp correction and no WS connection. The single caller owns
real I/O; injectable transports support the identical offline regression path.
Every request, response and application body is persisted before decoding.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
from pathlib import Path

from backend.research.rebuild import trendrider_common_source_v1 as base
from backend.research.rebuild import trendrider_rest_ws_timestamp_v2 as old
from backend.research.rebuild import trendrider_observed_ws_schema_v1 as observed

SourceIntegrityError = base.SourceIntegrityError
canonical_bytes, digest_bytes, write_once = base.canonical_bytes, base.digest_bytes, base.write_once
sealed, check_seal = old.sealed, old.check_seal
HOUR_MS, SYMBOL, CHANNEL = old.HOUR_MS, old.SYMBOL, old.CHANNEL
SCOPE = 'TRENDRIDER_UNIFIED_OBSERVED_WS_SCHEMA_AFTER_PR1283_V1'
NATIVE_T = 1_789_153_200_000
RECEIVED_MS = 1_789_156_017_958
PROTOCOL_SCHEMA = 'trendrider.observed.ws.rest.timestamp.protocol.v1'
RECEIPT_SCHEMA = 'trendrider.observed.ws.rest.timestamp.receipt.v1'
RECEIPT_NAME = 'OBSERVED_WS_REST_TIMESTAMP_RECEIPT.json'
INPUT_SHA = {
    'frame_raw': 'b0d5a0ec106e93a65432e5ebe23b79fc5a29003edc705c13e66a07e63ad8dfde',
    'frame_meta': '9ccb7a4b1e3fb4a4384ac147cb9069213078fe3fcdab352331ac0a6f90d2c260',
    'ack_raw': '175220f1fcaf3e6ba8d7164600953ebc1e61125fae8859364241b20483b97bde',
    'ack_meta': 'ec7848331369460a8d7c795bd408a2284022dd9841822a7231b5e013ab41c70d',
}
INPUT_NAME = {'frame_raw': 'stored/ws_0002.bin', 'frame_meta': 'stored/ws_0002.meta.json',
              'ack_raw': 'stored/ws_0001.bin', 'ack_meta': 'stored/ws_0001.meta.json'}


def protocol_template(frame_raw_sha256=None, frame_meta_sha256=None,
                      ack_raw_sha256=None, ack_meta_sha256=None):
    supplied = dict(zip(INPUT_SHA, (frame_raw_sha256, frame_meta_sha256,
                                   ack_raw_sha256, ack_meta_sha256)))
    if any(value is not None and value != INPUT_SHA[key] for key, value in supplied.items()):
        raise SourceIntegrityError('OBSERVED_ARCHIVED_PR1283_HASH')
    return sealed({
        'schema': PROTOCOL_SCHEMA, 'scope_key': SCOPE, 'archived_input_sha256': INPUT_SHA,
        'native_T': NATIVE_T, 'received_at_ms': RECEIVED_MS, 'symbol': SYMBOL,
        'interval': '1h', 'hour_ms': HOUR_MS, 'endpoint': base.ENDPOINT,
        'method': 'GET', 'headers': dict(old.REQUEST_HEADERS),
        'first_rest_params': rest_params(1), 'second_rest_params': rest_params(2),
        'second_rest_condition': 'ONLY_INCOMPLETE_T_MINUS_H_OR_T_COVERAGE_AFTER_VALID_FIRST_RESPONSE',
        'max_rest_requests': 2, 'max_new_ws_sessions': 0, 'retry_count': 0,
        'redirects': False, 'rest_timeout_seconds': 30, 'min_rest_spacing_ms': 1100,
        'max_rest_raw_bytes': old.MAX_BYTES, 'max_rows_per_response': 3,
        'allowed_row_native_times': [NATIVE_T-HOUR_MS, NATIVE_T, NATIVE_T+HOUR_MS],
        'unused_guard_rows': 'QUARANTINE_ECONOMIC_ZERO',
        'required_rows_closed_before_request': [NATIVE_T-HOUR_MS, NATIVE_T],
        'open_numeric_comparison': 'EXACT_FINITE_DECIMAL',
        'high_low_test': 'SNAPSHOT_HIGH_LE_FINAL_HIGH_AND_SNAPSHOT_LOW_GE_FINAL_LOW',
        'adjacent_identity_test': 'DIFFERENT_OPEN_OR_SNAPSHOT_OHLC_NOT_CONTAINED',
        'volume_rule': 'ADVISORY_ONLY_SEMANTIC_NOT_ESTABLISHED_BY_FIELD_NAME',
        'timestamp_adjustment_ms': 0, 'economics': 0, 'outcome_independent': True,
        'fatal_errors_abort_remaining_requests': True,
    })


def rest_params(ordinal):
    if ordinal not in (1, 2):
        raise SourceIntegrityError('OBSERVED_REST_BUDGET')
    return {'symbol': SYMBOL, 'interval': '1h', 'startTime': NATIVE_T-HOUR_MS,
            'endTime': NATIVE_T+HOUR_MS-1 if ordinal == 1 else NATIVE_T, 'limit': 3}


def validate_protocol(raw):
    value = base._decode_json(raw)
    if canonical_bytes(value) != canonical_bytes(protocol_template()):
        raise SourceIntegrityError('OBSERVED_PROTOCOL_CHANGED')
    return value


def _read_sealed(path):
    value = base._decode_json(Path(path).read_bytes())
    check_seal(value)
    return value


def decode_rest(raw):
    """Retain native field shape; only the semantic receipt grants open meaning."""
    if len(raw) > old.MAX_BYTES:
        raise SourceIntegrityError('OBSERVED_REST_RAW_LIMIT')
    try:
        payload = json.loads(raw, parse_float=Decimal, object_pairs_hook=old.unique_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(
                                 SourceIntegrityError('OBSERVED_REST_NONFINITE')))
    except (ValueError, UnicodeError) as exc:
        raise SourceIntegrityError('OBSERVED_REST_JSON') from exc
    if (not isinstance(payload, dict) or type(payload.get('code')) is not int
            or payload['code'] != 0 or not isinstance(payload.get('data'), list)
            or not 1 <= len(payload['data']) <= 3):
        raise SourceIntegrityError('OBSERVED_REST_ENVELOPE')
    rows = []
    for item in payload['data']:
        close_ms = None
        if isinstance(item, dict):
            fields = [key for key in ('time', 'openTime') if key in item]
            if len(fields) != 1 or any(k in item for k in ('timestamp', 'open_time', 'closeTime', 'close_time')):
                raise SourceIntegrityError('OBSERVED_REST_TIMESTAMP_AMBIGUOUS')
            if (('symbol' in item and item['symbol'] != SYMBOL)
                    or ('interval' in item and item['interval'] != '1h')):
                raise SourceIntegrityError('OBSERVED_REST_IDENTITY')
            if any(k not in item for k in ('open', 'high', 'low', 'close', 'volume')):
                raise SourceIntegrityError('OBSERVED_REST_OBJECT_FIELDS')
            field = fields[0]
            native = old.timestamp(item[field])
            values = [item[k] for k in ('open', 'high', 'low', 'close')]
            volume, schema = item['volume'], 'object'
        elif isinstance(item, list) and len(item) >= 7:
            native, close_ms = old.timestamp(item[0]), old.timestamp(item[6])
            if close_ms-native not in (HOUR_MS-1, HOUR_MS):
                raise SourceIntegrityError('OBSERVED_REST_ARRAY_CLOSE')
            values, volume, schema, field = item[1:5], item[5], 'array', 'index0'
        else:
            raise SourceIntegrityError('OBSERVED_REST_ROW_SHAPE')
        if native % HOUR_MS or native not in (NATIVE_T-HOUR_MS, NATIVE_T, NATIVE_T+HOUR_MS):
            raise SourceIntegrityError('OBSERVED_REST_NATIVE_TIME_RANGE')
        result = old.candle(native, close_ms, values, volume, schema)
        rows.append({'schema': schema, 'timestamp_field': field, 'native_time': native,
                     'native_close_ms': close_ms, 'ohlc': result['ohlc'], 'volume': result['volume']})
    if len({r['native_time'] for r in rows}) != len(rows):
        raise SourceIntegrityError('OBSERVED_REST_DUPLICATE_NATIVE_TIME')
    if len({(r['schema'], r['timestamp_field']) for r in rows}) != 1:
        raise SourceIntegrityError('OBSERVED_REST_MIXED_SCHEMA')
    return rows


def _archived(root):
    raws = {}
    for key, name in INPUT_NAME.items():
        raws[key] = (root/name).read_bytes()
        if digest_bytes(raws[key]) != INPUT_SHA[key]:
            raise SourceIntegrityError('OBSERVED_ARCHIVED_PR1283_HASH')
    frame_meta, ack_meta = (base._decode_json(raws[k]) for k in ('frame_meta', 'ack_meta'))
    for meta, key in ((frame_meta, 'frame_raw'), (ack_meta, 'ack_raw')):
        check_seal(meta)
        if (meta['raw_sha256'] != INPUT_SHA[key] or meta['raw_bytes'] != len(raws[key])
                or meta['binary'] is not True or meta['session_id'] != old.SESSION_ID):
            raise SourceIntegrityError('OBSERVED_ARCHIVED_METADATA')
    ack = observed.decode_ws(raws['ack_raw'], True, expected_request_id=old.SESSION_ID)
    frame = observed.decode_ws(raws['frame_raw'], True, expected_request_id=old.SESSION_ID)
    if (ack.get('kind') != 'ack' or ack.get('classification') != 'SUBSCRIPTION_ACK_OK'
            or frame.get('kind') != 'kline' or len(frame.get('candles', [])) != 1):
        raise SourceIntegrityError('OBSERVED_ARCHIVED_PREFIX')
    row = frame['candles'][0]
    if (row['native_T'] != NATIVE_T or frame_meta['received_at_ms'] != RECEIVED_MS
            or not NATIVE_T <= RECEIVED_MS < NATIVE_T+HOUR_MS
            or not ack_meta['received_at_ms'] < RECEIVED_MS
            or (ack_meta['ordinal'], frame_meta['ordinal']) != (1, 2)):
        raise SourceIntegrityError('OBSERVED_ARCHIVED_CHRONOLOGY')
    return row, {'ack_received_at_ms': ack_meta['received_at_ms'],
                 'kline_received_at_ms': RECEIVED_MS,
                 'ack_to_kline_ms': RECEIVED_MS-ack_meta['received_at_ms'],
                 'ack_classification': ack['classification'], 'kline_ordinal': 2}


def _prefix_consistency(snapshot, final):
    s, f = snapshot['ohlc'], final['ohlc']
    return {'open_exact_equal': Decimal(s['open']) == Decimal(f['open']),
            'snapshot_high_le_final_high': Decimal(s['high']) <= Decimal(f['high']),
            'snapshot_low_ge_final_low': Decimal(s['low']) >= Decimal(f['low'])}


def _merge_rows(accumulated, incoming):
    result = dict(accumulated)
    for row in incoming:
        old_row = result.get(row['native_time'])
        if old_row is not None and old_row != row:
            raise SourceIntegrityError('OBSERVED_REST_CLOSED_ROW_CHANGED')
        result[row['native_time']] = row
    if len({(r['schema'], r['timestamp_field']) for r in result.values()}) > 1:
        raise SourceIntegrityError('OBSERVED_REST_CROSS_RESPONSE_SCHEMA')
    return result


def _coverage(rows):
    return {NATIVE_T-HOUR_MS, NATIVE_T}.issubset(rows)


def _receipt_from_saved(root, counts):
    root = Path(root)
    protocol_raw = (root/'OBSERVED_TIMESTAMP_PROTOCOL.json').read_bytes()
    validate_protocol(protocol_raw)
    snapshot, chronology = _archived(root)
    start = _read_sealed(root/'WITNESS_ATTEMPT_STARTED.json')
    if (start['scope_key'] != SCOPE or start['protocol_sha256'] != digest_bytes(protocol_raw)
            or start['started_at_ms'] < NATIVE_T+HOUR_MS):
        raise SourceIntegrityError('OBSERVED_START_OR_CANDLE_NOT_CLOSED')
    if type(counts) is not int or not 1 <= counts <= 2:
        raise SourceIntegrityError('OBSERVED_REST_BUDGET')
    rows, responses, prior_request_ms = {}, [], None
    for ordinal in range(1, counts+1):
        if ordinal == 2 and _coverage(rows):
            raise SourceIntegrityError('OBSERVED_UNAUTHORIZED_SECOND_REQUEST')
        stem = f'raw/rest_{ordinal}'
        request = _read_sealed(root/(stem+'.request.json'))
        response = _read_sealed(root/(stem+'.response.json'))
        raw = (root/(stem+'.bin')).read_bytes()
        req_ms = request['requested_at_ms']
        expected_req = sealed({'scope_key': SCOPE, 'ordinal': ordinal, 'method': 'GET',
            'endpoint': base.ENDPOINT, 'params': rest_params(ordinal),
            'headers': dict(old.REQUEST_HEADERS), 'requested_at_ms': req_ms, 'retry_count': 0})
        if (request != expected_req or type(req_ms) is not int or req_ms < start['started_at_ms']
                or req_ms < NATIVE_T+HOUR_MS or (prior_request_ms is not None and req_ms-prior_request_ms < 1100)):
            raise SourceIntegrityError('OBSERVED_REST_REQUEST_OR_CHRONOLOGY')
        prior_request_ms = req_ms
        if (response['ordinal'] != ordinal or response['scope_key'] != SCOPE
                or response['status'] != 200 or type(response['status']) is not int
                or response['body_read_complete'] is not True or response['partial_failure'] is not None
                or response['raw_path'] != stem+'.bin' or response['request_path'] != stem+'.request.json'
                or response['raw_sha256'] != digest_bytes(raw) or response['raw_bytes'] != len(raw)
                or response['received_at_ms'] < req_ms):
            raise SourceIntegrityError('OBSERVED_REST_RAW_LINK_OR_STATUS')
        decoded = decode_rest(raw)
        rows = _merge_rows(rows, decoded)
        responses.append({'ordinal': ordinal, 'request_path': stem+'.request.json',
            'request_sha256': digest_bytes((root/(stem+'.request.json')).read_bytes()),
            'response_path': stem+'.response.json',
            'response_sha256': digest_bytes((root/(stem+'.response.json')).read_bytes()),
            'raw_path': stem+'.bin', 'raw_sha256': digest_bytes(raw), 'rows': decoded})
    if not _coverage(rows):
        raise SourceIntegrityError('OBSERVED_REST_ADJACENT_COVERAGE_INCOMPLETE')
    target, adjacent = rows[NATIVE_T], rows[NATIVE_T-HOUR_MS]
    consistent = _prefix_consistency(snapshot, target)
    distinct = not all(_prefix_consistency(snapshot, adjacent).values())
    if not all(consistent.values()) or not distinct:
        raise SourceIntegrityError('OBSERVED_TIMESTAMP_WITNESS_CONSISTENCY')
    lanes = {'time': ('OBJECT_TIME_OPEN', 'IDENTITY_NATIVE_OBJECT_TIME_MS'),
             'openTime': ('OBJECT_OPEN_TIME_OPEN', 'IDENTITY_NATIVE_OBJECT_OPEN_TIME_MS'),
             'index0': ('ARRAY_OPEN_CLOSE', 'IDENTITY_NATIVE_ARRAY_OPEN_MS')}
    lane, transform = lanes[target['timestamp_field']]
    return sealed({'schema': RECEIPT_SCHEMA, 'scope_key': SCOPE, 'state': 'PASS', 'status': 'PASS',
        'protocol_sha256': digest_bytes(protocol_raw),
        'attempt_started_sha256': digest_bytes((root/'WITNESS_ATTEMPT_STARTED.json').read_bytes()),
        'symbol': SYMBOL, 'interval': '1h', 'hour_ms': HOUR_MS,
        'stored_pr1283': {key: {'path': INPUT_NAME[key], 'sha256': value} for key, value in INPUT_SHA.items()},
        'pr1283_raw_sha256': INPUT_SHA['frame_raw'], 'native_T': NATIVE_T,
        'received_at': '2026-09-11T19:46:57.958Z', 'received_at_ms': RECEIVED_MS,
        'receive_within_native_T_interval': True, 'ack_to_kline_chronology': chronology,
        'rest_responses': responses, 'T_row': target, 'T_minus_1h_row': adjacent,
        'prefix_final_consistency': consistent, 'adjacent_identity_distinct': distinct,
        'volume_check': {'same_volume_semantic_established': False, 'required': False,
            'snapshot_le_final': Decimal(snapshot['volume']) <= Decimal(target['volume']),
            'snapshot_volume': snapshot['volume'], 'final_volume': target['volume'],
            'status': 'ADVISORY_ONLY'},
        'guard_rows_quarantined': [r for t, r in rows.items() if t not in (NATIVE_T-HOUR_MS, NATIVE_T)],
        'guard_economic_rows': 0, 'supported_canonical_lane': lane,
        'canonical_open_transform': transform, 'object_timestamp_field': target['timestamp_field'],
        'rest_native_close_delta_ms': (None if target['native_close_ms'] is None
                                     else target['native_close_ms']-NATIVE_T),
        'open_ts_rule': 'native_T', 'close_ts_rule': 'open_ts + 1h',
        'close_ts_semantics': 'ECONOMIC_INTERVAL_BOUNDARY', 'provider_native_close_claim': False,
        'timestamp_adjustment_ms': 0, 'outcome_independent': True,
        'counts': {'stored_ws_evidence_sets': 1, 'ws_sessions': 0, 'rest_requests': counts,
                   'retry_count': 0, 'economics': 0}})


async def run_witness(output_dir, protocol_path, frame_raw_path, frame_meta_path,
                      ack_raw_path, ack_meta_path, *, rest=None, clock=None):
    root, protocol_path = Path(output_dir), Path(protocol_path)
    protocol_raw = protocol_path.read_bytes()
    validate_protocol(protocol_raw)
    paths = dict(zip(INPUT_SHA, map(Path, (frame_raw_path, frame_meta_path, ack_raw_path, ack_meta_path))))
    originals = {key: path.read_bytes() for key, path in paths.items()}
    if any(digest_bytes(raw) != INPUT_SHA[key] for key, raw in originals.items()):
        raise SourceIntegrityError('OBSERVED_ARCHIVED_PR1283_HASH')
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise SourceIntegrityError('OBSERVED_OUTPUT_NONEMPTY_NO_RESUME')
    def save(name, value):
        write_once(root/name, canonical_bytes(sealed(value)))
    def unchanged():
        if protocol_path.read_bytes() != protocol_raw or any(paths[key].read_bytes() != raw for key, raw in originals.items()):
            raise SourceIntegrityError('OBSERVED_FROZEN_INPUT_CHANGED')
    write_once(root/'OBSERVED_TIMESTAMP_PROTOCOL.json', protocol_raw)
    for key, raw in originals.items():
        write_once(root/INPUT_NAME[key], raw)
    _archived(root)
    clock, rest_fn = clock or old.Clock(), rest or old.live_rest
    started_ms = clock.wall_ms()
    save('WITNESS_ATTEMPT_STARTED.json', {'scope_key': SCOPE, 'attempt_ordinal': 1,
        'started_at_ms': started_ms, 'protocol_sha256': digest_bytes(protocol_raw),
        'max_rest_requests': 2, 'max_new_ws_sessions': 0, 'retry_count': 0})
    counts, rows, previous_start = 0, {}, None
    try:
        if started_ms < NATIVE_T+HOUR_MS:
            raise SourceIntegrityError('OBSERVED_CANDLE_NOT_CLOSED')
        for ordinal in (1, 2):
            if previous_start is not None:
                await clock.sleep(max(0, previous_start+1.1-clock.monotonic()))
            unchanged()
            stem = f'raw/rest_{ordinal}'
            params = rest_params(ordinal)
            save(stem+'.request.json', {'scope_key': SCOPE, 'ordinal': ordinal, 'method': 'GET',
                'endpoint': base.ENDPOINT, 'params': params, 'headers': dict(old.REQUEST_HEADERS),
                'requested_at_ms': clock.wall_ms(), 'retry_count': 0})
            counts, previous_start = ordinal, clock.monotonic()
            partial = None
            try:
                response = await asyncio.wait_for(rest_fn(params), timeout=30)
            except old.PartialRESTFailure as exc:
                response, partial = exc.response, old.safe_error(exc)
            except Exception as exc:
                save(stem+'.failure.json', {'scope_key': SCOPE, 'ordinal': ordinal,
                    'error': old.safe_error(exc), 'retry_count': 0})
                raise
            write_once(root/(stem+'.bin'), response.body)
            save(stem+'.response.json', {'scope_key': SCOPE, 'ordinal': ordinal,
                'status': response.status, 'headers': dict(response.headers),
                'received_at_ms': clock.wall_ms(), 'raw_path': stem+'.bin',
                'raw_sha256': digest_bytes(response.body), 'raw_bytes': len(response.body),
                'request_path': stem+'.request.json', 'body_read_complete': partial is None,
                'partial_failure': partial})
            if partial is not None or response.status != 200:
                raise SourceIntegrityError('OBSERVED_REST_TRANSPORT_OR_HTTP')
            rows = _merge_rows(rows, decode_rest(response.body))
            if _coverage(rows):
                break
        unchanged()
        receipt = _receipt_from_saved(root, counts)
    except Exception as exc:
        receipt = sealed({'schema': RECEIPT_SCHEMA, 'scope_key': SCOPE,
            'state': 'BLOCKED_OBSERVED_WS_REST_TIMESTAMP_WITNESS',
            'status': 'BLOCKED_OBSERVED_WS_REST_TIMESTAMP_WITNESS',
            'failure': old.safe_error(exc), 'protocol_sha256': digest_bytes(protocol_raw),
            'outcome_independent': True, 'counts': {'stored_ws_evidence_sets': 1,
                'ws_sessions': 0, 'rest_requests': counts, 'retry_count': 0, 'economics': 0}})
    write_once(root/RECEIPT_NAME, canonical_bytes(receipt))
    return receipt


def validate_receipt(receipt_path, expected_sha256=None, *, protocol_path=None):
    path = Path(receipt_path)
    raw = path.read_bytes()
    if expected_sha256 is not None and digest_bytes(raw) != expected_sha256:
        raise SourceIntegrityError('OBSERVED_RECEIPT_EXPECTED_HASH')
    receipt = base._decode_json(raw)
    check_seal(receipt)
    if receipt.get('state') != 'PASS':
        raise SourceIntegrityError('OBSERVED_RECEIPT_NOT_PASS')
    if protocol_path is not None and Path(protocol_path).read_bytes() != (path.parent/'OBSERVED_TIMESTAMP_PROTOCOL.json').read_bytes():
        raise SourceIntegrityError('OBSERVED_EXTERNAL_PROTOCOL_MISMATCH')
    expected = _receipt_from_saved(path.parent, receipt['counts']['rest_requests'])
    if receipt != expected:
        raise SourceIntegrityError('OBSERVED_RECEIPT_RECOMPUTE_MISMATCH')
    allowed = {'OBSERVED_TIMESTAMP_PROTOCOL.json', 'WITNESS_ATTEMPT_STARTED.json', RECEIPT_NAME,
               *INPUT_NAME.values()}
    for ordinal in range(1, receipt['counts']['rest_requests']+1):
        allowed.update(f'raw/rest_{ordinal}{suffix}' for suffix in ('.request.json', '.response.json', '.bin'))
    actual = {p.relative_to(path.parent).as_posix() for p in path.parent.rglob('*') if p.is_file()}
    if actual != allowed:
        raise SourceIntegrityError('OBSERVED_RECEIPT_UNLISTED_OR_MISSING_EVIDENCE')
    return receipt


validate_semantic_receipt = validate_receipt
