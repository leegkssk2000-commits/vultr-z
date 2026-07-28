from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

NULL_ERROR_CONTRACT_VERSION = "14.5.7b.v1"
EMPTY_TEXT = ""
PLACEHOLDER_TEXT = "—"
READY_UI_STATE = "ready"
ERROR_UI_STATE = "error"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def safe_str(value: Any, default: str = EMPTY_TEXT) -> str:
    if value is None:
        return default
    try:
        text = str(value).strip()
    except Exception:
        return default
    return text if text else default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        if out != out:
            return float(default)
        return out
    except Exception:
        return float(default)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
        if raw in {"0", "false", "no", "n", "off"}:
            return False
    return default


def safe_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def safe_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def coalesce(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return default


def normalize_reason(detail: Any = None, reason: Any = None, default: str = "ok") -> str:
    return safe_str(coalesce(reason, detail, default=default), default)


def normalize_text(value: Any, default: str = PLACEHOLDER_TEXT) -> str:
    return safe_str(value, default)


def normalize_error_contract(
    *,
    detail: Any = None,
    reason: Any = None,
    error_code: Any = None,
    status: str = ERROR_UI_STATE,
    extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "ok": False,
        "detail": normalize_reason(detail=detail, reason=reason, default="error"),
        "reason": normalize_reason(detail=detail, reason=reason, default="error"),
        "error_code": safe_str(error_code, "contract_error"),
        "status": safe_str(status, ERROR_UI_STATE),
        "contract_version": NULL_ERROR_CONTRACT_VERSION,
        "written_at": now_iso(),
    }
    if extras:
        payload.update(extras)
    return payload


def normalize_collection_response(items: Any, *, ok: bool = True, reason: str = "ok") -> Dict[str, Any]:
    normalized_items = safe_list(items)
    return {
        "ok": bool(ok),
        "reason": safe_str(reason, "ok"),
        "detail": safe_str(reason, "ok"),
        "status": READY_UI_STATE if ok else ERROR_UI_STATE,
        "count": len(normalized_items),
        "items": normalized_items,
        "contract_version": NULL_ERROR_CONTRACT_VERSION,
        "written_at": now_iso(),
    }
