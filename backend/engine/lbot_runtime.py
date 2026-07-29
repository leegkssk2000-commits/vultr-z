from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path("/home/z/z/backend")
DATA_DIR = BASE_DIR / "data"
JOURNAL_DIR = DATA_DIR / "journal"

LATEST_FILE = JOURNAL_DIR / "lbot_event.latest.json"
TIMELINE_DB_PATH = DATA_DIR / "timeline.sqlite"

try:
    from backend.engine.paper_ledger import (
        get_paper_state,
        process_signal_to_paper_state,
    )
except Exception:
    get_paper_state = None
    process_signal_to_paper_state = None


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _safe_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        return str(v)
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
        return int(v)
    except Exception:
        return default


def _is_nonempty(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (dict, list, tuple, set)):
        return bool(v)
    return True


def _first_nonempty(*values: Any) -> str:
    for v in values:
        s = _safe_str(v).strip()
        if s:
            return s
    return ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _utc_now_ts() -> int:
    return int(_utc_now().timestamp())


def _yyyymmdd_from_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d")


def _write_json(path: Path, payload: Any) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write("\n")


def _timeline_conn() -> sqlite3.Connection:
    _ensure_dir(TIMELINE_DB_PATH.parent)
    conn = sqlite3.connect(str(TIMELINE_DB_PATH))
    return conn


