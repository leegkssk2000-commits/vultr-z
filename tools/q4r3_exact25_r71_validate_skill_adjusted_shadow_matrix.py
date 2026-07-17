#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.engine.exact25_skill_shadow_matrix_candidate import (
    SourceEntry,
    build_raw_baseline_plan,
    validate_contract,
    validate_planned_loss,
    validate_skill_set,
)
from tools.q4r3_exact25_skill_registry_v2_audit import discover_exact25

SCHEMA = "q4r3_exact25_r71_skill_adjusted_shadow_matrix_contract_v1"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sample_entries(strategy_ids: list[str], manifest_sha256: str) -> list[SourceEntry]:
    digest = "sha256:" + manifest_sha256
    return [
        SourceEntry(
            matrix_epoch_id="q4.shadow.r71.contract.audit",
            source_position_id=f"contract.source.{index:03d}",
            source_entry_event_id=f"contract.entry.{index:03d}",
            strategy_id=strategy_id,
            strategy_source_sha256=digest,
            method_id="intraday/breakout_probe",
            symbol="BTCUSDT" if index % 2 == 0 else "ETHUSDT",
            side="long" if index % 3 else "short",
            entry_ts=10000 + index,
            entry_price=100.0 + index,
            market_path_id="contract.market.path.shared",
        )
        for index, strategy_id in enumerate(strategy_ids)
    ]


def fail_closed_count(contract: dict[str, Any], registry: dict[str, Any], entries: list[SourceEntry]) -> int:
    passed = 0

    bad = copy.deepcopy(contract)
    bad["authority"]["provider_invocation_enabled"] = True
    if "AUTHORITY_FLAG_INVALID:provider_invocation_enabled" in validate_contract(bad, registry):
        passed += 1

    bad = copy.deepcopy(contract)
    bad["dependency_contract"]["r64_external_canary_required_for_shadow_matrix"] = True
    if "R64_DEPENDENCY_MUST_BE_FALSE" in validate_contract(bad, registry):
        passed += 1

    bad = copy.deepcopy(contract)
    bad["risk_budget_contract"]["research_total_planned_loss_cap_r"] = 1.0
    if "RESEARCH_RISK_CAP_INVALID" in validate_contract(bad, registry):
        passed += 1

    bad_registry = copy.deepcopy(registry)
    bad_registry["skills"] = bad_registry.get("skills", [])[:-1]
    if "SKILL_PARTITIONS_DO_NOT_COVER_REGISTRY" in validate_contract(contract, bad_registry):
        passed += 1

    if build_raw_baseline_plan(entries[:-1], contract, registry).state == "HOLD":
        passed += 1

    if "LOSS_AND_PROFIT_ADD_COMBINATION_FORBIDDEN" in validate_skill_set(
        ("SK_ADD_DCA", "SK_ADD_PYRAMIDING"), contract
    ):
        passed += 1

    if validate_planned_loss(0.751, contract) == ("AGGREGATE_PLANNED_LOSS_CAP_EXCEEDED",):
        passed += 1

    return passed


