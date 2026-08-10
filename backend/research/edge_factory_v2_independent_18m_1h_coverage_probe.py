from __future__ import annotations

import argparse, json
from datetime import datetime, timezone
from pathlib import Path

from edge_factory_v2_independent_18m_1h_collect import (
    END_EXCLUSIVE_UTC, INTERVAL_MS, SAFE_CHUNK_BARS, START_UTC, SYMBOLS,
    request_chunk, stable_sha, utc_ms,
)


def probe_symbol(symbol: str, start_ms: int, end_ms: int) -> dict:
    seen: set[int] = set()
    cursor = start_ms
    request_count = 0
    while cursor < end_ms:
        chunk_end = min(cursor + SAFE_CHUNK_BARS * INTERVAL_MS, end_ms)
        rows = request_chunk(symbol, cursor, chunk_end)
        request_count += 1
        for row in rows:
            ts = int(row['timestamp_ms'])
            if start_ms <= ts < end_ms:
                seen.add(ts)
        cursor = chunk_end
    ordered = sorted(seen)
    expected = (end_ms - start_ms) // INTERVAL_MS
    min_ts = ordered[0] if ordered else None
    max_ts = ordered[-1] if ordered else None
    missing = expected - len(ordered)
    return {
        'symbol': symbol,
        'request_count': request_count,
        'expected_row_count': expected,
        'available_row_count': len(ordered),
        'missing_row_count': missing,
        'coverage_ratio': len(ordered) / expected if expected else 0.0,
        'min_timestamp_ms': min_ts,
        'max_timestamp_ms': max_ts,
        'min_timestamp_utc': datetime.fromtimestamp(min_ts/1000, tz=timezone.utc).isoformat() if min_ts is not None else None,
        'max_timestamp_utc': datetime.fromtimestamp(max_ts/1000, tz=timezone.utc).isoformat() if max_ts is not None else None,
        'covers_requested_start': bool(min_ts is not None and min_ts <= start_ms),
        'covers_requested_end': bool(max_ts is not None and max_ts >= end_ms - INTERVAL_MS),
        'full_exact_coverage': len(ordered) == expected and min_ts == start_ms and max_ts == end_ms - INTERVAL_MS,
        'raw_market_values_emitted': False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    start_ms, end_ms = utc_ms(START_UTC), utc_ms(END_EXCLUSIVE_UTC)
    rows = [probe_symbol(symbol, start_ms, end_ms) for symbol in SYMBOLS]
    common_earliest = max((row['min_timestamp_ms'] for row in rows if row['min_timestamp_ms'] is not None), default=None)
    all_full = all(row['full_exact_coverage'] for row in rows)
    receipt = {
        'schema_version': 'zel.edge_factory_v2.independent_18m_1h_coverage_probe.v1',
        'state': 'PASS_FULL_INDEPENDENT_HISTORY_AVAILABLE' if all_full else 'HOLD_INDEPENDENT_HISTORY_SOURCE_COVERAGE_GAP',
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'requested_start_ms': start_ms,
        'requested_end_exclusive_ms': end_ms,
        'symbols': list(SYMBOLS),
        'rows': rows,
        'common_earliest_available_ms': common_earliest,
        'common_earliest_available_utc': datetime.fromtimestamp(common_earliest/1000, tz=timezone.utc).isoformat() if common_earliest is not None else None,
        'full_exact_coverage_all_symbols': all_full,
        'economics_inspected': False,
        'ai_used': False,
        'selection_authority': False,
        'promotion_authority': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'action': 'hold',
    }
    receipt['receipt_sha256'] = stable_sha(receipt)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': receipt['state'], 'common_earliest_available_utc': receipt['common_earliest_available_utc'], 'rows': rows, 'receipt_sha256': receipt['receipt_sha256']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
