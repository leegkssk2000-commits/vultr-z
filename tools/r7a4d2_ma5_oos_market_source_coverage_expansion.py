#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

SEGMENT_BARS = 320
PREROLL_BARS = 320
INTERVAL = "1m"
INTERVAL_MS = 60_000
LOOKBACK_DAYS = 30
MAX_SYMBOLS = 5
MIN_SYMBOLS = 3
MIN_ROWS_PER_SOURCE = PREROLL_BARS + SEGMENT_BARS * 6
REQUEST_LIMIT = 1000
MAX_REQUESTS_PER_SYMBOL = 80
REQUEST_TIMEOUT_SECONDS = 20
ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v3/quote/klines",
    "https://open-api.bingx.com/openApi/swap/v2/quote/klines",
)

SELECTED_MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
FROZEN_MANIFEST = Path("runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json")
OOS_SUMMARY = Path("runtime/r7a4d2_ma5_independent_oos_expansion/ma5_independent_oos_summary_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_ma5_oos_market_source_coverage_expansion")
MARKET_DIR = OUTPUT_DIR / "market_data"
OVERLAY_MANIFEST = OUTPUT_DIR / "oos_overlay_frozen_input_manifest_v1.json"
SUMMARY_PATH = OUTPUT_DIR / "market_source_coverage_expansion_summary_v1.json"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def finite(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_timestamp_ms(value: Any) -> int:
    number = finite(value)
    if not math.isfinite(number):
        raise ValueError(f"TIMESTAMP_INVALID:{value!r}")
    integer = int(number)
    if integer < 10_000_000_000:
        integer *= 1000
    elif integer > 10_000_000_000_000:
        integer //= 1000
    return integer


def symbol_from_path(path: Path) -> str:
    stem = path.stem.upper()
    for token in stem.replace("-", "_").split("_"):
        if token.endswith("USDT") and len(token) >= 7:
            return token.replace("-", "")
    return ""


def normalize_symbol(value: str) -> str:
    cleaned = "".join(ch for ch in value.upper() if ch.isalnum())
    if cleaned.endswith("USDT") and len(cleaned) > 4:
        return cleaned
    return ""


def bingx_symbol(value: str) -> str:
    symbol = normalize_symbol(value)
    if not symbol:
        raise ValueError(f"SYMBOL_INVALID:{value!r}")
    return symbol[:-4] + "-USDT"


def extract_selected_symbols(root: Path, selected: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    for row in selected.get("selected_segments", []):
        if not isinstance(row, dict):
            continue
        symbol = normalize_symbol(str(row.get("symbol") or ""))
        if not symbol:
            source_path = str(row.get("source_path") or "")
            if source_path:
                symbol = symbol_from_path(root / safe_repo_path(source_path))
        if symbol:
            symbols.append(symbol)
    ordered = list(dict.fromkeys(symbols))
    fallback = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"]
    for symbol in fallback:
        if symbol not in ordered:
            ordered.append(symbol)
    return ordered[:MAX_SYMBOLS]


def selected_global_end_ms(selected: dict[str, Any]) -> int:
    values: list[int] = []
    for row in selected.get("selected_segments", []):
        if not isinstance(row, dict):
            continue
        raw = row.get("end_timestamp")
        if raw is None:
            continue
        try:
            values.append(normalize_timestamp_ms(raw))
        except ValueError:
            continue
    if not values:
        raise ValueError("SELECTED_END_TIMESTAMP_MISSING")
    return max(values)


def request_json(url: str, attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "ZEL-MA5-OOS-Coverage/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("BINGX_RESPONSE_NOT_OBJECT")
            return payload
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"BINGX_REQUEST_FAILED:{type(last_error).__name__}:{last_error}")


def payload_rows(payload: dict[str, Any]) -> list[Any]:
    data: Any = payload.get("data")
    if isinstance(data, dict):
        for key in ("data", "rows", "klines", "list"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []
    return data


def parse_kline(row: Any) -> list[float] | None:
    if isinstance(row, dict):
        timestamp = row.get("time")
        if timestamp is None:
            timestamp = row.get("timestamp", row.get("openTime", row.get("open_time")))
        values = [
            timestamp,
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
            row.get("volume", row.get("vol")),
        ]
    elif isinstance(row, (list, tuple)) and len(row) >= 6:
        values = list(row[:6])
    else:
        return None
    try:
        timestamp_ms = normalize_timestamp_ms(values[0])
        open_v, high_v, low_v, close_v, volume_v = (float(values[index]) for index in range(1, 6))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (open_v, high_v, low_v, close_v, volume_v)):
        return None
    if open_v <= 0 or close_v <= 0 or volume_v < 0:
        return None
    if high_v < max(open_v, close_v) or low_v > min(open_v, close_v) or high_v < low_v:
        return None
    return [float(timestamp_ms), open_v, high_v, low_v, close_v, volume_v]


def fetch_symbol_rows(symbol: str, start_ms: int, end_ms: int) -> tuple[list[list[float]], str, list[str]]:
    endpoint_errors: list[str] = []
    for endpoint in ENDPOINTS:
        cursor = start_ms
        collected: dict[int, list[float]] = {}
        requests = 0
        try:
            while cursor <= end_ms and requests < MAX_REQUESTS_PER_SYMBOL:
                window_end = min(end_ms, cursor + (REQUEST_LIMIT - 1) * INTERVAL_MS)
                query = urllib.parse.urlencode({
                    "symbol": bingx_symbol(symbol),
                    "interval": INTERVAL,
                    "limit": REQUEST_LIMIT,
                    "startTime": cursor,
                    "endTime": window_end,
                })
                payload = request_json(endpoint + "?" + query)
                code = payload.get("code")
                if code not in (None, 0, "0"):
                    raise RuntimeError(f"BINGX_CODE:{code}:{payload.get('msg') or payload.get('message')}")
                parsed = [item for item in (parse_kline(row) for row in payload_rows(payload)) if item is not None]
                requests += 1
                for item in parsed:
                    timestamp = int(item[0])
                    if start_ms <= timestamp <= end_ms:
                        collected[timestamp] = item
                if not parsed:
                    cursor = window_end + INTERVAL_MS
                    continue
                max_seen = max(int(item[0]) for item in parsed)
                next_cursor = max(window_end + INTERVAL_MS, max_seen + INTERVAL_MS)
                if next_cursor <= cursor:
                    next_cursor = cursor + REQUEST_LIMIT * INTERVAL_MS
                cursor = next_cursor
                time.sleep(0.08)
            rows = [collected[key] for key in sorted(collected)]
            if len(rows) >= MIN_ROWS_PER_SOURCE:
                return rows, endpoint, endpoint_errors
            endpoint_errors.append(f"{endpoint}:INSUFFICIENT_ROWS:{len(rows)}")
        except Exception as exc:
            endpoint_errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    return [], "", endpoint_errors


def validate_rows(rows: list[list[float]]) -> None:
    if len(rows) < MIN_ROWS_PER_SOURCE:
        raise ValueError(f"ROWS_BELOW_MINIMUM:{len(rows)}")
    timestamps = [int(row[0]) for row in rows]
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("TIMESTAMP_NOT_STRICT")
    gaps = Counter(int((right - left) // INTERVAL_MS) for left, right in zip(timestamps, timestamps[1:]))
    non_unit = sum(count for step, count in gaps.items() if step != 1)
    if non_unit > max(3, len(rows) // 1000):
        raise ValueError(f"TOO_MANY_GAPS:{non_unit}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    required = [root / SELECTED_MANIFEST, root / FROZEN_MANIFEST, root / OOS_SUMMARY]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_INPUT")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    selected = load_json(root / SELECTED_MANIFEST)
    frozen = load_json(root / FROZEN_MANIFEST)
    prior_oos = load_json(root / OOS_SUMMARY)
    blockers: list[str] = []
    if len(selected.get("selected_segments") or []) != 24:
        blockers.append("SELECTED_SEGMENT_COUNT_INVALID")
    if frozen.get("state") != "PASS":
        blockers.append("FROZEN_MANIFEST_NOT_PASS")
    if prior_oos.get("classification") != "MA5_OOS_DATA_COVERAGE_HOLD":
        blockers.append("PRIOR_OOS_NOT_COVERAGE_HOLD")
    if int(prior_oos.get("strict_forward_oos_segment_count", -1)) != 0:
        blockers.append("PRIOR_OOS_SEGMENT_COUNT_NOT_ZERO")
    if int(prior_oos.get("mutation_path_count", -1)) != 0:
        blockers.append("PRIOR_OOS_MUTATION_DETECTED")
    if blockers:
        print("STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_INPUT")
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    original_paths: list[Path] = []
    category_inputs = frozen.get("category_inputs") if isinstance(frozen.get("category_inputs"), dict) else {}
    for row in category_inputs.get("market_data", []):
        if isinstance(row, dict) and row.get("path"):
            original_paths.append(root / safe_repo_path(str(row["path"])))
    protected_paths = [root / SELECTED_MANIFEST, root / FROZEN_MANIFEST, root / OOS_SUMMARY] + original_paths
    before = {str(path): sha256_file(path) for path in protected_paths}

    global_end_ms = selected_global_end_ms(selected)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    closed_end_ms = (now_ms // INTERVAL_MS - 2) * INTERVAL_MS
    deterministic_floor = closed_end_ms - LOOKBACK_DAYS * 24 * 60 * INTERVAL_MS
    start_ms = max(global_end_ms + INTERVAL_MS, deterministic_floor)
    if closed_end_ms - start_ms < MIN_ROWS_PER_SOURCE * INTERVAL_MS:
        print("STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_WINDOW")
        print("BLOCKERS=[\"STRICT_FORWARD_WINDOW_TOO_SHORT\"]")
        print(f"DISCOVERY_GLOBAL_END_MS={global_end_ms}")
        print(f"OOS_START_MS={start_ms}")
        print(f"OOS_END_MS={closed_end_ms}")
        print("RC=2")
        return 2

    symbols = extract_selected_symbols(root, selected)
    if len(symbols) < MIN_SYMBOLS:
        print("STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_SYMBOLS")
        print("BLOCKERS=[\"SYMBOL_COVERAGE_BELOW_3\"]")
        print("RC=2")
        return 2

    output_dir = root / OUTPUT_DIR
    market_dir = root / MARKET_DIR
    market_dir.mkdir(parents=True, exist_ok=True)
    generated_entries: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for symbol in symbols:
        rows, endpoint, errors = fetch_symbol_rows(symbol, start_ms, closed_end_ms)
        if not rows:
            failures.append({"symbol": symbol, "errors": errors})
            continue
        try:
            validate_rows(rows)
            payload = {
                "schema": "zel_ma5_oos_public_bingx_ohlcv_v1",
                "source": "BingX public perpetual klines",
                "endpoint": endpoint,
                "symbol": symbol,
                "exchange_symbol": bingx_symbol(symbol),
                "interval": INTERVAL,
                "row_count": len(rows),
                "start_timestamp_ms": int(rows[0][0]),
                "end_timestamp_ms": int(rows[-1][0]),
                "strictly_after_discovery_global_end": int(rows[0][0]) > global_end_ms,
                "target_commit": args.target_sha,
                "selection_policy": "LATEST_FIXED_30D_OR_POST_DISCOVERY_START_NO_PERFORMANCE_SELECTION",
                "rows": rows,
            }
            filename = f"bingx_{symbol.lower()}_1m_oos_{int(rows[0][0])}_{int(rows[-1][0])}.json"
            path = market_dir / filename
            atomic_json(path, payload)
            digest = sha256_file(path)
            relative = path.relative_to(root).as_posix()
            segment_capacity = max(0, (len(rows) - PREROLL_BARS) // SEGMENT_BARS)
            entry = {
                "category": "market_data",
                "path": relative,
                "sha256": digest,
                "size_bytes": path.stat().st_size,
                "git_tracked": False,
                "target_git_parity": False,
                "oos_overlay": True,
                "public_source": "BingX",
                "symbol": symbol,
                "interval": INTERVAL,
                "row_count": len(rows),
                "segment_capacity": segment_capacity,
                "start_timestamp_ms": int(rows[0][0]),
                "end_timestamp_ms": int(rows[-1][0]),
            }
            generated_entries.append(entry)
            source_rows.append(entry)
        except Exception as exc:
            failures.append({"symbol": symbol, "errors": errors + [f"{type(exc).__name__}:{exc}"]})

    if len(generated_entries) < MIN_SYMBOLS:
        summary = {
            "state": "HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION",
            "target_commit": args.target_sha,
            "discovery_global_end_ms": global_end_ms,
            "oos_start_ms": start_ms,
            "oos_end_ms": closed_end_ms,
            "requested_symbols": symbols,
            "generated_source_count": len(generated_entries),
            "generated_sources": source_rows,
            "failures": failures,
            "blockers": ["GENERATED_SYMBOL_COUNT_BELOW_3"],
        }
        atomic_json(root / SUMMARY_PATH, summary)
        print("STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION")
        print(f"GENERATED_SOURCE_COUNT={len(generated_entries)}")
        print("BLOCKERS=[\"GENERATED_SYMBOL_COUNT_BELOW_3\"]")
        print("SUMMARY_JSON=" + str(root / SUMMARY_PATH))
        print("RC=2")
        return 2

    overlay = json.loads(json.dumps(frozen))
    overlay["schema"] = "r7a4d2_ma5_oos_overlay_frozen_input_manifest_v1"
    overlay["state"] = "PASS"
    overlay["official_stage"] = "R7.A4D2_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION"
    overlay["base_frozen_manifest_path"] = str(FROZEN_MANIFEST)
    overlay["target_commit"] = args.target_sha
    overlay["selection_policy"] = "STRICT_FORWARD_PUBLIC_MARKET_DATA_NO_PERFORMANCE_SELECTION"
    overlay_categories = overlay.setdefault("category_inputs", {})
    original_market = [row for row in overlay_categories.get("market_data", []) if isinstance(row, dict)]
    overlay_categories["market_data"] = original_market + generated_entries
    overlay["oos_generated_market_source_count"] = len(generated_entries)
    overlay["oos_generated_segment_capacity"] = sum(int(row["segment_capacity"]) for row in generated_entries)
    overlay["oos_discovery_global_end_ms"] = global_end_ms
    overlay["oos_start_ms"] = start_ms
    overlay["oos_end_ms"] = closed_end_ms
    atomic_json(root / OVERLAY_MANIFEST, overlay)

    after = {str(path): sha256_file(path) for path in protected_paths}
    mutations = sorted(path for path in before if before[path] != after[path])
    total_capacity = sum(int(row["segment_capacity"]) for row in generated_entries)
    coverage_ready = len(generated_entries) >= MIN_SYMBOLS and total_capacity >= 6 and not mutations
    summary = {
        "state": "PASS_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION" if coverage_ready else "HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION",
        "target_commit": args.target_sha,
        "discovery_global_end_ms": global_end_ms,
        "oos_start_ms": start_ms,
        "oos_end_ms": closed_end_ms,
        "requested_symbols": symbols,
        "generated_source_count": len(generated_entries),
        "generated_segment_capacity": total_capacity,
        "generated_sources": source_rows,
        "failures": failures,
        "overlay_manifest_path": str(OVERLAY_MANIFEST),
        "mutation_path_count": len(mutations),
        "mutation_paths": mutations,
        "coverage_ready": coverage_ready,
        "next_stage": "R7.A4D2_MA5_INDEPENDENT_OOS_REPLAY_WITH_OVERLAY" if coverage_ready else "R7.A4D2_MA5_OOS_MARKET_SOURCE_COVERAGE_RETRY",
    }
    atomic_json(root / SUMMARY_PATH, summary)

    print("STATE=" + summary["state"])
    print(f"DISCOVERY_GLOBAL_END_MS={global_end_ms}")
    print(f"OOS_START_MS={start_ms}")
    print(f"OOS_END_MS={closed_end_ms}")
    print("REQUESTED_SYMBOLS=" + json.dumps(symbols))
    print(f"GENERATED_SOURCE_COUNT={len(generated_entries)}")
    print(f"GENERATED_SEGMENT_CAPACITY={total_capacity}")
    for row in source_rows:
        print(
            "SOURCE="
            f"{row['symbol']}|ROWS={row['row_count']}|SEGMENTS={row['segment_capacity']}|"
            f"START={row['start_timestamp_ms']}|END={row['end_timestamp_ms']}|PATH={row['path']}"
        )
    print(f"MUTATION_PATH_COUNT={len(mutations)}")
    print("OVERLAY_MANIFEST=" + str(root / OVERLAY_MANIFEST))
    print("SUMMARY_JSON=" + str(root / SUMMARY_PATH))
    print("NEXT_STAGE=" + summary["next_stage"])
    print("BLOCKERS=" + json.dumps([] if coverage_ready else ["COVERAGE_NOT_READY"]))
    print("RC=" + ("0" if coverage_ready else "2"))
    return 0 if coverage_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
