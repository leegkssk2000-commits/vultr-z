from __future__ import annotations

from abc import ABC, abstractmethod

from .lbot_models import DecisionContext, StrategyDecision


class LBotStrategyBase(ABC):
    strategy_name: str = "base_strategy"

    @abstractmethod
    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        raise NotImplementedError

