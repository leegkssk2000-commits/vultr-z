#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.engine.exact25_raw_100_lane_projection import build_projection_manifest
from tools.q4r3_exact25_skill_registry_v2_audit import discover_exact25

SCHEMA = "q4r3_exact25_r72_raw_100_lane_shadow_projection_v1"


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


def fail_closed_count(
    strategy_ids: list[str],
    manifest_sha: str,
    matrix_contract: dict[str, Any],
    r71: dict[str, Any],
    projection_contract: dict[str, Any],
) -> int:
    passed = 0

    bad = copy.deepcopy(r71)
    bad["state"] = "HOLD"
    result = build_projection_manifest(strategy_ids, manifest_sha, matrix_contract, bad, projection_contract)
    if result.state == "HOLD" and "R71_PASS_NOT_PROVEN" in result.reason_codes:
        passed += 1

    bad_strategies = list(strategy_ids)
    bad_strategies[-1] = bad_strategies[0]
    result = build_projection_manifest(bad_strategies, manifest_sha, matrix_contract, r71, projection_contract)
    if result.state == "HOLD" and "UNIQUE_EXACT25_NOT_PROVEN" in result.reason_codes:
        passed += 1

    result = build_projection_manifest(strategy_ids, "bad", matrix_contract, r71, projection_contract)
    if result.state == "HOLD" and "EXACT25_MANIFEST_DIGEST_INVALID" in result.reason_codes:
        passed += 1

    bad = copy.deepcopy(matrix_contract)
    bad["exit_policy_lanes"] = bad.get("exit_policy_lanes", [])[:-1]
    result = build_projection_manifest(strategy_ids, manifest_sha, bad, r71, projection_contract)
    if result.state == "HOLD" and "MATRIX_EXIT_POLICY_SET_INVALID" in result.reason_codes:
        passed += 1

    bad = copy.deepcopy(projection_contract)
    bad["authority"]["runtime_binding_allowed"] = True
    result = build_projection_manifest(strategy_ids, manifest_sha, matrix_contract, r71, bad)
    if result.state == "HOLD" and "AUTHORITY_FLAG_INVALID:runtime_binding_allowed" in result.reason_codes:
        passed += 1

    bad = copy.deepcopy(projection_contract)
    bad["dependencies"]["raw_skill_set_required"] = ["SK_EXIT_PARTIAL_30"]
    result = build_projection_manifest(strategy_ids, manifest_sha, matrix_contract, r71, bad)
    if result.state == "HOLD" and "RAW_SKILL_SET_MUST_BE_EMPTY" in result.reason_codes:
        passed += 1

    bad = copy.deepcopy(projection_contract)
    bad["projection_rules"]["cross_lane_state_sharing_forbidden"] = False
    result = build_projection_manifest(strategy_ids, manifest_sha, matrix_contract, r71, bad)
    if result.state == "HOLD" and "PROJECTION_RULE_INVALID:cross_lane_state_sharing_forbidden" in result.reason_codes:
        passed += 1

    return passed


def validate(
    projection_contract_path: Path,
    matrix_contract_path: Path,
    r71_status_path: Path,
    projection_output_path: Path,
) -> dict[str, Any]:
    blockers: list[str] = []
    projection_contract = read_json(projection_contract_path)
    matrix_contract = read_json(matrix_contract_path)
    r71 = read_json(r71_status_path)

    exact25 = discover_exact25()
    selected = exact25.get("selected") if isinstance(exact25, dict) else None
    strategy_ids = list(selected.get("names", [])) if isinstance(selected, dict) else []
    manifest_sha = str(selected.get("sha256", "")) if isinstance(selected, dict) else ""
    if exact25.get("state") != "PASS":
        blockers.append("EXACT25_DISCOVERY_NOT_PASS")

    projection = build_projection_manifest(
        strategy_ids,
        manifest_sha,
        matrix_contract,
        r71,
        projection_contract,
    )
    if projection.state != "PROJECTION_READY":
        blockers.extend(projection.reason_codes)
    if projection.lane_template_count != 100:
        blockers.append("RAW_100_TEMPLATE_COUNT_NOT_PROVEN")
    if projection.runtime_active is not False:
        blockers.append("RUNTIME_MUST_REMAIN_INACTIVE")
    if projection.source_event_subscription_allowed is not False:
        blockers.append("SOURCE_SUBSCRIPTION_MUST_REMAIN_DISABLED")
    if projection.formal_ledger_write_allowed is not False:
        blockers.append("FORMAL_LEDGER_WRITE_MUST_REMAIN_DISABLED")

    fail_closed = (
        fail_closed_count(strategy_ids, manifest_sha, matrix_contract, r71, projection_contract)
        if len(strategy_ids) == 25 and len(manifest_sha) == 64
        else 0
    )
    if fail_closed != 7:
        blockers.append("FAIL_CLOSED_SCENARIOS_INCOMPLETE")

    atomic_json(projection_output_path, projection.as_payload())
    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R7.2",
        "state": state,
        "verdict": "R72_RAW_100_LANE_PROJECTION_PASS" if state == "PASS" else "R72_RAW_100_LANE_PROJECTION_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "runtime_binding_allowed": False,
            "source_event_subscription_allowed": False,
            "projection_state_write_allowed": False,
            "producer_mutation_performed": False,
            "writer_mutation_performed": False,
            "formal_ledger_mutation_performed": False,
            "provider_invocation_enabled": False,
            "network_call_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "exact25_manifest_path": selected.get("path") if isinstance(selected, dict) else None,
            "strategy_count": projection.strategy_count,
            "exit_policy_count": projection.exit_policy_count,
            "lane_template_count": projection.lane_template_count,
            "projection_sha256": projection.projection_sha256,
            "fail_closed_scenario_count": fail_closed,
            "templates_are_positions": False,
            "sparse_event_instantiation_required": True,
            "runtime_active": False,
            "source_event_subscription_active": False,
            "next_route": "R7.3_20C_INTEGRITY_COST_PARITY_SIDECAR_CANARY",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-contract", type=Path, required=True)
    parser.add_argument("--matrix-contract", type=Path, required=True)
    parser.add_argument("--r71", type=Path, required=True)
    parser.add_argument("--projection-output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(
        args.projection_contract.resolve(),
        args.matrix_contract.resolve(),
        args.r71.resolve(),
        args.projection_output.resolve(),
    )
    atomic_json(args.status_output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "strategy_count": payload["report"]["strategy_count"],
        "exit_policy_count": payload["report"]["exit_policy_count"],
        "lane_template_count": payload["report"]["lane_template_count"],
        "fail_closed_scenario_count": payload["report"]["fail_closed_scenario_count"],
        "runtime_active": payload["report"]["runtime_active"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
