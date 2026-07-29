# -*- coding: utf-8 -*-
"""backend.config.settings

L4-grade settings module: single source of truth for runtime configuration.

Key constraints this module satisfies:
- Import-safe: no side effects beyond reading env / optional JSON.
- Deterministic exports: all expected constants exist at import time.
- Backward compatible: legacy symbol aliases & flags preserved.
- Works with: ``from backend.config.settings import <NAME>`` and ``import *`` via __all__.

Place this file at: backend/config/settings.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# =============================================================================
# Project paths
# =============================================================================

# This file is expected at: <PROJECT_ROOT>/backend/config/settings.py
_BACKEND_CONFIG_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _BACKEND_CONFIG_DIR.parent
PROJECT_ROOT = _BACKEND_DIR.parent


# =============================================================================
# Environment helpers
# =============================================================================

def get(key: str, default: Optional[str] = None) -> Optional[str]:
    """Thin wrapper for os.getenv to keep call sites uniform."""
    return os.getenv(key, default)


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "t", "yes", "y", "on"):
            return True
        if v in ("0", "false", "f", "no", "n", "off"):
            return False
    return default


def _env_str(key: str, default: str = "") -> str:
    v = os.getenv(key)
    return default if v is None else str(v)


def _env_int(key: str, default: int = 0) -> int:
    v = os.getenv(key)
    if v is None:
        return default
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    v = os.getenv(key)
    if v is None:
        return default
    try:
        return float(str(v).strip())
    except Exception:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    return _coerce_bool(os.getenv(key), default)


def _parse_csv(value: str) -> List[str]:
    items = []
    for raw in (value or "").split(","):
        s = raw.strip()
        if s:
            items.append(s)
    return items


# =============================================================================
# Secrets loader
# =============================================================================

# The control/start.json is treated as an optional local secrets/params file.
# Env vars always win over file values.
START_FILE = Path(_env_str("START_FILE", str(PROJECT_ROOT / "control" / "start.json")))


def load_secrets() -> Dict[str, Any]:
    """Load secrets/params JSON (best effort). Returns {} if missing/invalid."""
    p = Path(_env_str("SECRETS_FILE", _env_str("SECRETS_PATH", str(START_FILE))))
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


SECRETS: Dict[str, Any] = load_secrets()


def sget(key: str, default: Any = None) -> Any:
    """Get value from SECRETS dict (best effort)."""
    try:
        return SECRETS.get(key, default)
    except Exception:
        return default


# =============================================================================
# Core runtime flags
# =============================================================================

DEBUG: bool = _env_bool("DEBUG", _coerce_bool(sget("DEBUG", None), False))
DEBUG_SQL: bool = _env_bool("DEBUG_SQL", _coerce_bool(sget("DEBUG_SQL", None), False))

DRY_RUN: bool = _env_bool("DRY_RUN", _coerce_bool(sget("DRY_RUN", None), True))
LIVE_ROUTE: bool = _env_bool("LIVE_ROUTE", _coerce_bool(sget("LIVE_ROUTE", None), False))

# Mutual exclusion guard: if DRY_RUN is True, we must not live-route orders.
if DRY_RUN and LIVE_ROUTE:
    LIVE_ROUTE = False


# =============================================================================
# API (backend.api) defaults
# =============================================================================
# NOTE:
# - If your code imports `backend.api`, ensure a shim exists at backend/api.py
# that re-exports backend.engine.api (see provided api.py shim).

API_HOST: str = _env_str("API_HOST", str(sget("API_HOST", "0.0.0.0") or "0.0.0.0"))
API_PORT: int = _env_int("API_PORT", int(sget("API_PORT", 8000) or 8000))

_default_base = f"http://{API_HOST}:{API_PORT}"
API_BASE_URL: str = _env_str("API_BASE_URL", str(sget("API_BASE_URL", _default_base) or _default_base))


# =============================================================================
# Database / storage paths
# =============================================================================

STORAGE_DIR = Path(_env_str("STORAGE_DIR", str(PROJECT_ROOT / "storage")))
FILES_DIR = Path(_env_str("FILES_DIR", str(STORAGE_DIR / "files")))

# Primary DB path (project-local sqlite by default)
DB_PATH = Path(_env_str("DB_PATH", str(PROJECT_ROOT / "queue" / "db.sqlite3")))
QUEUE_DB_PATH = DB_PATH # legacy alias kept for compatibility

# Optional DB URL (e.g., Postgres). Empty string means "unused".
DATABASE_URL: str = _env_str("DATABASE_URL", _env_str("DB_URL", str(sget("DATABASE_URL", "") or "")))


# =============================================================================
# Symbol universe (execution layer expects these)
# =============================================================================

# Canonical universe list
_symbols_raw = _env_str("SYMBOLS", str(sget("SYMBOLS", "") or ""))
SYMBOLS: List[str] = _parse_csv(_symbols_raw)

# ---- SOL compatibility (RESTORED) ------------------------------------------
# Symbol aliases (do NOT remove - used by legacy execution / strategies)
SOL = "SOL"
SOL_USDT = "SOL-USDT"

# Feature / debug flags expected by execution layer
DEBUG_SOL: bool = _env_bool("DEBUG_SOL", _coerce_bool(sget("DEBUG_SOL", None), False))
ENABLE_SOL: bool = _env_bool("ENABLE_SOL", _coerce_bool(sget("ENABLE_SOL", None), True))
TRADE_SOL: bool = _env_bool("TRADE_SOL", _coerce_bool(sget("TRADE_SOL", None), True))

# Ensure SOL is always present in symbol universe (when enabled)
if ENABLE_SOL and SOL_USDT not in SYMBOLS:
    SYMBOLS.append(SOL_USDT)

# De-dup while preserving order
_seen: Set[str] = set()
SYMBOLS = [s for s in SYMBOLS if not (s in _seen or _seen.add(s))]


# =============================================================================
# Equity / Risk defaults
# =============================================================================

# Reconcile / RiskEngine default equity window (days); env override supported.
DEFAULT_EQUITY_WINDOW_DAYS: int = _env_int(
    "DEFAULT_EQUITY_WINDOW_DAYS",
    int(sget("DEFAULT_EQUITY_WINDOW_DAYS", 30) or 30),
)


# =============================================================================
# Export surface (__all__)
# =============================================================================

def _build_all() -> List[str]:
    export: Set[str] = set()

    # Explicit helpers / core objects referenced across layers
    export.update(
        {
            "get",
            "sget",
            "load_secrets",
            "SECRETS",
            "PROJECT_ROOT",
            "START_FILE",
        }
    )

    # Add all UPPERCASE constants automatically
    g = globals()
    for name, value in g.items():
        if not name:
            continue
        if name.startswith("_"):
            continue
        if name.isupper():
            export.add(name)

    # Stable order (deterministic for import * debugging)
    preferred_order = [
        # helpers
        "get",
        "sget",
        "load_secrets",
        "SECRETS",
        # paths
        "PROJECT_ROOT",
        "START_FILE",
        "STORAGE_DIR",
        "FILES_DIR",
        "DB_PATH",
        "QUEUE_DB_PATH",
        "DATABASE_URL",
        # flags
        "DEBUG",
        "DEBUG_SQL",
        "DRY_RUN",
        "LIVE_ROUTE",
        # api
        "API_HOST",
        "API_PORT",
        "API_BASE_URL",
        # symbols
        "SYMBOLS",
        "SOL",
        "SOL_USDT",
        "DEBUG_SOL",
        "ENABLE_SOL",
        "TRADE_SOL",
        # risk
        "DEFAULT_EQUITY_WINDOW_DAYS",
    ]

    ordered: List[str] = []
    for name in preferred_order:
        if name in export:
            ordered.append(name)
            export.remove(name)

    # Append remaining exports in sorted order
    ordered.extend(sorted(export))
    return ordered


__all__ = _build_all()