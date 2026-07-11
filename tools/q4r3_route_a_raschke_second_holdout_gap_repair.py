from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
OVERLAY_ROOT = Path(
    os.environ.get(
        "Q4R3_ROUTE_A_OVERLAY_ROOT",
        "/tmp/q4r3-route-a-video-fidelity",
    )
)
BASE_PATH = OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_second_holdout.py"
CHECKPOINT_EVERY_PAGES = 50
REPAIR_ROUNDS = 6
MAX_QUARANTINED_MISSING_MINUTES = 5
MAX_QUARANTINED_GAP_RANGES = 1


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
ORIGINAL_SIMULATE_TRADE = BASE.FORENSIC.BASE.simulate_trade


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


def _missing_from_stamps(stamps: Sequence[int]) -> List[int]:
    if not stamps:
        return []
    missing: List[int] = []
    ordered = sorted(set(int(stamp) for stamp in stamps))
    for previous, current in zip(ordered, ordered[1:]):
        expected = previous + BASE.MINUTE_MS
        while expected < current:
            missing.append(expected)
            expected += BASE.MINUTE_MS
    return missing


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


def _sparse_gap_allowed(missing: Sequence[int]) -> bool:
    return bool(
        0 < len(missing) <= MAX_QUARANTINED_MISSING_MINUTES
        and len(_contiguous_ranges(missing)) <= MAX_QUARANTINED_GAP_RANGES
    )


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
                remaining_inside_gap = [
                    stamp
                    for stamp in _missing_timestamps(candles, gap_start, gap_end)
                    if gap_start <= stamp <= gap_end
                ]
                if not remaining_inside_gap:
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
        "missing_utc": [
            str(pd.to_datetime(stamp, unit="ms", utc=True))
            for stamp in final_missing
        ],
    }


