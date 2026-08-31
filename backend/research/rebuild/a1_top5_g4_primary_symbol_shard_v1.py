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
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
V2_FRESH = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
BREAK_FRESH = ROOT / "backend/research/rebuild/a1_break_reclaim_breakout_g4_fresh_latest.json"
SCHEMA = "zel.a1.top5.g4.primary_symbol_shard.receipt.v1"
LANE_ID = "trend_rider_primary_wr8125"
ALLOWED_SYMBOLS = ("BTC-USDT", "ETH-USDT")


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def run(symbol: str, out: Path) -> dict[str, Any]:
    if symbol not in ALLOWED_SYMBOLS:
        raise RuntimeError(f"SYMBOL_NOT_ALLOWED:{symbol}")
    contract = read(CONTRACT)
    if contract.get("state") != "PREREGISTERED_BEFORE_RECENT_HISTORICAL_RESULTS":
        raise RuntimeError("FASTTRACK_CONTRACT_NOT_PREREGISTERED")
    lane = contract["lanes"][LANE_ID]
    if symbol not in lane["symbols"]:
        raise RuntimeError("PRIMARY_SYMBOL_CONTRACT_DRIFT")
    windows = contract["historical_windows"]
    starts = [core.utc_ms(x["start_utc"]) for x in windows]
    ends = [core.utc_ms(x["end_utc"]) for x in windows]
    global_start, global_end = min(starts), max(ends)
    calendar_days = (global_end - global_start) / 86_400_000.0

    protected = (TOP5, V2_FRESH, BREAK_FRESH)
    before = {str(p.relative_to(ROOT)): core.file_sha(p) for p in protected}
    trades, source = core.primary_trades(global_start, global_end, [symbol])
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
    after = {str(p.relative_to(ROOT)): core.file_sha(p) for p in protected}
    if before != after:
        raise RuntimeError("FRESH_AUTHORITY_MUTATED_BY_PRIMARY_SYMBOL_SHARD")
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_PRIMARY_SYMBOL_SHARD_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lane_id": LANE_ID,
        "strategy_id": "trend_rider",
        "symbol": symbol,
        "architecture": "CURRENT_PRIMARY_WR80_US_CHASE_COOLING_POLICY",
        "aggregate": aggregate,
        "windows": per_window,
        "source_summary": source,
        "trade_identity_sha256": core.stable([x["trade_id"] for x in trades]),
        "trades": trades,
        "historical_credit_to_fresh_g4_T": 0,
        "historical_credit_to_g5_T": 0,
        "fresh_authority_hashes_before": before,
        "fresh_authority_hashes_after": after,
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
    print(json.dumps({"symbol": symbol, "state": result["state"], "aggregate": aggregate, "receipt": result["receipt_sha256"]}, sort_keys=True))
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(a.symbol, Path(a.out))


if __name__ == "__main__":
    main()
