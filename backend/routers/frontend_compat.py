from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter


router = APIRouter(prefix="/api/frontend-compat", tags=["frontend-compat"])


@router.get("/status")
def frontend_compat_status() -> Dict[str, Any]:
    return {
        "status": "ready_read_only",
        "compatibility_only": True,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }


@router.get("/health")
def frontend_compat_health() -> Dict[str, Any]:
    return {"ok": True, "mode": "read_only", "order_authority": "BLOCKED"}
