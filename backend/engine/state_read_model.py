from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

from backend.contracts.null_error_contract import NULL_ERROR_CONTRACT_VERSION, normalize_reason

try:
    from backend.engine.bot_dna_resolver import resolve_bot_dna
except Exception:
    resolve_bot_dna = None  # type: ignore

try:
    from backend.engine.skill_resolver import (
        load_schema_lock,
        load_skill_registry,
        resolve_effective_skills,
    )
except Exception:
    load_schema_lock = None  # type: ignore
    load_skill_registry = None  # type: ignore
    resolve_effective_skills = None  # type: ignore

try:
    from backend.engine.strategy_registry import get_strategy_spec
except Exception:
    get_strategy_spec = None  # type: ignore

CONTRACT_DECISION_ACTIONS = {
    "enter",
    "add",
    "reduce",
    "exit",
    "hold",
    "block",
    "noop",
}

CONTRACT_RISK_ACTIONS = {
    "hold",
    "block",
    "reduce25",
    "partial30",
    "stop",
    "rollback",
    "route_change",
}

MODE_ALIASES = {
    "shadow": "shadow",
    "paper": "paper",
    "live": "live",
    "dummy": "dummy",
}

ROUTE_ALIASES = {
    "shadow": "shadow",
    "paper": "paper",
    "live": "live",
    "dummy": "dummy",
}

SIDE_ALIASES = {
    "long": "long",
    "buy": "long",
    "short": "short",
    "sell": "short",
}

STATUS_ALIASES = {
    "applied": "done",
    "idle": "noop",
}

EXECUTOR_STATUS_ALIASES = {
    "applied": "paper",
    "idle": "noop",
}


def _safe_dict(v: Any) -> Dict[str, Any]:
    return deepcopy(v) if isinstance(v, dict) else {}


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _safe_ts(v: Any, default: Any = "") -> Any:
    if v is None or v == "":
        return default
    if isinstance(v, (int, float)):
        return int(v)
    s = _safe_str(v)
    if not s:
        return default
    if s.isdigit():
        try:
            return int(s)
        except Exception:
            return s
    return s


def _norm_mode(v: Any) -> str:
    s = _safe_str(v).lower()
    return MODE_ALIASES.get(s, s)


def _norm_route(v: Any) -> str:
    s = _safe_str(v).lower()
    return ROUTE_ALIASES.get(s, s)


def _norm_side(v: Any) -> str:
    s = _safe_str(v).lower()
    return SIDE_ALIASES.get(s, "")


def _norm_decision_action(v: Any) -> str:
    s = _safe_str(v).lower()
    return s if s in CONTRACT_DECISION_ACTIONS else ""


def _norm_risk_action(v: Any) -> str:
    s = _safe_str(v).lower()
    return s if s in CONTRACT_RISK_ACTIONS else ""


def _norm_status(v: Any) -> str:
    s = _safe_str(v).lower()
    return STATUS_ALIASES.get(s, s)


def _norm_executor_status(v: Any) -> str:
    s = _safe_str(v).lower()
    return EXECUTOR_STATUS_ALIASES.get(s, s)


def _norm_event_type(v: Any) -> str:
    return _safe_str(v).lower()


def _pos_key(symbol: str, strategy: str) -> str:
    return f"{symbol}::{strategy}"


def _split_pos_key(key: str) -> Tuple[str, str]:
    if not key or "::" not in key:
        return "", ""
    a, b = key.split("::", 1)
    return _safe_str(a), _safe_str(b)


