from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, TYPE_CHECKING

from .strategy_iface import Strategy, MarketSnapshot

try:
    from backend.engine.skill_resolver import (
        load_schema_lock,
        load_skill_registry,
        validate_strategy_skill_refs,
    )
except Exception:
    load_schema_lock = None  # type: ignore
    load_skill_registry = None  # type: ignore
    validate_strategy_skill_refs = None  # type: ignore

if TYPE_CHECKING:
    from .risk_engine import AccountState, Position
else:
    AccountState = Any
    Position = Any


@dataclass
class StrategyConfig:
    key: str
    symbol: str
    exchange: str
    max_abs_size: float
    enabled: bool = True


class SimpleTrendStrategy:
    name = "simple_trend"

    def compute_target_size(
        self,
        state: AccountState,
        position: Position | None,
        snapshot: MarketSnapshot,
    ) -> float:
        if not snapshot.extra:
            return 0.0

        direction = snapshot.extra.get("dir")
        risk_pct = float(snapshot.extra.get("risk_pct", 0.01))

        equity = float(getattr(state, "equity", 0.0) or 0.0)
        price = float(getattr(snapshot, "price", 0.0) or 0.0)

        if direction in (None, "", "flat"):
            return 0.0
        if price <= 0 or equity <= 0:
            return 0.0

        qty = equity * risk_pct / price
        if str(direction).lower() == "short":
            qty = -qty
        return qty


STRATEGIES: Dict[str, Strategy] = {
    "btc_trend_v1": SimpleTrendStrategy(),
    "eth_trend_v1": SimpleTrendStrategy(),
}

STRATEGY_CONFIGS: List[StrategyConfig] = [
    StrategyConfig(
        key="btc_trend_v1",
        symbol="BTCUSDT",
        exchange="bingx",
        max_abs_size=0.05,
        enabled=True,
    ),
    StrategyConfig(
        key="eth_trend_v1",
        symbol="ETHUSDT",
        exchange="bitget",
        max_abs_size=0.5,
        enabled=True,
    ),
]

BOT_CATALOG: Dict[str, Dict[str, Any]] = {
    "LBot": {
        "id": "LBot",
        "family": "fallback",
        "display_name": "LBot",
        "posture": "broad / recovery",
        "shadow_only": False,
    },
    "MBot": {
        "id": "MBot",
        "family": "range",
        "display_name": "MBot",
        "posture": "mean-revert",
        "shadow_only": False,
    },
    "OBot": {
        "id": "OBot",
        "family": "momentum",
        "display_name": "OBot",
        "posture": "trend / breakout",
        "shadow_only": False,
    },
    "SBot": {
        "id": "SBot",
        "family": "short",
        "display_name": "SBot",
        "posture": "short-only",
        "shadow_only": True,
    },
}


def _safe_dict(v: Any) -> Dict[str, Any]:
    return dict(v) if isinstance(v, dict) else {}


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
    except Exception:
        return default


def _norm_family(v: Any) -> str:
    s = _safe_str(v).lower()
    return {
        "fallback": "L",
        "l": "L",
        "range": "M",
        "mean_revert": "M",
        "mean-revert": "M",
        "m": "M",
        "momentum": "O",
        "trend": "O",
        "breakout": "O",
        "o": "O",
        "short": "S",
        "s": "S",
    }.get(s, "L")


def _default_skill_refs(spec: Dict[str, Any]) -> Dict[str, Any]:
    family_code = _norm_family(spec.get("family"))
    if family_code == "M":
        return {
            "strategy_skills": [
                "SK_STRAT_RANGE_FADE",
                "SK_STRAT_MEAN_REVERT_TRIGGER",
            ],
            "position_management_skills": [
                "SK_POS_SCALE_IN",
                "SK_POS_SCALE_OUT",
                "SK_POS_TIME_STOP",
            ],
            "risk_skills": [
                "SK_PORT_CORRELATION_GUARD",
                "SK_OPS_GLOBAL_CIRCUIT_BREAKER",
            ],
            "explain_skills": [
                "SK_AI_WHY_SUMMARY",
            ],
        }
    if family_code == "O":
        return {
            "strategy_skills": [
                "SK_STRAT_TREND_CONTINUATION",
                "SK_STRAT_BREAKOUT_RETEST",
            ],
            "position_management_skills": [
                "SK_POS_SCALE_OUT",
                "SK_POS_BREAK_EVEN_SHIFT",
                "SK_POS_TRAILING_STOP",
            ],
            "risk_skills": [
                "SK_PORT_CORRELATION_GUARD",
                "SK_OPS_GLOBAL_CIRCUIT_BREAKER",
            ],
            "explain_skills": [
                "SK_AI_WHY_SUMMARY",
            ],
        }
    if family_code == "S":
        return {
            "strategy_skills": [
                "SK_STRAT_TREND_CONTINUATION",
            ],
            "position_management_skills": [
                "SK_POS_SCALE_OUT",
                "SK_POS_TIME_STOP",
            ],
            "risk_skills": [
                "SK_PORT_CORRELATION_GUARD",
                "SK_OPS_GLOBAL_CIRCUIT_BREAKER",
            ],
            "explain_skills": [
                "SK_AI_WHY_SUMMARY",
            ],
        }
    return {
        "strategy_skills": [
            "SK_STRAT_PULLBACK_ENTRY",
            "SK_STRAT_TREND_CONTINUATION",
        ],
        "position_management_skills": [
            "SK_POS_SCALE_IN",
            "SK_POS_SCALE_OUT",
            "SK_POS_BREAK_EVEN_SHIFT",
        ],
        "risk_skills": [
            "SK_PORT_CORRELATION_GUARD",
            "SK_OPS_GLOBAL_CIRCUIT_BREAKER",
        ],
        "explain_skills": [
            "SK_AI_WHY_SUMMARY",
        ],
    }


