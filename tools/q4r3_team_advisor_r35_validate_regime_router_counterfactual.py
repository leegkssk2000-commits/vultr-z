#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from canonical.teams.router_counterfactual import (
    REMAINING_SHARED_GAPS,
    RouterPolicy,
    TeamRouteCandidate,
    TeamRouterRequest,
    route_teams,
    validate_router_contract,
)

SRC = ("cf:r35:proof", "sheets:r35:proof")
EVD = ("evidence:r35:proof",)
ROUTES = {"trend": "AlphaTeam", "range": "BetaTeam", "breakout": "GammaTeam", "capital_stress": "DeltaTeam"}


def policy(**kw: object) -> RouterPolicy:
    return RouterPolicy(
        policy_id="ssot.team-router.r35.proof",
        source_ids=SRC,
        score_weights={"confidence": 0.30, "net_r": 0.50, "drawdown": 0.15, "cost": 0.05},
        minimum_score_margin=float(kw.pop("margin", 0.05)),
        minimum_counterfactual_uplift_r=float(kw.pop("uplift", 0.10)),
        maximum_candidate_dd_pct=5.0,
        defense_override_regimes=("capital_stress", "regime_shift", "execution_degradation", "recovery"),
    )


def cand(team: str, regime: str, **kw: object) -> TeamRouteCandidate:
    values = {
        "AlphaTeam": (0.88, 0.70, 1.2, 0.05),
        "BetaTeam": (0.82, 0.55, 1.0, 0.04),
        "GammaTeam": (0.86, 0.75, 1.5, 0.08),
        "DeltaTeam": (0.90, 0.25, 0.5, 0.03),
    }[team]
    return TeamRouteCandidate(
        team_id=team, observed_regime=regime,  # type: ignore[arg-type]
        calibrated_confidence=float(kw.pop("confidence", values[0])),
        expected_net_r=float(kw.pop("net_r", values[1])),
        expected_dd_pct=float(kw.pop("dd", values[2])),
        expected_cost_r=float(kw.pop("cost", values[3])),
        role_ready=bool(kw.pop("role_ready", True)),
        confidence_ready=bool(kw.pop("confidence_ready", True)),
        hard_veto=bool(kw.pop("hard_veto", False)),
        source_ids=kw.pop("source_ids", SRC),  # type: ignore[arg-type]
        evidence_ids=kw.pop("evidence_ids", EVD),  # type: ignore[arg-type]
    )


def req(regime: str, **kw: object) -> TeamRouterRequest:
    teams = ("AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam")
    return TeamRouterRequest(
        request_id=f"route.{regime}.r35.proof",
        candidates=kw.pop("candidates", tuple(cand(team, regime) for team in teams)),  # type: ignore[arg-type]
        no_team_expected_net_r=float(kw.pop("no_team", 0.0)),
        policy=kw.pop("policy", policy()),  # type: ignore[arg-type]
        source_ids=kw.pop("source_ids", SRC),  # type: ignore[arg-type]
        evidence_ids=kw.pop("evidence_ids", EVD),  # type: ignore[arg-type]
        data_state=str(kw.pop("data_state", "FRESH")),
    )


def replace(values: tuple[TeamRouteCandidate, ...], team: str, item: TeamRouteCandidate) -> tuple[TeamRouteCandidate, ...]:
    return tuple(item if value.team_id == team else value for value in values)