def _normalize_position(src: Dict[str, Any], fallback_key: str = "") -> Dict[str, Any]:
    raw = _safe_dict(src)
    sym_from_key, strat_from_key = _split_pos_key(fallback_key)

    out = deepcopy(raw)
    out["symbol"] = _safe_str(raw.get("symbol")) or sym_from_key
    out["strategy"] = _safe_str(raw.get("strategy")) or strat_from_key
    out["position_side"] = _norm_side(raw.get("position_side") or raw.get("side"))
    out["position_qty"] = _safe_float(raw.get("position_qty") or raw.get("qty"))
    out["avg_entry"] = _safe_float(raw.get("avg_entry") or raw.get("entry_price"))
    out["add_count"] = _safe_int(raw.get("add_count"))
    out["last_add_price"] = _safe_float(raw.get("last_add_price"))
    out["realized_pnl"] = _safe_float(raw.get("realized_pnl"))
    out["unrealized_pnl"] = _safe_float(raw.get("unrealized_pnl"))
    out["last_signal_id"] = _safe_str(raw.get("last_signal_id") or raw.get("signal_id"))
    out["last_action"] = _norm_decision_action(raw.get("last_action") or raw.get("decision_action"))
    out["updated_at"] = _safe_str(raw.get("updated_at") or raw.get("written_at"))
    return out


