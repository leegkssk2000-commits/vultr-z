#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_trend_rider_original_fresh_direct_ab_runner_v1.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/a1_trend_rider_original_fresh_direct_ab_guard_v1.json")
    args = ap.parse_args()
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    defects: list[str] = []
    if c.get("baseline_identity") != "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3": defects.append("BASELINE_IDENTITY_DRIFT")
    a = c.get("canonical_parent_anchor") or {}
    if int(a.get("trades") or 0) != 22: defects.append("PARENT_TRADE_ANCHOR_DRIFT")
    if abs(float(a.get("win_rate") or 0.0) - 13.0 / 22.0) > 1e-12: defects.append("PARENT_WIN_RATE_ANCHOR_DRIFT")
    for k in ("same_parent_child_boundary_required","same_execution_snapshot_required","same_cost_authority_required","a1_a2_a3_gate_order_preserved"):
        if c.get(k) is not True: defects.append(f"REQUIRED_TRUE:{k}")
    for k in ("numeric_threshold_sweep","best_horizon_selection","post_outcome_trade_deletion","selection_authority","promotion_authority"):
        if c.get(k) is not False: defects.append(f"REQUIRED_FALSE:{k}")
    if c.get("execution_authority") != "NONE" or c.get("order_authority") != "BLOCKED" or c.get("live_trade_authority") != "BLOCKED":
        defects.append("AUTHORITY_NOT_BLOCKED")
    r={"state":"PASS_ORIGINAL_FRESH_DIRECT_AB_GUARD" if not defects else "HOLD_ORIGINAL_FRESH_DIRECT_AB_GUARD","defects":defects,"action":"hold","execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,sort_keys=True,indent=2)+"\n")
    print(json.dumps(r,sort_keys=True))
    return 0 if not defects else 1

if __name__ == "__main__":
    raise SystemExit(main())
