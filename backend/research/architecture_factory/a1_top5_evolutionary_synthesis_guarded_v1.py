#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research import production_economic_guard_v1 as guard
from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7_1 as v71
from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7_2 as base

SCHEMA = "zel.a1_top5_evolutionary_synthesis.guarded.v1"
DEV_BLOCKS = ("initial_development_economics", "second_step_development_economics")


def _candidate_hosts(receipt: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in receipt.get("candidate_donor_attribution") or []:
        if isinstance(row, Mapping) and row.get("candidate_id") and row.get("host_strategy_id"):
            out[str(row["candidate_id"])] = str(row["host_strategy_id"])
    for key in ("initial_candidates", "second_step_candidates"):
        for row in receipt.get(key) or []:
            if isinstance(row, Mapping) and row.get("candidate_id") and row.get("strategy_id"):
                out.setdefault(str(row["candidate_id"]), str(row["strategy_id"]))
    return out


def _apply_guard(result: dict[str, Any]) -> dict[str, Any]:
    league = base.v7._read(base.v7.LEAGUE)
    hosts = v71._league_index(league)
    candidate_hosts = _candidate_hosts(result)
    guarded_ids: set[str] = set()
    failed_ids: set[str] = set()

    for block_name in DEV_BLOCKS:
        block = result.get(block_name)
        if not isinstance(block, dict):
            continue
        rows = [dict(x) for x in (block.get("rows") or []) if isinstance(x, Mapping)]
        for row in rows:
            cid = str(row.get("candidate_id") or "")
            host = candidate_hosts.get(cid, str(row.get("strategy_id") or ""))
            parent_raw = hosts.get(host)
            if not cid or not host or not isinstance(parent_raw, Mapping):
                continue
            parent = v71._metric_snapshot(parent_raw, development=False)
            child = v71._metric_snapshot(row, development=True)
            verdict = guard.evaluate(parent, child)
            row["production_economic_guard"] = verdict
            guarded_ids.add(cid)
            row["pre_production_guard_state"] = row.get("state")
            row["pre_production_guard_economic_pass"] = bool(row.get("economic_pass"))
            if verdict["hard_fail"]:
                failed_ids.add(cid)
                row["economic_pass"] = False
                row["state"] = "FAIL_DEVELOPMENT_ECONOMICS"
                row["production_guard_failure"] = True
                row["incumbent_state_action"] = "PRESERVE_UNCHANGED"
                row["fresh25_state_action"] = "PRESERVE_UNCHANGED"
        block["rows"] = rows
        block["passes"] = [dict(x) for x in rows if x.get("economic_pass") is True]
        block["economic_pass_count"] = len(block["passes"])
        block["economic_fail_count"] = sum(str(x.get("state") or "") == "FAIL_DEVELOPMENT_ECONOMICS" for x in rows)

    pass_ids: set[str] = set()
    for block_name in DEV_BLOCKS:
        block = result.get(block_name)
        if isinstance(block, Mapping):
            pass_ids.update(str(x.get("candidate_id") or "") for x in (block.get("passes") or []) if isinstance(x, Mapping))

    by_strategy = result.get("by_strategy")
    if isinstance(by_strategy, dict):
        for sid, raw in by_strategy.items():
            if not isinstance(raw, dict):
                continue
            candidate_ids = {
                cid for cid, host in candidate_hosts.items()
                if host == str(sid)
            }
            passes = sorted(candidate_ids & pass_ids)
            raw["development_economic_pass_count"] = len(passes)
            raw["pass_candidate_ids"] = passes
            remaining = int(raw.get("remaining_axis_count") or 0)
            raw["next"] = (
                "INDEPENDENT_OOS_WALK_FORWARD_STRESS_AND_CONTINUE_RESEARCH"
                if passes else
                "NEXT_DISTINCT_ALLOWED_AXIS" if remaining > 0 else
                "AXIS_EXHAUSTED_NO_DEVELOPMENT_PASS"
            )

    result["development_economic_pass_count"] = len(pass_ids)
    exhausted = bool(by_strategy) and all(
        int(raw.get("remaining_axis_count") or 0) == 0
        for raw in by_strategy.values()
        if isinstance(raw, Mapping)
    )
    result["state"] = (
        "PASS_A5_V3_DEVELOPMENT_ECONOMIC_CANDIDATE_FOUND" if pass_ids else
        "HOLD_A5_V3_ALL_AXES_EXHAUSTED" if exhausted else
        "HOLD_A5_V3_CONTINUE_DISTINCT_AXIS_RESEARCH"
    )

    # Rebuild donor contribution from the guarded development rows so a donor
    # that killed sample density cannot retain a stale positive contribution.
    material_result = v71.material.evaluate(
        v71.material.read(v71.material.LEDGER),
        v71.material.read(v71.material.INVENTORY),
        v71.material.read(v71.material.SSOT),
    )
    current_rows = v71._build_contribution_rows(
        result,
        league,
        material_result,
        source_receipt="CURRENT_RUN_PRODUCTION_GUARDED",
    )
    existing = [dict(x) for x in (result.get("donor_contribution_ledger") or []) if isinstance(x, Mapping)]
    result["donor_contribution_ledger"] = v71._merge_contribution_ledger(existing, current_rows)
    result["donor_contribution_summary"] = v71._aggregate_donor_contribution(result["donor_contribution_ledger"])
    result["host_exhaustion_routes"] = v71._host_exhaustion_routes(result)
    active = set(result.get("active_synthesis_hosts") or [])
    routes = dict(result.get("host_exhaustion_routes") or {})
    for sid in result.get("performance_top5_hosts") or []:
        if sid not in active and sid not in routes:
            routes[str(sid)] = "DONOR_NURSERY_UPGRADE_OR_NEW_EXTERNAL_MECHANISM"
    result["host_exhaustion_routes"] = routes

    result["production_economic_guard_enabled"] = True
    result["production_economic_guard_schema"] = guard.SCHEMA
    result["production_economic_guarded_candidate_count"] = len(guarded_ids)
    result["production_economic_guard_fail_count"] = len(failed_ids)
    result["production_economic_guard_failed_candidate_ids"] = sorted(failed_ids)
    result["production_economic_guard_rules"] = [
        "ZERO_TRADE_CHILD_HARD_FAIL",
        "TRADE_COUNT_DECREASE_HARD_FAIL",
        "ZERO_TRADE_DD_IMPROVEMENT_INVALID",
        "PNL_AND_EXPECTANCY_BOTH_WORSE_HARD_FAIL",
        "DONOR_ADMISSION_DENSITY_COLLAPSE_BLOCKED",
        "REJECT_PRESERVES_INCUMBENT_AND_FRESH25_STATE",
    ]
    result["incumbent_collectors_continue_on_candidate_reject"] = True
    result["fresh25_reset_on_candidate_reject"] = False
    return result


def run(output: Path) -> dict[str, Any]:
    result = _apply_guard(dict(base.run(output)))
    result["schema_version"] = SCHEMA
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = base.hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    # The shared guard is the invariant. The synthesis adapter additionally
    # guarantees that a stale economic_pass cannot survive a hard fail.
    parent = {"trades": 9, "net_pnl_bps": 900.0, "net_expectancy_bps": 100.0, "drawdown_bps": 300.0}
    child = {"trades": 0, "net_pnl_bps": 0.0, "net_expectancy_bps": None, "drawdown_bps": 0.0}
    verdict = guard.evaluate(parent, child)
    assert verdict["hard_fail"] and verdict["donor_admission_density_collapse"]
    assert verdict["zero_trade_dd_improvement_invalid"]
    assert verdict["incumbent_state_action"] == "PRESERVE_UNCHANGED"
    print("PASS_A1_TOP5_SYNTHESIS_PRODUCTION_GUARD_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_top5_evolutionary_synthesis_guarded_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({
        "state": result.get("state"),
        "development_pass": result.get("development_economic_pass_count"),
        "guarded": result.get("production_economic_guarded_candidate_count"),
        "guard_fail": result.get("production_economic_guard_fail_count"),
        "failed_ids": result.get("production_economic_guard_failed_candidate_ids"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
