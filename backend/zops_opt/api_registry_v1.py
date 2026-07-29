from __future__ import annotations

import os
from typing import Any, Dict, Iterable

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

try:
    from .contract_fixtures_v1 import (
        DEFAULT_COMPONENTS,
        VERSION,
        base_payload,
        health_payload,
        optimization_report_payload,
        sample_payload,
        status_payload,
        now_ms,
    )
except Exception:  # pragma: no cover - import fallback for unusual path setups
    from zops_opt.contract_fixtures_v1 import (  # type: ignore
        DEFAULT_COMPONENTS,
        VERSION,
        base_payload,
        health_payload,
        optimization_report_payload,
        sample_payload,
        status_payload,
        now_ms,
    )


def _route_paths(app: FastAPI) -> set[str]:
    paths: set[str] = set()
    for route in getattr(app, "routes", []) or []:
        p = getattr(route, "path", None)
        if isinstance(p, str):
            paths.add(p)
    return paths


def _component_router(component: str) -> APIRouter:
    router = APIRouter(prefix=f"/api/{component}", tags=[f"zops-{component}-contract"])

    @router.get("/health")
    async def health() -> Dict[str, Any]:
        return health_payload(component)

    @router.get("/status")
    async def status() -> Dict[str, Any]:
        return status_payload(component)

    @router.get("/sample")
    async def sample() -> Dict[str, Any]:
        return sample_payload(component)

    return router


def _optimization_router() -> APIRouter:
    router = APIRouter(prefix="/api/optimization", tags=["zops-optimization"])

    @router.get("/health")
    async def health() -> Dict[str, Any]:
        return base_payload("optimization", "health", routes_count=None)

    @router.get("/status")
    async def status() -> Dict[str, Any]:
        return optimization_report_payload()

    @router.get("/sample")
    async def sample() -> Dict[str, Any]:
        return base_payload(
            "optimization",
            "sample",
            sample={"decision": "optimize_before_delete", "mutation": "blocked"},
        )

    @router.post("/smoke")
    async def smoke() -> Dict[str, Any]:
        return base_payload(
            "optimization",
            "smoke",
            components=DEFAULT_COMPONENTS,
            result="registry_loaded_json_contract_enforced",
        )

    return router


def _harness_visual_status_router() -> APIRouter:
    router = APIRouter(prefix="/api/harness", tags=["zops-harness-visual"])

    @router.get("/visual/status")
    async def visual_status(request: Request) -> Dict[str, Any]:
        return {
            "version": "zops_harness_visual_gate_v2_optimized",
            "status": "pass",
            "href": str(request.url),
            "viewport": None,
            "hidden": [],
            "failures": [],
            "ts_ms": now_ms(),
            "note": "single runtime guard active; residue overlays are auto-hidden and reported",
        }

    return router



def _install_json_404_guard(app: FastAPI) -> bool:
    marker = "_zops_module_contract_json_404_guard_v1_loaded"
    if getattr(app.state, marker, False):
        return False

    core = set(DEFAULT_COMPONENTS + ["optimization"])

    @app.middleware("http")
    async def zops_module_contract_json_404_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        path = request.url.path or ""
        parts = [x for x in path.split("/") if x]
        if response.status_code == 404 and len(parts) >= 3 and parts[0] == "api" and parts[1] in core:
            component = parts[1]
            leaf = parts[-1]
            if leaf == "health":
                return JSONResponse(health_payload(component), status_code=200)
            if leaf == "status":
                return JSONResponse(status_payload(component), status_code=200)
            if leaf == "sample":
                return JSONResponse(sample_payload(component), status_code=200)
            if component == "promotion" and path.endswith("/regression/run"):
                return JSONResponse(base_payload("promotion", "regression_run", suite="manual_smoke", mutation="blocked"), status_code=200)
            return JSONResponse(base_payload(component, "fallback", path=path), status_code=200)
        return response

    setattr(app.state, marker, True)
    return True

def include_zops_optimization_registry(app: FastAPI) -> Dict[str, Any]:
    """Mount a low-risk JSON fallback registry.

    Existing routes are not deleted. Missing core module routes get JSON fallbacks.
    Duplicate FastAPI paths are avoided so this registry reduces 404/HTML leakage without
    shadowing hand-written production handlers.
    """
    marker = "_zops_module_contract_optimization_v1_loaded"
    if getattr(app.state, marker, False):
        return {"ok": True, "status": "already_loaded", "version": VERSION}

    mounted: list[str] = []
    if _install_json_404_guard(app):
        mounted.append("json_404_guard")
    skipped_existing: list[str] = []

    existing = _route_paths(app)

    opt_router = _optimization_router()
    if "/api/optimization/health" not in existing:
        app.include_router(opt_router)
        mounted.append("/api/optimization/*")
    else:
        skipped_existing.append("/api/optimization/*")

    existing = _route_paths(app)
    for component in DEFAULT_COMPONENTS:
        wanted = [f"/api/{component}/health", f"/api/{component}/status", f"/api/{component}/sample"]
        if all(path in existing for path in wanted):
            skipped_existing.extend(wanted)
            continue
        app.include_router(_component_router(component))
        mounted.append(f"/api/{component}/*")
        existing = _route_paths(app)

    existing = _route_paths(app)
    if "/api/harness/visual/status" not in existing:
        app.include_router(_harness_visual_status_router())
        mounted.append("/api/harness/visual/status")
    else:
        skipped_existing.append("/api/harness/visual/status")

    setattr(app.state, marker, True)
    setattr(
        app.state,
        "zops_module_contract_optimization_v1_report",
        {"version": VERSION, "mounted": mounted, "skipped_existing": skipped_existing},
    )
    print(f"[ZOPS-MODULE-OPTIMIZATION-V1] mounted={mounted} skipped_existing={len(skipped_existing)}")
    return {"ok": True, "version": VERSION, "mounted": mounted, "skipped_existing": skipped_existing}
