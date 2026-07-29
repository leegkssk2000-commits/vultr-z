from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.contracts.null_error_contract import NULL_ERROR_CONTRACT_VERSION, normalize_reason

BASE_DIR = Path("/home/z/z/backend/data/paper")
PAPER_STATE_LATEST_PATH = BASE_DIR / "paper_state.latest.json"

PROCESS_FN_NAME = "process_signal_to_paper_state"
PROCESS_FN_MODULE = "backend.engine.paper_ledger"

try:
    from backend.engine.lbot_core import (
        CONTRACT_DECISION_ACTIONS,
        CONTRACT_EXECUTOR_STATUSES,
        CONTRACT_RESULT_STATUSES,
        CONTRACT_RUNTIME_MODES,
        CONTRACT_RUNTIME_ROUTES,
        CONTRACT_SIGNAL_IDENTITY_KEYS,
        CONTRACT_STATE_SIDES,
    )
except Exception:
    CONTRACT_SIGNAL_IDENTITY_KEYS = ("event_id", "decision_id", "signal_id")
    CONTRACT_RUNTIME_MODES = ("noop", "dummy", "paper", "shadow", "live")
    CONTRACT_RUNTIME_ROUTES = ("noop", "paper", "live")
    CONTRACT_DECISION_ACTIONS = ("enter", "add", "reduce", "exit", "hold", "block", "noop")
    CONTRACT_RESULT_STATUSES = ("ready", "blocked", "hold", "done", "noop")
    CONTRACT_EXECUTOR_STATUSES = ("ready", "blocked", "hold", "noop", "paper", "live")
    CONTRACT_STATE_SIDES = ("long", "short", "")


# -----------------------------
# basic utils
# -----------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return int(default)
        return int(float(v))
    except Exception:
        return int(default)


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        return str(v)
    except Exception:
        return default


def _norm_side(v: Any) -> str:
    s = _safe_str(v, "").strip().lower()
    if s in ("long", "buy"):
        return "long"
    if s in ("short", "sell"):
        return "short"
    return ""


def _norm_action(v: Any) -> str:
    s = _safe_str(v, "").strip().lower()
    aliases = {
        "enter": "enter",
        "entry": "enter",
        "open": "enter",
        "add": "add",
        "scale_in": "add",
        "pyramid": "add",
        "reduce": "reduce",
        "partial": "reduce",
        "scale_out": "reduce",
        "exit": "exit",
        "close": "exit",
        "flat": "exit",
        "hold": "hold",
        "block": "block",
        "noop": "noop",
    }
    s = aliases.get(s, s)
    return s if s in CONTRACT_DECISION_ACTIONS else ""


def _state_key(symbol: str, strategy: str) -> str:
    return f"{symbol}::{strategy}"



def _norm_mode(v: Any) -> str:
    s = _safe_str(v, "paper").strip().lower()
    return s if s in CONTRACT_RUNTIME_MODES else "paper"


def _norm_route(v: Any) -> str:
    s = _safe_str(v, "paper").strip().lower()
    return s if s in CONTRACT_RUNTIME_ROUTES else "paper"


def _norm_result_status(v: Any, ok: bool = True) -> str:
    s = _safe_str(v, "").strip().lower()
    if s == "applied":
        s = "done"
    if s == "idle":
        s = "noop"
    if s in CONTRACT_RESULT_STATUSES:
        return s
    return "done" if ok else "blocked"


def _norm_executor_status(v: Any, ok: bool = True) -> str:
    s = _safe_str(v, "").strip().lower()
    if s == "applied":
        s = "paper"
    if s == "idle":
        s = "noop"
    if s in CONTRACT_EXECUTOR_STATUSES:
        return s
    return "paper" if ok else "blocked"


def _norm_state_side(v: Any) -> str:
    side = _norm_side(v)
    return side if side in CONTRACT_STATE_SIDES else ""


def _decision_id(signal: Dict[str, Any]) -> str:
    return _safe_str(signal.get("decision_id") or signal.get("signal_id"), "")


def _event_id(signal: Dict[str, Any]) -> str:
    return _safe_str(signal.get("event_id") or signal.get("signal_id"), "")


# -----------------------------
# contract helpers
# -----------------------------
def _binding_check(detail: str = "") -> Dict[str, Any]:
    return {
        "process_fn_found": True,
        "process_fn_name": PROCESS_FN_NAME,
        "process_fn_module": PROCESS_FN_MODULE,
        "process_candidates_found": [
            {"module": PROCESS_FN_MODULE, "name": PROCESS_FN_NAME},
            {"module": PROCESS_FN_MODULE, "name": "get_paper_state"},
        ],
        "detail": detail,
    }


