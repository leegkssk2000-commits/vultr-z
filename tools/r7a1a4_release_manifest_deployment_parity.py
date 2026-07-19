#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256_bytes(path.read_bytes())


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def git_bytes(root: Path, ref: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def compile_ok(data: bytes | None, label: str) -> bool:
    if data is None:
        return False
    try:
        compile(data.decode("utf-8"), label, "exec")
        return True
    except Exception:
        return False


def command_counts(data: bytes | None, commands: list[str]) -> dict[str, int]:
    text = data.decode("utf-8", errors="replace") if data is not None else ""
    return {command: text.count(command) for command in commands}


def discover_environment_keys(data: bytes | None) -> list[str]:
    if data is None:
        return []
    try:
        tree = ast.parse(data.decode("utf-8"))
    except Exception:
        return []
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        is_get = (
            isinstance(func, ast.Attribute)
            and func.attr in {"get", "getenv"}
            and isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "os"
            and func.value.attr == "environ"
        )
        is_getenv = (
            isinstance(func, ast.Attribute)
            and func.attr == "getenv"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        )
        if not (is_get or is_getenv):
            continue
        key_node = node.args[0]
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            keys.add(key_node.value)
    return sorted(keys)


def hardcoded_sensitive_assignment_count(data: bytes | None) -> int:
    if data is None:
        return 0
    try:
        tree = ast.parse(data.decode("utf-8"))
    except Exception:
        return 0
    count = 0
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None or not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        names = [t.id.lower() for t in targets if isinstance(t, ast.Name)]
        if not any(("token" in name or "chat_id" in name) for name in names):
            continue
        if value.value.strip():
            count += 1
    return count


def parse_show(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def systemd_record(unit: str) -> dict[str, Any]:
    props = ["ActiveState", "SubState", "UnitFileState", "MainPID", "FragmentPath", "ExecStart"]
    proc = run(["systemctl", "show", unit, *[f"--property={p}" for p in props]])
    parsed = parse_show(proc.stdout) if proc.returncode == 0 else {}
    exec_text = parsed.get("ExecStart", "")
    paths = re.findall(r"(?:path=|argv\[\]=)(/[^ ;}]+\.py)", exec_text)
    if not paths:
        paths = re.findall(r"(/[^ ;}]+\.py)", exec_text)
    return {
        "unit": unit,
        "show_rc": proc.returncode,
        "active_state": parsed.get("ActiveState"),
        "sub_state": parsed.get("SubState"),
        "unit_file_state": parsed.get("UnitFileState"),
        "main_pid": parsed.get("MainPID"),
        "fragment_path": parsed.get("FragmentPath"),
        "exec_source_paths": sorted(set(paths)),
        "fingerprint": sha256_bytes(proc.stdout.encode("utf-8")),
    }


def environment_key_presence(unit: str, keys: list[str]) -> dict[str, bool]:
    if not keys:
        return {}
    proc = run(["systemctl", "cat", unit])
    if proc.returncode != 0:
        return {key: False for key in keys}
    unit_text = proc.stdout
    combined = unit_text
    for raw in re.findall(r"^\s*EnvironmentFile\s*=\s*([^\n]+)$", unit_text, flags=re.MULTILINE):
        value = raw.strip().strip('"').strip("'")
        optional = value.startswith("-")
        if optional:
            value = value[1:]
        path = Path(value)
        try:
            if path.is_file():
                combined += "\n" + path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return {key: bool(re.search(rf"(?m)^\s*(?:Environment\s*=\s*)?[\"']?{re.escape(key)}\s*=", combined)) for key in keys}


def protected_snapshot(root: Path, units: list[str]) -> dict[str, Any]:
    paths = {
        "formal_ledger": root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
        "shadow_snapshot": root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json",
        "telegram_status": root / "runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json",
        "view_contract": Path("/var/www/z-os-alimi/api/view_contract_latest.json"),
    }
    return {
        "files": {name: sha256_file(path) for name, path in paths.items()},
        "systemd": {unit: systemd_record(unit).get("fingerprint") for unit in units},
    }


def load_contract(root: Path, ref: str, contract_path: str) -> dict[str, Any]:
    data = git_bytes(root, ref, contract_path)
    if data is None:
        raise RuntimeError(f"CONTRACT_NOT_FOUND:{contract_path}")
    return json.loads(data.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument(
        "--contract-path",
        default="backend/contracts/ZOS_R7A1A4_RELEASE_MANIFEST_DEPLOYMENT_PARITY_v1.json",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = root / "runtime/exact25_edge_v1/r7a1a4_release_manifest_deployment_parity"
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "status_latest.json"
    manifest_path = out_dir / "release_manifest_latest.json"
    report_path = out_dir / "report_latest.md"

    contract = load_contract(root, args.sha, args.contract_path)
    units = [item["unit"] for item in contract["services"]]
    before = protected_snapshot(root, units)

    blockers: list[str] = []
    records: list[dict[str, Any]] = []
    byte_identical_ready_count = 0
    sanitized_cutover_ready_count = 0
    missing_environment_keys: list[str] = []

    for item in contract["services"]:
        unit = item["unit"]
        canonical_path = item["canonical_path"]
        deployed_path = Path(item["deployed_path"])
        canonical = git_bytes(root, args.sha, canonical_path)
        deployed = deployed_path.read_bytes() if deployed_path.is_file() else None
        systemd = systemd_record(unit)
        env_keys = discover_environment_keys(canonical)
        env_presence = environment_key_presence(unit, env_keys)
        missing = [key for key, present in env_presence.items() if not present]
        missing_environment_keys.extend(f"{unit}:{key}" for key in missing)
        commands = item.get("required_command_surface", [])
        canonical_commands = command_counts(canonical, commands)
        deployed_commands = command_counts(deployed, commands)
        canonical_sha = sha256_bytes(canonical) if canonical is not None else None
        deployed_sha = sha256_bytes(deployed) if deployed is not None else None
        policy = item["parity_policy"]
        byte_identical = canonical_sha is not None and canonical_sha == deployed_sha
        sensitive_literal_count = hardcoded_sensitive_assignment_count(canonical)

        if canonical is None:
            blockers.append(f"CANONICAL_SOURCE_MISSING:{canonical_path}")
        if deployed is None:
            blockers.append(f"DEPLOYED_SOURCE_MISSING:{deployed_path}")
        if not compile_ok(canonical, canonical_path):
            blockers.append(f"CANONICAL_COMPILE_FAILED:{canonical_path}")
        if not compile_ok(deployed, str(deployed_path)):
            blockers.append(f"DEPLOYED_COMPILE_FAILED:{deployed_path}")
        if systemd.get("active_state") != "active":
            blockers.append(f"UNIT_NOT_ACTIVE:{unit}")
        if str(deployed_path) not in (systemd.get("exec_source_paths") or []):
            blockers.append(f"UNIT_EXEC_SOURCE_MISMATCH:{unit}")

        cutover_class: str
        if policy == "BYTE_IDENTICAL":
            if byte_identical:
                byte_identical_ready_count += 1
                cutover_class = "BYTE_IDENTICAL_READY"
            else:
                blockers.append(f"BYTE_PARITY_MISMATCH:{unit}")
                cutover_class = "BYTE_PARITY_MISMATCH"
        else:
            command_surface_preserved = canonical_commands == deployed_commands
            if sensitive_literal_count:
                blockers.append(f"CANONICAL_SENSITIVE_LITERAL_FOUND:{unit}")
            if not command_surface_preserved:
                blockers.append(f"COMMAND_SURFACE_MISMATCH:{unit}")
            if missing:
                cutover_class = "SANITIZED_CANONICAL_ENV_BINDING_REQUIRED"
            elif sensitive_literal_count == 0 and command_surface_preserved:
                sanitized_cutover_ready_count += 1
                cutover_class = "SANITIZED_CANONICAL_READY"
            else:
                cutover_class = "SANITIZED_CANONICAL_NOT_READY"

        records.append(
            {
                "unit": unit,
                "canonical_path": canonical_path,
                "deployed_path": str(deployed_path),
                "parity_policy": policy,
                "canonical_sha256": canonical_sha,
                "deployed_sha256": deployed_sha,
                "canonical_compile_ok": compile_ok(canonical, canonical_path),
                "deployed_compile_ok": compile_ok(deployed, str(deployed_path)),
                "byte_identical": byte_identical,
                "required_command_counts_canonical": canonical_commands,
                "required_command_counts_deployed": deployed_commands,
                "environment_key_names": env_keys,
                "environment_key_presence": env_presence,
                "missing_environment_key_names": missing,
                "hardcoded_sensitive_assignment_count": sensitive_literal_count,
                "cutover_class": cutover_class,
                "systemd": systemd,
                "rollback": {
                    "deployed_sha256": deployed_sha,
                    "deployed_path": str(deployed_path),
                    "unit": unit,
                },
            }
        )

    after = protected_snapshot(root, units)
    protected_changes = [
        key
        for key in sorted(set(before["files"]) | set(after["files"]))
        if before["files"].get(key) != after["files"].get(key)
    ]
    systemd_changes = [
        unit
        for unit in units
        if before["systemd"].get(unit) != after["systemd"].get(unit)
    ]
    if protected_changes:
        blockers.append("PROTECTED_RUNTIME_CHANGED:" + ",".join(protected_changes))
    if systemd_changes:
        blockers.append("SYSTEMD_CHANGED:" + ",".join(systemd_changes))

    blocker_count = len(blockers)
    state = "PASS" if blocker_count == 0 else "HOLD"
    if missing_environment_keys:
        next_stage = "R7.A1A4B_ENVIRONMENT_BINDING_PLAN"
    elif state == "PASS":
        next_stage = contract["next_stage"]
    else:
        next_stage = "R7.A1A4_DIAGNOSE"

    manifest = {
        "schema": "zos_r7a1a4_runtime_release_manifest_v1",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "services": records,
        "rollback_ready_count": sum(1 for row in records if row["rollback"]["deployed_sha256"]),
        "next_stage": next_stage,
    }
    status = {
        "schema": "zos_r7a1a4_release_manifest_deployment_parity_status_v1",
        "official_stage": "R7.A1A4",
        "generated_at": now_iso(),
        "state": state,
        "blocker_count": blocker_count,
        "blockers": blockers,
        "mutation_count": 0,
        "runtime_mutation_count": len(protected_changes),
        "systemd_mutation_count": len(systemd_changes),
        "service_count": len(records),
        "canonical_source_count": sum(1 for row in records if row["canonical_sha256"]),
        "byte_identical_ready_count": byte_identical_ready_count,
        "sanitized_cutover_ready_count": sanitized_cutover_ready_count,
        "missing_required_environment_key_count": len(missing_environment_keys),
        "missing_required_environment_keys": missing_environment_keys,
        "records": records,
        "release_manifest": str(manifest_path),
        "next_stage": next_stage,
    }

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_lines = [
        "# R7.A1A4 Release Manifest Deployment Parity",
        "",
        f"- state: `{state}`",
        f"- blocker_count: `{blocker_count}`",
        f"- byte_identical_ready_count: `{byte_identical_ready_count}`",
        f"- sanitized_cutover_ready_count: `{sanitized_cutover_ready_count}`",
        f"- missing_environment_key_count: `{len(missing_environment_keys)}`",
        f"- next_stage: `{next_stage}`",
        "",
        "## Services",
    ]
    for row in records:
        report_lines.extend(
            [
                f"### {row['unit']}",
                f"- policy: `{row['parity_policy']}`",
                f"- cutover_class: `{row['cutover_class']}`",
                f"- byte_identical: `{row['byte_identical']}`",
                f"- active_state: `{row['systemd'].get('active_state')}`",
                f"- missing_environment_keys: `{row['missing_environment_key_names']}`",
                "",
            ]
        )
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("R7A1A4_RELEASE_MANIFEST_DEPLOYMENT_PARITY_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={blocker_count}")
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("MUTATION_COUNT=0")
    print(f"RUNTIME_MUTATION_COUNT={len(protected_changes)}")
    print(f"SYSTEMD_MUTATION_COUNT={len(systemd_changes)}")
    print(f"SERVICE_COUNT={len(records)}")
    print(f"CANONICAL_SOURCE_COUNT={status['canonical_source_count']}")
    print(f"BYTE_IDENTICAL_READY_COUNT={byte_identical_ready_count}")
    print(f"SANITIZED_CUTOVER_READY_COUNT={sanitized_cutover_ready_count}")
    print(f"MISSING_REQUIRED_ENVIRONMENT_KEY_COUNT={len(missing_environment_keys)}")
    for index, row in enumerate(records, 1):
        print(
            f"SERVICE_{index}={row['unit']}|{row['cutover_class']}|"
            f"active={row['systemd'].get('active_state')}|byte_identical={row['byte_identical']}|"
            f"missing_env={len(row['missing_environment_key_names'])}"
        )
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"RELEASE_MANIFEST={manifest_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
