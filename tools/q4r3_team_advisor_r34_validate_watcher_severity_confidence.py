#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from canonical.teams.policy_contracts import TEAM_POLICY_REGISTRY
from canonical.teams.watcher_confidence import (
    CalibrationPolicy,
    REMAINING_SHARED_GAPS,
    TeamConfidenceRequest,
    WatcherSignal,
    calibrate_team_confidence,
    validate_watcher_confidence_contract,
)

SOURCES = ("cf:r34:proof", "sheets:r34:proof")
EVIDENCE = ("evidence:r34:proof",)
EXPECTED_GAPS = {
    "confidence_calibration",
    "counterfactual_team_selection",
    "regime_eligibility_engine",
    "team_router_ranking",
    "watcher_severity_aggregation",
}


def policy() -> CalibrationPolicy:
    return CalibrationPolicy(
        policy_id="ssot.team-confidence.r34.proof",
        source_ids=SOURCES,
        role_weights={"main": 0.55, "support": 0.35, "helper": 0.10},
        watcher_penalties={"none": 0.0, "m": 0.05, "M": 0.20, "C": 0.50},
        minimum_ready_confidence=0.50,
    )


def signal(bot: str, severity: str = "none", confidence: float = 1.0, **kwargs: object) -> WatcherSignal:
    return WatcherSignal(
        watcher=bot, severity=severity, confidence=confidence,  # type: ignore[arg-type]
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        evidence_ids=kwargs.pop("evidence_ids", EVIDENCE),  # type: ignore[arg-type]
        **kwargs,
    )


def request(team: str, **kwargs: object) -> TeamConfidenceRequest:
    watchers = tuple(signal(bot) for bot in TEAM_POLICY_REGISTRY[team].watcher_priorities)
    return TeamConfidenceRequest(
        team_id=team, role_assignment_id=f"role.{team}.r34",  # type: ignore[arg-type]
        main_confidence=float(kwargs.pop("main_confidence", 0.90)),
        support_confidence=float(kwargs.pop("support_confidence", 0.80)),
        helper_active=bool(kwargs.pop("helper_active", False)),
        helper_confidence=kwargs.pop("helper_confidence", None),  # type: ignore[arg-type]
        watcher_signals=kwargs.pop("watcher_signals", watchers),  # type: ignore[arg-type]
        policy=kwargs.pop("policy", policy()),  # type: ignore[arg-type]
        source_ids=kwargs.pop("source_ids", SOURCES),  # type: ignore[arg-type]
        evidence_ids=kwargs.pop("evidence_ids", EVIDENCE),  # type: ignore[arg-type]
        **kwargs,
    )


def write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r33", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r33 = json.loads(args.r33.read_text(encoding="utf-8"))
    report33 = r33.get("report") or {}
    blockers: list[str] = []
    if r33.get("state") != "PASS" or r33.get("verdict") != "R33_DYNAMIC_ROLE_HELPER_RESERVE_PASS":
        blockers.append("R33_STATE_INVALID")
    if report33.get("dynamic_role_engine_ready_count") != 4 or report33.get("helper_assignment_ready_count") != 4:
        blockers.append("R33_READY_COUNTS_INVALID")
    if set(report33.get("remaining_shared_gaps") or ()) != EXPECTED_GAPS:
        blockers.append("R33_GAPS_INVALID")
    blockers.extend(f"CONTRACT:{item}" for item in validate_watcher_confidence_contract())

    teams: dict[str, object] = {}
    ready = 0
    severity_ready = 0
    for team in sorted(TEAM_POLICY_REGISTRY):
        watchers = tuple(TEAM_POLICY_REGISTRY[team].watcher_priorities)
        base = calibrate_team_confidence(request(team))
        warned = calibrate_team_confidence(request(
            team,
            watcher_signals=(
                signal(watchers[0], "M", 0.80),
                signal(watchers[1], "m", 0.70),
            ),
        ))
        ready += int(base.decision_ready)
        severity_ready += int(warned.decision_ready and warned.severity == "M")
        teams[team] = {
            "watchers": list(watchers),
            "base_confidence": base.calibrated_confidence,
            "warned_confidence": warned.calibrated_confidence,
            "severity": warned.severity,
            "dominant_watcher": warned.dominant_watcher,
        }

    alpha = tuple(TEAM_POLICY_REGISTRY["AlphaTeam"].watcher_priorities)
    failures = (
        calibrate_team_confidence(request("AlphaTeam", source_ids=("cf:r34",))),
        calibrate_team_confidence(request("AlphaTeam", data_state="STALE")),
        calibrate_team_confidence(request("AlphaTeam", evidence_ids=())),
        calibrate_team_confidence(request("AlphaTeam", watcher_signals=(signal(alpha[0]),))),
        calibrate_team_confidence(request("AlphaTeam", watcher_signals=(signal(alpha[0], "C"), signal(alpha[1])))),
        calibrate_team_confidence(request("AlphaTeam", watcher_signals=(signal("OBot"), signal("SBot", "C", hard_veto=True)))),
    )
    failed = sum(item.fail_closed for item in failures)
    vetoes = sum(item.hard_veto and item.action == "block" for item in failures)
    if ready != 4: blockers.append("CONFIDENCE_READY_COUNT_INVALID")
    if severity_ready != 4: blockers.append("SEVERITY_READY_COUNT_INVALID")
    if failed != 6: blockers.append("FAIL_CLOSED_COUNT_INVALID")
    if vetoes != 1: blockers.append("SBOT_VETO_COUNT_INVALID")

    state = "PASS" if not blockers else "HOLD"
    payload: dict[str, object] = {
        "schema": "q4r3_team_advisor_r34_watcher_severity_confidence_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R3.4",
        "state": state,
        "verdict": "R34_WATCHER_SEVERITY_CONFIDENCE_PASS" if state == "PASS" else "R34_WATCHER_SEVERITY_CONFIDENCE_BLOCKED",
        "blockers": blockers,
        "report": {
            "team_count": 4,
            "watcher_severity_ready_count": severity_ready,
            "confidence_calibration_ready_count": ready,
            "fail_closed_scenario_count": failed,
            "sbot_hard_veto_proof_count": vetoes,
            "severity_order": ["none", "m", "M", "C"],
            "closed_shared_gaps": ["watcher_severity_aggregation", "confidence_calibration"],
            "remaining_shared_gaps": list(REMAINING_SHARED_GAPS),
            "shared_gap_count_after": len(REMAINING_SHARED_GAPS),
            "teams": teams,
            "embedded_numeric_trading_thresholds": False,
            "runtime_binding": False,
            "execution_authority": "none",
            "sgrade_ready_count": 0,
            "next_route": "R3.5_REGIME_ELIGIBILITY_ROUTER_RANKING_COUNTERFACTUAL" if state == "PASS" else "R3.4_REPAIR_WATCHER_SEVERITY_CONFIDENCE",
        },
        "authority": {"observer_only": True, "runtime_mutation_performed": False, "systemd_mutation_performed": False, "execution_authority": "none"},
        "action": "hold",
    }
    write(args.output, payload)
    print(json.dumps({"state": state, "team_count": 4, "watcher_severity_ready_count": severity_ready, "confidence_calibration_ready_count": ready, "fail_closed_scenario_count": failed, "remaining_shared_gap_count": len(REMAINING_SHARED_GAPS), "blocker_count": len(blockers)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
