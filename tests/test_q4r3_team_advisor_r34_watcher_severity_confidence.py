from __future__ import annotations

import pytest

from canonical.teams.policy_contracts import TEAM_POLICY_REGISTRY
from canonical.teams.watcher_confidence import (
    CalibrationPolicy,
    REMAINING_SHARED_GAPS,
    TeamConfidenceRequest,
    WatcherSignal,
    calibrate_team_confidence,
    validate_watcher_confidence_contract,
)

SOURCES = ("cf:r34", "sheets:r34")
EVIDENCE = ("evidence:r34",)


def calibration_policy(**kwargs: object) -> CalibrationPolicy:
    return CalibrationPolicy(
        policy_id=str(kwargs.pop("policy_id", "ssot.team-confidence.r34")),
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        role_weights=kwargs.pop(
            "role_weights", {"main": 0.55, "support": 0.35, "helper": 0.10}
        ),  # type: ignore[arg-type]
        watcher_penalties=kwargs.pop(
            "watcher_penalties", {"none": 0.0, "m": 0.05, "M": 0.20, "C": 0.50}
        ),  # type: ignore[arg-type]
        minimum_ready_confidence=float(kwargs.pop("minimum_ready_confidence", 0.50)),
        **kwargs,
    )


def signal(
    watcher: str,
    *,
    severity: str = "none",
    confidence: float = 1.0,
    **kwargs: object,
) -> WatcherSignal:
    return WatcherSignal(
        watcher=watcher,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        confidence=confidence,
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        evidence_ids=kwargs.pop("evidence_ids", EVIDENCE),  # type: ignore[arg-type]
        **kwargs,
    )


def request(team_id: str, **kwargs: object) -> TeamConfidenceRequest:
    watchers = tuple(
        signal(watcher)
        for watcher in TEAM_POLICY_REGISTRY[team_id].watcher_priorities
    )
    return TeamConfidenceRequest(
        team_id=team_id,  # type: ignore[arg-type]
        role_assignment_id=str(kwargs.pop("role_assignment_id", f"role.{team_id}.r34")),
        main_confidence=float(kwargs.pop("main_confidence", 0.90)),
        support_confidence=float(kwargs.pop("support_confidence", 0.80)),
        helper_active=bool(kwargs.pop("helper_active", False)),
        helper_confidence=kwargs.pop("helper_confidence", None),  # type: ignore[arg-type]
        watcher_signals=kwargs.pop("watcher_signals", watchers),  # type: ignore[arg-type]
        policy=kwargs.pop("policy", calibration_policy()),  # type: ignore[arg-type]
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        evidence_ids=kwargs.pop("evidence_ids", EVIDENCE),  # type: ignore[arg-type]
        **kwargs,
    )


def test_contract_is_clean() -> None:
    assert validate_watcher_confidence_contract() == ()
    assert REMAINING_SHARED_GAPS == (
        "counterfactual_team_selection",
        "regime_eligibility_engine",
        "team_router_ranking",
    )


@pytest.mark.parametrize("team_id", sorted(TEAM_POLICY_REGISTRY))
def test_four_teams_calibrate_with_canonical_watchers(team_id: str) -> None:
    envelope = calibrate_team_confidence(request(team_id))
    assert envelope.decision_ready is True
    assert envelope.fail_closed is False
    assert envelope.severity == "none"
    assert envelope.watcher_penalty == pytest.approx(0.0)
    assert envelope.binding_confidence() == pytest.approx(envelope.calibrated_confidence)
    assert envelope.authority == "advisory_only"
    assert envelope.runtime_enabled is False
    assert envelope.execution_authority == "none"


def test_helper_confidence_is_included_only_when_active() -> None:
    without_helper = calibrate_team_confidence(request("AlphaTeam"))
    with_helper = calibrate_team_confidence(
        request("AlphaTeam", helper_active=True, helper_confidence=0.30)
    )
    assert with_helper.role_confidence < without_helper.role_confidence
    assert with_helper.decision_ready is True


