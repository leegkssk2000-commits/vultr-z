# ZOPS_HARNESS_CONTROL_PLANE_V2
# Sentinel + Review + DeployGuard control plane. Monitoring/review only. No exchange/order mutation.
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from fastapi import APIRouter, Body, Query
except Exception:  # pragma: no cover
    APIRouter = None  # type: ignore
    Body = None  # type: ignore
    Query = None  # type: ignore

CONTRACT_VERSION = "harness_control_plane_v2"
AUTHORITY = "monitoring_only"
ORDER_MUTATION = "blocked"
PHASE = "phase-8-harness-hardening-v2"
ROOT = Path(os.environ.get("ZOPS_ROOT", "/home/z/z"))
DATA_DIR = Path(os.environ.get("ZOPS_DATA_DIR", str(ROOT / "data")))
HARNESS_DIR = DATA_DIR / "harness"
ALIMI_OUTBOX = Path(os.environ.get("ZOPS_ALIMI_OUTBOX", str(DATA_DIR / "alimi" / "outbox.jsonl")))
CONFIG_PATH = HARNESS_DIR / "harness_control_plane_v2_config.json"
EVENTS_PATH = HARNESS_DIR / "harness_events.jsonl"
RUNS_PATH = HARNESS_DIR / "harness_runs.jsonl"
REVIEWS_PATH = HARNESS_DIR / "review_packs.jsonl"
DEPLOYGUARD_PATH = HARNESS_DIR / "deployguard_runs.jsonl"

