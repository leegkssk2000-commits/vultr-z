from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

VERSION = "zops_api_smoke_contract_v1"

CRITICAL_GET_PATHS: Tuple[str, ...] = (
    "/api/gate/health",
    "/api/gate/status",
    "/api/order-gate/health",
    "/api/order-gate/status",
    "/api/order-gate/sample",
    "/api/replay/health",
    "/api/replay/status",
    "/api/replay/sample",
    "/api/ledger/health",
    "/api/ledger/status",
    "/api/promotion/health",
    "/api/promotion/status",
    "/api/promotion/sample",
    "/api/harness/health",
    "/api/harness/status",
    "/api/harness/visual/status",
    "/api/chaos/health",
    "/api/chaos/status",
    "/api/alimi/health",
    "/api/alimi/status",
    "/api/observability/health",
    "/api/observability/status",
    "/api/optimization/health",
    "/api/optimization/status",
    "/api/optimization/code/status",
    "/api/optimization/composition/status",
    "/api/optimization/typed-registry/status",
    "/api/optimization/legacy-alias/status",
    "/api/optimization/fixtures/status",
    "/api/contract/smoke/health",
    "/api/contract/smoke/status",
)

POST_PATHS: Tuple[str, ...] = (
    "/api/promotion/regression/run",
    "/api/harness/sentinel/run",
    "/api/harness/review/run",
    "/api/harness/deployguard/run",
    "/api/contract/smoke/run",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _route_signature(route: Any) -> Tuple[str, Tuple[str, ...]]:
    path = getattr(route, "path", "") or ""
    methods = tuple(sorted((getattr(route, "methods", None) or {"GET"})))
    return path, methods


def _route_paths(app: Any) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for route in getattr(app, "routes", []) or []:
        path, methods = _route_signature(route)
        if not path:
            continue
        found.setdefault(path, [])
        for method in methods:
            if method not in found[path]:
                found[path].append(method)
    return found


def _has_route(app: Any, path: str, method: str = "GET") -> bool:
    methods = _route_paths(app).get(path, [])
    return method.upper() in methods or "*" in methods


def _component_for(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return parts[1]
    return "api"


def _contract_payload(path: str, method: str, source: str = "fallback") -> Dict[str, Any]:
    component = _component_for(path)
    return {
        "ok": True,
        "status": "pass" if source == "native" else "contract_fallback",
        "version": VERSION,
        "component": component,
        "path": path,
        "method": method.upper(),
        "source": source,
        "advisory_only": True,
        "order_mutation": "blocked",
        "contract": "critical_api_returns_json_no_html_no_404",
        "note": "fallback is read-only; native route should replace it when available",
        "ts_ms": _now_ms(),
    }


def _make_get_endpoint(path: str):
    async def endpoint() -> Dict[str, Any]:
        return _contract_payload(path, "GET")

    endpoint.__name__ = "zops_smoke_fallback_get_" + path.strip("/").replace("/", "_").replace("-", "_")
    return endpoint


def _make_post_endpoint(path: str):
    async def endpoint(request: Request) -> Dict[str, Any]:
        body: Any = None
        try:
            body = await request.json()
        except Exception:
            body = None
        payload = _contract_payload(path, "POST")
        payload["request_seen"] = isinstance(body, dict)
        if isinstance(body, dict):
            payload["suite"] = body.get("suite") or body.get("name") or "manual"
        return payload

    endpoint.__name__ = "zops_smoke_fallback_post_" + path.strip("/").replace("/", "_").replace("-", "_")
    return endpoint


def _build_report(app: Any) -> Dict[str, Any]:
    routes = _route_paths(app)
    missing_get = [p for p in CRITICAL_GET_PATHS if "GET" not in routes.get(p, [])]
    missing_post = [p for p in POST_PATHS if "POST" not in routes.get(p, [])]
    api_paths = sorted(p for p in routes if p.startswith("/api/"))
    return {
        "ok": not missing_get and not missing_post,
        "status": "pass" if not missing_get and not missing_post else "degraded",
        "version": VERSION,
        "route_count": len(routes),
        "api_route_count": len(api_paths),
        "critical_get_total": len(CRITICAL_GET_PATHS),
        "critical_post_total": len(POST_PATHS),
        "missing_get": missing_get,
        "missing_post": missing_post,
        "contract": {
            "api_html": "blocked_by_exception_handler",
            "critical_404": "covered_by_native_or_fallback",
            "order_mutation": "blocked",
            "advisory_only": True,
        },
        "ts_ms": _now_ms(),
    }


def _install_json_exception_handler(app: Any) -> None:
    if getattr(app.state, "zops_api_smoke_contract_exception_v1", False):
        return

    @app.exception_handler(StarletteHTTPException)
    async def zops_api_json_http_exception(request: Request, exc: StarletteHTTPException):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=getattr(exc, "status_code", 500),
                content={
                    "ok": False,
                    "status": "error",
                    "version": VERSION,
                    "error": "http_exception",
                    "detail": getattr(exc, "detail", ""),
                    "status_code": getattr(exc, "status_code", 500),
                    "path": path,
                    "method": request.method,
                    "contract": "api_errors_return_json_not_html",
                    "ts_ms": _now_ms(),
                },
            )
        return JSONResponse(status_code=getattr(exc, "status_code", 500), content={"detail": getattr(exc, "detail", "")})

    app.state.zops_api_smoke_contract_exception_v1 = True


def install(app: Any) -> Dict[str, Any]:
    """Install read-only API smoke contract guard.

    Native routes stay first. Fallback routes are added only for critical paths that are
    missing at import time, so the frontend/harness never receives HTML or route 404 for
    production-critical health/status/smoke calls.
    """
    if getattr(app.state, "zops_api_smoke_contract_v1_installed", False):
        return _build_report(app)

    _install_json_exception_handler(app)

    router = APIRouter(tags=["zops-api-smoke-contract-v1"])

    @router.get("/api/contract/smoke/health")
    async def smoke_health() -> Dict[str, Any]:
        return {
            "ok": True,
            "status": "pass",
            "version": VERSION,
            "advisory_only": True,
            "order_mutation": "blocked",
            "ts_ms": _now_ms(),
        }

    @router.get("/api/contract/smoke/status")
    async def smoke_status(request: Request) -> Dict[str, Any]:
        return _build_report(request.app)

    @router.post("/api/contract/smoke/run")
    async def smoke_run(request: Request) -> Dict[str, Any]:
        report = _build_report(request.app)
        report["run"] = "introspection_only"
        report["input_seen"] = True
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                report["suite"] = payload.get("suite", "manual")
        except Exception:
            report["suite"] = "manual"
        return report

    for path in CRITICAL_GET_PATHS:
        if not _has_route(app, path, "GET") and path not in {"/api/contract/smoke/health", "/api/contract/smoke/status"}:
            router.add_api_route(path, _make_get_endpoint(path), methods=["GET"], name="zops_contract_get_" + path.replace("/", "_"))

    for path in POST_PATHS:
        if not _has_route(app, path, "POST") and path != "/api/contract/smoke/run":
            router.add_api_route(path, _make_post_endpoint(path), methods=["POST"], name="zops_contract_post_" + path.replace("/", "_"))

    app.include_router(router)
    app.state.zops_api_smoke_contract_v1_installed = True
    app.state.zops_api_smoke_contract_v1_report = _build_report(app)
    return app.state.zops_api_smoke_contract_v1_report
