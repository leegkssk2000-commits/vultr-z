"""
Z-OS Legacy Alias Quarantine v1
- tag-only quarantine for legacy API aliases/wrappers/overlay owners
- no route deletion, no redirect, no order mutation
- prepares later source-level consolidation after harness stays green
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

VERSION = "zops_legacy_alias_quarantine_v1"
ROOT = Path(os.environ.get("ZOPS_ROOT", "/home/z/z"))
DATA_DIR = Path(os.environ.get("ZOPS_DATA_DIR", str(ROOT / "data")))
OPS_DIR = DATA_DIR / "ops"
REPORT_PATH = OPS_DIR / "legacy_alias_quarantine_v1_report.json"

router = APIRouter(prefix="/api/optimization/legacy-alias", tags=["zops-legacy-alias-quarantine-v1"])

# Canonical means the long-term owner surface. Compat aliases are preserved until a later
# removal window; this patch only tags and audits them.
SURFACE_POLICY: Dict[str, Dict[str, List[str]]] = {
    "gate": {
        "canonical": ["/api/gate"],
        "compat_alias": ["/api/order-gate"],
    },
    "replay": {"canonical": ["/api/replay"], "compat_alias": []},
    "ledger": {"canonical": ["/api/ledger"], "compat_alias": []},
    "promotion": {"canonical": ["/api/promotion"], "compat_alias": []},
    "harness": {"canonical": ["/api/harness"], "compat_alias": []},
    "chaos": {"canonical": ["/api/chaos"], "compat_alias": []},
    "alimi": {"canonical": ["/api/alimi"], "compat_alias": []},
    "lico": {"canonical": ["/api/lico"], "compat_alias": []},
    "observability": {"canonical": ["/api/observability"], "compat_alias": []},
    "optimization": {"canonical": ["/api/optimization"], "compat_alias": []},
}

REQUIRED_HEALTH_PATHS = [
    "/api/gate/health",
    "/api/order-gate/health",
    "/api/replay/health",
    "/api/ledger/health",
    "/api/promotion/health",
    "/api/harness/health",
    "/api/harness/visual/status",
    "/api/alimi/health",
    "/api/lico/health",
    "/api/optimization/typed-registry/health",
    "/api/optimization/legacy-alias/health",
]

LEGACY_OWNER_TOKENS = (
    "alias",
    "overlay",
    "wrapper",
    "hard_mount",
    "force_runtime",
    "rescue",
    "runtime_mount",
    "compat",
)

BLOCKED_PREFIXES = ("/docs", "/redoc", "/openapi", "/static", "/assets")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_write_json(path: Path, payload: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _methods(route: Any) -> Tuple[str, ...]:
    raw = getattr(route, "methods", None) or []
    return tuple(sorted(str(m).upper() for m in raw if str(m).upper() not in {"HEAD", "OPTIONS"}))


def _path(route: Any) -> str:
    return str(getattr(route, "path", ""))


def _owner(route: Any) -> Dict[str, str]:
    endpoint = getattr(route, "endpoint", None)
    module = getattr(endpoint, "__module__", "unknown") if endpoint else "unknown"
    name = getattr(endpoint, "__name__", getattr(route, "name", "unknown")) if endpoint else getattr(route, "name", "unknown")
    return {"module": str(module), "name": str(name)}


def _route_record(route: Any, idx: int) -> Dict[str, Any]:
    return {
        "index": idx,
        "path": _path(route),
        "methods": list(_methods(route)),
        "name": str(getattr(route, "name", "")),
        "owner": _owner(route),
    }


def _safe_api_path(path: str) -> bool:
    if not path or any(path.startswith(p) for p in BLOCKED_PREFIXES):
        return False
    return path.startswith("/api/") or path == "/health"


def _classify_surface(path: str) -> Tuple[str, str]:
    """Return (group, role), where role is canonical/compat_alias/outside_policy."""
    for group, policy in SURFACE_POLICY.items():
        for p in policy.get("canonical", []):
            if path == p or path.startswith(p + "/"):
                return group, "canonical"
        for p in policy.get("compat_alias", []):
            if path == p or path.startswith(p + "/"):
                return group, "compat_alias"
    return "outside_policy", "outside_policy"


def _legacy_owner_type(module_name: str) -> Optional[str]:
    low = module_name.lower()
    if any(tok in low for tok in LEGACY_OWNER_TOKENS):
        return "legacy_runtime_shim"
    return None


def inspect_aliases(app: Any) -> Dict[str, Any]:
    routes = list(getattr(app, "routes", []) or [])
    records = [_route_record(r, i) for i, r in enumerate(routes)]
    api_records = [r for r in records if _safe_api_path(r.get("path", ""))]

    path_counts: Counter = Counter(r["path"] for r in api_records if r.get("path"))
    method_key_counts: Counter = Counter((r["path"], tuple(r.get("methods", []))) for r in api_records if r.get("path") and r.get("methods"))
    owner_counts: Counter = Counter(r["owner"]["module"] for r in api_records)

    by_group: Dict[str, Dict[str, Any]] = {}
    prefix_records: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    compat_alias_records: List[Dict[str, Any]] = []
    legacy_owner_records: List[Dict[str, Any]] = []

    for r in api_records:
        group, role = _classify_surface(r["path"])
        rr = dict(r)
        rr["group"] = group
        rr["role"] = role
        rr["quarantine"] = "tag_only_preserve_runtime" if role == "compat_alias" else "none"
        owner_type = _legacy_owner_type(r["owner"]["module"])
        if owner_type:
            rr["owner_quarantine"] = owner_type
            if len(legacy_owner_records) < 120:
                legacy_owner_records.append(rr)
        if role == "compat_alias" and len(compat_alias_records) < 120:
            compat_alias_records.append(rr)
        prefix_records[group].append(rr)

    for group, policy in SURFACE_POLICY.items():
        group_records = prefix_records.get(group, [])
        by_group[group] = {
            "canonical_prefixes": policy.get("canonical", []),
            "compat_alias_prefixes": policy.get("compat_alias", []),
            "canonical_route_count": sum(1 for r in group_records if r.get("role") == "canonical"),
            "compat_alias_route_count": sum(1 for r in group_records if r.get("role") == "compat_alias"),
            "owners": dict(Counter(r["owner"]["module"] for r in group_records).most_common(12)),
            "paths_sample": sorted({r["path"] for r in group_records})[:40],
        }

    duplicate_paths = sorted([p for p, c in path_counts.items() if c > 1])
    duplicate_method_keys = [k for k, c in method_key_counts.items() if c > 1]
    required_present = {p: any(r["path"] == p for r in api_records) for p in REQUIRED_HEALTH_PATHS}
    missing_required = [p for p, ok in required_present.items() if not ok]

    return {
        "route_count": len(records),
        "api_route_count": len(api_records),
        "unique_api_path_count": len(path_counts),
        "duplicate_path_count": len(duplicate_paths),
        "duplicate_paths_sample": duplicate_paths[:80],
        "duplicate_method_key_count": len(duplicate_method_keys),
        "duplicate_method_keys_sample": [
            {"path": p, "methods": list(m)} for p, m in duplicate_method_keys[:80]
        ],
        "owners_sample": dict(owner_counts.most_common(25)),
        "by_group": by_group,
        "compat_alias_records_sample": compat_alias_records[:80],
        "legacy_owner_records_sample": legacy_owner_records[:80],
        "required_health_paths": required_present,
        "missing_required_health_paths": missing_required,
    }


def build_status(request: Request) -> Dict[str, Any]:
    audit = inspect_aliases(request.app)
    hard_fail_flags: List[str] = []
    if audit.get("duplicate_method_key_count", 0) > 0:
        hard_fail_flags.append("duplicate_method_keys_still_present")
    if audit.get("missing_required_health_paths"):
        hard_fail_flags.append("required_health_path_missing")

    soft_flags: List[str] = []
    if audit.get("duplicate_path_count", 0) > 0:
        soft_flags.append("duplicate_path_names_exist_method_distinct_or_expected")
    if audit.get("compat_alias_records_sample"):
        soft_flags.append("compat_aliases_tagged_not_removed")
    if audit.get("legacy_owner_records_sample"):
        soft_flags.append("legacy_runtime_shims_tagged_for_later_source_cleanup")

    status = "fail" if hard_fail_flags else "pass"
    payload = {
        "version": VERSION,
        "status": status,
        "mode": "tag_only_legacy_alias_quarantine",
        "ts_ms": _now_ms(),
        "order_mutation": "blocked",
        "source_deletion": "none",
        "runtime_route_change": "none",
        "os_final_approval_required": True,
        "alias_policy": SURFACE_POLICY,
        "audit": audit,
        "hard_fail_flags": hard_fail_flags,
        "risk_flags": soft_flags,
        "quarantine_rules": [
            "canonical routes remain active",
            "compat aliases remain active but are tagged by group and owner",
            "legacy wrapper/overlay owners are recorded for later source cleanup only",
            "no redirect, no route deletion, no order execution change in this stage",
            "settings duplicate path names are not treated as failure when method keys are distinct",
        ],
        "next_safe_actions": [
            "move duplicate sample/mock payloads into shared contract fixtures",
            "only after fixtures pass, collapse wrapper/drop-in chain into one composition root",
            "keep visual harness green before any source-level alias removal",
        ],
        "decision": "legacy_alias_quarantine_v1_pass; next=shared_contract_fixtures_v1" if status == "pass" else "legacy_alias_quarantine_v1_hold; repair missing/duplicate method routes first",
    }
    _safe_write_json(REPORT_PATH, payload)
    return payload


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "status": "pass",
        "mode": "tag_only_legacy_alias_quarantine",
        "order_mutation": "blocked",
        "source_deletion": "none",
        "runtime_route_change": "none",
        "ts_ms": _now_ms(),
    }


@router.get("/status")
def status(request: Request) -> Dict[str, Any]:
    return build_status(request)


@router.get("/report")
def report(request: Request) -> Dict[str, Any]:
    payload = build_status(request)
    payload["report_path"] = str(REPORT_PATH)
    return payload


@router.post("/apply")
def apply_blocked() -> JSONResponse:
    return JSONResponse(status_code=403, content={
        "version": VERSION,
        "status": "blocked",
        "reason": "legacy alias quarantine v1 is tag-only; source deletion/redirect requires later explicit OS approval",
        "order_mutation": "blocked",
        "source_deletion": "none",
        "ts_ms": _now_ms(),
    })
