"""Read original price bodies for the immutable PR1354 cut. No strategy or writes.

SSH entrypoint is assembled from the pinned descriptor reader, this file, and a
hash-bound input literal by CI. Only six named symbols and known runtime roots
are readable. Existing source bodies, state and other lanes stay untouched.
"""
import base64
import csv
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
from pathlib import Path
import sqlite3
import sys
import time

if 'read_relative_record' not in globals():
    from ops.kp_committed_cursor_snapshot_v1 import (
        SYMBOLS, SOURCE, load, read_relative, read_relative_record, require, sha,
        validate_cursor, append_delta,
    )

ROOT = Path('/home/z/z/runtime/scalp7_broad_v2_20260915')
TREE = Path('/home/z/worktrees/scalp7-broad-v2-20260915')
SOURCE_ROOT = ROOT / 'fresh_1m_verified'
CANDIDATE = 'scalp7_keltner_hg_parent_utc30m_v2'
SNAPSHOT_SHA = 'f8391ea2ea907d3e52b144688111a733757713b5acd72992992bdc4d99662666'
IDENTITY_SHA = 'a5c2d7d6888b1cbf5e5c851c66b11127736fda94fd58f0484e19381c7e1efca9'
FIELDS = ('timestamp_ms', 'open', 'high', 'low', 'close', 'volume')
COMMON_END = 1791075300000  # 2026-10-04 00:55 UTC, fixed BEFORE body/performance read.
START = 1789498080000       # 2026-09-15 18:48 UTC; no outcome-dependent selection.


def normalize_body(raw, receipt):
    payload = load(raw)
    require(str(payload.get('code')) == '0' and isinstance(payload.get('data'), list), 'RESPONSE_SCHEMA')
    rows = []
    for item in payload['data']:
        require(isinstance(item, dict), 'NAMED_CANDLE_REQUIRED')
        stamps = [item[k] for k in ('time', 'openTime', 'timestamp') if k in item]
        require(bool(stamps) and all(not isinstance(x, bool) for x in stamps), 'TIMESTAMP_REQUIRED')
        try:
            ts = [Decimal(str(x)) for x in stamps]
            require(all(x.is_finite() and x == x.to_integral_value() for x in ts) and len(set(ts)) == 1, 'TIMESTAMP_ALIASES')
            t = int(ts[0])
            require(receipt['start_ms'] <= t < receipt['end_exclusive_ms'] and t % 60000 == 0 and t + 60000 <= receipt['received_at_ms'], 'BAR_CLOCK')
            nums = {}
            for k in FIELDS[1:]:
                v = item[k]
                require(v is not None and not isinstance(v, bool), 'NUMERIC_FIELD')
                d = Decimal(str(v))
                require(d.is_finite() and (d >= 0 if k == 'volume' else d > 0), 'NUMERIC_RANGE')
                nums[k] = d
        except (InvalidOperation, KeyError) as exc:
            raise ValueError('RAW_CANDLE_SCHEMA') from exc
        require(nums['low'] <= min(nums['open'], nums['close']) <= max(nums['open'], nums['close']) <= nums['high'], 'OHLC_GEOMETRY')
        rows.append({'timestamp_ms': t, **{k: format(v, 'f') for k, v in nums.items()}})
    rows.sort(key=lambda x: x['timestamp_ms'])
    stamps = [r['timestamp_ms'] for r in rows]
    require(len(set(stamps)) == len(stamps), 'DUPLICATE_MINUTE')
    missing = sorted(set(range(receipt['start_ms'], receipt['end_exclusive_ms'], 60000)) - set(stamps))
    require(missing == receipt['missing_minutes'] and len(rows) == receipt['rows'], 'BODY_RECEIPT_ACCOUNTING')
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return rows, out.getvalue().encode()


def bounded_gunzip(raw, max_bytes):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as handle:
        out = handle.read(max_bytes + 1)
    require(len(out) <= max_bytes, 'DECOMPRESSED_SIZE_LIMIT')
    return out


def saved_file(path, limit=8*1024*1024):
    """Only already-known runtime/worktree files; no arbitrary source paths."""
    p = Path(path)
    for root in (ROOT, TREE):
        if p.is_absolute() and p.is_relative_to(root):
            raw, file_id = read_relative_record(root, str(p.relative_to(root)), limit)
            return raw, {'path': str(p), 'sha256': sha(raw), 'file_identity': file_id}
    raise ValueError('UNAPPROVED_ROOT')