def _attach_skill_refs(spec: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(spec)
    if not isinstance(out.get("skill_refs"), dict):
        out["skill_refs"] = _default_skill_refs(out)
    return out


def _attach_skill_validation(spec: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(spec)
    if not callable(validate_strategy_skill_refs) or not callable(load_skill_registry) or not callable(load_schema_lock):
        out["_skill_validation"] = {"ok": False, "errors": ["skill_resolver_unavailable"]}
        return out
    try:
        registry = load_skill_registry()
        schema = load_schema_lock()
        out["_skill_validation"] = validate_strategy_skill_refs(out, registry, schema)
    except Exception as exc:
        out["_skill_validation"] = {"ok": False, "errors": [f"validation_error:{exc}"]}
    return out


STRATEGY_SPECS: Dict[str, Dict[str, Any]] = {
    "btc_trend_v1": {
        "key": "btc_trend_v1",
        "canonical": "btc_trend_v1",
        "display_name": "BTC Trend v1",
        "symbol": "BTCUSDT",
        "exchange": "bingx",
        "family": "range",
        "bot_id": "MBot",
        "grade": "AB",
        "enabled": True,
        "onboarding_stage": "capped-live",
        "deploy_stage": "capped-live",
        "allowed_bot_ids": ["MBot", "LBot", "OBot"],
        "strategy_spec_version": "1.0.0",
        "change_request_id": "bootstrap",
        "approved_by": "operator",
        "rollback_target_version": "bootstrap",
        "git_revision": "manual",
        "deployment_ticket_id": "ops-lite-g5-2",
        "reason": "range / mean-revert candidate",
    },
    "eth_trend_v1": {
        "key": "eth_trend_v1",
        "canonical": "eth_trend_v1",
        "display_name": "ETH Trend v1",
        "symbol": "ETHUSDT",
        "exchange": "bitget",
        "family": "range",
        "bot_id": "MBot",
        "grade": "AB",
        "enabled": True,
        "onboarding_stage": "capped-live",
        "deploy_stage": "capped-live",
        "allowed_bot_ids": ["MBot", "LBot", "OBot"],
        "strategy_spec_version": "1.0.0",
        "change_request_id": "bootstrap",
        "approved_by": "operator",
        "rollback_target_version": "bootstrap",
        "git_revision": "manual",
        "deployment_ticket_id": "ops-lite-g5-2",
        "reason": "range / mean-revert candidate",
    },
}


def get_active_strategies() -> List[StrategyConfig]:
    return [c for c in STRATEGY_CONFIGS if c.enabled]


def _phase1_registry_entry(key: str) -> Dict[str, Any]:
    try:
        from backend.engine.phase1_registry import get_strategy_record

        row = get_strategy_record(key)
        return dict(row) if isinstance(row, dict) else {}
    except Exception:
        return {}


def get_strategy_spec(key: str) -> Dict[str, Any]:
    raw = dict(STRATEGY_SPECS.get(str(key).strip().lower(), {}))
    if not raw:
        return {}
    with_refs = _attach_skill_refs(raw)
    with_validation = _attach_skill_validation(with_refs)
    phase1 = _phase1_registry_entry(str(key).strip().lower())
    if phase1:
        with_validation["phase1_registry"] = phase1
    return with_validation


def get_phase1_strategy_record(key: str) -> Dict[str, Any]:
    return _phase1_registry_entry(str(key).strip().lower())


def list_strategy_specs(*, only_enabled: bool = False) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for key, spec in STRATEGY_SPECS.items():
        merged = get_strategy_spec(key)
        if not merged:
            continue
        config = next((c for c in STRATEGY_CONFIGS if c.key == key), None)
        if config is not None:
            merged.setdefault("symbol", config.symbol)
            merged.setdefault("exchange", config.exchange)
            merged.setdefault("enabled", config.enabled)
        if only_enabled and not bool(merged.get("enabled", True)):
            continue
        items.append(merged)
    return items


STRATEGY_REGISTRY = {
    k: (lambda obj=v: obj)
    for k, v in STRATEGIES.items()
}


__all__ = [
    "StrategyConfig",
    "SimpleTrendStrategy",
    "STRATEGIES",
    "STRATEGY_CONFIGS",
    "STRATEGY_REGISTRY",
    "STRATEGY_SPECS",
    "BOT_CATALOG",
    "get_active_strategies",
    "get_phase1_strategy_record",
    "get_strategy_spec",
    "list_strategy_specs",
]
