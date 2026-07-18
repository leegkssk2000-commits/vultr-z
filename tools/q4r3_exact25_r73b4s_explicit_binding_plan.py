#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def command(args: list[str]) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_path(exec_start: str) -> Path | None:
    for value in re.findall(r"(/[A-Za-z0-9_./-]+\.(?:py|sh|js))", exec_start):
        path = Path(value)
        if path.is_file():
            return path
    return None


def anchor_lines(text: str, needles: list[str]) -> dict[str, list[int]]:
    rows = text.splitlines()
    return {
        needle: [index for index, line in enumerate(rows, 1) if needle.lower() in line.lower()][:20]
        for needle in needles
    }


def unit_record(item: dict[str, Any], snapshot: Path, forbidden: Path, quarantine: Path) -> dict[str, Any]:
    unit = str(item["unit"])
    active = command(["systemctl", "show", unit, "-p", "ActiveState", "--value"])
    pid = command(["systemctl", "show", unit, "-p", "MainPID", "--value"])
    fragment_value = command(["systemctl", "show", unit, "-p", "FragmentPath", "--value"])
    exec_start = command(["systemctl", "show", unit, "-p", "ExecStart", "--value"])
    working = command(["systemctl", "show", unit, "-p", "WorkingDirectory", "--value"])
    environment = command(["systemctl", "show", unit, "-p", "Environment", "--value"])
    fragment = Path(fragment_value) if fragment_value else None
    source = source_path(exec_start)
    source_text = source.read_text(encoding="utf-8", errors="ignore") if source else ""
    fragment_text = fragment.read_text(encoding="utf-8", errors="ignore") if fragment and fragment.is_file() else ""
    combined = "\n".join((exec_start, working, environment, fragment_text, source_text))
    required_commands = [str(value) for value in item.get("required_commands", [])]
    required_anchor_any = [str(value) for value in item.get("required_anchor_any", [])]
    needles = required_commands + required_anchor_any
    source_anchors = anchor_lines(source_text, needles)
    backup = quarantine / "backup" / (source.name if source else unit + ".missing")
    snapshot_markers = (str(snapshot), str(snapshot.parent), "shadow_aggregate_snapshot")
    return {
        "name": item["name"],
        "unit": unit,
        "active": active,
        "main_pid": pid,
        "fragment_path": str(fragment or ""),
        "fragment_sha256": sha256(fragment) if fragment and fragment.is_file() else "",
        "exec_start": exec_start,
        "working_directory": working,
        "source_path": str(source or ""),
        "source_sha256": sha256(source) if source else "",
        "source_mode_octal": oct(source.stat().st_mode & 0o777) if source else "",
        "source_anchor_lines": source_anchors,
        "required_anchor_any": required_anchor_any,
        "resolved_anchor_any_count": sum(bool(source_anchors.get(value)) for value in required_anchor_any),
        "required_commands": required_commands,
        "required_command_count": len(required_commands),
        "resolved_command_count": sum(command_name in combined for command_name in required_commands),
        "current_snapshot_bound": any(marker in combined for marker in snapshot_markers),
        "current_formal_ledger_bound": str(forbidden) in combined or forbidden.name in combined,
        "planned_backup_path": str(backup),
        "planned_binding_env": f"ZEL_SHADOW_AGGREGATE_SNAPSHOT={snapshot}",
        "planned_patch_scope": "READ_ONLY_SNAPSHOT_CONSUMER_ONLY",
        "planned_apply_method": "BACKUP_SOURCE_AND_UNIT_HASHES_PATCH_SOURCE_AT_RECORDED_ANCHORS_ADD_ENV_OVERRIDE_TARGETED_RESTART_PARITY_CANARY",
        "planned_rollback_method": "RESTORE_VERIFIED_SOURCE_BACKUP_REMOVE_ENV_OVERRIDE_DAEMON_RELOAD_TARGETED_RESTART",
        "rollback_ready": bool(source and SHA_RE.fullmatch(sha256(source)))
    }


def build(contract: dict[str, Any], snapshot_payload: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    snapshot = Path(contract["snapshot"])
    if snapshot_payload.get("owner_id") != "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER":
        blockers.append("SNAPSHOT_OWNER_INVALID")
    if snapshot_payload.get("state") != "PREBIND":
        blockers.append("SNAPSHOT_STATE_INVALID")
    if snapshot_payload.get("sample_count") != 0 or snapshot_payload.get("closed_count") != 0:
        blockers.append("SNAPSHOT_ZERO_EPOCH_INVALID")
    if snapshot_payload.get("formal_ledger_bound") is not False:
        blockers.append("SNAPSHOT_FORMAL_LEDGER_BOUND")
    if len(records) != 2:
        blockers.append("CONSUMER_COUNT_INVALID")
    if sum(row.get("active") == "active" for row in records) != 2:
        blockers.append("CONSUMER_NOT_ACTIVE")
    if sum(bool(row.get("source_path")) for row in records) != 2:
        blockers.append("SOURCE_NOT_RESOLVED")
    if sum(bool(row.get("rollback_ready")) for row in records) != 2:
        blockers.append("ROLLBACK_NOT_READY")
    if sum(bool(row.get("current_snapshot_bound")) for row in records) != 0:
        blockers.append("UNEXPECTED_EXISTING_SNAPSHOT_BINDING")
    if sum(bool(row.get("current_formal_ledger_bound")) for row in records) != 0:
        blockers.append("FORMAL_LEDGER_CONSUMER_BINDING_FOUND")
    telegram = next((row for row in records if row.get("name") == "TELEGRAM_COMMANDS"), {})
    if telegram.get("resolved_command_count") != telegram.get("required_command_count"):
        blockers.append("TELEGRAM_COMMAND_BINDING_INCOMPLETE")
    alimi = next((row for row in records if row.get("name") == "ALIMI_VIEW"), {})
    required_anchor_any = alimi.get("required_anchor_any", [])
    if not required_anchor_any or int(alimi.get("resolved_anchor_any_count", 0)) < 1:
        blockers.append("ALIMI_VIEW_CONTRACT_API_ANCHOR_UNRESOLVED")
    return {
        "schema": "q4r3_exact25_r73b4s_explicit_binding_plan_status_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "read_only": True,
        "mutation_count": 0,
        "snapshot_path": str(snapshot),
        "snapshot_sha256": snapshot_payload.get("snapshot_sha256"),
        "target_snapshot_valid": not any(value.startswith("SNAPSHOT_") for value in blockers),
        "consumer_count": len(records),
        "active_consumer_count": sum(row.get("active") == "active" for row in records),
        "source_resolved_count": sum(bool(row.get("source_path")) for row in records),
        "rollback_ready_count": sum(bool(row.get("rollback_ready")) for row in records),
        "current_snapshot_binding_count": sum(bool(row.get("current_snapshot_bound")) for row in records),
        "current_formal_ledger_binding_count": sum(bool(row.get("current_formal_ledger_bound")) for row in records),
        "consumers": records,
        "planned_apply_method": contract.get("planned_apply_method"),
        "planned_rollback_method": contract.get("planned_rollback_method"),
        "next_stage": contract.get("next_stage")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    snapshot_payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    quarantine = Path(contract["quarantine_root"])
    forbidden = Path(contract["forbidden_source"])
    records = [unit_record(item, args.snapshot, forbidden, quarantine) for item in contract["consumers"]]
    result = build(contract, snapshot_payload, records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "state", "blocker_count", "consumer_count", "active_consumer_count",
        "source_resolved_count", "rollback_ready_count", "current_snapshot_binding_count",
        "current_formal_ledger_binding_count", "mutation_count"
    )}, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
