from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

ROOT = Path("/home/z/z")
OVERLAY_ROOT = Path(
    __import__("os").environ.get(
        "Q4R3_ROUTE_A_OVERLAY_ROOT",
        "/tmp/q4r3-route-a-video-fidelity",
    )
)
BASE_PATH = OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_second_holdout.py"
CHECKPOINT_EVERY_PAGES = 50
REPAIR_ROUNDS = 6


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location(
        "q4r3_raschke_second_holdout_base",
        BASE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"SECOND_HOLDOUT_IMPORT_SPEC_FAILED:{BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _checkpoint_path(final_path: Path) -> Path:
    return final_path.with_suffix(".partial.json")


def _payload_rows(candles: Dict[int, Dict[str, float]]) -> List[List[float]]:
    return [
        [
            int(row["ts"]),
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
        ]
        for _, row in sorted(candles.items())
    ]


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_checkpoint(
    path: Path,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    rows_required: int,
    candles: Dict[int, Dict[str, float]],
    pages: int,
    stage: str,
) -> None:
    _atomic_write(
        path,
        {
            "status": "PARTIAL_BINGX_1M_COLLECTION",
            "symbol": symbol,
            "start_ms": int(start_ms),
            "end_ms": int(end_ms),
            "rows_required": int(rows_required),
            "rows_count": len(candles),
            "pages": int(pages),
            "stage": stage,
            "rows": _payload_rows(candles),
        },
    )


def _load_checkpoint(
    path: Path,
    *,
    start_ms: int,
    end_ms: int,
    rows_required: int,
) -> Tuple[Dict[int, Dict[str, float]], int]:
    if not path.exists():
        return {}, 0
    try:
        payload = json.loads(path.read_text(errors="ignore"))
    except Exception:
        return {}, 0
    if (
        int(payload.get("start_ms", -1)) != int(start_ms)
        or int(payload.get("end_ms", -1)) != int(end_ms)
        or int(payload.get("rows_required", -1)) != int(rows_required)
    ):
        return {}, 0
    candles: Dict[int, Dict[str, float]] = {}
    for row in payload.get("rows", []):
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            stamp = BASE._timestamp_ms(row[0])
            normalized = {
                "ts": stamp,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            start_ms <= stamp <= end_ms
            and min(
                normalized["open"],
                normalized["high"],
                normalized["low"],
                normalized["close"],
            )
            > 0
            and normalized["high"] >= normalized["low"]
            and normalized["volume"] >= 0
        ):
            candles[stamp] = normalized
    return candles, int(payload.get("pages", 0))


def _missing_timestamps(
    candles: Dict[int, Dict[str, float]],
    start_ms: int,
    end_ms: int,
) -> List[int]:
    present = set(candles)
    return [
        stamp
        for stamp in range(int(start_ms), int(end_ms) + BASE.MINUTE_MS, BASE.MINUTE_MS)
        if stamp not in present
    ]


def _contiguous_ranges(stamps: Sequence[int]) -> List[Tuple[int, int]]:
    if not stamps:
        return []
    ordered = sorted(set(int(stamp) for stamp in stamps))
    ranges: List[Tuple[int, int]] = []
    start = previous = ordered[0]
    for stamp in ordered[1:]:
        if stamp != previous + BASE.MINUTE_MS:
            ranges.append((start, previous))
            start = stamp
        previous = stamp
    ranges.append((start, previous))
    return ranges


def _merge_rows(
    candles: Dict[int, Dict[str, float]],
    rows: Iterable[Dict[str, float]],
    *,
    start_ms: int,
    end_ms: int,
) -> int:
    before = len(candles)
    for row in rows:
        stamp = int(row["ts"])
        if start_ms <= stamp <= end_ms:
            candles[stamp] = row
    return len(candles) - before


def _repair_gaps(
    api_symbol: str,
    candles: Dict[int, Dict[str, float]],
    *,
    start_ms: int,
    end_ms: int,
) -> Dict[str, Any]:
    history: List[Dict[str, Any]] = []
    initial_missing = _missing_timestamps(candles, start_ms, end_ms)
    for round_number in range(1, REPAIR_ROUNDS + 1):
        missing = _missing_timestamps(candles, start_ms, end_ms)
        if not missing:
            break
        added_round = 0
        ranges = _contiguous_ranges(missing)
        for gap_start, gap_end in ranges:
            anchors = {
                min(end_ms, gap_end + (BASE.REQUEST_LIMIT - 1) * BASE.MINUTE_MS),
                min(end_ms, gap_end + 120 * BASE.MINUTE_MS),
                min(end_ms, gap_end + 30 * BASE.MINUTE_MS),
                min(end_ms, gap_end + BASE.MINUTE_MS),
                gap_end,
            }
            for anchor in sorted(anchors, reverse=True):
                rows = BASE._fetch_page(api_symbol, int(anchor))
                added_round += _merge_rows(
                    candles,
                    rows,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
                if not any(gap_start <= stamp <= gap_end for stamp in _missing_timestamps(candles, gap_start, gap_end)):
                    break
        remaining = _missing_timestamps(candles, start_ms, end_ms)
        history.append(
            {
                "round": round_number,
                "ranges": len(ranges),
                "added": added_round,
                "remaining": len(remaining),
            }
        )
        print(
            f"GAP_REPAIR round={round_number} added={added_round} remaining={len(remaining)}",
            flush=True,
        )
        if not remaining:
            break
        time.sleep(min(2**round_number, 20))
    final_missing = _missing_timestamps(candles, start_ms, end_ms)
    return {
        "initial_missing": len(initial_missing),
        "final_missing": len(final_missing),
        "history": history,
        "missing_timestamps": final_missing,
    }


def collect_symbol(
    symbol: str,
    api_symbol: str,
    start_ms: int,
    end_ms: int,
    rows_required: int,
    current_holdout_start_ms: int,
) -> Tuple[Path, int, str]:
    final_path = BASE.SECOND_HOLDOUT_DIR / f"{symbol}_1m_{BASE.HOLDOUT_DAYS}d_pre90d.json"
    valid, _, reason = BASE.validate_file(final_path, start_ms, end_ms, rows_required)
    if valid:
        print(f"REUSE {symbol} rows={rows_required}", flush=True)
        return final_path, 0, "REUSE"

    partial_path = _checkpoint_path(final_path)
    candles, prior_pages = _load_checkpoint(
        partial_path,
        start_ms=start_ms,
        end_ms=end_ms,
        rows_required=rows_required,
    )
    pages = prior_pages
    cursor = min(candles) - BASE.MINUTE_MS if candles else end_ms
    max_new_pages = max(0, __import__("math").ceil(rows_required / BASE.REQUEST_LIMIT) + 25)
    print(
        f"COLLECT_RESUME {symbol} cached={len(candles)} pages={pages} cursor={cursor}",
        flush=True,
    )

    for _ in range(max_new_pages):
        api_rows = BASE._fetch_page(api_symbol, cursor)
        pages += 1
        _merge_rows(candles, api_rows, start_ms=start_ms, end_ms=end_ms)
        oldest = min(int(row["ts"]) for row in api_rows)
        if pages % CHECKPOINT_EVERY_PAGES == 0:
            _write_checkpoint(
                partial_path,
                symbol=symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                rows_required=rows_required,
                candles=candles,
                pages=pages,
                stage="bulk",
            )
            print(f"COLLECT {symbol} page={pages} unique={len(candles)}", flush=True)
        if oldest <= start_ms:
            break
        cursor = oldest - BASE.MINUTE_MS
        time.sleep(BASE.REQUEST_SLEEP)

    repair = _repair_gaps(
        api_symbol,
        candles,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    _write_checkpoint(
        partial_path,
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        rows_required=rows_required,
        candles=candles,
        pages=pages,
        stage="repair_complete" if repair["final_missing"] == 0 else "repair_failed",
    )

    stamps = sorted(candles)
    failures: List[str] = []
    if len(stamps) != rows_required:
        failures.append(f"COUNT={len(stamps)}")
    if not stamps or stamps[0] != start_ms:
        failures.append("START_MISMATCH")
    if not stamps or stamps[-1] != end_ms:
        failures.append("END_MISMATCH")
    gaps = sum(
        stamps[index] - stamps[index - 1] != BASE.MINUTE_MS
        for index in range(1, len(stamps))
    )
    if gaps:
        failures.append(f"GAPS={gaps}")
    if end_ms >= current_holdout_start_ms:
        failures.append("OVERLAP")
    if repair["final_missing"]:
        preview = [
            str(__import__("pandas").to_datetime(stamp, unit="ms", utc=True))
            for stamp in repair["missing_timestamps"][:20]
        ]
        failures.append(f"UNRESOLVED_MISSING={preview}")
    if failures:
        raise RuntimeError(
            f"{symbol}:{','.join(failures)}:existing={reason}:partial={partial_path}"
        )

    payload = {
        "symbol": symbol,
        "source": "bingx_public",
        "timeframe": "1m",
        "window_relation": "strictly_before_existing_90d_holdout",
        "start_ms": start_ms,
        "end_ms": end_ms,
        "current_holdout_start_ms": current_holdout_start_ms,
        "rows_count": len(stamps),
        "collection_pages": pages,
        "gap_repair": repair,
        "rows": _payload_rows(candles),
    }
    _atomic_write(final_path, payload)
    partial_path.unlink(missing_ok=True)
    print(
        f"PASS COLLECT {symbol} rows={len(stamps)} pages={pages} repaired={repair['initial_missing']}",
        flush=True,
    )
    return final_path, pages, "COLLECTED_WITH_GAP_REPAIR"


def main() -> None:
    BASE.collect_symbol = collect_symbol
    BASE.main()


if __name__ == "__main__":
    main()
