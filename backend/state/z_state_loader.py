from __future__ import annotations

import time
from typing import Any, Dict, TypedDict


class StatePayload(TypedDict, total=False):
    status: str
    equity_usdt: float
    day_pnl_usdt: float
    max_dd_usdt: float
    balances: Dict[str, Any]
    positions: Dict[str, Any]


class StateSnapshot(TypedDict):
    status: str
    ts: float
    state: StatePayload


DEFAULT_STATE: StateSnapshot = {
    "status": "ok",
    "ts": 0.0,
    "state": {
        "status": "ready",
        "equity_usdt": 0.0,
        "day_pnl_usdt": 0.0,
        "max_dd_usdt": 0.0,
        "balances": {},
        "positions": {},
    },
}


def ensure_state_table() -> None:
    return


def load_latest_state() -> StateSnapshot:
    return {
        "status": DEFAULT_STATE["status"],
        "ts": time.time(),
        "state": dict(DEFAULT_STATE["state"]),
    }
