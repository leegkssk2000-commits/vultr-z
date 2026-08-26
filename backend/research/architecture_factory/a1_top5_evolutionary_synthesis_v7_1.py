#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7 as v7
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil
from backend.research.prep import strategy_material_grade_v1 as material

SCHEMA = "zel.a1_top5_evolutionary_synthesis.v7_1"


def _extract_attempted(prior: Mapping[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}

    def add(sid: Any, rows: Any) -> None:
        if not sid or not isinstance(rows, list):
            return
        bucket = out.setdefault(str(sid), set())
        bucket.update(str(x) for x in rows if str(x))

    root = prior.get("economic_attempted_axes")
    if isinstance(root, Mapping):
        for sid, rows in root.items():
            add(sid, rows)

    by_strategy = prior.get("by_strategy")
    if isinstance(by_strategy, Mapping):
        for sid, raw in by_strategy.items():
            if not isinstance(raw, Mapping):
                continue
            add(sid, raw.get("economic_attempted_axes"))
            add(sid, raw.get("economically_tested_axes_this_run"))

    for raw in prior.get("candidate_donor_attribution") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = raw.get("host_strategy_id")
        axis = raw.get("changed_axis")
        if sid and axis:
            out.setdefault(str(sid), set()).add(str(axis))
    return out


def _prior_attempted_fixed() -> dict[str, set[str]]:
    prior = v7._read(v7.LATEST)
    return _extract_attempted(prior)


def _build_nursery_queue(material_result: Mapping[str, Any], active_hosts: set[str]) -> list[dict[str, Any]]:
    grade_rank = {"B": 0, "C": 1, "D": 2, "A": 3, "S": 4, "HOLD": 5}
    allowed_dispositions = {"SYNTHESIS_UPGRADE", "SYNTHESIS_EXPERIMENTAL", "DISCARD_PENDING_ABLATION"}
    rows: list[dict[str, Any]] = []
    for raw in material_result.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        if not sid or sid in active_hosts:
            continue
        disposition = str(raw.get("material_disposition") or "")
        if disposition not in allowed_dispositions:
            continue
        quality = raw.get("quality") if isinstance(raw.get("quality"), Mapping) else {}
        rows.append({
            "strategy_id": sid,
            "material_grade": raw.get("material_grade"),
            "material_disposition": disposition,
            "upgrade_axis": raw.get("upgrade_axis"),
            "target_grade": raw.get("target_grade"),
            "structural_diversity_prior": raw.get("structural_diversity_prior"),
            "completed_trades": quality.get("completed_trades"),
            "positive_gross": quality.get("positive_gross"),
            "positive_net": quality.get("positive_net"),
            "net_expectancy_bps": quality.get("net_expectancy_bps"),
            "risk_efficiency_net_pnl_over_dd": quality.get("risk_efficiency_net_pnl_over_dd"),
            "nursery_rule": "UPGRADE_MATERIAL_FIRST_THEN_REENTER_AS_DONOR;NO_NUMERIC_THRESHOLD_COPY",
        })

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        grade = str(row.get("material_grade") or "HOLD")
        positive_gross = bool(row.get("positive_gross"))
        diversity = float(row.get("structural_diversity_prior") or 0.0)
        trades = int(row.get("completed_trades") or 0)
        return (grade_rank.get(grade, 9), 0 if positive_gross else 1, -diversity, -trades, str(row.get("strategy_id")))

    rows.sort(key=key)
    return rows[:10]


def _host_exhaustion_routes(result: Mapping[str, Any]) -> dict[str, str]:
    routes: dict[str, str] = {}
    by_strategy = result.get("by_strategy")
    if not isinstance(by_strategy, Mapping):
        return routes
    for sid, raw in by_strategy.items():
        if not isinstance(raw, Mapping):
            continue
        passes = int(raw.get("development_economic_pass_count") or 0)
        remaining = int(raw.get("remaining_axis_count") or 0)
        if passes > 0:
            routes[str(sid)] = "INDEPENDENT_OOS_WALK_FORWARD_STRESS"
        elif remaining <= 0:
            routes[str(sid)] = "DONOR_NURSERY_UPGRADE_OR_NEW_EXTERNAL_MECHANISM"
        else:
            routes[str(sid)] = "CONTINUE_UNTRIED_DISTINCT_DONOR_AXIS"
    return routes


def run(output: Path) -> dict[str, Any]:
    original = v7._prior_attempted
    try:
        v7._prior_attempted = _prior_attempted_fixed
        result = dict(v7.run(output))
    finally:
        v7._prior_attempted = original

    attempted = _extract_attempted(v7._read(v7.LATEST))
    active_hosts = {str(x) for x in (result.get("active_strategy_ids") or result.get("performance_top5_hosts") or []) if str(x)}
    material_result = material.evaluate(
        material.read(material.LEDGER),
        material.read(material.INVENTORY),
        material.read(material.SSOT),
    )
    nursery = _build_nursery_queue(material_result, active_hosts)

    result["schema_version"] = SCHEMA
    result["stable_donor_host_attempt_history"] = True
    result["prior_attempted_gene_pairs"] = {sid: sorted(rows) for sid, rows in sorted(attempted.items())}
    result["failed_gene_pair_retest_same_axis_allowed"] = False
    result["synthesis_mode"] = "TOP5_HOST_EVOLUTION_PLUS_DONOR_NURSERY"
    result["donor_nursery_enabled"] = True
    result["donor_nursery_strategy_count"] = len(nursery)
    result["donor_nursery_queue"] = nursery
    result["host_exhaustion_routes"] = _host_exhaustion_routes(result)
    result["nursery_policy"] = {
        "abandon_synthesis": False,
        "blind_recombination_after_axis_exhaustion": False,
        "grow_demoted_material_before_reuse": True,
        "proven_positive_marginal_donor_can_reenter_immediately": True,
        "final_discard_requires_marginal_nonpositive_dd_nonimproving_and_redundant": True,
        "numeric_threshold_copy_allowed": False,
        "whole_strategy_merge_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    sample = {
        "by_strategy": {
            "trend_rider": {
                "economic_attempted_axes": ["DONOR__A__X__ONLY"],
                "economically_tested_axes_this_run": ["DONOR__B__Y__ONLY"],
            }
        },
        "candidate_donor_attribution": [
            {"host_strategy_id": "break_and_continue", "changed_axis": "DONOR__C__Z__ONLY"}
        ],
    }
    got = _extract_attempted(sample)
    assert got["trend_rider"] == {"DONOR__A__X__ONLY", "DONOR__B__Y__ONLY"}, got
    assert got["break_and_continue"] == {"DONOR__C__Z__ONLY"}, got

    nursery = _build_nursery_queue({"rows": [
        {"strategy_id": "weak_b", "material_grade": "B", "material_disposition": "SYNTHESIS_UPGRADE", "upgrade_axis": "COST", "target_grade": "A", "structural_diversity_prior": 0.5, "quality": {"completed_trades": 8, "positive_gross": True, "positive_net": False}},
        {"strategy_id": "weak_d", "material_grade": "D", "material_disposition": "DISCARD_PENDING_ABLATION", "upgrade_axis": "RECOMBINE", "target_grade": "B", "structural_diversity_prior": 1.0, "quality": {"completed_trades": 20, "positive_gross": False, "positive_net": False}},
        {"strategy_id": "active", "material_grade": "B", "material_disposition": "SYNTHESIS_UPGRADE", "upgrade_axis": "COST", "target_grade": "A", "structural_diversity_prior": 1.0, "quality": {"completed_trades": 9, "positive_gross": True, "positive_net": False}},
    ]}, {"active"})
    assert [x["strategy_id"] for x in nursery] == ["weak_b", "weak_d"], nursery

    routes = _host_exhaustion_routes({"by_strategy": {
        "passer": {"development_economic_pass_count": 1, "remaining_axis_count": 0},
        "spent": {"development_economic_pass_count": 0, "remaining_axis_count": 0},
        "open": {"development_economic_pass_count": 0, "remaining_axis_count": 2},
    }})
    assert routes["passer"] == "INDEPENDENT_OOS_WALK_FORWARD_STRESS"
    assert routes["spent"] == "DONOR_NURSERY_UPGRADE_OR_NEW_EXTERNAL_MECHANISM"
    assert routes["open"] == "CONTINUE_UNTRIED_DISTINCT_DONOR_AXIS"
    assert v7.v3.AUTH["execution_authority"] == "NONE" and v7.v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_EVOLUTIONARY_SYNTHESIS_V7_1_ATTEMPT_MEMORY_SELF_TEST")
    print("PASS_FAILED_DONOR_HOST_PAIR_WILL_ADVANCE_NOT_REPEAT")
    print("PASS_DONOR_NURSERY_ROUTE_AFTER_AXIS_EXHAUSTION")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_top5_evolutionary_synthesis_v7_1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r.get("state"),
        "hosts": r.get("performance_top5_hosts"),
        "donors": r.get("donor_pool_count"),
        "validated_donors": r.get("validated_edge_donor_count"),
        "candidates": r.get("evolutionary_candidate_count"),
        "development_pass": r.get("development_economic_pass_count"),
        "donor_nursery": r.get("donor_nursery_strategy_count"),
        "paid": r.get("paid_request_count"),
        "stable_attempt_history": r.get("stable_donor_host_attempt_history"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
