#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "q4r3_team_advisor_r52_zbot_canonical_provider_policy_v1"
CLOSED = {
    "unique_canonical_owner",
    "typed_decision_contract",
    "provider_registry",
    "openai_provider_adapter",
    "gemini_provider_adapter",
    "dual_provider_independence",
    "task_routing_policy",
    "privacy_secret_boundary",
    "human_approval_boundary",
    "point_in_time_guard",
    "input_evidence_lineage",
    "same_epoch_guard",
}
REMAINING = {
    "audit_receipt",
    "budget_token_accounting",
    "cost_performance_attribution",
    "disagreement_arbitration",
    "idempotency_cache_dedup",
    "model_quality_drift_evaluation",
    "prompt_versioning",
    "response_normalization",
    "response_schema_validation",
    "timeout_retry_circuit_breaker",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("canonical_zbot_r52", path)
    if not spec or not spec.loader:
        raise RuntimeError("ZBOT_MODULE_SPEC_INVALID")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def owner_paths(worktree: Path) -> list[str]:
    found: list[Path] = []
    direct = worktree / "canonical/zbot.py"
    if direct.is_file():
        found.append(direct)
    package = worktree / "canonical/zbot"
    if package.exists():
        found.extend(path for path in package.rglob("*") if path.is_file())
    return sorted(str(path.relative_to(worktree)) for path in found)


def sample_request(module):
    evidence = module.EvidenceItem(
        evidence_id="evidence.r52.validator",
        source_ref="cf:zbot:validator",
        available_at_ms=9900,
        schema_version="r52-validator",
    )
    request = module.ZBotTaskRequest(
        request_id="zbot.r52.validator",
        task_kind="risk_review",
        decision_ts_ms=10000,
        epoch_id="shadow.r52.validator",
        evidence=(evidence,),
        payload={"symbol": "BTCUSDT", "mode": "review"},
        requested_action="hold",
    )
    return module.build_provider_requests(request)


def validate(worktree: Path, r51_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r51 = read_json(r51_path)
    contract = read_json(contract_path)
    owner = worktree / "canonical/zbot.py"
    owners = owner_paths(worktree)

    if r51.get("state") != "HOLD" or r51.get("blockers"):
        blockers.append("R51_GAP_CLASSIFICATION_INVALID")
    report51 = r51.get("report", {})
    if report51.get("next_route") != "R5.2_ZBOT_CANONICAL_PROVIDER_POLICY":
        blockers.append("R51_NEXT_ROUTE_INVALID")
    if int(report51.get("ready_surface_count", -1)) != 2:
        blockers.append("R51_READY_SURFACE_COUNT_INVALID")
    if int(report51.get("missing_surface_count", -1)) != 22:
        blockers.append("R51_MISSING_SURFACE_COUNT_INVALID")
    if not CLOSED.issubset(set(report51.get("missing_surfaces", []))):
        blockers.append("R51_REQUIRED_GAPS_NOT_PROVEN")

    if owners != ["canonical/zbot.py"]:
        blockers.append("ZBOT_CANONICAL_OWNER_NOT_UNIQUE")
    if contract.get("schema") != "q4r3_zbot_canonical_provider_policy_v1":
        blockers.append("ZBOT_CONTRACT_SCHEMA_INVALID")
    if set(contract.get("closed_surfaces", [])) != CLOSED:
        blockers.append("ZBOT_CLOSED_SURFACE_SET_INVALID")
    if set(contract.get("remaining_surfaces", [])) != REMAINING:
        blockers.append("ZBOT_REMAINING_SURFACE_SET_INVALID")

    module = None
    if owner.is_file():
        try:
            module = load_module(owner)
        except Exception as exc:
            blockers.append(f"ZBOT_IMPORT_FAILED:{type(exc).__name__}")
    else:
        blockers.append("ZBOT_CANONICAL_OWNER_MISSING")

    dual_ready = False
    point_in_time_ready = False
    lineage_ready = False
    privacy_ready = False
    if module is not None:
        if module.ZBOT_OWNER != "canonical/zbot.py":
            blockers.append("ZBOT_OWNER_IDENTITY_INVALID")
        if set(module.PROVIDER_REGISTRY) != {"openai", "gemini"}:
            blockers.append("ZBOT_PROVIDER_REGISTRY_INVALID")
        if module.RUNTIME_ENABLED or module.SAME_EPOCH_AUTO_APPLY:
            blockers.append("ZBOT_RUNTIME_OR_AUTO_APPLY_ENABLED")
        if module.EXECUTION_AUTHORITY != "none" or module.ORDER_AUTHORITY != "none":
            blockers.append("ZBOT_AUTHORITY_BOUNDARY_INVALID")
        if not module.HUMAN_APPROVAL_REQUIRED or not module.PROPOSAL_ONLY:
            blockers.append("ZBOT_HUMAN_APPROVAL_BOUNDARY_INVALID")

        result = sample_request(module)
        dual_ready = result.state == "PROPOSAL_READY" and result.dual_provider_independent and len(result.provider_requests) == 2
        point_in_time_ready = result.point_in_time_valid
        lineage_ready = result.input_lineage_valid and len(result.input_evidence_ids) == 1
        privacy_ready = result.privacy_boundary_valid
        if not dual_ready:
            blockers.append("ZBOT_DUAL_PROVIDER_POLICY_NOT_READY")
        if not point_in_time_ready:
            blockers.append("ZBOT_POINT_IN_TIME_GUARD_NOT_READY")
        if not lineage_ready:
            blockers.append("ZBOT_INPUT_LINEAGE_NOT_READY")
        if not privacy_ready:
            blockers.append("ZBOT_PRIVACY_BOUNDARY_NOT_READY")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R5.2",
        "state": state,
        "verdict": "R52_ZBOT_CANONICAL_PROVIDER_POLICY_PASS" if state == "PASS" else "R52_ZBOT_CANONICAL_PROVIDER_POLICY_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "proposal_only": True,
            "execution_authority": "none",
            "order_authority": "none",
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "same_epoch_auto_apply": False,
            "human_approval_required": True,
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "canonical_owner_count": len(owners),
            "canonical_owner_paths": owners,
            "provider_registry_count": 2 if module is not None else 0,
            "openai_provider_policy_ready": module is not None and "openai" in module.PROVIDER_REGISTRY,
            "gemini_provider_policy_ready": module is not None and "gemini" in module.PROVIDER_REGISTRY,
            "dual_provider_independence_ready": dual_ready,
            "task_routing_policy_ready": module is not None and len(module.ROUTE_POLICY) == 5,
            "point_in_time_guard_ready": point_in_time_ready,
            "input_evidence_lineage_ready": lineage_ready,
            "privacy_boundary_ready": privacy_ready,
            "human_approval_boundary_ready": module is not None and module.HUMAN_APPROVAL_REQUIRED,
            "same_epoch_guard_ready": module is not None and not module.SAME_EPOCH_AUTO_APPLY,
            "closed_surface_count": len(CLOSED) if state == "PASS" else 0,
            "ready_surface_count": 14 if state == "PASS" else 2,
            "remaining_surface_count": len(REMAINING),
            "remaining_surfaces": sorted(REMAINING),
            "runtime_binding": False,
            "sgrade_ready": False,
            "next_route": "R5.3_ZBOT_RELIABILITY_BUDGET_PROMPT_IDEMPOTENCY",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r51", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.worktree.resolve(), args.r51.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "canonical_owner_count": payload["report"]["canonical_owner_count"],
        "provider_registry_count": payload["report"]["provider_registry_count"],
        "closed_surface_count": payload["report"]["closed_surface_count"],
        "remaining_surface_count": payload["report"]["remaining_surface_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