ACTIONS = ["reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"]
DEFAULT_CONFIG: Dict[str, Any] = {
    "contract_version": CONTRACT_VERSION,
    "authority": AUTHORITY,
    "order_mutation": ORDER_MUTATION,
    "os_final_approval_required": True,
    "violation_only_alimi": True,
    "bundle_minutes": 10,
    "quiet_hours_berlin": "01:00-07:00 critical_only",
    "local_base_url": "http://127.0.0.1:8000",
    "public_base_url": "https://app.z-os.vip",
    "timeout_ms": 900,
    "required_local_routes": [
        "/api/order-gate/health",
        "/api/replay/health",
        "/api/ledger/health",
        "/api/promotion/health"
    ],
    "optional_local_routes": [
        "/api/order-gate/status",
        "/api/replay/status",
        "/api/ledger/status",
        "/api/promotion/status",
        "/api/promotion/regression/run"
    ],
    "required_paths": [
        "/home/z/z/backend",
        "/home/z/z/frontend/z-os-pwa",
        "/home/z/z/data",
        "/home/z/z/data/alimi"
    ],
    "stale_limit_ms": 60000,
    "max_route_latency_ms": 1200,
    "max_route_404_count": 0,
    "max_route_5xx_count": 0,
    "deployguard_requires_build": True,
    "deployguard_requires_frontend_dist": True,
    "review_last_event_count": 20,
    "severity_order": {"ok": 0, "m": 1, "M": 2, "C": 3},
    "contract_notes": [
        "Sentinel catches backend/api/bot/data/route failures.",
        "Review creates evidence/replay packs for human-in-the-loop decisions.",
        "DeployGuard validates deploy readiness and rollback posture.",
        "Harness never sends orders and never mutates exchange state."
    ],
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ensure() -> None:
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    ALIMI_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _config() -> Dict[str, Any]:
    _ensure()
    cfg = dict(DEFAULT_CONFIG)
    user = _read_json(CONFIG_PATH, {})
    if isinstance(user, dict):
        cfg.update(user)
    cfg["authority"] = AUTHORITY
    cfg["order_mutation"] = ORDER_MUTATION
    cfg["os_final_approval_required"] = True
    return cfg


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> Dict[str, Any]:
    _ensure()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(obj)
    row.setdefault("ts_ms", _now_ms())
    path.open("a", encoding="utf-8").write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def _tail_jsonl(path: Path, n: int = 20) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, n):]
        for line in lines:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except Exception:
        return rows
    return rows


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.open("r", encoding="utf-8") if line.strip())
    except Exception:
        return 0


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _http_json(method: str, url: str, payload: Optional[Dict[str, Any]] = None, timeout_ms: int = 900) -> Dict[str, Any]:
    started = time.time()
    body: Optional[bytes] = None
    headers = {"accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=max(timeout_ms / 1000.0, 0.1)) as resp:
            raw = resp.read(8192).decode("utf-8", errors="replace")
            latency = int((time.time() - started) * 1000)
            parsed: Any
            try:
                parsed = json.loads(raw) if raw else None
            except Exception:
                parsed = {"raw": raw[:500]}
            return {"ok": 200 <= int(resp.status) < 300, "status": int(resp.status), "latency_ms": latency, "json": parsed}
    except urllib.error.HTTPError as e:
        latency = int((time.time() - started) * 1000)
        try:
            raw = e.read(4096).decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        return {"ok": False, "status": int(getattr(e, "code", 0) or 0), "latency_ms": latency, "error": raw[:500] or repr(e)}
    except Exception as e:
        latency = int((time.time() - started) * 1000)
        return {"ok": False, "status": 0, "latency_ms": latency, "error": repr(e)}


def _path_check(path_str: str) -> Dict[str, Any]:
    p = Path(path_str)
    exists = p.exists()
    writable = False
    if exists:
        try:
            target = p if p.is_dir() else p.parent
            target.mkdir(parents=True, exist_ok=True)
            probe = target / f".zops_harness_write_probe_{_now_ms()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable = True
        except Exception:
            writable = False
    return {"path": path_str, "exists": exists, "writable": writable, "ok": exists and (writable or not p.is_dir())}


def _sev_max(items: List[Dict[str, Any]], cfg: Dict[str, Any]) -> str:
    order = cfg.get("severity_order") or DEFAULT_CONFIG["severity_order"]
    best = "ok"
    for item in items:
        sev = str(item.get("sev") or item.get("severity") or "ok")
        if int(order.get(sev, 0)) > int(order.get(best, 0)):
            best = sev
    return best


def run_sentinel(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = _config()
    payload = payload or {}
    local_base = str(payload.get("local_base_url") or cfg.get("local_base_url") or "http://127.0.0.1:8000").rstrip("/")
    timeout_ms = int(payload.get("timeout_ms") or cfg.get("timeout_ms") or 900)
    checks: List[Dict[str, Any]] = []

    # Basic writable/data path checks.
    for p in cfg.get("required_paths", []):
        pc = _path_check(str(p))
        checks.append({"domain": "path", "name": str(p), "ok": pc["ok"], "sev": "C" if not pc["ok"] else "ok", "action": "hold" if not pc["ok"] else "hold", "detail": pc})

    # Required local route checks.
    for route in cfg.get("required_local_routes", []):
        result = _http_json("GET", f"{local_base}{route}", timeout_ms=timeout_ms)
        status = int(result.get("status") or 0)
        latency = int(result.get("latency_ms") or 0)
        ok = bool(result.get("ok")) and latency <= int(cfg.get("max_route_latency_ms", 1200))
        if status == 404:
            sev, action, metric = "C", "route_change", "route_404"
        elif status >= 500 or status == 0:
            sev, action, metric = "C", "hold", "route_unreachable_or_5xx"
        elif latency > int(cfg.get("max_route_latency_ms", 1200)):
            sev, action, metric = "M", "hold", "route_latency_ms"
        else:
            sev, action, metric = "ok", "hold", "route_ok"
        checks.append({"domain": "route", "name": route, "ok": ok, "sev": sev, "action": action, "metric": metric, "value": status, "latency_ms": latency, "detail": result})

    # Optional routes are visibility only, not a hard fail.
    optional: List[Dict[str, Any]] = []
    for route in cfg.get("optional_local_routes", []):
        method = "POST" if route.endswith("/run") else "GET"
        body = {"suite": "harness_optional_probe"} if method == "POST" else None
        result = _http_json(method, f"{local_base}{route}", payload=body, timeout_ms=timeout_ms)
        optional.append({"route": route, "ok": bool(result.get("ok")), "status": result.get("status"), "latency_ms": result.get("latency_ms")})

    violations = [c for c in checks if not c.get("ok")]
    sev = _sev_max(violations, cfg) if violations else "ok"
    action = "hold" if violations else "hold"
    if any(v.get("action") == "route_change" for v in violations):
        action = "route_change"
    if any(v.get("sev") == "C" and v.get("metric") != "route_404" for v in violations):
        action = "hold"

    run = {
        "run_id": f"harness_sentinel_{_now_ms()}",
        "contract_version": CONTRACT_VERSION,
        "phase": PHASE,
        "suite": str(payload.get("suite") or "sentinel_manual"),
        "ok": not violations,
        "action": action,
        "sev": sev,
        "checks": checks,
        "optional": optional,
        "violation_count": len(violations),
        "violations": violations,
        "authority": AUTHORITY,
        "order_mutation": ORDER_MUTATION,
        "os_final_approval_required": True,
        "ts_ms": _now_ms(),
    }
    run["evidence_hash"] = _hash(run)
    _append_jsonl(RUNS_PATH, run)
    _append_jsonl(EVENTS_PATH, {"type": "sentinel", "run_id": run["run_id"], "ok": run["ok"], "sev": sev, "action": action, "evidence_hash": run["evidence_hash"]})

    # Violation-only Alimi outbox.
    if violations and bool(cfg.get("violation_only_alimi", True)):
        top = violations[0]
        _append_jsonl(ALIMI_OUTBOX, {
            "type": "harness_sentinel",
            "symbol": "SYSTEM",
            "strategy": "harness",
            "metric": f"{top.get('name')} {top.get('metric')} v>limit",
            "action": action,
            "sev": sev,
            "src": "backend:/api/harness/sentinel/run",
            "run_id": run["run_id"],
            "evidence_hash": run["evidence_hash"],
            "bundle_key": "SYSTEM/harness",
        })
    return run


def run_review(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = _config()
    payload = payload or {}
    n = int(payload.get("last") or cfg.get("review_last_event_count") or 20)
    events = _tail_jsonl(EVENTS_PATH, n)
    runs = _tail_jsonl(RUNS_PATH, min(n, 20))
    pack = {
        "review_id": f"harness_review_{_now_ms()}",
        "contract_version": CONTRACT_VERSION,
        "phase": PHASE,
        "purpose": "evidence/replay pack for human-in-the-loop review",
        "summary": {
            "event_count": len(events),
            "run_count": len(runs),
            "latest_event": events[-1] if events else None,
            "latest_run": runs[-1] if runs else None,
        },
        "events": events,
        "runs": runs,
        "decision": {
            "authority": AUTHORITY,
            "order_mutation": ORDER_MUTATION,
            "allowed_action": "hold",
            "os_final_approval_required": True,
        },
        "ts_ms": _now_ms(),
    }
    pack["evidence_hash"] = _hash(pack)
    _append_jsonl(REVIEWS_PATH, pack)
    _append_jsonl(EVENTS_PATH, {"type": "review", "review_id": pack["review_id"], "evidence_hash": pack["evidence_hash"], "ok": True, "sev": "ok", "action": "hold"})
    return pack


def run_deployguard(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = _config()
    payload = payload or {}
    frontend = ROOT / "frontend" / "z-os-pwa"
    dist = frontend / "dist"
    app_target = Path(os.environ.get("ZOPS_APP_TARGET", "/var/www/z-os-app"))
    checks = [
        {"name": "frontend_dir", "ok": frontend.exists(), "sev": "C" if not frontend.exists() else "ok", "detail": str(frontend)},
        {"name": "frontend_dist", "ok": dist.exists() and (dist / "index.html").exists(), "sev": "M" if not ((dist.exists() and (dist / "index.html").exists())) else "ok", "detail": str(dist)},
        {"name": "app_target", "ok": app_target.exists() and (app_target / "index.html").exists(), "sev": "M" if not (app_target.exists() and (app_target / "index.html").exists()) else "ok", "detail": str(app_target)},
        {"name": "backend_module", "ok": (ROOT / "backend" / "zops_harness_control_plane_v2_mount.py").exists(), "sev": "C" if not (ROOT / "backend" / "zops_harness_control_plane_v2_mount.py").exists() else "ok", "detail": "harness module mounted"},
        {"name": "backup_root", "ok": (ROOT / "_zui_patch_backups").exists(), "sev": "M" if not (ROOT / "_zui_patch_backups").exists() else "ok", "detail": str(ROOT / "_zui_patch_backups")},
    ]
    violations = [c for c in checks if not c.get("ok")]
    sev = _sev_max(violations, cfg) if violations else "ok"
    run = {
        "deployguard_id": f"harness_deployguard_{_now_ms()}",
        "contract_version": CONTRACT_VERSION,
        "phase": PHASE,
        "ok": not violations,
        "action": "rollback" if sev == "C" else "hold",
        "sev": sev,
        "checks": checks,
        "violations": violations,
        "contract": {"authority": AUTHORITY, "order_mutation": ORDER_MUTATION, "os_final_approval_required": True},
        "notes": "API deployguard is non-mutating. The install script performs build/smoke/rollback checks.",
        "ts_ms": _now_ms(),
    }
    run["evidence_hash"] = _hash(run)
    _append_jsonl(DEPLOYGUARD_PATH, run)
    _append_jsonl(EVENTS_PATH, {"type": "deployguard", "deployguard_id": run["deployguard_id"], "ok": run["ok"], "sev": sev, "action": run["action"], "evidence_hash": run["evidence_hash"]})
    return run


def _status() -> Dict[str, Any]:
    cfg = _config()
    latest_run = _tail_jsonl(RUNS_PATH, 1)
    latest_review = _tail_jsonl(REVIEWS_PATH, 1)
    latest_deployguard = _tail_jsonl(DEPLOYGUARD_PATH, 1)
    return {
        "ok": True,
        "service": "harness_control_plane_v2",
        "contract_version": CONTRACT_VERSION,
        "phase": PHASE,
        "authority": AUTHORITY,
        "order_mutation": ORDER_MUTATION,
        "os_final_approval_required": True,
        "event_count": _count_jsonl(EVENTS_PATH),
        "run_count": _count_jsonl(RUNS_PATH),
        "review_count": _count_jsonl(REVIEWS_PATH),
        "deployguard_count": _count_jsonl(DEPLOYGUARD_PATH),
        "latest_run": latest_run[-1] if latest_run else None,
        "latest_review": latest_review[-1] if latest_review else None,
        "latest_deployguard": latest_deployguard[-1] if latest_deployguard else None,
        "config": cfg,
        "ts_ms": _now_ms(),
    }


def _make_router():
    if APIRouter is None:
        raise RuntimeError("fastapi_missing")
    router = APIRouter(prefix="/api/harness", tags=["zops-harness-control-plane-v2"])

    @router.get("/health")
    def health() -> Dict[str, Any]:
        _ensure()
        return {"ok": True, "service": "harness_control_plane_v2", "contract_version": CONTRACT_VERSION, "authority": AUTHORITY, "order_mutation": ORDER_MUTATION, "mounted": True, "ts_ms": _now_ms()}

    @router.get("/status")
    def status() -> Dict[str, Any]:
        return _status()

    @router.get("/sample")
    def sample() -> Dict[str, Any]:
        return {"ok": True, "sample": {"sentinel": {"suite": "manual_smoke"}, "review": {"last": 20}, "deployguard": {"suite": "manual_smoke"}}, "contract": {"authority": AUTHORITY, "order_mutation": ORDER_MUTATION, "os_final_approval_required": True}, "routes": ["/api/harness/health", "/api/harness/status", "/api/harness/sentinel/run", "/api/harness/review/run", "/api/harness/deployguard/run", "/api/harness/smoke", "/api/harness/events"]}

    @router.post("/sentinel/run")
    def sentinel_run(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:  # type: ignore
        return {"ok": True, "run": run_sentinel(payload)}

    @router.post("/review/run")
    def review_run(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:  # type: ignore
        return {"ok": True, "review": run_review(payload)}

    @router.post("/deployguard/run")
    def deployguard_run(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:  # type: ignore
        return {"ok": True, "deployguard": run_deployguard(payload)}

    @router.post("/smoke")
    def smoke(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:  # type: ignore
        sentinel = run_sentinel({**(payload or {}), "suite": "harness_smoke"})
        review = run_review({"last": 10})
        deployguard = run_deployguard({"suite": "harness_smoke"})
        # Smoke endpoint itself is OK if harness routes work. Component violations are returned as diagnostics.
        return {"ok": True, "smoke": {"sentinel_ok": sentinel.get("ok"), "deployguard_ok": deployguard.get("ok"), "review_ok": True, "sentinel": sentinel, "review_id": review.get("review_id"), "deployguard": deployguard}, "contract": {"authority": AUTHORITY, "order_mutation": ORDER_MUTATION}}

    @router.get("/events")
    def events(limit: int = Query(default=20, ge=1, le=200)) -> Dict[str, Any]:  # type: ignore
        return {"ok": True, "events": _tail_jsonl(EVENTS_PATH, int(limit)), "ts_ms": _now_ms()}

    return router


def mount_harness_control_plane(app: Any) -> Dict[str, Any]:
    """Idempotently mount Harness Control Plane v2 routes onto a FastAPI app."""
    existing = set()
    try:
        existing = {getattr(r, "path", "") for r in getattr(app, "routes", [])}
    except Exception:
        existing = set()
    wanted = {
        "/api/harness/health",
        "/api/harness/status",
        "/api/harness/sample",
        "/api/harness/sentinel/run",
        "/api/harness/review/run",
        "/api/harness/deployguard/run",
        "/api/harness/smoke",
        "/api/harness/events",
    }
    if wanted.issubset(existing):
        return {"mounted": False, "reason": "already_present", "routes": sorted(wanted)}
    router = _make_router()
    app.include_router(router)
    _ensure()
    return {"mounted": True, "routes": sorted(wanted), "contract_version": CONTRACT_VERSION}
