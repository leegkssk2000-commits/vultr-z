from __future__ import annotations
from backend.contracts.null_error_contract import NULL_ERROR_CONTRACT_VERSION
from backend.contracts.frontend_bridge_contract import build_frontend_bridge_meta

import json
from pathlib import Path
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, ConfigDict

try:
    from backend.engine.state_read_model import build_lbot_state_snapshot  # type: ignore
except Exception:
    build_lbot_state_snapshot = None  # type: ignore

router = APIRouter(tags=["state"])

BASE_DIR = Path("/home/z/z/backend/data")
PAPER_STATE_PATH = BASE_DIR / "paper" / "paper_state.latest.json"
JOURNAL_EVENT_PATH = BASE_DIR / "journal" / "lbot_event.latest.json"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        s = str(value).strip()
        return s if s else default
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip() == "":
                continue
            return value
        return value
    return None


def _mtime_ms(path: Path) -> Optional[int]:
    try:
        return int(path.stat().st_mtime * 1000)
    except Exception:
        return None


def _norm_symbol(value: Any) -> str:
    return _safe_str(value).upper().strip()


def _norm_strategy(value: Any) -> str:
    return _safe_str(value).lower().strip()


def _make_key(symbol: str, strategy: str) -> str:
    return f"{_norm_symbol(symbol)}::{_norm_strategy(strategy)}"


