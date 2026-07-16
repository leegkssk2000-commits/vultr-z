from __future__ import annotations

import pytest

from canonical.teams.policy_contracts import TEAM_POLICY_REGISTRY
from canonical.teams.role_engine import (
    REMAINING_SHARED_GAPS,
    RoleAssignmentRequest,
    assign_team_roles,
    validate_role_engine_contract,
)

SOURCES = ("cf:r33", "sheets:r33")
EVIDENCE = ("evidence:r33",)


def request(team_id: str, **kwargs: object) -> RoleAssignmentRequest:
    return RoleAssignmentRequest(
        team_id=team_id,  # type: ignore[arg-type]
        regime=str(kwargs.pop("regime", "test_regime")),
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        evidence_ids=kwargs.pop("evidence_ids", EVIDENCE),  # type: ignore[arg-type]
        **kwargs,
    )


def test_contract_registry_is_clean() -> None:
    assert validate_role_engine_contract() == ()
    assert len(TEAM_POLICY_REGISTRY) == 4
    assert len(REMAINING_SHARED_GAPS) == 5


@pytest.mark.parametrize("team_id", sorted(TEAM_POLICY_REGISTRY))
def test_canonical_assignment_is_ready(team_id: str) -> None:
    policy = TEAM_POLICY_REGISTRY[team_id]
    plan = assign_team_roles(request(team_id))
    assert plan.decision_ready is True
    assert plan.fail_closed is False
    assert plan.mode == "canonical"
    assert plan.effective_main == policy.main_owner
    assert plan.effective_support == policy.support_owner
    assert set(plan.active_watchers) == set(policy.watcher_priorities)
    assert plan.helper is None
    assert plan.action == "hold"
    assert plan.authority == "advisory_only"
    assert plan.runtime_enabled is False
    assert plan.execution_authority == "none"


@pytest.mark.parametrize(
    ("team_id", "trigger", "helper"),
    (
        ("AlphaTeam", "pullback_retest", "MBot"),
        ("BetaTeam", "fake_breakout", "OBot"),
        ("GammaTeam", "retest_required", "MBot"),
        ("DeltaTeam", "recovery_route", "OBot"),
    ),
)
def test_helper_is_activated_by_team_contract(team_id: str, trigger: str, helper: str) -> None:
    plan = assign_team_roles(request(team_id, active_triggers=(trigger,)))
    assert plan.decision_ready is True
    assert plan.mode == "helper_assisted"
    assert plan.helper_trigger == trigger
    assert plan.helper == helper
    assert plan.binding_helper() == (helper, trigger)


def test_multiple_helper_triggers_are_deterministic() -> None:
    plan = assign_team_roles(
        request("AlphaTeam", active_triggers=("method_conflict", "pullback_retest"))
    )
    assert plan.decision_ready is True
    assert plan.helper_trigger == "pullback_retest"
    assert plan.helper == "MBot"
    assert "ROLE_MULTIPLE_HELPER_TRIGGERS_PRIORITIZED" in plan.reason_codes


@pytest.mark.parametrize(
    ("source_ids", "reason"),
    (
        (("cf:r33",), "ROLE_CF_SHEETS_PARITY_MISSING"),
        (("sheets:r33",), "ROLE_CF_SHEETS_PARITY_MISSING"),
        (("other:r33", "cf:r33", "sheets:r33"), "ROLE_SOURCE_PREFIX_INVALID"),
        ((), "ROLE_SOURCE_IDS_MISSING"),
    ),
)
def test_source_integrity_fails_closed(source_ids: tuple[str, ...], reason: str) -> None:
    plan = assign_team_roles(request("AlphaTeam", source_ids=source_ids))
    assert plan.decision_ready is False
    assert plan.fail_closed is True
    assert plan.abstain is True
    assert plan.action == "hold"
    assert reason in plan.reason_codes


def test_stale_or_missing_evidence_fails_closed() -> None:
    stale = assign_team_roles(request("AlphaTeam", data_state="STALE"))
    missing = assign_team_roles(request("AlphaTeam", evidence_ids=()))
    assert stale.fail_closed and "ROLE_DATA_NOT_FRESH" in stale.reason_codes
    assert missing.fail_closed and "ROLE_EVIDENCE_IDS_MISSING" in missing.reason_codes


def test_unknown_or_unavailable_helper_fails_closed() -> None:
    unknown = assign_team_roles(request("AlphaTeam", active_triggers=("unknown",)))
    unavailable = assign_team_roles(
        request("BetaTeam", active_triggers=("fake_breakout",), unavailable_bots=("OBot",))
    )
    assert unknown.fail_closed and "ROLE_HELPER_TRIGGER_UNKNOWN" in unknown.reason_codes
    assert unavailable.fail_closed
    assert "ROLE_REQUIRED_HELPER_UNAVAILABLE" in unavailable.reason_codes
    assert "ROLE_WATCHER_COVERAGE_DEGRADED" in unavailable.reason_codes


def test_ordinary_main_or_support_failure_is_hold() -> None:
    main_down = assign_team_roles(request("AlphaTeam", unavailable_bots=("LBot",)))
    support_down = assign_team_roles(request("GammaTeam", unavailable_bots=("MBot",)))
    assert main_down.fail_closed and "ROLE_MAIN_UNAVAILABLE" in main_down.reason_codes
    assert support_down.fail_closed and "ROLE_SUPPORT_UNAVAILABLE" in support_down.reason_codes
    assert main_down.binding_helper() == (None, None)
    assert support_down.binding_helper() == (None, None)


def test_delta_reserve_is_recovery_only_and_never_replaces_sbot_authority() -> None:
    plan = assign_team_roles(request("DeltaTeam", unavailable_bots=("SBot",)))
    assert plan.reserve_used is True
    assert plan.mode == "reserve_recovery"
    assert plan.canonical_main == "SBot"
    assert plan.effective_main == "LBot"
    assert plan.decision_ready is False
    assert plan.fail_closed is True
    assert plan.action == "hold"
    assert "ROLE_DELTA_RESERVE_RECOVERY_HOLD" in plan.reason_codes


def test_request_validation_rejects_duplicate_or_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="DUPLICATE_TRIGGER"):
        request("AlphaTeam", active_triggers=("pullback_retest", "pullback_retest"))
    with pytest.raises(ValueError, match="DUPLICATE_UNAVAILABLE_BOT"):
        request("AlphaTeam", unavailable_bots=("LBot", "LBot"))
    with pytest.raises(ValueError, match="UNAVAILABLE_BOT_INVALID"):
        request("AlphaTeam", unavailable_bots=("ZBot",))
