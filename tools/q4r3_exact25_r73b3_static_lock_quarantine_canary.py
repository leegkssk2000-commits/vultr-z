#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

APPROVAL_TOKEN = "R7.3B3_APPLY_STATIC_LOCK_QUARANTINE"
ALLOWED_TARGETS = {
    "zel-s4g8r7f8t-telegram-6c-lock-only.timer",
    "zel-s4g8r7f8t-telegram-6c-lock-only.service",
}


def sha256(path: Path, limit: int | None = None) -> str:
    digest = hashlib.sha256()
    remaining = limit
    with path.open("rb") as handle:
        while True:
            size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
            if size <= 0:
                break
            chunk = handle.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_copy(source: Path, destination: Path, mode: int | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copy2(source, tmp)
        if mode is not None:
            os.chmod(tmp, mode)
        with tmp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, destination)
        fsync_dir(destination.parent)
    finally:
        tmp.unlink(missing_ok=True)


def command(args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=30)


def systemctl_value(unit: str, action: str) -> str:
    result = command(["systemctl", action, unit])
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0].strip() if value else "unknown"


def unit_snapshot(units: list[str]) -> dict[str, dict[str, str]]:
    snapshot: dict[str, dict[str, str]] = {}
    for unit in units:
        result = command([
            "systemctl", "show", unit,
            "-p", "ActiveState", "-p", "SubState", "-p", "UnitFileState", "-p", "MainPID",
        ])
        if result.returncode != 0:
            raise RuntimeError(f"PROTECTED_UNIT_UNREADABLE:{unit}")
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        if values.get("LoadState") == "not-found" or not values.get("ActiveState"):
            raise RuntimeError(f"PROTECTED_UNIT_NOT_RESOLVED:{unit}")
        snapshot[unit] = values
    return snapshot


def protected_file_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for row in manifest["protected_units"]:
        path = Path(row["path"])
        if not path.is_file():
            raise RuntimeError(f"PROTECTED_UNIT_FILE_MISSING:{path}")
        hashes[str(path)] = sha256(path)
    return hashes