def _normalize_positions_map(positions: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in positions.items():
        ks = _safe_str(k)
        if isinstance(v, dict):
            norm = _normalize_position(v, ks)
            final_key = ks or _pos_key(norm.get("symbol", ""), norm.get("strategy", ""))
            out[final_key] = norm
    return out


def _extract_selected_from_positions(
    positions: Dict[str, Any],
    symbol: str,
    strategy: str,
) -> Dict[str, Any]:
    if not positions:
        return {}

    if symbol and strategy:
        hit = positions.get(_pos_key(symbol, strategy))
        if isinstance(hit, dict):
            return deepcopy(hit)

    for _, v in positions.items():
        if isinstance(v, dict):
            qty = _safe_float(v.get("position_qty"))
            side = _norm_side(v.get("position_side"))
            if qty > 0.0 and side:
                return deepcopy(v)

    for _, v in positions.items():
        if isinstance(v, dict):
            return deepcopy(v)

    return {}


def _build_contract_base() -> Dict[str, Any]:
    return {
        "ok": True,
        "contract_version": NULL_ERROR_CONTRACT_VERSION,
        "detail": "",
        "reason": "",
        "status": "",
        "mode": "",
        "route": "",
        "decision_action": "",
        "decision_reason": "",
        "risk_action": "",
        "executor_status": "",
        "executor_result": "",
        "effective_mode": "",
        "effective_route": "",
        "event_id": "",
        "decision_id": "",
        "event_type": "",
        "signal_id": "",
        "strategy": "",
        "symbol": "",
        "side": "",
        "ts": "",
        "written_at": "",
        "updated_at": "",
        "position_side": "",
        "position_qty": 0.0,
        "avg_entry": 0.0,
        "add_count": 0,
        "last_add_price": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "last_signal_id": "",
        "last_action": "",
        "last_symbol": "",
        "last_strategy": "",
        "positions": {},
        "paper_state_selected": {
            "symbol": "",
            "strategy": "",
            "position_side": "",
            "position_qty": 0.0,
            "avg_entry": 0.0,
            "add_count": 0,
            "last_add_price": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "last_signal_id": "",
            "last_action": "",
            "updated_at": "",
        },
        "selected_bot_id": "",
        "deploy_stage": "",
        "strategy_grade": "",
        "effective_strategy_skill_ids": [],
        "effective_bot_skill_ids": [],
        "active_os_guard_skill_ids": [],
        "learning_only_skill_ids": [],
        "blocked_skill_ids": [],
        "blocked_reason": {},
    }


def _build_top_from_selected(selected: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    sel = _normalize_position(selected)
    top = _build_contract_base()

    top["ok"] = bool(state.get("ok", True))
    top["detail"] = _safe_str(state.get("detail"))
    top["reason"] = _safe_str(state.get("reason") or state.get("detail") or state.get("decision_reason"))
    top["status"] = _norm_status(state.get("status"))
    top["mode"] = _norm_mode(state.get("mode"))
    top["route"] = _norm_route(state.get("route"))
    top["decision_action"] = _norm_decision_action(state.get("decision_action") or state.get("last_action"))
    top["decision_reason"] = _safe_str(
        state.get("decision_reason") or state.get("reason") or state.get("detail")
    )
    top["risk_action"] = _norm_risk_action(state.get("risk_action"))
    top["executor_status"] = _norm_executor_status(state.get("executor_status"))
    top["executor_result"] = _safe_str(state.get("executor_result"))
    top["effective_mode"] = _norm_mode(state.get("effective_mode") or state.get("mode"))
    top["effective_route"] = _norm_route(state.get("effective_route") or state.get("route"))
    top["event_type"] = _norm_event_type(state.get("event_type"))
    top["event_id"] = _safe_str(state.get("event_id") or state.get("signal_id") or sel.get("last_signal_id"))
    top["decision_id"] = _safe_str(state.get("decision_id") or state.get("signal_id") or sel.get("last_signal_id"))
    top["signal_id"] = _safe_str(state.get("signal_id") or sel.get("last_signal_id"))
    top["strategy"] = _safe_str(state.get("strategy") or sel.get("strategy") or state.get("last_strategy"))
    top["symbol"] = _safe_str(state.get("symbol") or sel.get("symbol") or state.get("last_symbol"))
    top["side"] = _norm_side(state.get("side") or sel.get("position_side"))
    top["ts"] = _safe_ts(state.get("ts"))
    top["written_at"] = _safe_str(state.get("written_at") or state.get("updated_at"))
    top["updated_at"] = _safe_str(state.get("updated_at") or state.get("written_at") or sel.get("updated_at"))

    top["position_side"] = sel["position_side"]
    top["position_qty"] = sel["position_qty"]
    top["avg_entry"] = sel["avg_entry"]
    top["add_count"] = sel["add_count"]
    top["last_add_price"] = sel["last_add_price"]
    top["realized_pnl"] = sel["realized_pnl"]
    top["unrealized_pnl"] = sel["unrealized_pnl"]
    top["last_signal_id"] = sel["last_signal_id"]
    top["last_action"] = sel["last_action"]
    top["last_symbol"] = sel["symbol"] or _safe_str(state.get("last_symbol"))
    top["last_strategy"] = sel["strategy"] or _safe_str(state.get("last_strategy"))

    return top


def _attach_resolved_skill_fields(out: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    strategy_id = _safe_str(out.get("strategy") or out.get("last_strategy"))
    market = _safe_str(out.get("symbol") or out.get("last_symbol"))
    regime = _safe_str(state.get("regime") or state.get("market_regime"))
    selected_bot_id = _safe_str(
        state.get("selected_bot_id")
        or state.get("bot_id")
    )
    deploy_stage = _safe_str(state.get("deploy_stage"))
    strategy_grade = _safe_str(state.get("strategy_grade"))

    strategy_doc: Dict[str, Any] = {}
    if callable(get_strategy_spec) and strategy_id:
        try:
            strategy_doc = _safe_dict(get_strategy_spec(strategy_id))
        except Exception:
            strategy_doc = {}

    if not selected_bot_id:
        selected_bot_id = _safe_str(strategy_doc.get("bot_id"))

    if not deploy_stage:
        deploy_stage = _safe_str(strategy_doc.get("deploy_stage") or strategy_doc.get("onboarding_stage"))

    if not strategy_grade:
        strategy_grade = _safe_str(strategy_doc.get("grade"))

    out["selected_bot_id"] = selected_bot_id
    out["deploy_stage"] = deploy_stage
    out["strategy_grade"] = strategy_grade

    if (
        callable(resolve_bot_dna)
        and callable(resolve_effective_skills)
        and callable(load_skill_registry)
        and callable(load_schema_lock)
        and selected_bot_id
        and strategy_doc
    ):
        try:
            bot_dna = resolve_bot_dna(
                selected_bot_id,
                symbol=market,
                strategy_id=strategy_id,
                regime=regime,
                settings_snapshot=state,
            )
            resolved = resolve_effective_skills(
                strategy_doc,
                bot_dna,
                load_skill_registry(),
                load_schema_lock(),
                regime=regime,
                deploy_stage=deploy_stage,
                market=market,
            )
            out["effective_strategy_skill_ids"] = resolved.get("effective_strategy_skill_ids", [])
            out["effective_bot_skill_ids"] = resolved.get("effective_bot_skill_ids", [])
            out["active_os_guard_skill_ids"] = resolved.get("active_os_guard_skill_ids", [])
            out["learning_only_skill_ids"] = resolved.get("learning_only_skill_ids", [])
            out["blocked_skill_ids"] = resolved.get("blocked_skill_ids", [])
            out["blocked_reason"] = resolved.get("blocked_reason", {})
        except Exception:
            pass

    return out


def build_lbot_state_snapshot(
    paper_state: Optional[Dict[str, Any]] = None,
    symbol: str = "",
    strategy: str = "",
) -> Dict[str, Any]:
    state = _safe_dict(paper_state)
    out = _build_contract_base()

    for k, v in state.items():
        if k not in ("positions", "paper_state_selected"):
            out[k] = deepcopy(v)

    req_symbol = _safe_str(symbol)
    req_strategy = _safe_str(strategy)

    positions = _normalize_positions_map(_safe_dict(state.get("positions")))
    selected = _safe_dict(state.get("paper_state_selected"))

    selected_symbol = _safe_str(selected.get("symbol"))
    selected_strategy = _safe_str(selected.get("strategy"))

    if not selected:
        selected = _extract_selected_from_positions(positions, req_symbol, req_strategy)

    if not selected and selected_symbol and selected_strategy:
        selected = _extract_selected_from_positions(positions, selected_symbol, selected_strategy)

    selected = _normalize_position(selected)

    if not selected.get("symbol"):
        selected["symbol"] = req_symbol or _safe_str(state.get("symbol")) or _safe_str(state.get("last_symbol"))
    if not selected.get("strategy"):
        selected["strategy"] = req_strategy or _safe_str(state.get("strategy")) or _safe_str(state.get("last_strategy"))
    if not selected.get("last_signal_id"):
        selected["last_signal_id"] = _safe_str(state.get("signal_id") or state.get("last_signal_id"))
    if not selected.get("updated_at"):
        selected["updated_at"] = _safe_str(state.get("updated_at") or state.get("written_at"))

    top = _build_top_from_selected(selected, state)

    out.update(top)
    out["positions"] = deepcopy(positions)
    out["paper_state_selected"] = deepcopy(selected)

    out["last_symbol"] = _safe_str(out.get("last_symbol") or out.get("symbol"))
    out["last_strategy"] = _safe_str(out.get("last_strategy") or out.get("strategy"))
    out["event_id"] = _safe_str(out.get("event_id") or out.get("signal_id") or out.get("last_signal_id"))
    out["decision_id"] = _safe_str(out.get("decision_id") or out.get("signal_id") or out.get("last_signal_id"))
    out["signal_id"] = _safe_str(out.get("signal_id") or out.get("last_signal_id"))
    out["reason"] = normalize_reason(detail=out.get("detail"), reason=out.get("reason") or out.get("decision_reason"), default="ok")
    out["decision_reason"] = normalize_reason(detail=out.get("detail"), reason=out.get("decision_reason") or out.get("reason"), default="ok")
    out["effective_mode"] = _norm_mode(out.get("effective_mode") or out.get("mode"))
    out["effective_route"] = _norm_route(out.get("effective_route") or out.get("route"))
    out["side"] = _norm_side(out.get("side") or out.get("position_side"))
    out["status"] = _norm_status(out.get("status"))
    out["event_type"] = _norm_event_type(out.get("event_type"))
    out["last_action"] = _norm_decision_action(out.get("last_action"))
    out["decision_action"] = _norm_decision_action(out.get("decision_action"))
    out["risk_action"] = _norm_risk_action(out.get("risk_action"))
    out["executor_status"] = _norm_executor_status(out.get("executor_status"))
    out["mode"] = _norm_mode(out.get("mode"))
    out["route"] = _norm_route(out.get("route"))
    out["ts"] = _safe_ts(out.get("ts"))
    out["written_at"] = _safe_str(out.get("written_at") or out.get("updated_at"))
    out["updated_at"] = _safe_str(out.get("updated_at") or out.get("written_at"))

    out = _attach_resolved_skill_fields(out, state)
    return out


__all__ = ["build_lbot_state_snapshot", "CONTRACT_DECISION_ACTIONS", "CONTRACT_RISK_ACTIONS"]
