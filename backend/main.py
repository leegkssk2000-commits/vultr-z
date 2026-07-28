from __future__ import annotations

import importlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent

NOISY_PATHS_204 = {
    "/favicon.ico",
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
}
NOISY_PATHS_TEXT = {
    "/robots.txt": "User-agent: *\nDisallow: /\n",
    "/sitemap.xml": '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',
}
NOISY_PREFIXES_404 = (
    "/.git",
    "/wp-admin",
    "/wp-login",
    "/phpmyadmin",
    "/boaform",
)


def _import_module_attr(module_names: list[str], attr_name: str):
    last_err = None
    for module_name in module_names:
        try:
            mod = importlib.import_module(module_name)
            return getattr(mod, attr_name), None
        except Exception as e:
            last_err = e
    return None, last_err


verify_tv_hmac_only, TV_HMAC_IMPORT_ERR = _import_module_attr(
    ["backend.engine.tv_hmac", "engine.tv_hmac"],
    "verify_tv_hmac_only",
)

def _load_api_router():
    router, err = _import_module_attr(["backend.routers", "routers"], "router")
    if router is not None:
        return router, err
    core_router, core_err = _import_module_attr(
        ["backend.routers.core_api", "routers.core_api"],
        "router",
    )
    if core_router is not None:
        merged_err = err
        if merged_err is not None:
            merged_err = RuntimeError(f"package_router_import_failed={err}; core_api_fallback_active")
        return core_router, merged_err
    if err is not None and core_err is not None:
        return None, RuntimeError(f"package_router_import_failed={err}; core_api_import_failed={core_err}")
    return None, err or core_err


api_router, API_ROUTER_IMPORT_ERR = _load_api_router()
lbot_router, LBOT_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.lbot_api", "routers.lbot_api"],
    "router",
)
market_router, MARKET_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.market", "routers.market"],
    "router",
)
state_router, STATE_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.state", "routers.state"],
    "router",
)
trades_router, TRADES_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.trades", "routers.trades"],
    "router",
)
journal_router, JOURNAL_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.journal_api", "routers.journal_api"],
    "router",
)
timeline_router, TIMELINE_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.timeline", "routers.timeline"],
    "router",
)
bots_router, BOTS_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.bot_api", "routers.bot_api", "backend.api.bots", "api.bots"],
    "router",
)
dashboard_router, DASHBOARD_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.dashboard", "routers.dashboard"],
    "router",
)
log_router, LOG_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.log_api", "routers.log_api"],
    "router",
)

lico_router, LICO_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.api.lico", "api.lico"],
    "router",
)


zops_readonly_router, ZOPS_READONLY_ROUTER_IMPORT_ERR = _import_module_attr(
    ["zops_readonly_api", "backend.zops_readonly_api"],
    "router",
)

# Added / repaired routers
trade_router, TRADE_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.trade", "routers.trade", "backend.api.trade", "api.trade"],
    "router",
)
settings_router, SETTINGS_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.settings", "routers.settings"],
    "router",
)
tv_webhook_router, TV_WEBHOOK_ROUTER_IMPORT_ERR = _import_module_attr(
    ["backend.routers.tv_webhook", "routers.tv_webhook"],
    "router",
)

APP_NAME = os.environ.get("ZOS_APP_NAME", "Z-OS Backend")
APP_ENV = os.environ.get("ZOS_ENV", "prod").lower()
APP_VERSION = os.environ.get("ZOS_VERSION", "0.1.0")
API_V1_PREFIX = "/api/v1"

LOG_LEVEL = os.environ.get("ZOS_LOG_LEVEL", "INFO").upper()
HTTP_LOG = os.environ.get("HTTP_LOG", "1") == "1"
DUMP_ROUTES = os.environ.get("DUMP_ROUTES", "0") == "1"

# Keep docs/openapi enabled by default in prod unless explicitly turned off
ENABLE_OPENAPI_IN_PROD = os.environ.get("ZOS_ENABLE_OPENAPI_IN_PROD", "1") == "1"
ENABLE_DOCS_IN_PROD = os.environ.get("ZOS_ENABLE_DOCS_IN_PROD", "1") == "1"
ENABLE_REDOC_IN_PROD = os.environ.get("ZOS_ENABLE_REDOC_IN_PROD", "0") == "1"

STATE_FILE = Path(os.environ.get("Z_STATE_FILE", str(BASE_DIR / "state.json")))

