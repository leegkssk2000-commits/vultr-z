from __future__ import annotations

from pathlib import Path

from canonical.teams.binding import validate_binding_registry
from canonical.teams.registry import TEAM_REGISTRY, validate_registry


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MISS = (
    "policies.py", "regime.py", "assignment.py", "helpers.py", "watcher.py",
    "failover.py", "confidence.py", "router.py", "counterfactual.py",
)


def test_team_foundation_is_valid_before_sgrade_upgrade() -> None:
    assert validate_registry() == ()
    assert validate_binding_registry() == ()
    assert set(TEAM_REGISTRY) == {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}
    assert len({spec.mission for spec in TEAM_REGISTRY.values()}) == 4
    for spec in TEAM_REGISTRY.values():
        assert set((spec.main, spec.support, *spec.watchers)) == {"LBot", "MBot", "OBot", "SBot"}
        assert spec.execution_authority == "none"
        assert spec.runtime_enabled is False


def test_current_team_engine_is_not_falsely_promoted_to_sgrade() -> None:
    team_dir = ROOT / "canonical/teams"
    missing = [name for name in EXPECTED_MISS if not (team_dir / name).is_file()]
    assert missing == list(EXPECTED_MISS)


def test_current_common_aggregator_has_known_sgrade_gaps() -> None:
    binding = (ROOT / "canonical/teams/binding.py").read_text(encoding="utf-8")
    proposal = (ROOT / "canonical/teams/proposal.py").read_text(encoding="utf-8")
    assert "spec.reserve" not in binding
    assert "severity" not in proposal.lower()
    assert "min(main.confidence, support.confidence)" in proposal
    assert "SUPPORT_CHALLENGE_FAIL_CLOSED" in proposal
