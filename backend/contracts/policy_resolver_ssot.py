from __future__ import annotations

from typing import Any, Dict, Iterable

POLICY_RESOLVER_SSOT_VERSION = "15A.6.v1"
POLICY_SOURCE = "policy_resolver_ssot"

SUPPORTED_PROFILES = {"default", "trend", "range", "recovery", "guard", "paper", "live", "shadow"}
SUPPORTED_SUBTYPES = {"default", "scalp", "revert", "breakout", "hedge", "intraday", "swing", "confirm"}
SUPPORTED_STRATEGY_PREFIXES = ("btc_", "eth_", "sol_", "xrp_", "link_", "mean_", "short_", "breakout_")


def _s(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
    except Exception:
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        if v in (None, ""):
            return default
        return int(float(v))
    except Exception:
        return default


def _b(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on", "ready"}
    return default


def _norm_profile(v: Any) -> str:
    return _s(v, "default").lower().replace("-", "_").replace(" ", "_")


def _norm_subtype(v: Any) -> str:
    return _s(v, "default").lower().replace("-", "_").replace(" ", "_")


def _as_flags(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [item.strip() for item in v.split(',') if item.strip()]
    if isinstance(v, Iterable):
        out: list[str] = []
        for item in v:
            s = _s(item)
            if s:
                out.append(s)
        return out
    return []


def _block(reason_code: str, *, profile: str, subtype: str, strategy: str) -> Dict[str, Any]:
    return {
        "decision_action": "block",
        "risk_action": "block",
        "reason_code": reason_code,
        "policy_source": POLICY_SOURCE,
        "resolver_contract_version": POLICY_RESOLVER_SSOT_VERSION,
        "profile": profile,
        "subtype": subtype,
        "strategy": strategy,
        "silent_fallback": False,
    }


def resolve_policy_ssot(payload: Dict[str, Any] | None = None, **kwargs: Any) -> Dict[str, Any]:
    src = dict(payload or {})
    src.update(kwargs)

    strategy = _s(src.get("strategy"), "unknown")
    profile = _norm_profile(src.get("profile") or src.get("mode") or src.get("regime"))
    subtype = _norm_subtype(src.get("subtype") or src.get("method") or src.get("trade_method"))
    fit_tier = _s(src.get("fit_tier") or src.get("fit"), "").upper()
    mood = _s(src.get("mood"), "").lower()
    consensus = _s(src.get("consensus"), "").lower()
    venue_health = _s(src.get("venue_health") or src.get("venue"), "").lower()
    intuition_score = _i(src.get("intuition_score") or src.get("intuition"))
    decay_pct = _i(src.get("decay_pct") or src.get("decay"))
    stale = _b(src.get("stale"), default=False)
    flags = set(_as_flags(src.get("feature_flags")))

    if strategy == "unknown" or (strategy != "unknown" and not strategy.startswith(SUPPORTED_STRATEGY_PREFIXES)):
        return _block("UNKNOWN_STRATEGY", profile=profile, subtype=subtype, strategy=strategy)
    if profile not in SUPPORTED_PROFILES:
        return _block("UNSUPPORTED_PROFILE", profile=profile, subtype=subtype, strategy=strategy)
    if subtype not in SUPPORTED_SUBTYPES:
        return _block("UNSUPPORTED_SUBTYPE", profile=profile, subtype=subtype, strategy=strategy)
    if "freeze_mode" in flags:
        return _block("FREEZE_MODE", profile=profile, subtype=subtype, strategy=strategy)
    if venue_health in {"weak", "degraded", "thin"}:
        return _block("VENUE_WEAK", profile=profile, subtype=subtype, strategy=strategy)

    reason_code = "OK"
    decision_action = "hold"
    risk_action = "hold"

    if stale:
        reason_code = "MARKET_STALE"
    elif "dd_total_high" in flags:
        decision_action = "reduce"
        risk_action = "reduce25"
        reason_code = "DD_TOTAL_HIGH"
    elif "dd_day_high" in flags:
        decision_action = "reduce"
        risk_action = "partial30"
        reason_code = "DD_DAY_HIGH"
    elif consensus == "low":
        reason_code = "CONSENSUS_LOW"
    elif intuition_score and intuition_score < 40:
        reason_code = "INTUITION_ALERT"
    elif decay_pct >= 15:
        reason_code = "DECAY_HIGH"
    elif fit_tier == "A" and consensus in {"high", "84", "strong"} and mood not in {"alert", "uneasy"}:
        decision_action = "enter"
        reason_code = "CONSENSUS_HIGH"
    elif fit_tier == "B" and mood == "uneasy":
        reason_code = "UNEASY_FILTER"

    return {
        "decision_action": decision_action,
        "risk_action": risk_action,
        "reason_code": reason_code,
        "policy_source": POLICY_SOURCE,
        "resolver_contract_version": POLICY_RESOLVER_SSOT_VERSION,
        "profile": profile,
        "subtype": subtype,
        "strategy": strategy,
        "silent_fallback": False,
    }


__all__ = ["POLICY_RESOLVER_SSOT_VERSION", "POLICY_SOURCE", "resolve_policy_ssot"]
