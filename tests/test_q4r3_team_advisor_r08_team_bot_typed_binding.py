from __future__ import annotations

import pytest

from canonical.teams.binding import (
    BOT_CLASS_REGISTRY,
    TeamDecisionContext,
    build_binding_plan,
    validate_binding_registry,
)


def context(data_state: str = "FRESH") -> TeamDecisionContext:
    return TeamDecisionContext(
        decision_id="decision.1",
        position_id="position.1",
        event_id="event.1",
        parent_event_id="event.0",
        event_ts="2026-07-15T00:00:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.alpha",
        method_id="method.pullback",
        skill_id="skill.runner",
        data_state=data_state,
        freshness_ms=100,
        latency_ms=25,
        source_ids=("src:test",),
        evidence_ids=("evidence:test",),
    )


def evidence() -> dict:
    return {
        "LBot": {"trend_thesis": {}, "hold_reduce_posture": "hold", "invalidation_flags": []},
        "MBot": {"method_fit": {}, "range_state": "trend", "timing_quality": 0.8, "conflict_flags": []},
        "OBot": {"breakout_quality": 0.7, "anomaly_flags": [], "mfe_mae_context": {}},
        "SBot": {"hard_violations": [], "soft_penalties": [], "risk_state": "normal"},
    }


def test_registry_is_exact() -> None:
    assert validate_binding_registry() == ()
    assert set(BOT_CLASS_REGISTRY) == {"LBot", "MBot", "OBot", "SBot"}


@pytest.mark.parametrize("team_id", ["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"])
def test_each_team_binds_all_four_internal_bots_once(team_id: str) -> None:
    plan = build_binding_plan(team_id, context(), evidence())
    assert len(plan.voting_requests) == 4
    assert {item.bot_id for item in plan.voting_requests} == {"LBot", "MBot", "OBot", "SBot"}
    assert len({item.bot_id for item in plan.voting_requests}) == 4


def test_zbot_is_external_and_no_request_is_created() -> None:
    plan = build_binding_plan("AlphaTeam", context(), evidence())
    assert plan.external_proof_watcher == "ZBot"
    assert plan.zbot_team_vote_allowed is False
    assert "ZBot" not in {item.bot_id for item in plan.all_internal_requests}


def test_full_lineage_and_latency_are_copied_to_every_request() -> None:
    plan = build_binding_plan("GammaTeam", context(), evidence())
    for item in plan.all_internal_requests:
        request = item.request
        assert request.strategy_id == "strategy.alpha"
        assert request.method_id == "method.pullback"
        assert request.skill_id == "skill.runner"
        assert request.team_id == "GammaTeam"
        assert request.decision_id == "decision.1"
        assert request.position_id == "position.1"
        assert request.event_id == "event.1"
        assert request.parent_event_id == "event.0"
        assert request.latency_ms == 25


def test_bound_bot_response_preserves_team_role_and_full_lineage() -> None:
    plan = build_binding_plan("AlphaTeam", context(), evidence())
    for bound in plan.voting_requests:
        response = BOT_CLASS_REGISTRY[bound.bot_id]().evaluate(bound.request)
        assert response.bot_id == bound.bot_id
        assert response.team_role == bound.team_role
        assert response.team_id == "AlphaTeam"
        assert response.strategy_id == "strategy.alpha"
        assert response.method_id == "method.pullback"
        assert response.skill_id == "skill.runner"
        assert response.event_id == "event.1"
        assert response.latency_ms == 25


def test_helper_is_conditional_and_non_voting() -> None:
    plan = build_binding_plan(
        "AlphaTeam",
        context(),
        evidence(),
        helper_bot="OBot",
        helper_trigger="pullback_retest",
    )
    assert plan.helper is not None
    assert plan.helper.bot_id == "OBot"
    assert plan.helper.vote_eligible is False
    assert len(plan.voting_requests) == 4


def test_unapproved_helper_is_rejected() -> None:
    with pytest.raises(ValueError, match="HELPER_BOT_NOT_ALLOWED"):
        build_binding_plan(
            "AlphaTeam",
            context(),
            evidence(),
            helper_bot="SBot",
            helper_trigger="pullback_retest",
        )


def test_stale_state_is_propagated_for_fail_closed_bot_behavior() -> None:
    plan = build_binding_plan("BetaTeam", context("STALE"), evidence())
    assert all(item.request.data_state == "STALE" for item in plan.all_internal_requests)


def test_binding_has_no_runtime_authority() -> None:
    plan = build_binding_plan("DeltaTeam", context(), evidence())
    assert plan.runtime_enabled is False
    assert plan.execution_authority == "none"