def _event_contract(
    *,
    ok: bool,
    detail: str,
    reason: Optional[str] = None,
    signal_id: str = "",
    event_id: str = "",
    decision_id: str = "",
    symbol: str = "",
    strategy: str = "",
    side: str = "",
    mode: str = "paper",
    route: str = "paper",
    action: str = "hold",
    ts: Any = None,
    position_qty: float = 0.0,
    avg_entry: float = 0.0,
    realized_pnl: float = 0.0,
) -> Dict[str, Any]:
    contract_reason = _safe_str(reason or detail, detail)
    decision_action = _norm_action(action) or "hold"
    written_at = _now_iso()
    runtime_mode = _norm_mode(mode)
    runtime_route = _norm_route(route)
    result_status = _norm_result_status("done" if ok else "blocked", ok=ok)
    executor_status = _norm_executor_status("paper" if ok else "blocked", ok=ok)
    risk_action = decision_action if decision_action in ("hold", "reduce", "exit", "block") else ("hold" if not ok else decision_action)
    return {
        "ok": bool(ok),
        "contract_version": NULL_ERROR_CONTRACT_VERSION,
        "detail": contract_reason,
        "reason": contract_reason,
        "status": result_status,
        "mode": runtime_mode,
        "route": runtime_route,
        "effective_mode": runtime_mode,
        "effective_route": runtime_route,
        "decision_action": decision_action,
        "decision_reason": contract_reason,
        "risk_action": risk_action,
        "executor_status": executor_status,
        "executor_result": "paper_state_updated" if ok else "paper_state_rejected",
        "event_type": "paper_ledger",
        "event_id": event_id or signal_id,
        "decision_id": decision_id or signal_id,
        "signal_id": signal_id,
        "symbol": symbol,
        "strategy": strategy,
        "side": _norm_state_side(side),
        "ts": _safe_int(ts, 0),
        "written_at": written_at,
        "updated_at": written_at,
        "position_qty": _safe_float(position_qty),
        "avg_entry": _safe_float(avg_entry),
        "realized_pnl": _safe_float(realized_pnl),
        "_binding_check": _binding_check(contract_reason),
    }


# -----------------------------
# state shape
# -----------------------------
def _empty_position(symbol: str = "", strategy: str = "") -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "position_side": "",
        "position_qty": 0.0,
        "avg_entry": 0.0,
        "add_count": 0,
        "last_add_price": 0.0,
        "realized_pnl": 0.0,
        "last_signal_id": "",
        "last_action": "hold",
        "updated_at": _now_iso(),
    }


def _empty_state() -> Dict[str, Any]:
    now = _now_iso()
    return {
        "ok": True,
        "detail": "ok",
        "reason": "ok",
        "status": "noop",
        "mode": "paper",
        "route": "paper",
        "effective_mode": "paper",
        "effective_route": "paper",
        "decision_action": "hold",
        "decision_reason": "ok",
        "risk_action": "hold",
        "executor_status": "noop",
        "executor_result": "paper_state_idle",
        "event_type": "paper_state",
        "event_id": "",
        "decision_id": "",
        "signal_id": "",
        "symbol": "",
        "strategy": "",
        "side": "",
        "ts": 0,
        "position_side": "",
        "position_qty": 0.0,
        "avg_entry": 0.0,
        "add_count": 0,
        "last_add_price": 0.0,
        "realized_pnl": 0.0,
        "last_signal_id": "",
        "last_symbol": "",
        "last_strategy": "",
        "last_action": "hold",
        "positions": {},
        "paper_state_selected": None,
        "account": {
            "positions_count": 0,
            "equity": 0.0,
            "exchange": "paper",
        },
        "sync_state": {
            "status": "ok",
            "stale": False,
            "exchange": "paper",
        },
        "written_at": now,
        "updated_at": now,
        "_binding_check": _binding_check("ok"),
    }


