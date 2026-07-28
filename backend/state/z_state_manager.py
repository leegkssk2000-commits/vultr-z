from __future__ import annotations

"""
z_state_manager.py (robust redesign for unified backend/state)

Primary responsibilities:
  - Maintain a minimal, stable account/risk state backbone for API/PWA.
  - Persist state to a JSON file (state.json).
  - Provide a singleton STATE_MANAGER with tolerant update_state.

Compatibility goals:
  - Preserve existing public surface used across the codebase:
      * STATE_MANAGER
      * ZStateManager.update_state(...)
      * ZStateManager.snapshot()
      * load_state_from_disk()
      * save_state_to_disk()
      * init_state_if_needed()
      * get_state_for_api()
      * update_state(...) # module-level helper supporting **kwargs
  - Never raise due to wrong payload types or unexpected kwargs.
  - Keep /api/v1/state response shape stable.

Notes:
  - File-based state is the default truth source.
  - Legacy DB snapshot helpers are optional and isolated.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------
# Optional legacy imports (do not break if missing)
# ---------------------------------------------------------------------

try:
    from .db_access import get_conn # type: ignore
except Exception: # pragma: no cover
    get_conn = None # type: ignore

try:
    from .z_state_loader import ( # type: ignore
        StatePayload,
        StateSnapshot,
        DEFAULT_STATE as LOADER_DEFAULT_SNAPSHOT,
        ensure_state_table,
        load_latest_state,
    )
except Exception: # pragma: no cover
    StatePayload = Dict[str, Any] # type: ignore
    StateSnapshot = Dict[str, Any] # type: ignore
    LOADER_DEFAULT_SNAPSHOT = {"status": "ok", "ts": 0.0, "state": {}} # type: ignore

    def ensure_state_table() -> None: # type: ignore
        return

    def load_latest_state() -> Dict[str, Any]: # type: ignore
        return LOADER_DEFAULT_SNAPSHOT # type: ignore


# Optional engine DB connector (kept harmless if missing)
try:
    from engine.state.z_state_db import ZStateDB, get_state_conn # type: ignore
except Exception: # pragma: no cover
    ZStateDB = None # type: ignore

    def get_state_conn(): # type: ignore
        return None


# ---------------------------------------------------------------------
# File-based state backbone
# ---------------------------------------------------------------------

STATE_FILE = os.getenv("Z_STATE_FILE", "/home/z/z/backend/state.json")

# Minimal account/risk backbone
FILE_DEFAULT_STATE: Dict[str, Any] = {
    "status": "ready",
    "equity_usdt": 0.0,
    "day_pnl_usdt": 0.0,
    "max_dd_usdt": 0.0,
    "quiet_hours": False,

    # Compatibility/min-shape for account-oriented consumers
    "balances": {},
    "positions": {},
}

# Module-level cache for legacy helper functions
_state: Optional[Dict[str, Any]] = None


def _safe_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _ensure_min_shape(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Guarantee minimal, stable state shape:
      - merges given input over FILE_DEFAULT_STATE
      - ensures balances/positions are dict
    """
    base = FILE_DEFAULT_STATE.copy()
    if isinstance(state, dict):
        base.update(state)

    if not isinstance(base.get("balances"), dict):
        base["balances"] = {}
    if not isinstance(base.get("positions"), dict):
        base["positions"] = {}

    return base


