from canonical.teams import TEAM_REGISTRY, validate_registry


def test_registry_is_valid() -> None:
    assert validate_registry() == ()


def test_team_count_and_main_rotation() -> None:
    assert set(TEAM_REGISTRY) == {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}
    assert {spec.main for spec in TEAM_REGISTRY.values()} == {"LBot", "MBot", "OBot", "SBot"}


def test_zbot_is_external_only() -> None:
    for spec in TEAM_REGISTRY.values():
        assert spec.external_proof_watcher == "ZBot"
        assert "ZBot" not in (spec.main, spec.support, *spec.watchers)


def test_runtime_authority_is_disabled() -> None:
    for spec in TEAM_REGISTRY.values():
        assert spec.runtime_enabled is False
        assert spec.paper_enabled is False
        assert spec.live_enabled is False
        assert spec.order_enabled is False
        assert spec.execution_authority == "none"


def test_helper_is_conditional_and_non_empty() -> None:
    for spec in TEAM_REGISTRY.values():
        assert spec.conditional_helpers
        assert spec.helper_triggers
