from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple

BotName = Literal["LBot", "MBot", "OBot", "SBot"]
TeamName = Literal["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"]


@dataclass(frozen=True, slots=True)
class TeamSpec:
    team_id: TeamName
    mission: str
    main: BotName
    support: BotName
    watchers: Tuple[BotName, BotName]
    external_proof_watcher: Literal["ZBot"]
    conditional_helpers: Tuple[BotName, ...]
    helper_triggers: Tuple[str, ...]
    reserve: BotName | None = None
    contract_version: str = "team-canonical/1.0.0"
    runtime_enabled: bool = False
    paper_enabled: bool = False
    live_enabled: bool = False
    order_enabled: bool = False
    execution_authority: Literal["none"] = "none"

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.main == self.support:
            errors.append("MAIN_SUPPORT_COLLISION")
        if len(self.watchers) != 2 or len(set(self.watchers)) != 2:
            errors.append("WATCHER_SET_INVALID")
        if self.main in self.watchers or self.support in self.watchers:
            errors.append("ROLE_DUPLICATION")
        if not self.conditional_helpers:
            errors.append("HELPER_SET_EMPTY")
        if not self.helper_triggers:
            errors.append("HELPER_TRIGGER_SET_EMPTY")
        if self.external_proof_watcher != "ZBot":
            errors.append("EXTERNAL_PROOF_WATCHER_INVALID")
        if self.runtime_enabled or self.paper_enabled or self.live_enabled or self.order_enabled:
            errors.append("RUNTIME_AUTHORITY_ENABLED")
        if self.execution_authority != "none":
            errors.append("EXECUTION_AUTHORITY_INVALID")
        return tuple(errors)
