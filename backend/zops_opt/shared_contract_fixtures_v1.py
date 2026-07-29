from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

VERSION = "zops_shared_contract_fixtures_v1"
router = APIRouter(prefix="/api/optimization/fixtures", tags=["zops-optimization-fixtures-v1"])

CANONICAL_GROUPS: Dict[str, Dict[str, Any]] = {
    "gate": {
        "canonical_prefixes": ["/api/gate"],
        "compat_alias_prefixes": ["/api/order-gate"],
        "required_paths": ["/api/gate/health", "/api/order-gate/health"],
        "fixture": {
            "ok": True,
            "component": "order_risk_gate_contract_v1",
            "policy_id": "zops_gate_policy_v1",
            "execution_enabled": False,
            "advisory_only": True,
            "order_mutation": "blocked",
            "os_final_approval_required": True,
            "allowed_action": "hold",
            "contract": {
                "pre_trade_validation": True,
                "risk_gate": True,
                "structured_reject_reason": True,
                "no_live_order_side_effect": True,
            },
        },
    },
    "replay": {
        "canonical_prefixes": ["/api/replay"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/replay/health"],
        "fixture": {
            "ok": True,
            "component": "deterministic_replay_engine_v1",
            "decision_id": "decision_sample_001",
            "seed": "seed_sample_001",
            "same_seed_same_payload_same_decision_id": True,
            "exchange_simulator": "deterministic_stub",
            "order_mutation": "blocked",
        },
    },
    "ledger": {
        "canonical_prefixes": ["/api/ledger"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/ledger/health"],
        "fixture": {
            "ok": True,
            "component": "dual_ledger_reconciliation_v1",
            "mode": "append_only_immutable_event_log",
            "reconciliation": "bingx_internal_pnl_daily",
            "mismatch_action": "alimi_critical_alert_plus_strategy_pause",
            "order_mutation": "blocked",
        },
    },
    "promotion": {
        "canonical_prefixes": ["/api/promotion"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/promotion/health"],
        "fixture": {
            "ok": True,
            "component": "promotion_gate_v2_regression_harness",
            "canary_days_min": 14,
            "canary_days_target": 21,
            "os_veto_required": True,
            "metrics": ["regime_similarity_score", "minimum_trade_count", "out_of_sample_decay_rate"],
            "order_mutation": "blocked",
        },
    },
    "harness": {
        "canonical_prefixes": ["/api/harness"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/harness/health", "/api/harness/visual/status"],
        "fixture": {
            "ok": True,
            "component": "harness_control_plane_v2",
            "sentinel": "available",
            "review": "available",
            "deployguard": "available",
            "visual_gate": "active",
            "order_mutation": "blocked",
        },
    },
    "chaos": {
        "canonical_prefixes": ["/api/chaos"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/chaos/health"],
        "fixture": {
            "ok": True,
            "component": "chaos_test_suite_v1",
            "cases": ["stale_price", "latency_injection", "exchange_disconnect", "liq_buffer"],
            "order_mutation": "blocked",
        },
    },
    "alimi": {
        "canonical_prefixes": ["/api/alimi"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/alimi/health"],
        "fixture": {
            "ok": True,
            "component": "alimi_dashboard_v1",
            "policy": "violation_only_bundle_10m_by_symbol_strategy",
            "actions": ["reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"],
            "order_mutation": "blocked",
        },
    },
    "lico": {
        "canonical_prefixes": ["/api/lico"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/lico/health"],
        "fixture": {
            "ok": True,
            "component": "lico_guard_v1",
            "sources": ["cf", "sheets"],
            "min_data_policy": "hold_on_missing",
            "order_mutation": "blocked",
        },
    },
    "observability": {
        "canonical_prefixes": ["/api/observability"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/observability/health"],
        "fixture": {
            "ok": True,
            "component": "observability_chain_v1",
            "chain": "zbot -> app_projection -> zlice_proof -> receipt_archive",
            "proof": "sample_valid",
            "order_mutation": "blocked",
        },
    },
    "optimization": {
        "canonical_prefixes": ["/api/optimization"],
        "compat_alias_prefixes": [],
        "required_paths": ["/api/optimization/health"],
        "fixture": {
            "ok": True,
            "component": "optimization_control_plane",
            "mode": "audit_plus_safe_runtime_guard",
            "order_mutation": "blocked",
        },
    },
}

REQUIRED_FIXTURE_FIELDS = ["ok", "component", "order_mutation"]

def now_ms() -> int:
    return int(time.time() * 1000)


def stable_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def base_envelope() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "status": "pass",
        "mode": "shared_contract_fixtures_advisory_only",
        "advisory_only": True,
        "order_mutation": "blocked",
        "source_deletion": "none",
        "runtime_route_change": "none",
        "os_final_approval_required": True,
        "ts_ms": now_ms(),
    }


def fixture_for(group: str, kind: str = "sample") -> Dict[str, Any]:
    if group not in CANONICAL_GROUPS:
        return {
            **base_envelope(),
            "status": "fail",
            "error": "unknown_group",
            "group": group,
            "allowed_groups": sorted(CANONICAL_GROUPS.keys()),
        }
    payload = deepcopy(CANONICAL_GROUPS[group]["fixture"])
    payload.update(
        {
            "version": VERSION,
            "group": group,
            "kind": kind,
            "fixture_hash": stable_hash(payload),
            "ts_ms": now_ms(),
        }
    )
    return payload


def manifest() -> Dict[str, Any]:
    groups = {}
    for group, meta in CANONICAL_GROUPS.items():
        fx = fixture_for(group)
        groups[group] = {
            "canonical_prefixes": meta["canonical_prefixes"],
            "compat_alias_prefixes": meta["compat_alias_prefixes"],
            "required_paths": meta["required_paths"],
            "fixture_hash": fx["fixture_hash"],
            "required_fields_present": all(k in fx for k in REQUIRED_FIXTURE_FIELDS),
        }
    return {
        **base_envelope(),
        "groups": groups,
        "required_fixture_fields": REQUIRED_FIXTURE_FIELDS,
        "decision": "shared_contract_fixtures_v1_ready; next=sample_payload_source_consolidation_v1",
    }


def _route_methods(route: Any) -> List[str]:
    return sorted([m for m in getattr(route, "methods", set()) if m not in {"HEAD", "OPTIONS"}])


def route_snapshot(app: Any) -> Dict[str, Any]:
    routes = list(getattr(app, "routes", []))
    path_records: List[Dict[str, Any]] = []
    by_path: Dict[str, int] = {}
    sample_paths: List[str] = []
    health_paths: Dict[str, bool] = {}
    owners_sample: Dict[str, int] = {}

    for r in routes:
        path = getattr(r, "path", None)
        if not path:
            continue
        endpoint = getattr(r, "endpoint", None)
        owner_module = getattr(endpoint, "__module__", "unknown") if endpoint else "unknown"
        by_path[path] = by_path.get(path, 0) + 1
        owners_sample[owner_module] = owners_sample.get(owner_module, 0) + 1
        if path.startswith("/api/"):
            path_records.append({"path": path, "methods": _route_methods(r), "owner": owner_module})
        if "/sample" in path or "sample" in path.lower():
            sample_paths.append(path)

    for group, meta in CANONICAL_GROUPS.items():
        for required in meta["required_paths"]:
            health_paths[required] = required in by_path

    duplicate_paths = sorted([p for p, n in by_path.items() if n > 1 and p.startswith("/api/")])
    return {
        "route_count": len(routes),
        "api_route_count": len(path_records),
        "unique_api_path_count": len({x["path"] for x in path_records}),
        "duplicate_path_count": len(duplicate_paths),
        "duplicate_paths_sample": duplicate_paths[:20],
        "sample_paths_count": len(sorted(set(sample_paths))),
        "sample_paths_sample": sorted(set(sample_paths))[:40],
        "owners_sample": dict(sorted(owners_sample.items(), key=lambda kv: kv[1], reverse=True)[:30]),
        "required_health_paths": health_paths,
        "missing_required_health_paths": [p for p, ok in health_paths.items() if not ok],
    }


def status_payload(app: Optional[Any] = None) -> Dict[str, Any]:
    m = manifest()
    fixture_failures = []
    for group in CANONICAL_GROUPS:
        fx = fixture_for(group)
        missing = [k for k in REQUIRED_FIXTURE_FIELDS if k not in fx]
        if missing:
            fixture_failures.append({"group": group, "missing": missing})
    status = {
        **base_envelope(),
        "fixtures": m["groups"],
        "fixture_failures": fixture_failures,
        "hard_fail_flags": [] if not fixture_failures else ["fixture_contract_missing_required_fields"],
        "risk_flags": ["source_sample_generators_not_removed_yet", "compat_aliases_still_tag_only"],
        "next_safe_actions": [
            "replace duplicate sample/mock payload generation with shared fixture imports per module",
            "keep existing /api/* runtime responses unchanged until smoke parity passes",
            "then collapse wrapper/drop-in chain into single composition root",
            "keep visual harness pass before any source-level deletion",
        ],
        "decision": "shared_contract_fixtures_v1_pass; next=sample_payload_source_consolidation_v1",
    }
    if app is not None:
        status["route"] = route_snapshot(app)
        if status["route"]["missing_required_health_paths"]:
            status["hard_fail_flags"].append("required_health_path_missing")
            status["status"] = "fail"
    if status["hard_fail_flags"]:
        status["status"] = "fail"
    return status


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        **base_envelope(),
        "component": "shared_contract_fixtures_v1",
        "groups": sorted(CANONICAL_GROUPS.keys()),
        "fixture_count": len(CANONICAL_GROUPS),
        "decision": "pass",
    }


@router.get("/status")
def status(request: Request) -> Dict[str, Any]:
    return status_payload(request.app)


@router.get("/manifest")
def manifest_endpoint() -> Dict[str, Any]:
    return manifest()


@router.get("/sample/{group}")
def sample(group: str) -> JSONResponse:
    payload = fixture_for(group)
    code = 200 if payload.get("status") != "fail" else 404
    return JSONResponse(payload, status_code=code)


@router.post("/validate")
async def validate(request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    group = str(body.get("group") or "").strip()
    payload = body.get("payload") if isinstance(body, dict) else None
    failures = []
    if group and group not in CANONICAL_GROUPS:
        failures.append("unknown_group")
    if payload is not None and not isinstance(payload, dict):
        failures.append("payload_not_object")
    if isinstance(payload, dict):
        missing = [k for k in REQUIRED_FIXTURE_FIELDS if k not in payload]
        if missing:
            failures.append("payload_missing_fields:" + ",".join(missing))
    return {
        **base_envelope(),
        "status": "pass" if not failures else "fail",
        "group": group or None,
        "failures": failures,
        "decision": "fixture_validate_pass" if not failures else "fixture_validate_fail_hold",
    }


@router.post("/apply")
def apply_blocked() -> Dict[str, Any]:
    return {
        **base_envelope(),
        "status": "blocked",
        "reason": "source rewrite not allowed in shared_contract_fixtures_v1; audit/staging only",
        "allowed_next": "sample_payload_source_consolidation_v1 after manual smoke parity",
        "decision": "block",
    }
