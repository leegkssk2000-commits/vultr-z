from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import zel_bingx_1m_backfill_stage_v1 as base

REPAIR_ROUNDS = 3
REPAIR_PADDING_BARS = 2


def _contiguous_ranges(timestamps: list[int]) -> list[tuple[int, int]]:
    if not timestamps:
        return []
    ranges: list[tuple[int, int]] = []
    start = prior = timestamps[0]
    for timestamp in timestamps[1:]:
        if timestamp != prior + base.INTERVAL_MS:
            ranges.append((start, prior + base.INTERVAL_MS))
            start = timestamp
        prior = timestamp
    ranges.append((start, prior + base.INTERVAL_MS))
    return ranges


def collect_symbol(symbol: str, out_dir: Path, start_ms: int, end_exclusive_ms: int) -> dict[str, Any]:
    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    requests = 0
    cursor = start_ms
    while cursor < end_exclusive_ms:
        chunk_end_exclusive = min(cursor + base.SAFE_CHUNK_BARS * base.INTERVAL_MS, end_exclusive_ms)
        rows = base.request_chunk(symbol, cursor, chunk_end_exclusive)
        requests += 1
        for row in rows:
            timestamp_ms = int(row["timestamp_ms"])
            if cursor <= timestamp_ms < chunk_end_exclusive:
                prior = rows_by_timestamp.get(timestamp_ms)
                if prior is not None and prior != row:
                    raise RuntimeError(f"CONFLICTING_DUPLICATE:{symbol}:{timestamp_ms}")
                rows_by_timestamp[timestamp_ms] = row
        cursor = chunk_end_exclusive
        time.sleep(0.12)

    expected = list(base.expected_timestamps(start_ms, end_exclusive_ms))
    repair_requests = 0
    for repair_round in range(1, REPAIR_ROUNDS + 1):
        missing = [timestamp for timestamp in expected if timestamp not in rows_by_timestamp]
        if not missing:
            break
        for gap_start, gap_end_exclusive in _contiguous_ranges(missing):
            request_start = max(start_ms, gap_start - REPAIR_PADDING_BARS * base.INTERVAL_MS)
            request_end = min(end_exclusive_ms, gap_end_exclusive + REPAIR_PADDING_BARS * base.INTERVAL_MS)
            rows = base.request_chunk(symbol, request_start, request_end, attempts=5)
            requests += 1
            repair_requests += 1
            for row in rows:
                timestamp_ms = int(row["timestamp_ms"])
                if start_ms <= timestamp_ms < end_exclusive_ms:
                    prior = rows_by_timestamp.get(timestamp_ms)
                    if prior is not None and prior != row:
                        raise RuntimeError(f"CONFLICTING_DUPLICATE:{symbol}:{timestamp_ms}")
                    rows_by_timestamp[timestamp_ms] = row
            time.sleep(0.5 * repair_round)

    missing = [timestamp for timestamp in expected if timestamp not in rows_by_timestamp]
    unexpected = sorted(timestamp for timestamp in rows_by_timestamp if timestamp < start_ms or timestamp >= end_exclusive_ms)
    if missing or unexpected:
        raise RuntimeError(
            f"COVERAGE_FAIL_AFTER_REPAIR:{symbol}:missing={len(missing)}:unexpected={len(unexpected)}:"
            f"first_missing={missing[:5]}:repair_requests={repair_requests}"
        )

    ordered = [rows_by_timestamp[timestamp] for timestamp in expected]
    output = out_dir / f"{symbol.replace('-', '')}_1m_{start_ms}_{end_exclusive_ms}.csv.gz"
    with base.gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = base.csv.DictWriter(handle, fieldnames=base.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    return {
        "symbol": symbol,
        "interval": base.INTERVAL,
        "start_ms": start_ms,
        "end_exclusive_ms": end_exclusive_ms,
        "start_utc": base.datetime.fromtimestamp(start_ms / 1000, tz=base.timezone.utc).isoformat(),
        "end_exclusive_utc": base.datetime.fromtimestamp(end_exclusive_ms / 1000, tz=base.timezone.utc).isoformat(),
        "expected_row_count": len(expected),
        "row_count": len(ordered),
        "request_count": requests,
        "repair_request_count": repair_requests,
        "duplicate_timestamp_count": 0,
        "missing_interval_count": 0,
        "unexpected_timestamp_count": 0,
        "first_timestamp_ms": int(ordered[0]["timestamp_ms"]),
        "last_timestamp_ms": int(ordered[-1]["timestamp_ms"]),
        "file": output.name,
        "file_bytes": output.stat().st_size,
        "file_sha256": base.file_sha(output),
    }


def main() -> int:
    base.collect_symbol = collect_symbol
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
