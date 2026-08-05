from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_BINGX_BTC_REGIME_EVENT_DATASET_V1"
SCHEMA = "zel.btc.regime_event_dataset.v1"
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "1h": 3_600_000,
}
CHUNK_LIMIT = 1000
SAFE_CHUNK_BARS = CHUNK_LIMIT - 1
CSV_FIELDS = ("timestamp_ms", "open", "high", "low", "close", "volume")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def iso_utc(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def decimal_text(value: Any, field: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError(f"INVALID_DECIMAL:{field}:{value}") from exc
    if not number.is_finite():
        raise RuntimeError(f"NONFINITE_DECIMAL:{field}:{value}")
    if field != "volume" and number <= 0:
        raise RuntimeError(f"NONPOSITIVE_PRICE:{field}:{value}")
    if field == "volume" and number < 0:
        raise RuntimeError(f"NEGATIVE_VOLUME:{value}")
    return format(number, "f")


def extract_rows(payload: Mapping[str, Any]) -> list[Any]:
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for key in ("data", "rows", "items", "list", "klines"):
            child = data.get(key)
            if isinstance(child, list):
                return child
    raise RuntimeError("BINGX_KLINE_ROWS_MISSING")


def normalize_row(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        values = {
            "timestamp_ms": raw.get("openTime", raw.get("time", raw.get("timestamp"))),
            "open": raw.get("open"),
            "high": raw.get("high"),
            "low": raw.get("low"),
            "close": raw.get("close"),
            "volume": raw.get("volume", raw.get("vol", 0)),
        }
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) >= 6:
        values = {
            "timestamp_ms": raw[0],
            "open": raw[1],
            "high": raw[2],
            "low": raw[3],
            "close": raw[4],
            "volume": raw[5],
        }
    else:
        raise RuntimeError(f"UNSUPPORTED_KLINE_ROW:{type(raw).__name__}")
    try:
        timestamp_ms = int(float(values["timestamp_ms"]))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"INVALID_TIMESTAMP:{values.get('timestamp_ms')}") from exc
    row = {
        "timestamp_ms": timestamp_ms,
        "open": decimal_text(values["open"], "open"),
        "high": decimal_text(values["high"], "high"),
        "low": decimal_text(values["low"], "low"),
        "close": decimal_text(values["close"], "close"),
        "volume": decimal_text(values["volume"], "volume"),
    }
    prices = {key: Decimal(row[key]) for key in ("open", "high", "low", "close")}
    if prices["high"] < max(prices.values()):
        raise RuntimeError(f"OHLC_HIGH_INVALID:{timestamp_ms}")
    if prices["low"] > min(prices.values()):
        raise RuntimeError(f"OHLC_LOW_INVALID:{timestamp_ms}")
    return row


def request_chunk(
    *,
    base_url: str,
    endpoint: str,
    source_header: str,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    attempts: int = 5,
) -> list[dict[str, Any]]:
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": CHUNK_LIMIT,
    }
    request = urllib.request.Request(
        f"{base_url}{endpoint}?{urllib.parse.urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": VERSION,
            "X-SOURCE-KEY": source_header,
        },
    )
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = json.loads(response.read())
            return sorted((normalize_row(row) for row in extract_rows(payload)), key=lambda row: int(row["timestamp_ms"]))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}:{exc}"
            if attempt == attempts:
                break
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"BINGX_REQUEST_FAILED:{symbol}:{interval}:{start_ms}:{end_ms}:{last_error}")


def expected_timestamps(start_ms: int, end_exclusive_ms: int, interval_ms: int) -> Iterable[int]:
    return range(start_ms, end_exclusive_ms, interval_ms)


