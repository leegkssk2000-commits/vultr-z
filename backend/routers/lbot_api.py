from __future__ import annotations
from backend.contracts.frontend_bridge_contract import enrich_frontend_bridge

import importlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Callable

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.engine.lbot_runtime import append_timeline_event


router = APIRouter(prefix="/api/v1/lbot", tags=["lbot"])

DATA_ROOT = Path("/home/z/z/backend/data")
JOURNAL_LATEST = DATA_ROOT / "journal" / "lbot_event.latest.json"
PAPER_STATE_LATEST = DATA_ROOT / "paper" / "paper_state.latest.json"

PROCESS_SSOT_MODULE = "backend.engine.lbot_core"
PROCESS_SSOT_NAME = "lbot_process"

STATE_BUILDER_MODULE = "backend.engine.state_read_model"
STATE_BUILDER_NAME = "build_lbot_state_snapshot"

CONTRACT_KEYS = [
    "ok",
    "detail",
    "reason",
    "status",
    "mode",
    "route",
    "effective_mode",
    "effective_route",
    "decision_action",
    "decision_reason",
    "risk_action",
    "executor_status",
    "executor_result",
    "event_type",
    "signal_id",
    "symbol",
    "strategy",
    "side",
    "ts",
    "written_at",
]


class LBotProcessRequest(BaseModel):
    mode: str = Field(default="dummy")
    route: str = Field(default="paper")
    signal: Dict[str, Any] = Field(default_factory=dict)


