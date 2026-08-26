#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research import production_economic_guard_v1 as prod_guard
from backend.research.rebuild import a1_a4_distinct_child_repair_batch_v1 as distinct
from backend.research.rebuild import a1_finalist_sample_stall_no_idle_router_v1 as router

ROOT = Path(__file__).resolve().parents[3]
ROUTER_LATEST = ROOT / "backend/research/rebuild/a1_finalist_sample_stall_no_idle_latest.json"
ROTATION_LATEST = ROOT / "backend/research/rebuild/a1_challenger_rotation_latest.json"
BREAK_R4_LATEST = ROOT / "backend/research/rebuild/a1_break_box_iterative_dd_repair_v2_latest.json"
SCHEMA = "zel.a1.challenger_rotation.v1"
TERMINAL_STATE = "REJECT_CHILD_PRODUCTION_ECONOMICS"

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


def _terminal_signature(routes: Mapping[str, Any]) -> str:
    rows: list[dict[str, Any]] = []
    for raw in routes.get("targets") or []:
        if not isinstance(raw, Mapping) or str(raw.get("state") or "") != TERMINAL_STATE:
            continue
        guard = raw.get("production_economic_guard") if isinstance(raw.get("production_economic_guard"), Mapping) else {}
        rows.append({
            "strategy_id": str(raw.get("strategy_id") or ""),
            "canonical_boundary_utc": str(raw.get("canonical_boundary_utc") or ""),
            "reject_source": str(raw.get("production_child_reject_source") or ""),
            "guard_reasons": list(guard.get("reasons") or []),
            "guard_child": guard.get("child"),
        })
    rows.sort(key=lambda x: x["strategy_id"])
    return stable(rows)


def _cached_slots(signature: str) -> dict[str, dict[str, Any]]:
    if not ROTATION_LATEST.exists():
        return {}
    previous = read(ROTATION_LATEST)
    if str(previous.get("terminal_signature") or "") != signature:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw in previous.get("slots") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        state = str(raw.get("state") or "")
        if sid and state in {"READY_DISTINCT_CHALLENGER_SLOT", "BUILD_NEW_DISTINCT_MECHANISM_WITHOUT_RESET"}:
            row = dict(raw)
            row["cache_reused"] = True
            row["incumbent_mutated"] = False
            row["restart_from_zero"] = False
            out[sid] = row
    return out


def _historical_break_r4() -> dict[str, Any] | None:
    if not BREAK_R4_LATEST.exists():
        return None
    raw = read(BREAK_R4_LATEST)
    candidate = raw.get("R4_candidate") if isinstance(raw.get("R4_candidate"), Mapping) else None
    if not candidate:
        return None
    return {
        "state": raw.get("state"),
        "comparison_boundary_utc": raw.get("comparison_boundary_utc"),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate.get("candidate_sha256"),
        "metrics": candidate.get("metrics"),
        "development_upgrade_gate_pass": bool(candidate.get("development_upgrade_gate_pass")),
        "preserved": True,
        "current_context_replay_required_before_slot_reservation": True,
        "reason": "HISTORICAL_R4_LINEAGE_IS_NOT_ASSUMED_COMPARABLE_TO_CURRENT_INCUMBENT_RECEIPT",
    }


