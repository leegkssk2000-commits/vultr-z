from __future__ import annotations

from fastapi import APIRouter

from .core_api import router as core_router
from .frontend_compat import router as frontend_compat_router


# Explicitly copy authoritative child routes. In the active FastAPI runtime,
# nesting these already-populated routers through include_router produced a
# single empty-path placeholder and caused main.py to accept a hollow router.
router = APIRouter()
router.routes.extend(core_router.routes)
router.routes.extend(frontend_compat_router.routes)

if not router.routes:
    raise RuntimeError("BACKEND_PACKAGE_ROUTER_EMPTY")

__all__ = ["router"]
