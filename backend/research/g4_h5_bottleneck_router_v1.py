#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
LEAGUE = ROOT / "backend/research/rebuild/a1_strategy25_improvement_league_latest.json"
A4_EXACT = ROOT / "backend/research/rebuild/a1_a4_exact_parent_repair_latest.json"
TR_EXACT = ROOT / "backend/research/rebuild/a1_trend_rider_exact_parent_repair_latest.json"
DISTINCT = ROOT / "backend/research/rebuild/a1_a4_distinct_child_repair_latest.json"
HARD = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
DEFAULT_OUT = ROOT / "backend/research/g4_h5_bottleneck_route_latest.json"
SCHEMA = "zel.g4.h5_bottleneck_route.v1"


def read(path: Path, *, optional: bool = False) -> dict[str, Any]:
    if optional and not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def candidate_score(row: Mapping[str, Any]) -> tuple[Any, ...]:
    c = row.get("concentration") if isinstance(row.get("concentration"), Mapping) else {}
    m = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
    return (
        int(c.get("blocker_count") or 99),
        -float(m.get("net_expectancy_bps") or -1e18),
        -float(m.get("profit_factor") or 0.0),
        float(m.get("drawdown_bps") or 1e18),
        -float(row.get("trade_retention_pct") or 0.0),
        str(row.get("candidate_id") or ""),
    )


def best_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    viable = [x for x in rows if bool(x.get("economic_gate_pass"))]
    if not viable:
        return None
    viable.sort(key=candidate_score)
    return viable[0]


