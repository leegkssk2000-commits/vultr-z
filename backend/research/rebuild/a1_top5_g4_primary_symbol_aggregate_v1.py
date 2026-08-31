#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as core

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_extended_historical_fasttrack_v1.json"
SCHEMA = "zel.a1.top5.g4.extended_historical_lane_shard.receipt.v1"
SYMBOL_SCHEMA = "zel.a1.top5.g4.primary_symbol_shard.receipt.v1"
LANE_ID = "trend_rider_primary_wr8125"
SYMBOLS = ("BTC-USDT", "ETH-USDT")


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def load_shards(path: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for p in path.rglob("*.json"):
        try:
            row = read(p)
        except Exception:
            continue
        if row.get("schema_version") != SYMBOL_SCHEMA or row.get("state") != "PASS_PRIMARY_SYMBOL_SHARD_COMPLETE":
            continue
        symbol = str(row.get("symbol") or "")
        if symbol in SYMBOLS:
            if symbol in found:
                raise RuntimeError(f"DUPLICATE_PRIMARY_SYMBOL_SHARD:{symbol}")
            found[symbol] = row
    missing = [x for x in SYMBOLS if x not in found]
    if missing:
        raise RuntimeError("MISSING_PRIMARY_SYMBOL_SHARDS:" + ",".join(missing))
    return found


def run(shard_dir: Path, out: Path) -> dict[str, Any]:
    contract = read(CONTRACT)
    shards = load_shards(shard_dir)
    authorities = [shards[s]["fresh_authority_hashes_before"] for s in SYMBOLS]
    if authorities[0] != authorities[1]:
        raise RuntimeError("PRIMARY_SYMBOL_AUTHORITY_HASH_DRIFT")
    if any(shards[s]["fresh_authority_hashes_before"] != shards[s]["fresh_authority_hashes_after"] for s in SYMBOLS):
        raise RuntimeError("PRIMARY_SYMBOL_FRESH_AUTHORITY_MUTATION")

    windows = contract["historical_windows"]
    starts = [core.utc_ms(x["start_utc"]) for x in windows]
    ends = [core.utc_ms(x["end_utc"]) for x in windows]
    global_start, global_end = min(starts), max(ends)
    calendar_days = (global_end - global_start) / 86_400_000.0
    trades = [dict(x) for s in SYMBOLS for x in shards[s]["trades"]]
    trades.sort(key=lambda x: (int(x["exit_ts"]), int(x["signal_ts"]), str(x["symbol"]), str(x["trade_id"])))
    ids = [x["trade_id"] for x in trades]
    if len(ids) != len(set(ids)):
        raise RuntimeError("PRIMARY_AGGREGATE_DUPLICATE_TRADE")

    per_window = []
    for raw, start_ms, end_ms in zip(windows, starts, ends):
        rows = core.window_rows(trades, start_ms, end_ms)
        days = (end_ms - start_ms) / 86_400_000.0
        per_window.append({
            "window_id": raw["window_id"],
            "start_utc": raw["start_utc"],
            "end_utc": raw["end_utc"],
            **core.metrics(rows, days),
            "trade_ids": [x["trade_id"] for x in rows],
        })
    aggregate = core.metrics(trades, calendar_days)
    legacy_state = core.classify(contract, per_window, aggregate)
    source = {}
    for symbol in SYMBOLS:
        source.update(shards[s]["source_summary"])

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_LANE_SHARD_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lane_id": LANE_ID,
        "strategy_id": "trend_rider",
        "architecture": "CURRENT_PRIMARY_WR80_US_CHASE_COOLING_POLICY",
        "legacy_six_window_state": legacy_state,
        "aggregate": aggregate,
        "windows": per_window,
        "source_summary": source,
        "trade_identity_sha256": core.stable(ids),
        "trades": trades,
        "symbol_shard_receipts": {s: shards[s]["receipt_sha256"] for s in SYMBOLS},
        "historical_credit_to_fresh_g4_T": 0,
        "historical_credit_to_g5_T": 0,
        "fresh_authority_hashes_before": authorities[0],
        "fresh_authority_hashes_after": authorities[0],
        "fresh_authority_unchanged": True,
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    result["deterministic_result_sha256"] = core.stable({k: v for k, v in result.items() if k not in {"observed_at_utc", "receipt_sha256", "deterministic_result_sha256"}})
    result["receipt_sha256"] = core.stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "aggregate": aggregate, "legacy_state": legacy_state, "receipt": result["receipt_sha256"]}, sort_keys=True))
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--shard-dir", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.shard_dir), Path(a.out))


if __name__ == "__main__":
    main()
