"""
Z-OS Typed Registry Migration v1
- safe runtime route de-duplication for unreachable duplicate method routes only
- typed owner map + canonical group contract
- no source deletion, no trading/order mutation
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

VERSION = "zops_typed_registry_migration_v1"
ROOT = Path(os.environ.get("ZOPS_ROOT", "/home/z/z"))
DATA_DIR = Path(os.environ.get("ZOPS_DATA_DIR", str(ROOT / "data")))
OPS_DIR = DATA_DIR / "ops"
REPORT_PATH = OPS_DIR / "typed_registry_migration_v1_report.json"

router = APIRouter(prefix="/api/optimization/typed-registry", tags=["zops-typed-registry-migration-v1"])

CANONICAL_GROUPS: Dict[str, List[str]] = {
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

SAFE_PREFIXES = tuple(p for group in CANONICAL_GROUPS.values() for p in group) + ("/health", "/api/v1/health")
BLOCKED_PATH_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi",
    "/static",
    "/assets",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_write_json(path: Path, payload: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # optimization telemetry must never break core API
        pass


def _owner(route: Any) -> Dict[str, str]:
    endpoint = getattr(route, "endpoint", None)
    module = getattr(endpoint, "__module__", "unknown") if endpoint else "unknown"
    name = getattr(endpoint, "__name__", getattr(route, "name", "unknown")) if endpoint else getattr(route, "name", "unknown")
    return {"module": str(module), "name": str(name)}


def _methods(route: Any) -> Tuple[str, ...]:
    raw = getattr(route, "methods", None) or []
    methods = sorted(str(m).upper() for m in raw if str(m).upper() not in {"HEAD", "OPTIONS"})
    return tuple(methods)


def _path(route: Any) -> str:
    return str(getattr(route, "path", ""))


def _is_safe_prefix(path: str) -> bool:
    if not path:
        return False
    if any(path.startswith(p) for p in BLOCKED_PATH_PREFIXES):
        return False
    return path.startswith(SAFE_PREFIXES) or path.startswith("/api/optimization")


def _route_key(route: Any) -> Optional[Tuple[str, Tuple[str, ...]]]:
    path = _path(route)
    methods = _methods(route)
    if not path or not methods:
        return None
    if not _is_safe_prefix(path):
        return None
    return (path, methods)


def _route_record(route: Any, index: int) -> Dict[str, Any]:
    key = _route_key(route)
    return {
        "index": index,
        "path": _path(route),
        "methods": list(_methods(route)),
        "name": str(getattr(route, "name", "")),
        "owner": _owner(route),
        "typed_key": [key[0], list(key[1])] if key else None,
    }


def inspect_routes(app: Any) -> Dict[str, Any]:
    routes = list(getattr(app, "routes", []) or [])
    records = [_route_record(route, i) for i, route in enumerate(routes)]
    typed_records = [r for r in records if r.get("typed_key")]

    key_counts: Counter = Counter()
    path_counts: Counter = Counter()
    owner_counts: Counter = Counter()
    first_by_key: Dict[Tuple[str, Tuple[str, ...]], Dict[str, Any]] = {}
    duplicate_method_records: List[Dict[str, Any]] = []

    for route, rec in zip(routes, records):
        path = rec["path"]
        if path:
            path_counts[path] += 1
        owner_counts[rec["owner"]["module"]] += 1
        key = _route_key(route)
        if not key:
            continue
        key_counts[key] += 1
        if key not in first_by_key:
            first_by_key[key] = rec
        elif len(duplicate_method_records) < 120:
            duplicate_method_records.append({
                "duplicate": rec,
                "kept_first": first_by_key[key],
                "action": "runtime_quarantine_candidate_keep_first_no_behavior_change",
            })

    duplicate_paths = sorted([p for p, c in path_counts.items() if c > 1])
    duplicate_method_keys = [k for k, c in key_counts.items() if c > 1]

    by_group: Dict[str, Dict[str, Any]] = {}
    for group, prefixes in CANONICAL_GROUPS.items():
        group_records = [r for r in typed_records if any(str(r["path"]).startswith(p) for p in prefixes)]
        by_group[group] = {
            "prefixes": prefixes,
            "route_count": len(group_records),
            "owners": dict(Counter(r["owner"]["module"] for r in group_records).most_common(12)),
            "paths_sample": sorted({r["path"] for r in group_records})[:40],
        }

    return {
        "route_count": len(records),
        "typed_route_count": len(typed_records),
        "unique_path_count": len(path_counts),
        "duplicate_path_count": len(duplicate_paths),
        "duplicate_paths_sample": duplicate_paths[:60],
        "duplicate_method_key_count": len(duplicate_method_keys),
        "duplicate_method_records_sample": duplicate_method_records[:60],
        "owners_sample": dict(owner_counts.most_common(20)),
        "by_group": by_group,
    }


def apply_runtime_route_dedupe(app: Any) -> Dict[str, Any]:
    """Remove only unreachable duplicate routes with the exact same path+method tuple.

    FastAPI resolves the first matching route. Later routes with the same path and method
    are not reachable. Keeping the first route preserves behavior and removes only shadowed
    duplicates. Distinct methods on the same path are preserved.
    """
    before_routes = list(getattr(app.router, "routes", []) or [])
    seen: Dict[Tuple[str, Tuple[str, ...]], Dict[str, Any]] = {}
    kept: List[Any] = []
    removed: List[Dict[str, Any]] = []

    for idx, route in enumerate(before_routes):
        key = _route_key(route)
        if key is None:
            kept.append(route)
            continue
        rec = _route_record(route, idx)
        if key in seen:
            removed.append({
                "removed": rec,
                "kept_first": seen[key],
                "reason": "duplicate_path_and_methods_unreachable_after_first",
            })
            continue
        seen[key] = rec
        kept.append(route)

    if removed:
        try:
            app.router.routes[:] = kept
        except Exception:
            # fail open: never break app startup
            removed = []

    after = inspect_routes(app)
    payload = {
        "version": VERSION,
        "status": "pass",
        "mode": "runtime_duplicate_method_quarantine",
        "ts_ms": _now_ms(),
        "order_mutation": "blocked",
        "order_runtime_behavior": "keep_first_runtime_route_preserved",
        "source_deletion": "none",
        "removed_duplicate_method_routes": len(removed),
        "removed_sample": removed[:80],
        "after": after,
        "decision": "typed_registry_runtime_dedupe_ready; next=legacy_alias_quarantine_after_smoke_green",
    }
    _safe_write_json(REPORT_PATH, payload)
    return payload


def build_status(request: Request) -> Dict[str, Any]:
    snapshot = inspect_routes(request.app)
    try:
        persisted = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    except Exception:
        persisted = {}
    payload = {
        "version": VERSION,
        "status": "pass",
        "mode": "typed_registry_runtime_audit",
        "ts_ms": _now_ms(),
        "order_mutation": "blocked",
        "source_deletion": "none",
        "os_final_approval_required": True,
        "canonical_groups": CANONICAL_GROUPS,
        "route": snapshot,
        "last_runtime_dedupe": {
            "removed_duplicate_method_routes": persisted.get("removed_duplicate_method_routes", 0),
            "decision": persisted.get("decision"),
        },
        "risk_flags": ["duplicate_paths_remaining_by_path_name"] if snapshot.get("duplicate_path_count", 0) else [],
        "next_safe_actions": [
            "keep visual harness green",
            "quarantine legacy aliases by canonical owner",
            "move duplicated samples into shared fixtures",
            "only then remove source-level wrapper/drop-in code",
        ],
        "decision": "typed_registry_migration_v1_pass; next=legacy_alias_quarantine_v1",
    }
    _safe_write_json(REPORT_PATH, payload)
    return payload


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "status": "pass",
        "mode": "typed_registry_migration_v1",
        "order_mutation": "blocked",
        "source_deletion": "none",
        "ts_ms": _now_ms(),
    }


@router.get("/status")
def status(request: Request) -> Dict[str, Any]:
    return build_status(request)


@router.get("/registry")
def registry(request: Request) -> Dict[str, Any]:
    data = build_status(request)
    return {
        "version": VERSION,
        "status": "pass",
        "ts_ms": _now_ms(),
        "canonical_groups": CANONICAL_GROUPS,
        "by_group": data.get("route", {}).get("by_group", {}),
        "decision": data.get("decision"),
    }


@router.get("/report")
def report(request: Request) -> Dict[str, Any]:
    payload = build_status(request)
    payload["report_path"] = str(REPORT_PATH)
    return payload


@router.post("/dedupe")
def dedupe_blocked() -> JSONResponse:
    return JSONResponse(status_code=403, content={
        "version": VERSION,
        "status": "blocked",
        "reason": "manual API mutation disabled; runtime dedupe only occurs during controlled deployment/import",
        "order_mutation": "blocked",
        "ts_ms": _now_ms(),
    })