def _ensure_dir() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    _ensure_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _sanitize_position(pos: Dict[str, Any], symbol: str, strategy: str) -> Dict[str, Any]:
    out = _empty_position(symbol=symbol, strategy=strategy)
    out["position_side"] = _norm_state_side(pos.get("position_side"))
    out["position_qty"] = _safe_float(pos.get("position_qty"))
    out["avg_entry"] = _safe_float(pos.get("avg_entry"))
    out["add_count"] = _safe_int(pos.get("add_count"), 0)
    out["last_add_price"] = _safe_float(pos.get("last_add_price"))
    out["realized_pnl"] = _safe_float(pos.get("realized_pnl"))
    out["last_signal_id"] = _safe_str(pos.get("last_signal_id"), "")
    out["last_action"] = _norm_action(pos.get("last_action")) or "hold"
    out["updated_at"] = _safe_str(pos.get("updated_at"), _now_iso()) or _now_iso()
    return out


def _select_position(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    selected = state.get("paper_state_selected")
    if isinstance(selected, dict) and selected:
        return deepcopy(selected)

    positions = state.get("positions") or {}
    if not isinstance(positions, dict) or not positions:
        return None

    last_symbol = _safe_str(state.get("last_symbol"), "")
    last_strategy = _safe_str(state.get("last_strategy"), "")
    if last_symbol and last_strategy:
        maybe = positions.get(_state_key(last_symbol, last_strategy))
        if isinstance(maybe, dict):
            return deepcopy(maybe)

    for _, pos in positions.items():
        if isinstance(pos, dict):
            return deepcopy(pos)
    return None


def _mirror_from_selected(state: Dict[str, Any], selected: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = deepcopy(state)
    if not selected:
        out["position_side"] = ""
        out["position_qty"] = 0.0
        out["avg_entry"] = 0.0
        out["add_count"] = 0
        out["last_add_price"] = 0.0
        out["realized_pnl"] = 0.0
        out["paper_state_selected"] = None
        return out

    out["position_side"] = _norm_side(selected.get("position_side"))
    out["position_qty"] = _safe_float(selected.get("position_qty"))
    out["avg_entry"] = _safe_float(selected.get("avg_entry"))
    out["add_count"] = _safe_int(selected.get("add_count"), 0)
    out["last_add_price"] = _safe_float(selected.get("last_add_price"))
    out["realized_pnl"] = _safe_float(selected.get("realized_pnl"))
    out["last_signal_id"] = _safe_str(selected.get("last_signal_id"), "")
    out["last_action"] = _norm_action(selected.get("last_action")) or "hold"
    out["last_symbol"] = _safe_str(selected.get("symbol"), "")
    out["last_strategy"] = _safe_str(selected.get("strategy"), "")
    out["paper_state_selected"] = deepcopy(selected)
    return out


def _recount_account(state: Dict[str, Any]) -> None:
    positions = state.get("positions") or {}
    count = 0
    for _, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        if _safe_float(pos.get("position_qty")) > 0:
            count += 1

    account = state.get("account")
    if not isinstance(account, dict):
        account = {}
        state["account"] = account
    account["positions_count"] = count
    account["equity"] = _safe_float(account.get("equity"))
    account["exchange"] = _safe_str(account.get("exchange"), "paper") or "paper"

    sync_state = state.get("sync_state")
    if not isinstance(sync_state, dict):
        sync_state = {}
        state["sync_state"] = sync_state
    sync_state["status"] = _safe_str(sync_state.get("status"), "ok") or "ok"
    sync_state["stale"] = bool(sync_state.get("stale", False))
    sync_state["exchange"] = _safe_str(sync_state.get("exchange"), "paper") or "paper"


def _normalize_full_state(raw: Dict[str, Any]) -> Dict[str, Any]:
    state = _empty_state()
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k not in ("positions", "account", "sync_state", "paper_state_selected"):
                state[k] = v

    raw_positions = raw.get("positions") if isinstance(raw, dict) else {}
    positions: Dict[str, Any] = {}
    if isinstance(raw_positions, dict):
        for key, pos in raw_positions.items():
            if not isinstance(pos, dict):
                continue
            symbol = _safe_str(pos.get("symbol"), "")
            strategy = _safe_str(pos.get("strategy"), "")
            if not symbol or not strategy:
                if "::" in str(key):
                    symbol, strategy = str(key).split("::", 1)
            if not symbol or not strategy:
                continue
            positions[_state_key(symbol, strategy)] = _sanitize_position(pos, symbol, strategy)

    state["positions"] = positions

    selected = raw.get("paper_state_selected") if isinstance(raw, dict) else None
    if isinstance(selected, dict) and selected:
        s_symbol = _safe_str(selected.get("symbol"), "")
        s_strategy = _safe_str(selected.get("strategy"), "")
        if s_symbol and s_strategy:
            selected = _sanitize_position(selected, s_symbol, s_strategy)
            state["paper_state_selected"] = deepcopy(selected)
            positions[_state_key(s_symbol, s_strategy)] = deepcopy(selected)
    if state.get("paper_state_selected") is None:
        sel = _select_position(state)
        if sel:
            state["paper_state_selected"] = deepcopy(sel)

    state = _mirror_from_selected(state, state.get("paper_state_selected"))
    _recount_account(state)
    state["written_at"] = _safe_str(state.get("written_at"), _now_iso()) or _now_iso()
    state["updated_at"] = _safe_str(state.get("updated_at"), state["written_at"]) or state["written_at"]
    return state


def get_paper_state() -> Dict[str, Any]:
    raw = _load_json(PAPER_STATE_LATEST_PATH)
    return _normalize_full_state(raw)


def save_paper_state(state: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_full_state(state)
    _write_json(PAPER_STATE_LATEST_PATH, normalized)
    return normalized


# -----------------------------
# signal extraction
# -----------------------------
def _extract_signal(req_or_signal: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(req_or_signal, dict):
        return {}
    sig = req_or_signal.get("signal")
    if isinstance(sig, dict):
        return sig
    return req_or_signal


def _extract_mode(req_or_signal: Dict[str, Any]) -> str:
    if not isinstance(req_or_signal, dict):
        return "paper"
    return _safe_str(req_or_signal.get("mode"), "paper") or "paper"


def _extract_route(req_or_signal: Dict[str, Any]) -> str:
    if not isinstance(req_or_signal, dict):
        return "paper"
    return _safe_str(req_or_signal.get("route"), "paper") or "paper"


def _signal_side(signal: Dict[str, Any]) -> str:
    payload = signal.get("payload")
    if isinstance(payload, dict):
        side = _norm_state_side(payload.get("force_side"))
        if side:
            return side
    side = _norm_state_side(signal.get("side"))
    if side:
        return side
    return ""


def _signal_action(signal: Dict[str, Any]) -> str:
    payload = signal.get("payload")
    if isinstance(payload, dict):
        action = _norm_action(payload.get("force_action"))
        if action:
            return action

    action = _norm_action(signal.get("action"))
    if action:
        return action

    side = _signal_side(signal)
    if side == "long":
        return "enter"
    if side == "short":
        return "exit"
    return "hold"


def _signal_size(signal: Dict[str, Any]) -> float:
    payload = signal.get("payload")
    if isinstance(payload, dict) and "force_size" in payload:
        return _safe_float(payload.get("force_size"))
    if "size" in signal:
        return _safe_float(signal.get("size"))
    if "qty" in signal:
        return _safe_float(signal.get("qty"))
    return 0.0


def _signal_price(signal: Dict[str, Any]) -> float:
    payload = signal.get("payload")
    if isinstance(payload, dict) and "force_entry" in payload:
        return _safe_float(payload.get("force_entry"))
    return _safe_float(signal.get("price"))


# -----------------------------
# position transitions
# -----------------------------
def _apply_enter(pos: Dict[str, Any], size: float, price: float, side: str, signal_id: str) -> None:
    pos["position_side"] = side
    pos["position_qty"] = max(size, 0.0)
    pos["avg_entry"] = price if size > 0 else 0.0
    pos["add_count"] = 0
    pos["last_add_price"] = 0.0
    pos["last_signal_id"] = signal_id
    pos["last_action"] = "enter"
    pos["updated_at"] = _now_iso()


def _apply_add(pos: Dict[str, Any], size: float, price: float, side: str, signal_id: str) -> None:
    cur_qty = _safe_float(pos.get("position_qty"))
    cur_avg = _safe_float(pos.get("avg_entry"))
    if cur_qty <= 0:
        _apply_enter(pos, size=size, price=price, side=side, signal_id=signal_id)
        return

    add_qty = max(size, 0.0)
    new_qty = cur_qty + add_qty
    new_avg = ((cur_qty * cur_avg) + (add_qty * price)) / new_qty if new_qty > 0 else 0.0

    pos["position_side"] = side or _norm_side(pos.get("position_side")) or "long"
    pos["position_qty"] = new_qty
    pos["avg_entry"] = new_avg
    pos["add_count"] = _safe_int(pos.get("add_count"), 0) + 1
    pos["last_add_price"] = price
    pos["last_signal_id"] = signal_id
    pos["last_action"] = "add"
    pos["updated_at"] = _now_iso()


def _apply_reduce(pos: Dict[str, Any], size: float, price: float, signal_id: str) -> None:
    cur_qty = _safe_float(pos.get("position_qty"))
    cur_avg = _safe_float(pos.get("avg_entry"))
    side = _norm_side(pos.get("position_side"))

    if cur_qty <= 0:
        pos["last_signal_id"] = signal_id
        pos["last_action"] = "hold"
        pos["updated_at"] = _now_iso()
        return

    reduce_qty = min(cur_qty, max(size, 0.0))
    remain_qty = cur_qty - reduce_qty
    realized = _safe_float(pos.get("realized_pnl"))
    if side == "long":
        realized += (price - cur_avg) * reduce_qty
    elif side == "short":
        realized += (cur_avg - price) * reduce_qty

    pos["realized_pnl"] = realized
    pos["position_qty"] = remain_qty
    pos["last_signal_id"] = signal_id
    pos["last_action"] = "reduce"
    pos["updated_at"] = _now_iso()

    if remain_qty <= 0:
        pos["position_side"] = ""
        pos["position_qty"] = 0.0
        pos["avg_entry"] = 0.0
        pos["last_add_price"] = 0.0
    else:
        pos["position_side"] = side


def _apply_exit(pos: Dict[str, Any], price: float, signal_id: str) -> None:
    cur_qty = _safe_float(pos.get("position_qty"))
    cur_avg = _safe_float(pos.get("avg_entry"))
    side = _norm_side(pos.get("position_side"))

    realized = _safe_float(pos.get("realized_pnl"))
    if cur_qty > 0:
        if side == "long":
            realized += (price - cur_avg) * cur_qty
        elif side == "short":
            realized += (cur_avg - price) * cur_qty

    pos["position_side"] = ""
    pos["position_qty"] = 0.0
    pos["avg_entry"] = 0.0
    pos["last_add_price"] = 0.0
    pos["realized_pnl"] = realized
    pos["last_signal_id"] = signal_id
    pos["last_action"] = "exit"
    pos["updated_at"] = _now_iso()


# -----------------------------
# main
# -----------------------------
def process_signal_to_paper_state(req_or_signal: Dict[str, Any]) -> Dict[str, Any]:
    state = get_paper_state()
    signal = _extract_signal(req_or_signal)
    mode = _extract_mode(req_or_signal)
    route = _extract_route(req_or_signal)

    if not signal:
        state.update(
            _event_contract(
                ok=False,
                detail="empty_signal",
                reason="empty_signal",
                mode=mode,
                route=route,
                action="hold",
            )
        )
        return save_paper_state(state)

    symbol = _safe_str(signal.get("symbol"), "")
    strategy = _safe_str(signal.get("strategy"), "")
    signal_id = _safe_str(signal.get("signal_id"), "")
    event_id = _event_id(signal)
    decision_id = _decision_id(signal)
    side = _signal_side(signal)
    action = _signal_action(signal)
    size = _signal_size(signal)
    price = _signal_price(signal)
    ts = signal.get("ts")

    if not symbol or not strategy:
        state.update(
            _event_contract(
                ok=False,
                detail="missing_symbol_or_strategy",
                reason="missing_symbol_or_strategy",
                signal_id=signal_id,
                event_id=event_id,
                decision_id=decision_id,
                symbol=symbol,
                strategy=strategy,
                side=side,
                mode=mode,
                route=route,
                action="hold",
                ts=ts,
            )
        )
        return save_paper_state(state)

    key = _state_key(symbol, strategy)
    positions = state.get("positions")
    if not isinstance(positions, dict):
        positions = {}
        state["positions"] = positions

    current = positions.get(key)
    if not isinstance(current, dict):
        current = _empty_position(symbol=symbol, strategy=strategy)
    pos = _sanitize_position(current, symbol=symbol, strategy=strategy)

    # infer add/reduce/exit from existing position
    cur_qty = _safe_float(pos.get("position_qty"))
    cur_side = _norm_side(pos.get("position_side"))

    # same-key same-side re-entry -> add
    if action == "enter" and cur_qty > 0 and side and cur_side and side == cur_side:
        action = "add"

    # opposite-side signal currently comes in as exit from _signal_action();
    # split it into partial reduce vs full exit by comparing incoming size to current qty
    if action == "exit" and cur_qty > 0 and side and cur_side and side != cur_side:
        if 0.0 < size < cur_qty:
            action = "reduce"
        else:
            action = "exit"

    # contract-safe guards
    if action in ("enter", "add", "reduce") and size <= 0:
        state.update(
            _event_contract(
                ok=False,
                detail="invalid_size",
                reason="invalid_size",
                signal_id=signal_id,
                event_id=event_id,
                decision_id=decision_id,
                symbol=symbol,
                strategy=strategy,
                side=side,
                mode=mode,
                route=route,
                action="hold",
                ts=ts,
                position_qty=pos.get("position_qty", 0.0),
                avg_entry=pos.get("avg_entry", 0.0),
                realized_pnl=pos.get("realized_pnl", 0.0),
            )
        )
        return save_paper_state(state)

    if action in ("enter", "add", "reduce", "exit") and price <= 0:
        state.update(
            _event_contract(
                ok=False,
                detail="invalid_price",
                reason="invalid_price",
                signal_id=signal_id,
                event_id=event_id,
                decision_id=decision_id,
                symbol=symbol,
                strategy=strategy,
                side=side,
                mode=mode,
                route=route,
                action="hold",
                ts=ts,
                position_qty=pos.get("position_qty", 0.0),
                avg_entry=pos.get("avg_entry", 0.0),
                realized_pnl=pos.get("realized_pnl", 0.0),
            )
        )
        return save_paper_state(state)

    if action == "enter":
        _apply_enter(pos, size=size, price=price, side=side or "long", signal_id=signal_id)
    elif action == "add":
        _apply_add(pos, size=size, price=price, side=side or _norm_side(pos.get("position_side")) or "long", signal_id=signal_id)
    elif action == "reduce":
        _apply_reduce(pos, size=size, price=price, signal_id=signal_id)
    elif action == "exit":
        _apply_exit(pos, price=price, signal_id=signal_id)
    else:
        pos["last_signal_id"] = signal_id or _safe_str(pos.get("last_signal_id"), "")
        pos["last_action"] = "hold"
        pos["updated_at"] = _now_iso()

    state["last_symbol"] = symbol
    state["last_strategy"] = strategy
    state["last_signal_id"] = _safe_str(pos.get("last_signal_id"), "")
    state["last_action"] = _norm_action(pos.get("last_action")) or "hold"
    state["event_id"] = event_id or signal_id
    state["decision_id"] = decision_id or signal_id

    if _safe_float(pos.get("position_qty")) <= 0:
        positions.pop(key, None)
        state["paper_state_selected"] = None
        if isinstance(state.get("selected"), dict):
            selected_alias = state.get("selected") or {}
            alias_key = _state_key(
                _safe_str(selected_alias.get("symbol"), ""),
                _safe_str(selected_alias.get("strategy"), ""),
            )
            if alias_key == key:
                state["selected"] = None
        next_selected = _select_position(state)
        state["paper_state_selected"] = deepcopy(next_selected) if next_selected else None
    else:
        positions[key] = deepcopy(pos)
        state["paper_state_selected"] = deepcopy(pos)

    state = _mirror_from_selected(state, state["paper_state_selected"])
    _recount_account(state)

    state.update(
        _event_contract(
            ok=True,
            detail="paper_state_updated",
            reason=_safe_str(pos.get("last_action"), action) or action or "hold",
            signal_id=signal_id,
            symbol=symbol,
            strategy=strategy,
            side=side,
            mode=mode,
            route=route,
            action=_safe_str(pos.get("last_action"), action) or action or "hold",
            ts=ts,
            position_qty=pos.get("position_qty", 0.0),
            avg_entry=pos.get("avg_entry", 0.0),
            realized_pnl=pos.get("realized_pnl", 0.0),
        )
    )
    state["executor_status"] = _norm_executor_status(state.get("executor_status"), ok=True)
    state["status"] = _norm_result_status(state.get("status"), ok=True)
    state["executor_result"] = "paper_state_updated"
    state["written_at"] = _now_iso()
    state["updated_at"] = state["written_at"]
    state["_last_event_meta"] = {
        "mode": _norm_mode(mode),
        "route": _norm_route(route),
        "event_id": event_id or signal_id,
        "decision_id": decision_id or signal_id,
        "signal_id": signal_id,
        "symbol": symbol,
        "strategy": strategy,
        "action": action,
    }

    return save_paper_state(state)


def process(req_or_signal: Dict[str, Any]) -> Dict[str, Any]:
    return process_signal_to_paper_state(req_or_signal)

__all__ = [
    "process_signal_to_paper_state",
    "process",
    "get_paper_state",
    "save_paper_state",
]
