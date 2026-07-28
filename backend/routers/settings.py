from __future__ import annotations

import importlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.contracts.null_error_contract import (
    NULL_ERROR_CONTRACT_VERSION,
    normalize_error_contract,
    normalize_text,
)

from backend.state.alerts_contract import (
    alerts_defaults,
    alert_preview_payload,
    ensure_settings_contract,
)

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS_FILE = DATA_DIR / "settings" / "lbot_settings.json"
SETTINGS_FILE = Path(os.getenv("Z_SETTINGS_FILE", str(DEFAULT_SETTINGS_FILE)))
SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)

PAPER_DIR = DATA_DIR / "paper"
JOURNAL_DIR = DATA_DIR / "journal"
PAPER_DIR.mkdir(parents=True, exist_ok=True)
JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

PAPER_STATE_LATEST = PAPER_DIR / "paper_state.latest.json"
JOURNAL_LATEST = JOURNAL_DIR / "lbot_event.latest.json"

router = APIRouter(tags=["settings"])

CONTRACT_RUNTIME_MODES = ("noop", "dummy", "paper", "shadow", "live")
CONTRACT_RUNTIME_ROUTES = ("noop", "paper", "live")
CONTRACT_EVENT_STATUSES = ("ready", "blocked", "hold", "done", "noop")
CONTRACT_EXECUTOR_STATUSES = ("ready", "blocked", "hold", "noop", "paper", "live")

SENSITIVE_EXACT_KEYS = {
    "api_key",
    "api_secret",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "passphrase",
    "private_key",
    "client_secret",
    "webhook_secret",
    "signature_secret",
    "bot_token",
}
SENSITIVE_PARTIAL_KEYS = (
    "secret",
    "token",
    "apikey",
    "api_key",
    "passphrase",
    "private_key",
    "client_secret",
    "webhook_secret",
)


def _norm_runtime_mode(v: Any, default: str = "paper") -> str:
    s = _safe_str(v, default).lower()
    return s if s in CONTRACT_RUNTIME_MODES else default


def _norm_runtime_route(v: Any, default: str = "paper") -> str:
    s = _safe_str(v, default).lower()
    return s if s in CONTRACT_RUNTIME_ROUTES else default


def _norm_event_status(v: Any, default: str = "ready") -> str:
    s = _safe_str(v, default).lower()
    if s == "applied":
        s = "done"
    if s == "idle":
        s = "noop"
    return s if s in CONTRACT_EVENT_STATUSES else default


def _norm_executor_status(v: Any, default: str = "ready") -> str:
    s = _safe_str(v, default).lower()
    if s == "applied":
        s = "paper"
    if s == "idle":
        s = "noop"
    return s if s in CONTRACT_EXECUTOR_STATUSES else default


def _settings_signal_id(changed_key: str, now_ts: int) -> str:
    return f"settings:{changed_key}:{now_ts}"


def _settings_event_identity(changed_key: str, now_ts: int) -> Dict[str, str]:
    signal_id = _settings_signal_id(changed_key, now_ts)
    return {
        "event_id": signal_id,
        "decision_id": signal_id,
        "signal_id": signal_id,
    }


class SettingPatchRequest(BaseModel):
    value: Any = Field(..., description="Value to set")


class SettingReplaceRequest(BaseModel):
    items: Dict[str, Any] = Field(default_factory=dict)


class AlertPreviewRequest(BaseModel):
    event_type: str = "risk"
    severity: str = "warning"
    decision_id: str = "preview_decision_id"
    symbol: str = "BTCUSDT"
    team: str = "ALPHA"
    action: str = "hold"
    reason: str = "preview"


def _ensure_file() -> None:
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text("{}", encoding="utf-8")


def _backup_file() -> None:
    if SETTINGS_FILE.exists():
        ts = int(time.time())
        backup_path = SETTINGS_FILE.with_name(f"{SETTINGS_FILE.name}.bak.{ts}")
        shutil.copy2(SETTINGS_FILE, backup_path)


def _now_ts() -> int:
    return int(time.time())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_yyyymmdd() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
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


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _load_all() -> Dict[str, Any]:
    _ensure_file()
    try:
        raw = SETTINGS_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return ensure_settings_contract({})
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail="settings file is not a JSON object")
        return ensure_settings_contract(data)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"invalid settings json: {e.msg}")


