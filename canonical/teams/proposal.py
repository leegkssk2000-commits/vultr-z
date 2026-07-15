from __future__ import annotations

import hashlib
from dataclasses import dataclass

from canonical.bots.contracts import BotResponse
from canonical.performance import AttributionEnvelope, ComponentRef
from .binding import BOT_CLASS_REGISTRY, BoundBotRequest, TeamBindingPlan

TEAM_PROPOSAL_VERSION = "team-proposal/1.0.0"
LINEAGE_FIELDS = (
    "decision_id", "position_id", "event_id", "parent_event_id", "event_ts",
    "symbol", "side", "strategy_id", "method_id", "skill_id", "team_id",
    "data_state", "freshness_ms", "latency_ms",
)


def _id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}.{hashlib.sha256(raw).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class WatcherObservation:
    bot_id: str
    team_role: str
    action: str
    confidence: float
    abstain: bool
    veto: bool
    reason_codes: tuple[str, ...]
    trace_id: str

    @property
    def flagged(self) -> bool:
        return self.action != "hold" or self.abstain or self.veto


@dataclass(frozen=True, slots=True)
class TeamProposal:
    proposal_id: str
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
    team_id: str
    main_bot_id: str
    support_bot_id: str
    proposed_action: str
    main_action: str
    support_result: str
    watcher_observations: tuple[WatcherObservation, ...]
    helper_observation: WatcherObservation | None
    confidence: float
    abstain: bool
    veto: bool
    reason_codes: tuple[str, ...]
    attribution: AttributionEnvelope
    authority: str = "advisory_only"
    runtime_enabled: bool = False
    execution_authority: str = "none"
    contract_version: str = TEAM_PROPOSAL_VERSION



def _evaluate(bound: BoundBotRequest) -> BotResponse:
    return BOT_CLASS_REGISTRY[bound.bot_id]().evaluate(bound.request)


def _check_lineage(anchor: BotResponse, response: BotResponse) -> None:
    for field in LINEAGE_FIELDS:
        if getattr(anchor, field) != getattr(response, field):
            raise ValueError(f"TEAM_RESPONSE_LINEAGE_MISMATCH:{response.bot_id}:{field}")


def _observation(response: BotResponse) -> WatcherObservation:
    return WatcherObservation(
        bot_id=response.bot_id,
        team_role=response.team_role,
        action=response.action,
        confidence=response.confidence,
        abstain=response.abstain,
        veto=response.veto,
        reason_codes=response.reason_codes,
        trace_id=_id("bot", response.decision_id, response.team_id, response.bot_id, response.team_role),
    )


def build_team_proposal(
    plan: TeamBindingPlan,
    *,
    policy_variant_id: str = "team-core-no-advisor",
    counterfactual_cohort_id: str | None = None,
) -> TeamProposal:
    main = _evaluate(plan.main)
    support = _evaluate(plan.support)
    watchers = tuple(_evaluate(bound) for bound in plan.watch_requests)
    helper = _evaluate(plan.helper) if plan.helper is not None else None
    all_responses = (main, support, *watchers) + ((helper,) if helper is not None else ())
    for response in all_responses:
        _check_lineage(main, response)

    sbot_veto = next((response for response in all_responses if response.bot_id == "SBot" and response.veto), None)
    any_abstain = any(response.abstain for response in all_responses)
    if support.abstain:
        support_result = "abstain"
    elif support.action == main.action:
        support_result = "confirm"
    else:
        support_result = "challenge"

    reasons = list(main.reason_codes)
    reasons.extend(f"SUPPORT:{code}" for code in support.reason_codes)
    if sbot_veto is not None:
        proposed_action, confidence, abstain, veto = "block", 1.0, False, True
        reasons.extend(f"SBOT_VETO:{code}" for code in sbot_veto.reason_codes)
    elif any_abstain:
        proposed_action, confidence, abstain, veto = "hold", 0.0, True, False
        reasons.append("TEAM_ROLE_ABSTAIN_FAIL_CLOSED")
    elif support_result == "challenge":
        proposed_action, confidence, abstain, veto = "hold", 0.0, True, False
        reasons.append("SUPPORT_CHALLENGE_FAIL_CLOSED")
    else:
        proposed_action = main.action
        confidence = min(main.confidence, support.confidence)
        abstain = False
        veto = False

    proposal_id = _id("team", main.decision_id, main.position_id, main.event_id, main.team_id)
    cohort = counterfactual_cohort_id or _id("cohort", main.position_id, main.event_id)
    refs = [
        ComponentRef("strategy", main.strategy_id, "runtime-pinned", _id("strategy", main.strategy_id, main.event_id), "baseline"),
        ComponentRef("method", main.method_id, "runtime-pinned", _id("method", main.method_id, main.event_id), "baseline"),
        ComponentRef("skill", main.skill_id, "runtime-pinned", _id("skill", main.skill_id, main.event_id), "baseline"),
        ComponentRef("team", main.team_id, TEAM_PROPOSAL_VERSION, proposal_id, "observer"),
    ]
    for response in all_responses:
        refs.append(ComponentRef(
            "team_bot", response.bot_id, response.contract_version,
            _id("bot", response.decision_id, response.team_id, response.bot_id, response.team_role), "observer",
        ))
    attribution = AttributionEnvelope(
        attribution_id=_id("attr", proposal_id, policy_variant_id),
        decision_id=main.decision_id,
        position_id=main.position_id,
        event_id=main.event_id,
        strategy_id=main.strategy_id,
        method_id=main.method_id,
        skill_id=main.skill_id,
        team_id=main.team_id,
        policy_variant_id=policy_variant_id,
        counterfactual_cohort_id=cohort,
        component_refs=tuple(refs),
        dimensions={"symbol": main.symbol, "side": main.side, "data_state": main.data_state},
    )
    return TeamProposal(
        proposal_id=proposal_id,
        decision_id=main.decision_id,
        position_id=main.position_id,
        event_id=main.event_id,
        parent_event_id=main.parent_event_id,
        event_ts=main.event_ts,
        symbol=main.symbol,
        side=main.side,
        strategy_id=main.strategy_id,
        method_id=main.method_id,
        skill_id=main.skill_id,
        team_id=main.team_id,
        main_bot_id=main.bot_id,
        support_bot_id=support.bot_id,
        proposed_action=proposed_action,
        main_action=main.action,
        support_result=support_result,
        watcher_observations=tuple(_observation(item) for item in watchers),
        helper_observation=_observation(helper) if helper is not None else None,
        confidence=confidence,
        abstain=abstain,
        veto=veto,
        reason_codes=tuple(dict.fromkeys(reasons)),
        attribution=attribution,
    )