def validate(
    contract_path: Path,
    registry_path: Path,
    event_contract_path: Path,
    r63_status_path: Path,
) -> dict[str, Any]:
    blockers: list[str] = []
    contract = read_json(contract_path)
    registry = read_json(registry_path)
    event_contract = read_json(event_contract_path)
    r63 = read_json(r63_status_path)

    contract_errors = validate_contract(contract, registry) if contract and registry else ("CONTRACT_OR_REGISTRY_MISSING",)
    blockers.extend(contract_errors)

    exact25 = discover_exact25()
    selected = exact25.get("selected") if isinstance(exact25, dict) else None
    strategy_ids = list(selected.get("names", [])) if isinstance(selected, dict) else []
    manifest_sha = str(selected.get("sha256", "")) if isinstance(selected, dict) else ""
    if exact25.get("state") != "PASS" or len(strategy_ids) != 25 or len(set(strategy_ids)) != 25:
        blockers.append("UNIQUE_EXACT25_MANIFEST_NOT_PROVEN")
    if len(manifest_sha) != 64:
        blockers.append("EXACT25_MANIFEST_DIGEST_INVALID")

    if event_contract.get("schema") != "zos_skill_event_contract_v1":
        blockers.append("SKILL_EVENT_CONTRACT_INVALID")
    if event_contract.get("observer_only") is not True:
        blockers.append("SKILL_EVENT_OBSERVER_BOUNDARY_INVALID")
    if event_contract.get("historical_backfill_allowed") is not False:
        blockers.append("SKILL_EVENT_BACKFILL_BOUNDARY_INVALID")

    if r63.get("state") != "PASS" or r63.get("blockers"):
        blockers.append("R63_PASS_NOT_PROVEN")
    r63_authority = r63.get("authority", {})
    if r63_authority.get("provider_invocation_enabled") is not False:
        blockers.append("R63_PROVIDER_BOUNDARY_INVALID")
    if r63_authority.get("network_access_enabled") is not False:
        blockers.append("R63_NETWORK_BOUNDARY_INVALID")

    entries = sample_entries(strategy_ids, manifest_sha) if len(strategy_ids) == 25 and len(manifest_sha) == 64 else []
    plan = build_raw_baseline_plan(entries, contract, registry) if contract and registry else None
    if plan is None or plan.state != "PLAN_READY" or plan.lane_count != 100:
        blockers.append("RAW_100_LANE_PLAN_NOT_READY")

    closed = fail_closed_count(contract, registry, entries) if entries and contract and registry else 0
    if closed != 7:
        blockers.append("FAIL_CLOSED_SCENARIOS_INCOMPLETE")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R7.1",
        "state": state,
        "verdict": "R71_EXACT25_SKILL_ADJUSTED_SHADOW_MATRIX_CONTRACT_PASS" if state == "PASS" else "R71_EXACT25_SKILL_ADJUSTED_SHADOW_MATRIX_CONTRACT_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "runtime_binding_allowed": False,
            "strategy_mutation_performed": False,
            "skill_registry_mutation_performed": False,
            "producer_mutation_performed": False,
            "writer_mutation_performed": False,
            "formal_ledger_mutation_performed": False,
            "provider_invocation_enabled": False,
            "network_access_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
            "r64_external_canary_required": False,
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "exact25_manifest_path": selected.get("path") if isinstance(selected, dict) else None,
            "strategy_count": len(strategy_ids),
            "method_profile_count": contract.get("dependency_contract", {}).get("method_profile_count", 0),
            "skill_count": len(registry.get("skills", [])) if isinstance(registry.get("skills"), list) else 0,
            "entry_ablation_skill_count": len(contract.get("skill_partitions", {}).get("entry_ablation_skills", [])),
            "single_skill_management_candidate_count": len(contract.get("skill_partitions", {}).get("single_skill_management_candidates", [])),
            "mandatory_guardrail_skill_count": len(contract.get("skill_partitions", {}).get("mandatory_guardrail_skills", [])),
            "exit_policy_count": len(contract.get("exit_policy_lanes", [])),
            "raw_baseline_lane_count": plan.lane_count if plan else 0,
            "fail_closed_scenario_count": closed,
            "aggregate_planned_loss_cap_r": contract.get("risk_budget_contract", {}).get("research_total_planned_loss_cap_r"),
            "original_25_immutable": contract.get("selection_policy", {}).get("original_25_archived_as_immutable_controls") is True,
            "automatic_promotion_enabled": False,
            "matrix_runtime_active": False,
            "next_route": "R7.2_EXACT25_RAW_100_LANE_SHADOW_PROJECTION",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--event-contract", type=Path, required=True)
    parser.add_argument("--r63", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(
        args.contract.resolve(),
        args.registry.resolve(),
        args.event_contract.resolve(),
        args.r63.resolve(),
    )
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "strategy_count": payload["report"]["strategy_count"],
        "skill_count": payload["report"]["skill_count"],
        "exit_policy_count": payload["report"]["exit_policy_count"],
        "raw_baseline_lane_count": payload["report"]["raw_baseline_lane_count"],
        "fail_closed_scenario_count": payload["report"]["fail_closed_scenario_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
