#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

Probe = Callable[[str, str], str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def systemctl_probe(unit: str, mode: str) -> str:
    result = subprocess.run(
        ["systemctl", mode, unit],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    value = result.stdout.strip()
    return value or f"rc={result.returncode}"


def build(
    contract: dict[str, Any],
    status: dict[str, Any],
    disposition: dict[str, Any],
    *,
    probe: Probe = systemctl_probe,
) -> dict[str, Any]:
    blockers: list[str] = []
    deps = contract.get("dependencies", {})
    expected_counts = {
        "raw_writer_candidate_count": deps.get("raw_writer_candidate_count"),
        "canonical_writer_unit_count": deps.get("canonical_writer_unit_count"),
        "static_lock_count": deps.get("static_lock_count"),
    }
    if status.get("state") != deps.get("r73b1_state") or status.get("blocker_count") != deps.get("r73b1_blocker_count"):
        blockers.append("R73B1_NOT_PASS")
    if status.get("cleanup_applied") is not deps.get("r73b1_cleanup_applied"):
        blockers.append("R73B1_MUTATION_STATE_INVALID")
    for key, expected in expected_counts.items():
        if status.get(key) != expected or disposition.get(key) != expected:
            blockers.append(f"R73B1_{key.upper()}_MISMATCH")

    preserved = []
    allowed_preserved = set(contract.get("required_preserved_dispositions", []))
    for row in disposition.get("writer_candidates", []):
        if not isinstance(row, dict):
            continue
        if row.get("disposition") in allowed_preserved:
            preserved.append({
                "unit": row.get("unit"),
                "path": row.get("path"),
                "disposition": row.get("disposition"),
            })

    target_disposition = contract.get("target_disposition")
    targets_raw = [
        row for row in disposition.get("static_locks", [])
        if isinstance(row, dict) and row.get("disposition") == target_disposition
    ]
    target_units = [str(row.get("unit", "")) for row in targets_raw]
    protected_units = {str(row.get("unit", "")) for row in preserved}
    overlap = sorted(unit for unit in target_units if unit in protected_units)
    if overlap:
        blockers.append("TARGET_PROTECTED_OVERLAP")
    if len(preserved) != int(contract.get("pass_conditions", {}).get("protected_unit_count", -1)):
        blockers.append("PROTECTED_UNIT_COUNT_MISMATCH")
    if len(targets_raw) != int(contract.get("pass_conditions", {}).get("target_count", -1)):
        blockers.append("TARGET_COUNT_MISMATCH")
    if len(set(target_units)) != len(target_units) or any(not unit for unit in target_units):
        blockers.append("TARGET_UNIT_ID_INVALID")

    quarantine_root = Path(str(contract.get("quarantine_root")))
    target_plan = []
    missing_target_count = 0
    hash_ready_count = 0
    rollback_ready_count = 0
    for row in sorted(targets_raw, key=lambda item: str(item.get("unit", "")), reverse=True):
        unit = str(row.get("unit", ""))
        original = Path(str(row.get("path", "")))
        exists = original.is_file()
        if not exists:
            missing_target_count += 1
        digest = sha256_file(original) if exists else ""
        if digest:
            hash_ready_count += 1
        backup = quarantine_root / "backup" / unit
        isolated = quarantine_root / "isolated" / unit
        rollback_ready = bool(unit and original and digest and backup and isolated)
        if rollback_ready:
            rollback_ready_count += 1
        target_plan.append({
            "unit": unit,
            "original_path": str(original),
            "exists_now": exists,
            "size_bytes": original.stat().st_size if exists else 0,
            "mode_octal": oct(original.stat().st_mode & 0o777) if exists else "",
            "sha256_before": digest,
            "active_before": probe(unit, "is-active"),
            "enabled_before": probe(unit, "is-enabled"),
            "planned_backup_path": str(backup),
            "planned_isolated_path": str(isolated),
            "planned_method": contract.get("planned_method"),
            "rollback_method": contract.get("rollback_method"),
            "rollback_ready": rollback_ready,
            "apply_order": 1 if unit.endswith(".timer") else 2,
            "rollback_order": 1 if unit.endswith(".service") else 2,
        })

    if missing_target_count:
        blockers.append("TARGET_FILE_MISSING")
    if hash_ready_count != int(contract.get("pass_conditions", {}).get("hash_ready_count", -1)):
        blockers.append("TARGET_HASH_NOT_READY")
    if rollback_ready_count != int(contract.get("pass_conditions", {}).get("rollback_ready_count", -1)):
        blockers.append("ROLLBACK_NOT_READY")

    return {
        "schema": "q4r3_exact25_r73b2_minimal_isolation_rollback_plan_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "mutation_count": 0,
        "cleanup_applied": False,
        "raw_writer_candidate_count": status.get("raw_writer_candidate_count", 0),
        "canonical_writer_unit_count": status.get("canonical_writer_unit_count", 0),
        "protected_unit_count": len(preserved),
        "protected_units": preserved,
        "target_count": len(target_plan),
        "target_protected_overlap_count": len(overlap),
        "missing_target_count": missing_target_count,
        "hash_ready_count": hash_ready_count,
        "rollback_ready_count": rollback_ready_count,
        "targets": target_plan,
        "planned_method": contract.get("planned_method"),
        "rollback_method": contract.get("rollback_method"),
        "quarantine_root": str(quarantine_root),
        "next_stage": contract.get("next_stage"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--disposition", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        json.loads(args.contract.read_text(encoding="utf-8")),
        json.loads(args.status.read_text(encoding="utf-8")),
        json.loads(args.disposition.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "blocker_count": result["blocker_count"],
        "protected_unit_count": result["protected_unit_count"],
        "target_count": result["target_count"],
        "hash_ready_count": result["hash_ready_count"],
        "rollback_ready_count": result["rollback_ready_count"],
        "mutation_count": 0,
    }, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