def load_inputs(contract_path: Path, manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if contract.get("official_stage") != "R7.3B3":
        raise RuntimeError("CONTRACT_STAGE_INVALID")
    if manifest.get("state") != "PASS" or manifest.get("blocker_count") != 0:
        raise RuntimeError("R73B2_NOT_PASS")
    if manifest.get("target_count") != 2 or manifest.get("protected_unit_count") != 5:
        raise RuntimeError("R73B2_COUNTS_INVALID")
    names = {row.get("unit") for row in manifest.get("targets", [])}
    if names != ALLOWED_TARGETS:
        raise RuntimeError(f"TARGET_SET_INVALID:{sorted(names)}")
    return contract, manifest


def target_preflight(manifest: dict[str, Any]) -> None:
    for row in manifest["targets"]:
        original = Path(row["original_path"])
        if not original.is_file():
            raise RuntimeError(f"TARGET_MISSING:{original}")
        if sha256(original) != row["sha256_before"]:
            raise RuntimeError(f"TARGET_HASH_MISMATCH:{original}")
        active = systemctl_value(row["unit"], "is-active")
        enabled = systemctl_value(row["unit"], "is-enabled")
        if active != "inactive":
            raise RuntimeError(f"TARGET_NOT_INACTIVE:{row['unit']}:{active}")
        if enabled != row["enabled_before"]:
            raise RuntimeError(f"TARGET_ENABLE_STATE_CHANGED:{row['unit']}:{enabled}")


def restore_targets(manifest: dict[str, Any]) -> int:
    restored = 0
    for row in sorted(manifest["targets"], key=lambda item: item["rollback_order"]):
        original = Path(row["original_path"])
        backup = Path(row["planned_backup_path"])
        isolated = Path(row["planned_isolated_path"])
        source = backup if backup.is_file() else isolated
        if not source.is_file() or sha256(source) != row["sha256_before"]:
            raise RuntimeError(f"ROLLBACK_SOURCE_INVALID:{row['unit']}")
        atomic_copy(source, original, int(row["mode_octal"], 8))
        if sha256(original) != row["sha256_before"]:
            raise RuntimeError(f"ROLLBACK_HASH_MISMATCH:{row['unit']}")
        restored += 1
    command(["systemctl", "daemon-reload"], check=True)
    return restored


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    fsync_dir(path.parent)


def apply(contract: dict[str, Any], manifest: dict[str, Any], ledger: Path, status_path: Path) -> int:
    protected_units = [row["unit"] for row in manifest["protected_units"]]
    protected_before = unit_snapshot(protected_units)
    protected_hashes_before = protected_file_hashes(manifest)
    ledger_size = ledger.stat().st_size
    ledger_prefix_before = sha256(ledger, ledger_size)
    target_preflight(manifest)
    rollback_performed = False
    try:
        for row in manifest["targets"]:
            original = Path(row["original_path"])
            backup = Path(row["planned_backup_path"])
            isolated = Path(row["planned_isolated_path"])
            mode = int(row["mode_octal"], 8)
            atomic_copy(original, backup, mode)
            atomic_copy(original, isolated, mode)
            if sha256(backup) != row["sha256_before"]:
                raise RuntimeError(f"BACKUP_HASH_MISMATCH:{row['unit']}")
            if sha256(isolated) != row["sha256_before"]:
                raise RuntimeError(f"ISOLATED_HASH_MISMATCH:{row['unit']}")
        for row in sorted(manifest["targets"], key=lambda item: item["apply_order"]):
            original = Path(row["original_path"])
            original.unlink()
            fsync_dir(original.parent)
        command(["systemctl", "daemon-reload"], check=True)
        if any(Path(row["original_path"]).exists() for row in manifest["targets"]):
            raise RuntimeError("ORIGINAL_TARGET_STILL_PRESENT")
        protected_after = unit_snapshot(protected_units)
        if protected_after != protected_before:
            raise RuntimeError("PROTECTED_UNIT_STATE_CHANGED")
        if protected_file_hashes(manifest) != protected_hashes_before:
            raise RuntimeError("PROTECTED_UNIT_FILE_CHANGED")
        if sha256(ledger, ledger_size) != ledger_prefix_before:
            raise RuntimeError("FORMAL_LEDGER_PREFIX_CHANGED")
        payload = {
            "schema": "q4r3_exact25_r73b3_static_lock_quarantine_canary_status_v1",
            "state": "PASS",
            "blockers": [],
            "blocker_count": 0,
            "target_count": 2,
            "quarantined_count": 2,
            "backup_verified_count": 2,
            "isolated_verified_count": 2,
            "original_absent_count": 2,
            "protected_unit_count": 5,
            "protected_state_change_count": 0,
            "formal_ledger_prefix_change_count": 0,
            "rollback_ready_count": 2,
            "rollback_performed": False,
            "cleanup_applied": True,
            "mutation_count": 2,
            "next_stage": contract["next_stage"],
        }
        write_status(status_path, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        try:
            restored = restore_targets(manifest)
            rollback_performed = restored == 2
        except Exception as rollback_exc:
            exc = RuntimeError(f"{exc};ROLLBACK_FAILED:{rollback_exc}")
        payload = {
            "schema": "q4r3_exact25_r73b3_static_lock_quarantine_canary_status_v1",
            "state": "HOLD",
            "blockers": [str(exc)],
            "blocker_count": 1,
            "target_count": 2,
            "quarantined_count": 0,
            "rollback_performed": rollback_performed,
            "cleanup_applied": False,
            "mutation_count": 0,
            "next_stage": "R7.3B3_REPAIR_OR_ROLLBACK",
        }
        write_status(status_path, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


def rollback(manifest: dict[str, Any], status_path: Path, reason: str) -> int:
    restored = restore_targets(manifest)
    payload = {
        "schema": "q4r3_exact25_r73b3_static_lock_quarantine_canary_status_v1",
        "state": "HOLD",
        "blockers": [reason],
        "blocker_count": 1,
        "target_count": 2,
        "quarantined_count": 0,
        "rollback_performed": restored == 2,
        "cleanup_applied": False,
        "mutation_count": 0,
        "next_stage": "R7.3B3_REPAIR_OR_ROLLBACK",
    }
    write_status(status_path, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if restored == 2 else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--approval-token")
    parser.add_argument("--rollback-reason")
    args = parser.parse_args()
    contract, manifest = load_inputs(args.contract, args.manifest)
    if args.rollback_reason:
        return rollback(manifest, args.status, args.rollback_reason)
    if args.approval_token != APPROVAL_TOKEN:
        raise SystemExit("EXPLICIT_APPROVAL_TOKEN_REQUIRED")
    return apply(contract, manifest, args.ledger, args.status)


if __name__ == "__main__":
    raise SystemExit(main())
