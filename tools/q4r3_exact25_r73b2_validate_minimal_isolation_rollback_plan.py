#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    expected = contract.get("pass_conditions", {})
    blockers: list[str] = []

    if contract.get("official_stage") != "R7.3B2" or contract.get("mutation_authority") != "none":
        blockers.append("CONTRACT_INVALID")
    if plan.get("state") != "PASS" or plan.get("blocker_count") != 0:
        blockers.append("PLAN_NOT_PASS")
    if plan.get("mutation_count") != 0 or plan.get("cleanup_applied") is not False:
        blockers.append("PLAN_MUTATION_DETECTED")

    for key in (
        "target_count",
        "protected_unit_count",
        "target_protected_overlap_count",
        "missing_target_count",
        "hash_ready_count",
        "rollback_ready_count",
    ):
        if plan.get(key) != expected.get(key):
            blockers.append(f"{key.upper()}_INVALID")

    protected = plan.get("protected_units", [])
    targets = plan.get("targets", [])
    if len(protected) != plan.get("protected_unit_count"):
        blockers.append("PROTECTED_LIST_COUNT_INVALID")
    if len(targets) != plan.get("target_count"):
        blockers.append("TARGET_LIST_COUNT_INVALID")

    protected_names = {str(row.get("unit", "")) for row in protected if isinstance(row, dict)}
    target_names = {str(row.get("unit", "")) for row in targets if isinstance(row, dict)}
    if not protected_names.isdisjoint(target_names):
        blockers.append("TARGET_PROTECTED_OVERLAP")
    if any(not row.get("unit") or not row.get("path") or not row.get("disposition") for row in protected):
        blockers.append("PROTECTED_ENTRY_INVALID")
    for row in targets:
        if not isinstance(row, dict):
            blockers.append("TARGET_ENTRY_INVALID")
            continue
        if row.get("exists_now") is not True:
            blockers.append("TARGET_NOT_PRESENT")
        if not SHA256_RE.fullmatch(str(row.get("sha256_before", ""))):
            blockers.append("TARGET_HASH_INVALID")
        if row.get("rollback_ready") is not True:
            blockers.append("TARGET_ROLLBACK_NOT_READY")
        if not row.get("planned_backup_path") or not row.get("planned_isolated_path"):
            blockers.append("TARGET_PATH_PLAN_INVALID")
        if row.get("planned_method") != contract.get("planned_method"):
            blockers.append("TARGET_METHOD_INVALID")
        if row.get("rollback_method") != contract.get("rollback_method"):
            blockers.append("ROLLBACK_METHOD_INVALID")

    result = {
        "schema": "q4r3_exact25_r73b2_minimal_isolation_rollback_plan_status_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": sorted(set(blockers)),
        "blocker_count": len(set(blockers)),
        "protected_unit_count": plan.get("protected_unit_count", 0),
        "target_count": plan.get("target_count", 0),
        "target_protected_overlap_count": plan.get("target_protected_overlap_count", 0),
        "missing_target_count": plan.get("missing_target_count", 0),
        "hash_ready_count": plan.get("hash_ready_count", 0),
        "rollback_ready_count": plan.get("rollback_ready_count", 0),
        "mutation_count": 0,
        "cleanup_applied": False,
        "next_stage": contract.get("next_stage"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