def _ensure_timeline_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;

        CREATE TABLE IF NOT EXISTS timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            meta TEXT
        );
        """
    )
    conn.commit()


def append_timeline_event(
    *,
    ts: str,
    level: str,
    category: str,
    message: str,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    conn = _timeline_conn()
    try:
        _ensure_timeline_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO timeline_events (
                ts,
                level,
                category,
                message,
                meta
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                ts,
                level,
                category,
                message,
                json.dumps(meta or {}, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.commit()
        return {
            "ok": True,
            "id": int(cur.lastrowid),
            "ts": ts,
            "level": level,
            "category": category,
            "message": message,
            "meta": meta or {},
            "db_path": str(TIMELINE_DB_PATH),
        }
    finally:
        conn.close()


def _extract_action(executor_result: Any, signal: Dict[str, Any]) -> str:
    payload = _safe_dict(signal.get("payload"))
    forced = _safe_str(payload.get("force_action")).strip().lower()
    if forced:
        return forced

    if isinstance(executor_result, dict):
        for key in ("action", "decision_action", "last_action"):
            v = _safe_str(executor_result.get(key)).strip().lower()
            if v:
                return v

    for key in ("action", "decision_action"):
        v = _safe_str(signal.get(key)).strip().lower()
        if v:
            return v

    side = _safe_str(signal.get("side")).strip().lower()
    if side in {"buy", "long", "enter"}:
        return "enter"
    if side in {"sell", "short", "exit"}:
        return "exit"

    sid = _safe_str(signal.get("signal_id")).strip().lower()
    if "_enter_" in sid:
        return "enter"
    if "_add_" in sid:
        return "add"
    if "_reduce_" in sid:
        return "reduce"
    if "_exit_" in sid:
        return "exit"

    return "hold"


def _normalize_executor_result(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return dict(v)

    text = _safe_str(v).strip().lower()
    if not text:
        return {}

    return {
        "status": "",
        "executor_result": text,
        "action": text,
        "reason": text,
    }


def _normalize_signal(signal: Dict[str, Any]) -> Dict[str, Any]:
    signal = _safe_dict(signal)
    return {
        "signal_id": _safe_str(signal.get("signal_id")).strip(),
        "symbol": _safe_str(signal.get("symbol")).strip(),
        "strategy": _safe_str(signal.get("strategy") or signal.get("strategy_id")).strip(),
        "side": _safe_str(signal.get("side")).strip().lower(),
        "price": _safe_float(signal.get("price")),
        "ts": _safe_int(signal.get("ts"), _utc_now_ts()),
        "payload": _safe_dict(signal.get("payload")),
    }


def _normalize_paper_state(state: Any, signal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    src = _safe_dict(state)
    sig = _safe_dict(signal)

    return {
        "symbol": _safe_str(src.get("symbol") or sig.get("symbol")).strip(),
        "strategy": _safe_str(src.get("strategy") or sig.get("strategy")).strip(),
        "position_side": _safe_str(src.get("position_side")).strip(),
        "position_qty": _safe_float(src.get("position_qty")),
        "avg_entry": _safe_float(src.get("avg_entry")),
        "add_count": _safe_int(src.get("add_count")),
        "last_add_price": _safe_float(src.get("last_add_price")),
        "realized_pnl": _safe_float(src.get("realized_pnl")),
        "last_signal_id": _safe_str(src.get("last_signal_id")).strip(),
        "last_action": _safe_str(src.get("last_action")).strip().lower(),
        "updated_at": _safe_str(src.get("updated_at") or _utc_now_iso()).strip(),
    }


def _call_paper_ledger(
    *,
    mode: str,
    route: str,
    signal: Dict[str, Any],
    flags: Dict[str, Any],
    strategy_decision: Dict[str, Any],
    risk: Dict[str, Any],
    executor: Dict[str, Any],
    debug_trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not callable(process_signal_to_paper_state):
        return {}

    req = {
        "mode": _safe_str(mode).strip().lower(),
        "route": _safe_str(route).strip().lower(),
        "signal": _safe_dict(signal),
        "flags": _safe_dict(flags),
        "strategy_decision": _safe_dict(strategy_decision),
        "risk": _safe_dict(risk),
        "executor": _safe_dict(executor),
        "debug_trace": _safe_list(debug_trace),
    }

    attempts = [
        ((req,), {}),
        ((_safe_dict(signal),), {}),
        ((), {"req_or_signal": req}),
        ((), {"request": req}),
        ((), {"signal": _safe_dict(signal)}),
    ]

    for args, kwargs in attempts:
        try:
            out = process_signal_to_paper_state(*args, **kwargs)
            return _safe_dict(out)
        except TypeError:
            continue
        except Exception:
            return {}

    return {}


def _read_current_paper_state(signal: Dict[str, Any]) -> Dict[str, Any]:
    if not callable(get_paper_state):
        return {}

    symbol = _safe_str(signal.get("symbol")).strip()
    strategy = _safe_str(signal.get("strategy")).strip()

    attempts = [
        ((), {"symbol": symbol, "strategy": strategy}),
        ((symbol, strategy), {}),
        ((symbol,), {}),
        ((), {}),
    ]

    for args, kwargs in attempts:
        try:
            out = get_paper_state(*args, **kwargs)
            out = _safe_dict(out)

            selected = _safe_dict(out.get("paper_state_selected"))
            if selected:
                return _normalize_paper_state(selected, signal)

            positions = _safe_dict(out.get("positions"))
            key = f"{symbol}::{strategy}"
            if isinstance(positions.get(key), dict):
                return _normalize_paper_state(positions[key], signal)

            if out:
                return _normalize_paper_state(out, signal)
        except Exception:
            continue

    return {}


def _build_effective_state_snapshot(
    *,
    signal: Dict[str, Any],
    state: Dict[str, Any],
    paper_state: Dict[str, Any],
) -> Dict[str, Any]:
    base = _safe_dict(state)
    ps = _normalize_paper_state(paper_state, signal)

    base["position_side"] = ps["position_side"]
    base["position_qty"] = ps["position_qty"]
    base["avg_entry"] = ps["avg_entry"]
    base["add_count"] = ps["add_count"]
    base["last_add_price"] = ps["last_add_price"]
    base["realized_pnl"] = ps["realized_pnl"]
    base["last_signal_id"] = ps["last_signal_id"] or _safe_str(signal.get("signal_id")).strip()
    base["last_action"] = ps["last_action"] or _extract_action({}, signal)
    base["paper_state_selected"] = {
        "symbol": _safe_str(signal.get("symbol")).strip(),
        "strategy": _safe_str(signal.get("strategy")).strip(),
        "position_side": ps["position_side"],
        "position_qty": ps["position_qty"],
        "avg_entry": ps["avg_entry"],
        "add_count": ps["add_count"],
        "last_add_price": ps["last_add_price"],
        "realized_pnl": ps["realized_pnl"],
        "last_signal_id": ps["last_signal_id"] or _safe_str(signal.get("signal_id")).strip(),
        "last_action": ps["last_action"] or _extract_action({}, signal),
        "updated_at": ps["updated_at"],
    }
    return base


def _extract_executor_status(executor_result: Dict[str, Any], route: str) -> str:
    return _first_nonempty(
        executor_result.get("status"),
        executor_result.get("executor_status"),
        route,
    ).strip().lower()


def _extract_executor_reason(executor_result: Dict[str, Any]) -> str:
    guard = _safe_dict(executor_result.get("guard"))
    details = _safe_dict(guard.get("details"))

    return _first_nonempty(
        executor_result.get("executor_result"),
        executor_result.get("reason"),
        executor_result.get("code"),
        executor_result.get("result"),
        executor_result.get("error"),
        guard.get("reason"),
        guard.get("code"),
        details.get("reason"),
        details.get("code"),
    ).strip().lower()


def _extract_decision_reason(
    strategy_decision: Dict[str, Any],
    risk: Dict[str, Any],
    executor_result: Dict[str, Any],
    action: str,
) -> str:
    return _first_nonempty(
        strategy_decision.get("reason"),
        strategy_decision.get("decision_reason"),
        risk.get("reason"),
        risk.get("risk_reason"),
        executor_result.get("reason"),
        executor_result.get("code"),
        _safe_dict(executor_result.get("guard")).get("reason"),
        _safe_dict(executor_result.get("guard")).get("code"),
        f"forced_{action}" if action else "",
    ).strip().lower()


def _merge_external_journal_event(base: Dict[str, Any], ext: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    ext = _safe_dict(ext)

    for key, value in ext.items():
        if _is_nonempty(value):
            merged[key] = value

    for must_keep in (
        "signal_id",
        "strategy",
        "symbol",
        "decision_action",
        "decision_reason",
        "risk_action",
        "executor_status",
        "executor_result",
        "effective_mode",
        "effective_route",
        "ts",
    ):
        if not _is_nonempty(merged.get(must_keep)):
            merged[must_keep] = base.get(must_keep)

    return merged


def _write_journal_event(
    *,
    signal: Dict[str, Any],
    mode: str,
    route: str,
    strategy_decision: Dict[str, Any],
    risk: Dict[str, Any],
    executor_result: Dict[str, Any],
    state: Dict[str, Any],
    flags: Dict[str, Any],
    debug_trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
    signal_id = _safe_str(signal.get("signal_id")).strip()
    symbol = _safe_str(signal.get("symbol")).strip()
    strategy = _safe_str(
        signal.get("strategy")
        or signal.get("strategy_id")
        or strategy_decision.get("strategy")
    ).strip()

    decision_action = _safe_str(
        strategy_decision.get("action")
        or strategy_decision.get("decision_action")
        or _extract_action(executor_result, signal)
    ).strip().lower()

    decision_reason = _extract_decision_reason(
        _safe_dict(strategy_decision),
        _safe_dict(risk),
        _safe_dict(executor_result),
        decision_action,
    )

    risk_action = _safe_str(
        risk.get("action")
        or risk.get("risk_action")
    ).strip().lower()

    executor_status = _extract_executor_status(_safe_dict(executor_result), route)
    executor_result_text = _extract_executor_reason(_safe_dict(executor_result))

    if not executor_result_text:
        if executor_status in {"blocked", "reject", "rejected"} and decision_reason:
            executor_result_text = decision_reason
        else:
            executor_result_text = _first_nonempty(
                executor_status if executor_status not in {"", "ok"} else "",
                f"{_safe_str(route).strip().lower()}_{decision_action}" if decision_action else "",
                "unknown",
            ).strip().lower()

    event_ts = _safe_int(
        signal.get("ts")
        or signal.get("timestamp")
        or _utc_now_ts()
    )

    journal_event = {
        "status": "ready",
        "event_type": "lbot_runtime",
        "signal_id": signal_id,
        "strategy": strategy,
        "symbol": symbol,
        "decision_action": decision_action,
        "decision_reason": decision_reason,
        "risk_action": risk_action,
        "executor_status": executor_status,
        "executor_result": executor_result_text,
        "effective_mode": _safe_str(mode).strip().lower(),
        "effective_route": _safe_str(route).strip().lower(),
        "ts": event_ts,
    }

    return {
        "signal_id": signal_id,
        "journal_event": journal_event,
        "state_snapshot": _safe_dict(state),
        "strategy_decision": _safe_dict(strategy_decision),
        "risk": _safe_dict(risk),
        "executor": _safe_dict(executor_result),
        "flags": _safe_dict(flags),
        "debug_trace": _safe_list(debug_trace),
        "updated_at": _utc_now_iso(),
    }


def _build_timeline_message(event: Dict[str, Any]) -> str:
    journal_event = _safe_dict(event.get("journal_event"))
    symbol = _safe_str(journal_event.get("symbol")).strip()
    strategy = _safe_str(journal_event.get("strategy")).strip()
    action = _safe_str(journal_event.get("decision_action")).strip().lower()
    decision_reason = _safe_str(journal_event.get("decision_reason")).strip().lower()
    executor_result = _safe_str(journal_event.get("executor_result")).strip().lower()
    signal_id = _safe_str(journal_event.get("signal_id")).strip()

    display_result = executor_result
    if not display_result or display_result == "unknown":
        display_result = decision_reason or "unknown"

    left = "/".join(x for x in [symbol, strategy] if x)
    right = " | ".join(x for x in [action, display_result, signal_id] if x)

    if left and right:
        return f"{left} | {right}"
    if left:
        return left
    if right:
        return right
    return "lbot runtime event"


def _build_timeline_meta(event: Dict[str, Any]) -> Dict[str, Any]:
    journal_event = _safe_dict(event.get("journal_event"))
    state_snapshot = _safe_dict(event.get("state_snapshot"))
    executor = _safe_dict(event.get("executor"))
    guard = _safe_dict(executor.get("guard"))

    return {
        "signal_id": _safe_str(journal_event.get("signal_id")).strip(),
        "symbol": _safe_str(journal_event.get("symbol")).strip(),
        "strategy": _safe_str(journal_event.get("strategy")).strip(),
        "decision_action": _safe_str(journal_event.get("decision_action")).strip(),
        "decision_reason": _safe_str(journal_event.get("decision_reason")).strip(),
        "risk_action": _safe_str(journal_event.get("risk_action")).strip(),
        "executor_status": _safe_str(journal_event.get("executor_status")).strip(),
        "executor_result": _safe_str(journal_event.get("executor_result")).strip(),
        "effective_mode": _safe_str(journal_event.get("effective_mode")).strip(),
        "effective_route": _safe_str(journal_event.get("effective_route")).strip(),
        "guard_reason": _safe_str(guard.get("reason")).strip(),
        "guard_code": _safe_str(guard.get("code")).strip(),
        "state_snapshot": state_snapshot,
        "executor": executor,
    }


def _build_persist_event(
    mode: str,
    route: str,
    signal: Dict[str, Any],
    state: Dict[str, Any],
    flags: Dict[str, Any],
    strategy_decision: Dict[str, Any],
    risk: Dict[str, Any],
    executor: Dict[str, Any],
    journal_event: Dict[str, Any] | None = None,
    debug_trace: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    executor = _normalize_executor_result(executor)
    event = _write_journal_event(
        signal=_safe_dict(signal),
        mode=_safe_str(mode),
        route=_safe_str(route),
        strategy_decision=_safe_dict(strategy_decision),
        risk=_safe_dict(risk),
        executor_result=executor,
        state=_safe_dict(state),
        flags=_safe_dict(flags),
        debug_trace=_safe_list(debug_trace),
    )

    if isinstance(journal_event, dict) and journal_event:
        event["journal_event"] = _merge_external_journal_event(
            _safe_dict(event.get("journal_event")),
            _safe_dict(journal_event),
        )

    return event


def _persist_event(event: Dict[str, Any]) -> Dict[str, Any]:
    event = _safe_dict(event)

    journal_event = _safe_dict(event.get("journal_event"))
    ts_val = _safe_int(journal_event.get("ts"), _utc_now_ts())
    day = _yyyymmdd_from_ts(ts_val)

    _ensure_dir(JOURNAL_DIR)

    daily_path = JOURNAL_DIR / f"lbot_event.{day}.jsonl"
    latest_path = LATEST_FILE

    _append_jsonl(daily_path, event)
    _write_json(latest_path, event)

    timeline_result = append_timeline_event(
        ts=_utc_now_iso(),
        level="info",
        category="lbot",
        message=_build_timeline_message(event),
        meta=_build_timeline_meta(event),
    )

    return {
        "ok": True,
        "daily_path": str(daily_path),
        "latest_path": str(latest_path),
        "timeline": timeline_result,
        "signal_id": _safe_str(journal_event.get("signal_id")).strip(),
    }


def process_signal(
    *,
    mode: str,
    route: str,
    signal: Dict[str, Any],
    state: Dict[str, Any],
    flags: Dict[str, Any],
    strategy_decision: Dict[str, Any],
    risk: Dict[str, Any],
    executor: Dict[str, Any],
    journal_event: Dict[str, Any] | None = None,
    debug_trace: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    signal = _normalize_signal(signal)
    flags = _safe_dict(flags)
    strategy_decision = _safe_dict(strategy_decision)
    risk = _safe_dict(risk)
    executor = _normalize_executor_result(executor)
    debug_trace = _safe_list(debug_trace)

    _call_paper_ledger(
        mode=mode,
        route=route,
        signal=signal,
        flags=flags,
        strategy_decision=strategy_decision,
        risk=risk,
        executor=executor,
        debug_trace=debug_trace,
    )

    latest_paper_state = _read_current_paper_state(signal)
    effective_state = _build_effective_state_snapshot(
        signal=signal,
        state=_safe_dict(state),
        paper_state=latest_paper_state,
    )

    event = _build_persist_event(
        mode=mode,
        route=route,
        signal=signal,
        state=effective_state,
        flags=flags,
        strategy_decision=strategy_decision,
        risk=risk,
        executor=executor,
        journal_event=journal_event,
        debug_trace=debug_trace,
    )
    persisted = _persist_event(event)

    return {
        "ok": True,
        "event": event,
        "persist": persisted,
        "paper_state_selected": _safe_dict(effective_state.get("paper_state_selected")),
    }


def persist_runtime_event(
    *,
    mode: str,
    route: str,
    signal: Dict[str, Any],
    state: Dict[str, Any],
    flags: Dict[str, Any],
    strategy_decision: Dict[str, Any],
    risk: Dict[str, Any],
    executor: Dict[str, Any],
    journal_event: Dict[str, Any] | None = None,
    debug_trace: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return process_signal(
        mode=mode,
        route=route,
        signal=signal,
        state=state,
        flags=flags,
        strategy_decision=strategy_decision,
        risk=risk,
        executor=executor,
        journal_event=journal_event,
        debug_trace=debug_trace,
    )


def lbot_process(
    *,
    mode: str,
    route: str,
    signal: Dict[str, Any],
    state: Dict[str, Any],
    flags: Dict[str, Any],
    strategy_decision: Dict[str, Any],
    risk: Dict[str, Any],
    executor: Dict[str, Any],
    journal_event: Dict[str, Any] | None = None,
    debug_trace: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return process_signal(
        mode=mode,
        route=route,
        signal=signal,
        state=state,
        flags=flags,
        strategy_decision=strategy_decision,
        risk=risk,
        executor=executor,
        journal_event=journal_event,
        debug_trace=debug_trace,
    )