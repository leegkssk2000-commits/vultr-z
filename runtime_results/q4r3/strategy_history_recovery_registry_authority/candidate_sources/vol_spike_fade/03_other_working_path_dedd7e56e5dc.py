from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Archetype(str, Enum):
    TREND_CONTINUATION = "trend_continuation"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    LIQUIDITY_RECLAIM = "liquidity_reclaim"
    RANGE_FADE = "range_fade"
    META_ROUTER = "meta_router"


class Regime(str, Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    SQUEEZE = "squeeze"
    BREAKOUT = "breakout"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


@dataclass
class LegendaryContext:
    symbol: str
    price: float
    regime: Regime = Regime.UNKNOWN
    htf_regime: Regime = Regime.UNKNOWN
    atr_pct: float = 0.0
    adx: float = 0.0
    volume_z: float = 0.0
    vwap_dev_atr: float = 0.0
    funding_8h_pct: float = 0.0
    oi_6h_pct: float = 0.0
    spread_bps: float = 0.0
    stale_ms: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradePlan:
    strategy: str
    archetype: Archetype
    side: Optional[str]
    action: str
    entry: float
    sl: float
    tp: float
    confidence: float
    reason: str
    required_regimes: List[Regime] = field(default_factory=list)
    invalidation: str = ""
    tags: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GateResult:
    accepted: bool
    reasons: List[str]
    rr: float = 0.0
    risk: float = 0.0
    reward: float = 0.0


MIN_RR = 1.45
MIN_CONFIDENCE = 0.62
MAX_SPREAD_BPS = 8.0
MAX_STALE_MS = 5000


def rr_of(plan: TradePlan) -> tuple[float, float, float]:
    if plan.side == "long":
        risk = max(plan.entry - plan.sl, 0.0)
        reward = max(plan.tp - plan.entry, 0.0)
    elif plan.side == "short":
        risk = max(plan.sl - plan.entry, 0.0)
        reward = max(plan.entry - plan.tp, 0.0)
    else:
        return 0.0, 0.0, 0.0
    rr = reward / risk if risk > 0 else 0.0
    return rr, risk, reward


def legendary_gate(ctx: LegendaryContext, plan: TradePlan) -> GateResult:
    reasons: List[str] = []

    if plan.action not in {"enter", "add", "hold", "reduce", "block"}:
        reasons.append("invalid_action")

    if plan.action in {"enter", "add"}:
        if plan.side not in {"long", "short"}:
            reasons.append("side_missing")
        if plan.entry <= 0 or plan.sl <= 0 or plan.tp <= 0:
            reasons.append("entry_sl_tp_missing")
        if plan.confidence < MIN_CONFIDENCE:
            reasons.append("confidence_low")
        if ctx.stale_ms > MAX_STALE_MS:
            reasons.append("data_stale")
        if ctx.spread_bps > MAX_SPREAD_BPS:
            reasons.append("spread_too_wide")
        if plan.required_regimes and ctx.regime not in plan.required_regimes and ctx.htf_regime not in plan.required_regimes:
            reasons.append("regime_mismatch")

        rr, risk, reward = rr_of(plan)
        if rr < MIN_RR:
            reasons.append("rr_below_min")
        if risk <= 0 or reward <= 0:
            reasons.append("invalid_risk_reward")
    else:
        rr, risk, reward = 0.0, 0.0, 0.0

    return GateResult(accepted=(len(reasons) == 0), reasons=reasons, rr=rr, risk=risk, reward=reward)
