#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as core

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_extended_historical_fasttrack_v1.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
V2_FRESH = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
BREAK_FRESH = ROOT / "backend/research/rebuild/a1_break_reclaim_breakout_g4_fresh_latest.json"
SCHEMA = "zel.a1.top5.g4.extended_historical_lane_shard.receipt.v1"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def run(lane_id: str, out: Path) -> dict[str, Any]:
    contract = read(CONTRACT)
    top5, freeze, v2fresh, break_fresh = read(TOP5), read(V2_FREEZE), read(V2_FRESH), read(BREAK_FRESH)
    core.CONTRACT = CONTRACT
    core.assert_contract(contract, top5, freeze, break_fresh)
    allowed = list(contract["scope"]["include_lane_ids"])
    if lane_id not in allowed:
        raise RuntimeError(f"LANE_NOT_ALLOWED:{lane_id}")

    protected = (TOP5, V2_FRESH, BREAK_FRESH)
    before_hashes = {str(p.relative_to(ROOT)): core.file_sha(p) for p in protected}
    windows = contract["historical_windows"]
    starts = [core.utc_ms(x["start_utc"]) for x in windows]
    ends = [core.utc_ms(x["end_utc"]) for x in windows]
    global_start, global_end = min(starts), max(ends)
    calendar_days = (global_end - global_start) / 86_400_000.0
    lane_contract = contract["lanes"][lane_id]
    freeze_children = {str(x["lane_id"]): x for x in freeze["children"]}

    if lane_id == "trend_rider_primary_wr8125":
        trades, source = core.primary_trades(global_start, global_end, lane_contract["symbols"])
        architecture = "CURRENT_PRIMARY_WR80_US_CHASE_COOLING_POLICY"
        strategy_id = str(lane_contract["strategy_id"])
    else:
        child = freeze_children.get(lane_id)
        if not isinstance(child, Mapping):
            raise RuntimeError(f"V2_CHILD_LANE_MISSING:{lane_id}")
        if child.get("child_id") != lane_contract["child_id"]:
            raise RuntimeError(f"V2_CHILD_ID_DRIFT:{lane_id}")
        trades, source = core.v2_trades(child, global_start, global_end, freeze["frozen_symbol_universe"])
        architecture = str(child["architecture_family"])
        strategy_id = str(child["parent_strategy_id"])

    per_window: list[dict[str, Any]] = []
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

    after_hashes = {str(p.relative_to(ROOT)): core.file_sha(p) for p in protected}
    if before_hashes != after_hashes:
        raise RuntimeError("FRESH_AUTHORITY_MUTATED_BY_LANE_SHARD")

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_LANE_SHARD_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lane_id": lane_id,
        "strategy_id": strategy_id,
        "architecture": architecture,
        "legacy_six_window_state": legacy_state,
        "aggregate": aggregate,
        "windows": per_window,
        "source_summary": source,
        "trade_identity_sha256": core.stable([x["trade_id"] for x in trades]),
        "trades": trades,
        "historical_credit_to_fresh_g4_T": 0,
        "historical_credit_to_g5_T": 0,
        "fresh_authority_hashes_before": before_hashes,
        "fresh_authority_hashes_after": after_hashes,
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
    print(json.dumps({"lane_id": lane_id, "state": result["state"], "aggregate": aggregate, "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lane-id", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(a.lane_id, Path(a.out))


if __name__ == "__main__":
    main()