def _safe_read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _safe_copy_dict(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return dict(v)
    return {}


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        return value
    return None


def _normalize_state_snapshot(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    snap = raw.get("state_snapshot")
    if isinstance(snap, dict):
        return snap

    state = raw.get("state")
    if isinstance(state, dict):
        return state

    return dict(raw)


def _import_callable(module_name: str, fn_name: str) -> tuple[Callable[..., Any] | None, str | None]:
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        return None, repr(e)

    fn = getattr(mod, fn_name, None)
    if not callable(fn):
        return None, f"{module_name}.{fn_name} not callable"
    return fn, None


def _find_process_binding() -> Dict[str, Any]:
    state_builder_found = False
    state_builder_name = None
    state_builder_module = None
    state_builder_candidates_found = []

    fn, err = _import_callable(STATE_BUILDER_MODULE, STATE_BUILDER_NAME)
    if callable(fn):
        state_builder_found = True
        state_builder_name = STATE_BUILDER_NAME
        state_builder_module = STATE_BUILDER_MODULE
        state_builder_candidates_found.append(
            {"module": STATE_BUILDER_MODULE, "name": STATE_BUILDER_NAME}
        )

    process_fn_found = False
    process_candidates_found = []

    pfn, perr = _import_callable(PROCESS_SSOT_MODULE, PROCESS_SSOT_NAME)
    if callable(pfn):
        process_fn_found = True
        process_candidates_found.append(
            {"module": PROCESS_SSOT_MODULE, "name": PROCESS_SSOT_NAME}
        )

    return {
        "state_builder_found": state_builder_found,
        "state_builder_name": state_builder_name,
        "state_builder_module": state_builder_module,
        "state_builder_candidates_found": state_builder_candidates_found,
        "process_fn_found": process_fn_found,
        "process_fn_name": PROCESS_SSOT_NAME if process_fn_found else None,
        "process_fn_module": PROCESS_SSOT_MODULE if process_fn_found else None,
        "process_candidates_found": process_candidates_found,
        "paths": {
            "lbot_event_latest": str(JOURNAL_LATEST),
            "paper_state_latest": str(PAPER_STATE_LATEST),
        },
        "errors": {
            "state_builder_error": None if state_builder_found else err,
            "process_fn_error": None if process_fn_found else perr,
        },
    }


def _build_process_payload(req: LBotProcessRequest) -> Dict[str, Any]:
    signal = _safe_copy_dict(req.signal)
    return {
        "mode": req.mode,
        "route": req.route,
        "signal": signal,
    }


def _read_latest_journal_event() -> Dict[str, Any]:
    raw = _safe_read_json(JOURNAL_LATEST)
    je = raw.get("journal_event")
    return je if isinstance(je, dict) else raw


def _read_latest_paper_state() -> Dict[str, Any]:
    return _safe_read_json(PAPER_STATE_LATEST)


def _extract_contract_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    result = _safe_copy_dict(result)
    executor = _safe_copy_dict(result.get("executor"))
    journal_event = _safe_copy_dict(result.get("journal_event"))

    detail = _first_non_empty(
        result.get("detail"),
        result.get("reason"),
        result.get("decision_reason"),
        journal_event.get("decision_reason"),
        executor.get("reason"),
        executor.get("code"),
    )
    reason = _first_non_empty(
        result.get("reason"),
        result.get("detail"),
        result.get("decision_reason"),
        journal_event.get("decision_reason"),
        executor.get("reason"),
        executor.get("code"),
    )
    decision_reason = _first_non_empty(
        result.get("decision_reason"),
        journal_event.get("decision_reason"),
        reason,
        detail,
    )

    status = _first_non_empty(
        result.get("status"),
        journal_event.get("status"),
        "ok" if bool(result.get("ok")) else "blocked",
    )

    out = {
        "ok": bool(result.get("ok")),
        "detail": detail,
        "reason": reason,
        "status": status,
        "mode": _first_non_empty(result.get("mode"), journal_event.get("mode")),
        "route": _first_non_empty(result.get("route"), journal_event.get("route")),
        "effective_mode": _first_non_empty(
            result.get("effective_mode"),
            journal_event.get("effective_mode"),
            result.get("mode"),
        ),
        "effective_route": _first_non_empty(
            result.get("effective_route"),
            journal_event.get("effective_route"),
            result.get("route"),
        ),
        "decision_action": _first_non_empty(
            result.get("decision_action"),
            journal_event.get("decision_action"),
            executor.get("action"),
        ),
        "decision_reason": decision_reason,
        "risk_action": _first_non_empty(
            result.get("risk_action"),
            journal_event.get("risk_action"),
            executor.get("risk_action"),
            result.get("decision_action"),
            journal_event.get("decision_action"),
            executor.get("action"),
        ),
        "executor_status": _first_non_empty(
            result.get("executor_status"),
            executor.get("executor_status"),
            journal_event.get("executor_status"),
        ),
        "executor_result": _first_non_empty(
            result.get("executor_result"),
            executor.get("executor_result"),
            journal_event.get("executor_result"),
        ),
        "event_type": _first_non_empty(
            result.get("event_type"),
            journal_event.get("event_type"),
        ),
        "signal_id": _first_non_empty(
            result.get("signal_id"),
            journal_event.get("signal_id"),
        ),
        "symbol": _first_non_empty(
            result.get("symbol"),
            journal_event.get("symbol"),
        ),
        "strategy": _first_non_empty(
            result.get("strategy"),
            journal_event.get("strategy"),
        ),
        "side": _first_non_empty(
            result.get("side"),
            journal_event.get("side"),
        ),
        "ts": _first_non_empty(
            result.get("ts"),
            journal_event.get("ts"),
        ),
        "written_at": _first_non_empty(
            result.get("written_at"),
            journal_event.get("written_at"),
        ),
    }
    return out


def _error_result(detail: str, reason: str | None = None, **extra: Any) -> Dict[str, Any]:
    r = reason or detail
    out = {
        "ok": False,
        "detail": detail,
        "reason": r,
        "status": "blocked",
        "mode": extra.get("mode"),
        "route": extra.get("route"),
        "effective_mode": extra.get("effective_mode", extra.get("mode")),
        "effective_route": extra.get("effective_route", extra.get("route")),
        "decision_action": extra.get("decision_action", "hold"),
        "decision_reason": extra.get("decision_reason", r),
        "risk_action": extra.get("risk_action", extra.get("decision_action", "hold")),
        "executor_status": extra.get("executor_status", "blocked"),
        "executor_result": extra.get("executor_result", detail),
        "event_type": extra.get("event_type", "lbot_api"),
        "signal_id": extra.get("signal_id"),
        "symbol": extra.get("symbol"),
        "strategy": extra.get("strategy"),
        "side": extra.get("side"),
        "ts": extra.get("ts"),
        "written_at": extra.get("written_at"),
    }
    return out


def _call_process_ssot(payload: Dict[str, Any]) -> Dict[str, Any]:
    req_signal = _safe_copy_dict(payload.get("signal"))
    process_fn, _ = _import_callable(PROCESS_SSOT_MODULE, PROCESS_SSOT_NAME)
    if not callable(process_fn):
        return _error_result(
            "process_fn_not_found",
            mode=payload.get("mode"),
            route=payload.get("route"),
            signal_id=req_signal.get("signal_id"),
            symbol=req_signal.get("symbol"),
            strategy=req_signal.get("strategy"),
            side=req_signal.get("side"),
            ts=req_signal.get("ts"),
            executor_result="process_fn_not_found",
        )

    try:
        result = process_fn(payload)
    except Exception as e:
        return _error_result(
            "process_call_failed",
            reason="process_call_failed",
            mode=payload.get("mode"),
            route=payload.get("route"),
            signal_id=req_signal.get("signal_id"),
            symbol=req_signal.get("symbol"),
            strategy=req_signal.get("strategy"),
            side=req_signal.get("side"),
            ts=req_signal.get("ts"),
            executor_result=repr(e),
        )

    out = _safe_copy_dict(result)
    contract = _extract_contract_fields(out)
    out.update({k: contract.get(k) for k in CONTRACT_KEYS})
    out.setdefault("executor", _safe_copy_dict(out.get("executor")))
    out.setdefault("_binding_check", {})
    out["_binding_check"].update(
        {
            "process_fn_found": True,
            "process_fn_name": PROCESS_SSOT_NAME,
            "process_fn_module": PROCESS_SSOT_MODULE,
            "process_candidates_found": [
                {
                    "module": PROCESS_SSOT_MODULE,
                    "name": PROCESS_SSOT_NAME,
                }
            ],
        }
    )
    return out


def _call_state_builder(raw_state: Dict[str, Any], symbol: str = "", strategy: str = "") -> Dict[str, Any]:
    state_fn, _ = _import_callable(STATE_BUILDER_MODULE, STATE_BUILDER_NAME)
    if not callable(state_fn):
        snap = _normalize_state_snapshot(raw_state)
        if symbol and strategy:
            positions = snap.get("positions") if isinstance(snap.get("positions"), dict) else {}
            key = f"{symbol}::{strategy}"
            pos = positions.get(key)
            if isinstance(pos, dict):
                snap = dict(snap)
                snap["paper_state_selected"] = pos
        return snap

    call_attempts = [
        lambda: state_fn(raw_state, symbol=symbol, strategy=strategy),
        lambda: state_fn(raw_state, symbol=symbol),
        lambda: state_fn(raw_state),
    ]
    for attempt in call_attempts:
        try:
            result = attempt()
            if isinstance(result, dict):
                return dict(result)
        except TypeError:
            continue
        except Exception:
            break

    return _normalize_state_snapshot(raw_state)


def _build_state_response(symbol: str = "", strategy: str = "") -> Dict[str, Any]:
    raw_state = _read_latest_paper_state()
    snapshot = _call_state_builder(raw_state, symbol=symbol, strategy=strategy)
    contract = _extract_contract_fields(snapshot)
    out = {
        **contract,
        "ok": bool(snapshot.get("ok", True)),
        "state_snapshot": snapshot,
        "paper_state": raw_state,
        "_binding_check": _find_process_binding(),
    }
    out = enrich_frontend_bridge(
        out,
        source=str(snapshot.get("source") or "lbot_state"),
        source_ts=snapshot.get("source_ts"),
        stale=snapshot.get("stale"),
        stale_ms=snapshot.get("stale_ms"),
        reconcile_status=snapshot.get("reconcile_status"),
        journal_event=_safe_copy_dict(out.get("journal_event")),
        paper_state=_safe_copy_dict(out.get("paper_state")),
    )
    return out


def _req_echo(req: LBotProcessRequest) -> Dict[str, Any]:
    return {
        "mode": req.mode,
        "route": req.route,
        "has_signal": isinstance(req.signal, dict) and bool(req.signal),
        "signal_id": req.signal.get("signal_id") if isinstance(req.signal, dict) else None,
    }


def _append_timeline_from_contract(contract: Dict[str, Any]) -> Dict[str, Any]:
    try:
        signal_id = str(_first_non_empty(contract.get("signal_id"), "") or "")
        symbol = str(_first_non_empty(contract.get("symbol"), "") or "")
        strategy = str(_first_non_empty(contract.get("strategy"), "") or "")
        decision_action = str(_first_non_empty(contract.get("decision_action"), "") or "")
        executor_result = str(_first_non_empty(contract.get("executor_result"), contract.get("detail"), "unknown") or "unknown")

        message = f"{symbol}/{strategy} | {decision_action} | {executor_result} | {signal_id}"

        append_timeline_event(
            ts=int(time.time()),
            level="info" if bool(contract.get("ok")) else "warning",
            category="lbot",
            message=message,
            meta={
                "ok": bool(contract.get("ok")),
                "detail": contract.get("detail"),
                "reason": contract.get("reason"),
                "signal_id": signal_id,
                "symbol": symbol,
                "strategy": strategy,
                "decision_action": contract.get("decision_action"),
                "decision_reason": contract.get("decision_reason"),
                "risk_action": contract.get("risk_action"),
                "executor_status": contract.get("executor_status"),
                "executor_result": contract.get("executor_result"),
                "effective_mode": contract.get("effective_mode"),
                "effective_route": contract.get("effective_route"),
            },
        )
        return {"ok": True, "signal_id": signal_id}
    except Exception as e:
        return {"ok": False, "error": repr(e)}
@router.get("/debug/process-binding")
async def lbot_debug_process_binding() -> Dict[str, Any]:
    return {
        "ok": True,
        "binding": _find_process_binding(),
    }

@router.get("/state")
async def lbot_state(symbol: str = "", strategy: str = "") -> Dict[str, Any]:
    return _build_state_response(symbol=symbol, strategy=strategy)

@router.post("/process")
async def lbot_process(req: LBotProcessRequest) -> Dict[str, Any]:
    payload = _build_process_payload(req)
    result = _call_process_ssot(payload)

    journal_event = _read_latest_journal_event()
    paper_state = _read_latest_paper_state()

    state_symbol = _first_non_empty(
        result.get("symbol"),
        req.signal.get("symbol") if isinstance(req.signal, dict) else None,
    ) or ""
    state_strategy = _first_non_empty(
        result.get("strategy"),
        req.signal.get("strategy") if isinstance(req.signal, dict) else None,
    ) or ""

    state_snapshot = _call_state_builder(
        paper_state,
        symbol=state_symbol,
        strategy=state_strategy,
    )

    contract = _extract_contract_fields(result)
    timeline_append = _append_timeline_from_contract(contract)

    payload = {
        **contract,
        "executor": _safe_copy_dict(result.get("executor")),
        "journal_event": journal_event,
        "state_snapshot": state_snapshot,
        "_binding_check": result.get("_binding_check", _find_process_binding()),
        "_req_echo": _req_echo(req),
        "_timeline_append": timeline_append,
    }
    return enrich_frontend_bridge(
        payload,
        source=str(state_snapshot.get("source") or "lbot_process"),
        source_ts=state_snapshot.get("source_ts"),
        stale=state_snapshot.get("stale"),
        stale_ms=state_snapshot.get("stale_ms"),
        reconcile_status=state_snapshot.get("reconcile_status"),
        journal_event=journal_event,
        paper_state=_safe_copy_dict(result.get("paper_state")),
    )


@router.post("/debug/process-bind")
async def lbot_process_bind(req: LBotProcessRequest) -> Dict[str, Any]:
    payload = _build_process_payload(req)
    binding = _find_process_binding()

    if not binding.get("process_fn_found"):
        signal = _safe_copy_dict(req.signal)
        return {
            **_error_result(
                "process_fn_not_found",
                mode=req.mode,
                route=req.route,
                signal_id=signal.get("signal_id"),
                symbol=signal.get("symbol"),
                strategy=signal.get("strategy"),
                side=signal.get("side"),
                ts=signal.get("ts"),
            ),
            "binding": binding,
            "_req_echo": _req_echo(req),
            "_timeline_append": {"ok": False, "error": "process_fn_not_found"},
        }

    result = _call_process_ssot(payload)
    journal_event = _read_latest_journal_event()
    paper_state = _read_latest_paper_state()

    state_symbol = _first_non_empty(
        result.get("symbol"),
        req.signal.get("symbol") if isinstance(req.signal, dict) else None,
    ) or ""
    state_strategy = _first_non_empty(
        result.get("strategy"),
        req.signal.get("strategy") if isinstance(req.signal, dict) else None,
    ) or ""

    state_snapshot = _call_state_builder(
        paper_state,
        symbol=state_symbol,
        strategy=state_strategy,
    )

    contract = _extract_contract_fields(result)
    timeline_append = _append_timeline_from_contract(contract)

    return {
        **contract,
        "executor": _safe_copy_dict(result.get("executor")),
        "journal_event": journal_event,
        "state_snapshot": state_snapshot,
        "_binding_check": result.get("_binding_check", binding),
        "_req_echo": _req_echo(req),
        "_timeline_append": timeline_append,
    }