def route_for(
    sid: str,
    formal: Mapping[str, Any],
    exact_block: Mapping[str, Any],
    distinct_block: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    parent_c = exact_block.get("parent_concentration") if isinstance(exact_block.get("parent_concentration"), Mapping) else {}
    parent_blockers = [str(x) for x in (parent_c.get("blockers") or [])]
    exact_rows = [dict(x) for x in (exact_block.get("candidates") or []) if isinstance(x, Mapping)]
    distinct_rows = [dict(x) for x in (distinct_block.get("candidates") or []) if isinstance(x, Mapping)]
    distinct_attempted = bool(distinct_rows)
    attempted_distinct_axes = sorted({str(x.get("changed_axis") or "") for x in distinct_rows if x.get("changed_axis")})

    exact_ready = [x for x in exact_rows if bool(x.get("development_candidate_ready"))]
    distinct_ready = [x for x in distinct_rows if bool(x.get("development_candidate_ready"))]
    best = best_candidate(exact_ready or exact_rows)
    source = "EXACT_PARENT"
    if not best:
        best = best_candidate(distinct_ready or distinct_rows)
        source = "DISTINCT_CHILD"

    if best:
        c = best.get("concentration") if isinstance(best.get("concentration"), Mapping) else {}
        blockers = [str(x) for x in (c.get("blockers") or [])]
        blocker_count = int(c.get("blocker_count") or len(blockers))
        top10 = float(c.get("top10_trade_profit_share") or 0.0)
        regime = float(c.get("maximum_single_regime_profit_share") or 0.0)
        symbol = float(c.get("maximum_single_symbol_profit_share") or 0.0)
        loo = float(c.get("minimum_leave_one_group_out_net_R") or 0.0)
        metrics = best.get("metrics") if isinstance(best.get("metrics"), Mapping) else {}
        structural = (
            "SINGLE_REGIME_CONCENTRATION" in blockers
            or "SINGLE_SYMBOL_CONCENTRATION" in blockers
            or "LEAVE_ONE_GROUP_OUT_NON_POSITIVE" in blockers
        )
        if blocker_count == 0:
            route = "FRESH_OOS_NOW"
            reason = "H5_CLEAR"
        elif set(blockers) == {"TOP10_TRADE_CONCENTRATION"}:
            route = "FRESH_SAMPLE_EXPANSION_TOP10_DILUTION"
            reason = "ONLY_TOP10_CONCENTRATION_REMAINS"
        elif structural and distinct_attempted:
            route = "FAILOVER_TO_NEXT5_OR_NEW_MECHANISM_NOW"
            reason = "STRUCTURAL_H5_REMAINS_AFTER_DISTINCT_CHILD_ATTEMPT"
        elif structural:
            route = "RUN_ONE_DISTINCT_MECHANISM_THEN_FAILOVER"
            reason = "STRUCTURAL_H5_REQUIRES_NONREDUNDANT_MECHANISM"
        else:
            route = "FAILOVER_TO_NEXT5_OR_NEW_MECHANISM_NOW" if distinct_attempted else "RUN_ONE_DISTINCT_MECHANISM_THEN_FAILOVER"
            reason = "NO_REPEAT_H5_POLICY"
        return {
            "strategy_id": sid,
            "route": route,
            "route_reason": reason,
            "candidate_id": best.get("candidate_id"),
            "candidate_source": source,
            "candidate_trades": metrics.get("trades", best.get("completed_trades")),
            "candidate_net_expectancy_bps": metrics.get("net_expectancy_bps"),
            "candidate_profit_factor": metrics.get("profit_factor"),
            "candidate_drawdown_bps": metrics.get("drawdown_bps"),
            "candidate_retention_pct": best.get("trade_retention_pct"),
            "h5_blockers": blockers,
            "h5_blocker_count": blocker_count,
            "top10_profit_share": top10,
            "top10_limit": float(thresholds["maximum_top10_trade_profit_share"]),
            "top10_excess": max(0.0, top10 - float(thresholds["maximum_top10_trade_profit_share"])),
            "single_regime_profit_share": regime,
            "single_regime_limit": float(thresholds["maximum_single_regime_profit_share"]),
            "single_symbol_profit_share": symbol,
            "single_symbol_limit": float(thresholds["maximum_single_symbol_profit_share"]),
            "minimum_leave_one_group_out_net_R": loo,
            "distinct_child_already_attempted": distinct_attempted,
            "attempted_distinct_axes": attempted_distinct_axes,
            "repeat_same_axis_forbidden": True,
            "threshold_weakening_forbidden": True,
            "fresh_oos_required_before_survivor": True,
        }

    formal_trades = int(formal.get("completed_trades") or 0)
    if distinct_attempted:
        route = "FAILOVER_TO_NEXT5_OR_NEW_MECHANISM_NOW"
        reason = "DISTINCT_CHILD_ALREADY_ATTEMPTED_WITHOUT_ECONOMIC_H5_READY_CANDIDATE"
    elif exact_block.get("unsupported_exact_identity_axes"):
        route = "RUN_ONE_DISTINCT_MECHANISM_THEN_FAILOVER"
        reason = "ONE_UNTRIED_DISTINCT_AXIS_ALLOWED"
    elif formal_trades < 50:
        route = "FRESH_SAMPLE_EXPANSION_WITH_DEADLINE"
        reason = "LOW_SAMPLE_NO_READY_CHILD"
    else:
        route = "FAILOVER_TO_NEXT5_OR_NEW_MECHANISM_NOW"
        reason = "NO_READY_CHILD_AND_SAMPLE_NOT_SPARSE"
    return {
        "strategy_id": sid,
        "route": route,
        "route_reason": reason,
        "candidate_id": None,
        "candidate_source": None,
        "formal_trades": formal_trades,
        "parent_h5_blockers": parent_blockers,
        "distinct_child_already_attempted": distinct_attempted,
        "attempted_distinct_axes": attempted_distinct_axes,
        "repeat_same_axis_forbidden": True,
        "threshold_weakening_forbidden": True,
        "fresh_oos_required_before_survivor": True,
    }


def run(out: Path) -> dict[str, Any]:
    league = read(LEAGUE)
    exact = read(A4_EXACT)
    tr = read(TR_EXACT, optional=True)
    distinct = read(DISTINCT, optional=True)
    hard = read(HARD)
    thresholds = hard["h5_concentration_fragility"]
    top5 = [str(x) for x in league.get("active_top5") or []]
    if len(top5) != 5 or len(set(top5)) != 5:
        raise RuntimeError(f"ACTIVE_TOP5_INVALID:{top5}")
    headline = {str(x.get("strategy_id")): x for x in (league.get("headline_top5") or []) if isinstance(x, Mapping)}
    exact_map = exact.get("strategies") if isinstance(exact.get("strategies"), Mapping) else {}
    distinct_map = distinct.get("strategies") if isinstance(distinct.get("strategies"), Mapping) else {}
    routes: list[dict[str, Any]] = []
    for sid in top5:
        formal = headline.get(sid, {}).get("formal_metrics") if isinstance(headline.get(sid, {}), Mapping) else {}
        if not isinstance(formal, Mapping):
            formal = {}
        if sid == "trend_rider":
            exact_block = tr
        else:
            exact_block = exact_map.get(sid, {}) if isinstance(exact_map.get(sid, {}), Mapping) else {}
        distinct_block = distinct_map.get(sid, {}) if isinstance(distinct_map.get(sid, {}), Mapping) else {}
        routes.append(route_for(sid, formal, exact_block, distinct_block, thresholds))

    route_counts: dict[str, int] = {}
    for row in routes:
        route_counts[row["route"]] = route_counts.get(row["route"], 0) + 1
    result = {
        "schema_version": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_G4_H5_ANTI_STALL_ROUTE_BOUND",
        "active_top5": top5,
        "routes": routes,
        "route_counts": route_counts,
        "same_axis_repeat_allowed": False,
        "h5_threshold_weakening_allowed": False,
        "post_outcome_trade_deletion_allowed": False,
        "g4_progress_rule": "EVERY_TOP5_MEMBER_MUST_ROUTE_TO_FRESH_OOS,FRESH_SAMPLE,ONE_UNTRIED_DISTINCT_MECHANISM,OR_IMMEDIATE_FAILOVER; NO_INDEFINITE_HOLD_AND_NO_REPEAT_DISTINCT_CHILD",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": "EXECUTE_ONLY_NONREPEATED_ROUTES; FAILOVER_STRUCTURAL_H5_AFTER_DISTINCT_ATTEMPT",
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    thresholds = {"maximum_top10_trade_profit_share": 0.8, "maximum_single_regime_profit_share": 0.7, "maximum_single_symbol_profit_share": 0.7}
    formal = {"completed_trades": 58}
    exact = {"candidates": [{"candidate_id":"x","economic_gate_pass":True,"development_candidate_ready":True,"trade_retention_pct":90.0,"metrics":{"trades":58,"net_expectancy_bps":100.0,"profit_factor":2.0,"drawdown_bps":100.0},"concentration":{"blocker_count":1,"blockers":["TOP10_TRADE_CONCENTRATION"],"top10_trade_profit_share":0.86,"maximum_single_regime_profit_share":0.6,"maximum_single_symbol_profit_share":0.3,"minimum_leave_one_group_out_net_R":1.0}}]}
    r = route_for("x", formal, exact, {}, thresholds)
    assert r["route"] == "FRESH_SAMPLE_EXPANSION_TOP10_DILUTION"
    structural = {"candidates": [{"candidate_id":"y","economic_gate_pass":True,"development_candidate_ready":False,"trade_retention_pct":90.0,"metrics":{"trades":58,"net_expectancy_bps":100.0,"profit_factor":2.0,"drawdown_bps":100.0},"concentration":{"blocker_count":2,"blockers":["SINGLE_REGIME_CONCENTRATION","LEAVE_ONE_GROUP_OUT_NON_POSITIVE"],"top10_trade_profit_share":0.7,"maximum_single_regime_profit_share":0.95,"maximum_single_symbol_profit_share":0.3,"minimum_leave_one_group_out_net_R":-1.0}}]}
    distinct = {"candidates": [{"candidate_id":"old","changed_axis":"EXIT_TRAILING_ONLY","economic_gate_pass":False,"development_candidate_ready":False}]}
    r2 = route_for("y", formal, structural, distinct, thresholds)
    assert r2["route"] == "FAILOVER_TO_NEXT5_OR_NEW_MECHANISM_NOW"
    assert r2["distinct_child_already_attempted"] is True
    assert r["repeat_same_axis_forbidden"] is True
    print("PASS_G4_H5_BOTTLENECK_ROUTER_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out.resolve())
    print(json.dumps({"state":r["state"],"routes":r["route_counts"],"receipt":r["receipt_sha256"]},sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
