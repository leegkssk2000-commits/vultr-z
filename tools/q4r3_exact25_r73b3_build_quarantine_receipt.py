#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state(unit: str, action: str) -> str:
    result = subprocess.run(["systemctl", action, unit], text=True, capture_output=True, check=False, timeout=20)
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0].strip() if lines else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    status = json.loads(args.status.read_text(encoding="utf-8"))
    targets: list[dict[str, object]] = []
    blockers: list[str] = []
    for row in manifest["targets"]:
        original = Path(row["original_path"])
        backup = Path(row["planned_backup_path"])
        isolated = Path(row["planned_isolated_path"])
        expected = row["sha256_before"]
        record = {
            "unit": row["unit"],
            "original_path": str(original),
            "original_absent": not original.exists(),
            "backup_path": str(backup),
            "backup_exists": backup.is_file(),
            "backup_sha256": sha256(backup) if backup.is_file() else None,
            "isolated_path": str(isolated),
            "isolated_exists": isolated.is_file(),
            "isolated_sha256": sha256(isolated) if isolated.is_file() else None,
            "expected_sha256": expected,
            "active_after": state(row["unit"], "is-active"),
            "enabled_after": state(row["unit"], "is-enabled"),
        }
        if not record["original_absent"]:
            blockers.append(f"ORIGINAL_PRESENT:{row['unit']}")
        if record["backup_sha256"] != expected:
            blockers.append(f"BACKUP_HASH_INVALID:{row['unit']}")
        if record["isolated_sha256"] != expected:
            blockers.append(f"ISOLATED_HASH_INVALID:{row['unit']}")
        targets.append(record)
    if status.get("state") != "PASS":
        blockers.append("CANARY_STATUS_NOT_PASS")
    receipt = {
        "schema": "q4r3_exact25_r73b3_static_lock_quarantine_receipt_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "target_count": len(targets),
        "original_absent_count": sum(bool(row["original_absent"]) for row in targets),
        "backup_verified_count": sum(row["backup_sha256"] == row["expected_sha256"] for row in targets),
        "isolated_verified_count": sum(row["isolated_sha256"] == row["expected_sha256"] for row in targets),
        "targets": targets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in (
        "state", "blocker_count", "target_count", "original_absent_count",
        "backup_verified_count", "isolated_verified_count",
    )}, sort_keys=True))
    return 0 if receipt["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
