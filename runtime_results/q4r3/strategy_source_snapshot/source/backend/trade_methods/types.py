from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


class TradeMethod(StrEnum):
    SCALP_FIRST = "scalp_first"
    INTRADAY = "intraday"
    TACTICAL_SWING = "tactical_swing"
    BLOCKED = "blocked"


class ScalpSubtype(StrEnum):
    REVERT = "revert"
    CONTINUATION = "continuation"
    LIQUIDITY_RECLAIM = "liquidity_reclaim"
    BREAKOUT_PROBE = "breakout_probe"
    RESCUE = "rescue"


class FitTier(StrEnum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"


class IntuitionLevel(StrEnum):
    CALM = "calm"
    UNEASY = "uneasy"
    ALERT = "alert"


class ActionKind(StrEnum):
    REDUCE25 = "reduce25"
    PARTIAL30 = "partial30"
    HOLD = "hold"
    STOP = "stop"
    ROUTE_CHANGE = "route_change"
    ROLLBACK = "rollback"
    BLOCK = "block"


class ConsensusLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


EntryStyle = Literal["pullback_confirm", "break_reclaim", "range_revert", "observe_then_confirm"]
HoldHorizon = Literal["3-15m", "10-45m", "2-6h", "blocked"]


@dataclass(slots=True)
class MethodProfile:
    method: TradeMethod
    subtype: ScalpSubtype
    label: str
    entry_style: EntryStyle
    hold_horizon: HoldHorizon
    rescue_observe: str
    next_strategy_hint: str


@dataclass(slots=True)
class DecisionInput:
    symbol: str
    pair_confidence: int
    watcher_regime_score: int
    watcher_risk_score: int
    watcher_venue_score: int
    intuition_score: int
    decay_pct: float
    venue_health: int
    method: TradeMethod
    subtype: ScalpSubtype
    recent_failure: str = "none"
    helper_active: bool = False
    entry_window: str = "Next 15m"
    next_strategy: str = "BTC Trend v1"
    queue_top3: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DecisionOutput:
    fit_tier: FitTier
    consensus_level: ConsensusLevel
    consensus_score: int
    intuition_level: IntuitionLevel
    primary_action: ActionKind
    fallback_action: ActionKind
    why_now: str
    entry_window: str
    next_strategy: str
    queue_top3: list[str]

# >>> H74TM8_SINGLE_PATCH_WITH_BACKUP

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

@dataclass(frozen=True)
class H74TM8ComboDecision:
    decision: str
    action: str
    size_multiplier: float
    target_r: Any
    reason: str
    source: str = "H74TM8"

H74TM8_DECISION_ALLOW_FULL = "ALLOW_FULL_BASE25"
H74TM8_DECISION_ALLOW_POLICY = "ALLOW_POLICY"
H74TM8_DECISION_WATCH = "WATCH_COMBO"
H74TM8_DECISION_BLOCK = "BLOCK_COMBO"
H74TM8_ACTION_HOLD = "hold"
H74TM8_ACTION_BLOCK = "block"
# <<< H74TM8_SINGLE_PATCH_WITH_BACKUP
