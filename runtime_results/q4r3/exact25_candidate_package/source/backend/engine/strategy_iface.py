from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol, runtime_checkable

from .risk_engine import AccountState, Position


@dataclass
class MarketSnapshot:
    symbol: str
    price: float
    ts: float  # epoch seconds
    extra: Dict[str, Any] | None = None  # 지표/추가 메타


@runtime_checkable
class Strategy(Protocol):
    """
    모든 전략이 만족해야 하는 최소 인터페이스.
    - 코어 루프는 이 인터페이스만 보고 동작.
    """

    name: str

    def compute_target_size(
        self,
        state: AccountState,
        position: Position | None,
        snapshot: MarketSnapshot,
    ) -> float:
        """
        계정 상태 + 현재 포지션 + 마켓 스냅샷 →
        목표 순 포지션(계약 수) 반환.
        - >0 : 순 LONG
        - <0 : 순 SHORT
        - 0 : 포지션 없음
        """
        ...


__all__ = [
    "MarketSnapshot",
    "Strategy",
]