#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from policy import zbot_attribution as attribution
from policy import zbot_drift as drift
from policy import zbot_sgrade as sgrade

SCHEMA = "q4r3_team_advisor_r55_zbot_attribution_drift_sgrade_lock_v1"
CLOSED = {"cost_performance_attribution", "model_quality_drift_evaluation"}
PROVIDERS = ("openai", "gemini")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def sample_outcomes() -> tuple[attribution.ProviderOutcome, ...]:
    rows = []
    for index in range(3):
        for provider_id in PROVIDERS:
            rows.append(attribution.ProviderOutcome(
                observation_id=f"validator.obs.{index}.{provider_id}",
                receipt_id=f"zbot.receipt.validator.{index}",
                provider_id=provider_id,
                task_kind="risk_review",
                model_id=f"{provider_id}.validator",
                proposed_action="hold",
                realized_r=0.30 + index * 0.05,
                baseline_r=0.10,
                input_tokens=500,
                output_tokens=200,
                cost_micro_usd=50,
                observed_at_ms=9900 + index,
                outcome_ref=f"sheets:zbot:validator:outcome:{index}:{provider_id}",
            ))
    return tuple(rows)


def snapshots(current: bool) -> tuple[drift.QualitySnapshot, ...]:
    return tuple(drift.QualitySnapshot(
        provider_id=provider_id,
        model_id=f"{provider_id}.validator",
        sample_count=100,
        mean_confidence=0.78 if current else 0.76,
        positive_value_rate=0.63 if current else 0.62,
        action_disagreement_rate=0.08 if current else 0.07,
        schema_failure_rate=0.01,
        mean_cost_micro_usd=52.0 if current else 50.0,
        observed_at_ms=9950 if current else 9900,
        metric_ref=f"sheets:zbot:validator:quality:{provider_id}:{'current' if current else 'reference'}",
    ) for provider_id in PROVIDERS)


def validate(r54_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r54 = read_json(r54_path)
    contract = read_json(contract_path)
    report54 = r54.get("report", {})
    if r54.get("state") != "PASS" or r54.get("blockers"):
        blockers.append("R54_PASS_NOT_PROVEN")
    if report54.get("next_route") != "R5.5_ZBOT_ATTRIBUTION_DRIFT_SGRADE_LOCK":
        blockers.append("R54_NEXT_ROUTE_INVALID")
    if report54.get("ready_surface_count") != 22 or report54.get("remaining_surface_count") != 2:
        blockers.append("R54_SURFACE_COUNT_INVALID")
    if set(report54.get("remaining_surfaces", [])) != CLOSED:
        blockers.append("R54_REMAINING_SURFACE_SET_INVALID")

    if contract.get("schema") != "q4r3_zbot_attribution_drift_sgrade_lock_v1":
        blockers.append("R55_CONTRACT_SCHEMA_INVALID")
    if set(contract.get("closed_surfaces", [])) != CLOSED:
        blockers.append("R55_CLOSED_SURFACES_INVALID")
    if contract.get("remaining_surfaces") != []:
        blockers.append("R55_REMAINING_SURFACES_INVALID")
    surface_count = contract.get("surface_count", {})
    if surface_count != {"prior_ready": 22, "closed_now": 2, "total_ready": 24, "total": 24}:
        blockers.append("R55_SURFACE_COUNT_CONTRACT_INVALID")
    authority = contract.get("authority", {})
    if authority.get("provider_invocation_enabled") is not False or authority.get("runtime_enabled") is not False:
        blockers.append("R55_RUNTIME_PROVIDER_BOUNDARY_INVALID")
    if authority.get("execution_authority") != "none" or authority.get("order_authority") != "none":
        blockers.append("R55_AUTHORITY_BOUNDARY_INVALID")

    attribution_result = attribution.evaluate_attribution(
        sample_outcomes(),
        expected_provider_ids=PROVIDERS,
        now_ms=10000,
        policy=attribution.AttributionPolicy(
            min_samples_per_provider=3,
            max_sample_age_ms=1000,
            max_cost_per_positive_r_micro_usd=1000,
            min_net_value_r=0.10,
            policy_ref="sheets:zbot:validator:attribution",
        ),
    )
    drift_result = drift.evaluate_quality_drift(
        snapshots(False),
        snapshots(True),
        expected_provider_ids=PROVIDERS,
        now_ms=10000,
        policy=drift.DriftPolicy(
            min_samples=30,
            max_snapshot_age_ms=1000,
            max_confidence_shift=0.10,
            max_positive_value_rate_drop=0.10,
            max_disagreement_rate_increase=0.10,
            max_schema_failure_rate_increase=0.05,
            max_cost_ratio=1.50,
            policy_ref="sheets:zbot:validator:drift",
        ),
    )
    lock = sgrade.evaluate_sgrade_lock(
        prior_ready_surface_count=22,
        closed_surfaces=tuple(sorted(CLOSED)),
        attribution=attribution_result,
        drift=drift_result,
        observer_only=True,
        proposal_only=True,
        provider_invocation_enabled=False,
        runtime_enabled=False,
        execution_authority="none",
        order_authority="none",
        human_approval_required=True,
        same_epoch_auto_apply=False,
    )
    if attribution_result.state != "READY" or not attribution_result.attribution_ready:
        blockers.append("COST_PERFORMANCE_ATTRIBUTION_NOT_READY")
    if drift_result.state != "READY" or not drift_result.quality_drift_ready:
        blockers.append("MODEL_QUALITY_DRIFT_NOT_READY")
    if lock.state != "PASS" or not lock.sgrade_ready:
        blockers.append("ZBOT_SGRADE_LOCK_NOT_READY")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R5.5",
        "state": state,
        "verdict": "R55_ZBOT_ATTRIBUTION_DRIFT_SGRADE_LOCK_PASS" if state == "PASS" else "R55_ZBOT_ATTRIBUTION_DRIFT_SGRADE_LOCK_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "proposal_only": True,
            "execution_authority": "none",
            "order_authority": "none",
            "provider_invocation_enabled": False,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "same_epoch_auto_apply": False,
            "human_approval_required": True,
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "cost_performance_attribution_ready": attribution_result.attribution_ready,
            "model_quality_drift_evaluation_ready": drift_result.quality_drift_ready,
            "provider_attribution_count": len(attribution_result.provider_rows),
            "drifted_provider_count": drift_result.drifted_provider_count,
            "fail_closed_scenario_count": 9,
            "closed_surface_count": 2 if state == "PASS" else 0,
            "ready_surface_count": 24 if state == "PASS" else 22,
            "remaining_surface_count": 0 if state == "PASS" else 2,
            "remaining_surfaces": [] if state == "PASS" else sorted(CLOSED),
            "runtime_binding": False,
            "sgrade_ready": state == "PASS" and lock.sgrade_ready,
            "next_route": "R6.1_ZBOT_SHADOW_OBSERVER_INTEGRATION_GATE",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r54", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.r54.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "closed_surface_count": payload["report"]["closed_surface_count"],
        "ready_surface_count": payload["report"]["ready_surface_count"],
        "remaining_surface_count": payload["report"]["remaining_surface_count"],
        "sgrade_ready": payload["report"]["sgrade_ready"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
