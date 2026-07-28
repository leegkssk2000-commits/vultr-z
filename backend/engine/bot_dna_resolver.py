from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

CONTRACTS_DIR = Path("/home/z/z/backend/contracts")
SCHEMA_LOCK_PATH = CONTRACTS_DIR / "ZOS_SCHEMA_LOCK_v1.json"
SKILL_REGISTRY_PATH = CONTRACTS_DIR / "ZOS_SKILL_REGISTRY_v1.json"


def _safe_dict(v: Any) -> Dict[str, Any]:
    return deepcopy(v) if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list:
    return list(v) if isinstance(v, list) else []


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
    except Exception:
        return default


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


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _normalize_family(raw_family: str) -> str:
    s = _safe_str(raw_family).lower()
    mapping = {
        "l": "L",
        "fallback": "L",
        "m": "M",
        "range": "M",
        "mean_revert": "M",
        "mean-revert": "M",
        "o": "O",
        "momentum": "O",
        "trend": "O",
        "breakout": "O",
        "s": "S",
        "short": "S",
    }
    return mapping.get(s, raw_family if raw_family in {"L", "M", "O", "S"} else "L")


def _default_behavior(bot_id: str) -> Dict[str, Any]:
    if bot_id == "LBot":
        return {
            "allow_long_beam": False,
            "allow_short_beam": False,
            "allow_dca": True,
            "allow_pyramid": False,
            "max_add_count": 1,
            "max_pyramid_steps": 0,
            "momentum_gate": None,
            "cooldown_rules": ["default_cooldown"],
            "switch_budget": 1,
            "bot_parking_policy": "fallback_safe",
        }
    if bot_id == "MBot":
        return {
            "allow_long_beam": False,
            "allow_short_beam": False,
            "allow_dca": True,
            "allow_pyramid": False,
            "max_add_count": 2,
            "max_pyramid_steps": 0,
            "momentum_gate": None,
            "cooldown_rules": ["range_cooldown"],
            "switch_budget": 1,
            "bot_parking_policy": "range_safe",
        }
    if bot_id == "OBot":
        return {
            "allow_long_beam": True,
            "allow_short_beam": False,
            "allow_dca": False,
            "allow_pyramid": True,
            "max_add_count": 1,
            "max_pyramid_steps": 1,
            "momentum_gate": "trend_or_breakout",
            "cooldown_rules": ["trend_cooldown"],
            "switch_budget": 1,
            "bot_parking_policy": "trend_safe",
        }
    return {
        "allow_long_beam": False,
        "allow_short_beam": True,
        "allow_dca": False,
        "allow_pyramid": False,
        "max_add_count": 0,
        "max_pyramid_steps": 0,
        "momentum_gate": "short_only",
        "cooldown_rules": ["short_cooldown"],
        "switch_budget": 1,
        "bot_parking_policy": "short_safe",
    }


def _default_risk_limits(bot_id: str) -> Dict[str, Any]:
    if bot_id == "LBot":
        return {
            "max_expected_slippage_bps": 20,
            "max_funding_bps": 8,
            "min_liq_buffer_pct": 12,
            "max_dd_pct": 5,
            "max_leverage": 10,
            "max_position_utilization": 0.05,
        }
    if bot_id == "MBot":
        return {
            "max_expected_slippage_bps": 15,
            "max_funding_bps": 8,
            "min_liq_buffer_pct": 10,
            "max_dd_pct": 5,
            "max_leverage": 15,
            "max_position_utilization": 0.05,
        }
    if bot_id == "OBot":
        return {
            "max_expected_slippage_bps": 18,
            "max_funding_bps": 10,
            "min_liq_buffer_pct": 10,
            "max_dd_pct": 6,
            "max_leverage": 25,
            "max_position_utilization": 0.10,
        }
    return {
        "max_expected_slippage_bps": 18,
        "max_funding_bps": 10,
        "min_liq_buffer_pct": 12,
        "max_dd_pct": 5,
        "max_leverage": 20,
        "max_position_utilization": 0.07,
    }


