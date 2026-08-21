from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPEC = ROOT / "backend/research/architecture_factory/a1_external_research_exact8_spec_v1.json"
ENDPOINT = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
SYMBOLS = ("BTC-USDT", "ETH-USDT")

# These are the frozen parent-policy warmups, not values selected from outcomes.
CANDIDATE_WARMUPS = {
    "anchor_vwap_trend": 64,
    "bb_revert": 58,
    "break_and_continue": 64,
    "fvg_revert": 40,
    "range_fade": 40,
    "session_bias": 90,
}
INTERVAL_BY_MS = {300_000: "5m", 3_600_000: "1h"}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _number(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except Exception as exc:
        raise ValueError(f"BAR_FIELD_INVALID:{field}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"BAR_FIELD_NONFINITE:{field}")
    return parsed


def normalize_bar(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        try:
            ts_ms = int(raw.get("time", raw.get("ts_ms", raw.get("timestamp"))))
            opened = _number(raw["open"], "open")
            high = _number(raw["high"], "high")
            low = _number(raw["low"], "low")
            close = _number(raw["close"], "close")
            volume = _number(raw["volume"], "volume")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("BINGX_KLINE_OBJECT_INVALID") from exc
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) >= 6:
        # Supported only as a defensive compatibility path. BingX swap v3 normally
        # returns objects; array-form OHLCV follows timestamp/open/high/low/close/volume.
        try:
            ts_ms = int(raw[0])
            opened, high, low, close, volume = (
                _number(raw[i], name)
                for i, name in zip(range(1, 6), ("open", "high", "low", "close", "volume"))
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("BINGX_KLINE_ARRAY_INVALID") from exc
    else:
        raise ValueError("BINGX_KLINE_SHAPE_INVALID")
    return {
        "ts_ms": ts_ms,
        "open": opened,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def extract_rows(payload: Any) -> list[Any]:
    if not isinstance(payload, Mapping):
        raise RuntimeError("BINGX_RESPONSE_OBJECT_REQUIRED")
    code = payload.get("code", 0)
    if str(code) not in {"0", "000000"}:
        raise RuntimeError(f"BINGX_RESPONSE_CODE:{code}")
    rows = payload.get("data")
    if isinstance(rows, Mapping):
        rows = rows.get("data", rows.get("list", rows.get("rows")))
    if not isinstance(rows, list):
        raise RuntimeError("BINGX_KLINE_LIST_REQUIRED")
    return rows


def fetch_klines(symbol: str, timeframe_ms: int, *, limit: int = 1000) -> list[Any]:
    interval = INTERVAL_BY_MS.get(timeframe_ms)
    if interval is None:
        raise ValueError("UNSUPPORTED_TIMEFRAME")
    query = urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    request = Request(
        f"{ENDPOINT}?{query}",
        headers={"Accept": "application/json", "User-Agent": "zel-source-audit/1.0"},
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return extract_rows(payload)


def audit_stream(
    raw_rows: Sequence[Any], *, symbol: str, timeframe_ms: int, now_ms: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    for raw in raw_rows:
        try:
            normalized.append(normalize_bar(raw))
        except ValueError as exc:
            parse_errors.append(str(exc))

    normalized.sort(key=lambda row: row["ts_ms"])
    timestamps = [row["ts_ms"] for row in normalized]
    duplicate_count = len(timestamps) - len(set(timestamps))
    closed = [row for row in normalized if row["ts_ms"] + timeframe_ms <= now_ms]
    in_progress_excluded = len(normalized) - len(closed)

    gap_count = 0
    ohlc_invalid_count = 0
    nonpositive_volume_count = 0
    for index, row in enumerate(closed):
        if index and row["ts_ms"] - closed[index - 1]["ts_ms"] != timeframe_ms:
            gap_count += 1
        opened, high, low, close = (row[key] for key in ("open", "high", "low", "close"))
        if (
            min(opened, high, low, close) <= 0
            or high < max(opened, close)
            or low > min(opened, close)
            or high < low
        ):
            ohlc_invalid_count += 1
        if row["volume"] <= 0:
            nonpositive_volume_count += 1

    blockers: list[str] = []
    if parse_errors:
        blockers.append("BAR_PARSE_FAILURE")
    if duplicate_count:
        blockers.append("DUPLICATE_TIMESTAMP")
    if gap_count:
        blockers.append("INTERVAL_DISCONTINUITY")
    if ohlc_invalid_count:
        blockers.append("OHLC_INTEGRITY_FAILURE")
    if nonpositive_volume_count:
        blockers.append("NONPOSITIVE_VOLUME")
    if not closed:
        blockers.append("NO_COMPLETED_BARS")

    row = {
        "symbol": symbol,
        "timeframe_ms": timeframe_ms,
        "interval": INTERVAL_BY_MS[timeframe_ms],
        "raw_count": len(raw_rows),
        "normalized_count": len(normalized),
        "completed_bar_count": len(closed),
        "in_progress_bar_count_excluded": in_progress_excluded,
        "first_completed_ts_ms": closed[0]["ts_ms"] if closed else None,
        "last_completed_ts_ms": closed[-1]["ts_ms"] if closed else None,
        "parse_error_count": len(parse_errors),
        "duplicate_timestamp_count": duplicate_count,
        "interval_gap_count": gap_count,
        "ohlc_invalid_count": ohlc_invalid_count,
        "nonpositive_volume_count": nonpositive_volume_count,
        "strictly_monotonic_after_sort": duplicate_count == 0,
        "completed_bars_only": True,
        "state": "PASS_SOURCE_STREAM_INTEGRITY" if not blockers else "HOLD_SOURCE_STREAM_INTEGRITY",
        "blockers": blockers,
    }
    return row, closed


def build_receipt(
    spec: dict[str, Any],
    raw_streams: Mapping[tuple[str, int], Sequence[Any]],
    *,
    now_ms: int,
) -> dict[str, Any]:
    specs = spec.get("specs") or {}
    if set(CANDIDATE_WARMUPS) - set(specs):
        raise RuntimeError("EXACT8_SOURCE_AUDIT_SPEC_REQUIRED")
    if spec.get("threshold_search") is not False or spec.get("holdout_outcomes_accessed") is not False:
        raise RuntimeError("OUTCOME_BLIND_SPEC_REQUIRED")

    stream_rows: list[dict[str, Any]] = []
    completed: dict[tuple[str, int], list[dict[str, Any]]] = {}
    required_keys = {
        (symbol, int(specs[parent_id]["timeframe_ms"]))
        for parent_id in CANDIDATE_WARMUPS
        for symbol in SYMBOLS
    }
    for symbol, timeframe_ms in sorted(required_keys):
        key = (symbol, timeframe_ms)
        if key not in raw_streams:
            stream_rows.append(
                {
                    "symbol": symbol,
                    "timeframe_ms": timeframe_ms,
                    "interval": INTERVAL_BY_MS[timeframe_ms],
                    "completed_bar_count": 0,
                    "state": "HOLD_SOURCE_STREAM_MISSING",
                    "blockers": ["SOURCE_STREAM_MISSING"],
                }
            )
            completed[key] = []
            continue
        audited, closed = audit_stream(
            raw_streams[key], symbol=symbol, timeframe_ms=timeframe_ms, now_ms=now_ms
        )
        stream_rows.append(audited)
        completed[key] = closed

    stream_index = {(row["symbol"], row["timeframe_ms"]): row for row in stream_rows}
    candidate_rows: list[dict[str, Any]] = []
    for parent_id, warmup in sorted(CANDIDATE_WARMUPS.items()):
        timeframe_ms = int(specs[parent_id]["timeframe_ms"])
        symbol_rows: list[dict[str, Any]] = []
        for symbol in SYMBOLS:
            stream = stream_index[(symbol, timeframe_ms)]
            count = int(stream.get("completed_bar_count", 0))
            source_ready = stream["state"] == "PASS_SOURCE_STREAM_INTEGRITY" and count >= warmup
            blockers = list(stream["blockers"])
            if count < warmup:
                blockers.append("FROZEN_WARMUP_INSUFFICIENT")
            symbol_rows.append(
                {
                    "symbol": symbol,
                    "completed_bar_count": count,
                    "frozen_warmup_required": warmup,
                    "source_ready": source_ready,
                    "blockers": blockers,
                }
            )
        candidate_rows.append(
            {
                "parent_id": parent_id,
                "child_id": str(specs[parent_id]["child_id"]),
                "timeframe_ms": timeframe_ms,
                "required_data": list(specs[parent_id]["required_data"]),
                "frozen_warmup_required": warmup,
                "symbol_rows": symbol_rows,
                "source_ready": all(row["source_ready"] for row in symbol_rows),
                "fresh_boundary_assigned": False,
                "replay_state": "NOT_RUN",
                "effect_verified": False,
            }
        )

    ready_count = sum(row["source_ready"] for row in candidate_rows)
    state = (
        "PASS_EXACT8_SIX_SOURCE_REALITY_AUDIT_NO_BOUNDARY"
        if ready_count == len(CANDIDATE_WARMUPS)
        else "HOLD_EXACT8_SOURCE_REALITY_AUDIT"
    )
    receipt = {
        "schema_version": "zel.a1_external_research_exact8_source_audit.v1",
        "state": state,
        "captured_at_utc": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat(),
        "source_endpoint": ENDPOINT,
        "source_authentication": "PUBLIC_MARKET_DATA_NO_CREDENTIALS",
        "symbols": list(SYMBOLS),
        "stream_count": len(stream_rows),
        "stream_rows": stream_rows,
        "candidate_count": len(candidate_rows),
        "source_ready_candidate_count": ready_count,
        "candidate_rows": candidate_rows,
        "source_reality_evidence_used": True,
        "fresh_boundary_assigned": False,
        "boundary_assignment_authority": False,
        "replay_performed": False,
        "effect_verified_count": 0,
        "threshold_search": False,
        "holdout_outcomes_accessed": False,
        "synthetic_market_evidence_used": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
        "next": "AFTER_MERGE_ASSIGN_ONE_FRESH_BOUNDARY_PER_READY_CHILD;DO_NOT_INFER_EFFECT",
    }
    receipt["receipt_sha256"] = digest(receipt)
    return receipt


def fetch_live_streams(
    spec: dict[str, Any], *, fetcher: Callable[..., list[Any]] = fetch_klines
) -> dict[tuple[str, int], list[Any]]:
    timeframes = sorted({int(spec["specs"][parent_id]["timeframe_ms"]) for parent_id in CANDIDATE_WARMUPS})
    streams: dict[tuple[str, int], list[Any]] = {}
    for symbol in SYMBOLS:
        for timeframe_ms in timeframes:
            streams[(symbol, timeframe_ms)] = fetcher(symbol, timeframe_ms, limit=1000)
    return streams


def deterministic_streams(now_ms: int) -> dict[tuple[str, int], list[dict[str, Any]]]:
    streams: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for symbol in SYMBOLS:
        offset = 1000.0 if symbol.startswith("BTC") else 100.0
        for timeframe_ms in INTERVAL_BY_MS:
            start = now_ms - 130 * timeframe_ms
            rows: list[dict[str, Any]] = []
            for index in range(130):
                opened = offset + index * 0.1
                close = opened + 0.05
                rows.append(
                    {
                        "time": start + index * timeframe_ms,
                        "open": opened,
                        "high": close + 0.05,
                        "low": opened - 0.05,
                        "close": close,
                        "volume": 10.0 + index,
                    }
                )
            streams[(symbol, timeframe_ms)] = rows
    return streams


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--live", action="store_true")
    args = parser.parse_args()

    spec = read(args.spec)
    now_ms = int(time.time() * 1000)
    streams = deterministic_streams(now_ms) if args.self_test else fetch_live_streams(spec)
    receipt = build_receipt(spec, streams, now_ms=now_ms)
    if args.self_test:
        assert receipt["source_ready_candidate_count"] == 6, receipt
        assert receipt["fresh_boundary_assigned"] is False, receipt
        assert receipt["effect_verified_count"] == 0, receipt
        assert receipt["order_authority"] == "BLOCKED", receipt
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
