from __future__ import annotations

from fastapi import APIRouter
from .core_api import router as core_router
from .frontend_compat import router as frontend_compat_router

router = APIRouter()
router.include_router(core_router)
router.include_router(frontend_compat_router)

__all__ = ["router"]