def _extract_positions(paper: Dict[str, Any]) -> Dict[str, Any]:
    account = _safe_dict(paper.get("account"))
    account_snapshot = _safe_dict(paper.get("account_state_snapshot"))

    for candidate in (
        paper.get("positions"),
        account.get("positions"),
        account_snapshot.get("positions"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _extract_balances(paper: Dict[str, Any]) -> Dict[str, Any]:
    account = _safe_dict(paper.get("account"))
    account_snapshot = _safe_dict(paper.get("account_state_snapshot"))

    for candidate in (
        paper.get("balances"),
        account.get("balances"),
        account_snapshot.get("balances"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _extract_equity(paper: Dict[str, Any]) -> float:
    account = _safe_dict(paper.get("account"))
    account_snapshot = _safe_dict(paper.get("account_state_snapshot"))

    for candidate in (
        paper.get("equity"),
        account.get("equity"),
        account_snapshot.get("equity"),
    ):
        if candidate is not None and candidate != "":
            return _safe_float(candidate)
    return 0.0


def _select_position(
    positions: Dict[str, Any],
    symbol: str,
    strategy: str,
) -> Dict[str, Any]:
    if not isinstance(positions, dict):
        return {}

    key = _make_key(symbol, strategy)
    pos = positions.get(key)
    if isinstance(pos, dict):
        return pos

    symbol_norm = _norm_symbol(symbol)
    strategy_norm = _norm_strategy(strategy)

    for item in positions.values():
        if not isinstance(item, dict):
            continue
        if (
            _norm_symbol(item.get("symbol")) == symbol_norm
            and _norm_strategy(item.get("strategy")) == strategy_norm
        ):
            return item

    for item in positions.values():
        if isinstance(item, dict):
            qty = _safe_float(item.get("position_qty") or item.get("qty"))
            side = _safe_str(item.get("position_side") or item.get("side"))
            if qty > 0 and side:
                return item

    return {}


def _normalize_selected(raw: Dict[str, Any], symbol: str = "", strategy: str = "") -> Dict[str, Any]:
    return {
        "symbol": _safe_str(raw.get("symbol")) or _norm_symbol(symbol),
        "strategy": _safe_str(raw.get("strategy")) or _norm_strategy(strategy),
        "position_side": _safe_str(raw.get("position_side") or raw.get("side")),
        "position_qty": _safe_float(raw.get("position_qty") or raw.get("qty")),
        "avg_entry": _safe_float(raw.get("avg_entry") or raw.get("entry_price")),
        "add_count": _safe_int(raw.get("add_count")),
        "last_add_price": _safe_float(raw.get("last_add_price")),
        "realized_pnl": _safe_float(raw.get("realized_pnl")),
        "unrealized_pnl": _safe_float(raw.get("unrealized_pnl")),
        "last_signal_id": _safe_str(raw.get("last_signal_id") or raw.get("signal_id")),
        "last_action": _safe_str(raw.get("last_action") or raw.get("decision_action")),
        "updated_at": _safe_str(raw.get("updated_at") or raw.get("written_at")),
    }


def _derive_source_meta(snapshot: Dict[str, Any], paper: Dict[str, Any], journal: Dict[str, Any]) -> Dict[str, Any]:
    journal_event = _safe_dict(journal.get("journal_event"))

    source = _first_non_empty(
        snapshot.get("source"),
        paper.get("source"),
        journal_event.get("source"),
        journal.get("source"),
        f"json:{PAPER_STATE_PATH}",
    )
    source_ts = _first_non_empty(
        snapshot.get("source_ts"),
        paper.get("source_ts"),
        journal_event.get("source_ts"),
        journal.get("source_ts"),
        _mtime_ms(PAPER_STATE_PATH),
        _mtime_ms(JOURNAL_EVENT_PATH),
    )
    source_internal = _first_non_empty(
        snapshot.get("_source"),
        paper.get("_source"),
        journal_event.get("_source"),
        journal.get("_source"),
        source,
    )
    source_ts_internal = _first_non_empty(
        snapshot.get("_source_ts"),
        paper.get("_source_ts"),
        journal_event.get("_source_ts"),
        journal.get("_source_ts"),
        source_ts,
    )
    stale = bool(_first_non_empty(snapshot.get("stale"), paper.get("stale"), journal.get("stale"), False))
    stale_ms = _safe_int(_first_non_empty(snapshot.get("stale_ms"), paper.get("stale_ms"), journal.get("stale_ms"), 0))
    reconcile_status = _safe_str(_first_non_empty(snapshot.get("reconcile_status"), paper.get("reconcile_status"), journal.get("reconcile_status"), "ok"), "ok")
    decision_id = _safe_str(_first_non_empty(snapshot.get("decision_id"), journal_event.get("decision_id"), paper.get("decision_id"), journal.get("decision_id")), "")

    return {
        "source": _safe_str(source),
        "source_ts": source_ts,
        "_source": _safe_str(source_internal),
        "_source_ts": source_ts_internal,
        "stale": stale,
        "stale_ms": stale_ms,
        "reconcile_status": reconcile_status,
        "decision_id": decision_id or None,
    }


def _build_state_base(
    paper: Dict[str, Any],
    journal: Dict[str, Any],
    symbol: str = "",
    strategy: str = "",
) -> Dict[str, Any]:
    account = _safe_dict(paper.get("account"))
    sync_state = _safe_dict(paper.get("sync_state"))
    journal_event = _safe_dict(journal.get("journal_event"))
    executor = _safe_dict(journal.get("executor"))
    positions = _extract_positions(paper)
    balances = _extract_balances(paper)

    selected = _safe_dict(
        _first_non_empty(
            paper.get("paper_state_selected"),
            journal.get("paper_state_selected"),
        )
    )

    if not selected:
        selected = _select_position(
            positions,
            _safe_str(_first_non_empty(symbol, journal_event.get("symbol"), paper.get("symbol"))),
            _safe_str(_first_non_empty(strategy, journal_event.get("strategy"), paper.get("strategy"))),
        )

    selected = _normalize_selected(selected, symbol=symbol, strategy=strategy)

    merged = {
        "ok": True,
        "source": "paper_state_latest",
        "paper_state_selected": selected,
        "positions": positions,
        "balances": balances,
        "equity": _extract_equity(paper),
        "sync_state": sync_state,
        "journal_event": journal_event,
        "executor": executor,
        "account": account,
        "mode": _safe_str(_first_non_empty(journal.get("mode"), paper.get("mode"))),
        "route": _safe_str(_first_non_empty(journal.get("route"), paper.get("route"))),
        "effective_mode": _safe_str(_first_non_empty(journal.get("effective_mode"), paper.get("effective_mode"), journal.get("mode"), paper.get("mode"))),
        "effective_route": _safe_str(_first_non_empty(journal.get("effective_route"), paper.get("effective_route"), journal.get("route"), paper.get("route"))),
        "decision_action": _safe_str(_first_non_empty(journal_event.get("decision_action"), paper.get("decision_action"), selected.get("last_action"))),
        "decision_reason": _safe_str(_first_non_empty(journal_event.get("decision_reason"), journal_event.get("reason"), paper.get("decision_reason"), paper.get("reason"), paper.get("detail"))),
        "risk_action": _safe_str(_first_non_empty(journal_event.get("risk_action"), paper.get("risk_action"))),
        "executor_status": _safe_str(_first_non_empty(executor.get("status"), journal_event.get("executor_status"), paper.get("executor_status"))),
        "executor_result": _safe_str(_first_non_empty(executor.get("result"), journal_event.get("executor_result"), paper.get("executor_result"))),
        "signal_id": _safe_str(_first_non_empty(journal_event.get("signal_id"), selected.get("last_signal_id"), paper.get("signal_id"))),
        "event_type": _safe_str(_first_non_empty(journal_event.get("event_type"), journal_event.get("type"), paper.get("event_type"))),
        "status": _safe_str(_first_non_empty(journal.get("status"), executor.get("status"), paper.get("status"))),
        "symbol": _safe_str(_first_non_empty(journal_event.get("symbol"), selected.get("symbol"), paper.get("symbol"))),
        "strategy": _safe_str(_first_non_empty(journal_event.get("strategy"), selected.get("strategy"), paper.get("strategy"))),
        "side": _safe_str(_first_non_empty(journal_event.get("side"), selected.get("position_side"), paper.get("side"))),
        "last_symbol": _safe_str(_first_non_empty(journal_event.get("symbol"), selected.get("symbol"), paper.get("last_symbol"))),
        "last_strategy": _safe_str(_first_non_empty(journal_event.get("strategy"), selected.get("strategy"), paper.get("last_strategy"))),
        "written_at": _safe_str(_first_non_empty(journal_event.get("updated_at"), paper.get("updated_at"), selected.get("updated_at"))),
        "updated_at": _safe_str(_first_non_empty(journal_event.get("updated_at"), paper.get("updated_at"), selected.get("updated_at"))),
        "ts": _first_non_empty(journal_event.get("ts"), journal.get("ts"), paper.get("ts")),
    }

    merged["positions_count"] = _safe_int(
        _first_non_empty(account.get("positions_count"), len(positions))
    )
    return merged


def _build_snapshot(
    paper: Dict[str, Any],
    journal: Dict[str, Any],
    symbol: str = "",
    strategy: str = "",
) -> Dict[str, Any]:
    base = _build_state_base(paper, journal, symbol=symbol, strategy=strategy)

    if callable(build_lbot_state_snapshot):
        try:
            snapshot = build_lbot_state_snapshot(
                base,
                symbol=symbol,
                strategy=strategy,
            )
            if isinstance(snapshot, dict):
                snapshot.update(_derive_source_meta(snapshot, paper, journal))
                return snapshot
        except Exception:
            pass

    base.update(_derive_source_meta(base, paper, journal))
    return base

def _build_bridge(snapshot: Dict[str, Any], paper: Dict[str, Any], journal: Dict[str, Any]) -> Dict[str, Any]:
    return build_frontend_bridge_meta(
        snapshot,
        source=_safe_str(snapshot.get("source"), "paper_state_latest"),
        source_ts=snapshot.get("source_ts"),
        stale=bool(snapshot.get("stale", False)),
        stale_ms=_safe_int(snapshot.get("stale_ms")),
        reconcile_status=_safe_str(snapshot.get("reconcile_status"), "ok"),
        journal_event=_safe_dict(journal.get("journal_event")),
        paper_state=paper,
        paths={
            "paper_state_path": str(PAPER_STATE_PATH),
            "journal_event_path": str(JOURNAL_EVENT_PATH),
        },
    )



class PaperPositionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    found: bool = False
    symbol: str = ""
    strategy: str = ""
    key: str = ""
    position_side: str = ""
    position_qty: float = 0.0
    avg_entry: float = 0.0
    add_count: int = 0
    last_add_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    last_signal_id: str = ""
    last_action: str = ""
    updated_at: Optional[str] = None
    source: str = ""
    source_ts: Optional[int] = None
    source_internal: str = Field(default="", alias="_source", serialization_alias="_source")
    source_ts_internal: Optional[int] = Field(default=None, alias="_source_ts", serialization_alias="_source_ts")
    stale: bool = False
    stale_ms: int = 0
    reconcile_status: str = "ok"
    decision_id: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)

    backend_ver: str = ""
    verification_status: str = ""
    change_digest: str = ""
    delta_summary: str = ""
    why_now: str = ""
    why_not_now: str = ""
    route_reason: str = ""
    next_best_action: str = ""
    recovery_path: str = ""
    replay_anchor: Dict[str, Any] = Field(default_factory=dict)


class PaperStateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    ok: bool = True
    source: str = "paper_state_latest"
    source_ts: Optional[int] = None
    source_internal: str = Field(default="", alias="_source", serialization_alias="_source")
    source_ts_internal: Optional[int] = Field(default=None, alias="_source_ts", serialization_alias="_source_ts")
    stale: bool = False
    stale_ms: int = 0
    reconcile_status: str = "ok"
    decision_id: Optional[str] = None
    paper_state_path: str = ""
    journal_event_path: str = ""
    mode: str = ""
    route: str = ""
    effective_mode: str = ""
    effective_route: str = ""
    decision_action: str = ""
    decision_reason: str = ""
    risk_action: str = ""
    executor_status: str = ""
    executor_result: str = ""
    signal_id: str = ""
    strategy: str = ""
    symbol: str = ""
    side: str = ""
    updated_at: str = ""
    positions_count: int = 0
    equity: float = 0.0
    balances: Dict[str, Any] = Field(default_factory=dict)
    positions: Dict[str, Any] = Field(default_factory=dict)
    paper_state_selected: Dict[str, Any] = Field(default_factory=dict)
    selected_position: Dict[str, Any] = Field(default_factory=dict)
    state_snapshot: Dict[str, Any] = Field(default_factory=dict)
    sync_state: Dict[str, Any] = Field(default_factory=dict)
    journal_event: Dict[str, Any] = Field(default_factory=dict)
    executor: Dict[str, Any] = Field(default_factory=dict)
    account: Dict[str, Any] = Field(default_factory=dict)
    selected_bot_id: str = ""
    deploy_stage: str = ""
    strategy_grade: str = ""
    effective_strategy_skill_ids: List[str] = Field(default_factory=list)
    effective_bot_skill_ids: List[str] = Field(default_factory=list)
    active_os_guard_skill_ids: List[str] = Field(default_factory=list)
    learning_only_skill_ids: List[str] = Field(default_factory=list)
    blocked_skill_ids: List[str] = Field(default_factory=list)
    blocked_reason: Dict[str, Any] = Field(default_factory=dict)

    backend_ver: str = ""
    verification_status: str = ""
    change_digest: str = ""
    delta_summary: str = ""
    why_now: str = ""
    why_not_now: str = ""
    route_reason: str = ""
    next_best_action: str = ""
    recovery_path: str = ""
    replay_anchor: Dict[str, Any] = Field(default_factory=dict)


@router.get("/state/paper", response_model=PaperStateResponse)
@router.get("/api/v1/state/paper", response_model=PaperStateResponse, include_in_schema=False)
def get_paper_state() -> PaperStateResponse:
    paper = _read_json(PAPER_STATE_PATH)
    journal = _read_json(JOURNAL_EVENT_PATH)
    snapshot = _build_snapshot(paper, journal)
    bridge = _build_bridge(snapshot, paper, journal)

    positions = _safe_dict(snapshot.get("positions"))
    selected = _safe_dict(snapshot.get("paper_state_selected"))
    balances = _extract_balances(paper)
    account = _safe_dict(paper.get("account"))
    sync_state = _safe_dict(paper.get("sync_state"))
    journal_event = _safe_dict(journal.get("journal_event"))
    executor = _safe_dict(journal.get("executor"))

    return PaperStateResponse(
        ok=True,
        source=_safe_str(snapshot.get("source"), "paper_state_latest"),
        source_ts=snapshot.get("source_ts"),
        _source=_safe_str(snapshot.get("_source"), _safe_str(snapshot.get("source"), "paper_state_latest")),
        _source_ts=snapshot.get("_source_ts"),
        stale=bool(snapshot.get("stale", False)),
        stale_ms=_safe_int(snapshot.get("stale_ms")),
        reconcile_status=_safe_str(snapshot.get("reconcile_status"), "ok"),
        decision_id=_safe_str(snapshot.get("decision_id")) or None,
        paper_state_path=str(PAPER_STATE_PATH),
        journal_event_path=str(JOURNAL_EVENT_PATH),
        mode=_safe_str(snapshot.get("mode")),
        route=_safe_str(snapshot.get("route")),
        effective_mode=_safe_str(snapshot.get("effective_mode")),
        effective_route=_safe_str(snapshot.get("effective_route")),
        decision_action=_safe_str(snapshot.get("decision_action")),
        decision_reason=_safe_str(snapshot.get("decision_reason")),
        risk_action=_safe_str(snapshot.get("risk_action")),
        executor_status=_safe_str(snapshot.get("executor_status")),
        executor_result=_safe_str(snapshot.get("executor_result")),
        signal_id=_safe_str(snapshot.get("signal_id")),
        strategy=_safe_str(snapshot.get("strategy")),
        symbol=_safe_str(snapshot.get("symbol")),
        side=_safe_str(snapshot.get("side")),
        updated_at=_safe_str(snapshot.get("updated_at")),
        positions_count=_safe_int(snapshot.get("positions_count") or len(positions)),
        equity=_safe_float(snapshot.get("equity")),
        balances=balances,
        positions=positions,
        paper_state_selected=selected,
        selected_position=selected,
        state_snapshot=snapshot,
        sync_state=sync_state,
        journal_event=journal_event,
        executor=executor,
        account=account,
        selected_bot_id=_safe_str(snapshot.get("selected_bot_id")),
        deploy_stage=_safe_str(snapshot.get("deploy_stage")),
        strategy_grade=_safe_str(snapshot.get("strategy_grade")),
        effective_strategy_skill_ids=list(snapshot.get("effective_strategy_skill_ids") or []),
        effective_bot_skill_ids=list(snapshot.get("effective_bot_skill_ids") or []),
        active_os_guard_skill_ids=list(snapshot.get("active_os_guard_skill_ids") or []),
        learning_only_skill_ids=list(snapshot.get("learning_only_skill_ids") or []),
        blocked_skill_ids=list(snapshot.get("blocked_skill_ids") or []),
        blocked_reason=_safe_dict(snapshot.get("blocked_reason")),
        backend_ver=_safe_str(bridge.get("backend_ver")),
        verification_status=_safe_str(bridge.get("verification_status")),
        change_digest=_safe_str(bridge.get("change_digest")),
        delta_summary=_safe_str(bridge.get("delta_summary")),
        why_now=_safe_str(bridge.get("why_now")),
        why_not_now=_safe_str(bridge.get("why_not_now")),
        route_reason=_safe_str(bridge.get("route_reason")),
        next_best_action=_safe_str(bridge.get("next_best_action")),
        recovery_path=_safe_str(bridge.get("recovery_path")),
        replay_anchor=_safe_dict(bridge.get("replay_anchor")),
    )


@router.get("/state/paper/position", response_model=PaperPositionResponse)
@router.get("/api/v1/state/paper/position", response_model=PaperPositionResponse, include_in_schema=False)
def get_paper_position(
    symbol: str = Query(..., min_length=1),
    strategy: str = Query(..., min_length=1),
) -> PaperPositionResponse:
    symbol_norm = _norm_symbol(symbol)
    strategy_norm = _norm_strategy(strategy)

    paper = _read_json(PAPER_STATE_PATH)
    journal = _read_json(JOURNAL_EVENT_PATH)
    snapshot = _build_snapshot(paper, journal, symbol=symbol_norm, strategy=strategy_norm)
    bridge = _build_bridge(snapshot, paper, journal)

    selected = _safe_dict(snapshot.get("paper_state_selected"))
    selected = _normalize_selected(selected, symbol=symbol_norm, strategy=strategy_norm)

    found = any(
        [
            bool(selected.get("position_side")),
            _safe_float(selected.get("position_qty")) > 0.0,
            _safe_float(selected.get("avg_entry")) > 0.0,
            _safe_str(selected.get("last_signal_id")) != "",
        ]
    )

    return PaperPositionResponse(
        found=found,
        symbol=symbol_norm,
        strategy=strategy_norm,
        key=_make_key(symbol_norm, strategy_norm),
        position_side=_safe_str(selected.get("position_side")),
        position_qty=_safe_float(selected.get("position_qty")),
        avg_entry=_safe_float(selected.get("avg_entry")),
        add_count=_safe_int(selected.get("add_count")),
        last_add_price=_safe_float(selected.get("last_add_price")),
        realized_pnl=_safe_float(selected.get("realized_pnl")),
        unrealized_pnl=_safe_float(selected.get("unrealized_pnl")),
        last_signal_id=_safe_str(selected.get("last_signal_id") or snapshot.get("signal_id")),
        last_action=_safe_str(selected.get("last_action") or snapshot.get("decision_action")),
        updated_at=_safe_str(selected.get("updated_at") or snapshot.get("updated_at")) or None,
        source=_safe_str(snapshot.get("source"), "paper_state_latest"),
        source_ts=snapshot.get("source_ts"),
        _source=_safe_str(snapshot.get("_source"), _safe_str(snapshot.get("source"), "paper_state_latest")),
        _source_ts=snapshot.get("_source_ts"),
        stale=bool(snapshot.get("stale", False)),
        stale_ms=_safe_int(snapshot.get("stale_ms")),
        reconcile_status=_safe_str(snapshot.get("reconcile_status"), "ok"),
        decision_id=_safe_str(snapshot.get("decision_id")) or None,
        raw=selected,
        backend_ver=_safe_str(bridge.get("backend_ver")),
        verification_status=_safe_str(bridge.get("verification_status")),
        change_digest=_safe_str(bridge.get("change_digest")),
        delta_summary=_safe_str(bridge.get("delta_summary")),
        why_now=_safe_str(bridge.get("why_now")),
        why_not_now=_safe_str(bridge.get("why_not_now")),
        route_reason=_safe_str(bridge.get("route_reason")),
        next_best_action=_safe_str(bridge.get("next_best_action")),
        recovery_path=_safe_str(bridge.get("recovery_path")),
        replay_anchor=_safe_dict(bridge.get("replay_anchor")),
    )


NULL_ERROR_CONTRACT_MARKER = NULL_ERROR_CONTRACT_VERSION