def state_census():
    out = {}
    for folder in ('fresh_forward', 'observed_paper_clock_v3'):
        raw, meta = saved_file(ROOT / folder / 'STATE.json', 64*1024*1024)
        state = load(raw)
        evaluations = state.get('evaluations', {})
        # Full STATE content remains on host; only this exact candidate's metadata.
        clocks = []
        for key in ('signals', 'positions', 'trades', 'closes'):
            records = state.get(key, [])
            if isinstance(records, dict): records = list(records.values())
            if not isinstance(records, list): continue
            for row in records:
                if not isinstance(row, dict): continue
                sig = row.get('signal', {})
                identity = row.get('identity', sig.get('identity'))
                if identity != CANDIDATE: continue
                clocks.append({k: row[k] for k in ('identity', 'opportunity_key', 'decision_bar_close_ms', 'strategy_observed_at_ms', 'input_snapshot_cutoff_ms', 'observed_at_ms') if k in row})
        out[folder] = {**meta, 'schema': state.get('schema'), 'cursors': state.get('cursors'), 'last_poll_ms': state.get('last_poll_ms'),
                       'candidate_evaluation': evaluations.get(CANDIDATE), 'candidate_record_metadata': clocks,
                       'global_use_history_certified': False}
    return out


def export_prices(payload_raw, expected_code_hashes, max_seconds=240):
    started = time.monotonic()
    require(sha(payload_raw) == SNAPSHOT_SHA, 'PINNED_SNAPSHOT_BYTES_CHANGED')
    snapshot = load(payload_raw)['snapshot']
    require(snapshot['metadata_snapshot_pass'] is True and snapshot['source_identity_sha256'] == IDENTITY_SHA, 'PINNED_SNAPSHOT_PROFILE')
    ident_raw = read_relative(SOURCE_ROOT, 'IDENTITY.json', 262144)
    require(sha(ident_raw) == IDENTITY_SHA, 'SOURCE_IDENTITY_CHANGED')
    before = state_census()
    module_hashes = {}
    for path, expected in expected_code_hashes.items():
        require(path.startswith('backend/research/rebuild/') and path.endswith('.py'), 'CODE_SCOPE')
        raw = read_relative(TREE, path, 300000)
        module_hashes[path] = sha(raw)
        require(module_hashes[path] == expected, 'DEPLOYED_FROZEN_CODE_CHANGED:' + path)
    old_cursor = {'identity_sha256': IDENTITY_SHA, 'symbols': {s: [] for s in SYMBOLS}}
    minutes = {s: [] for s in SYMBOLS}
    totals = {s: {'receipts_verified': 0, 'raw_rows_verified': 0, 'explicit_gaps': 0} for s in SYMBOLS}
    count = 0
    for old in snapshot['receipt_metadata']:
        require(time.monotonic() - started < max_seconds, 'PRICE_VERIFICATION_TIME_BUDGET')
        symbol = old['symbol']
        require(symbol in SYMBOLS, 'SYMBOL_CHANGED')
        old_cursor['symbols'][symbol].append({'path': old['receipt_path'], 'sha256': old['receipt_sha256']})
        raw_receipt = read_relative(SOURCE_ROOT, old['receipt_path'], 262144)
        require(sha(raw_receipt) == old['receipt_sha256'], 'ORIGINAL_RECEIPT_CHANGED')
        receipt = load(raw_receipt)
        require(all(receipt[k] == v for k, v in old.items() if k not in ('receipt_path', 'receipt_sha256')), 'CAPTURED_METADATA_DIFFERS')
        require(receipt['source'] == SOURCE and receipt['http_status'] == 200 and receipt['synthetic_fill'] is False, 'SOURCE_PROVENANCE')
        raw = read_relative(SOURCE_ROOT, receipt['body_path'], 1024*1024)
        normal = read_relative(SOURCE_ROOT, receipt['normalized_path'], 1024*1024)
        require(sha(raw) == receipt['body_sha256'] and sha(normal) == receipt['normalized_sha256'], 'ORIGINAL_BODY_HASH_MISMATCH')
        rows, csv_bytes = normalize_body(raw, receipt)
        require(bounded_gunzip(normal, 8*1024*1024) == csv_bytes, 'RAW_NORMALIZED_CONTENT_MISMATCH')
        for row in rows:
            if row['timestamp_ms'] < COMMON_END:
                minutes[symbol].append([row[k] for k in FIELDS] + [receipt['received_at_ms'], count])
        totals[symbol]['receipts_verified'] += 1
        totals[symbol]['raw_rows_verified'] += len(rows)
        totals[symbol]['explicit_gaps'] += len(receipt['missing_minutes'])
        count += 1
    current = load(read_relative(SOURCE_ROOT, 'CURSOR.json', 32*1024*1024))
    appended = append_delta(old_cursor, current, IDENTITY_SHA, tuple(SYMBOLS))
    for symbol, rows in minutes.items():
        stamps = [r[0] for r in rows]
        require(stamps == list(range(START, COMMON_END, 60000)), 'NONCONTIGUOUS_CUT:' + symbol)
    config_raw, config_meta = saved_file(ROOT / 'FRESH_FORWARD_CONFIG_V2.json')
    config = load(config_raw)
    keep = ('fresh_start_ms', 'frozen_at_ms', 'historical_context', 'regime_fit', 'cost_snapshot', 'campaign_contract', 'code_hashes', 'producer_role', 'sources', 'source_dir', 'source_identity_sha256')
    projected = {k: config[k] for k in keep if k in config}
    context_files = {}
    for symbol in SYMBOLS:
        item = config['historical_context']['30'][symbol]
        require(Path(item['path']) == ROOT/'fresh_context'/f'{symbol}_30m.csv.gz', 'CONTEXT_PATH_PROFILE')
        raw, meta = saved_file(item['path'], 1024*1024)
        require(meta['sha256'] == item['sha256'], 'HISTORICAL_SEED_CHANGED')
        context_files[symbol] = {**meta, 'gzip_base64': base64.b64encode(raw).decode()}
    contract_files = {}
    for name in ('cost_snapshot', 'campaign_contract'):
        item = config[name]
        path = Path(item['path'])
        if not path.is_absolute(): path = TREE/path
        require(path.suffix == '.json' and ('research' in path.parts or path.is_relative_to(ROOT)), 'CONTRACT_PATH_PROFILE')
        raw, meta = saved_file(path)
        require(meta['sha256'] == item['sha256'], 'FROZEN_CONTRACT_CHANGED')
        contract_files[name] = {**meta, 'content': load(raw)}
    # A read-only transaction observes committed candidate reservations; does not
    # claim a global census merely because this campaign's matching list is empty.
    dbpath = ROOT/'campaign.sqlite3'
    _, dbmeta = saved_file(dbpath, 4*1024*1024)
    with sqlite3.connect('file:' + str(dbpath) + '?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA query_only=ON'); con.execute('BEGIN')
        claims = [dict(x) for x in con.execute('SELECT identity_key,scope,candidate_id,state FROM claims WHERE candidate_id=?', (CANDIDATE,))]
        con.rollback()
    return {'schema': 'kp30.verified_price_input.v1', 'snapshot_sha256': SNAPSHOT_SHA, 'source_identity_sha256': IDENTITY_SHA,
            'captured_cut_ms': snapshot['captured_at_ms'], 'source_start_ms': START, 'common_end_exclusive_ms': COMMON_END,
            'price_bodies_verified': True, 'receipts_verified': count, 'totals': totals,
            'fields': list(FIELDS) + ['source_received_at_ms', 'snapshot_receipt_index'], 'minutes': minutes,
            'new_append_references_excluded': appended, 'config_projection': projected, 'config_source': config_meta,
            'context': context_files, 'contracts': contract_files, 'deployed_code_hashes': module_hashes,
            'before': before, 'after': state_census(), 'campaign_claims': claims, 'campaign_db_observation': dbmeta,
            'elapsed_s': round(time.monotonic()-started, 6), 'global_use_history_certified': False,
            'unused_oos_certified': False, 'market_runs': 0, 'server_file_writes': 0,
            'collection_started': False, 'shared_state_modified': False, 'account_performance_certified': False}


if __name__ == '__main__':
    # Only CI's pinned input literal can enter the fixed-target remote exporter.
    payload = bounded_gunzip(base64.b64decode(KP_INPUT_B64, validate=True), 64*1024*1024)
    try:
        result = export_prices(payload, KP_EXPECTED_CODE_HASHES)
        with gzip.GzipFile(fileobj=sys.stdout.buffer, mode='wb', mtime=0) as output:
            output.write(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    except Exception as exc:
        print('KP_BODY_EXPORT_REJECTED:' + type(exc).__name__ + ':' + str(exc)[:250], file=sys.stderr)
        raise
