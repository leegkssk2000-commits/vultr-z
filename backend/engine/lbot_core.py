from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from backend.engine.ingress_guard import validate_signal_envelope
from backend.engine.execution.execution_router import ExecutionRouter


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_ROOT = BASE_DIR / "data"
JOURNAL_DIR = DATA_ROOT / "journal"
PAPER_DIR = DATA_ROOT / "paper"
SETTINGS_FILE = DATA_ROOT / "settings" / "lbot_settings.json"

JOURNAL_LATEST = JOURNAL_DIR / "lbot_event.latest.json"
PAPER_STATE_LATEST = PAPER_DIR / "paper_state.latest.json"

CONTRACT_IDENTITY_KEYS = ("event_id", "decision_id", "signal_id")
CONTRACT_MODES = ("noop", "dummy", "paper", "shadow", "live")
CONTRACT_ROUTES = ("noop", "paper", "live")
CONTRACT_INGRESS_SIDES = ("buy", "sell", "long", "short", "exit")
CONTRACT_STATE_SIDES = ("", "long", "short")
CONTRACT_DECISION_ACTIONS = ("enter", "add", "reduce", "exit", "hold", "block", "noop")
CONTRACT_RUNTIME_MODES = ("noop", "dummy", "paper", "shadow", "live")
CONTRACT_RUNTIME_ROUTES = ("noop", "paper", "live")

CONTRACT_RISK_ACTIONS = ("hold", "block", "reduce25", "partial30", "stop", "rollback", "route_change")
CONTRACT_EXECUTOR_STATUSES = ("ready", "blocked", "hold", "noop", "paper", "live")
CONTRACT_EVENT_STATUSES = ("ready", "blocked", "hold", "done", "noop")
CONTRACT_RESULT_REQUIRED_KEYS = (
    "ok",
    "detail",
    "reason",
    "status",
    "event_id",
    "decision_id",
    "signal_id",
    "decision_action",
    "decision_reason",
    "risk_action",
    "executor_status",
    "executor_result",
    "effective_mode",
    "effective_route",
    "event_type",
    "symbol",
    "strategy",
    "side",
    "ts",
    "written_at",
)

VALID_SIDES = set(CONTRACT_INGRESS_SIDES)
VALID_MODES = set(CONTRACT_MODES)
VALID_ROUTES = set(CONTRACT_ROUTES)
VALID_DECISION_ACTIONS = set(CONTRACT_DECISION_ACTIONS)
VALID_RISK_ACTIONS = set(CONTRACT_RISK_ACTIONS)
VALID_EXECUTOR_STATUSES = set(CONTRACT_EXECUTOR_STATUSES)
VALID_EVENT_STATUSES = set(CONTRACT_EVENT_STATUSES)


def _safe_dict(v: Any) -> Dict[str, Any]:
    return dict(v) if isinstance(v, dict) else {}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        return str(v).strip()
    except Exception:
        return default


def _coalesce(*vals: Any) -> Any:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str):
            if v.strip() == "":
                continue
            return v
        return v
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _ts_to_iso(ts: Any) -> str:
    n = _safe_int(ts)
    if n > 0:
        try:
            return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
        except Exception:
            pass
    return _now_iso()


def _ensure_dirs() -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    PAPER_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        f.write("\n")


def _journal_daily_path(ts: int) -> Path:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return JOURNAL_DIR / f"lbot_events_{dt.strftime('%Y%m%d')}.jsonl"


