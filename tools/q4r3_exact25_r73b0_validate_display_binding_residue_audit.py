#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

GROUPS = {
    "active_units", "active_timers", "unit_file_hits", "script_hits",
    "runtime_artifacts", "static_lock_hits", "writer_candidates", "archive_or_backup_hits",
}
AUDIT_SCHEMAS = {
    "q4r3_exact25_r73b0_display_binding_residue_audit_v1",
    "q4r3_exact25_r73b0_display_binding_residue_audit_v2",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    blockers: list[str] = []
    if contract.get("official_stage") != "R7.3B0":
        blockers.append("CONTRACT_STAGE_INVALID")
    if audit.get("schema") not in AUDIT_SCHEMAS:
        blockers.append("AUDIT_SCHEMA_INVALID")
    authority = contract.get("authority", {})
    forbidden_true = [key for key, value in authority.items() if key.endswith("_allowed") and value is True]
    if forbidden_true:
        blockers.append("MUTATION_AUTHORITY_OPEN")
    if audit.get("state") != "PASS" or audit.get("blocker_count") != 0:
        blockers.append("AUDIT_NOT_PASS")
    if audit.get("required_scan_root_error_count", 0) != 0:
        blockers.append("REQUIRED_SCAN_ROOT_UNREADABLE")
    if audit.get("systemctl_errors"):
        blockers.append("SYSTEMD_QUERY_FAILED")
    if audit.get("mutation_count") != 0 or audit.get("cleanup_applied") is not False:
        blockers.append("AUDIT_MUTATION_DETECTED")
    if set(audit.get("groups", {})) != GROUPS:
        blockers.append("INVENTORY_GROUPS_INCOMPLETE")
    if audit.get("record_count", -1) < 0:
        blockers.append("RECORD_COUNT_INVALID")
    result = {
        "schema": "q4r3_exact25_r73b0_display_binding_residue_audit_status_v2",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "warnings": audit.get("warnings", []),
        "warning_count": audit.get("warning_count", 0),
        "optional_scan_root_missing_count": audit.get("optional_scan_root_missing_count", 0),
        "optional_scan_root_missing": audit.get("optional_scan_root_missing", []),
        "inventory_complete": not blockers,
        "cleanup_applied": False,
        "record_count": audit.get("record_count", 0),
        "suppressed_noncritical_record_count": audit.get("suppressed_noncritical_record_count", 0),
        "writer_candidate_count": len(audit.get("groups", {}).get("writer_candidates", [])),
        "static_lock_count": len(audit.get("groups", {}).get("static_lock_hits", [])),
        "next_stage": "R7.3B1_SINGLE_OWNER_QUARANTINE_PLAN",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
