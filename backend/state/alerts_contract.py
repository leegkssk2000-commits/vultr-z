from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        elif k not in dst:
            dst[k] = deepcopy(v)
    return dst


def base_settings_defaults() -> Dict[str, Any]:
    return {
        "mode": "paper",
        "route": "paper",
        "exchange_enabled": False,
        "kill_switch": True,
        "strategy_overrides": {},
    }


def alerts_defaults() -> Dict[str, Any]:
    return {
        "alerts": {
            "contract_version": "alerts.settings.v1",
            "channels": {
                "telegram": {
                    "enabled": False,
                    "bot_token": "",
                    "chat_id": "",
                    "thread_id": "",
                    "parse_mode": "Markdown",
                    "send_silent": False,
                },
                "push": {
                    "enabled": False,
                    "provider": "native",
                    "topic": "",
                    "device_ids": [],
                },
            },
            "policy": {
                "level": "warning",
                "team_filter": [],
                "symbol_filter": [],
                "quiet_hours": {
                    "enabled": False,
                    "start": "01:00",
                    "end": "07:00",
                    "timezone": "Europe/Berlin",
                    "critical_override": True,
                },
                "thresholds": {
                    "dd_day_pct": 3.0,
                    "dd_total_pct": 8.0,
                    "liq_buffer_pct": 10.0,
                    "funding_8h_pct": 0.05,
                },
                "dedupe": {
                    "enabled": True,
                    "window_sec": 600,
                    "key_template": "event_type:team:symbol:action:severity",
                },
                "cooldown": {
                    "enabled": True,
                    "sec": 600,
                },
                "escalation": {
                    "mode": "telegram_first",
                    "fallback_push": True,
                },
            },
            "reports": {
                "daily": {
                    "enabled": False,
                    "time": "08:30",
                    "timezone": "Europe/Berlin",
                    "channel": "telegram",
                },
                "weekly": {
                    "enabled": False,
                    "day": "MON",
                    "time": "09:00",
                    "timezone": "Europe/Berlin",
                    "channel": "telegram",
                },
            },
        }
    }


def ensure_settings_contract(data: Dict[str, Any]) -> Dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    out = deepcopy(data)
    _deep_merge(out, base_settings_defaults())
    _deep_merge(out, alerts_defaults())
    return out


def alert_preview_payload(
    *,
    event_type: str = "risk",
    severity: str = "warning",
    decision_id: str = "preview_decision_id",
    symbol: str = "BTCUSDT",
    team: str = "ALPHA",
    action: str = "hold",
    reason: str = "preview",
) -> Dict[str, Any]:
    return {
        "contract_version": "alerts.event.v1",
        "channel": "telegram",
        "event_type": event_type,
        "severity": severity,
        "decision_id": decision_id,
        "source_ts": 0,
        "stale_ms": 0,
        "reconcile_status": "ok",
        "symbol": symbol,
        "team": team,
        "action": action,
        "reason": reason,
        "message": f"[{severity}] {team} {symbol} {action} | {reason}",
    }