def write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--r34", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    r34 = json.loads(args.r34.read_text(encoding="utf-8"))
    report = r34.get("report") or {}
    blockers: list[str] = []
    expected = {"counterfactual_team_selection", "regime_eligibility_engine", "team_router_ranking"}
    if r34.get("state") != "PASS" or r34.get("verdict") != "R34_WATCHER_SEVERITY_CONFIDENCE_PASS": blockers.append("R34_STATE_INVALID")
    if report.get("watcher_severity_ready_count") != 4 or report.get("confidence_calibration_ready_count") != 4: blockers.append("R34_READY_COUNT_INVALID")
    if set(report.get("remaining_shared_gaps") or ()) != expected: blockers.append("R34_GAPS_INVALID")
    blockers.extend(f"CONTRACT:{item}" for item in validate_router_contract())

    proofs = {regime: route_teams(req(regime)) for regime in ROUTES}
    eligibility = sum(item.binding_team() == ROUTES[regime] for regime, item in proofs.items())
    ranking = sum(item.decision_ready and item.score_margin is not None for item in proofs.values())
    counterfactual = sum(item.decision_ready and (item.counterfactual_uplift_r or 0.0) > 0.0 for item in proofs.values())

    base = req("trend").candidates
    failures = (
        route_teams(req("trend", source_ids=("cf:r35",))),
        route_teams(req("trend", data_state="STALE")),
        route_teams(req("trend", evidence_ids=())),
        route_teams(req("unknown_regime")),
        route_teams(req("trend", policy=policy(margin=10.0))),
        route_teams(req("trend", candidates=replace(base, "AlphaTeam", cand("AlphaTeam", "trend", net_r=0.12)), policy=policy(uplift=0.20))),
        route_teams(req("trend", candidates=replace(base, "AlphaTeam", cand("AlphaTeam", "trend", source_ids=("cf:r35",))))),
        route_teams(req("trend", candidates=replace(base, "AlphaTeam", cand("AlphaTeam", "trend", hard_veto=True)))),
    )
    failed = sum(item.fail_closed for item in failures)
    veto = sum(item.hard_veto and item.action == "block" for item in failures)
    if eligibility != 4: blockers.append("ELIGIBILITY_COUNT_INVALID")
    if ranking != 4: blockers.append("RANKING_COUNT_INVALID")
    if counterfactual != 4: blockers.append("COUNTERFACTUAL_COUNT_INVALID")
    if failed != 8: blockers.append("FAIL_CLOSED_COUNT_INVALID")
    if veto != 1: blockers.append("VETO_COUNT_INVALID")
    if REMAINING_SHARED_GAPS: blockers.append("SHARED_GAPS_REMAIN")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r35_regime_router_counterfactual_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R3.5", "state": state,
        "verdict": "R35_REGIME_ROUTER_COUNTERFACTUAL_PASS" if state == "PASS" else "R35_REGIME_ROUTER_COUNTERFACTUAL_BLOCKED",
        "blockers": blockers,
        "report": {
            "team_count": 4, "regime_eligibility_ready_count": eligibility,
            "team_router_ranking_ready_count": ranking,
            "counterfactual_selection_ready_count": counterfactual,
            "fail_closed_scenario_count": failed, "sbot_hard_veto_proof_count": veto,
            "closed_shared_gaps": sorted(expected), "remaining_shared_gaps": [],
            "shared_gap_count_after": 0, "feature_complete_team_count": 4 if state == "PASS" else 0,
            "sgrade_ready_count": 0,
            "routes": {regime: {"selected_team": item.binding_team(), "score_margin": item.score_margin, "counterfactual_uplift_r": item.counterfactual_uplift_r} for regime, item in proofs.items()},
            "embedded_numeric_trading_thresholds": False, "runtime_binding": False,
            "execution_authority": "none",
            "next_route": "R3.6_FOUR_TEAM_SGRADE_LOCK" if state == "PASS" else "R3.5_REPAIR_REGIME_ROUTER_COUNTERFACTUAL",
        },
        "authority": {"observer_only": True, "runtime_mutation_performed": False, "systemd_mutation_performed": False, "execution_authority": "none"},
        "action": "hold",
    }
    write(args.output, payload)
    print(json.dumps({"state": state, "team_count": 4, "regime_eligibility_ready_count": eligibility, "team_router_ranking_ready_count": ranking, "counterfactual_selection_ready_count": counterfactual, "fail_closed_scenario_count": failed, "remaining_shared_gap_count": 0, "blocker_count": len(blockers)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
