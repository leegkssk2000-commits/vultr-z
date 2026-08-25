#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_a4_exact_parent_repair_batch_v1 as a4
from backend.research.rebuild import a1_finalist_sample_stall_no_idle_router_v1 as router

ROOT = Path(__file__).resolve().parents[3]
ROUTER_LATEST = ROOT / "backend/research/rebuild/a1_finalist_sample_stall_no_idle_latest.json"
BREAK_R4_LATEST = ROOT / "backend/research/rebuild/a1_break_box_iterative_dd_repair_v2_latest.json"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def lifecycle_diagnostic(parent: Mapping[str, Any]) -> dict[str, Any]:
    trades = [x for x in (parent.get("trades") or []) if isinstance(x, Mapping)]
    completed = int(parent.get("completed_trades") or len(trades))
    intents = int(parent.get("intent_count") or 0)
    missing_net = 0
    nonfinite_net = 0
    for trade in trades:
        value = trade.get("net_bps")
        if value is None:
            missing_net += 1
        elif not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            nonfinite_net += 1
    defects = list(parent.get("integrity_defects") or [])
    leakage = int(parent.get("leakage_lookahead") or 0)
    source_quality = str((parent.get("source_quality_gate") or {}).get("state") or "")
    closure_gap = max(0, intents - completed)
    if missing_net or nonfinite_net or defects or leakage:
        state = "HOLD_EXIT_PNL_INTEGRITY"
    elif closure_gap >= max(2, math.ceil(max(1, intents) * 0.25)):
        state = "HOLD_EXIT_CLOSURE_LAG"
    else:
        state = "PASS_EXIT_LIFECYCLE_INTEGRITY"
    return {
        "state": state,
        "completed_trades": completed,
        "intent_count": intents,
        "intent_minus_completed": closure_gap,
        "trade_rows": len(trades),
        "missing_net_bps_count": missing_net,
        "nonfinite_net_bps_count": nonfinite_net,
        "integrity_defects": defects,
        "leakage_lookahead": leakage,
        "source_quality_state": source_quality,
        "entry_relaxation_allowed": False,
        "canonical_mutation": False,
    }


def _parent_receipt(strategy_id: str, boundary: str, outdir: Path, inventory: Mapping[str, Any]) -> dict[str, Any]:
    return router.run_receipt(
        strategy_id,
        router.parent_policy_path(strategy_id, inventory),
        boundary,
        outdir / f".{strategy_id}.executor_parent.json",
    )


def _loss_cluster_repair(strategy_id: str, parent: Mapping[str, Any], hard: Mapping[str, Any]) -> dict[str, Any]:
    if strategy_id not in a4.A4:
        return {
            "state": "HOLD_NO_EXACT_PARENT_REPAIR_ADAPTER",
            "strategy_id": strategy_id,
            "next": "BUILD_DISTINCT_MECHANISM_REBUILD_ADAPTER",
            **AUTH,
        }
    result = a4.evaluate_strategy(strategy_id, parent, hard)
    nxt = result.get("next_exact_parent_candidate") or {}
    return {
        "state": result["state"],
        "strategy_id": strategy_id,
        "parent_metrics": result["parent_metrics"],
        "parent_concentration": result["parent_concentration"],
        "tested_axes": result["tested_axes"],
        "development_ready_count": result["development_ready_count"],
        "next_exact_parent_candidate": nxt or None,
        "next": (
            "REALIZE_CANDIDATE_AS_FROZEN_RESEARCH_CHILD_THEN_START_INDEPENDENT_FRESH_OOS"
            if nxt
            else "ROTATE_TO_NEXT_DISTINCT_MECHANISM_AXIS_OR_FULL_REBUILD_WITHOUT_RESET"
        ),
        "fresh_oos_required": True,
        "identity_h4_h5_required": True,
        **AUTH,
    }


def _break_r4_status() -> dict[str, Any] | None:
    if not BREAK_R4_LATEST.exists():
        return None
    row = read(BREAK_R4_LATEST)
    candidate = row.get("R4_candidate") if isinstance(row.get("R4_candidate"), Mapping) else {}
    if str(row.get("state") or "") != "PASS_R4_COMMON_MODE_QUALITY_SELECTOR_READY":
        return None
    return {
        "state": row.get("state"),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate.get("candidate_sha256"),
        "development_upgrade_gate_pass": bool(candidate.get("development_upgrade_gate_pass")),
        "metrics": candidate.get("metrics"),
        "next": "PRESERVE_R4; IMPLEMENT_FROZEN_COMMON_MODE_OWNER_FOR_FRESH_OOS; DO_NOT_RESTART_DEVELOPMENT",
    }