def collect_range(
    *,
    source: Mapping[str, Any],
    symbol: str,
    interval: str,
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    interval_ms = INTERVAL_MS[interval]
    if end_exclusive_ms <= start_ms or start_ms % interval_ms or end_exclusive_ms % interval_ms:
        raise RuntimeError(f"UNALIGNED_RANGE:{interval}:{start_ms}:{end_exclusive_ms}")
    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    conflicting_duplicates = 0
    requests = 0
    cursor = start_ms
    while cursor < end_exclusive_ms:
        chunk_end = min(cursor + SAFE_CHUNK_BARS * interval_ms, end_exclusive_ms)
        rows = request_chunk(
            base_url=str(source["base_url"]),
            endpoint=str(source["endpoint"]),
            source_header=str(source["source_header"]),
            symbol=symbol,
            interval=interval,
            start_ms=cursor,
            end_ms=chunk_end,
        )
        requests += 1
        for row in rows:
            timestamp = int(row["timestamp_ms"])
            if cursor <= timestamp < chunk_end:
                prior = rows_by_timestamp.get(timestamp)
                if prior is not None and prior != row:
                    conflicting_duplicates += 1
                    continue
                rows_by_timestamp[timestamp] = row
        cursor = chunk_end
        time.sleep(0.13)

    expected = list(expected_timestamps(start_ms, end_exclusive_ms, interval_ms))
    missing = [timestamp for timestamp in expected if timestamp not in rows_by_timestamp]
    ordered = [rows_by_timestamp[timestamp] for timestamp in expected if timestamp in rows_by_timestamp]
    unexpected = [timestamp for timestamp in rows_by_timestamp if timestamp < start_ms or timestamp >= end_exclusive_ms]
    coverage = len(ordered) / len(expected) * 100.0 if expected else 0.0
    stats = {
        "symbol": symbol,
        "interval": interval,
        "start_ms": start_ms,
        "end_exclusive_ms": end_exclusive_ms,
        "start_utc": iso_utc(start_ms),
        "end_exclusive_utc": iso_utc(end_exclusive_ms),
        "expected_row_count": len(expected),
        "row_count": len(ordered),
        "request_count": requests,
        "coverage_pct": coverage,
        "missing_interval_count": len(missing),
        "unexpected_timestamp_count": len(unexpected),
        "conflicting_duplicate_count": conflicting_duplicates,
        "first_missing_timestamp_ms": missing[0] if missing else None,
        "first_timestamp_ms": int(ordered[0]["timestamp_ms"]) if ordered else None,
        "last_timestamp_ms": int(ordered[-1]["timestamp_ms"]) if ordered else None,
    }
    return ordered, stats


def write_gzip_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError(f"EMPTY_OUTPUT_FORBIDDEN:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "file": path.name,
        "relative_path": path.as_posix(),
        "file_bytes": path.stat().st_size,
        "file_sha256": file_sha(path),
    }


def contiguous_segments(rows: Sequence[Mapping[str, Any]], interval_ms: int) -> list[list[Mapping[str, Any]]]:
    if not rows:
        return []
    segments: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = [rows[0]]
    for row in rows[1:]:
        if int(row["timestamp_ms"]) - int(current[-1]["timestamp_ms"]) == interval_ms:
            current.append(row)
        else:
            segments.append(current)
            current = [row]
    segments.append(current)
    return segments


def pct_return(start: float, end: float) -> float:
    return (end / start - 1.0) * 100.0 if start else 0.0


def detect_events(rows: Sequence[Mapping[str, Any]], detector: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    crash24 = float(detector["crash_24h_return_lte_pct"])
    crash72 = float(detector["crash_72h_return_lte_pct"])
    surge24 = float(detector["surge_24h_return_gte_pct"])
    surge72 = float(detector["surge_72h_return_gte_pct"])
    for segment in contiguous_segments(rows, INTERVAL_MS["1h"]):
        if len(segment) <= 72:
            continue
        closes = [float(row["close"]) for row in segment]
        for index in range(72, len(segment)):
            ret24 = pct_return(closes[index - 24], closes[index])
            ret72 = pct_return(closes[index - 72], closes[index])
            direction: str | None = None
            severity = 0.0
            if ret24 <= crash24 or ret72 <= crash72:
                direction = "crash"
                severity = max(abs(ret24 / crash24) if crash24 else 0.0, abs(ret72 / crash72) if crash72 else 0.0)
            elif ret24 >= surge24 or ret72 >= surge72:
                direction = "surge"
                severity = max(abs(ret24 / surge24) if surge24 else 0.0, abs(ret72 / surge72) if surge72 else 0.0)
            if direction:
                timestamp = int(segment[index]["timestamp_ms"])
                candidates.append({
                    "event_id": f"detected_{direction}_{timestamp}",
                    "event_type": "price_detected",
                    "direction": direction,
                    "center_ms": timestamp,
                    "center_utc": iso_utc(timestamp),
                    "return_24h_pct": ret24,
                    "return_72h_pct": ret72,
                    "severity": severity,
                    "source_key": "bingx:price_only_detector",
                })

    cooldown_ms = int(detector["cluster_cooldown_hours"]) * 3_600_000
    top_k = int(detector["top_k_per_direction"])
    selected: list[dict[str, Any]] = []
    for direction in ("crash", "surge"):
        rows_for_direction = sorted((row for row in candidates if row["direction"] == direction), key=lambda row: int(row["center_ms"]))
        clusters: list[dict[str, Any]] = []
        for row in rows_for_direction:
            if not clusters or int(row["center_ms"]) - int(clusters[-1]["cluster_last_ms"]) > cooldown_ms:
                clusters.append({"best": row, "cluster_last_ms": int(row["center_ms"])})
            else:
                clusters[-1]["cluster_last_ms"] = int(row["center_ms"])
                if float(row["severity"]) > float(clusters[-1]["best"]["severity"]):
                    clusters[-1]["best"] = row
        best = sorted((cluster["best"] for cluster in clusters), key=lambda row: float(row["severity"]), reverse=True)[:top_k]
        selected.extend(best)
    return sorted(selected, key=lambda row: int(row["center_ms"]))


def nearest_index(rows: Sequence[Mapping[str, Any]], timestamp_ms: int, tolerance_ms: int) -> int | None:
    if not rows:
        return None
    best_index = min(range(len(rows)), key=lambda index: abs(int(rows[index]["timestamp_ms"]) - timestamp_ms))
    return best_index if abs(int(rows[best_index]["timestamp_ms"]) - timestamp_ms) <= tolerance_ms else None


def event_features(rows: Sequence[Mapping[str, Any]], timestamp_ms: int) -> dict[str, Any]:
    index = nearest_index(rows, timestamp_ms, 2 * INTERVAL_MS["1h"])
    if index is None:
        return {"available": False}
    closes = [float(row["close"]) for row in rows]
    center = closes[index]
    result: dict[str, Any] = {
        "available": True,
        "matched_timestamp_ms": int(rows[index]["timestamp_ms"]),
        "matched_timestamp_utc": iso_utc(int(rows[index]["timestamp_ms"])),
        "center_close": center,
    }
    for hours in (24, 72):
        result[f"pre_{hours}h_return_pct"] = pct_return(closes[index - hours], center) if index >= hours else None
        result[f"post_{hours}h_return_pct"] = pct_return(center, closes[index + hours]) if index + hours < len(rows) else None
    future = closes[index : min(index + 73, len(rows))]
    result["post_72h_max_drawdown_pct"] = min((pct_return(center, value) for value in future), default=0.0)
    result["post_72h_max_runup_pct"] = max((pct_return(center, value) for value in future), default=0.0)
    if index >= 24:
        log_returns = [math.log(closes[pos] / closes[pos - 1]) for pos in range(index - 23, index + 1) if closes[pos - 1] > 0]
        result["pre_24h_realized_vol_pct"] = statistics.pstdev(log_returns) * math.sqrt(24) * 100.0 if len(log_returns) >= 2 else None
    else:
        result["pre_24h_realized_vol_pct"] = None
    return result


def floor_timestamp(timestamp_ms: int, interval_ms: int) -> int:
    return timestamp_ms - timestamp_ms % interval_ms


def collect_event_window(
    *,
    source: Mapping[str, Any],
    symbol: str,
    event: Mapping[str, Any],
    drilldown: Mapping[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    center_ms = int(event.get("center_ms") or utc_ms(str(event["center_utc"])))
    attempts = (
        (
            str(drilldown["primary_interval"]),
            int(drilldown["primary_pre_hours"]),
            int(drilldown["primary_post_hours"]),
            float(drilldown["primary_minimum_coverage_pct"]),
        ),
        (
            str(drilldown["fallback_interval"]),
            int(drilldown["fallback_pre_hours"]),
            int(drilldown["fallback_post_hours"]),
            float(drilldown["fallback_minimum_coverage_pct"]),
        ),
    )
    coverage_attempts: list[dict[str, Any]] = []
    for interval, pre_hours, post_hours, minimum_coverage in attempts:
        interval_ms = INTERVAL_MS[interval]
        aligned_center = floor_timestamp(center_ms, interval_ms)
        start_ms = aligned_center - pre_hours * 3_600_000
        end_ms = aligned_center + post_hours * 3_600_000
        rows, stats = collect_range(
            source=source,
            symbol=symbol,
            interval=interval,
            start_ms=start_ms,
            end_exclusive_ms=end_ms,
        )
        stats["minimum_coverage_pct"] = minimum_coverage
        accepted = (
            float(stats["coverage_pct"]) >= minimum_coverage
            and int(stats["unexpected_timestamp_count"]) == 0
            and int(stats["conflicting_duplicate_count"]) == 0
        )
        stats["accepted"] = accepted
        coverage_attempts.append(stats)
        if accepted:
            path = out_dir / "events" / f"{event['event_id']}_{interval}_{start_ms}_{end_ms}.csv.gz"
            file_info = write_gzip_csv(path, rows)
            return {
                "event_id": event["event_id"],
                "state": "PASS_EVENT_WINDOW_COLLECTED",
                "selected_interval": interval,
                "center_ms": center_ms,
                "center_utc": iso_utc(center_ms),
                "coverage_attempts": coverage_attempts,
                **file_info,
            }
    return {
        "event_id": event["event_id"],
        "state": "SOURCE_UNAVAILABLE_NO_INTERPOLATION",
        "selected_interval": None,
        "center_ms": center_ms,
        "center_utc": iso_utc(center_ms),
        "coverage_attempts": coverage_attempts,
        "file": None,
        "file_sha256": None,
    }


def run(catalog_path: Path, out_dir: Path, manifest_path: Path) -> dict[str, Any]:
    catalog = read_json(catalog_path)
    source = catalog["source"]
    symbol = str(catalog["symbol"])
    skeleton = catalog["skeleton"]
    start_ms = floor_timestamp(utc_ms(str(skeleton["start_utc"])), INTERVAL_MS["1h"])
    end_ms = floor_timestamp(utc_ms(str(skeleton["end_exclusive_utc"])), INTERVAL_MS["1h"])
    out_dir.mkdir(parents=True, exist_ok=True)

    skeleton_rows, skeleton_stats = collect_range(
        source=source,
        symbol=symbol,
        interval="1h",
        start_ms=start_ms,
        end_exclusive_ms=end_ms,
    )
    if not skeleton_rows:
        raise RuntimeError("BINGX_SKELETON_EMPTY")
    skeleton_file = out_dir / "BTCUSDT_1h_regime_skeleton.csv.gz"
    skeleton_info = write_gzip_csv(skeleton_file, skeleton_rows)
    skeleton_stats.update(skeleton_info)
    skeleton_stats["contiguous_segment_count"] = len(contiguous_segments(skeleton_rows, INTERVAL_MS["1h"]))

    detected = detect_events(skeleton_rows, catalog["detector"])
    anchors: list[dict[str, Any]] = []
    for raw in catalog["anchors"]:
        row = dict(raw)
        row["center_ms"] = utc_ms(str(row["center_utc"]))
        row["features"] = event_features(skeleton_rows, int(row["center_ms"]))
        anchors.append(row)
    for row in detected:
        row["features"] = event_features(skeleton_rows, int(row["center_ms"]))

    events: list[dict[str, Any]] = anchors + detected
    drilldowns = [
        collect_event_window(
            source=source,
            symbol=symbol,
            event=event,
            drilldown=catalog["drilldown"],
            out_dir=out_dir,
        )
        for event in events
    ]
    accepted_files = [row for row in drilldowns if row["state"] == "PASS_EVENT_WINDOW_COLLECTED"]
    unavailable = [row for row in drilldowns if row["state"] != "PASS_EVENT_WINDOW_COLLECTED"]
    data_material = [
        {"path": skeleton_info["relative_path"], "sha256": skeleton_info["file_sha256"]},
        *[
            {"path": row["relative_path"], "sha256": row["file_sha256"]}
            for row in accepted_files
        ],
    ]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_BTC_REGIME_EVENT_DATASET_COLLECTED" if accepted_files else "HOLD_BINGX_EVENT_SOURCE_UNAVAILABLE",
        "catalog_path": str(catalog_path),
        "catalog_sha256": file_sha(catalog_path),
        "symbol": symbol,
        "source": source,
        "skeleton": skeleton_stats,
        "detector": catalog["detector"],
        "detected_event_count": len(detected),
        "anchor_event_count": len(anchors),
        "events": events,
        "drilldown": catalog["drilldown"],
        "drilldowns": drilldowns,
        "accepted_event_window_count": len(accepted_files),
        "source_unavailable_event_count": len(unavailable),
        "data_files": data_material,
        "dataset_sha256": stable_sha(data_material),
        "economics_inspected": False,
        "holdout_metrics_inspected": False,
        "event_labels_used_for_strategy_selection": False,
        "interpolation_used": False,
        "synthetic_candles_used": False,
        "strategy_rules_mutated": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_mutated": False,
        "paper_mutated": False,
        "live_mutated": False,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "VERIFY_AND_SEAL_EVENT_CORPUS_THEN_PREREGISTER_STRESS_USE",
    }
    manifest["receipt_sha256"] = stable_sha(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    sample = normalize_row([1_700_000_000_000, "10", "12", "9", "11", "3"])
    assert sample["timestamp_ms"] == 1_700_000_000_000
    assert len(list(expected_timestamps(0, 180_000, 60_000))) == 3
    rows: list[dict[str, Any]] = []
    price = 100.0
    for hour in range(200):
        if hour == 100:
            price *= 0.75
        elif hour == 160:
            price *= 1.35
        rows.append({
            "timestamp_ms": hour * INTERVAL_MS["1h"],
            "open": str(price),
            "high": str(price),
            "low": str(price),
            "close": str(price),
            "volume": "1",
        })
    detector = {
        "crash_24h_return_lte_pct": -8.0,
        "crash_72h_return_lte_pct": -15.0,
        "surge_24h_return_gte_pct": 8.0,
        "surge_72h_return_gte_pct": 15.0,
        "cluster_cooldown_hours": 24,
        "top_k_per_direction": 5,
    }
    events = detect_events(rows, detector)
    assert any(row["direction"] == "crash" for row in events)
    assert any(row["direction"] == "surge" for row in events)
    assert event_features(rows, 100 * INTERVAL_MS["1h"])["available"] is True
    assert floor_timestamp(61_001, 60_000) == 60_000
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not all((args.catalog, args.out_dir, args.manifest)):
        parser.error("catalog, out-dir and manifest are required")
    receipt = run(args.catalog.resolve(), args.out_dir.resolve(), args.manifest.resolve())
    print(json.dumps({
        "state": receipt["state"],
        "detected_event_count": receipt["detected_event_count"],
        "accepted_event_window_count": receipt["accepted_event_window_count"],
        "source_unavailable_event_count": receipt["source_unavailable_event_count"],
        "dataset_sha256": receipt["dataset_sha256"],
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0 if str(receipt["state"]).startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
