from __future__ import annotations

from canonical.bots.contracts import ALLOWED_ACTIONS
from canonical.teams.policy_contracts import (
    CANONICAL_SOURCES,
    DEFENSIVE_TEAM_ACTIONS,
    ORDINARY_TEAM_ACTIONS,
    TEAM_POLICY_REGISTRY,
    TEAM_POLICY_VERSION,
    validate_team_policy_registry,
)
from canonical.teams.registry import TEAM_REGISTRY


def test_team_policy_registry_is_complete_and_valid() -> None:
    assert validate_team_policy_registry() == ()
    assert set(TEAM_POLICY_REGISTRY) == set(TEAM_REGISTRY)
    assert len(TEAM_POLICY_REGISTRY) == 4


def test_each_team_has_a_distinct_policy_identity() -> None:
    identities = {
        (policy.policy_family, policy.primary_objective, policy.eligible_regimes)
        for policy in TEAM_POLICY_REGISTRY.values()
    }
    assert len(identities) == 4
    assert {policy.main_owner for policy in TEAM_POLICY_REGISTRY.values()} == {"LBot", "MBot", "OBot", "SBot"}


def test_team_contracts_remain_advisory_and_source_bound() -> None:
    for policy in TEAM_POLICY_REGISTRY.values():
        assert policy.threshold_source_prefixes == CANONICAL_SOURCES
        assert policy.authority == "advisory_only"
        assert policy.runtime_enabled is False
        assert policy.execution_authority == "none"
        assert policy.contract_version == TEAM_POLICY_VERSION
        assert policy.helper_trigger_map
        assert policy.watcher_priorities


def test_action_authority_is_separated_by_team_mission() -> None:
    for team_id, policy in TEAM_POLICY_REGISTRY.items():
        if team_id == "DeltaTeam":
            assert policy.allowed_actions == DEFENSIVE_TEAM_ACTIONS == frozenset(ALLOWED_ACTIONS)
            assert policy.reserve_owner == "LBot"
            assert {"rollback", "stop", "block"} <= set(policy.recovery_routes)
        else:
            assert policy.allowed_actions == ORDINARY_TEAM_ACTIONS
            assert not ({"rollback", "stop", "block"} & set(policy.allowed_actions))


def test_policy_contracts_cover_the_r31_team_specific_gaps() -> None:
    assert TEAM_POLICY_REGISTRY["AlphaTeam"].policy_family == "trend_continuation"
    assert "pullback_retest" in TEAM_POLICY_REGISTRY["AlphaTeam"].helper_trigger_map
    assert "trend" in TEAM_POLICY_REGISTRY["AlphaTeam"].eligible_regimes

    assert TEAM_POLICY_REGISTRY["BetaTeam"].policy_family == "range_mean_reversion"
    assert "range_extreme" in TEAM_POLICY_REGISTRY["BetaTeam"].helper_trigger_map
    assert "range" in TEAM_POLICY_REGISTRY["BetaTeam"].eligible_regimes

    assert TEAM_POLICY_REGISTRY["GammaTeam"].policy_family == "breakout_acceleration"
    assert "retest_required" in TEAM_POLICY_REGISTRY["GammaTeam"].helper_trigger_map
    assert "breakout" in TEAM_POLICY_REGISTRY["GammaTeam"].eligible_regimes

    assert TEAM_POLICY_REGISTRY["DeltaTeam"].policy_family == "capital_preservation"
    assert "recovery_route" in TEAM_POLICY_REGISTRY["DeltaTeam"].helper_trigger_map
    assert TEAM_POLICY_REGISTRY["DeltaTeam"].recovery_routes
