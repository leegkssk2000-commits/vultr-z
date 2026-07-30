from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountState:
    equity: float = 0.0
    available_balance: float = 0.0
    day_drawdown_pct: float = 0.0
    total_drawdown_pct: float = 0.0


@dataclass(frozen=True)
class Position:
    symbol: str = ""
    quantity: float = 0.0
    avg_entry: float = 0.0
    side: str = ""