def _validate_sparse_file(
    path: Path,
    *,
    start_ms: int,
    end_ms: int,
    rows_required: int,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    if not path.exists():
        return False, None, "MISSING"
    try:
        payload = json.loads(path.read_text(errors="ignore"))
    except Exception as exc:
        return False, None, f"JSON_ERROR:{exc!r}"
    rows = payload.get("rows", [])
    stamps = sorted(
        {
            BASE._timestamp_ms(row[0])
            for row in rows
            if isinstance(row, list) and len(row) >= 6
        }
    )
    if not stamps:
        return False, payload, "EMPTY"
    if stamps[0] != start_ms:
        return False, payload, "START_MISMATCH"
    if stamps[-1] != end_ms:
        return False, payload, "END_MISMATCH"
    missing = _missing_from_stamps(stamps)
    if not missing:
        if len(stamps) != rows_required:
            return False, payload, f"COUNT={len(stamps)}"
        return True, payload, "PASS_CONTIGUOUS"
    if not _sparse_gap_allowed(missing):
        return False, payload, f"UNAPPROVED_GAPS={len(missing)}"
    if len(stamps) != rows_required - len(missing):
        return False, payload, f"SPARSE_COUNT={len(stamps)}"
    declared = sorted(int(value) for value in payload.get("missing_timestamps", []))
    if declared and declared != missing:
        return False, payload, "DECLARED_GAP_MISMATCH"
    return True, payload, "PASS_SPARSE_GAP_QUARANTINE"


def sparse_load_frame(path: Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    payload = json.loads(path.read_text(errors="ignore"))
    records: List[Dict[str, Any]] = []
    for row in payload.get("rows", []):
        if not isinstance(row, list) or len(row) < 6:
            continue
        stamp = BASE._timestamp_ms(row[0])
        records.append(
            {
                "ts": stamp,
                "ts_dt": pd.to_datetime(stamp, unit="ms", utc=True),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        raise RuntimeError(f"EMPTY_DATA:{path}")
    frame = frame.sort_values("ts_dt").drop_duplicates("ts_dt", keep="last").reset_index(drop=True)
    frame["raw_idx"] = range(len(frame))
    stamps = [int(value) for value in frame["ts"].tolist()]
    missing = _missing_from_stamps(stamps)
    duplicate_ts = int(frame["ts_dt"].duplicated().sum())
    if duplicate_ts:
        raise RuntimeError(f"DATA_DUPLICATE_TS:{path}:{duplicate_ts}")
    if missing and not _sparse_gap_allowed(missing):
        raise RuntimeError(f"DATA_UNAPPROVED_GAP:{path}:{len(missing)}")
    integrity = {
        "path": str(path),
        "rows": int(len(frame)),
        "start": str(frame["ts_dt"].iloc[0]),
        "end": str(frame["ts_dt"].iloc[-1]),
        "duplicate_ts": duplicate_ts,
        "gap_count": len(_contiguous_ranges(missing)) if missing else 0,
        "missing_minutes": len(missing),
        "missing_timestamps": missing,
        "missing_utc": [
            str(pd.to_datetime(stamp, unit="ms", utc=True))
            for stamp in missing
        ],
        "integrity_mode": "sparse_gap_quarantine" if missing else "strict_contiguous",
        "quarantine_policy": {
            "no_interpolation": True,
            "incomplete_signal_bars_rejected": True,
            "trade_horizons_crossing_gap_rejected": True,
            "indicator_window_resets_via_contiguous_window_gate": True,
        },
        "valid": True,
    }
    frame.attrs["missing_timestamps"] = missing
    return frame, integrity


def sparse_safe_simulate_trade(
    raw: pd.DataFrame,
    *,
    entry_idx: int,
    side: str,
    signal_entry: float,
    native_stop: float,
    contract: Dict[str, float],
    timeout_min: int,
) -> Optional[Dict[str, Any]]:
    if entry_idx < 0 or entry_idx >= len(raw):
        return None
    last_idx = min(len(raw) - 1, entry_idx + max(int(timeout_min), 1) - 1)
    horizon = raw.iloc[entry_idx : last_idx + 1]
    diffs = horizon["ts"].diff().dropna()
    if bool((diffs != BASE.MINUTE_MS).any()):
        return None
    return ORIGINAL_SIMULATE_TRADE(
        raw,
        entry_idx=entry_idx,
        side=side,
        signal_entry=signal_entry,
        native_stop=native_stop,
        contract=contract,
        timeout_min=timeout_min,
    )


def collect_symbol(
    symbol: str,
    api_symbol: str,
    start_ms: int,
    end_ms: int,
    rows_required: int,
    current_holdout_start_ms: int,
) -> Tuple[Path, int, str]:
    final_path = BASE.SECOND_HOLDOUT_DIR / f"{symbol}_1m_{BASE.HOLDOUT_DAYS}d_pre90d.json"
    valid, _, reason = _validate_sparse_file(
        final_path,
        start_ms=start_ms,
        end_ms=end_ms,
        rows_required=rows_required,
    )
    if valid:
        print(f"REUSE {symbol} rows={rows_required} mode={reason}", flush=True)
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
    max_new_pages = max(0, math.ceil(rows_required / BASE.REQUEST_LIMIT) + 25)
    print(
        f"COLLECT_RESUME {symbol} cached={len(candles)} pages={pages} cursor={cursor}",
        flush=True,
    )

    if candles and min(candles) <= start_ms:
        print(f"COLLECT_BULK_COMPLETE {symbol} cached={len(candles)}", flush=True)
    else:
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
    missing = repair["missing_timestamps"]
    sparse_allowed = _sparse_gap_allowed(missing)
    _write_checkpoint(
        partial_path,
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        rows_required=rows_required,
        candles=candles,
        pages=pages,
        stage=(
            "repair_complete"
            if not missing
            else "sparse_gap_quarantine_ready"
            if sparse_allowed
            else "repair_failed"
        ),
    )

    stamps = sorted(candles)
    failures: List[str] = []
    expected_count = rows_required - len(missing)
    if len(stamps) != expected_count:
        failures.append(f"COUNT={len(stamps)} expected={expected_count}")
    if not stamps or stamps[0] != start_ms:
        failures.append("START_MISMATCH")
    if not stamps or stamps[-1] != end_ms:
        failures.append("END_MISMATCH")
    if end_ms >= current_holdout_start_ms:
        failures.append("OVERLAP")
    if missing and not sparse_allowed:
        failures.append(f"UNRESOLVED_MISSING={repair['missing_utc'][:20]}")
    if failures:
        raise RuntimeError(
            f"{symbol}:{','.join(failures)}:existing={reason}:partial={partial_path}"
        )

    integrity_mode = "sparse_gap_quarantine" if missing else "strict_contiguous"
    payload = {
        "symbol": symbol,
        "source": "bingx_public",
        "timeframe": "1m",
        "window_relation": "strictly_before_existing_90d_holdout",
        "start_ms": start_ms,
        "end_ms": end_ms,
        "current_holdout_start_ms": current_holdout_start_ms,
        "rows_required": rows_required,
        "rows_count": len(stamps),
        "collection_pages": pages,
        "gap_repair": repair,
        "integrity_mode": integrity_mode,
        "missing_timestamps": missing,
        "missing_utc": repair["missing_utc"],
        "quarantine_policy": {
            "no_interpolation": True,
            "max_missing_minutes": MAX_QUARANTINED_MISSING_MINUTES,
            "max_gap_ranges": MAX_QUARANTINED_GAP_RANGES,
            "incomplete_signal_bars_rejected": True,
            "trade_horizons_crossing_gap_rejected": True,
            "contiguous_indicator_window_required": True,
        },
        "rows": _payload_rows(candles),
    }
    _atomic_write(final_path, payload)
    partial_path.unlink(missing_ok=True)
    print(
        f"PASS COLLECT {symbol} rows={len(stamps)} pages={pages} mode={integrity_mode} missing={len(missing)}",
        flush=True,
    )
    action = (
        "COLLECTED_WITH_SPARSE_GAP_QUARANTINE"
        if missing
        else "COLLECTED_WITH_GAP_REPAIR"
    )
    return final_path, pages, action


def main() -> None:
    BASE.collect_symbol = collect_symbol
    BASE.FORENSIC.BASE.load_frame = sparse_load_frame
    BASE.FORENSIC.BASE.simulate_trade = sparse_safe_simulate_trade
    BASE.main()


if __name__ == "__main__":
    main()
