from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "backend/tools/r7a4d_strategy11_continuous_data_collector_v1.py"
VERSION = "ZEL_FORWARD_WINDOW_COLLECTOR_V1"
INTERVAL_MS = 900_000
TARGET_BARS_DEFAULT = 480


def load_base() -> Any:
    name = "zel_forward_window_base_v1"
    spec = importlib.util.spec_from_file_location(name, BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_COLLECTOR_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load_base()


def parse_utc_ms(value: str) -> int:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.timestamp() * 1000)


def validate_frame(frame: pd.DataFrame, first_ms: int, last_ms: int) -> None:
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise RuntimeError("COLUMNS_MISSING")
    frame.sort_values("timestamp_ms", inplace=True)
    ts = frame["timestamp_ms"].astype("int64")
    expected = (last_ms - first_ms) // INTERVAL_MS + 1
    if len(frame) != expected:
        raise RuntimeError(f"ROW_COUNT_MISMATCH:{len(frame)}!={expected}")
    if int(ts.iloc[0]) != first_ms or int(ts.iloc[-1]) != last_ms:
        raise RuntimeError("BOUNDARY_MISMATCH")
    if ts.duplicated().any():
        raise RuntimeError("DUPLICATE_TIMESTAMP")
    if len(ts) > 1 and not bool((ts.diff().dropna() == INTERVAL_MS).all()):
        raise RuntimeError("TIMESTAMP_GAP")
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if not all(math.isfinite(float(value)) for value in numeric.to_numpy().ravel()):
        raise RuntimeError("OHLCV_NONFINITE")
    if bool((numeric[["open", "high", "low", "close"]] <= 0).any().any()):
        raise RuntimeError("PRICE_NONPOSITIVE")
    if bool((numeric["volume"] < 0).any()):
        raise RuntimeError("VOLUME_NEGATIVE")
    if bool((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()):
        raise RuntimeError("HIGH_INVARIANT")
    if bool((numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()):
        raise RuntimeError("LOW_INVARIANT")


def wait_manifest(stage: str, authority_end_ms: int, target_bars: int, status_out: Path) -> int:
    first_ms = authority_end_ms + INTERVAL_MS
    target_end_ms = authority_end_ms + target_bars * INTERVAL_MS
    payload = {
        "schema_version": "zel.forward_window.v1",
        "version": VERSION,
        "stage": stage,
        "state": "PASS_WAIT_FIRST_CLOSED_BAR",
        "blockers": [],
        "authority_end_ms": authority_end_ms,
        "authority_end": base.iso(authority_end_ms),
        "first_evaluation_ms": first_ms,
        "first_evaluation": base.iso(first_ms),
        "target_end_ms": target_end_ms,
        "target_end": base.iso(target_end_ms),
        "latest_closed_end_ms": None,
        "latest_closed_end": None,
        "available_non_overlap_bars": 0,
        "target_bars": target_bars,
        "missing_to_target": target_bars,
        "window_ready": False,
        "symbols": [],
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
    }
    base.atomic_json(status_out.parent / "manifest.json", payload)
    base.atomic_json(status_out, payload)
    print(json.dumps({"stage": stage, "state": payload["state"], "available": 0, "missing": target_bars}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("W2", "W3"), required=True)
    parser.add_argument("--authority-end", required=True)
    parser.add_argument("--target-bars", type=int, default=TARGET_BARS_DEFAULT)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--status-out", required=True)
    parser.add_argument("--as-of-ms", type=int)
    args = parser.parse_args()

    stage = args.stage
    authority_end_ms = parse_utc_ms(args.authority_end)
    target_bars = int(args.target_bars)
    if target_bars <= 0:
        raise RuntimeError("TARGET_BARS_INVALID")

    first_ms = authority_end_ms + INTERVAL_MS
    target_end_ms = authority_end_ms + target_bars * INTERVAL_MS
    now_ms = args.as_of_ms or int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    latest_closed = base.aligned_closed_end(now_ms)
    effective_end = min(latest_closed, target_end_ms)

    root = Path(args.data_root).resolve()
    status_out = Path(args.status_out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if effective_end < first_ms:
        return wait_manifest(stage, authority_end_ms, target_bars, status_out)

    rows: list[dict[str, Any]] = []
    total_added = 0
    for symbol in base.SYMBOLS:
        market_path = root / "market" / f"{symbol}.csv"
        if market_path.exists():
            existing = pd.read_csv(market_path)
            existing = existing[(existing["timestamp_ms"] >= first_ms) & (existing["timestamp_ms"] <= effective_end)]
            fetch_start = int(existing["timestamp_ms"].max()) + INTERVAL_MS if len(existing) else first_ms
        else:
            existing = pd.DataFrame(columns=("timestamp_ms", "open", "high", "low", "close", "volume"))
            fetch_start = first_ms

        endpoint = None
        request_count = 0
        added = 0
        if fetch_start <= effective_end:
            new, endpoint, request_count = base.fetch_klines(symbol, fetch_start, effective_end)
            added = len(new)
            total_added += added
            combined = pd.concat([existing, new], ignore_index=True)
        else:
            combined = existing.copy()
        combined = combined.drop_duplicates("timestamp_ms", keep="last").sort_values("timestamp_ms")
        combined = combined[(combined["timestamp_ms"] >= first_ms) & (combined["timestamp_ms"] <= effective_end)]
        validate_frame(combined, first_ms, effective_end)
        market_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(market_path, index=False)

        funding_path = root / "funding" / f"{symbol}.json"
        old_funding: list[dict[str, Any]] = []
        if funding_path.exists():
            old = json.loads(funding_path.read_text(encoding="utf-8"))
            old_funding = [dict(row) for row in old.get("rows", []) if isinstance(row, dict)]
        old_funding = [row for row in old_funding if int(row["timestamp_ms"]) >= first_ms - 8 * 60 * 60 * 1000]
        funding_start = max(first_ms - 8 * 60 * 60 * 1000, max((int(row["timestamp_ms"]) for row in old_funding), default=0) + 1)
        funding_endpoint = None
        if funding_start <= effective_end:
            fresh_funding, funding_endpoint = base.fetch_funding(symbol, funding_start, effective_end)
            merged = {int(row["timestamp_ms"]): row for row in old_funding + fresh_funding}
            old_funding = [merged[key] for key in sorted(merged)]
        if not old_funding:
            raise RuntimeError(f"FUNDING_EMPTY:{symbol}")
        base.atomic_json(funding_path, {"symbol": symbol, "rows": old_funding, "source": funding_endpoint})

        rows.append({
            "symbol": symbol,
            "rows": len(combined),
            "added_rows": added,
            "first_timestamp_ms": int(combined["timestamp_ms"].iloc[0]),
            "last_timestamp_ms": int(combined["timestamp_ms"].iloc[-1]),
            "market_sha256": base.sha256(market_path),
            "funding_sha256": base.sha256(funding_path),
            "funding_events": len(old_funding),
            "kline_source": endpoint,
            "funding_source": funding_endpoint,
            "request_count": request_count,
        })

    available = int((effective_end - authority_end_ms) // INTERVAL_MS)
    ready = available >= target_bars
    manifest = {
        "schema_version": "zel.forward_window.v1",
        "version": VERSION,
        "stage": stage,
        "state": f"PASS_{stage}_WINDOW_READY" if ready else f"PASS_{stage}_COLLECTING",
        "blockers": [],
        "authority_end_ms": authority_end_ms,
        "authority_end": base.iso(authority_end_ms),
        "first_evaluation_ms": first_ms,
        "first_evaluation": base.iso(first_ms),
        "target_end_ms": target_end_ms,
        "target_end": base.iso(target_end_ms),
        "latest_closed_end_ms": effective_end,
        "latest_closed_end": base.iso(effective_end),
        "available_non_overlap_bars": available,
        "target_bars": target_bars,
        "missing_to_target": max(0, target_bars - available),
        "window_ready": ready,
        "total_added_rows_this_run": total_added,
        "symbols": rows,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
    }
    base.atomic_json(root / "manifest.json", manifest)
    base.atomic_json(status_out, manifest)
    print(json.dumps({
        "stage": stage,
        "state": manifest["state"],
        "available": available,
        "missing": manifest["missing_to_target"],
        "added": total_added,
        "ready": ready,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
