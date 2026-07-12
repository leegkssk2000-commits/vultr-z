from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LBotMode(str, Enum):
    DUMMY = "dummy"
    SHADOW = "shadow"
    LIVE = "live"


class LBotRoute(str, Enum):
    NOOP = "noop"
    PAPER = "paper"
    EXCHANGE = "exchange"


class StrategyIntent(str, Enum):
    HOLD = "hold"
    ENTER_LONG = "enter_long"
    EXIT_LONG = "exit_long"
    REDUCE = "reduce"
    BLOCK = "block"


@dataclass
class SignalInput:
    signal_id: str
    symbol: str
    strategy: str
    side: str = "long"
    price: float = 0.0
    ts: int = 0
    timeframe: str = ""
    source: str = "signal"
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountSnapshot:
    exchange: str = "bingx"
    equity: float = 0.0
    balance: float = 0.0
    available: float = 0.0
    used_margin: float = 0.0
    positions_count: int = 0
    trades_count: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskSnapshot:
    ok: bool = True
    action: str = "hold"
    severity: str = "ok"
    reason: str = ""
    violations: List[Dict[str, Any]] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionContext:
    mode: LBotMode
    route: LBotRoute
    signal: SignalInput
    account: AccountSnapshot
    risk: RiskSnapshot
    sync_state: Dict[str, Any] = field(default_factory=dict)
    journal_summary: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyDecision:
    ok: bool
    intent: StrategyIntent
    confidence: float = 0.0
    reason: str = ""
    target_qty: float = 0.0
    target_price: float = 0.0
    tags: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CoreDecision:
    ok: bool
    mode: str
    route: str
    strategy: str
    symbol: str
    intent: str
    gated: bool
    gate_reason: str
    confidence: float
    executor_status: str
    executor_result: Dict[str, Any] = field(default_factory=dict)
    strategy_reason: str = ""
    risk_action: str = "hold"
    risk_severity: str = "ok"
    trace_id: str = ""
    replay_key: str = ""
    journal_event: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)