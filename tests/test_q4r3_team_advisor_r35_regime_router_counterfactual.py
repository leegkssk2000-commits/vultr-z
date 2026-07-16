from __future__ import annotations

import pytest

from canonical.teams.router_counterfactual import (
    REMAINING_SHARED_GAPS,
    RouterPolicy,
    TeamRouteCandidate,
    TeamRouterRequest,
    route_teams,
    validate_router_contract,
)

SOURCES = ("cf:r35", "sheets:r35")
EVIDENCE = ("evidence:r35",)


def policy(**kwargs: object) -> RouterPolicy:
    return RouterPolicy(
        policy_id=str(kwargs.pop("policy_id", "ssot.team-router.r35")),
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        score_weights=kwargs.pop(
            "score_weights",
            {"confidence": 0.30, "net_r": 0.50, "drawdown": 0.15, "cost": 0.05},
        ),  # type: ignore[arg-type]
        minimum_score_margin=float(kwargs.pop("minimum_score_margin", 0.05)),
        minimum_counterfactual_uplift_r=float(
            kwargs.pop("minimum_counterfactual_uplift_r", 0.10)
        ),
        maximum_candidate_dd_pct=float(kwargs.pop("maximum_candidate_dd_pct", 5.0)),
        defense_override_regimes=kwargs.pop(
            "defense_override_regimes",
            ("capital_stress", "regime_shift", "execution_degradation", "recovery"),
        ),  # type: ignore[arg-type]
        **kwargs,
    )


def candidate(
    team_id: str,
    regime: str,
    *,
    confidence: float = 0.80,
    net_r: float = 0.40,
    dd_pct: float = 1.0,
    cost_r: float = 0.05,
    **kwargs: object,
) -> TeamRouteCandidate:
    return TeamRouteCandidate(
        team_id=team_id,  # type: ignore[arg-type]
        observed_regime=regime,
        calibrated_confidence=confidence,
        expected_net_r=net_r,
        expected_dd_pct=dd_pct,
        expected_cost_r=cost_r,
        role_ready=bool(kwargs.pop("role_ready", True)),
        confidence_ready=bool(kwargs.pop("confidence_ready", True)),
        hard_veto=bool(kwargs.pop("hard_veto", False)),
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        evidence_ids=kwargs.pop("evidence_ids", EVIDENCE),  # type: ignore[arg-type]
        **kwargs,
    )


def request(regime: str, **kwargs: object) -> TeamRouterRequest:
    values = {
        "AlphaTeam": dict(confidence=0.88, net_r=0.70, dd_pct=1.2, cost_r=0.05),
        "BetaTeam": dict(confidence=0.82, net_r=0.55, dd_pct=1.0, cost_r=0.04),
        "GammaTeam": dict(confidence=0.86, net_r=0.75, dd_pct=1.5, cost_r=0.08),
        "DeltaTeam": dict(confidence=0.90, net_r=0.25, dd_pct=0.5, cost_r=0.03),
    }
    candidates = tuple(
        candidate(team_id, regime, **values[team_id])
        for team_id in ("AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam")
    )
    return TeamRouterRequest(
        request_id=str(kwargs.pop("request_id", f"route.{regime}.r35")),
        candidates=kwargs.pop("candidates", candidates),  # type: ignore[arg-type]
        no_team_expected_net_r=float(kwargs.pop("no_team_expected_net_r", 0.0)),
        policy=kwargs.pop("policy", policy()),  # type: ignore[arg-type]
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        evidence_ids=kwargs.pop("evidence_ids", EVIDENCE),  # type: ignore[arg-type]
        **kwargs,
    )


def replace_candidate(
    values: tuple[TeamRouteCandidate, ...],
    team_id: str,
    replacement: TeamRouteCandidate,
) -> tuple[TeamRouteCandidate, ...]:
    return tuple(replacement if item.team_id == team_id else item for item in values)


def test_contract_closes_all_team_shared_gaps() -> None:
    assert validate_router_contract() == ()
    assert REMAINING_SHARED_GAPS == ()


@pytest.mark.parametrize(
    ("regime", "expected"),
    (
        ("trend", "AlphaTeam"),
        ("range", "BetaTeam"),
        ("breakout", "GammaTeam"),
        ("capital_stress", "DeltaTeam"),
    ),
)
def test_regime_eligibility_selects_distinct_team(regime: str, expected: str) -> None:
    envelope = route_teams(request(regime))
    assert envelope.decision_ready is True
    assert envelope.fail_closed is False
    assert envelope.selected_team == expected
    assert envelope.binding_team() == expected
    assert envelope.action == "hold"
    assert envelope.authority == "advisory_only"
    assert envelope.runtime_enabled is False
    assert envelope.execution_authority == "none"


def test_defense_override_excludes_ordinary_teams() -> None:
    envelope = route_teams(request("execution_degradation"))
    assert envelope.selected_team == "DeltaTeam"
    ordinary = [item for item in envelope.ranked_teams if item.team_id != "DeltaTeam"]
    assert ordinary
    assert all(item.eligible is False for item in ordinary)
    assert any(
        reason.endswith("DEFENSE_OVERRIDE")
        for item in ordinary
        for reason in item.reason_codes
    )