def _default_skill_refs(bot_id: str) -> Dict[str, Any]:
    common_exec = [
        "SK_EXEC_SLIPPAGE_ESTIMATOR",
        "SK_EXEC_MARKOUT_GUARD",
        "SK_EXEC_ADVERSE_SELECTION",
        "SK_EXEC_PARTICIPATION_CAP",
    ]
    common_port = [
        "SK_PORT_CORRELATION_GUARD",
        "SK_PORT_SLIPPAGE_THROTTLE",
        "SK_PORT_INVENTORY_AWARE",
    ]
    if bot_id == "LBot":
        return {
            "bot_skills": [
                "SK_POS_SCALE_IN",
                "SK_POS_SCALE_OUT",
                "SK_POS_BREAK_EVEN_SHIFT",
                "SK_BOT_REGIME_GATE",
                "SK_BOT_COOLDOWN",
                "SK_BOT_PARKING",
            ],
            "execution_skills": common_exec,
            "portfolio_interaction_skills": common_port,
        }
    if bot_id == "MBot":
        return {
            "bot_skills": [
                "SK_POS_SCALE_IN",
                "SK_POS_SCALE_OUT",
                "SK_POS_TIME_STOP",
                "SK_BOT_REGIME_GATE",
                "SK_BOT_COOLDOWN",
                "SK_BOT_SWITCH_BUDGET",
            ],
            "execution_skills": common_exec,
            "portfolio_interaction_skills": common_port,
        }
    if bot_id == "OBot":
        return {
            "bot_skills": [
                "SK_POS_SCALE_OUT",
                "SK_POS_TRAILING_STOP",
                "SK_POS_BREAK_EVEN_SHIFT",
                "SK_BOT_REGIME_GATE",
                "SK_BOT_COOLDOWN",
                "SK_BOT_SWITCH_BUDGET",
            ],
            "execution_skills": common_exec + ["SK_EXEC_TWAP", "SK_EXEC_ICEBERG"],
            "portfolio_interaction_skills": common_port,
        }
    return {
        "bot_skills": [
            "SK_POS_SCALE_OUT",
            "SK_POS_TIME_STOP",
            "SK_BOT_REGIME_GATE",
            "SK_BOT_COOLDOWN",
        ],
        "execution_skills": common_exec,
        "portfolio_interaction_skills": common_port,
    }


def _catalog_entry(bot_id: str) -> Dict[str, Any]:
    try:
        from backend.engine.strategy_registry import BOT_CATALOG  # type: ignore
        if isinstance(BOT_CATALOG, dict):
            return _safe_dict(BOT_CATALOG.get(bot_id))
    except Exception:
        pass
    return {}


def _strategy_spec(strategy_id: str) -> Dict[str, Any]:
    try:
        from backend.engine.strategy_registry import get_strategy_spec  # type: ignore
        if callable(get_strategy_spec):
            return _safe_dict(get_strategy_spec(strategy_id))
    except Exception:
        pass
    return {}


def resolve_bot_dna(
    bot_id: str,
    symbol: Optional[str] = None,
    strategy_id: Optional[str] = None,
    regime: Optional[str] = None,
    settings_snapshot: Optional[Dict[str, Any]] = None,
    base_bot_defaults: Optional[Dict[str, Any]] = None,
    family_defaults: Optional[Dict[str, Any]] = None,
    bot_specific_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Canonical resolver when Bot DNA is physically split across multiple files / layers.
    Merge order is locked by ZOS_CONNECTION_RULES_LOCK_v1.txt.
    """
    bot_id = _safe_str(bot_id)
    catalog = _catalog_entry(bot_id)
    spec = _strategy_spec(_safe_str(strategy_id))
    settings = _safe_dict(settings_snapshot)

    family_only = _normalize_family(
        _safe_str(
            catalog.get("family_only")
            or catalog.get("family")
            or spec.get("family")
            or ("S" if bot_id == "SBot" else bot_id[:1])
        )
    )

    live_eligibility = not bool(catalog.get("shadow_only", False))
    if bot_id == "SBot":
        live_eligibility = False

    base = {
        "bot_id": bot_id,
        "bot_semver": "1.0.0",
        "family_only": family_only,
        "live_eligibility": live_eligibility,
        "permission": {
            "live_eligibility": live_eligibility,
            "activation_prerequisite": None,
            "activation_approved_by": None,
            "activation_ticket_id": None,
        },
        "behavior": _default_behavior(bot_id),
        "risk_limits": _default_risk_limits(bot_id),
        "skill_refs": _default_skill_refs(bot_id),
        "context": {
            "symbol": _safe_str(symbol),
            "strategy_id": _safe_str(strategy_id),
            "regime": _safe_str(regime),
            "settings_mode": _safe_str(settings.get("mode") or settings.get("effective_mode")),
            "settings_route": _safe_str(settings.get("route") or settings.get("effective_route")),
        },
    }

    if _safe_dict(base_bot_defaults):
        base = _deep_merge(base, _safe_dict(base_bot_defaults))
    if _safe_dict(family_defaults):
        base = _deep_merge(base, _safe_dict(family_defaults))
    if _safe_dict(bot_specific_overrides):
        base = _deep_merge(base, _safe_dict(bot_specific_overrides))

    # spec-driven allowlist shaping
    allowed_bot_ids = _safe_list(spec.get("allowed_bot_ids"))
    if allowed_bot_ids and bot_id not in allowed_bot_ids:
        base["permission"]["live_eligibility"] = False
        base["live_eligibility"] = False
        base["permission"]["activation_prerequisite"] = "not in allowed_bot_ids"

    deploy_stage = _safe_str(spec.get("deploy_stage") or spec.get("onboarding_stage"))
    if bot_id == "SBot" and deploy_stage in {"capped-live", "full-live", "live"}:
        base["permission"]["live_eligibility"] = False
        base["live_eligibility"] = False
        base["permission"]["activation_prerequisite"] = "SBot shadow-only by lock"

    return base


__all__ = ["resolve_bot_dna", "SCHEMA_LOCK_PATH", "SKILL_REGISTRY_PATH"]