def test_severity_aggregation_uses_highest_watcher_level() -> None:
    envelope = calibrate_team_confidence(
        request(
            "AlphaTeam",
            watcher_signals=(
                signal("OBot", severity="m", confidence=0.90),
                signal("SBot", severity="M", confidence=0.80),
            ),
        )
    )
    assert envelope.severity == "M"
    assert envelope.dominant_watcher == "SBot"
    assert envelope.watcher_penalty > 0.0
    assert envelope.decision_ready is True


def test_multiple_watcher_penalties_compound_conservatively() -> None:
    one_warning = calibrate_team_confidence(
        request(
            "AlphaTeam",
            watcher_signals=(
                signal("OBot", severity="M", confidence=0.80),
                signal("SBot"),
            ),
        )
    )
    two_warnings = calibrate_team_confidence(
        request(
            "AlphaTeam",
            watcher_signals=(
                signal("OBot", severity="M", confidence=0.80),
                signal("SBot", severity="m", confidence=0.90),
            ),
        )
    )
    assert two_warnings.watcher_penalty > one_warning.watcher_penalty
    assert two_warnings.calibrated_confidence < one_warning.calibrated_confidence


def test_critical_watcher_fails_closed_to_hold() -> None:
    envelope = calibrate_team_confidence(
        request(
            "AlphaTeam",
            watcher_signals=(signal("OBot", severity="C"), signal("SBot")),
        )
    )
    assert envelope.decision_ready is False
    assert envelope.fail_closed is True
    assert envelope.action == "hold"
    assert "CONFIDENCE_CRITICAL_WATCHER_HOLD" in envelope.reason_codes


def test_sbot_hard_veto_is_the_only_block_path() -> None:
    envelope = calibrate_team_confidence(
        request(
            "AlphaTeam",
            watcher_signals=(signal("OBot"), signal("SBot", severity="C", hard_veto=True)),
        )
    )
    assert envelope.decision_ready is False
    assert envelope.hard_veto is True
    assert envelope.action == "block"
    assert "CONFIDENCE_SBOT_HARD_VETO" in envelope.reason_codes
    with pytest.raises(ValueError, match="HARD_VETO_OWNER_INVALID"):
        signal("OBot", hard_veto=True)


def test_missing_or_extra_watcher_fails_closed() -> None:
    missing = calibrate_team_confidence(
        request("BetaTeam", watcher_signals=(signal("OBot"),))
    )
    assert missing.fail_closed is True
    assert "CONFIDENCE_WATCHER_SET_MISMATCH" in missing.reason_codes


def test_source_freshness_evidence_and_abstain_fail_closed() -> None:
    source_missing = calibrate_team_confidence(
        request("GammaTeam", source_ids=("cf:r34",))
    )
    stale = calibrate_team_confidence(request("GammaTeam", data_state="STALE"))
    evidence_missing = calibrate_team_confidence(request("GammaTeam", evidence_ids=()))
    watcher_abstain = calibrate_team_confidence(
        request(
            "GammaTeam",
            watcher_signals=(signal("LBot", abstain=True), signal("SBot")),
        )
    )
    assert source_missing.fail_closed and "REQUEST_SHEETS_SOURCE_MISSING" in source_missing.reason_codes
    assert stale.fail_closed and "CONFIDENCE_DATA_NOT_FRESH" in stale.reason_codes
    assert evidence_missing.fail_closed and "CONFIDENCE_EVIDENCE_IDS_MISSING" in evidence_missing.reason_codes
    assert watcher_abstain.fail_closed and "WATCHER_LBot_ABSTAIN" in watcher_abstain.reason_codes


def test_below_ssot_minimum_fails_closed() -> None:
    strict_policy = calibration_policy(minimum_ready_confidence=0.95)
    envelope = calibrate_team_confidence(request("DeltaTeam", policy=strict_policy))
    assert envelope.fail_closed is True
    assert envelope.binding_confidence() is None
    assert "CONFIDENCE_BELOW_SSOT_MINIMUM" in envelope.reason_codes


def test_calibration_id_is_deterministic() -> None:
    first = calibrate_team_confidence(request("AlphaTeam"))
    second = calibrate_team_confidence(request("AlphaTeam"))
    assert first.calibration_id == second.calibration_id
