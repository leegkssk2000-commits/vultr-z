from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: float
    ts: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Strategy(Protocol):
    name: str

    def compute_target_size(
        self,
        state: Any,
        position: Any | None,
        snapshot: MarketSnapshot,
    ) -> float:
        ...
