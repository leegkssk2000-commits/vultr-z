from __future__ import annotations

from typing import Any, Dict


def _safe_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def adapt_legacy_decision(bot_name: str, decision: Dict[str, Any], team_policy: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out = _safe_dict(decision)
    out.setdefault("bot", str(bot_name))
    out.setdefault("action", "hold")
    out.setdefault("risk_action", "hold")
    out.setdefault("execution_allowed", False)
    out.setdefault("order_authority", "BLOCKED")
    out.setdefault("runtime_bound", False)
    if team_policy:
        out.setdefault("team_policy", _safe_dict(team_policy))
    return out


def adapt_team_payload(team_name: str, team_cfg: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "team": str(team_name),
        "config": _safe_dict(team_cfg),
        "decision": _safe_dict(raw),
        "action": "hold",
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }


def adapt_team_overview(team_name: str, team_cfg: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    payload = adapt_team_payload(team_name, team_cfg, raw)
    payload["overview_only"] = True
    return payload
