from __future__ import annotations

from .policy import POLICY
from .profiles import METHOD_PROFILES
from .types import (
    ActionKind,
    ConsensusLevel,
    DecisionInput,
    DecisionOutput,
    FitTier,
    IntuitionLevel,
    MethodProfile,
    ScalpSubtype,
    TradeMethod,
)


def resolve_method_profile(method: TradeMethod, subtype: ScalpSubtype) -> MethodProfile:
    return METHOD_PROFILES.get(
        (method, subtype),
        MethodProfile(
            method=method,
            subtype=subtype,
            label=f"{method.value} · {subtype.value}",
            entry_style="observe_then_confirm",
            hold_horizon="blocked" if method == TradeMethod.BLOCKED else "10-45m",
            rescue_observe="fallback observe",
            next_strategy_hint="watch_only",
        ),
    )


def resolve_fit_tier(pair_confidence: int, venue_health: int, decay_pct: float) -> FitTier:
    if pair_confidence >= 90 and venue_health >= 90 and decay_pct <= 6:
        return FitTier.S
    if pair_confidence >= 80 and venue_health >= 80 and decay_pct <= 10:
        return FitTier.A
    if pair_confidence >= 65 and venue_health >= 70 and decay_pct <= 18:
        return FitTier.B
    return FitTier.C


def resolve_intuition(intuition_score: int) -> IntuitionLevel:
    if intuition_score <= POLICY["intuition"]["calm_max"]:
        return IntuitionLevel.CALM
    if intuition_score <= POLICY["intuition"]["uneasy_max"]:
        return IntuitionLevel.UNEASY
    return IntuitionLevel.ALERT


def resolve_consensus(regime_score: int, risk_score: int, venue_score: int) -> tuple[ConsensusLevel, int]:
    score = round((regime_score + risk_score + venue_score) / 3)
    if score >= POLICY["consensus"]["high_min"]:
        return ConsensusLevel.HIGH, score
    if score >= POLICY["consensus"]["medium_min"]:
        return ConsensusLevel.MEDIUM, score
    return ConsensusLevel.LOW, score


def resolve_action_bundle(data: DecisionInput) -> DecisionOutput:
    profile = resolve_method_profile(data.method, data.subtype)
    fit = resolve_fit_tier(data.pair_confidence, data.venue_health, data.decay_pct)
    intuition = resolve_intuition(data.intuition_score)
    consensus_level, consensus_score = resolve_consensus(
        data.watcher_regime_score,
        data.watcher_risk_score,
        data.watcher_venue_score,
    )

    primary = ActionKind.HOLD
    fallback = ActionKind.REDUCE25
    why_bits: list[str] = []

    if data.venue_health <= POLICY["action_gate"]["block_if_venue_health_lte"]:
        primary = ActionKind.BLOCK
        fallback = ActionKind.ROUTE_CHANGE
        why_bits.append("venue weak")
    elif data.decay_pct >= POLICY["action_gate"]["route_change_if_decay_gte"]:
        primary = ActionKind.ROUTE_CHANGE
        fallback = ActionKind.REDUCE25
        why_bits.append("decay rising")
    elif intuition == IntuitionLevel.ALERT:
        primary = ActionKind.REDUCE25
        fallback = ActionKind.BLOCK
        why_bits.append("intuition alert")
    elif intuition == IntuitionLevel.UNEASY and fit in (FitTier.B, FitTier.C):
        primary = ActionKind.REDUCE25
        fallback = ActionKind.HOLD
        why_bits.append("uneasy fit")
    elif data.decay_pct >= POLICY["action_gate"]["partial30_if_decay_gte"]:
        primary = ActionKind.PARTIAL30
        fallback = ActionKind.REDUCE25
        why_bits.append("soft decay")
    else:
        why_bits.append("aligned")

    if consensus_level == ConsensusLevel.LOW:
        why_bits.append("low consensus")
    elif consensus_level == ConsensusLevel.HIGH:
        why_bits.append("watcher aligned")

    if not data.queue_top3:
        queue_top3 = [profile.next_strategy_hint]
    else:
        queue_top3 = data.queue_top3

    why_now = " · ".join(why_bits)

    return DecisionOutput(
        fit_tier=fit,
        consensus_level=consensus_level,
        consensus_score=consensus_score,
        intuition_level=intuition,
        primary_action=primary,
        fallback_action=fallback,
        why_now=why_now,
        entry_window=data.entry_window,
        next_strategy=data.next_strategy or profile.next_strategy_hint,
        queue_top3=queue_top3,
    )


def build_decision_snapshot(data: DecisionInput, resolved: DecisionOutput) -> str:
    return (
        f"{data.symbol.lower()}."
        f"{data.method.value}."
        f"{data.subtype.value}."
        f"{resolved.primary_action.value}."
        f"fit{resolved.fit_tier.value}."
        f"consensus{resolved.consensus_score}."
        f"intuition{data.intuition_score}"
    )


def build_replay_incident_key(data: DecisionInput) -> str:
    symbol = data.symbol.lower()
    recent = (data.recent_failure or "none").replace(" ", "_")
    return f"replay:{symbol}:{data.method.value}:{recent}"

# >>> H74TM8_SINGLE_PATCH_WITH_BACKUP

from typing import Any, Dict, Iterable, Optional

try:
    from .policy import h74tm8_resolve_combo, h74tm8_policy_snapshot
except Exception:
    from policy import h74tm8_resolve_combo, h74tm8_policy_snapshot

def h74tm8_resolve_trade_method(strategy: Optional[str] = None, skills: Optional[Iterable[str]] = None, cost_r: Optional[float] = 0.0, **kwargs: Any) -> Dict[str, Any]:
    result = h74tm8_resolve_combo(strategy=strategy, skills=skills, cost_r=cost_r)
    result["resolver"] = "h74tm8_resolve_trade_method"
    result["paper_execution_allowed"] = False
    result["live_execution_allowed"] = False
    result["registry_enabled"] = False
    result["order_authority"] = "blocked"
    result["execution_authority"] = "none"
    return result

def h74tm8_resolver_health() -> Dict[str, Any]:
    p = h74tm8_policy_snapshot()
    return {
        "status": "ok",
        "owner": "H74TM8_SINGLE_PATCH_WITH_BACKUP",
        "base_tp_r": p.get("base_tp_r"),
        "fallback_tp_r": p.get("fallback_tp_r"),
        "long_beam_cap_r": p.get("long_beam_cap_r"),
        "runner_allowed": p.get("runner_allowed"),
        "order_authority": "blocked",
        "execution_authority": "none",
    }
# <<< H74TM8_SINGLE_PATCH_WITH_BACKUP
