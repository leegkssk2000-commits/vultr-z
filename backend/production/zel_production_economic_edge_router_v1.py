from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_economic_edge_router.v1"
POLICY_SCHEMA = "zel.production_economic_edge_router_policy.v1"
FACTORY_SCHEMA = "zel.production_alpha_factory.v1"
BOOTSTRAP_SCHEMA = "zel.production_performance_bootstrap.v1"
DEFAULT_POLICY = Path("config/zel_production_economic_edge_router_v1.json")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("EDGE_ROUTER_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("EDGE_ROUTER_NON_PAPER_FORBIDDEN")
    if int(policy.get("candidate_budget") or 0) != 1:
        raise RuntimeError("EDGE_ROUTER_CANDIDATE_BUDGET_MUST_BE_1")
    for key in ("factory_path", "bootstrap_state_path", "acquisition_state_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"EDGE_ROUTER_PATH_MISSING:{key}")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("EDGE_ROUTER_LIVE_AUTHORITY_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("EDGE_ROUTER_MUTATION_FORBIDDEN")
    priority = policy.get("family_priority")
    requirements = policy.get("family_requirements")
    if not isinstance(priority, list) or not priority or len(priority) != len(set(map(str, priority))):
        raise RuntimeError("EDGE_ROUTER_PRIORITY_INVALID")
    if not isinstance(requirements, Mapping):
        raise RuntimeError("EDGE_ROUTER_REQUIREMENTS_INVALID")
    route_states = policy.get("route_change_states")
    if not isinstance(route_states, list) or not route_states:
        raise RuntimeError("EDGE_ROUTER_ROUTE_STATES_INVALID")
    return dict(policy)


def _base(state: str, reason: str, *, action: str = "hold") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": state,
        "action": action,
        "reason": reason,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
    }


def _validate_factory(factory: Mapping[str, Any]) -> Mapping[str, Any]:
    if factory.get("schema_version") != FACTORY_SCHEMA:
        raise RuntimeError("EDGE_ROUTER_FACTORY_SCHEMA_INVALID")
    if factory.get("order_authority") != "BLOCKED" or factory.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("EDGE_ROUTER_FACTORY_LIVE_AUTHORITY_INVALID")
    families = factory.get("families")
    if not isinstance(families, Mapping):
        raise RuntimeError("EDGE_ROUTER_FACTORY_FAMILIES_MISSING")
    return families


def _route_required(bootstrap: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    if bootstrap.get("schema_version") != BOOTSTRAP_SCHEMA:
        raise RuntimeError("EDGE_ROUTER_BOOTSTRAP_SCHEMA_INVALID")
    if bootstrap.get("order_authority") != "BLOCKED" or bootstrap.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("EDGE_ROUTER_BOOTSTRAP_LIVE_AUTHORITY_INVALID")
    if bootstrap.get("exchange_order_submitted") is not False:
        raise RuntimeError("EDGE_ROUTER_BOOTSTRAP_ORDER_STATE_INVALID")
    return str(bootstrap.get("state") or "") in set(map(str, policy["route_change_states"]))


def _family_status(family_id: str, row: Mapping[str, Any], required: list[str]) -> tuple[bool, dict[str, Any]]:
    status = str(row.get("status") or "")
    if status.startswith("TERMINAL_REJECT") or row.get("reactivation_allowed") is False:
        return False, {
            "family_id": family_id,
            "status": status,
            "classification": "TERMINAL_REJECT",
            "missing_source_fields": [],
        }
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"EDGE_ROUTER_PREEXISTING_SELECTION_AUTHORITY:{family_id}")
    if row.get("execution_authority") != "NONE":
        raise RuntimeError(f"EDGE_ROUTER_PREEXISTING_EXECUTION_AUTHORITY:{family_id}")
    missing = [key for key in required if row.get(key) is not True]
    if missing:
        return False, {
            "family_id": family_id,
            "status": status,
            "classification": "SOURCE_UNBOUND",
            "missing_source_fields": missing,
        }
    return True, {
        "family_id": family_id,
        "strategy_id": str(row.get("strategy_id") or ""),
        "status": status,
        "symbols": list(row.get("symbols") or []),
        "mechanism": row.get("mechanism"),
        "required_source_fields": list(required),
        "classification": "SOURCE_READY_FOR_BOUNDED_ECONOMIC_ADMISSION",
        "route": "BUILD_BOUNDED_ECONOMIC_ADMISSION_FROM_EXISTING_BOUND_SOURCES",
    }


def route_tick(policy: Mapping[str, Any], *, factory: Mapping[str, Any] | None, bootstrap: Mapping[str, Any] | None, now_ms: int | None = None) -> dict[str, Any]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if bootstrap is None:
        out = _base("HOLD_EDGE_ROUTER_BOOTSTRAP_STATE_MISSING", "BOOTSTRAP_STATE_NOT_AVAILABLE")
    elif not _route_required(bootstrap, cfg):
        out = _base("HOLD_EDGE_ACQUISITION_NOT_REQUIRED", "BOOTSTRAP_NOT_IN_ROUTE_CHANGE")
        out["bootstrap_state"] = bootstrap.get("state")
    elif factory is None:
        out = _base("HOLD_EDGE_ROUTER_FACTORY_MISSING", "ALPHA_FACTORY_NOT_AVAILABLE")
    else:
        families = _validate_factory(factory)
        blockers: list[dict[str, Any]] = []
        queue: list[dict[str, Any]] = []
        requirements = cfg["family_requirements"]
        for raw_id in cfg["family_priority"]:
            family_id = str(raw_id)
            row = families.get(family_id)
            if not isinstance(row, Mapping):
                blockers.append({"family_id": family_id, "classification": "FACTORY_FAMILY_MISSING", "missing_source_fields": []})
                continue
            required_raw = requirements.get(family_id)
            if not isinstance(required_raw, list):
                blockers.append({"family_id": family_id, "classification": "SOURCE_REQUIREMENTS_UNDECLARED", "missing_source_fields": []})
                continue
            eligible, detail = _family_status(family_id, row, [str(x) for x in required_raw])
            if eligible and len(queue) < int(cfg["candidate_budget"]):
                if not detail.get("strategy_id"):
                    blockers.append({"family_id": family_id, "classification": "STRATEGY_ID_MISSING", "missing_source_fields": []})
                else:
                    queue.append(detail)
            else:
                blockers.append(detail)
        if queue:
            out = _base("PASS_EDGE_ACQUISITION_SOURCE_READY_QUEUE", "SOURCE_READY_FAMILY_AVAILABLE")
            out["acquisition_queue"] = queue
            out["blockers"] = blockers
            out["next"] = "RUN_BOUNDED_ECONOMIC_ADMISSION_FOR_QUEUED_FAMILY"
        else:
            out = _base("HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED", "NO_SOURCE_READY_ECONOMIC_FAMILY")
            out["acquisition_queue"] = []
            out["blockers"] = blockers
            out["next"] = "REGISTER_NEW_VERIFIED_ECONOMIC_FAMILY_OR_BIND_MISSING_NATIVE_SOURCE"
        out["bootstrap_state"] = bootstrap.get("state")
    out["updated_at_ms"] = now
    out["receipt_sha256"] = stable_sha(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--tick", action="store_true")
    ns = ap.parse_args()
    policy = json.loads(ns.policy.read_text(encoding="utf-8"))
    cfg = validate_policy(policy)
    factory = read_json(Path(str(cfg["factory_path"])))
    bootstrap = read_json(Path(str(cfg["bootstrap_state_path"])))
    result = route_tick(cfg, factory=factory, bootstrap=bootstrap)
    atomic_json_write(Path(str(cfg["acquisition_state_path"])), result)
    print(json.dumps({
        "state": result["state"],
        "next": result.get("next"),
        "queue_count": len(result.get("acquisition_queue") or []),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