def load_state_from_disk() -> Optional[Dict[str, Any]]:
    """
    Returns:
      - dict when a valid JSON dict exists
      - None when file is missing
      - {} when file exists but content is invalid
    """
    try:
        if not os.path.exists(STATE_FILE):
            return None
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state_to_disk(state: Dict[str, Any]) -> None:
    """Persist current state to state.json."""
    try:
        Path(os.path.dirname(STATE_FILE)).mkdir(parents=True, exist_ok=True)
        norm = _ensure_min_shape(_safe_dict(state))
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(norm, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def init_state_if_needed() -> bool:
    """
    Initializes module-level _state for legacy callers.
    The class-based STATE_MANAGER is the preferred interface.
    """
    global _state

    if isinstance(_state, dict) and _state:
        _state = _ensure_min_shape(_state)
        return True

    disk_state = load_state_from_disk()

    if not disk_state:
        _state = FILE_DEFAULT_STATE.copy()
        save_state_to_disk(_state)
    else:
        _state = _ensure_min_shape(_safe_dict(disk_state))
        save_state_to_disk(_state)

    return True


def get_state_for_api() -> Dict[str, Any]:
    """
    PWA/dashboard uses this to fetch a stable state snapshot.
    Always uses the latest state.json as the truth source.
    """
    try:
        state = load_state_from_disk()
    except Exception:
        state = None

    merged = _ensure_min_shape(_safe_dict(state))

    return {
        "status": "ok",
        "ts": time.time(),
        "state": merged,
    }


# ---------------------------------------------------------------------
# Class-based manager (preferred API)
# ---------------------------------------------------------------------

class ZStateManager:
    """
    - state.json <-> in-memory state manager

    Public API:
      - update_state(payload: dict | None = None, **kwargs)
      - snapshot() -> dict
      - get_state() -> dict
      - set_state(state: dict | None = None, **kwargs)
    """

    def __init__(self, state_file: str = STATE_FILE) -> None:
        self._state_file = state_file
        self._state: Dict[str, Any] = self._load_initial_state()

    # ---- internal -----------------------------------------------------

    def _load_initial_state(self) -> Dict[str, Any]:
        if not os.path.exists(self._state_file):
            return _ensure_min_shape({})
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _ensure_min_shape({})
            return _ensure_min_shape(data)
        except Exception:
            return _ensure_min_shape({})

    def _persist(self) -> None:
        try:
            Path(os.path.dirname(self._state_file)).mkdir(parents=True, exist_ok=True)
            self._state = _ensure_min_shape(self._state)
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---- public -------------------------------------------------------

    def get_state(self) -> Dict[str, Any]:
        return _ensure_min_shape(self._state).copy()

    def set_state(self, state: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        """
        Compatibility setter.
        Accepts dict payload and/or kwargs and replaces/merges safely.
        """
        data: Dict[str, Any] = {}
        if isinstance(state, dict):
            data.update(state)
        if kwargs:
            data.update(kwargs)

        if not data:
            self._state = _ensure_min_shape(self._state)
            self._persist()
            return

        base = _ensure_min_shape({})
        base.update(_safe_dict(data))
        self._state = _ensure_min_shape(base)

        self._persist()

        global _state
        _state = self._state.copy()

    def update_state(
        self,
        payload: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Merge payload/kwargs into current state and persist.

        Defensive rules:
          - Ignore non-dict payload.
          - Skip None values.
          - Keep unknown keys.
        """
        data: Dict[str, Any] = {}

        if isinstance(payload, dict):
            data.update(payload)
        if kwargs:
            data.update(kwargs)

        if not data:
            self._state = _ensure_min_shape(self._state)
            self._persist()
            return

        for k, v in data.items():
            if v is None:
                continue
            self._state[k] = v

        self._state = _ensure_min_shape(self._state)

        self._persist()

        global _state
        _state = self._state.copy()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "ts": time.time(),
            "state": self.get_state(),
        }


# External singleton
STATE_MANAGER = ZStateManager()


# ---------------------------------------------------------------------
# Legacy DB snapshot helpers (isolated)
# ---------------------------------------------------------------------

def _merge_state(old: StateSnapshot, delta: StatePayload) -> StatePayload:
    base_state = _safe_dict(LOADER_DEFAULT_SNAPSHOT.get("state", {}))
    merged: StatePayload = dict(base_state)
    merged.update(_safe_dict(old.get("state", {})))
    for k, v in (delta or {}).items():
        merged[k] = v

    # Prevent schema drift when DB path is used
    return _ensure_min_shape(_safe_dict(merged)) # type: ignore


def _insert_snapshot(payload: StatePayload) -> StateSnapshot:
    ts = time.time()
    snap: StateSnapshot = {
        "status": "ok",
        "ts": ts,
        "state": payload,
    }

    try:
        ensure_state_table()
        if get_conn is None:
            return snap

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO z_state (ts, payload_json) VALUES (?, ?)",
                (ts, json.dumps(payload)),
            )
            conn.commit()
    except Exception:
        pass

    return snap


# ---------------------------------------------------------------------
# Public module-level helpers (compat 강화)
# ---------------------------------------------------------------------

def update_state(payload: Optional[Dict[str, Any]] = None, **kwargs: Any) -> bool:
    """
    Compatibility helper.
    Delegates to STATE_MANAGER (file-based).
    """
    data: Dict[str, Any] = {}
    if isinstance(payload, dict):
        data.update(payload)
    if kwargs:
        data.update(kwargs)

    if not data:
        STATE_MANAGER.update_state({})
        return True

    STATE_MANAGER.update_state(data)
    return True


def update_state_db(delta: Optional[Dict[str, Any]] = None) -> StateSnapshot:
    """
    Legacy DB update entrypoint.
    Safe no-op fallback when DB layer is not configured.
    """
    delta = delta or {}
    current = load_latest_state()
    merged = _merge_state(current, delta) # type: ignore
    return _insert_snapshot(merged) # type: ignore


# ---- 추가 호환 API: 일부 코드가 모듈 함수만 기대할 수 있음 ----

def get_state() -> Dict[str, Any]:
    """Module-level alias for STATE_MANAGER.get_state()."""
    return STATE_MANAGER.get_state()


def set_state(state: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
    """Module-level alias for STATE_MANAGER.set_state()."""
    STATE_MANAGER.set_state(state, **kwargs)


def snapshot() -> Dict[str, Any]:
    """Module-level alias for STATE_MANAGER.snapshot()."""
    return STATE_MANAGER.snapshot()