def _import_optional(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def _find_attr(module_name: str, attr_name: str) -> Tuple[Any, Any]:
    mod = _import_optional(module_name)
    if mod is None:
        return None, None
    return mod, getattr(mod, attr_name, None)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _load_runtime_settings() -> Dict[str, Any]:
    settings = _read_json(SETTINGS_FILE)
    if not isinstance(settings, dict):
        settings = {}
    return settings


def _configured_mode_route(norm: Dict[str, Any], settings: Dict[str, Any]) -> Tuple[str, str]:
    mode = _safe_str(settings.get("mode"), norm.get("mode", "dummy")).lower()
    route = _safe_str(settings.get("route"), norm.get("route", "paper")).lower()

    if mode not in VALID_MODES:
        mode = _safe_str(norm.get("mode"), "dummy").lower()
    if route not in VALID_ROUTES:
        route = _safe_str(norm.get("route"), "paper").lower()

    return mode, route


def _live_trading_enabled(settings: Dict[str, Any]) -> bool:
    env_enabled = os.getenv("Z_LIVE_TRADING_ENABLED", "0").strip() == "1"
    settings_enabled = _safe_bool(settings.get("exchange_enabled"), False)
    return env_enabled and settings_enabled


def _normalize_ingress_side(raw_side: Any) -> str:
    side = _safe_str(raw_side).lower()
    if side in VALID_SIDES:
        return side
    return ""


def _to_execution_side(raw_side: Any) -> str:
    side = _normalize_ingress_side(raw_side)
    if side == "exit":
        return "sell"
    if side in {"buy", "sell"}:
        return side
    if side == "long":
        return "buy"
    if side == "short":
        return "sell"
    return ""


def _to_state_side(raw_side: Any) -> str:
    side = _normalize_ingress_side(raw_side)
    if side in {"long", "short"}:
        return side
    if side == "buy":
        return "long"
    if side in {"sell", "exit"}:
        return "short"
    return ""


def _normalize_side(raw_side: Any) -> str:
    return _normalize_ingress_side(raw_side)


def _display_side(raw_side: Any) -> str:
    side = _normalize_ingress_side(raw_side)
    if side in {"long", "buy"}:
        return "Long"
    if side in {"short", "sell"}:
        return "Short"
    if side == "exit":
        return "Exit"
    return _safe_str(raw_side)


def _normalize_signal(signal: Dict[str, Any]) -> Dict[str, Any]:
    signal_id = _safe_str(signal.get("signal_id"))
    event_id = _safe_str(signal.get("event_id") or signal_id)
    decision_id = _safe_str(signal.get("decision_id") or signal_id)
    symbol = _safe_str(signal.get("symbol"))
    strategy = _safe_str(signal.get("strategy"))
    side = _normalize_ingress_side(signal.get("side"))
    price = _safe_float(signal.get("price"))

    ts = _safe_int(signal.get("ts"))
    if ts <= 0:
        ts = _now_ts()

    timeframe = _safe_str(signal.get("timeframe"))
    source = _safe_str(signal.get("source"), "api").lower()
    payload = _safe_dict(signal.get("payload"))
    meta = _safe_dict(signal.get("meta"))
    exchange = _safe_str(signal.get("exchange"))
    order_type = _safe_str(signal.get("order_type"), "market").lower() or "market"
    reduce_only = _safe_bool(signal.get("reduce_only"), False)
    size = _safe_float(_coalesce(signal.get("size"), signal.get("qty"), signal.get("amount")), 0.0)
    qty = _safe_float(_coalesce(signal.get("qty"), signal.get("size"), signal.get("amount")), 0.0)
    amount = _safe_float(_coalesce(signal.get("amount"), signal.get("qty"), signal.get("size")), 0.0)

    if not signal_id:
        raise ValueError("signal.signal_id missing")
    if not symbol:
        raise ValueError("signal.symbol missing")
    if not strategy:
        raise ValueError("signal.strategy missing")
    if side not in VALID_SIDES:
        raise ValueError("signal.side invalid")
    if price <= 0:
        raise ValueError("signal.price invalid")
    if ts <= 0:
        raise ValueError("signal.ts invalid")

    return {
        "signal_id": signal_id,
        "event_id": event_id,
        "decision_id": decision_id,
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
        "execution_side": _to_execution_side(side),
        "state_side": _to_state_side(side),
        "price": price,
        "ts": ts,
        "timeframe": timeframe,
        "source": source,
        "payload": payload,
        "meta": meta,
        "exchange": exchange,
        "order_type": order_type,
        "reduce_only": reduce_only,
        "size": size,
        "qty": qty,
        "amount": amount,
    }


def _extract_signal_payload(req: Dict[str, Any]) -> Dict[str, Any]:
    req = _safe_dict(req)

    nested = _safe_dict(req.get("signal"))
    if nested:
        return nested

    direct_hint_keys = {
        "signal_id",
        "event_id",
        "decision_id",
        "symbol",
        "side",
        "strategy",
        "price",
        "ts",
        "timeframe",
        "source",
        "payload",
    }
    if not any(k in req for k in direct_hint_keys):
        return {}

    signal = dict(req)
    for k in ("signal", "mode", "route"):
        signal.pop(k, None)
    return _safe_dict(signal)


def _build_req_echo(
    *,
    mode: Any,
    route: Any,
    signal: Optional[Dict[str, Any]] = None,
    has_signal: Optional[bool] = None,
) -> Dict[str, Any]:
    sig = _safe_dict(signal)
    echo_has_signal = has_signal if has_signal is not None else bool(sig)
    return {
        "mode": _safe_str(mode) or None,
        "route": _safe_str(route) or None,
        "has_signal": bool(echo_has_signal),
        "event_id": _safe_str(sig.get("event_id")) or None,
        "decision_id": _safe_str(sig.get("decision_id")) or None,
        "signal_id": _safe_str(sig.get("signal_id")) or None,
    }


def _normalize_action(action: Any, *, fallback: str = "hold") -> str:
    value = _safe_str(action).lower()
    if value in VALID_DECISION_ACTIONS:
        return value
    return fallback


def _normalize_risk_action(action: Any, *, fallback: str = "hold") -> str:
    value = _safe_str(action).lower()
    if value in VALID_RISK_ACTIONS or value in VALID_DECISION_ACTIONS:
        return value
    fb = _safe_str(fallback).lower()
    if fb in VALID_RISK_ACTIONS or fb in VALID_DECISION_ACTIONS:
        return fb
    return "hold"


def _normalize_executor_status_name(status: Any, *, fallback: str = "blocked") -> str:
    value = _safe_str(status).lower()
    if value in VALID_EXECUTOR_STATUSES:
        return value
    return fallback


def _normalize_event_status_name(status: Any, *, fallback: str = "blocked") -> str:
    value = _safe_str(status).lower()
    if value in VALID_EVENT_STATUSES:
        return value
    return fallback


def _build_contract_result(
    *,
    ok: bool,
    detail: Any,
    reason: Any,
    executor: Optional[Dict[str, Any]],
    journal_event: Optional[Dict[str, Any]],
    state_snapshot: Optional[Dict[str, Any]],
    req_echo: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    ex = _safe_dict(executor)
    je = _safe_dict(journal_event)
    snap = _safe_dict(state_snapshot)
    echo = _safe_dict(req_echo)

    contract_reason = _safe_str(
        _coalesce(
            reason,
            detail,
            je.get("decision_reason"),
            ex.get("reason"),
            ex.get("code"),
        )
    )
    contract_detail = _safe_str(_coalesce(detail, contract_reason))
    decision_action = _normalize_action(
        je.get("decision_action") or ex.get("action"),
        fallback="hold",
    )
    risk_action = _normalize_risk_action(
        je.get("risk_action") or ex.get("risk_action") or decision_action,
        fallback=decision_action if ok else "hold",
    )
    executor_status = _normalize_executor_status_name(
        je.get("executor_status") or ex.get("executor_status") or ex.get("status"),
        fallback="ready" if ok else "blocked",
    )
    event_status = _normalize_event_status_name(
        je.get("status"),
        fallback="ready" if ok else "blocked",
    )
    executor_result = _safe_str(
        _coalesce(
            je.get("executor_result"),
            ex.get("executor_result"),
            ex.get("reason"),
            ex.get("code"),
            contract_reason,
        )
    )
    effective_mode = _safe_str(_coalesce(je.get("effective_mode"), ex.get("mode"), echo.get("mode")))
    effective_route = _safe_str(_coalesce(je.get("effective_route"), ex.get("route"), echo.get("route")))
    event_id = _safe_str(_coalesce(je.get("event_id"), ex.get("event_id"), echo.get("event_id"), echo.get("signal_id")))
    decision_id = _safe_str(_coalesce(je.get("decision_id"), ex.get("decision_id"), echo.get("decision_id"), event_id))
    signal_id = _safe_str(_coalesce(je.get("signal_id"), echo.get("signal_id"), decision_id, event_id))
    strategy = _safe_str(_coalesce(je.get("strategy"), ex.get("strategy")))
    symbol = _safe_str(_coalesce(je.get("symbol"), ex.get("symbol")))
    side = _safe_str(_coalesce(je.get("side"), ex.get("side")))
    ts = _safe_int(_coalesce(je.get("ts"), ex.get("accepted_at"), 0))
    written_at = _now_iso()

    return {
        "ok": bool(ok),
        "detail": contract_detail or None,
        "reason": contract_reason or None,
        "status": event_status,
        "event_id": event_id or None,
        "decision_id": decision_id or None,
        "signal_id": signal_id or None,
        "decision_action": decision_action,
        "decision_reason": contract_reason or None,
        "risk_action": risk_action,
        "executor_status": executor_status,
        "executor_result": executor_result or None,
        "effective_mode": effective_mode or None,
        "effective_route": effective_route or None,
        "event_type": _safe_str(je.get("event_type")) or None,
        "strategy": strategy or None,
        "symbol": symbol or None,
        "side": side or None,
        "ts": ts or None,
        "written_at": written_at,
        "executor": ex,
        "journal_event": je,
        "state_snapshot": snap,
        "_binding_check": binding_check(),
        "_req_echo": echo,
    }


def _normalize_request(req: Dict[str, Any]) -> Dict[str, Any]:
    req = _safe_dict(req)

    mode = _safe_str(req.get("mode"), "dummy").lower()
    route = _safe_str(req.get("route"), "paper").lower()
    signal = _normalize_signal(_extract_signal_payload(req))

    if mode not in VALID_MODES:
        raise ValueError("mode invalid")
    if route not in VALID_ROUTES:
        raise ValueError("route invalid")

    return {
        "mode": mode,
        "route": route,
        "signal": signal,
    }


def _normalize_paper_state(v: Any, signal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    src = _safe_dict(v)
    sig = signal or {}

    symbol = _safe_str(src.get("symbol") or sig.get("symbol"))
    strategy = _safe_str(src.get("strategy") or sig.get("strategy"))

    return {
        "symbol": symbol,
        "strategy": strategy,
        "position_side": _safe_str(src.get("position_side")),
        "position_qty": _safe_float(src.get("position_qty")),
        "avg_entry": _safe_float(src.get("avg_entry")),
        "add_count": _safe_int(src.get("add_count")),
        "last_add_price": _safe_float(src.get("last_add_price")),
        "realized_pnl": _safe_float(src.get("realized_pnl")),
        "last_signal_id": _safe_str(src.get("last_signal_id")),
        "last_symbol": _safe_str(src.get("last_symbol") or symbol),
        "last_strategy": _safe_str(src.get("last_strategy") or strategy),
        "last_action": _safe_str(src.get("last_action")),
        "updated_at": _safe_str(src.get("updated_at") or _now_iso()),
    }


def _selected_from_state(state: Dict[str, Any], signal: Dict[str, Any]) -> Dict[str, Any]:
    ps = _normalize_paper_state(state, signal)
    return {
        "symbol": signal["symbol"],
        "strategy": signal["strategy"],
        "position_side": ps["position_side"],
        "position_qty": ps["position_qty"],
        "avg_entry": ps["avg_entry"],
        "add_count": ps["add_count"],
        "last_add_price": ps["last_add_price"],
        "realized_pnl": ps["realized_pnl"],
        "last_signal_id": ps["last_signal_id"],
        "last_action": ps["last_action"],
        "updated_at": ps["updated_at"],
    }


def _call_candidate(fn: Any, req: Dict[str, Any], signal: Dict[str, Any]) -> Any:
    if fn is None or not callable(fn):
        raise TypeError("callable_missing")

    attempts = [
        ((req,), {}),
        ((signal,), {}),
        ((), {"req": req}),
        ((), {"request": req}),
        ((), {"signal": signal}),
    ]

    last_err = None
    for args, kwargs in attempts:
        try:
            return fn(*args, **kwargs)
        except TypeError as e:
            last_err = e
            continue

    if last_err is not None:
        raise last_err
    raise RuntimeError("candidate_call_failed")


def _resolve_paper_bindings() -> Dict[str, Any]:
    paper_mod, process_fn = _find_attr(
        "backend.engine.paper_ledger",
        "process_signal_to_paper_state",
    )
    _, get_state_fn = _find_attr(
        "backend.engine.paper_ledger",
        "get_paper_state",
    )
    _, snapshot_builder = _find_attr(
        "backend.engine.state_read_model",
        "build_lbot_state_snapshot",
    )

    return {
        "paper_module": paper_mod,
        "paper_process_fn": process_fn,
        "paper_get_state_fn": get_state_fn,
        "snapshot_builder": snapshot_builder,
    }


def _resolve_gsheets_bindings() -> Dict[str, Any]:
    gs_mod, upsert_fn = _find_attr(
        "backend.engine.gsheets_readwrite",
        "upsert_row",
    )
    _, append_fn = _find_attr(
        "backend.engine.gsheets_readwrite",
        "append_rows",
    )
    _, binding_fn = _find_attr(
        "backend.engine.gsheets_readwrite",
        "binding_check",
    )

    return {
        "module": gs_mod,
        "upsert_row": upsert_fn,
        "append_rows": append_fn,
        "binding_check": binding_fn,
    }

def _resolve_strategy_registry_bindings() -> Dict[str, Any]:
    reg_mod, strategies = _find_attr(
        "backend.engine.strategy_registry",
        "STRATEGIES",
    )
    if reg_mod is None or strategies is None:
        reg_mod, strategies = _find_attr(
            "backend.engine.strategy_registry_g0_runtime_safe",
            "STRATEGIES",
        )

    return {
        "module": reg_mod,
        "strategies": strategies,
    }



def _check_strategy_registered(strategy_name: Any) -> Tuple[bool, str]:
    name = _safe_str(strategy_name)
    if not name:
        return False, "signal.strategy missing"

    bindings = _resolve_strategy_registry_bindings()
    strategies = bindings.get("strategies")
    if not isinstance(strategies, dict):
        return False, "strategy_registry_unavailable"

    if name not in strategies:
        return False, "unknown_strategy"

    return True, ""



def _build_execution_intent(req: Dict[str, Any], norm: Dict[str, Any]) -> Dict[str, Any]:
    signal = _safe_dict(norm.get("signal"))
    payload = _safe_dict(signal.get("payload"))

    # ingress_guard  I A           A payload.qty / payload.size / payload.amount   c  e   YAo
    # qty  A top-level signal   C  A req             A    A  U.     A    e   o ? A    I  쨢  U.
    qty = _coalesce(
        signal.get("qty"),
        req.get("qty") if isinstance(req, dict) else None,
        req.get("size") if isinstance(req, dict) else None,
        req.get("amount") if isinstance(req, dict) else None,
        "",
    )

    return {
        "symbol": signal.get("symbol"),
        "side": signal.get("execution_side") or _to_execution_side(signal.get("side")),
        "event_id": signal.get("event_id") or signal.get("signal_id") or "",
        "decision_id": signal.get("decision_id") or signal.get("signal_id") or signal.get("event_id") or "",
        "qty": qty,
        "price": signal.get("price"),
        "exchange": (
            payload.get("exchange")
            or signal.get("exchange")
            or (req.get("exchange") if isinstance(req, dict) else "")
            or "bingx"
        ),
        "strategy": signal.get("strategy"),
        "mode": norm.get("mode"),
        "route": norm.get("route"),
        "meta": _safe_dict(signal.get("meta")),
        "raw": req if isinstance(req, dict) else {"req": _safe_str(req)},
    }


def _router_gate_result(norm: Dict[str, Any], routed: Dict[str, Any]) -> Dict[str, Any]:
    signal = norm["signal"]
    status = _safe_str(routed.get("status"), "blocked")
    reason = _safe_str(routed.get("reason"), "execution_router_blocked")
    route = _safe_str(routed.get("route"), norm.get("route", "noop"))
    mode = _safe_str(routed.get("mode"), norm.get("mode", "noop"))
    action = "hold" if status == "hold" else "block"

    executor = {
        "status": status,
        "executor_status": status,
        "executor_result": "boundary_block",
        "reason": reason,
        "code": reason,
        "action": action,
        "mode": mode,
        "route": route,
        "guard": _safe_dict(routed.get("guard")),
    }
    journal_event = {
        "status": "hold" if status == "hold" else "blocked",
        "event_type": "lbot_runtime",
        "signal_id": signal["signal_id"],
        "strategy": signal["strategy"],
        "symbol": signal["symbol"],
        "decision_action": action,
        "decision_reason": reason,
        "risk_action": action,
        "executor_status": status,
        "executor_result": "boundary_block",
        "effective_mode": mode,
        "effective_route": route,
        "ts": signal["ts"],
    }
    return _build_contract_result(
        ok=False,
        detail=reason,
        reason=reason,
        executor=executor,
        journal_event=journal_event,
        state_snapshot={},
        req_echo=_build_req_echo(mode=mode, route=route, signal=signal),
    )


def _router_noop_result(norm: Dict[str, Any], routed: Dict[str, Any]) -> Dict[str, Any]:
    signal = norm["signal"]
    reason = _safe_str(routed.get("reason"), "noop_route")
    route = _safe_str(routed.get("route"), "noop")
    mode = _safe_str(routed.get("mode"), norm.get("mode", "noop"))

    executor = {
        "status": "noop",
        "executor_status": "noop",
        "executor_result": reason,
        "reason": reason,
        "code": reason,
        "action": "hold",
        "mode": mode,
        "route": route,
        "guard": _safe_dict(routed.get("guard")),
    }
    journal_event = {
        "status": "ready",
        "event_type": "lbot_runtime",
        "signal_id": signal["signal_id"],
        "strategy": signal["strategy"],
        "symbol": signal["symbol"],
        "decision_action": "hold",
        "decision_reason": reason,
        "risk_action": "hold",
        "executor_status": "noop",
        "executor_result": reason,
        "effective_mode": mode,
        "effective_route": route,
        "ts": signal["ts"],
    }
    return _build_contract_result(
        ok=True,
        detail=reason,
        reason=reason,
        executor=executor,
        journal_event=journal_event,
        state_snapshot={},
        req_echo=_build_req_echo(mode=mode, route=route, signal=signal),
    )

def _fallback_state_snapshot(signal: Dict[str, Any], paper_state: Dict[str, Any]) -> Dict[str, Any]:
    ps = _normalize_paper_state(paper_state, signal)
    selected = _selected_from_state(ps, signal)

    return {
        "position_side": ps["position_side"],
        "position_qty": ps["position_qty"],
        "avg_entry": ps["avg_entry"],
        "add_count": ps["add_count"],
        "last_add_price": ps["last_add_price"],
        "realized_pnl": ps["realized_pnl"],
        "last_signal_id": ps["last_signal_id"],
        "last_action": ps["last_action"],
        "paper_state_selected": selected,
    }


def _merge_snapshot_with_paper_state(
    root: Dict[str, Any],
    signal: Dict[str, Any],
    paper_state: Dict[str, Any],
) -> Dict[str, Any]:
    ps = _normalize_paper_state(paper_state, signal)
    selected = _selected_from_state(ps, signal)

    merged = _safe_dict(root)

    merged["position_side"] = ps["position_side"]
    merged["position_qty"] = ps["position_qty"]
    merged["avg_entry"] = ps["avg_entry"]
    merged["add_count"] = ps["add_count"]
    merged["last_add_price"] = ps["last_add_price"]
    merged["realized_pnl"] = ps["realized_pnl"]
    merged["last_signal_id"] = ps["last_signal_id"]
    merged["last_action"] = ps["last_action"]
    merged["paper_state_selected"] = selected
    merged["last_symbol"] = ps["last_symbol"] or signal["symbol"]
    merged["last_strategy"] = ps["last_strategy"] or signal["strategy"]
    merged["updated_at"] = ps["updated_at"]

    return merged


def _build_state_snapshot(
    snapshot_builder: Any,
    signal: Dict[str, Any],
    paper_state: Dict[str, Any],
) -> Dict[str, Any]:
    if callable(snapshot_builder):
        try:
            built = snapshot_builder(symbol=signal["symbol"], strategy=signal["strategy"])
            if isinstance(built, dict):
                root = _safe_dict(built.get("state_snapshot") or built.get("state") or built)
                if root:
                    return _merge_snapshot_with_paper_state(root, signal, paper_state)
        except Exception:
            pass

    return _fallback_state_snapshot(signal, paper_state)


def _extract_action(executor_result: Any, signal: Dict[str, Any]) -> str:
    payload = _safe_dict(signal.get("payload"))
    forced = _safe_str(payload.get("force_action")).lower()
    if forced:
        return forced

    if isinstance(executor_result, dict):
        for key in ("action", "decision_action", "last_action"):
            v = _safe_str(executor_result.get(key)).lower()
            if v:
                return v

    sid = signal["signal_id"].lower()
    if "_enter_" in sid:
        return "enter"
    if "_add_" in sid:
        return "add"
    if "_reduce_" in sid:
        return "reduce"
    if "_exit_" in sid:
        return "exit"

    if signal["side"] in {"buy", "long"}:
        return "enter"
    if signal["side"] in {"sell", "short", "exit"}:
        return "exit"

    return "hold"


def _normalize_executor_result(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return v
    return {"raw": v}


def _read_current_paper_state(get_state_fn: Any, signal: Dict[str, Any]) -> Dict[str, Any]:
    if callable(get_state_fn):
        attempts = [
            ((), {"symbol": signal["symbol"], "strategy": signal["strategy"]}),
            ((signal["symbol"], signal["strategy"]), {}),
            ((signal["symbol"],), {}),
            ((), {}),
        ]
        for args, kwargs in attempts:
            try:
                out = get_state_fn(*args, **kwargs)
                if isinstance(out, dict):
                    selected = out.get("paper_state_selected")
                    if isinstance(selected, dict):
                        return _normalize_paper_state(selected, signal)

                    positions = _safe_dict(out.get("positions"))
                    key = f'{signal["symbol"]}::{signal["strategy"]}'
                    if isinstance(positions.get(key), dict):
                        return _normalize_paper_state(positions[key], signal)

                    return _normalize_paper_state(out, signal)
            except Exception:
                continue
    return _normalize_paper_state({}, signal)


def _build_positions_row(
    signal: Dict[str, Any],
    state_snapshot: Dict[str, Any],
    paper_state: Dict[str, Any],
) -> Dict[str, Any]:
    payload = _safe_dict(signal.get("payload"))
    selected = _safe_dict(state_snapshot.get("paper_state_selected"))
    if not selected:
        selected = _selected_from_state(paper_state, signal)

    side = _display_side(selected.get("position_side") or signal.get("side"))
    entry = _coalesce(selected.get("avg_entry"), "")
    qty = _coalesce(selected.get("position_qty"), "")
    lev = _coalesce(
        payload.get("lev"),
        payload.get("leverage"),
        payload.get("x"),
        "",
    )
    liq = _coalesce(
        payload.get("liq"),
        payload.get("liq_price"),
        payload.get("liq_buffer"),
        payload.get("liq_buffer_pct"),
        "",
    )
    tp = _coalesce(
        payload.get("TP"),
        payload.get("tp"),
        payload.get("take_profit"),
        payload.get("tp_price"),
        "",
    )
    sl = _coalesce(
        payload.get("SL"),
        payload.get("sl"),
        payload.get("stop_loss"),
        payload.get("sl_price"),
        "",
    )
    rr = _coalesce(payload.get("rr"), payload.get("RR"), "")
    liq_warn = _safe_bool(
        _coalesce(payload.get("liq_warn"), payload.get("liquidation_warn"), False),
        False,
    )
    sl_ok = _safe_bool(
        _coalesce(payload.get("sl_ok"), payload.get("has_sl"), bool(sl)),
        bool(sl),
    )

    return {
        "sym": signal["symbol"],
        "side": side,
        "entry": entry,
        "mark": signal["price"],
        "qty": qty,
        "lev": lev,
        "liq": liq,
        "TP": tp,
        "SL": sl,
        "ts": _ts_to_iso(signal["ts"]),
        "rr": rr,
        "liq_warn": liq_warn,
        "sl_ok": sl_ok,
    }


def _build_signal_row(
    norm: Dict[str, Any],
    signal: Dict[str, Any],
    executor: Dict[str, Any],
    journal_event: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "signal_id": signal["signal_id"],
        "symbol": signal["symbol"],
        "strategy": signal["strategy"],
        "side": _display_side(signal["side"]),
        "price": signal["price"],
        "ts": _ts_to_iso(signal["ts"]),
        "timeframe": signal.get("timeframe", ""),
        "source": signal.get("source", ""),
        "mode": norm["mode"],
        "route": norm["route"],
        "decision_action": _safe_str(journal_event.get("decision_action")),
        "decision_reason": _safe_str(journal_event.get("decision_reason")),
        "risk_action": _safe_str(journal_event.get("risk_action")),
        "executor_status": _safe_str(journal_event.get("executor_status") or executor.get("status")),
        "executor_result": _safe_str(journal_event.get("executor_result") or executor.get("executor_result")),
        "effective_mode": _safe_str(journal_event.get("effective_mode") or norm["mode"]),
        "effective_route": _safe_str(journal_event.get("effective_route") or norm["route"]),
        "event_type": _safe_str(journal_event.get("event_type")),
        "status": _safe_str(journal_event.get("status")),
        "written_at": _now_iso(),
    }


def _build_trade_row(
    norm: Dict[str, Any],
    signal: Dict[str, Any],
    executor: Dict[str, Any],
    journal_event: Dict[str, Any],
    state_snapshot: Dict[str, Any],
    paper_state: Dict[str, Any],
) -> Dict[str, Any]:
    selected = _safe_dict(state_snapshot.get("paper_state_selected"))
    if not selected:
        selected = _selected_from_state(paper_state, signal)

    return {
        "event_id": signal["signal_id"],
        "decision_id": signal["signal_id"],
        "signal_id": signal["signal_id"],
        "symbol": signal["symbol"],
        "strategy": signal["strategy"],
        "action": _safe_str(journal_event.get("decision_action") or executor.get("action") or "hold"),
        "side": _display_side(signal["side"]),
        "price": signal["price"],
        "mode": norm["mode"],
        "route": norm["route"],
        "executor_status": _safe_str(journal_event.get("executor_status") or executor.get("status")),
        "executor_result": _safe_str(journal_event.get("executor_result") or executor.get("executor_result")),
        "decision_reason": _safe_str(journal_event.get("decision_reason")),
        "position_qty": _coalesce(selected.get("position_qty"), ""),
        "avg_entry": _coalesce(selected.get("avg_entry"), ""),
        "realized_pnl": _coalesce(selected.get("realized_pnl"), ""),
        "ts": _ts_to_iso(signal["ts"]),
        "written_at": _now_iso(),
    }


def _write_gsheets_hooks(
    norm: Dict[str, Any],
    executor: Dict[str, Any],
    journal_event: Dict[str, Any],
    state_snapshot: Dict[str, Any],
    paper_state: Dict[str, Any],
) -> Dict[str, Any]:
    gs = _resolve_gsheets_bindings()

    binding_out: Dict[str, Any]
    if callable(gs["binding_check"]):
        try:
            binding_out = _safe_dict(gs["binding_check"]())
        except Exception as e:
            binding_out = {"ok": False, "reason": repr(e)}
    else:
        binding_out = {
            "ok": False,
            "reason": "gsheets_binding_check_not_found",
        }

    out: Dict[str, Any] = {
        "binding": binding_out,
        "positions": {"ok": True, "status": "skipped"},
        "signals": {"ok": True, "status": "skipped"},
        "trades_log": {"ok": True, "status": "skipped"},
    }

    append_fn = gs.get("append_rows")
    upsert_fn = gs.get("upsert_row")
    signal = norm["signal"]

    executor_status = _safe_str(
        journal_event.get("executor_status") or executor.get("status")
    ).lower()
    executor_result = _safe_str(
        journal_event.get("executor_result") or executor.get("executor_result")
    ).lower()

    allow_positions_upsert = (
        callable(upsert_fn)
        and executor_status == "paper"
        and executor_result.startswith("paper_")
    )

    if allow_positions_upsert:
        try:
            out["positions"] = _safe_dict(
                upsert_fn(
                    row=_build_positions_row(
                        signal=signal,
                        state_snapshot=state_snapshot,
                        paper_state=paper_state,
                    ),
                    key_field="sym",
                    tab="positions",
                    create_header=True,
                )
            )
        except Exception as e:
            out["positions"] = {"ok": False, "reason": repr(e)}

    if callable(append_fn):
        try:
            out["signals"] = _safe_dict(
                append_fn(
                    rows=[
                        _build_signal_row(
                            norm=norm,
                            signal=signal,
                            executor=executor,
                            journal_event=journal_event,
                        )
                    ],
                    tab="signals",
                    create_header=True,
                )
            )
        except Exception as e:
            out["signals"] = {"ok": False, "reason": repr(e)}

        try:
            out["trades_log"] = _safe_dict(
                append_fn(
                    rows=[
                        _build_trade_row(
                            norm=norm,
                            signal=signal,
                            executor=executor,
                            journal_event=journal_event,
                            state_snapshot=state_snapshot,
                            paper_state=paper_state,
                        )
                    ],
                    tab="trades_log",
                    create_header=True,
                )
            )
        except Exception as e:
            out["trades_log"] = {"ok": False, "reason": repr(e)}

    return out


def _finalize_result(
    norm: Dict[str, Any],
    result: Dict[str, Any],
    paper_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    finalized = _safe_dict(result)
    gs_out = _write_gsheets_hooks(
        norm=norm,
        executor=_safe_dict(finalized.get("executor")),
        journal_event=_safe_dict(finalized.get("journal_event")),
        state_snapshot=_safe_dict(finalized.get("state_snapshot")),
        paper_state=_normalize_paper_state(paper_state or {}, norm["signal"]),
    )
    finalized["gsheets"] = gs_out
    finalized["written_at"] = _safe_str(finalized.get("written_at") or _now_iso())
    return finalized


def _build_blocked_result(
    *,
    norm: Dict[str, Any],
    detail: str,
    effective_mode: Optional[str] = None,
    effective_route: Optional[str] = None,
    status: str = "blocked",
) -> Dict[str, Any]:
    signal = norm["signal"]
    route = effective_route or _safe_str(norm.get("effective_route") or norm.get("route"))
    mode = effective_mode or _safe_str(norm.get("effective_mode") or norm.get("mode"))
    reason = _safe_str(detail)
    action = "hold" if status == "hold" else "block"

    executor = {
        "status": status,
        "executor_status": status,
        "executor_result": reason,
        "reason": reason,
        "code": reason,
        "action": action,
        "mode": mode,
        "route": route,
        "guard": {
            "ok": False,
            "reason": reason,
            "code": reason,
            "details": {
                "mode": mode,
                "route": route,
                "signal_id": signal["signal_id"],
            },
        },
    }

    journal_event = {
        "status": "hold" if status == "hold" else "blocked",
        "event_type": "lbot_runtime",
        "signal_id": signal["signal_id"],
        "strategy": signal["strategy"],
        "symbol": signal["symbol"],
        "decision_action": action,
        "decision_reason": reason,
        "risk_action": action,
        "executor_status": status,
        "executor_result": reason,
        "effective_mode": mode,
        "effective_route": route,
        "ts": signal["ts"],
    }

    return _build_contract_result(
        ok=False,
        detail=reason,
        reason=reason,
        executor=executor,
        journal_event=journal_event,
        state_snapshot={},
        req_echo=_build_req_echo(mode=mode, route=route, signal=signal),
    )

def _write_journal_event(
    req: Dict[str, Any],
    signal: Dict[str, Any],
    action: str,
    executor_result: Dict[str, Any],
    paper_state: Dict[str, Any],
    state_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    payload = _safe_dict(signal.get("payload"))

    decision_reason = _safe_str(
        executor_result.get("reason")
        or executor_result.get("code")
        or _safe_dict(executor_result.get("guard")).get("reason")
        or payload.get("why")
        or f"forced_{action}"
    )

    effective_mode = _safe_str(req.get("effective_mode") or req.get("mode"))
    effective_route = _safe_str(req.get("effective_route") or req.get("route"))

    executor_status = _safe_str(executor_result.get("status") or effective_route)
    executor_result_text = _safe_str(
        executor_result.get("executor_result")
        or executor_result.get("reason")
        or executor_result.get("code")
        or _safe_dict(executor_result.get("guard")).get("reason")
        or f'{effective_route}_{action}'
    )

    event = {
        "signal_id": signal["signal_id"],
        "mode": _safe_str(req.get("configured_mode") or req.get("mode")),
        "route": _safe_str(req.get("configured_route") or req.get("route")),
        "executor": executor_result,
        "journal_event": {
            "status": "ready",
            "event_type": "lbot_runtime",
            "signal_id": signal["signal_id"],
            "strategy": signal["strategy"],
            "symbol": signal["symbol"],
            "decision_action": action,
            "decision_reason": decision_reason,
            "risk_action": _normalize_risk_action(
                executor_result.get("risk_action") or action,
                fallback=action,
            ),
            "executor_status": executor_status,
            "executor_result": executor_result_text,
            "effective_mode": effective_mode,
            "effective_route": effective_route,
            "ts": signal["ts"],
        },
        "state_snapshot": state_snapshot,
    }

    latest_path = JOURNAL_LATEST
    daily_path = _journal_daily_path(signal["ts"])

    _atomic_write_json(latest_path, event)
    _append_jsonl(daily_path, event)

    return {
        "status": "written",
        "latest_path": str(latest_path),
        "daily_path": str(daily_path),
        "event": event,
        "paper_state": paper_state,
    }


def _write_runtime_state_latest(
    *,
    signal: Dict[str, Any],
    norm: Dict[str, Any],
    settings: Dict[str, Any],
    journal_event: Dict[str, Any],
    state_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    current = _read_json(PAPER_STATE_LATEST)
    out = _safe_dict(current)
    out.update(_safe_dict(state_snapshot))

    out["mode"] = _safe_str(_coalesce(settings.get("mode"), norm.get("configured_mode"), norm.get("mode")))
    out["route"] = _safe_str(_coalesce(settings.get("route"), norm.get("configured_route"), norm.get("route")))
    out["effective_mode"] = _safe_str(_coalesce(journal_event.get("effective_mode"), norm.get("effective_mode"), norm.get("mode")))
    out["effective_route"] = _safe_str(_coalesce(journal_event.get("effective_route"), norm.get("effective_route"), norm.get("route")))
    out["exchange_enabled"] = _safe_bool(settings.get("exchange_enabled"), False)

    out["signal_id"] = _safe_str(_coalesce(journal_event.get("signal_id"), signal.get("signal_id")))
    out["strategy"] = _safe_str(_coalesce(journal_event.get("strategy"), signal.get("strategy"), out.get("strategy")))
    out["symbol"] = _safe_str(_coalesce(journal_event.get("symbol"), signal.get("symbol"), out.get("symbol")))
    out["side"] = _safe_str(_coalesce(signal.get("side"), out.get("side")))
    out["decision_action"] = _safe_str(journal_event.get("decision_action"))
    out["decision_reason"] = _safe_str(journal_event.get("decision_reason"))
    out["risk_action"] = _safe_str(journal_event.get("risk_action"))
    out["executor_status"] = _safe_str(journal_event.get("executor_status"))
    out["executor_result"] = _safe_str(journal_event.get("executor_result"))
    out["event_type"] = _safe_str(journal_event.get("event_type"))
    out["status"] = _safe_str(journal_event.get("status"))
    out["ts"] = _safe_int(_coalesce(journal_event.get("ts"), signal.get("ts"), out.get("ts")))
    out["written_at"] = _now_iso()
    out["updated_at"] = _safe_str(_coalesce(out.get("updated_at"), out.get("written_at"), _now_iso()))

    _atomic_write_json(PAPER_STATE_LATEST, out)
    return out


def _resolve_effective_mode_route(norm: Dict[str, Any], settings: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    mode = norm["mode"]
    route = norm["route"]

    if mode == "noop" or route == "noop":
        return mode, "noop", None

    if mode == "shadow":
        return mode, "noop", None

    if mode in {"dummy", "paper"} and route == "live":
        return mode, route, "live_route_blocked_for_non_live_mode"

    if mode == "live":
        if route != "live":
            return mode, route, "live_mode_requires_live_route"

        if not _live_trading_enabled(settings):
            return mode, route, "live_trading_disabled"

        return mode, route, None

    return mode, route, None


def binding_check() -> Dict[str, Any]:
    lbot_process_found = callable(globals().get("lbot_process"))
    process_found = callable(globals().get("process"))
    process_signal_found = callable(globals().get("process_signal"))
    binding_check_found = callable(globals().get("binding_check"))

    gs = _resolve_gsheets_bindings()
    paper = _resolve_paper_bindings()

    exported: List[str] = []
    if lbot_process_found:
        exported.append("lbot_process")
    if process_found:
        exported.append("process")
    if process_signal_found:
        exported.append("process_signal")
    if binding_check_found:
        exported.append("binding_check")

    process_candidates_found: List[Dict[str, str]] = []
    if lbot_process_found:
        process_candidates_found.append(
            {
                "module": "backend.engine.lbot_core",
                "name": "lbot_process",
                "role": "ssot",
            }
        )

    return {
        "module": "backend.engine.lbot_core",
        "lbot_process_found": lbot_process_found,
        "process_found": process_found,
        "process_signal_found": process_signal_found,
        "exported": exported,
        "process_fn_found": lbot_process_found,
        "process_fn_name": "lbot_process" if lbot_process_found else None,
        "process_fn_module": "backend.engine.lbot_core" if lbot_process_found else None,
        "process_candidates_found": process_candidates_found,
        "aliases": {
            "process": process_found,
            "process_signal": process_signal_found,
        },
        "paper_bindings": {
            "paper_process_fn_found": callable(paper.get("paper_process_fn")),
            "paper_get_state_fn_found": callable(paper.get("paper_get_state_fn")),
            "snapshot_builder_found": callable(paper.get("snapshot_builder")),
        },
        "gsheets": {
            "upsert_found": callable(gs.get("upsert_row")),
            "append_found": callable(gs.get("append_rows")),
            "binding_found": callable(gs.get("binding_check")),
        },
        "paths": {
            "lbot_event_latest": str(JOURNAL_LATEST),
            "paper_state_latest": str(PAPER_DIR / "paper_state.latest.json"),
            "settings_file": str(SETTINGS_FILE),
        },
    }


def lbot_process(req: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_dirs()

    raw_req = _safe_dict(req)
    try:
        norm = _normalize_request(raw_req)
    except Exception as e:
        raw_signal = _extract_signal_payload(raw_req)
        signal_id = _safe_str(raw_signal.get("signal_id") or raw_signal.get("event_id"))
        signal = {
            "signal_id": signal_id,
            "strategy": _safe_str(raw_signal.get("strategy")),
            "symbol": _safe_str(raw_signal.get("symbol")),
            "ts": _safe_int(raw_signal.get("ts")),
        }
        reason = _safe_str(e) or "request_normalization_failed"
        return _build_contract_result(
            ok=False,
            detail=reason,
            reason=reason,
            executor={
                "status": "blocked",
                "executor_status": "blocked",
                "executor_result": "ingress_hold",
                "reason": reason,
                "code": reason,
                "action": "hold",
                "mode": _safe_str(raw_req.get("mode"), "dummy").lower(),
                "route": _safe_str(raw_req.get("route"), "paper").lower(),
                "guard": {
                    "ok": False,
                    "reason": reason,
                    "details": {},
                },
            },
            journal_event={
                "status": "blocked",
                "event_type": "lbot_runtime",
                "signal_id": signal["signal_id"],
                "strategy": signal["strategy"],
                "symbol": signal["symbol"],
                "decision_action": "hold",
                "decision_reason": reason,
                "risk_action": "hold",
                "executor_status": "blocked",
                "executor_result": "ingress_hold",
                "effective_mode": _safe_str(raw_req.get("mode"), "dummy").lower(),
                "effective_route": _safe_str(raw_req.get("route"), "paper").lower(),
                "ts": signal["ts"],
            },
            state_snapshot={},
            req_echo=_build_req_echo(
                mode=_safe_str(raw_req.get("mode"), "dummy").lower(),
                route=_safe_str(raw_req.get("route"), "paper").lower(),
                signal=signal,
                has_signal=bool(raw_signal),
            ),
        )

    signal = norm["signal"]
    settings = _load_runtime_settings()

    requested_mode = _safe_str(norm.get("mode"), "dummy").lower()
    requested_route = _safe_str(norm.get("route"), "paper").lower()
    configured_mode, configured_route = _configured_mode_route(norm, settings)

    norm["requested_mode"] = requested_mode
    norm["requested_route"] = requested_route
    norm["configured_mode"] = configured_mode
    norm["configured_route"] = configured_route
    norm["mode"] = configured_mode
    norm["route"] = configured_route

    effective_mode, effective_route, resolve_reason = _resolve_effective_mode_route(norm, settings)
    norm["effective_mode"] = effective_mode
    norm["effective_route"] = effective_route
    norm["mode"] = effective_mode
    norm["route"] = effective_route

    strategy_ok, strategy_reason = _check_strategy_registered(signal.get("strategy"))
    if not strategy_ok:
        return _finalize_result(
            norm=norm,
            result=_build_blocked_result(
                norm=norm,
                detail=strategy_reason,
                effective_mode=effective_mode,
                effective_route=effective_route,
                status="blocked",
            ),
            paper_state={},
        )

    if resolve_reason:
        if effective_route == "noop":
            return _finalize_result(
                norm=norm,
                result=_router_noop_result(
                    norm,
                    {
                        "reason": resolve_reason,
                        "route": effective_route,
                        "mode": effective_mode,
                    },
                ),
                paper_state={},
            )

        return _finalize_result(
            norm=norm,
            result=_build_blocked_result(
                norm=norm,
                detail=resolve_reason,
                effective_mode=effective_mode,
                effective_route=effective_route,
                status="blocked",
            ),
            paper_state={},
        )

    routed = ExecutionRouter().route(_build_execution_intent(req, norm)).to_dict()

    norm["mode"] = _safe_str(routed.get("mode"), norm["mode"]).lower()
    norm["route"] = _safe_str(routed.get("route"), norm["route"]).lower()
    norm["effective_mode"] = norm["mode"]
    norm["effective_route"] = norm["route"]

    if not _safe_bool(routed.get("ok"), False):
        return _finalize_result(
            norm=norm,
            result=_router_gate_result(norm, routed),
            paper_state={},
        )

    if norm["route"] == "noop":
        return _finalize_result(
            norm=norm,
            result=_router_noop_result(norm, routed),
            paper_state={},
        )

    if norm["route"] == "live":
        return _finalize_result(
            norm=norm,
            result=_build_blocked_result(
                norm=norm,
                detail="live_executor_not_enabled_in_lbot_core",
                effective_mode=norm.get("effective_mode"),
                effective_route=norm["route"],
                status="blocked",
            ),
            paper_state={},
        )

    bindings = _resolve_paper_bindings()
    paper_process_fn = bindings["paper_process_fn"]
    paper_get_state_fn = bindings["paper_get_state_fn"]
    snapshot_builder = bindings["snapshot_builder"]

    if norm["route"] != "paper":
        return _finalize_result(
            norm=norm,
            result=_build_blocked_result(
                norm=norm,
                detail="unsupported_route",
                effective_route=norm["route"],
                status="blocked",
            ),
            paper_state={},
        )

    if not callable(paper_process_fn):
        return _finalize_result(
            norm=norm,
            result=_build_blocked_result(
                norm=norm,
                detail="paper_process_fn_not_found",
                effective_route=norm["route"],
                status="blocked",
            ),
            paper_state={},
        )

    executor_raw = _call_candidate(paper_process_fn, norm, signal)
    executor = _normalize_executor_result(executor_raw)

    paper_state = _read_current_paper_state(paper_get_state_fn, signal)
    state_snapshot = _build_state_snapshot(snapshot_builder, signal, paper_state)
    action = _extract_action(executor, signal)

    journal = _write_journal_event(
        req=norm,
        signal=signal,
        action=action,
        executor_result=executor,
        paper_state=paper_state,
        state_snapshot=state_snapshot,
    )
    _write_runtime_state_latest(
        signal=signal,
        norm=norm,
        settings=settings,
        journal_event=_safe_dict(journal["event"]["journal_event"]),
        state_snapshot=state_snapshot,
    )

    return _finalize_result(
        norm=norm,
        result=_build_contract_result(
            ok=True,
            detail=None,
            reason=journal["event"]["journal_event"].get("decision_reason"),
            executor=executor,
            journal_event=journal["event"]["journal_event"],
            state_snapshot=state_snapshot,
            req_echo=_build_req_echo(mode=norm["mode"], route=norm["route"], signal=signal),
        ),
        paper_state=paper_state,
    )

def process(req: Dict[str, Any]) -> Dict[str, Any]:
    # legacy alias: SSOT  A lbot_process
    return lbot_process(req)


def process_signal(req: Dict[str, Any]) -> Dict[str, Any]:
    # ingress alias: guard        ?       o     SSOT(lbot_process)       
    raw_req = _safe_dict(req)
    if "signal" not in raw_req:
        direct_signal = _extract_signal_payload(raw_req)
        if direct_signal:
            raw_req = {
                "signal": direct_signal,
                "mode": _safe_str(raw_req.get("mode"), "dummy").lower(),
                "route": _safe_str(raw_req.get("route"), "paper").lower(),
            }

    guard_ok, guard_reason, guard_meta = validate_signal_envelope(raw_req)
    signal = _extract_signal_payload(raw_req)

    if not guard_ok:
        return _build_contract_result(
            ok=False,
            detail=guard_reason,
            reason=guard_reason,
            executor={
                "action": "hold",
                "code": guard_reason,
                "executor_result": "ingress_hold",
                "executor_status": "blocked",
                "status": "blocked",
                "reason": guard_reason,
                "guard": {
                    "ok": False,
                    "reason": guard_reason,
                    "details": guard_meta,
                },
            },
            journal_event={
                "decision_action": "hold",
                "decision_reason": guard_reason,
                "executor_result": "ingress_hold",
                "executor_status": "blocked",
                "risk_action": "hold",
                "signal_id": signal.get("signal_id"),
                "strategy": signal.get("strategy"),
                "symbol": signal.get("symbol"),
                "status": "blocked",
                "event_type": "lbot_runtime",
                "effective_mode": _safe_str(raw_req.get("mode"), "dummy").lower(),
                "effective_route": _safe_str(raw_req.get("route"), "paper").lower(),
                "ts": _safe_int(signal.get("ts")),
            },
            state_snapshot={},
            req_echo=_build_req_echo(
                mode=raw_req.get("mode"),
                route=raw_req.get("route"),
                signal=signal,
                has_signal=bool(signal),
            ),
        )

    return lbot_process(raw_req)


__all__ = ["lbot_process", "process", "process_signal", "binding_check"]