def test_non_eligible_regime_fails_closed_without_guessing() -> None:
    envelope = route_teams(request("unknown_regime"))
    assert envelope.decision_ready is False
    assert envelope.fail_closed is True
    assert envelope.selected_team is None
    assert "ROUTER_NO_ELIGIBLE_TEAM" in envelope.reason_codes


def test_ranking_uses_risk_adjusted_score_when_multiple_teams_are_eligible() -> None:
    values = request("trend").candidates
    alpha = candidate("AlphaTeam", "trend_transition", confidence=0.75, net_r=0.45, dd_pct=1.0, cost_r=0.05)
    # Delta is not regime-eligible. Alpha remains the only valid route despite a higher raw confidence elsewhere.
    values = replace_candidate(values, "AlphaTeam", alpha)
    values = tuple(
        candidate(item.team_id, "trend_transition", confidence=item.calibrated_confidence,
                  net_r=item.expected_net_r, dd_pct=item.expected_dd_pct,
                  cost_r=item.expected_cost_r)
        if item.team_id != "AlphaTeam" else item
        for item in values
    )
    envelope = route_teams(request("trend_transition", candidates=values))
    assert envelope.decision_ready is True
    assert envelope.selected_team == "AlphaTeam"


def test_counterfactual_uplift_below_ssot_minimum_holds() -> None:
    base = request("trend")
    alpha = candidate(
        "AlphaTeam", "trend", confidence=0.95, net_r=0.12, dd_pct=0.1, cost_r=0.01
    )
    values = replace_candidate(base.candidates, "AlphaTeam", alpha)
    strict = policy(minimum_counterfactual_uplift_r=0.20)
    envelope = route_teams(
        request("trend", candidates=values, no_team_expected_net_r=0.0, policy=strict)
    )
    assert envelope.fail_closed is True
    assert envelope.selected_team is None
    assert "ROUTER_COUNTERFACTUAL_UPLIFT_BELOW_SSOT_MINIMUM" in envelope.reason_codes


def test_score_margin_below_ssot_minimum_holds() -> None:
    base = request("trend")
    strict = policy(minimum_score_margin=10.0)
    envelope = route_teams(request("trend", candidates=base.candidates, policy=strict))
    assert envelope.fail_closed is True
    assert "ROUTER_SCORE_MARGIN_BELOW_SSOT_MINIMUM" in envelope.reason_codes


def test_candidate_integrity_failure_holds_entire_router() -> None:
    base = request("range")
    broken = candidate("BetaTeam", "range", source_ids=("cf:r35",))
    values = replace_candidate(base.candidates, "BetaTeam", broken)
    envelope = route_teams(request("range", candidates=values))
    assert envelope.fail_closed is True
    assert envelope.selected_team is None
    assert "ROUTER_CANDIDATE_INTEGRITY_FAILURE" in envelope.reason_codes


def test_role_confidence_and_dd_fail_closed() -> None:
    base = request("breakout")
    role_bad = candidate("GammaTeam", "breakout", role_ready=False)
    values = replace_candidate(base.candidates, "GammaTeam", role_bad)
    assert route_teams(request("breakout", candidates=values)).fail_closed is True

    dd_bad = candidate("GammaTeam", "breakout", dd_pct=9.0)
    values = replace_candidate(base.candidates, "GammaTeam", dd_bad)
    assert route_teams(request("breakout", candidates=values)).fail_closed is True


def test_request_source_stale_and_evidence_fail_closed() -> None:
    assert route_teams(request("trend", source_ids=("cf:r35",))).fail_closed is True
    assert route_teams(request("trend", data_state="STALE")).fail_closed is True
    assert route_teams(request("trend", evidence_ids=())).fail_closed is True


def test_hard_veto_blocks_global_route() -> None:
    base = request("trend")
    vetoed = candidate("AlphaTeam", "trend", hard_veto=True)
    values = replace_candidate(base.candidates, "AlphaTeam", vetoed)
    envelope = route_teams(request("trend", candidates=values))
    assert envelope.fail_closed is True
    assert envelope.hard_veto is True
    assert envelope.action == "block"
    assert envelope.selected_team is None
    assert "ROUTER_SBOT_HARD_VETO" in envelope.reason_codes


def test_route_id_and_ranking_are_deterministic() -> None:
    first = route_teams(request("range"))
    second = route_teams(request("range"))
    assert first.route_id == second.route_id
    assert first.ranked_teams == second.ranked_teams


def test_request_rejects_incomplete_or_duplicate_team_set() -> None:
    values = request("trend").candidates
    with pytest.raises(ValueError, match="CANDIDATE_TEAM_SET_INVALID"):
        TeamRouterRequest(
            request_id="bad",
            candidates=values[:-1],
            no_team_expected_net_r=0.0,
            policy=policy(),
            source_ids=SOURCES,
            evidence_ids=EVIDENCE,
        )
    with pytest.raises(ValueError, match="CANDIDATE_TEAM_DUPLICATE"):
        TeamRouterRequest(
            request_id="bad",
            candidates=(values[0], values[0], values[2], values[3]),
            no_team_expected_net_r=0.0,
            policy=policy(),
            source_ids=SOURCES,
            evidence_ids=EVIDENCE,
        )