def _save_all(data: Dict[str, Any]) -> None:
    data = ensure_settings_contract(data)
    tmp_path = SETTINGS_FILE.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(SETTINGS_FILE)


def _validate_key(key: str) -> str:
    key = key.strip().strip(".")
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    if ".." in key:
        raise HTTPException(status_code=400, detail="invalid key")
    return key


def _get_nested(data: Dict[str, Any], key: str) -> Any:
    cur: Any = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise HTTPException(status_code=404, detail=f"setting not found: {key}")
        cur = cur[part]
    return cur


def _set_nested(data: Dict[str, Any], key: str, value: Any) -> Dict[str, Any]:
    cur = data
    parts = key.split(".")
    for part in parts[:-1]:
        next_val = cur.get(part)
        if next_val is None:
            cur[part] = {}
            next_val = cur[part]
        if not isinstance(next_val, dict):
            raise HTTPException(
                status_code=409,
                detail=f"cannot create nested key under non-object path: {part}",
            )
        cur = next_val
    cur[parts[-1]] = value
    return data


def _delete_nested(data: Dict[str, Any], key: str) -> Dict[str, Any]:
    cur = data
    parts = key.split(".")
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            raise HTTPException(status_code=404, detail=f"setting not found: {key}")
        cur = cur[part]

    leaf = parts[-1]
    if leaf not in cur:
        raise HTTPException(status_code=404, detail=f"setting not found: {key}")

    del cur[leaf]

    parent_stack = []
    cur2 = data
    for part in parts[:-1]:
        parent_stack.append((cur2, part))
        cur2 = cur2[part]

    for parent, part in reversed(parent_stack):
        if isinstance(parent.get(part), dict) and not parent[part]:
            del parent[part]
        else:
            break

    return data


def _build_meta() -> Dict[str, Any]:
    return {
        "file": str(SETTINGS_FILE),
        "updated_at": int(time.time()),
    }


def _coerce_replace_payload(payload: Any) -> Dict[str, Any]:
    if payload is None:
        return {}

    if isinstance(payload, SettingReplaceRequest):
        payload = payload.items

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="settings payload must be object")

    if "items" in payload and isinstance(payload.get("items"), dict) and len(payload) == 1:
        payload = payload["items"]

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="items must be object")

    return payload


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


def _runtime_control_key(key: str) -> bool:
    k = _validate_key(key)
    return k in {"mode", "route", "kill_switch", "exchange_enabled"}


def _live_trading_enabled(settings: Dict[str, Any]) -> bool:
    env_enabled = os.getenv("Z_LIVE_TRADING_ENABLED", "0").strip() == "1"
    settings_enabled = _safe_bool(settings.get("exchange_enabled"), False)
    return env_enabled and settings_enabled


def _is_sensitive_key(key: Any) -> bool:
    if key is None:
        return False
    k = _safe_str(key).lower()
    if not k:
        return False
    if k in SENSITIVE_EXACT_KEYS:
        return True
    return any(token in k for token in SENSITIVE_PARTIAL_KEYS)


def _mask_secret_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "****"
    s = _safe_str(value, "")
    if not s:
        return ""
    return "****"


def _public_settings_view(obj: Any, parent_key: str = "") -> Any:
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if _is_sensitive_key(k):
                out[k] = _mask_secret_value(v)
            else:
                out[k] = _public_settings_view(v, parent_key=f"{parent_key}.{k}" if parent_key else str(k))
        return out
    if isinstance(obj, list):
        return [_public_settings_view(v, parent_key=parent_key) for v in obj]
    return obj


