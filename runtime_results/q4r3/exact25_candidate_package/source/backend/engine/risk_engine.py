from __future__ import annotations

from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Position:
    symbol: str = ""
    side: str = "long"
    qty: float = 0.0
    entry_price: float = 0.0
    mark_price: float = 0.0
    pnl_unrealized: float = 0.0
    strategy: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> float:
        return float(self.qty)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AccountState:
    equity: float = 0.0
    balance: float = 0.0
    positions: List[Position] = field(default_factory=list)
    realized_pnl_day: float = 0.0
    max_drawdown_day: float = 0.0
    open_orders_margin: float = 0.0
    exchange: str = ""

    # runtime-safe legacy/new fields
    daily_pnl_usdt: float = 0.0
    total_exposure_usdt: float = 0.0
    total_unrealized_pnl_usdt: float = 0.0

    @property
    def equity_usdt(self) -> float:
        return float(self.equity)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PositionSnapshot:
    account_state: Optional[AccountState] = None
    positions: List[Position] = field(default_factory=list)
    ts: float = 0.0
    exchange: str = ""
    account_id: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskLimits:
    max_exposure_pct: float = 1.0
    soft_exposure_pct: float = 0.7
    max_daily_loss_pct: float = 0.05
    max_unrealized_dd_pct: float = 0.10
    min_equity_usdt: float = 50.0


@dataclass
class RiskDecision:
    level: str
    reasons: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    recommended: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RiskEngine:
    def __init__(self, limits: Optional[RiskLimits] = None) -> None:
        self._limits = limits or RiskLimits()

    def _base_decision(self) -> RiskDecision:
        return RiskDecision(
            level="OK",
            reasons=[],
            metrics={},
            recommended=["hold"],
        )

    def eval_snapshot(self, snapshot: PositionSnapshot) -> Dict[str, Any]:
        decision = self._base_decision()

        acc_state = snapshot.account_state
        if acc_state is None:
            decision.level = "BLOCK"
            decision.reasons.append("no_account_state")
            decision.recommended = ["block"]
            return decision.to_dict()

        eq = float(acc_state.equity_usdt)
        daily_pnl = float(acc_state.daily_pnl_usdt)

        if float(acc_state.total_exposure_usdt or 0.0) > 0:
            total_exposure = float(acc_state.total_exposure_usdt)
        else:
            total_exposure = 0.0
            for p in snapshot.positions or acc_state.positions or []:
                qty = abs(float(getattr(p, "qty", 0.0) or 0.0))
                mark = float(getattr(p, "mark_price", 0.0) or getattr(p, "entry_price", 0.0) or 0.0)
                total_exposure += qty * mark

        if float(acc_state.total_unrealized_pnl_usdt or 0.0) != 0.0:
            total_unrealized = float(acc_state.total_unrealized_pnl_usdt)
        else:
            total_unrealized = 0.0
            for p in snapshot.positions or acc_state.positions or []:
                total_unrealized += float(getattr(p, "pnl_unrealized", 0.0) or 0.0)

        if eq > 0:
            exposure_pct = total_exposure / eq
            daily_pnl_pct = daily_pnl / eq
            unrealized_dd_pct = max(0.0, -total_unrealized / eq) if total_unrealized < 0 else 0.0
        else:
            exposure_pct = 0.0
            daily_pnl_pct = 0.0
            unrealized_dd_pct = 0.0

        decision.metrics = {
            "equity_usdt": eq,
            "daily_pnl_usdt": daily_pnl,
            "total_exposure_usdt": total_exposure,
            "total_unrealized_pnl_usdt": total_unrealized,
            "exposure_pct": exposure_pct,
            "daily_pnl_pct": daily_pnl_pct,
            "unrealized_dd_pct": unrealized_dd_pct,
        }

        if eq <= 0:
            decision.level = "BLOCK"
            decision.reasons.append("no_equity")
            decision.recommended = ["block"]
            return decision.to_dict()

        if eq < self._limits.min_equity_usdt:
            decision.level = "BLOCK"
            decision.reasons.append("min_equity_breached")
            decision.recommended = ["stop"]
            return decision.to_dict()

        if daily_pnl_pct <= -self._limits.max_daily_loss_pct:
            decision.level = "BLOCK"
            decision.reasons.append("daily_loss_limit")
            decision.recommended = ["stop"]

        if unrealized_dd_pct >= self._limits.max_unrealized_dd_pct:
            if decision.level != "BLOCK":
                decision.level = "WARN"
                decision.recommended = ["reduce25"]
            decision.reasons.append("unrealized_dd_limit")

        if exposure_pct >= self._limits.max_exposure_pct * 1.5:
            decision.level = "BLOCK"
            decision.reasons.append("over_exposure_hard")
            decision.recommended = ["reduce25"]
        elif exposure_pct >= self._limits.max_exposure_pct:
            if decision.level != "BLOCK":
                decision.level = "WARN"
            if "over_exposure_soft" not in decision.reasons:
                decision.reasons.append("over_exposure_soft")
            if "stop" not in decision.recommended and "reduce25" not in decision.recommended:
                decision.recommended.append("reduce25")
        elif exposure_pct >= self._limits.soft_exposure_pct:
            if decision.level == "OK":
                decision.level = "WARN"
            if "near_exposure_limit" not in decision.reasons:
                decision.reasons.append("near_exposure_limit")
            if "reduce25" not in decision.recommended:
                decision.recommended.append("reduce25")

        decision.recommended = list(dict.fromkeys(decision.recommended))
        return decision.to_dict()


def evaluate_risk(snapshot: PositionSnapshot, limits: Optional[RiskLimits] = None) -> Dict[str, Any]:
    return RiskEngine(limits=limits).eval_snapshot(snapshot)


__all__ = [
    "Side",
    "Position",
    "AccountState",
    "PositionSnapshot",
    "RiskLimits",
    "RiskDecision",
    "RiskEngine",
    "evaluate_risk",
]
