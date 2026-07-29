"""
Z-OS Safe Code Optimization v2
- audit-only/runtime-safe optimization plane
- no order mutation
- no destructive file deletion
- exposes live counts, route coverage, and optimization plan
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

VERSION = "zops_safe_code_optimization_v2"
ROOT = Path(os.environ.get("ZOPS_ROOT", "/home/z/z"))
BACKEND = Path(os.environ.get("ZOPS_BACKEND", str(ROOT / "backend")))
FRONTEND = Path(os.environ.get("ZOPS_FRONTEND", str(ROOT / "frontend" / "z-os-pwa")))
APP_TARGET = Path(os.environ.get("ZOPS_APP_TARGET", "/var/www/z-os-app"))
DATA_DIR = Path(os.environ.get("ZOPS_DATA_DIR", str(ROOT / "data")))

router = APIRouter(prefix="/api/optimization/code", tags=["zops-code-optimization-v2"])

REQUIRED_PREFIXES = [
    "/api/gate",
    "/api/order-gate",
    "/api/replay",
    "/api/ledger",
    "/api/promotion",
    "/api/harness",
    "/api/chaos",
    "/api/alimi",
    "/api/observability",
    "/api/optimization",
]

RISKY_PATTERNS = [
    "app = FastAPI(",
    "FastAPI(",
    "include_router(",
    "add_api_route(",
    "@app.",
    "@router.",
    "zops_ui_residue_cleanup",
    "document.body.appendChild",
    "position:fixed",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_read(path: Path, limit: int = 5_000_000) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        if path.stat().st_size > limit:
            with path.open("rb") as f:
                return f.read(limit).decode("utf-8", "ignore")
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _file_hash(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return "na"


def _count_files(base: Path, suffix: str) -> int:
    try:
        return sum(1 for _ in base.rglob(f"*{suffix}") if _.is_file())
    except Exception:
        return 0


def _grep_count(base: Path, pattern: str, suffixes: tuple[str, ...]) -> int:
    total = 0
    try:
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in suffixes:
                continue
            txt = _safe_read(p, limit=700_000)
            total += txt.count(pattern)
    except Exception:
        pass
    return total


def _route_snapshot(app: Any) -> Dict[str, Any]:
    paths: List[str] = []
    for r in getattr(app, "routes", []) or []:
        p = getattr(r, "path", None)
        if isinstance(p, str):
            paths.append(p)
    uniq = sorted(set(paths))
    coverage = {prefix: any(p.startswith(prefix) for p in uniq) for prefix in REQUIRED_PREFIXES}
    duplicates = sorted({p for p in paths if paths.count(p) > 1})[:50]
    return {
        "route_count": len(paths),
        "unique_route_count": len(uniq),
        "duplicate_path_count": len(duplicates),
        "duplicate_paths_sample": duplicates,
        "coverage": coverage,
        "missing_prefixes": [k for k, v in coverage.items() if not v],
    }


def _static_snapshot() -> Dict[str, Any]:
    index = APP_TARGET / "index.html"
    html = _safe_read(index, limit=1_000_000)
    assets_dir = APP_TARGET / "assets"
    js_kb = 0
    css_kb = 0
    try:
        for p in assets_dir.glob("*.js"):
            js_kb += p.stat().st_size // 1024
        for p in assets_dir.glob("*.css"):
            css_kb += p.stat().st_size // 1024
    except Exception:
        pass
    return {
        "app_target": str(APP_TARGET),
        "index_exists": index.exists(),
        "index_sha16": _file_hash(index) if index.exists() else "missing",
        "guard_asset_present": "zops_code_opt_guard_v2.js" in html,
        "residue_cleanup_refs": html.count("zops_ui_residue_cleanup"),
        "code_opt_refs": html.count("zops_code_opt_guard_v2"),
        "dist_js_kb": js_kb,
        "dist_css_kb": css_kb,
    }


def _source_snapshot() -> Dict[str, Any]:
    backend_files = _count_files(BACKEND, ".py")
    frontend_tsx = _count_files(FRONTEND, ".tsx")
    frontend_ts = _count_files(FRONTEND, ".ts")
    frontend_js = _count_files(FRONTEND, ".js")
    return {
        "backend_py_files": backend_files,
        "frontend_tsx_files": frontend_tsx,
        "frontend_ts_files": frontend_ts,
        "frontend_js_files": frontend_js,
        "include_router_lines": _grep_count(BACKEND, "include_router(", (".py",)),
        "add_api_route_lines": _grep_count(BACKEND, "add_api_route(", (".py",)),
        "dom_append_lines": _grep_count(FRONTEND, "appendChild", (".ts", ".tsx", ".js", ".jsx")),
        "fixed_position_lines": _grep_count(FRONTEND, "position: fixed", (".ts", ".tsx", ".css", ".js", ".jsx")),
    }


def build_status(request: Request) -> Dict[str, Any]:
    route = _route_snapshot(request.app)
    static = _static_snapshot()
    source = _source_snapshot()
    risk_flags: List[str] = []
    if route["duplicate_path_count"] > 0:
        risk_flags.append("duplicate_routes")
    if route["missing_prefixes"]:
        risk_flags.append("missing_api_prefixes")
    if static["residue_cleanup_refs"] > 1:
        risk_flags.append("duplicate_static_residue_assets")
    if static["dist_js_kb"] > 650:
        risk_flags.append("frontend_bundle_large")
    if source["include_router_lines"] > 350:
        risk_flags.append("router_mount_sprawl")
    return {
        "version": VERSION,
        "status": "pass" if not route["missing_prefixes"] else "warn",
        "mode": "audit_plus_safe_runtime_guard",
        "ts_ms": _now_ms(),
        "order_mutation": "blocked",
        "advisory_only": True,
        "route": route,
        "static": static,
        "source": source,
        "risk_flags": risk_flags,
        "optimization_order": [
            "1. keep runtime-safe guard assets; hide bottom-left residue before React hydration",
            "2. collapse wrapper/drop-in chain into one composition root only after smoke coverage is green",
            "3. move all API overlays into typed router modules with single registry",
            "4. dedupe sample/mock payload generators into shared contract fixtures",
            "5. lazy-load log/proof panels; keep trading path synchronous and small",
            "6. enforce every /api/{gate,order-gate,replay,ledger,promotion,harness,chaos,alimi,observability} endpoint returns JSON, never HTML/404",
            "7. keep OS final approval/order mutation blocked until live gate contract passes",
        ],
        "decision": "safe_code_optimization_pass; next=composition_root_consolidation_when_stable",
    }


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "status": "pass",
        "advisory_only": True,
        "order_mutation": "blocked",
        "ts_ms": _now_ms(),
    }


@router.get("/status")
def status(request: Request) -> Dict[str, Any]:
    return build_status(request)


@router.get("/audit")
def audit(request: Request) -> Dict[str, Any]:
    s = build_status(request)
    s["audit_scope"] = {
        "root": str(ROOT),
        "backend": str(BACKEND),
        "frontend": str(FRONTEND),
        "app_target": str(APP_TARGET),
    }
    s["contract"] = [
        "no deletion of existing modules in this pass",
        "no order mutation",
        "no API route removal",
        "compile check before restart",
        "rollback on startup failure",
    ]
    return s


@router.post("/apply")
def apply_blocked() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "version": VERSION,
            "status": "blocked",
            "reason": "optimization endpoint is audit-only; use patch script with backup/compile/restart gates",
            "order_mutation": "blocked",
            "ts_ms": _now_ms(),
        },
    )


@router.post("/smoke")
def smoke(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "version": VERSION,
        "status": "pass",
        "payload_seen": bool(payload),
        "mutation": "blocked",
        "ts_ms": _now_ms(),
    }