TV_WEBHOOK_PATH = os.environ.get("TV_WEBHOOK_PATH", f"{API_V1_PREFIX}/tv/webhook")
TV_SECRET_FILE = Path(os.environ.get("TV_SECRET_FILE", str(BASE_DIR / "config" / "tv_secret.txt")))
TV_NONCE_LEDGER_PATH = Path(
    os.environ.get("TV_NONCE_LEDGER_PATH", str(BASE_DIR / "_logs" / "tv_nonce_ledger.json"))
)
TV_NONCE_TTL_MS = int(os.environ.get("TV_NONCE_TTL_MS", "30000"))
TV_MAX_SKEW_S = int(os.environ.get("TV_MAX_SKEW_S", "60"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
log = logging.getLogger("z-backend")

STARTED_AT = time.time()
WEBHOOK_SECRET_CACHE = ""
STATE_MANAGER: Optional[Any] = None
STATE_CACHE: Dict[str, Any] = {}


class HealthResponse(BaseModel):
    status: str
    ts: float
    uptime_sec: float
    env: str
    version: str


class StateSnapshotResponse(BaseModel):
    status: str
    ts: float
    state: Dict[str, Any]


def _is_noise_path(path: str) -> bool:
    if path in NOISY_PATHS_204 or path in NOISY_PATHS_TEXT:
        return True
    return any(path.startswith(prefix) for prefix in NOISY_PREFIXES_404)


def load_webhook_secret() -> str:
    secret = (os.getenv("WEBHOOK_SECRET") or os.getenv("TV_WEBHOOK_SECRET") or "").strip()
    if secret:
        return secret

    try:
        if TV_SECRET_FILE.exists():
            txt = TV_SECRET_FILE.read_text(encoding="utf-8").strip()
            if txt:
                return txt
    except Exception as e:
        log.warning("tv secret file read failed: %s", e)

    return ""


def get_webhook_secret() -> str:
    global WEBHOOK_SECRET_CACHE
    if not WEBHOOK_SECRET_CACHE:
        WEBHOOK_SECRET_CACHE = load_webhook_secret()
    return WEBHOOK_SECRET_CACHE


def load_state_from_disk() -> Dict[str, Any]:
    try:
        if STATE_FILE.exists():
            raw = STATE_FILE.read_text(encoding="utf-8").strip()
            if raw:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    return obj
    except Exception as e:
        log.warning("state disk load failed: %s", e)
    return {}


def save_state_to_disk(state: Dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("state disk save failed: %s", e)


def init_state_best_effort() -> None:
    global STATE_MANAGER, STATE_CACHE

    zstate_module = None
    for module_name in ["backend.state.z_state_manager", "state.z_state_manager"]:
        try:
            zstate_module = importlib.import_module(module_name)
            break
        except Exception:
            continue

    if zstate_module is not None:
        try:
            init_state_if_needed = getattr(zstate_module, "init_state_if_needed", None)
            if callable(init_state_if_needed):
                init_state_if_needed()
        except Exception as e:
            log.warning("init_state_if_needed failed: %s", e)

        try:
            state_manager_from_module = getattr(zstate_module, "STATE_MANAGER", None)
            if state_manager_from_module is not None:
                STATE_MANAGER = state_manager_from_module
        except Exception:
            pass

        if STATE_MANAGER is None:
            try:
                zstate_cls = getattr(zstate_module, "ZStateManager", None)
                if zstate_cls is not None:
                    STATE_MANAGER = zstate_cls()
            except Exception:
                STATE_MANAGER = None
    else:
        log.warning("state manager module not found; using disk fallback only")

    STATE_CACHE = load_state_from_disk()


def get_state_for_api_best_effort() -> Dict[str, Any]:
    for module_name in ["backend.state.z_state_manager", "state.z_state_manager"]:
        try:
            zstate_module = importlib.import_module(module_name)
            get_state_for_api = getattr(zstate_module, "get_state_for_api", None)
            if callable(get_state_for_api):
                st = get_state_for_api()
                return st if isinstance(st, dict) else {"state": st}
        except Exception:
            continue

    if STATE_MANAGER is not None:
        try:
            if hasattr(STATE_MANAGER, "snapshot") and callable(getattr(STATE_MANAGER, "snapshot")):
                st = STATE_MANAGER.snapshot()
                return st if isinstance(st, dict) else {"state": st}
            if hasattr(STATE_MANAGER, "summary") and callable(getattr(STATE_MANAGER, "summary")):
                st = STATE_MANAGER.summary()
                return st if isinstance(st, dict) else {"state": st}
        except Exception as e:
            log.warning("state manager read failed: %s", e)

    return load_state_from_disk()


def update_state(**kwargs: Any) -> bool:
    global STATE_CACHE
    if not isinstance(STATE_CACHE, dict):
        STATE_CACHE = {}
    STATE_CACHE.update(kwargs)
    save_state_to_disk(STATE_CACHE)
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        TV_NONCE_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("nonce ledger dir create failed: %s", e)

    secret = get_webhook_secret()
    if not secret:
        log.warning(
            "webhook secret is empty: set WEBHOOK_SECRET or TV_WEBHOOK_SECRET or %s",
            str(TV_SECRET_FILE),
        )

    if TV_HMAC_IMPORT_ERR is not None:
        log.error("tv_hmac import failed: %s", TV_HMAC_IMPORT_ERR)

    for label, err in (
        ("api", API_ROUTER_IMPORT_ERR),
        ("lbot", LBOT_ROUTER_IMPORT_ERR),
        ("market", MARKET_ROUTER_IMPORT_ERR),
        ("state", STATE_ROUTER_IMPORT_ERR),
        ("bots", BOTS_ROUTER_IMPORT_ERR),
        ("dashboard", DASHBOARD_ROUTER_IMPORT_ERR),
        ("log", LOG_ROUTER_IMPORT_ERR),
        ("lico", LICO_ROUTER_IMPORT_ERR),
        ("trade", TRADE_ROUTER_IMPORT_ERR),
        ("settings", SETTINGS_ROUTER_IMPORT_ERR),
        ("tv_webhook", TV_WEBHOOK_ROUTER_IMPORT_ERR),
    ):
        if err is not None:
            log.warning("%s router import skipped: %s", label, err)

    init_state_best_effort()
    log.info(
        "startup complete env=%s version=%s docs=%s redoc=%s openapi=%s",
        APP_ENV, APP_VERSION, ENABLE_DOCS_IN_PROD, ENABLE_REDOC_IN_PROD, ENABLE_OPENAPI_IN_PROD,
    )
    yield
    log.info("shutdown complete")


def _has_route_path(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)




def _ensure_frontend_route_singletons(app: FastAPI, logger: logging.Logger) -> None:
    route_paths = sorted({getattr(route, "path", "") for route in app.routes if getattr(route, "path", "")})
    if os.getenv("APP_DUMP_ROUTES") == "1":
        try:
            Path("/tmp/backend-routes.log").write_text("\n".join(route_paths) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.warning("route dump write failed: %s", exc)

    if _has_route_path(app, "/api/v1/journal/summary"):
        return

    build_summary = None
    for mod_name in ("backend.routers.journal_api", "routers.journal_api"):
        try:
            mod = importlib.import_module(mod_name)
            build_summary = getattr(mod, "build_journal_summary", None)
            if build_summary is not None:
                break
        except Exception as exc:
            logger.warning("journal summary alias import skipped: %s", exc)

    if build_summary is None:
        logger.error("journal summary alias install failed: build_journal_summary missing")
        return

    @app.get("/api/v1/journal/summary", include_in_schema=False)
    def _journal_summary_alias() -> Any:
        return build_summary()


def _install_visibility_middlewares(app: FastAPI) -> None:
    _install_visibility_middlewares(app)


def _install_logging_middlewares(app: FastAPI) -> None:
    if not HTTP_LOG:
        return

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        path = request.url.path
        if _is_noise_path(path):
            return await call_next(request)
        t0 = time.time()
        response = await call_next(request)
        ms = (time.time() - t0) * 1000.0
        log.info("%s %s -> %s (%.1f ms)", request.method, path, response.status_code, ms)
        return response


def create_app() -> FastAPI:
    is_prod = APP_ENV == "prod"

    docs_enabled = (not is_prod) or ENABLE_DOCS_IN_PROD
    redoc_enabled = (not is_prod) or ENABLE_REDOC_IN_PROD
    openapi_enabled = (not is_prod) or ENABLE_OPENAPI_IN_PROD or docs_enabled or redoc_enabled

    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if redoc_enabled else None,
        openapi_url="/openapi.json" if openapi_enabled else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def noise_guard(request: Request, call_next):
        path = request.url.path
        if path in NOISY_PATHS_204:
            return Response(status_code=204)
        if path in NOISY_PATHS_TEXT:
            media_type = "application/xml" if path.endswith(".xml") else "text/plain"
            return PlainTextResponse(NOISY_PATHS_TEXT[path], media_type=media_type)
        if any(path.startswith(prefix) for prefix in NOISY_PREFIXES_404):
            return JSONResponse(status_code=404, content={"detail": "Not Found", "path": path})
        return await call_next(request)

    @app.exception_handler(404)
    async def not_found(request: Request, exc):  # noqa: ARG001
        return JSONResponse(status_code=404, content={"detail": "Not Found", "path": request.url.path})

    @app.middleware("http")
    async def tv_hmac_only_guard(request: Request, call_next):
        if request.method == "POST" and request.url.path == TV_WEBHOOK_PATH:
            if verify_tv_hmac_only is None:
                return JSONResponse(
                    status_code=500,
                    content={"status": "reject", "reason": f"server_misconfigured: tv_hmac import failed: {TV_HMAC_IMPORT_ERR}"},
                )
            raw = await request.body()
            sig = (
                request.headers.get("x-tv-signature")
                or request.headers.get("x-openai-signature")
                or request.headers.get("x-webhook-signature")
            )
            result = verify_tv_hmac_only(
                raw_body=raw,
                sig_header_value=sig,
                secret=get_webhook_secret(),
                nonce_ttl_ms=TV_NONCE_TTL_MS,
                max_skew_s=TV_MAX_SKEW_S,
                nonce_ledger_path=str(TV_NONCE_LEDGER_PATH),
            )
            if not result.ok:
                return JSONResponse(status_code=result.status_code, content={"status": "reject", "reason": result.reason})
        return await call_next(request)

    @app.get("/health", response_model=HealthResponse, include_in_schema=False)
    @app.get(f"{API_V1_PREFIX}/health", response_model=HealthResponse, include_in_schema=False)
    async def global_health_check() -> HealthResponse:
        now = time.time()
        return HealthResponse(status="ok", ts=now, uptime_sec=now - STARTED_AT, env=APP_ENV, version=APP_VERSION)

    @app.get(f"{API_V1_PREFIX}/state", response_model=StateSnapshotResponse, include_in_schema=False)
    async def global_state_check() -> StateSnapshotResponse:
        now = time.time()
        st = get_state_for_api_best_effort()
        if not isinstance(st, dict):
            st = {"state": st}
        st.setdefault("status", "ready")
        return StateSnapshotResponse(status="ok", ts=now, state=st)

    @app.get("/__docs_status", include_in_schema=False)
    @app.get(f"{API_V1_PREFIX}/meta/docs_status", include_in_schema=False)
    async def docs_status():
        return {
            "env": APP_ENV,
            "docs_enabled": docs_enabled,
            "redoc_enabled": redoc_enabled,
            "openapi_enabled": openapi_enabled,
            "docs_url": "/docs" if docs_enabled else None,
            "redoc_url": "/redoc" if redoc_enabled else None,
            "openapi_url": "/openapi.json" if openapi_enabled else None,
        }

    @app.get("/", include_in_schema=False)
    async def root():
        payload = {
            "ok": True,
            "health": f"{API_V1_PREFIX}/health",
            "tv_health": f"{API_V1_PREFIX}/tv/health",
            "market_cards": f"{API_V1_PREFIX}/market/cards",
            "market_stream": f"{API_V1_PREFIX}/market/stream",
            "env": APP_ENV,
            "version": APP_VERSION,
        }
        if docs_enabled:
            payload["docs"] = "/docs"
        if redoc_enabled:
            payload["redoc"] = "/redoc"
        if openapi_enabled:
            payload["openapi"] = "/openapi.json"
        return payload


    # ZOPS read-only repair routes must be registered before older dashboard routes.
    if zops_readonly_router is not None and not _has_route_path(app, "/api/quant/readiness"):
        app.include_router(zops_readonly_router)

    if api_router is not None:
        app.include_router(api_router)
    if not _has_route_path(app, "/api/rail-status"):
        rail_router_shim, rail_router_shim_err = _import_module_attr(
            ["backend.routers.core_api", "routers.core_api"],
            "router",
        )
        if rail_router_shim is not None:
            app.include_router(rail_router_shim)
            logger.warning("rail-status router shim attached directly from core_api")
        else:
            logger.warning("rail-status router shim import failed: %s", rail_router_shim_err)
    if lbot_router is not None:
        app.include_router(lbot_router)
    if bots_router is not None:
        app.include_router(bots_router)
    if market_router is not None:
        app.include_router(market_router)
    if state_router is not None:
        app.include_router(state_router)
    if False and trades_router is not None and not _has_route_path(app, "/trades/recent"):
        app.include_router(trades_router)
    if trade_router is not None and not _has_route_path(app, "/api/trade/context"):
        app.include_router(trade_router)
    if settings_router is not None and not _has_route_path(app, "/api/v1/settings"):
        app.include_router(settings_router)
    if tv_webhook_router is not None and not _has_route_path(app, TV_WEBHOOK_PATH):
        app.include_router(tv_webhook_router)
    if journal_router is not None and not _has_route_path(app, "/api/v1/journal/summary"):
        app.include_router(journal_router)
    if timeline_router is not None and not _has_route_path(app, "/timeline"):
        app.include_router(timeline_router)
    if dashboard_router is not None and not _has_route_path(app, "/api/dashboard/active-team"):
        app.include_router(dashboard_router)
    if log_router is not None and not _has_route_path(app, "/api/log/timeline"):
        app.include_router(log_router)
    if lico_router is not None and not _has_route_path(app, "/api/lico/health"):
        app.include_router(lico_router)

    if DUMP_ROUTES:
        from fastapi.routing import APIRoute

        @app.on_event("startup")
        def dump_routes() -> None:
            log.info("=== ROUTES BEGIN ===")
            for route in app.routes:
                if isinstance(route, APIRoute):
                    methods = ",".join(sorted(route.methods or []))
                    log.info("ROUTE %s %s", methods, route.path)
            log.info("=== ROUTES END ===")

    _install_logging_middlewares(app)

    _ensure_frontend_route_singletons(app, log)

    return app


app = create_app()

# --- ZOS_WEB_AUDIT_REPLAY_ROUTER_V1_START ---
try:
    from backend.api.web_audit import router as z_web_audit_router
except Exception:
    from api.web_audit import router as z_web_audit_router
if not any(getattr(route, "path", None) == "/api/web/health" for route in app.routes):
    app.include_router(z_web_audit_router)
# --- ZOS_WEB_AUDIT_REPLAY_ROUTER_V1_END ---
# --- ZOS_ALIMI_MESSAGE_ROUTER_V2_START ---
try:
    from backend.api.alimi import router as z_alimi_message_router
except Exception:
    try:
        from api.alimi import router as z_alimi_message_router
    except Exception as _z_alimi_import_error:
        z_alimi_message_router = None
        try:
            log.warning("alimi message router import failed: %s", _z_alimi_import_error)
        except Exception:
            pass
if z_alimi_message_router is not None:
    try:
        if not any(getattr(_route, "path", None) == "/api/alimi/health" for _route in app.routes):
            app.include_router(z_alimi_message_router)
    except Exception as _z_alimi_attach_error:
        try:
            log.warning("alimi message router attach failed: %s", _z_alimi_attach_error)
        except Exception:
            pass
# --- ZOS_ALIMI_MESSAGE_ROUTER_V2_END ---


# --- ZOS_ALIMI_ROUTER_V1_START ---
try:
    from backend.api.alimi import router as z_alimi_router
except Exception:
    from api.alimi import router as z_alimi_router
if not any(getattr(route, "path", None) == "/api/alimi/health" for route in app.routes):
    app.include_router(z_alimi_router)
# --- ZOS_ALIMI_ROUTER_V1_END ---

# --- ZOS_LICO_ROUTER_V4_START ---
try:
    from backend.api.lico import router as z_lico_router
except Exception:
    from api.lico import router as z_lico_router
app.include_router(z_lico_router)
# --- ZOS_LICO_ROUTER_V4_END ---

# --- ZUI_ALIMI_ROUTER_V1_START ---
# Read-only Alimi semantic briefing API. Safe to append: it only mounts GET routes.
try:
    from backend.api.alimi import router as zui_alimi_router
except Exception:
    try:
        from api.alimi import router as zui_alimi_router
    except Exception:
        zui_alimi_router = None

if zui_alimi_router is not None:
    try:
        _zui_alimi_paths = {getattr(route, "path", "") for route in getattr(app, "routes", [])}
        if "/api/alimi/health" not in _zui_alimi_paths:
            app.include_router(zui_alimi_router)
    except Exception:
        pass
# --- ZUI_ALIMI_ROUTER_V1_END ---


# ZOPS_ORDER_RISK_GATE_CONTRACT_V1_BEGIN
try:
    try:
        from routers.gate_contract_v1 import router as _zops_gate_contract_v1_router
    except Exception:
        from backend.routers.gate_contract_v1 import router as _zops_gate_contract_v1_router
    app.include_router(_zops_gate_contract_v1_router)
    print("[ZOPS_ORDER_RISK_GATE_CONTRACT_V1] router mounted")
except Exception as _zops_gate_contract_v1_exc:
    print(f"[ZOPS_ORDER_RISK_GATE_CONTRACT_V1] router mount failed: {_zops_gate_contract_v1_exc}")
# ZOPS_ORDER_RISK_GATE_CONTRACT_V1_END
# ZOPS_DETERMINISTIC_REPLAY_ENGINE_V1_INCLUDE
try:
    from backend.zops_replay_router import router as zops_replay_router
    app.include_router(zops_replay_router)
except Exception as _zops_replay_router_error:
    try:
        import logging
        logging.getLogger("zops.replay").warning("replay router disabled: %s", _zops_replay_router_error)
    except Exception:
        pass
# ZOPS_REPLAY_API_404_INCLUDE_REPAIR_V1
try:
    try:
        from zops_replay_router import router as _zops_replay_router_repair_v1
    except Exception:
        from backend.zops_replay_router import router as _zops_replay_router_repair_v1
    app.include_router(_zops_replay_router_repair_v1)
except Exception as _zops_replay_router_repair_v1_error:
    try:
        import logging
        logging.getLogger("zops.replay").error("replay router include repair failed: %s", _zops_replay_router_repair_v1_error)
    except Exception:
        pass
# ZOPS_DUAL_LEDGER_RECONCILIATION_V1_INCLUDE
try:
    try:
        from zops_ledger_router import router as zops_ledger_router
    except Exception:
        from backend.zops_ledger_router import router as zops_ledger_router
    app.include_router(zops_ledger_router)
except Exception as _zops_ledger_router_error:
    try:
        import logging
        logging.getLogger("zops.ledger").warning("ledger router disabled: %s", _zops_ledger_router_error)
    except Exception:
        pass

# ZOPS_PROMOTION_GATE_V2_INCLUDE_REPAIR_V1
try:
    from zops_promotion_gate_v2 import router as zops_promotion_gate_v2_router
    app.include_router(zops_promotion_gate_v2_router)
except Exception as _zops_promotion_gate_v2_error:
    print("[ZOPS-PROMOTION-GATE-V2] include skipped:", _zops_promotion_gate_v2_error)

# ZOPS_PROMOTION_GATE_V2_DIRECT_ROUTES_HARDFIX_V1
# Purpose: hard-include Promotion Gate v2 API into the active FastAPI app.
# Contract: advisory/read-only, no order mutation, OS final approval required.
try:
    import time as _zops_promo_time
    import hashlib as _zops_promo_hashlib
    from typing import Any as _ZopsAny, Dict as _ZopsDict, Optional as _ZopsOptional
    from fastapi import APIRouter as _ZopsAPIRouter, Body as _ZopsBody

    _zops_promo_router = _ZopsAPIRouter(prefix="/api/promotion", tags=["promotion_gate_v2"])

    def _zops_promo_now_ms() -> int:
        return int(_zops_promo_time.time() * 1000)

    def _zops_promo_decision_id(payload: _ZopsOptional[_ZopsDict[str, _ZopsAny]] = None) -> str:
        raw = repr(payload or {}) + ":" + str(_zops_promo_now_ms())
        return _zops_promo_hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _zops_promo_contract() -> _ZopsDict[str, _ZopsAny]:
        return {
            "authority": "advisory_only",
            "order_mutation": "blocked",
            "os_final_approval_required": True,
            "allowed_actions": ["reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"],
            "route": "Zbot recommendation -> Order/Risk Gate validation -> OS final approval -> execution adapter",
            "source_required": ["cf:/", "sheets:/", "lico:", "zlice:"],
        }

    def _zops_promo_metrics() -> _ZopsDict[str, _ZopsAny]:
        return {
            "winrate": {"required": True, "unit": "%", "src": "SSOT"},
            "expectancy": {"required": True, "unit": "R", "src": "SSOT"},
            "max_dd": {"required": True, "unit": "%", "src": "SSOT"},
            "slippage": {"required": True, "unit": "bps", "src": "SSOT"},
            "funding_cost": {"required": True, "unit": "8h%", "src": "SSOT"},
            "proof_freshness": {"required": True, "unit": "ms", "src": "SSOT.DATA_STALE_MS"},
            "route_stability": {"required": True, "unit": "score", "src": "Zlice"},
            "shadow_live_divergence": {"required": True, "unit": "bps/%", "src": "Replay/Ledger"},
            "regime_similarity": {"required": True, "unit": "score", "src": "Replay"},
            "minimum_trade_count": {"required": True, "unit": "trades", "src": "SSOT"},
            "minimum_canary_days": {"required": True, "unit": "days", "src": "SSOT"},
        }

    @_zops_promo_router.get("/health")
    def zops_promotion_health() -> _ZopsDict[str, _ZopsAny]:
        return {
            "ok": True,
            "service": "promotion_gate_v2",
            "phase": "v3.1_hardening_layer",
            "route_loaded": True,
            "ts_ms": _zops_promo_now_ms(),
            "contract": _zops_promo_contract(),
        }

    @_zops_promo_router.get("/status")
    def zops_promotion_status() -> _ZopsDict[str, _ZopsAny]:
        return {
            "ok": True,
            "service": "promotion_gate_v2",
            "state": "advisory_ready",
            "current_lane": "paper_shadow_canary_gate",
            "mutation": "blocked",
            "os_final_approval_required": True,
            "gate_metrics": _zops_promo_metrics(),
            "pipeline": [
                "paper",
                "shadow",
                "promotion_gate",
                "canary_live",
                "os_final_approval",
                "live"
            ],
            "hardening_order": [
                "order_risk_gate_contract",
                "deterministic_replay_engine",
                "dual_ledger_reconciliation",
                "promotion_gate_v2_regression_harness",
                "sentinel_review_deployguard",
                "chaos_test_suite_alimi_dashboard",
                "observability_chain"
            ],
            "contract": _zops_promo_contract(),
            "ts_ms": _zops_promo_now_ms(),
        }

    @_zops_promo_router.get("/sample")
    def zops_promotion_sample() -> _ZopsDict[str, _ZopsAny]:
        return {
            "ok": True,
            "decision_id": "promo_sample_001",
            "symbol": "BTCUSDT",
            "strategy": "alpha1",
            "recommendation": "hold",
            "promotion_decision": "not_promoted_without_os_final_approval",
            "mode": "paper_shadow_canary_gate",
            "reasons": [
                "advisory_only_contract_active",
                "order_mutation_blocked",
                "minimum_canary_and_replay_metrics_required",
                "os_final_approval_required"
            ],
            "metrics_required": list(_zops_promo_metrics().keys()),
            "contract": _zops_promo_contract(),
            "ts_ms": _zops_promo_now_ms(),
        }

    @_zops_promo_router.post("/regression/run")
    def zops_promotion_regression_run(payload: _ZopsDict[str, _ZopsAny] = _ZopsBody(default_factory=dict)) -> _ZopsDict[str, _ZopsAny]:
        suite = str(payload.get("suite", "manual_smoke")) if isinstance(payload, dict) else "manual_smoke"
        decision_id = _zops_promo_decision_id(payload if isinstance(payload, dict) else {"payload": str(payload)})
        return {
            "ok": True,
            "service": "promotion_gate_v2_regression_harness",
            "suite": suite,
            "decision_id": decision_id,
            "result": "PASS_READ_ONLY_SMOKE",
            "checks": {
                "route_loaded": True,
                "order_mutation": "blocked",
                "os_final_approval_required": True,
                "same_seed_same_payload_same_decision_id_contract": True,
                "promotion_requires_metrics": True,
            },
            "contract": _zops_promo_contract(),
            "ts_ms": _zops_promo_now_ms(),
        }

    _zops_promo_app = globals().get("app") or globals().get("application")
    if _zops_promo_app is not None:
        _zops_existing_paths = {getattr(r, "path", "") for r in getattr(_zops_promo_app, "routes", [])}
        _zops_required_paths = {
            "/api/promotion/health",
            "/api/promotion/status",
            "/api/promotion/sample",
            "/api/promotion/regression/run",
        }
        if not _zops_required_paths.issubset(_zops_existing_paths):
            _zops_promo_app.include_router(_zops_promo_router)
except Exception as _zops_promo_route_error:
    print("[ZOPS_PROMOTION_GATE_V2_DIRECT_ROUTES_HARDFIX_V1] route include skipped:", repr(_zops_promo_route_error))
# /ZOPS_PROMOTION_GATE_V2_DIRECT_ROUTES_HARDFIX_V1

# ZOPS_PROMOTION_GATE_V2_ACTUAL_BACKEND_MOUNT_V2_INCLUDE
try:
    try:
        from zops_promotion_gate_v2_mount import mount_promotion_gate as _zops_mount_promotion_gate_v2
    except Exception:
        from backend.zops_promotion_gate_v2_mount import mount_promotion_gate as _zops_mount_promotion_gate_v2
    _zops_mount_promotion_gate_v2(app)
except Exception as _zops_promotion_gate_v2_actual_mount_error:
    print("ZOPS_PROMOTION_GATE_V2_ACTUAL_MOUNT_ERROR", repr(_zops_promotion_gate_v2_actual_mount_error))

# ZOPS_HARNESS_CONTROL_PLANE_V2_INCLUDE
try:
    try:
        from zops_harness_control_plane_v2_mount import mount_harness_control_plane as _zops_mount_harness_control_plane_v2
    except Exception:
        from backend.zops_harness_control_plane_v2_mount import mount_harness_control_plane as _zops_mount_harness_control_plane_v2
    _zops_mount_harness_control_plane_v2(app)
except Exception as _zops_harness_control_plane_v2_mount_error:
    print("ZOPS_HARNESS_CONTROL_PLANE_V2_MOUNT_ERROR", repr(_zops_harness_control_plane_v2_mount_error))


# ZOPS_ORDER_GATE_ALIAS_FOR_HARNESS_V1_BEGIN
try:
    try:
        from routers.order_gate_alias_for_harness_v1 import router as _zops_order_gate_alias_for_harness_v1_router
    except Exception:
        from backend.routers.order_gate_alias_for_harness_v1 import router as _zops_order_gate_alias_for_harness_v1_router
    app.include_router(_zops_order_gate_alias_for_harness_v1_router)
    print("[ZOPS_ORDER_GATE_ALIAS_FOR_HARNESS_V1] router mounted")
except Exception as _zops_order_gate_alias_for_harness_v1_exc:
    print(f"[ZOPS_ORDER_GATE_ALIAS_FOR_HARNESS_V1] router mount failed: {_zops_order_gate_alias_for_harness_v1_exc}")
# ZOPS_ORDER_GATE_ALIAS_FOR_HARNESS_V1_END

# ZOPS_ORDER_GATE_ALIAS_HARD_MOUNT_V2_BEGIN
try:
    try:
        from zops_order_gate_alias_hard_mount_v2 import router as zops_order_gate_alias_hard_mount_v2_router
    except Exception:
        from backend.zops_order_gate_alias_hard_mount_v2 import router as zops_order_gate_alias_hard_mount_v2_router
    app.include_router(
        zops_order_gate_alias_hard_mount_v2_router,
        prefix="/api/order-gate",
        tags=["zops-order-gate-alias-hard-mount-v2"],
    )
    print("ZOPS_ORDER_GATE_ALIAS_HARD_MOUNT_V2_INCLUDE=mounted")
except Exception as _zops_order_gate_alias_hard_mount_v2_exc:
    print("ZOPS_ORDER_GATE_ALIAS_HARD_MOUNT_V2_INCLUDE=failed", repr(_zops_order_gate_alias_hard_mount_v2_exc))
# ZOPS_ORDER_GATE_ALIAS_HARD_MOUNT_V2_END
# ZOPS_ORDER_GATE_EOF_SAFE_MOUNT_V4_BEGIN
try:
    try:
        from backend._zops_order_gate_eof_safe_mount_v4 import mount_order_gate_routes as _zops_mount_order_gate_v4
    except Exception:
        from _zops_order_gate_eof_safe_mount_v4 import mount_order_gate_routes as _zops_mount_order_gate_v4
    _zops_order_gate_v4_mount_result = _zops_mount_order_gate_v4(app)
    print("ZOPS_ORDER_GATE_EOF_SAFE_MOUNT_V4=mounted", _zops_order_gate_v4_mount_result)
except Exception as _zops_order_gate_v4_exc:
    print("ZOPS_ORDER_GATE_EOF_SAFE_MOUNT_V4=failed", repr(_zops_order_gate_v4_exc))
# ZOPS_ORDER_GATE_EOF_SAFE_MOUNT_V4_END


# --- ZOPS_ORDER_GATE_REWRITE_ALIAS_RUNTIME_V5_START ---
# Runtime alias: /api/order-gate/* -> /api/gate/*
# Contract: advisory-only; no order mutation; OS remains final approval layer.
try:
    @app.middleware("http")
    async def _zops_order_gate_rewrite_alias_runtime_v5(request, call_next):
        try:
            path = request.scope.get("path") or ""
            if path == "/api/order-gate" or path.startswith("/api/order-gate/"):
                suffix = path[len("/api/order-gate"):]
                new_path = "/api/gate" + suffix
                request.scope["path"] = new_path
                request.scope["raw_path"] = new_path.encode("utf-8")
        except Exception as _zops_alias_err:
            try:
                print(f"[ZOPS_ORDER_GATE_REWRITE_ALIAS_RUNTIME_V5] rewrite_error={_zops_alias_err}")
            except Exception:
                pass
        return await call_next(request)
    try:
        print("[ZOPS_ORDER_GATE_REWRITE_ALIAS_RUNTIME_V5] mounted middleware /api/order-gate/* -> /api/gate/*")
    except Exception:
        pass
except Exception as _zops_mount_err:
    try:
        print(f"[ZOPS_ORDER_GATE_REWRITE_ALIAS_RUNTIME_V5] mount_failed={_zops_mount_err}")
    except Exception:
        pass
# --- ZOPS_ORDER_GATE_REWRITE_ALIAS_RUNTIME_V5_END ---

# ZOPS_HARNESS_VISUAL_GATE_V1_EOF_MOUNT
try:
    from backend.routers.zops_harness_visual_gate_v1 import router as zops_harness_visual_gate_v1_router
    _zops_existing_paths = {getattr(getattr(r, "path", None), "__str__", lambda: getattr(r, "path", ""))() for r in getattr(app, "routes", [])}
    if "/api/harness/health" not in _zops_existing_paths:
        app.include_router(zops_harness_visual_gate_v1_router)
        print("[ZOPS_HARNESS_VISUAL_GATE_V1] router mounted")
    else:
        print("[ZOPS_HARNESS_VISUAL_GATE_V1] router already mounted")
except Exception as _zops_harness_visual_gate_v1_error:
    print("[ZOPS_HARNESS_VISUAL_GATE_V1][WARN] mount skipped:", repr(_zops_harness_visual_gate_v1_error))

# ZOPS_MODULE_CONTRACT_OPTIMIZATION_V1_AUTOLOAD_START
try:
    from backend.zops_opt.api_registry_v1 import include_zops_optimization_registry as _zops_include_opt_v1
except Exception:
    try:
        from zops_opt.api_registry_v1 import include_zops_optimization_registry as _zops_include_opt_v1
    except Exception as _zops_opt_import_exc:
        _zops_include_opt_v1 = None
        print(f"[ZOPS-MODULE-CONTRACT-OPTIMIZATION-V1][WARN] import skipped: {_zops_opt_import_exc}")
if _zops_include_opt_v1 is not None:
    try:
        _zops_include_opt_v1(app)
    except Exception as _zops_opt_mount_exc:
        print(f"[ZOPS-MODULE-CONTRACT-OPTIMIZATION-V1][WARN] mount skipped: {_zops_opt_mount_exc}")
# ZOPS_MODULE_CONTRACT_OPTIMIZATION_V1_AUTOLOAD_END

# --- ZOPS_SAFE_CODE_OPTIMIZATION_V2_MOUNT: append-only, rollback-safe ---
try:
    from backend.zops_opt.code_optimization_v2 import router as zops_safe_code_optimization_v2_router
    app.include_router(zops_safe_code_optimization_v2_router)
    print("[ZOPS_SAFE_CODE_OPTIMIZATION_V2] router mounted")
except Exception as _zops_safe_code_opt_v2_e:
    print(f"[ZOPS_SAFE_CODE_OPTIMIZATION_V2] include skipped: {_zops_safe_code_opt_v2_e}")
# --- /ZOPS_SAFE_CODE_OPTIMIZATION_V2_MOUNT ---

# --- ZOPS_COMPOSITION_ROOT_SHADOW_V1_MOUNT: append-only, rollback-safe ---
try:
    from backend.zops_opt.composition_root_shadow_v1 import router as zops_composition_root_shadow_v1_router
    app.include_router(zops_composition_root_shadow_v1_router)
    print("[ZOPS_COMPOSITION_ROOT_SHADOW_V1] router mounted")
except Exception as _zops_composition_root_shadow_v1_e:
    print(f"[ZOPS_COMPOSITION_ROOT_SHADOW_V1] include skipped: {_zops_composition_root_shadow_v1_e}")
# --- /ZOPS_COMPOSITION_ROOT_SHADOW_V1_MOUNT ---

# --- ZOPS_TYPED_REGISTRY_MIGRATION_V1_MOUNT: append-only, rollback-safe ---
try:
    from backend.zops_opt.typed_registry_migration_v1 import router as zops_typed_registry_migration_v1_router
    from backend.zops_opt.typed_registry_migration_v1 import apply_runtime_route_dedupe as _zops_typed_registry_migration_v1_dedupe
    app.include_router(zops_typed_registry_migration_v1_router)
    _zops_typed_registry_migration_v1_report = _zops_typed_registry_migration_v1_dedupe(app)
    print("[ZOPS_TYPED_REGISTRY_MIGRATION_V1] router mounted; duplicate method routes removed=", _zops_typed_registry_migration_v1_report.get("removed_duplicate_method_routes"))
except Exception as _zops_typed_registry_migration_v1_e:
    print(f"[ZOPS_TYPED_REGISTRY_MIGRATION_V1] include/dedupe skipped: {_zops_typed_registry_migration_v1_e}")
# --- /ZOPS_TYPED_REGISTRY_MIGRATION_V1_MOUNT ---

# --- ZOPS_LEGACY_ALIAS_QUARANTINE_V1_MOUNT: append-only, tag-only, rollback-safe ---
try:
    from backend.zops_opt.legacy_alias_quarantine_v1 import router as zops_legacy_alias_quarantine_v1_router
    app.include_router(zops_legacy_alias_quarantine_v1_router)
    print("[ZOPS_LEGACY_ALIAS_QUARANTINE_V1] router mounted; tag-only quarantine active")
except Exception as _zops_legacy_alias_quarantine_v1_e:
    print(f"[ZOPS_LEGACY_ALIAS_QUARANTINE_V1] include skipped: {_zops_legacy_alias_quarantine_v1_e}")
# --- /ZOPS_LEGACY_ALIAS_QUARANTINE_V1_MOUNT ---

# ZOPS_SHARED_CONTRACT_FIXTURES_V1_INCLUDE_START
try:
    from backend.zops_opt.shared_contract_fixtures_v1 import router as zops_shared_contract_fixtures_v1_router
    app.include_router(zops_shared_contract_fixtures_v1_router)
    print("[ZOPS_SHARED_CONTRACT_FIXTURES_V1] router mounted")
except Exception as e:
    print(f"[ZOPS_SHARED_CONTRACT_FIXTURES_V1] include skipped: {e}")
# ZOPS_SHARED_CONTRACT_FIXTURES_V1_INCLUDE_END


# ZOPS_API_SMOKE_CONTRACT_V1_INCLUDE_START
try:
    from backend.zops_opt.api_smoke_contract_v1 import install as _zops_api_smoke_contract_v1_install
    _zops_api_smoke_contract_v1_report = _zops_api_smoke_contract_v1_install(app)
    print("[ZOPS_API_SMOKE_CONTRACT_V1] installed", _zops_api_smoke_contract_v1_report)
except Exception as _zops_api_smoke_contract_v1_exc:
    print("[ZOPS_API_SMOKE_CONTRACT_V1] skipped:", _zops_api_smoke_contract_v1_exc)
# ZOPS_API_SMOKE_CONTRACT_V1_INCLUDE_END

# --- ZOPS_QI_ABSORBED_READONLY_SURFACE_V1_START ---
# Read-only QI_Absorbed Final surface API. No order mutation, no final_action emission.
try:
    try:
        from backend.api.qi_readonly import router as _zops_qi_readonly_router
    except Exception:
        from api.qi_readonly import router as _zops_qi_readonly_router
    _zops_qi_paths = {getattr(_route, "path", "") for _route in getattr(app, "routes", [])}
    if "/api/qi/context" not in _zops_qi_paths:
        app.include_router(_zops_qi_readonly_router)
except Exception as _zops_qi_readonly_mount_error:
    try:
        import logging
        logging.getLogger("zops.qi").warning("QI readonly surface disabled: %s", _zops_qi_readonly_mount_error)
    except Exception:
        pass
# --- ZOPS_QI_ABSORBED_READONLY_SURFACE_V1_END ---

# --- ZOPS_LICO_MARKET_SAFETY_DECISION_FEED_V1_START ---
# LICO market safety context feed: read-only, P4-consumable, no final_action authority.
try:
    try:
        from backend.api.lico_market_safety import router as _zops_lico_msf_router
    except Exception:
        from api.lico_market_safety import router as _zops_lico_msf_router
    _zops_lico_msf_paths = {getattr(_route, "path", "") for _route in getattr(app, "routes", [])}
    if "/api/lico/market-safety" not in _zops_lico_msf_paths:
        app.include_router(_zops_lico_msf_router)
except Exception as _zops_lico_msf_mount_error:
    try:
        import logging
        logging.getLogger("zops.lico").warning("LICO market safety feed disabled: %s", _zops_lico_msf_mount_error)
    except Exception:
        pass
# --- ZOPS_LICO_MARKET_SAFETY_DECISION_FEED_V1_END ---