def _guard_candidates(parent: Mapping[str, Any], evaluated: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    rows: list[dict[str, Any]] = []
    for raw in evaluated.get("candidates") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        verdict = prod_guard.evaluate(parent, row)
        row["production_economic_guard"] = verdict
        row["pre_production_guard_development_candidate_ready"] = bool(row.get("development_candidate_ready"))
        row["rotation_eligible"] = bool(row.get("development_candidate_ready") and verdict.get("pass"))
        rows.append(row)
    eligible = [x for x in rows if x.get("rotation_eligible") is True]
    return rows, (eligible[0] if eligible else None)


def _slot_from_current_parent(
    strategy_id: str,
    boundary: str,
    *,
    inventory: Mapping[str, Any],
    hard: Mapping[str, Any],
    outdir: Path,
) -> dict[str, Any]:
    parent_out = outdir / f".{strategy_id}.challenger_rotation_parent.json"
    parent = router.run_receipt(
        strategy_id,
        router.parent_policy_path(strategy_id, inventory),
        boundary,
        parent_out,
    )
    try:
        evaluated = distinct.evaluate(strategy_id, parent, hard)
        candidates, chosen = _guard_candidates(parent, evaluated)
        base = {
            "strategy_id": strategy_id,
            "canonical_boundary_utc": boundary,
            "parent_receipt_sha256": parent.get("receipt_sha256"),
            "parent_metrics": evaluated.get("parent_metrics"),
            "candidate_count": len(candidates),
            "production_guard_pass_count": sum(x.get("production_economic_guard", {}).get("pass") is True for x in candidates),
            "rotation_eligible_count": sum(x.get("rotation_eligible") is True for x in candidates),
            "candidate_diagnostics": candidates,
            "challenger_slot_count": 1 if chosen else 0,
            "incumbent_mutated": False,
            "restart_from_zero": False,
            "strategy_parameters_changed": False,
            "fresh_oos_required_before_any_promotion": True,
            **AUTH,
        }
        if chosen:
            base.update({
                "state": "READY_DISTINCT_CHALLENGER_SLOT",
                "challenger": chosen,
                "next": "MATERIALIZE_ONE_FROZEN_RESEARCH_CHILD_AND_START_INDEPENDENT_FRESH_OOS",
            })
        else:
            base.update({
                "state": "BUILD_NEW_DISTINCT_MECHANISM_WITHOUT_RESET",
                "challenger": None,
                "next": "CONSTRUCT_NEW_MECHANISM_AXIS_FROM_INCUMBENT; KEEP_INCUMBENT_COLLECTING; DO_NOT_RESTART_ZERO",
            })
        if strategy_id == "break_and_continue":
            base["preserved_historical_break_r4"] = _historical_break_r4()
        base["slot_receipt_sha256"] = stable({k: v for k, v in base.items() if k != "slot_receipt_sha256"})
        return base
    finally:
        parent_out.unlink(missing_ok=True)


def run(route_path: Path, out: Path, *, reuse_cache: bool = True) -> dict[str, Any]:
    routes = read(route_path)
    if str(routes.get("state") or "") != "PASS_NO_IDLE_RESEARCH_ACTIVE":
        raise RuntimeError("NO_IDLE_ROUTER_NOT_ACTIVE")
    if routes.get("selection_authority") is not False or routes.get("promotion_authority") is not False:
        raise RuntimeError("ROUTER_AUTHORITY_NOT_BLOCKED")

    terminals = [
        x for x in (routes.get("targets") or [])
        if isinstance(x, Mapping) and str(x.get("state") or "") == TERMINAL_STATE
    ]
    signature = _terminal_signature(routes)
    cached = _cached_slots(signature) if reuse_cache else {}
    inventory = router.read(router.INVENTORY)
    hard = distinct.read(distinct.HARDENING_POLICY)
    slots: list[dict[str, Any]] = []

    for target in terminals:
        sid = str(target.get("strategy_id") or "")
        boundary = str(target.get("canonical_boundary_utc") or "")
        if not sid or not boundary:
            raise RuntimeError("TERMINAL_TARGET_ID_OR_BOUNDARY_MISSING")
        if sid in cached:
            slot = dict(cached[sid])
        elif sid in distinct.A4:
            slot = _slot_from_current_parent(sid, boundary, inventory=inventory, hard=hard, outdir=out.parent)
        else:
            slot = {
                "strategy_id": sid,
                "canonical_boundary_utc": boundary,
                "state": "BUILD_NEW_DISTINCT_MECHANISM_WITHOUT_RESET",
                "challenger": None,
                "challenger_slot_count": 0,
                "incumbent_mutated": False,
                "restart_from_zero": False,
                "strategy_parameters_changed": False,
                "next": "BUILD_STRATEGY_SPECIFIC_DISTINCT_MECHANISM_ADAPTER",
                **AUTH,
            }
            slot["slot_receipt_sha256"] = stable({k: v for k, v in slot.items() if k != "slot_receipt_sha256"})
        if int(slot.get("challenger_slot_count") or 0) > 1:
            raise RuntimeError(f"MULTIPLE_CHALLENGER_SLOTS_FORBIDDEN:{sid}")
        slots.append(slot)

    slots.sort(key=lambda x: str(x.get("strategy_id") or ""))
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_CHALLENGER_ROTATION_ACTIVE",
        "purpose": "Replace terminal-rejected fixed children with at most one production-guarded distinct research challenger per strategy while preserving the incumbent and never resetting its evidence.",
        "router_receipt_sha256": routes.get("receipt_sha256"),
        "terminal_signature": signature,
        "terminal_reject_count": len(terminals),
        "slot_count": len(slots),
        "ready_slot_count": sum(x.get("state") == "READY_DISTINCT_CHALLENGER_SLOT" for x in slots),
        "build_new_mechanism_count": sum(x.get("state") == "BUILD_NEW_DISTINCT_MECHANISM_WITHOUT_RESET" for x in slots),
        "max_challengers_per_strategy": 1,
        "slots": slots,
        "policy": {
            "incumbent_always_preserved": True,
            "restart_from_zero_forbidden": True,
            "one_challenger_per_strategy": True,
            "known_failed_child_replay_forbidden": True,
            "production_economic_guard_required": True,
            "fresh_oos_required_before_promotion": True,
            "historical_candidate_requires_current_context_replay": True,
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
    return result


def self_test() -> int:
    parent = {"completed_trades": 9, "metrics": {"net_pnl_bps": 900.0, "net_expectancy_bps": 100.0, "max_drawdown_bps": 300.0}}
    candidates = {
        "candidates": [
            {"candidate_id": "density_killer", "development_candidate_ready": True, "completed_trades": 7, "metrics": {"net_pnl_bps": 1100.0, "net_expectancy_bps": 157.0, "drawdown_bps": 200.0}},
            {"candidate_id": "valid_one", "development_candidate_ready": True, "completed_trades": 9, "metrics": {"net_pnl_bps": 1000.0, "net_expectancy_bps": 111.0, "drawdown_bps": 250.0}},
            {"candidate_id": "extra_valid_but_not_selected", "development_candidate_ready": True, "completed_trades": 10, "metrics": {"net_pnl_bps": 1050.0, "net_expectancy_bps": 105.0, "drawdown_bps": 260.0}},
        ]
    }
    rows, chosen = _guard_candidates(parent, candidates)
    assert rows[0]["rotation_eligible"] is False
    assert "TRADE_COUNT_DECREASE" in rows[0]["production_economic_guard"]["reasons"]
    assert chosen is not None and chosen["candidate_id"] == "valid_one"
    assert AUTH["selection_authority"] is False and AUTH["promotion_authority"] is False
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_CHALLENGER_ROTATION_V1_SELF_TEST")
    print("PASS_ONE_SLOT_INCUMBENT_PRESERVE_NO_RESET_INVARIANT")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", type=Path, default=ROUTER_LATEST)
    ap.add_argument("--out", type=Path, default=Path("out/a1_challenger_rotation_latest.json"))
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.routes, args.out, reuse_cache=not args.no_cache)
    print(json.dumps({
        "state": result["state"],
        "terminal_reject_count": result["terminal_reject_count"],
        "ready_slot_count": result["ready_slot_count"],
        "build_new_mechanism_count": result["build_new_mechanism_count"],
        "slots": {x["strategy_id"]: x["state"] for x in result["slots"]},
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