def _resolve_effective_mode_route(settings: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    mode = _norm_runtime_mode(settings.get("mode"), "paper")
    route = _norm_runtime_route(settings.get("route"), "paper")

    if _safe_bool(settings.get("kill_switch"), False):
        return mode, route, "kill_switch_triggered"

    if mode == "noop" or route == "noop":
        return mode or "noop", "noop", None

    if mode == "shadow":
        return mode, route, None

    if mode in {"dummy", "paper"} and route == "live":
        return mode, route, "live_route_blocked_for_non_live_mode"

    if mode == "live":
        if route != "live":
            return mode, route, "live_mode_requires_live_route"
        if not _live_trading_enabled(settings):
            return mode, route, "live_trading_disabled"
        return mode, route, None

    return mode, route, None


def _base_selected_position(current: Dict[str, Any]) -> Dict[str, Any]:
    selected = current.get("paper_state_selected")
    if isinstance(selected, dict):
        return dict(selected)
    positions = current.get("positions")
    if isinstance(positions, dict) and positions:
        first_key = next(iter(positions))
        first_val = positions.get(first_key)
        if isinstance(first_val, dict):
            return dict(first_val)
    return {}


def _sync_paper_state(settings: Dict[str, Any], changed_key: str, changed_value: Any) -> Dict[str, Any]:
    current = _read_json(PAPER_STATE_LATEST)
    now_ts = _now_ts()
    now_iso = _now_iso()
    mode = _safe_str(settings.get("mode"), _safe_str(current.get("mode"), "paper")).lower()
    route = _safe_str(settings.get("route"), _safe_str(current.get("route"), "paper")).lower()
    effective_mode, effective_route, reason = _resolve_effective_mode_route(settings)

    selected = _base_selected_position(current)
    ids = _settings_event_identity(changed_key, now_ts)
    current.update(
        {
            "ok": True,
            "detail": "kill_switch_triggered" if changed_key == "kill_switch" else f"{changed_key}_updated",
            "reason": reason or ("kill_switch_triggered" if changed_key == "kill_switch" else f"{changed_key}_updated"),
            "status": _norm_event_status("ready"),
            "mode": _norm_runtime_mode(mode, "paper"),
            "route": _norm_runtime_route(route, "paper"),
            "effective_mode": _norm_runtime_mode(effective_mode or mode, "paper"),
            "effective_route": _norm_runtime_route(effective_route or route, "paper"),
            "event_type": "settings_update",
            "event_id": ids["event_id"],
            "decision_id": ids["decision_id"],
            "signal_id": ids["signal_id"],
            "executor_status": _norm_executor_status("ready"),
            "executor_result": "kill_switch_triggered" if changed_key == "kill_switch" else f"{changed_key}_updated",
            "ts": now_ts,
            "written_at": now_iso,
            "updated_at": now_iso,
            "position_side": _safe_str(current.get("position_side"), _safe_str(selected.get("position_side"), "")),
            "position_qty": _safe_float(current.get("position_qty"), _safe_float(selected.get("position_qty"), 0.0)),
            "avg_entry": _safe_float(current.get("avg_entry"), _safe_float(selected.get("avg_entry"), 0.0)),
            "add_count": _safe_int(current.get("add_count"), _safe_int(selected.get("add_count"), 0)),
            "last_add_price": _safe_float(current.get("last_add_price"), _safe_float(selected.get("last_add_price"), 0.0)),
            "realized_pnl": _safe_float(current.get("realized_pnl"), _safe_float(selected.get("realized_pnl"), 0.0)),
            "unrealized_pnl": _safe_float(current.get("unrealized_pnl"), _safe_float(selected.get("unrealized_pnl"), 0.0)),
            "last_signal_id": _safe_str(current.get("last_signal_id"), _safe_str(selected.get("last_signal_id"), "")),
            "last_action": _safe_str(current.get("last_action"), _safe_str(selected.get("last_action"), "hold")),
            "last_symbol": _safe_str(current.get("last_symbol"), _safe_str(selected.get("symbol"), "")),
            "last_strategy": _safe_str(current.get("last_strategy"), _safe_str(selected.get("strategy"), "")),
            "_last_event_meta": {
                "mode": mode,
                "route": route,
                "effective_mode": effective_mode,
                "effective_route": effective_route,
                "event_id": ids["event_id"],
                "decision_id": ids["decision_id"],
                "signal_id": ids["signal_id"],
                "symbol": _safe_str(_first_non_empty(current.get("symbol"), selected.get("symbol")), ""),
                "strategy": _safe_str(_first_non_empty(current.get("strategy"), selected.get("strategy")), ""),
                "action": "hold" if changed_key == "kill_switch" else "settings_update",
            },
        }
    )

    if selected:
        selected["updated_at"] = now_iso
        current["paper_state_selected"] = selected

    _atomic_write_json(PAPER_STATE_LATEST, current)
    return current


def _build_settings_journal_event(
    *,
    settings: Dict[str, Any],
    changed_key: str,
    changed_value: Any,
    paper_state: Dict[str, Any],
) -> Dict[str, Any]:
    effective_mode, effective_route, reason = _resolve_effective_mode_route(settings)
    now_ts = _now_ts()

    ids = _settings_event_identity(changed_key, now_ts)

    if changed_key == "kill_switch":
        message_result = "kill_switch_triggered"
        decision_reason = "kill_switch_triggered"
        status = _norm_event_status("blocked")
    else:
        message_result = f"{changed_key}_updated"
        decision_reason = reason or f"{changed_key}_updated"
        status = _norm_event_status("ready")

    symbol = _safe_str(
        _first_non_empty(
            paper_state.get("symbol"),
            isinstance(paper_state.get("paper_state_selected"), dict)
            and paper_state["paper_state_selected"].get("symbol"),
        ),
        "",
    )
    strategy = _safe_str(
        _first_non_empty(
            paper_state.get("strategy"),
            isinstance(paper_state.get("paper_state_selected"), dict)
            and paper_state["paper_state_selected"].get("strategy"),
        ),
        "",
    )

    return {
        "status": status,
        "event_type": "settings_update",
        "event_id": ids["event_id"],
        "decision_id": ids["decision_id"],
        "signal_id": ids["signal_id"],
        "strategy": strategy,
        "symbol": symbol,
        "decision_action": "hold",
        "decision_reason": decision_reason,
        "risk_action": "hold",
        "executor_status": _norm_executor_status("blocked" if changed_key == "kill_switch" else "ready"),
        "executor_result": message_result,
        "effective_mode": effective_mode,
        "effective_route": effective_route,
        "ts": now_ts,
        "changed_key": changed_key,
        "changed_value": changed_value,
    }


def _build_settings_event_envelope(
    *,
    settings: Dict[str, Any],
    changed_key: str,
    changed_value: Any,
    paper_state: Dict[str, Any],
) -> Dict[str, Any]:
    journal_event = _build_settings_journal_event(
        settings=settings,
        changed_key=changed_key,
        changed_value=changed_value,
        paper_state=paper_state,
    )
    return {
        "event_id": journal_event.get("event_id"),
        "decision_id": journal_event.get("decision_id"),
        "signal_id": journal_event["signal_id"],
        "journal_event": journal_event,
        "state_snapshot": paper_state,
        "strategy_decision": {
            "action": journal_event["decision_action"],
            "decision_reason": journal_event["decision_reason"],
        },
        "risk": {
            "risk_action": journal_event["risk_action"],
        },
        "executor": {
            "status": journal_event["executor_status"],
            "executor_result": journal_event["executor_result"],
            "action": journal_event["decision_action"],
        },
        "flags": {
            "source": "settings_patch",
            "changed_key": changed_key,
            "changed_value": changed_value,
            "mode": _norm_runtime_mode(settings.get("mode"), "paper"),
            "route": _norm_runtime_route(settings.get("route"), "paper"),
            "exchange_enabled": _safe_bool(settings.get("exchange_enabled"), False),
            "kill_switch": _safe_bool(settings.get("kill_switch"), False),
        },
        "debug_trace": [],
        "updated_at": _now_iso(),
    }


def _timeline_message(changed_key: str, changed_value: Any) -> str:
    if changed_key == "kill_switch":
        return "kill-switch triggered"
    return f"{changed_key} updated -> {changed_value}"


def _append_timeline_from_settings(event: Dict[str, Any], changed_key: str, changed_value: Any) -> Dict[str, Any]:
    journal_event = event["journal_event"]
    try:
        from backend.engine.lbot_runtime import append_timeline_event  # type: ignore

        result = append_timeline_event(
            ts=_now_iso(),
            level="warning" if changed_key == "kill_switch" else "info",
            category="lbot",
            message=_timeline_message(changed_key, changed_value),
            meta={
                "ok": True,
                "detail": _timeline_message(changed_key, changed_value),
                "reason": journal_event["decision_reason"],
                "signal_id": journal_event["signal_id"],
                "symbol": journal_event["symbol"],
                "strategy": journal_event["strategy"],
                "decision_action": journal_event["decision_action"],
                "decision_reason": journal_event["decision_reason"],
                "risk_action": journal_event["risk_action"],
                "executor_status": journal_event["executor_status"],
                "executor_result": journal_event["executor_result"],
                "effective_mode": journal_event["effective_mode"],
                "effective_route": journal_event["effective_route"],
                "changed_key": changed_key,
                "changed_value": changed_value,
            },
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _sync_journal_and_timeline(settings: Dict[str, Any], changed_key: str, changed_value: Any, paper_state: Dict[str, Any]) -> Dict[str, Any]:
    event = _build_settings_event_envelope(
        settings=settings,
        changed_key=changed_key,
        changed_value=changed_value,
        paper_state=paper_state,
    )

    _atomic_write_json(JOURNAL_LATEST, event)
    date = _today_yyyymmdd()
    _append_jsonl(JOURNAL_DIR / f"lbot_event.{date}.jsonl", event)
    _append_jsonl(JOURNAL_DIR / f"lbot_events.{date}.jsonl", event)
    _append_jsonl(JOURNAL_DIR / f"lbot_events_{date}.jsonl", event)

    timeline_sync = _append_timeline_from_settings(event, changed_key, changed_value)
    return {
        "event": event,
        "timeline_sync": timeline_sync,
    }


def _sync_runtime_side_effects(data: Dict[str, Any], changed_key: str, changed_value: Any) -> Dict[str, Any]:
    if changed_key == "kill_switch" and _safe_bool(changed_value, False):
        _set_nested(data, "exchange_enabled", False)

    paper_state = _sync_paper_state(data, changed_key=changed_key, changed_value=changed_value)
    journal_and_timeline = _sync_journal_and_timeline(
        data,
        changed_key=changed_key,
        changed_value=changed_value,
        paper_state=paper_state,
    )

    effective_mode, effective_route, reason = _resolve_effective_mode_route(data)
    return {
        "mode": _norm_runtime_mode(data.get("mode"), "paper"),
        "route": _norm_runtime_route(data.get("route"), "paper"),
        "effective_mode": effective_mode,
        "effective_route": effective_route,
        "reason": reason,
        "exchange_enabled": _safe_bool(data.get("exchange_enabled"), False),
        "kill_switch": _safe_bool(data.get("kill_switch"), False),
        "journal_event": journal_and_timeline["event"].get("journal_event"),
        "timeline_sync": journal_and_timeline.get("timeline_sync"),
    }


@router.get("/api/v1/settings")
def get_settings(
    prefix: Optional[str] = Query(default=None, description="prefix filter, e.g. risk or trading.bingx"),
):
    data = _load_all()
    if prefix:
        prefix = _validate_key(prefix)
        try:
            filtered = _get_nested(data, prefix)
        except HTTPException as e:
            if e.status_code == 404:
                filtered = {}
            else:
                raise
        return {
            "ok": True,
            "prefix": prefix,
            "items": _public_settings_view(filtered),
            "meta": _build_meta(),
        }

    return {
        "ok": True,
        "items": _public_settings_view(data),
        "meta": _build_meta(),
    }




@router.get("/api/v1/settings/alerts/contract")
def get_alerts_contract():
    data = _load_all()
    return {
        "ok": True,
        "contract_version": "alerts.settings.v1",
        "defaults": _public_settings_view(alerts_defaults()["alerts"]),
        "current": _public_settings_view(data.get("alerts", {})),
        "meta": _build_meta(),
    }


@router.get("/api/v1/settings/alerts/current")
def get_alerts_current():
    data = _load_all()
    return {
        "ok": True,
        "contract_version": "alerts.settings.v1",
        "current": _public_settings_view(data.get("alerts", {})),
        "meta": _build_meta(),
    }


@router.post("/api/v1/settings/alerts/preview")
def post_alerts_preview(payload: AlertPreviewRequest):
    preview = alert_preview_payload(
        event_type=payload.event_type,
        severity=payload.severity,
        decision_id=payload.decision_id,
        symbol=payload.symbol,
        team=payload.team,
        action=payload.action,
        reason=payload.reason,
    )
    return {
        "ok": True,
        "preview": preview,
        "meta": _build_meta(),
    }


@router.get("/api/v1/settings/{key:path}")
def get_setting(key: str):
    key = _validate_key(key)
    data = _load_all()
    value = _get_nested(data, key)
    return {
        "ok": True,
        "key": key,
        "value": _public_settings_view(value, parent_key=key),
        "meta": _build_meta(),
    }


@router.patch("/api/v1/settings/{key:path}")
def patch_setting(key: str, payload: SettingPatchRequest):
    key = _validate_key(key)
    data = _load_all()
    _backup_file()

    updated = _set_nested(data, key, payload.value)

    _save_all(updated)

    runtime_sync = None
    if _runtime_control_key(key):
        runtime_sync = _sync_runtime_side_effects(updated, changed_key=key, changed_value=payload.value)
        _save_all(updated)

    return {
        "ok": True,
        "key": key,
        "value": _public_settings_view(payload.value, parent_key=key),
        "runtime_sync": _public_settings_view(runtime_sync),
        "meta": _build_meta(),
    }


@router.delete("/api/v1/settings/{key:path}")
def delete_setting(key: str):
    key = _validate_key(key)
    data = _load_all()
    _backup_file()
    updated = _delete_nested(data, key)
    _save_all(updated)
    return {
        "ok": True,
        "deleted": key,
        "meta": _build_meta(),
    }


@router.put("/api/v1/settings", include_in_schema=False)
async def replace_settings(request: Request):
    try:
        raw_payload = await request.json()
    except Exception:
        raw_payload = {}

    items = _coerce_replace_payload(raw_payload)
    _backup_file()
    _save_all(items)

    runtime_sync = None
    if any(k in items for k in ("mode", "route", "kill_switch", "exchange_enabled")):
        runtime_sync = _sync_runtime_side_effects(
            items,
            changed_key="replace_settings",
            changed_value={
                "mode": items.get("mode"),
                "route": items.get("route"),
                "kill_switch": items.get("kill_switch"),
                "exchange_enabled": items.get("exchange_enabled"),
            },
        )
        _save_all(items)

    return {
        "ok": True,
        "replaced": True,
        "items": _public_settings_view(items),
        "runtime_sync": _public_settings_view(runtime_sync),
        "meta": _build_meta(),
    }


class StrategyToggleRequest(BaseModel):
    strategy: str = Field(..., min_length=1)
    enabled: bool = Field(...)


def _resolve_registry_module() -> Any:
    for mod_path in (
        "backend.engine.strategy_registry",
        "backend.engine.strategy_registry_g0_runtime_safe",
    ):
        try:
            return importlib.import_module(mod_path)
        except Exception:
            continue
    return None


def _infer_display_name(strategy_key: str) -> str:
    parts = [part for part in _safe_str(strategy_key).replace("-", "_").split("_") if part]
    if not parts:
        return "-"
    if len(parts) >= 2 and parts[-1].startswith("v"):
        return f"{parts[0].upper()} {' '.join(p.capitalize() for p in parts[1:-1])} {parts[-1]}".strip()
    return " ".join(part.upper() if idx == 0 else part.capitalize() for idx, part in enumerate(parts))


def _infer_deploy_stage(mode: str, route: str) -> str:
    m = _safe_str(mode, "paper").lower()
    r = _safe_str(route, "paper").lower()
    if m == "paper":
        return "paper"
    if m == "shadow":
        return "shadow"
    if m == "live" and r == "paper":
        return "capped-live"
    if m == "live" and r == "live":
        return "full-live"
    return m or "paper"


def _registry_specs_with_overrides(settings_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    reg_mod = _resolve_registry_module()
    base_specs = {}
    if reg_mod is not None:
        try:
            list_fn = getattr(reg_mod, "list_strategy_specs", None)
            if callable(list_fn):
                for item in list_fn(only_enabled=False):
                    if isinstance(item, dict) and item.get("key"):
                        base_specs[_safe_str(item.get("key")).lower()] = dict(item)
        except Exception:
            pass
        if not base_specs:
            try:
                raw_specs = getattr(reg_mod, "STRATEGY_SPECS", None)
                if isinstance(raw_specs, dict):
                    for key, spec in raw_specs.items():
                        if isinstance(spec, dict):
                            merged = dict(spec)
                            merged.setdefault("key", key)
                            base_specs[_safe_str(key).lower()] = merged
            except Exception:
                pass
    overrides = settings_data.get("strategy_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
    for key, spec in list(base_specs.items()):
        ov = overrides.get(key) or overrides.get(_safe_str(key).lower())
        if isinstance(ov, dict):
            merged = dict(spec)
            merged.update({k: v for k, v in ov.items() if k != "updated_at"})
            base_specs[key] = merged
    return base_specs


def _default_registry_spec(strategy_key: str, symbol: str) -> Dict[str, Any]:
    family = "range"
    bot_id = "MBot"
    s = _safe_str(strategy_key).lower()
    if "short" in s:
        family = "short"
        bot_id = "SBot"
    elif any(token in s for token in ("trend", "momentum", "breakout")):
        family = "range"
        bot_id = "MBot"
    return {
        "key": s or "btc_trend_v1",
        "canonical": s or "btc_trend_v1",
        "display_name": _infer_display_name(s or symbol or "strategy"),
        "symbol": _safe_str(symbol).upper(),
        "family": family,
        "bot_id": bot_id,
        "grade": "AB",
        "enabled": True,
        "onboarding_stage": "capped-live",
        "deploy_stage": "capped-live",
        "allowed_bot_ids": ["MBot", "LBot", "OBot"] if bot_id != "SBot" else ["SBot"],
        "strategy_spec_version": "bootstrap",
        "reason": "registry default",
    }


def _resolve_registry_spec(settings_data: Dict[str, Any], strategy_key: str, symbol: str) -> Dict[str, Any]:
    specs = _registry_specs_with_overrides(settings_data)
    key = _safe_str(strategy_key).lower()
    if key and key in specs:
        spec = dict(specs[key])
        spec.setdefault("key", key)
        spec.setdefault("canonical", key)
        spec.setdefault("display_name", _infer_display_name(key))
        spec.setdefault("symbol", _safe_str(symbol).upper())
        return spec
    return _default_registry_spec(key, symbol)


def _current_symbol_strategy(paper_state: Dict[str, Any], journal_event: Dict[str, Any], symbol: str, strategy: str) -> Tuple[str, str]:
    selected = paper_state.get("paper_state_selected")
    if not isinstance(selected, dict):
        selected = {}
    resolved_symbol = _safe_str(_first_non_empty(symbol, journal_event.get("symbol"), selected.get("symbol"), paper_state.get("symbol")), "BTCUSDT").upper()
    resolved_strategy = _safe_str(_first_non_empty(strategy, journal_event.get("strategy"), selected.get("strategy"), paper_state.get("strategy")), "btc_trend_v1").lower()
    return resolved_symbol, resolved_strategy


def _build_registry_selection(settings_data: Dict[str, Any], symbol: str = "", strategy: str = "") -> Dict[str, Any]:
    paper_state = _read_json(PAPER_STATE_LATEST)
    journal_latest = _read_json(JOURNAL_LATEST)
    journal_event = journal_latest.get("journal_event") if isinstance(journal_latest.get("journal_event"), dict) else {}
    resolved_symbol, resolved_strategy = _current_symbol_strategy(paper_state, journal_event, symbol, strategy)
    spec = _resolve_registry_spec(settings_data, resolved_strategy, resolved_symbol)
    effective_mode, effective_route, reason = _resolve_effective_mode_route(settings_data)
    deploy_stage = _infer_deploy_stage(effective_mode, effective_route)
    selected_bot_id = _safe_str(spec.get("bot_id"), "MBot")
    return {
        "ok": True,
        "symbol": resolved_symbol,
        "strategy": resolved_strategy,
        "canonical": _safe_str(spec.get("canonical"), resolved_strategy),
        "display_name": _safe_str(spec.get("display_name"), _infer_display_name(resolved_strategy)),
        "family": _safe_str(spec.get("family"), "range"),
        "selected_bot_id": selected_bot_id,
        "bot_id": selected_bot_id,
        "grade": _safe_str(spec.get("grade"), "AB"),
        "enabled": _safe_bool(spec.get("enabled"), True),
        "deploy_stage": _safe_str(spec.get("deploy_stage"), deploy_stage),
        "runtime_deploy_stage": deploy_stage,
        "onboarding_stage": _safe_str(spec.get("onboarding_stage"), deploy_stage),
        "allowed_bot_ids": spec.get("allowed_bot_ids") if isinstance(spec.get("allowed_bot_ids"), list) else [selected_bot_id],
        "strategy_spec_version": _safe_str(spec.get("strategy_spec_version"), "bootstrap"),
        "change_request_id": _safe_str(spec.get("change_request_id"), ""),
        "approved_by": _safe_str(spec.get("approved_by"), ""),
        "rollback_target_version": _safe_str(spec.get("rollback_target_version"), ""),
        "git_revision": _safe_str(spec.get("git_revision"), ""),
        "deployment_ticket_id": _safe_str(spec.get("deployment_ticket_id"), ""),
        "reason": _safe_str(spec.get("reason"), reason or "registry selection"),
        "mode": _norm_runtime_mode(settings_data.get("mode"), "paper"),
        "route": _norm_runtime_route(settings_data.get("route"), "paper"),
        "effective_mode": effective_mode,
        "effective_route": effective_route,
        "selection_locked": True,
        "source": "settings_registry",
    }


@router.get("/api/v1/registry/selection")
def registry_selection(
    symbol: Optional[str] = Query(default=None),
    strategy: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    data = _load_all()
    return _build_registry_selection(
        data,
        symbol=_safe_str(symbol, ""),
        strategy=_safe_str(strategy, ""),
    )


@router.get("/api/v1/registry/strategies")
def registry_strategies() -> Dict[str, Any]:
    data = _load_all()
    specs = _registry_specs_with_overrides(data)
    items = []
    for key in sorted(specs.keys()):
        spec = dict(specs[key])
        spec.setdefault("key", key)
        spec.setdefault("canonical", key)
        spec.setdefault("display_name", _infer_display_name(key))
        items.append(_public_settings_view(spec))
    if not items:
        current = _build_registry_selection(data)
        items = [_public_settings_view(current)]
    return {"ok": True, "count": len(items), "items": items}


@router.post("/api/v1/control/strategy_toggle")
def control_strategy_toggle(payload: StrategyToggleRequest) -> Dict[str, Any]:
    strategy_key = _safe_str(payload.strategy).lower()
    if not strategy_key:
        raise HTTPException(status_code=400, detail="strategy is required")
    data = _load_all()
    overrides = data.setdefault("strategy_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}
        data["strategy_overrides"] = overrides
    spec = _resolve_registry_spec(data, strategy_key, "")
    overrides[strategy_key] = {
        **spec,
        "enabled": bool(payload.enabled),
        "updated_at": _now_iso(),
    }
    _backup_file()
    _save_all(data)
    return {
        "ok": True,
        "strategy": strategy_key,
        "enabled": bool(payload.enabled),
        "selection": _public_settings_view(_build_registry_selection(data)),
        "meta": _build_meta(),
    }


@router.get("/api/v1/settings/null-error-contract")
def get_null_error_contract() -> Dict[str, Any]:
    return {
        "ok": True,
        "contract_version": NULL_ERROR_CONTRACT_VERSION,
        "defaults": {
            "mode": "paper",
            "route": "paper",
            "exchange_enabled": False,
            "kill_switch": True,
            "journal_enabled": True,
            "timeline_enabled": True,
            "ui_placeholder": normalize_text(None),
        },
        "null_policy": {
            "missing_string": "",
            "missing_number": 0,
            "missing_bool": False,
            "missing_object": {},
            "missing_list": [],
        },
        "error_policy": normalize_error_contract(detail="contract_ready", reason="contract_ready", error_code="ok", status="ready"),
    }