def run(route_path: Path, out: Path) -> dict[str, Any]:
    routes = read(route_path)
    if str(routes.get("state") or "") != "PASS_NO_IDLE_RESEARCH_ACTIVE":
        raise RuntimeError("NO_IDLE_ROUTER_NOT_ACTIVE")
    if routes.get("selection_authority") is not False or routes.get("promotion_authority") is not False:
        raise RuntimeError("ROUTER_AUTHORITY_NOT_BLOCKED")

    inventory = router.read(router.INVENTORY)
    hard = a4.read(a4.HARDENING_POLICY)
    actions: list[dict[str, Any]] = []
    actionable_count = 0
    repair_ready_count = 0
    integrity_hold_count = 0

    for target in routes.get("targets") or []:
        if not isinstance(target, Mapping):
            continue
        strategy_id = str(target.get("strategy_id") or "")
        state = str(target.get("state") or "")
        boundary = str(target.get("canonical_boundary_utc") or "")
        action: dict[str, Any] = {
            "strategy_id": strategy_id,
            "router_state": state,
            "incumbent_mutated": False,
            "restart_from_zero": False,
            **AUTH,
        }

        if state == "ROUTE_EXISTING_LOSS_CLUSTER_REPAIR":
            actionable_count += 1
            parent = _parent_receipt(strategy_id, boundary, out.parent, inventory)
            repair = _loss_cluster_repair(strategy_id, parent, hard)
            action["action_type"] = "EXECUTED_EXACT_PARENT_LOSS_CLUSTER_REPAIR"
            action["repair"] = repair
            repair_ready_count += int(int(repair.get("development_ready_count") or 0) > 0)
        elif state == "HOLD_EXIT_LIFECYCLE_DIAGNOSIS_REQUIRED":
            actionable_count += 1
            parent = _parent_receipt(strategy_id, boundary, out.parent, inventory)
            diag = lifecycle_diagnostic(parent)
            action["action_type"] = "EXECUTED_EXIT_LIFECYCLE_DIAGNOSTIC"
            action["diagnostic"] = diag
            action["next"] = (
                "PRESERVE_INCUMBENT_AND_REPAIR_SETTLEMENT_TRUTH_BEFORE_ANY_ENTRY_CHANGE"
                if diag["state"].startswith("HOLD_")
                else "EXIT_TRUTH_CLEAN; RESUME_DISTINCT_ONE_AXIS_REPAIR"
            )
            integrity_hold_count += int(diag["state"].startswith("HOLD_"))
        elif state in {"HOLD_SAMPLE_EXPANSION_CHILD_NOT_PARETO_USEFUL"}:
            actionable_count += 1
            parent = _parent_receipt(strategy_id, boundary, out.parent, inventory)
            repair = _loss_cluster_repair(strategy_id, parent, hard)
            action["action_type"] = "EXECUTED_DISTINCT_AXIS_EXACT_PARENT_FAILOVER"
            action["repair"] = repair
            repair_ready_count += int(int(repair.get("development_ready_count") or 0) > 0)
        else:
            action["action_type"] = "PRESERVE_AND_ACCUMULATE"
            action["next"] = str(target.get("next") or "KEEP_COLLECTING")

        if strategy_id == "break_and_continue":
            r4 = _break_r4_status()
            if r4:
                action["preserved_break_r4"] = r4
        action["receipt_sha256"] = stable({k: v for k, v in action.items() if k != "receipt_sha256"})
        actions.append(action)

    result = {
        "schema_version": "zel.a1.finalist.no_idle.action_executor.v1",
        "state": "PASS_NO_IDLE_ACTION_EXECUTOR_ACTIVE",
        "purpose": "Convert no-idle research routes into executed research-only diagnostics and exact-parent one-axis repair comparisons while preserving incumbents and blocking all promotion/execution authority.",
        "router_receipt_sha256": routes.get("receipt_sha256"),
        "actions": actions,
        "actionable_count": actionable_count,
        "repair_ready_count": repair_ready_count,
        "integrity_hold_count": integrity_hold_count,
        "policy": {
            "best_partial_success_preserved": True,
            "restart_from_zero_forbidden": True,
            "one_axis_exact_parent_repair_first": True,
            "structural_failure_routes_to_distinct_mechanism_or_rebuild": True,
            "fresh_oos_required_before_promotion": True,
            "entry_relaxation_for_exit_integrity_failure_forbidden": True,
        },
        "canonical_ledger_mutation": False,
        "canonical_inventory_mutation": False,
        "strategy_parameters_changed": False,
        "action": "hold",
        **AUTH,
    }
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    for p in out.parent.glob(".*.executor_parent.json"):
        p.unlink(missing_ok=True)
    return result


def self_test() -> int:
    clean = {
        "completed_trades": 3,
        "intent_count": 3,
        "trades": [{"net_bps": 1.0}, {"net_bps": -1.0}, {"net_bps": 2.0}],
        "integrity_defects": [],
        "leakage_lookahead": 0,
    }
    bad = {
        "completed_trades": 2,
        "intent_count": 4,
        "trades": [{"net_bps": 1.0}, {"net_bps": None}],
        "integrity_defects": [],
        "leakage_lookahead": 0,
    }
    assert lifecycle_diagnostic(clean)["state"] == "PASS_EXIT_LIFECYCLE_INTEGRITY"
    assert lifecycle_diagnostic(bad)["state"] == "HOLD_EXIT_PNL_INTEGRITY"
    assert AUTH["selection_authority"] is False and AUTH["promotion_authority"] is False
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_FINALIST_NO_IDLE_ACTION_EXECUTOR_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", type=Path, default=ROUTER_LATEST)
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_no_idle_action_executor_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.routes, args.out)
    print(json.dumps({
        "state": result["state"],
        "actionable_count": result["actionable_count"],
        "repair_ready_count": result["repair_ready_count"],
        "integrity_hold_count": result["integrity_hold_count"],
        "actions": {x["strategy_id"]: x["action_type"] for x in result["actions"]},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
