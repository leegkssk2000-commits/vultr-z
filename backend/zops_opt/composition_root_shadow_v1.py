"""
Z-OS Composition Root Shadow v1
- non-destructive route/composition audit plane
- no existing router removal
- no order mutation
- prepares canonical registry before real consolidation
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

VERSION = "zops_composition_root_shadow_v1"
ROOT = Path(os.environ.get("ZOPS_ROOT", "/home/z/z"))
BACKEND = Path(os.environ.get("ZOPS_BACKEND", str(ROOT / "backend")))
DATA_DIR = Path(os.environ.get("ZOPS_DATA_DIR", str(ROOT / "data")))
OPS_DIR = DATA_DIR / "ops"
REPORT_PATH = OPS_DIR / "composition_root_shadow_v1_report.json"

router = APIRouter(prefix="/api/optimization/composition", tags=["zops-composition-root-shadow-v1"])

CANONICAL_PREFIX_ORDER = [
    "/api/gate",
    "/api/order-gate",
    "/api/replay",
    "/api/ledger",
    "/api/promotion",
    "/api/harness",
    "/api/chaos",
    "/api/alimi",
    "/api/lico",
    "/api/observability",
    "/api/optimization",
]

CANONICAL_ROUTE_GROUPS = {
    "gate": ["/api/gate", "/api/order-gate"],
    "replay": ["/api/replay"],
    "ledger": ["/api/ledger"],
    "promotion": ["/api/promotion"],
    "harness": ["/api/harness"],
    "chaos": ["/api/chaos"],
    "alimi": ["/api/alimi"],
    "lico": ["/api/lico"],
    "observability": ["/api/observability"],
    "optimization": ["/api/optimization"],
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_read(path: Path, limit: int = 900_000) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        with path.open("rb") as f:
            return f.read(limit).decode("utf-8", "ignore")
    except Exception:
        return ""


def _safe_write_json(path: Path, payload: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # composition audit must never break core API
        pass


def _endpoint_owner(route: Any) -> Dict[str, str]:
    endpoint = getattr(route, "endpoint", None)
    module = getattr(endpoint, "__module__", "unknown") if endpoint else "unknown"
    name = getattr(endpoint, "__name__", getattr(route, "name", "unknown")) if endpoint else getattr(route, "name", "unknown")
    return {"module": str(module), "name": str(name)}


def _route_records(app: Any) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for r in getattr(app, "routes", []) or []:
        path = getattr(r, "path", None)
        if not isinstance(path, str):
            continue
        methods = sorted([m for m in getattr(r, "methods", []) or [] if isinstance(m, str)])
        owner = _endpoint_owner(r)
        records.append({
            "path": path,
            "methods": methods,
            "name": getattr(r, "name", owner["name"]),
            "owner": owner,
        })
    return records


def _prefix_for(path: str) -> str:
    for prefix in sorted(CANONICAL_PREFIX_ORDER, key=len, reverse=True):
        if path.startswith(prefix):
            return prefix
    if path.startswith("/api/v1"):
        return "/api/v1"
    if path == "/health":
        return "/health"
    if path.startswith("/api"):
        parts = path.strip("/").split("/")
        return "/" + "/".join(parts[:2]) if len(parts) >= 2 else "/api"
    return "other"


def _route_snapshot(app: Any) -> Dict[str, Any]:
    records = _route_records(app)
    paths = [r["path"] for r in records]
    counts = Counter(paths)
    duplicates = sorted([p for p, c in counts.items() if c > 1])
    by_prefix: Dict[str, int] = defaultdict(int)
    owners_by_prefix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    duplicate_detail: List[Dict[str, Any]] = []
    for rec in records:
        prefix = _prefix_for(rec["path"])
        by_prefix[prefix] += 1
        owners_by_prefix[prefix][rec["owner"]["module"]] += 1
    for path in duplicates[:80]:
        entries = [r for r in records if r["path"] == path]
        duplicate_detail.append({
            "path": path,
            "count": len(entries),
            "owners": [e["owner"] for e in entries[:12]],
            "action": "keep_first_runtime_route; migrate later into typed registry; do_not_delete_in_shadow_pass",
        })
    coverage = {prefix: any(p.startswith(prefix) for p in paths) for prefix in CANONICAL_PREFIX_ORDER}
    return {
        "route_count": len(paths),
        "unique_route_count": len(set(paths)),
        "duplicate_path_count": len(duplicates),
        "duplicate_paths_sample": duplicates[:40],
        "duplicate_detail_sample": duplicate_detail[:25],
        "by_prefix": dict(sorted(by_prefix.items())),
        "owners_by_prefix_sample": {k: dict(sorted(v.items(), key=lambda kv: kv[1], reverse=True)[:8]) for k, v in sorted(owners_by_prefix.items())},
        "coverage": coverage,
        "missing_prefixes": [k for k, v in coverage.items() if not v],
    }


def _source_snapshot() -> Dict[str, Any]:
    main = BACKEND / "main.py"
    txt = _safe_read(main, limit=2_500_000)
    py_files = 0
    try:
        py_files = sum(1 for p in BACKEND.rglob("*.py") if p.is_file())
    except Exception:
        pass
    zops_modules: List[str] = []
    try:
        zops_modules = sorted(str(p.relative_to(BACKEND)) for p in BACKEND.rglob("zops*.py") if p.is_file())[:160]
    except Exception:
        pass
    return {
        "main_py_exists": main.exists(),
        "main_include_router_lines": txt.count("include_router("),
        "main_append_markers": txt.count("ZOPS_"),
        "main_add_api_route_lines": txt.count("add_api_route("),
        "backend_py_files": py_files,
        "zops_module_sample": zops_modules[:80],
    }


def _registry_plan() -> Dict[str, Any]:
    return {
        "mode": "shadow_registry_no_behavior_change",
        "canonical_groups": CANONICAL_ROUTE_GROUPS,
        "consolidation_rules": [
            "single composition root owns router mounting order",
            "typed router modules expose router + health/status/sample where applicable",
            "legacy aliases remain until duplicate route count is reduced by staged migration",
            "no order mutation; OS final approval remains required",
            "public 404/HTML leakage stays blocked by JSON contract guard",
            "remove DOM/fixed overlay shims only after visual harness stays green",
        ],
        "next_safe_actions": [
            "generate route owner map",
            "select canonical owner per duplicate path",
            "convert duplicate aliases into redirect/compat layer",
            "move mock/sample fixtures into shared contract fixture module",
            "lazy-load Log/Replay/Proof panels; keep trading path synchronous",
        ],
    }


def build_status(request: Request) -> Dict[str, Any]:
    route = _route_snapshot(request.app)
    source = _source_snapshot()
    risk_flags: List[str] = []
    if route["missing_prefixes"]:
        risk_flags.append("missing_prefixes")
    if route["duplicate_path_count"]:
        risk_flags.append("duplicate_routes_pending_consolidation")
    if source["main_include_router_lines"] > 35:
        risk_flags.append("main_py_router_sprawl")
    status = "pass" if not route["missing_prefixes"] else "warn"
    payload = {
        "version": VERSION,
        "status": status,
        "mode": "shadow_composition_root_audit_only",
        "ts_ms": _now_ms(),
        "advisory_only": True,
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "route": route,
        "source": source,
        "risk_flags": risk_flags,
        "registry_plan": _registry_plan(),
        "decision": "composition_root_shadow_ready; next=typed_registry_migration_when_visual_and_route_smoke_stay_green",
    }
    _safe_write_json(REPORT_PATH, payload)
    return payload


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "status": "pass",
        "mode": "shadow_composition_root_audit_only",
        "advisory_only": True,
        "order_mutation": "blocked",
        "ts_ms": _now_ms(),
    }


@router.get("/status")
def status(request: Request) -> Dict[str, Any]:
    return build_status(request)


@router.get("/registry")
def registry() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "status": "pass",
        "ts_ms": _now_ms(),
        **_registry_plan(),
    }


@router.get("/report")
def report(request: Request) -> Dict[str, Any]:
    payload = build_status(request)
    payload["report_path"] = str(REPORT_PATH)
    return payload


@router.post("/apply")
def apply_blocked() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "version": VERSION,
            "status": "blocked",
            "reason": "shadow composition root is audit-only; destructive consolidation requires dedicated migration patch with rollback",
            "order_mutation": "blocked",
            "ts_ms": _now_ms(),
        },
    )
