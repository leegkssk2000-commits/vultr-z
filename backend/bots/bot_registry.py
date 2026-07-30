from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class _ReadOnlyBot:
    name: str
    primary_key: str
    secondary_key: str
    posture: str

    def decide(self, market_state: Dict[str, Any], *, team_policy: Dict[str, Any] | None = None) -> Dict[str, Any]:
        state = dict(market_state or {})
        try:
            primary = float(state.get(self.primary_key, 0.0) or 0.0)
        except Exception:
            primary = 0.0
        try:
            secondary = float(state.get(self.secondary_key, 0.0) or 0.0)
        except Exception:
            secondary = 0.0
        fit = max(0.0, min(1.0, (0.70 * primary) + (0.30 * secondary)))
        stale = bool(state.get("stale", False))
        freeze = bool(state.get("freeze_mode", False))
        venue = str(state.get("venue_health") or "unknown").lower()
        consensus = str(state.get("consensus") or state.get("watcher_consensus") or "unknown").lower()
        warnings = []
        if stale:
            warnings.append("stale_source")
        if freeze:
            warnings.append("freeze_mode")
        if venue in {"weak", "down", "blocked"}:
            warnings.append("venue_weak")
        if consensus == "low":
            warnings.append("consensus_low")
        if warnings:
            fit = min(fit, 0.25)
        identity = {
            "bot": self.name,
            "source": state.get("source") or state.get("_source") or "",
            "source_ts": state.get("source_ts") or state.get("_source_ts") or 0,
            "fit": round(fit, 4),
        }
        decision_id = "bot." + hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()[:20]
        return {
            "bot": self.name,
            "fit": round(fit, 4),
            "why": [self.posture, f"{self.primary_key}={primary:.4f}", f"{self.secondary_key}={secondary:.4f}"],
            "warnings": warnings,
            "meta": {
                "helper_trigger": bool(fit >= 0.72 and not warnings),
                "watcher_consensus": "low" if warnings else (consensus if consensus in {"low", "medium", "high"} else "medium"),
                "team_policy_bound": bool(team_policy),
            },
            "decision_id": decision_id,
            "source": identity["source"],
            "source_ts": identity["source_ts"],
            "stale_ms": int(state.get("stale_ms") or 0),
            "reconcile_status": str(state.get("reconcile_status") or "ok"),
            "action": "hold",
            "risk_action": "hold",
            "research_only": True,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "runtime_bound": False,
        }


_BOTS = {
    "LBot": _ReadOnlyBot("LBot", "trend_score", "confirm_score", "lead trend confirmation"),
    "MBot": _ReadOnlyBot("MBot", "confirm_score", "intuition_score", "method/range confirmation"),
    "OBot": _ReadOnlyBot("OBot", "breakout_score", "trend_score", "breakout observation"),
    "SBot": _ReadOnlyBot("SBot", "drawdown_score", "decay_pct", "defensive short/risk observation"),
}


def get_bot(name: str) -> _ReadOnlyBot:
    key = str(name or "").strip()
    if key not in _BOTS:
        raise KeyError(f"unknown bot: {key}")
    return _BOTS[key]


def list_bots() -> list[str]:
    return sorted(_BOTS)


def registry_snapshot() -> Dict[str, Any]:
    return {
        "bots": list_bots(),
        "mode": "read_only_fail_closed",
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
