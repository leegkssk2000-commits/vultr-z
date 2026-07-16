#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA = "q4r3_team_advisor_r51_zbot_sgrade_gap_audit_v1"
EXPECTED_CONTRACT = "q4r3_zbot_sgrade_audit_contract_v1"
EXPECTED_SURFACES = 24


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()

    payload = read_json(args.status.resolve())
    contract = read_json(args.contract.resolve())
    report = payload.get("report", {})
    authority = payload.get("authority", {})
    errors: list[str] = []

    if payload.get("schema") != EXPECTED_SCHEMA:
        errors.append("R51_SCHEMA_INVALID")
    if payload.get("official_stage") != "R5.1":
        errors.append("R51_STAGE_INVALID")
    if payload.get("state") not in {"PASS", "HOLD"}:
        errors.append("R51_STATE_INVALID")
    if payload.get("action") != "hold":
        errors.append("R51_ACTION_INVALID")
    if authority.get("execution_authority") != "none" or not authority.get("observer_only"):
        errors.append("R51_AUTHORITY_INVALID")
    if authority.get("runtime_mutation_performed") or authority.get("systemd_mutation_performed"):
        errors.append("R51_MUTATION_DETECTED")
    if authority.get("same_epoch_auto_apply"):
        errors.append("R51_SAME_EPOCH_AUTO_APPLY_INVALID")
    if report.get("required_surface_count") != EXPECTED_SURFACES:
        errors.append("R51_SURFACE_SCHEMA_INVALID")
    if report.get("ready_surface_count", 0) + report.get("missing_surface_count", 0) != EXPECTED_SURFACES:
        errors.append("R51_SURFACE_COUNT_MISMATCH")
    if report.get("canonical_owner_count") != len(report.get("canonical_owner_paths", [])):
        errors.append("R51_OWNER_COUNT_MISMATCH")
    if report.get("candidate_count") != len(report.get("candidates", [])):
        errors.append("R51_CANDIDATE_COUNT_MISMATCH")
    if contract.get("schema") != EXPECTED_CONTRACT or contract.get("required_surfaces") != EXPECTED_SURFACES:
        errors.append("R51_CONTRACT_INVALID")
    contract_authority = contract.get("authority", {})
    if contract_authority.get("execution_authority") != "none" or not contract_authority.get("human_approval_required"):
        errors.append("R51_CONTRACT_AUTHORITY_INVALID")

    print(json.dumps({
        "audit_valid": not errors,
        "state": payload.get("state"),
        "validation_error_count": len(errors),
        "validation_errors": sorted(set(errors)),
    }, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
