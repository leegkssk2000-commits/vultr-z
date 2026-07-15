from __future__ import annotations

import pytest

from canonical.teams.binding import ROLE_AUTHORITY_VERSION, TeamDecisionContext, build_binding_plan


def context() -> TeamDecisionContext:
    return TeamDecisionContext(
        decision_id="decision.r082",
        position_id="position.r082",
        event_id="event.r082",
        parent_event_id="event.parent",
        event_ts="2026-07-15T00:00:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.r082",
        method_id="method.r082",
        skill_id="skill.r082",
        data_state="FRESH",
        freshness_ms=10,
        latency_ms=20,
    )


def evidence() -> dict:
    return {
        "LBot": {"trend_thesis": {}, "hold_reduce_posture": "hold", "invalidation_flags": []},
        "MBot": {"method_fit": {}, "range_state": "trend", "timing_quality": 0.8, "conflict_flags": []},
        "OBot": {"breakout_quality": 0.8, "anomaly_flags": [], "mfe_mae_context": {}},
        "SBot": {"hard_violations": [], "soft_penalties": [], "risk_state": "normal"},
    }


@pytest.mark.parametrize("team_id", ["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"])
def test_main_support_watchers_are_not_equal_votes(team_id: str) -> None:
    plan = build_binding_plan(team_id, context(), evidence())
    assert ROLE_AUTHORITY_VERSION == "team-binding/1.1.0"
    assert len(plan.decision_requests) == 2
    assert len(plan.watch_requests) == 2
    assert plan.main.proposal_owner is True
    assert plan.support.support_validator is True
    assert all(item.watch_only for item in plan.watch_requests)
    assert all(not item.generic_vote_eligible for item in plan.watch_requests)
    assert {item.bot_id for item in plan.all_internal_requests} == {"LBot", "MBot", "OBot", "SBot"}


@pytest.mark.parametrize("team_id", ["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"])
def test_sbot_hard_veto_capability_survives_any_team_role(team_id: str) -> None:
    plan = build_binding_plan(team_id, context(), evidence())
    sbot = next(item for item in plan.all_internal_requests if item.bot_id == "SBot")
    assert sbot.hard_veto_capable is True


def test_helper_is_conditional_and_never_generic_vote() -> None:
    plan = build_binding_plan(
        "GammaTeam",
        context(),
        evidence(),
        helper_bot="LBot",
        helper_trigger="volume_expansion",
    )
    assert plan.helper is not None
    assert plan.helper.helper_only is True
    assert plan.helper.generic_vote_eligible is False
    assert plan.helper.proposal_owner is False
    assert plan.helper.support_validator is False
    assert plan.helper.watch_only is False
