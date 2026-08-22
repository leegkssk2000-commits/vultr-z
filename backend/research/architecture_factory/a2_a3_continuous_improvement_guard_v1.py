#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a2_a3_continuous_improvement_loop_v1.json"


def load() -> dict[str, Any]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def validate(c: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    gp = c.get("global_policy") or {}
    required_true = [
        "a2_a3_are_not_leave_unchanged_stages",
        "improvement_search_runs_in_parallel_with_validation",
        "canonical_parent_required",
        "same_baseline_direct_ab_required_for_numeric_claim",
        "transport_or_parser_failure_is_not_strategy_failure",
        "no_threshold_rescue",
        "no_post_outcome_trade_deletion",
        "no_best_horizon_cherry_pick",
        "no_repeating_terminal_tuple",
        "one_causal_axis_per_child",
        "entry_or_exit_identity_change_routes_back_through_A1",
        "regime_or_sizing_change_routes_back_through_A1_then_A2_before_A3",
        "fresh_forward_validation_required"
    ]
    for k in required_true:
        if gp.get(k) is not True:
            defects.append(f"POLICY_NOT_TRUE:{k}")

    a2 = c.get("A2_improvement_axes") or []
    a3 = c.get("A3_improvement_axes") or []
    if len(a2) < 5:
        defects.append(f"A2_AXIS_DEPTH_TOO_LOW:{len(a2)}")
    if len(a3) < 5:
        defects.append(f"A3_AXIS_DEPTH_TOO_LOW:{len(a3)}")
    for stage, rows in (("A2", a2), ("A3", a3)):
        seen: set[str] = set()
        for row in rows:
            axis = row.get("axis")
            if not axis:
                defects.append(f"{stage}:AXIS_MISSING")
                continue
            if axis in seen:
                defects.append(f"{stage}:DUPLICATE_AXIS:{axis}")
            seen.add(axis)
            if not row.get("mechanism"):
                defects.append(f"{stage}:MECHANISM_MISSING:{axis}")
            if not row.get("target"):
                defects.append(f"{stage}:TARGET_MISSING:{axis}")
            if not row.get("route"):
                defects.append(f"{stage}:ROUTE_MISSING:{axis}")

    ev = c.get("research_evidence") or []
    families = {str(x.get("id")) for x in ev if x.get("id")}
    if len(ev) < 10 or len(families) < 10:
        defects.append(f"RESEARCH_EVIDENCE_DEPTH_TOO_LOW:{len(families)}")

    tr = c.get("current_trend_rider_snapshot_reference") or {}
    if tr.get("A2_state") != "PASS_A2_COST_TURNOVER":
        defects.append("TREND_RIDER_A2_REFERENCE_MISMATCH")
    if tr.get("A3_state") != "HOLD_A3_ENTRY_CONTEXT_INCOMPLETE":
        defects.append("TREND_RIDER_A3_REFERENCE_MISMATCH")
    if not tr.get("priority_repair_order"):
        defects.append("TREND_RIDER_REPAIR_ORDER_EMPTY")

    auth = c.get("authority") or {}
    if auth.get("execution_authority") != "NONE" or auth.get("order_authority") != "BLOCKED" or auth.get("live_trade_authority") != "BLOCKED":
        defects.append("AUTHORITY_NOT_BLOCKED")
    return defects


def build_summary(c: dict[str, Any]) -> dict[str, Any]:
    tr = c["current_trend_rider_snapshot_reference"]
    return {
        "state": "PASS_A2_A3_CONTINUOUS_IMPROVEMENT_POLICY" if not validate(c) else "HOLD_A2_A3_POLICY_DEFECT",
        "A2_axis_count": len(c["A2_improvement_axes"]),
        "A3_axis_count": len(c["A3_improvement_axes"]),
        "research_evidence_count": len(c["research_evidence"]),
        "trend_rider_priority_repair_order": tr["priority_repair_order"],
        "mandatory_revalidation_route": "identity-changing repair -> A1 direct A/B -> A2 -> A3",
        "authority": c["authority"]
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out")
    args = p.parse_args()
    c = load()
    defects = validate(c)
    summary = build_summary(c)
    summary["defects"] = defects
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if not defects else 2


if __name__ == "__main__":
    raise SystemExit(main())
