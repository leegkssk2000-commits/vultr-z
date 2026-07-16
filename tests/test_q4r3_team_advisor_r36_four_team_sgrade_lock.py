from __future__ import annotations

from canonical.teams.policy_contracts import (
    DEFENSIVE_TEAM_ACTIONS,
    ORDINARY_TEAM_ACTIONS,
    TEAM_POLICY_REGISTRY,
)
from canonical.teams.registry import TEAM_REGISTRY
from canonical.teams.router_counterfactual import REMAINING_SHARED_GAPS
from canonical.teams.sgrade_lock import (
    REQUIRED_CAPABILITIES,
    build_team_sgrade_proofs,
    validate_team_sgrade_lock_contract,
)


def proof_map():
    return {proof.team_id: proof for proof in build_team_sgrade_proofs()}


def test_contract_is_clean_and_all_four_teams_are_sgrade_ready() -> None:
    assert validate_team_sgrade_lock_contract() == ()
    proofs = build_team_sgrade_proofs()
    assert len(proofs) == 4
    assert sum(proof.sgrade_ready for proof in proofs) == 4
    assert all(proof.binding_team() == proof.team_id for proof in proofs)
    assert all(proof.capability_hits == REQUIRED_CAPABILITIES for proof in proofs)


def test_team_identities_and_main_owners_are_distinct() -> None:
    proofs = build_team_sgrade_proofs()
    assert len({(proof.mission, proof.policy_family) for proof in proofs}) == 4
    assert {proof.main_owner for proof in proofs} == {"LBot", "MBot", "OBot", "SBot"}
    assert len({TEAM_POLICY_REGISTRY[proof.team_id].eligible_regimes for proof in proofs}) == 4


def test_canonical_team_composition_is_preserved() -> None:
    for team_id, proof in proof_map().items():
        spec = TEAM_REGISTRY[team_id]
        assert proof.main_owner == spec.main
        assert proof.support_owner == spec.support
        assert set(proof.watcher_owners) == set(spec.watchers)
        assert set(proof.helper_triggers) == set(spec.helper_triggers)


def test_zbot_remains_external_non_voting_proof_watcher() -> None:
    for spec in TEAM_REGISTRY.values():
        decision_roles = {spec.main, spec.support, *spec.watchers, *spec.conditional_helpers}
        assert spec.external_proof_watcher == "ZBot"
        assert "ZBot" not in decision_roles


def test_delta_is_the_only_reserve_and_defensive_action_team() -> None:
    proofs = proof_map()
    assert proofs["DeltaTeam"].reserve_owner == "LBot"
    assert TEAM_POLICY_REGISTRY["DeltaTeam"].allowed_actions == DEFENSIVE_TEAM_ACTIONS
    for team_id in ("AlphaTeam", "BetaTeam", "GammaTeam"):
        assert proofs[team_id].reserve_owner is None
        assert TEAM_POLICY_REGISTRY[team_id].allowed_actions == ORDINARY_TEAM_ACTIONS


def test_all_team_surfaces_remain_advisory_only() -> None:
    for proof in build_team_sgrade_proofs():
        assert proof.authority == "advisory_only"
        assert proof.runtime_enabled is False
        assert proof.execution_authority == "none"
    for spec in TEAM_REGISTRY.values():
        assert spec.runtime_enabled is False
        assert spec.paper_enabled is False
        assert spec.live_enabled is False
        assert spec.order_enabled is False
        assert spec.execution_authority == "none"


def test_final_shared_gap_set_is_empty() -> None:
    assert REMAINING_SHARED_GAPS == ()
