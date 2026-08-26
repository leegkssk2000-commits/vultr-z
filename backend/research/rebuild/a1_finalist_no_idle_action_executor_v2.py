#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_challenger_rotation_v1 as rotation
from backend.research.rebuild import a1_finalist_no_idle_action_executor_v1 as base

ROOT = Path(__file__).resolve().parents[3]
ROUTER_LATEST = ROOT / "backend/research/rebuild/a1_finalist_sample_stall_no_idle_latest.json"
ROTATION_LATEST = ROOT / "backend/research/rebuild/a1_challenger_rotation_latest.json"
SCHEMA = "zel.a1.finalist.no_idle.action_executor.v2"


def _rotation_index(receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in receipt.get("slots") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        if sid:
            out[sid] = dict(raw)
    return out


def _apply_rotation(result: dict[str, Any], rotation_receipt: Mapping[str, Any]) -> dict[str, Any]:
    if str(rotation_receipt.get("state") or "") != "PASS_CHALLENGER_ROTATION_ACTIVE":
        raise RuntimeError("CHALLENGER_ROTATION_NOT_ACTIVE")
    slots = _rotation_index(rotation_receipt)
    rotation_actionable = 0
    ready = 0
    build = 0
    actions: list[dict[str, Any]] = []

    for raw in result.get("actions") or []:
        if not isinstance(raw, Mapping):
            continue
        action = dict(raw)
        sid = str(action.get("strategy_id") or "")
        slot = slots.get(sid)
        if slot and str(action.get("router_state") or "") == rotation.TERMINAL_STATE:
            rotation_actionable += 1
            state = str(slot.get("state") or "")
            action["challenger_rotation"] = slot
            action["incumbent_mutated"] = False
            action["restart_from_zero"] = False
            if state == "READY_DISTINCT_CHALLENGER_SLOT":
                ready += 1
                action["action_type"] = "ROTATE_DISTINCT_CHALLENGER_SLOT"
                action["next"] = "MATERIALIZE_ONE_FROZEN_RESEARCH_CHILD_AND_START_INDEPENDENT_FRESH_OOS"
            elif state == "BUILD_NEW_DISTINCT_MECHANISM_WITHOUT_RESET":
                build += 1
                action["action_type"] = "BUILD_NEW_DISTINCT_MECHANISM_WITHOUT_RESET"
                action["next"] = str(slot.get("next") or "CONSTRUCT_NEW_MECHANISM_AXIS_FROM_INCUMBENT")
            else:
                raise RuntimeError(f"UNKNOWN_ROTATION_SLOT_STATE:{sid}:{state}")
            action.pop("receipt_sha256", None)
            action["receipt_sha256"] = base.stable(action)
        actions.append(action)

    result["schema_version"] = SCHEMA
    result["purpose"] = "Execute no-idle research routes and convert production-economic terminal rejects into one-slot distinct challenger rotation without mutating or resetting incumbents."
    result["actions"] = actions
    result["challenger_rotation_receipt_sha256"] = rotation_receipt.get("receipt_sha256")
    result["rotation_actionable_count"] = rotation_actionable
    result["rotation_ready_slot_count"] = ready
    result["rotation_build_new_mechanism_count"] = build
    result["actionable_count"] = int(result.get("actionable_count") or 0) + rotation_actionable
    policy = dict(result.get("policy") or {})
    policy.update({
        "terminal_reject_routes_to_rotation": True,
        "one_challenger_per_strategy": True,
        "failed_child_replay_forbidden": True,
        "incumbent_reset_forbidden": True,
        "production_economic_guard_required_for_rotation": True,
    })
    result["policy"] = policy
    result["strategy_parameters_changed"] = False
    result["canonical_ledger_mutation"] = False
    result["canonical_inventory_mutation"] = False
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result["action"] = "hold"
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = base.stable(result)
    return result


def run(route_path: Path, rotation_path: Path, out: Path) -> dict[str, Any]:
    base_out = out.parent / ".a1_finalist_no_idle_action_executor_v1_for_v2.json"
    try:
        result = dict(base.run(route_path, base_out))
        rotation_receipt = rotation.read(rotation_path)
        result = _apply_rotation(result, rotation_receipt)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return result
    finally:
        base_out.unlink(missing_ok=True)


def self_test() -> int:
    base_result = {
        "actions": [{
            "strategy_id": "trend_ma_macd",
            "router_state": rotation.TERMINAL_STATE,
            "action_type": "PRESERVE_AND_ACCUMULATE",
            "incumbent_mutated": False,
            "restart_from_zero": False,
        }],
        "actionable_count": 0,
        "policy": {},
    }
    rot = {
        "state": "PASS_CHALLENGER_ROTATION_ACTIVE",
        "receipt_sha256": "r1",
        "slots": [{
            "strategy_id": "trend_ma_macd",
            "state": "BUILD_NEW_DISTINCT_MECHANISM_WITHOUT_RESET",
            "challenger_slot_count": 0,
            "incumbent_mutated": False,
            "restart_from_zero": False,
            "next": "CONSTRUCT_NEW_MECHANISM_AXIS_FROM_INCUMBENT",
        }],
    }
    out = _apply_rotation(dict(base_result), rot)
    assert out["actions"][0]["action_type"] == "BUILD_NEW_DISTINCT_MECHANISM_WITHOUT_RESET"
    assert out["rotation_actionable_count"] == 1 and out["actionable_count"] == 1
    assert out["selection_authority"] is False and out["promotion_authority"] is False
    assert out["execution_authority"] == "NONE" and out["order_authority"] == "BLOCKED"
    assert out["strategy_parameters_changed"] is False
    print("PASS_A1_FINALIST_NO_IDLE_ACTION_EXECUTOR_V2_SELF_TEST")
    print("PASS_TERMINAL_REJECT_ROTATES_WITHOUT_INCUMBENT_RESET")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", type=Path, default=ROUTER_LATEST)
    ap.add_argument("--rotation", type=Path, default=ROTATION_LATEST)
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_no_idle_action_executor_v2_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.routes, args.rotation, args.out)
    print(json.dumps({
        "state": result.get("state"),
        "actionable_count": result.get("actionable_count"),
        "rotation_actionable_count": result.get("rotation_actionable_count"),
        "rotation_ready_slot_count": result.get("rotation_ready_slot_count"),
        "rotation_build_new_mechanism_count": result.get("rotation_build_new_mechanism_count"),
        "actions": {x["strategy_id"]: x["action_type"] for x in result.get("actions", [])},
        "receipt_sha256": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
