"""Read-only committed-source metadata snapshot. No prices, strategies or writes.

Pin CURSOR once; follow only its hash-bound immutable receipt references.
An appended cursor suffix is not a rewrite of the captured prefix. This utility
is NOT activated in either frozen producer and grants no economic authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any, Callable

SOURCE = 'https://open-api.bingx.com/openApi/swap/v3/quote/klines'
SYMBOLS = ('BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'LINK-USDT', 'DOGE-USDT')
MAX_CURSOR_BYTES = 32 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024
MAX_RECORDS = 150000


class SnapshotError(RuntimeError):
    pass


def require(ok: bool, why: str) -> None:
    if not ok:
        raise SnapshotError(why)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def hash_value(value: Any) -> str:
    require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value), 'INVALID_SHA256')
    return value


def ms(value: Any) -> int:
    require(type(value) is int and value >= 0, 'INVALID_TIMESTAMP')
    return value


def load(raw: bytes) -> dict[str, Any]:
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def bad(value):
        raise SnapshotError('NONFINITE_JSON')
    data = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    require(isinstance(data, dict), 'JSON_OBJECT_REQUIRED')
    return data


def read_relative(root: Path, relative: str, limit: int) -> bytes:
    """Use descriptor-relative O_NOFOLLOW on every component; no path TOCTOU."""
    require(isinstance(relative, str) and relative and not relative.startswith('/'), 'RELATIVE_PATH_REQUIRED')
    parts = relative.split('/')
    require(all(p not in ('', '.', '..') for p in parts), 'PATH_TRAVERSAL')
    base = Path(root).absolute()
    require(all(p not in ('.', '..') for p in base.parts[1:]), 'ROOT_TRAVERSAL')
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open('/', flags | os.O_DIRECTORY)
    try:
        # Walk the supplied root as well, avoiding lstat/open ancestor races.
        for component in base.parts[1:]:
            nxt = os.open(component, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = nxt
        for part in parts[:-1]:
            nxt = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = nxt
        child = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(child)
            require(stat.S_ISREG(before.st_mode), 'REGULAR_FILE_REQUIRED')
            require(before.st_size <= limit, 'READ_SIZE_LIMIT')
            chunks = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(child, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b''.join(chunks)
            after = os.fstat(child)
            require(len(raw) <= limit, 'READ_SIZE_LIMIT')
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'INPLACE_CHANGE_DURING_READ')
            require(len(raw) == before.st_size, 'READ_LENGTH_CHANGED')
            return raw
        finally:
            os.close(child)
    finally:
        os.close(fd)


def validate_cursor(data: dict[str, Any], identity_hash: str, symbols: tuple[str, ...]) -> None:
    require(set(data) == {'identity_sha256', 'symbols'}, 'CURSOR_FIELDS')
    require(data['identity_sha256'] == identity_hash, 'CURSOR_IDENTITY_CHANGED')
    require(isinstance(data['symbols'], dict) and set(data['symbols']) == set(symbols), 'CURSOR_SYMBOLS')
    refs = set()
    total = 0
    for symbol in symbols:
        records = data['symbols'][symbol]
        require(isinstance(records, list) and records, 'EMPTY_SYMBOL_RECEIPTS')
        total += len(records)
        require(total <= MAX_RECORDS, 'RECORD_LIMIT')
        for ref in records:
            require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'REFERENCE_FIELDS')
            path = ref['path']
            require(isinstance(path, str) and path.startswith('requests/' + symbol + '/') and path.endswith('.receipt.json'), 'RECEIPT_PATH_PROFILE')
            require(all(p not in ('', '.', '..') for p in path.split('/')), 'REFERENCE_TRAVERSAL')
            require(path not in refs, 'DUPLICATE_RECEIPT_REFERENCE')
            refs.add(path)
            hash_value(ref['sha256'])


def append_delta(before: dict[str, Any], after: dict[str, Any], identity_hash: str, symbols: tuple[str, ...]) -> dict[str, int]:
    validate_cursor(before, identity_hash, symbols)
    validate_cursor(after, identity_hash, symbols)
    counts = {}
    for symbol in symbols:
        old, new = before['symbols'][symbol], after['symbols'][symbol]
        require(len(new) >= len(old) and new[:len(old)] == old, 'COMMITTED_PREFIX_REWRITTEN:' + symbol)
        counts[symbol] = len(new) - len(old)
    return counts


def capture(root: Path, expected_identity_sha256: str, *, after_capture: Callable[[], None] | None = None,
            time_budget_s: float = 140.0) -> dict[str, Any]:
    """Return a self-contained metadata copy with a byte-pinned cursor.

    Price bodies are NOT opened. Their recorded hashes remain unverified.
    Caller can persist this returned copy in an isolated artifact. Any later
    body reader must verify those exact bytes before using them as market data.
    """
    started = time.monotonic()
    identity_raw = read_relative(root, 'IDENTITY.json', MAX_RECEIPT_BYTES)
    expected = hash_value(expected_identity_sha256)
    require(sha(identity_raw) == expected, 'SOURCE_IDENTITY_PIN_MISMATCH')
    identity = load(identity_raw)
    require(identity.get('schema') == 'scalp7.fresh_source.v2' and identity.get('source') == SOURCE and
            identity.get('interval') == '1m' and identity.get('timeZone') == 0 and
            identity.get('order_authority') == 'BLOCKED' and identity.get('synthetic_fill') is False, 'SOURCE_IDENTITY_PROFILE')
    symbols_raw = identity.get('symbols')
    require(isinstance(symbols_raw, list) and len(symbols_raw) == len(SYMBOLS) and set(symbols_raw) == set(SYMBOLS), 'IDENTITY_EXACT_SIX_SYMBOLS')
    symbols = tuple(symbols_raw)
    first_ms = ms(identity['start_ms'])
    require(first_ms % 60000 == 0, 'SOURCE_START_ALIGNMENT')
    cursor_raw = read_relative(root, 'CURSOR.json', MAX_CURSOR_BYTES)
    captured_at_ms = time.time_ns() // 1_000_000
    cursor = load(cursor_raw)
    validate_cursor(cursor, expected, symbols)
    if after_capture:
        after_capture()
    entries, summaries = [], []
    for symbol in symbols:
        begin, rows_count, gaps_count, last_received = first_ms, 0, 0, 0
        for ref in cursor['symbols'][symbol]:
            require(time.monotonic() - started < time_budget_s, 'METADATA_SCAN_TIME_BUDGET')
            raw = read_relative(root, ref['path'], MAX_RECEIPT_BYTES)
            require(sha(raw) == ref['sha256'], 'RECEIPT_HASH_CHANGED')
            receipt = load(raw)
            end = ms(receipt['end_exclusive_ms'])
            received = ms(receipt['received_at_ms'])
            query = receipt.get('query')
            require(isinstance(query, dict), 'RECEIPT_QUERY')
            require(receipt.get('symbol') == symbol and receipt.get('start_ms') == begin and
                    end > begin and end % 60000 == 0 and received >= end and received <= captured_at_ms and
                    receipt.get('http_status') == 200 and receipt.get('source') == SOURCE and
                    str(receipt.get('url', '')).split('?')[0] == SOURCE and
                    query.get('symbol') == symbol and query.get('interval') == '1m' and query.get('timeZone') == 0 and
                    query.get('startTime') == begin and query.get('endTime') == end - 1 and
                    receipt.get('synthetic_fill') is False, 'RECEIPT_IDENTITY_WINDOW_OR_CLOCK')
            gaps, count = receipt.get('missing_minutes'), receipt.get('rows')
            require(isinstance(gaps, list) and all(type(g) is int and begin <= g < end and g % 60000 == 0 for g in gaps)
                    and gaps == sorted(set(gaps)), 'INVALID_GAPS')
            require(type(count) is int and count >= 0 and count + len(gaps) == (end - begin) // 60000, 'RECEIPT_ROW_ACCOUNTING')
            require(receipt.get('state') == ('GAP_PRESERVED' if gaps else 'COMPLETE'), 'GAP_STATUS_MISMATCH')
            for name, suffix in (('body_path', '.body'), ('normalized_path', '.csv.gz')):
                p = receipt.get(name)
                require(isinstance(p, str) and p.startswith('requests/' + symbol + '/') and p.endswith(suffix)
                        and all(x not in ('', '.', '..') for x in p.split('/')), 'BODY_REFERENCE_PATH')
            entry = {k: receipt[k] for k in ('symbol', 'start_ms', 'end_exclusive_ms', 'requested_at_ms', 'received_at_ms',
                     'body_path', 'body_sha256', 'normalized_path', 'normalized_sha256', 'rows', 'missing_minutes', 'state', 'volume_units')}
            ms(entry['requested_at_ms'])
            require(entry['requested_at_ms'] <= received, 'REQUEST_AFTER_RECEIPT')
            hash_value(entry['body_sha256']); hash_value(entry['normalized_sha256'])
            entry.update(receipt_path=ref['path'], receipt_sha256=ref['sha256'])
            entries.append(entry)
            rows_count += count; gaps_count += len(gaps); last_received = max(last_received, received); begin = end
        summaries.append({'symbol': symbol, 'receipts': len(cursor['symbols'][symbol]), 'start_ms': first_ms,
                          'end_exclusive_ms': begin, 'reported_rows': rows_count, 'explicit_missing_minutes': gaps_count,
                          'latest_received_at_ms': last_received})
    # Retain append progress, but never admit new suffix references into the copy.
    later_raw = read_relative(root, 'CURSOR.json', MAX_CURSOR_BYTES)
    delta = append_delta(cursor, load(later_raw), expected, symbols)
    require(read_relative(root, 'IDENTITY.json', MAX_RECEIPT_BYTES) == identity_raw, 'IDENTITY_CHANGED_DURING_SNAPSHOT')
    return {'schema': 'kp30.committed_source_metadata_snapshot.v1', 'captured_at_ms': captured_at_ms,
            'completed_at_ms': time.time_ns() // 1_000_000, 'elapsed_seconds': round(time.monotonic()-started, 6),
            'source_identity_sha256': expected, 'cursor_sha256': sha(cursor_raw), 'later_cursor_sha256': sha(later_raw),
            'cursor_changed': cursor_raw != later_raw, 'append_only_verified': True, 'appended_records_excluded': delta,
            'receipt_metadata_verified': len(entries), 'symbols': summaries, 'receipt_metadata': entries,
            'metadata_snapshot_pass': True, 'raw_price_bodies_opened': 0, 'body_hashes_verified': False,
            'usage_history_complete': False, 'unused_data_certified': False, 'market_execution_ready': False,
            'strategy_invocations': 0, 'new_full_runs': 0, 'runtime_state_mutations': 0,
            'existing_frozen_reader_replaced': False}
