from __future__ import annotations

from canonical.performance import PERFORMANCE_CONTRACT_VERSION
from canonical.teams.binding import TeamDecisionContext, build_binding_plan
from canonical.teams.proposal import TEAM_PROPOSAL_VERSION, build_team_proposal
from canonical.zlice import ZLICE_CONTRACT_VERSION, ZliceEvent


def context() -> TeamDecisionContext:
    return TeamDecisionContext(
        decision_id="decision.r09",
        position_id="position.r09",
        event_id="event.r09",
        parent_event_id="event.parent",
        event_ts="2026-07-15T00:00:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.trend",
        method_id="method.pullback",
        skill_id="skill.runner",
        data_state="FRESH",
        freshness_ms=10,
        latency_ms=20,
        source_ids=("src:r09",),
        evidence_ids=("evidence:r09",),
    )


def evidence(action: str = "hold") -> dict:
    return {
        "LBot": {
            "trend_thesis": "continuation", "hold_reduce_posture": action,
            "invalidation_flags": [], "suggested_action": action, "confidence": 0.8,
        },
        "MBot": {
            "method_fit": "fit", "range_state": "trend", "timing_quality": 0.9,
            "conflict_flags": [], "suggested_action": action, "confidence": 0.7,
        },
        "OBot": {
            "breakout_quality": 0.8, "anomaly_flags": [], "mfe_mae_context": {},
            "suggested_action": "hold", "confidence": 0.6,
        },
        "SBot": {
            "hard_violations": [], "soft_penalties": [], "risk_state": "normal",
            "suggested_action": "hold", "confidence": 0.9,
        },
    }


def test_team_proposal_uses_main_and_support_only_for_generic_decision() -> None:
    plan = build_binding_plan("AlphaTeam", context(), evidence())
    proposal = build_team_proposal(plan)
    assert proposal.proposed_action == "hold"
    assert proposal.main_bot_id == "LBot"
    assert proposal.support_bot_id == "MBot"
    assert proposal.support_result == "confirm"
    assert len(proposal.watcher_observations) == 2
    assert all(item.team_role.startswith("watcher_") for item in proposal.watcher_observations)
    assert proposal.contract_version == TEAM_PROPOSAL_VERSION


def test_support_challenge_fails_closed() -> None:
    value = evidence("partial30")
    value["MBot"]["suggested_action"] = "hold"
    plan = build_binding_plan("AlphaTeam", context(), value)
    proposal = build_team_proposal(plan)
    assert proposal.support_result == "challenge"
    assert proposal.proposed_action == "hold"
    assert proposal.abstain is True
    assert "SUPPORT_CHALLENGE_FAIL_CLOSED" in proposal.reason_codes


def test_sbot_hard_veto_precedes_every_role() -> None:
    value = evidence("partial30")
    value["SBot"] = {
        "hard_violations": ["SL_MISSING"], "soft_penalties": [], "risk_state": "critical",
        "suggested_action": "hold", "confidence": 0.1,
    }
    for team_id in ("AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"):
        proposal = build_team_proposal(build_binding_plan(team_id, context(), value))
        assert proposal.proposed_action == "block"
        assert proposal.veto is True
        assert proposal.confidence == 1.0


def test_helper_is_attributed_but_never_changes_generic_decision() -> None:
    plan = build_binding_plan(
        "AlphaTeam", context(), evidence(), helper_bot="OBot", helper_trigger="pullback_retest"
    )
    proposal = build_team_proposal(plan)
    assert proposal.helper_observation is not None
    assert proposal.helper_observation.bot_id == "OBot"
    assert proposal.proposed_action == "hold"


def test_attribution_is_ready_for_cross_layer_outcome_join() -> None:
    proposal = build_team_proposal(build_binding_plan("GammaTeam", context(), evidence()))
    attribution = proposal.attribution
    assert attribution.contract_version == PERFORMANCE_CONTRACT_VERSION
    assert attribution.strategy_id == "strategy.trend"
    assert attribution.method_id == "method.pullback"
    assert attribution.skill_id == "skill.runner"
    assert attribution.team_id == "GammaTeam"
    types = [item.component_type for item in attribution.component_refs]
    assert types.count("strategy") == 1
    assert types.count("method") == 1
    assert types.count("skill") == 1
    assert types.count("team") == 1
    assert types.count("team_bot") == 4
    assert attribution.policy_variant_id == "team-core-no-advisor"


def test_zlice_is_evidence_only_and_append_only() -> None:
    proposal = build_team_proposal(build_binding_plan("BetaTeam", context(), evidence()))
    event = ZliceEvent(
        event_id="zlice.event.r09",
        parent_event_id=proposal.parent_event_id,
        decision_id=proposal.decision_id,
        position_id=proposal.position_id,
        event_type="team_proposal_emitted",
        event_ts=proposal.event_ts,
        producer_id="TeamProposalAggregator",
        producer_version=proposal.contract_version,
        attribution_id=proposal.attribution.attribution_id,
        payload_hash="a" * 64,
        source_ids=("src:r09",),
        sequence_no=1,
    )
    assert event.contract_version == ZLICE_CONTRACT_VERSION
    assert event.append_only is True
    assert event.authority == "evidence_only"
    assert event.execution_authority == "none"
