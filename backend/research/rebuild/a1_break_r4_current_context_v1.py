#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research import production_economic_guard_v1 as prod_guard
from backend.research.rebuild import a1_break_box_iterative_dd_repair_v1 as r1
from backend.research.rebuild import a1_break_box_iterative_dd_repair_v2 as r4
from backend.research.rebuild import a1_finalist_sample_stall_no_idle_router_v1 as router

ROOT = Path(__file__).resolve().parents[3]
ROUTER_LATEST = ROOT / "backend/research/rebuild/a1_finalist_sample_stall_no_idle_latest.json"
SCHEMA = "zel.a1.break_r4.current_context.v1"
STRATEGY_ID = "break_and_continue"

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


def _break_terminal(routes: Mapping[str, Any]) -> dict[str, Any]:
    for raw in routes.get("targets") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("strategy_id") or "") != STRATEGY_ID:
            continue
        if str(raw.get("state") or "") != "REJECT_CHILD_PRODUCTION_ECONOMICS":
            raise RuntimeError("BREAK_NOT_TERMINAL_REJECT")
        return dict(raw)
    raise RuntimeError("BREAK_TERMINAL_TARGET_MISSING")


def evaluate_current(parent: Mapping[str, Any], box: Mapping[str, Any], boundary: str) -> dict[str, Any]:
    lineage = r4.evaluate(parent, box, boundary)
    candidate = dict(lineage["R4_candidate"])
    verdict = prod_guard.evaluate(parent, candidate)
    candidate["production_economic_guard"] = verdict
    candidate["current_incumbent_comparable"] = True
    candidate["current_incumbent_receipt_sha256"] = parent.get("receipt_sha256")
    candidate["box_child_receipt_sha256"] = box.get("receipt_sha256")
    eligible = bool(candidate.get("development_upgrade_gate_pass") and verdict.get("pass"))
    candidate["current_context_rotation_eligible"] = eligible

    result = {
        "schema_version": SCHEMA,
        "strategy_id": STRATEGY_ID,
        "comparison_boundary_utc": boundary,
        "state": "READY_BREAK_R4_CURRENT_CONTEXT_ONE_SLOT" if eligible else "REJECT_BREAK_R4_CURRENT_CONTEXT",
        "current_incumbent": prod_guard.snapshot(parent),
        "current_incumbent_receipt_sha256": parent.get("receipt_sha256"),
        "current_box_child": prod_guard.snapshot(box),
        "current_box_child_receipt_sha256": box.get("receipt_sha256"),
        "R4_candidate": candidate,
        "R4_original_development_gate_pass": bool(candidate.get("development_upgrade_gate_pass")),
        "production_guard_pass": bool(verdict.get("pass")),
        "production_guard_reasons": list(verdict.get("reasons") or []),
        "challenger_slot_count": 1 if eligible else 0,
        "next": (
            "FREEZE_EXACT_R4_AS_BREAK_ONE_CHALLENGER_AND_START_INDEPENDENT_FRESH_OOS"
            if eligible else
            "BUILD_NEW_BREAK_EXIT_OR_LOSS_PATH_MECHANISM_WITHOUT_RESET"
        ),
        "policy": {
            "incumbent_preserved": True,
            "restart_from_zero_forbidden": True,
            "one_challenger_per_strategy": True,
            "historical_r4_not_auto_promoted": True,
            "current_context_replay_required": True,
            "trade_density_may_not_decrease": True,
            "production_economic_guard_required": True,
            "fresh_oos_required_before_any_promotion": True,
        },
        "incumbent_mutated": False,
        "restart_from_zero": False,
        "strategy_parameters_changed": False,
        "canonical_ledger_mutation": False,
        "canonical_inventory_mutation": False,
        "action": "hold",
        **AUTH,
    }
    result["receipt_sha256"] = stable(result)
    return result


def run(routes_path: Path, out: Path) -> dict[str, Any]:
    routes = read(routes_path)
    target = _break_terminal(routes)
    boundary = str(target.get("canonical_boundary_utc") or "")
    if not boundary:
        raise RuntimeError("BREAK_BOUNDARY_MISSING")
    inventory = router.read(router.INVENTORY)
    parent_policy = router.parent_policy_path(STRATEGY_ID, inventory)
    with tempfile.TemporaryDirectory(prefix="break_r4_current_context_") as td:
        p = Path(td)
        parent = router.run_receipt(STRATEGY_ID, parent_policy, boundary, p / "parent.json")
        box = router.run_receipt(STRATEGY_ID, r1.BOX_CHILD, boundary, p / "box.json")
    result = evaluate_current(parent, box, boundary)
    result["router_receipt_sha256"] = routes.get("receipt_sha256")
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    parent = {
        "completed_trades": 10,
        "metrics": {"net_pnl_bps": 1000.0, "net_expectancy_bps": 100.0, "net_profit_factor": 2.0, "max_drawdown_bps": 300.0},
        "receipt_sha256": "parent",
    }
    fewer = {
        "candidate_id": "break_box_r4_common_mode_lowest_chase_owner_v1",
        "development_upgrade_gate_pass": True,
        "metrics": {"trades": 8, "net_pnl_bps": 1200.0, "net_expectancy_bps": 150.0, "profit_factor": 3.0, "drawdown_bps": 200.0},
    }
    verdict = prod_guard.evaluate(parent, fewer)
    assert verdict["hard_fail"] is True
    assert "TRADE_COUNT_DECREASE" in verdict["reasons"]
    assert verdict["incumbent_state_action"] == "PRESERVE_UNCHANGED"
    equal = {
        "metrics": {"trades": 10, "net_pnl_bps": 1100.0, "net_expectancy_bps": 110.0, "profit_factor": 2.1, "drawdown_bps": 250.0}
    }
    good = prod_guard.evaluate(parent, equal)
    assert good["pass"] is True
    assert AUTH["selection_authority"] is False and AUTH["promotion_authority"] is False
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_BREAK_R4_CURRENT_CONTEXT_V1_SELF_TEST")
    print("PASS_R4_CANNOT_BYPASS_CURRENT_INCUMBENT_TRADE_DENSITY")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", type=Path, default=ROUTER_LATEST)
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_r4_current_context_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.routes, args.out)
    c = result["R4_candidate"]
    print(json.dumps({
        "state": result["state"],
        "parent": result["current_incumbent"],
        "box": result["current_box_child"],
        "r4": c.get("metrics"),
        "r4_original_gate": result["R4_original_development_gate_pass"],
        "production_guard_pass": result["production_guard_pass"],
        "production_guard_reasons": result["production_guard_reasons"],
        "challenger_slot_count": result["challenger_slot_count"],
        "next": result["next"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
