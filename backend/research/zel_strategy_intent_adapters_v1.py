"""Thin research adapters for strategy-kernel parity checks.

Both adapters call the same strategy-policy SSOT and return the unchanged
DecisionIntent hash. They do not model fills, mutate risk geometry, or create
orders. Economic replay remains blocked until the feature-contribution gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.research.zel_feature_strategy_ssot_v1 import (
    Bar,
    DecisionIntent,
    StrategyConfig,
    decide_momentum_long,
)

AdapterName = Literal["REPLAY_DRY_RUN", "PAPER_DRY_RUN"]


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    regime_15m: tuple[Bar, ...]
    setup_5m: tuple[Bar, ...]
    all_in_cost_pct: float


@dataclass(frozen=True)
class AdapterReceipt:
    adapter: AdapterName
    intent: DecisionIntent
    intent_sha256: str
    execution_model: str
    economic_projection_allowed: bool
    execution_authority: str
    order_authority: str


def _run(adapter: AdapterName, snapshot: MarketSnapshot, config: StrategyConfig) -> AdapterReceipt:
    intent = decide_momentum_long(
        snapshot.symbol,
        snapshot.regime_15m,
        snapshot.setup_5m,
        config,
        snapshot.all_in_cost_pct,
    )
    return AdapterReceipt(
        adapter=adapter,
        intent=intent,
        intent_sha256=intent.sha256(),
        execution_model="NO_FILL_DRY_RUN",
        economic_projection_allowed=False,
        execution_authority="NONE",
        order_authority="BLOCKED",
    )


def replay_dry_run(snapshot: MarketSnapshot, config: StrategyConfig) -> AdapterReceipt:
    return _run("REPLAY_DRY_RUN", snapshot, config)


def paper_dry_run(snapshot: MarketSnapshot, config: StrategyConfig) -> AdapterReceipt:
    return _run("PAPER_DRY_RUN", snapshot, config)


__all__ = [
    "MarketSnapshot",
    "AdapterReceipt",
    "replay_dry_run",
    "paper_dry_run",
]
