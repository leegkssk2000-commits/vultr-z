from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from canonical.bots import LBot, MBot, OBot, SBot
from canonical.bots.contracts import BotRequest
from .registry import TEAM_REGISTRY

BOT_CLASS_REGISTRY = MappingProxyType({
    "LBot": LBot,
    "MBot": MBot,
    "OBot": OBot,
    "SBot": SBot,
})


@dataclass(frozen=True, slots=True)
class TeamDecisionContext:
    decision_id: str
    position_id: str
    event_id: str
    parent_event_id: str
    event_ts: str
    symbol: str
    side: str
    strategy_id: str
    method_id: str
    skill_id: str
    data_state: str
    freshness_ms: int
    source_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class BoundBotRequest:
    bot_id: str
    team_role: str
    vote_eligible: bool
    request: BotRequest


@dataclass(frozen=True, slots=True)
class TeamBindingPlan:
    team_id: str
    main: BoundBotRequest
    support: BoundBotRequest
    watchers: tuple[BoundBotRequest, BoundBotRequest]
    helper: BoundBotRequest | None
    helper_trigger: str | None
    external_proof_watcher: str = "ZBot"
    zbot_team_vote_allowed: bool = False
    runtime_enabled: bool = False
    execution_authority: str = "none"

    @property
    def voting_requests(self) -> tuple[BoundBotRequest, ...]:
        return (self.main, self.support, *self.watchers)

    @property
    def all_internal_requests(self) -> tuple[BoundBotRequest, ...]:
        return self.voting_requests + ((self.helper,) if self.helper else ())


def _request(
    context: TeamDecisionContext,
    *,
    team_id: str,
    bot_id: str,
    team_role: str,
    role_evidence: Mapping[str, Any],
) -> BotRequest:
    return BotRequest(
        decision_id=context.decision_id,
        position_id=context.position_id,
        event_id=context.event_id,
        parent_event_id=context.parent_event_id,
        event_ts=context.event_ts,
        symbol=context.symbol,
        side=context.side,
        strategy_id=context.strategy_id,
        method_id=context.method_id,
        skill_id=context.skill_id,
        team_id=team_id,
        team_role=team_role,
        data_state=context.data_state,
        freshness_ms=context.freshness_ms,
        role_evidence=role_evidence,
        source_ids=context.source_ids,
        evidence_ids=context.evidence_ids,
    )


def build_binding_plan(
    team_id: str,
    context: TeamDecisionContext,
    evidence_by_bot: Mapping[str, Mapping[str, Any]],
    *,
    helper_bot: str | None = None,
    helper_trigger: str | None = None,
) -> TeamBindingPlan:
    if team_id not in TEAM_REGISTRY:
        raise ValueError("TEAM_ID_INVALID")
    spec = TEAM_REGISTRY[team_id]
    if spec.validate():
        raise ValueError(f"TEAM_SPEC_INVALID:{','.join(spec.validate())}")

    def bound(bot_id: str, role: str, *, vote_eligible: bool) -> BoundBotRequest:
        if bot_id not in BOT_CLASS_REGISTRY:
            raise ValueError(f"BOT_ID_INVALID:{bot_id}")
        evidence = evidence_by_bot.get(bot_id)
        if evidence is None:
            evidence = {}
        return BoundBotRequest(
            bot_id=bot_id,
            team_role=role,
            vote_eligible=vote_eligible,
            request=_request(
                context,
                team_id=team_id,
                bot_id=bot_id,
                team_role=role,
                role_evidence=evidence,
            ),
        )

    helper: BoundBotRequest | None = None
    if helper_bot is not None or helper_trigger is not None:
        if not helper_bot or not helper_trigger:
            raise ValueError("HELPER_BOT_AND_TRIGGER_REQUIRED")
        if helper_bot not in spec.conditional_helpers:
            raise ValueError("HELPER_BOT_NOT_ALLOWED")
        if helper_trigger not in spec.helper_triggers:
            raise ValueError("HELPER_TRIGGER_NOT_ALLOWED")
        helper = bound(helper_bot, "conditional_helper", vote_eligible=False)

    return TeamBindingPlan(
        team_id=team_id,
        main=bound(spec.main, "main", vote_eligible=True),
        support=bound(spec.support, "support", vote_eligible=True),
        watchers=(
            bound(spec.watchers[0], "watcher_1", vote_eligible=True),
            bound(spec.watchers[1], "watcher_2", vote_eligible=True),
        ),
        helper=helper,
        helper_trigger=helper_trigger,
        external_proof_watcher=spec.external_proof_watcher,
    )


def validate_binding_registry() -> tuple[str, ...]:
    errors: list[str] = []
    if set(BOT_CLASS_REGISTRY) != {"LBot", "MBot", "OBot", "SBot"}:
        errors.append("BOT_CLASS_REGISTRY_INVALID")
    for team_id, spec in TEAM_REGISTRY.items():
        role_bots = (spec.main, spec.support, *spec.watchers)
        if len(role_bots) != 4 or set(role_bots) != {"LBot", "MBot", "OBot", "SBot"}:
            errors.append(f"{team_id}:FOUR_BOT_ROLE_COVERAGE_INVALID")
        if spec.external_proof_watcher != "ZBot":
            errors.append(f"{team_id}:ZBOT_EXTERNAL_POLICY_INVALID")
    return tuple(errors)
