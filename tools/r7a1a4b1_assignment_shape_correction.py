#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def git_bytes(root: Path, ref: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def protected_snapshot(root: Path) -> dict[str, str | None]:
    paths = {
        "formal_ledger": root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
        "shadow_snapshot": root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json",
        "telegram_status": root / "runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json",
        "view_contract": Path("/var/www/z-os-alimi/api/view_contract_latest.json"),
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in node.elts:
            names.extend(target_names(item))
        return names
    return []


def assignment_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        names: list[str] = []
        for target in node.targets:
            names.extend(target_names(target))
        return names
    if isinstance(node, ast.AnnAssign):
        return target_names(node.target)
    return []


def assignment_value(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Assign):
        return node.value
    if isinstance(node, ast.AnnAssign):
        return node.value
    return None


def assignment_shape_records(data: bytes | None, required: set[str]) -> list[dict[str, Any]]:
    if data is None:
        return []
    try:
        tree = ast.parse(data.decode("utf-8"))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        names = assignment_targets(node)
        value = assignment_value(node)
        if not names or value is None:
            continue
        for name in names:
            if name not in required:
                continue
            rows.append({
                "target": name,
                "line": int(getattr(node, "lineno", 0)),
                "rhs_ast_type": type(value).__name__,
            })
    return sorted(rows, key=lambda row: (row["target"], row["line"]))


def env_call_key(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    key_node = node.args[0]
    if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        return key_node.value
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
        and func.value.attr == "environ"
    ):
        return key_node.value
    return None


def canonical_env_records(data: bytes | None, required: set[str]) -> list[dict[str, Any]]:
    if data is None:
        return []
    try:
        tree = ast.parse(data.decode("utf-8"))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        names = assignment_targets(node)
        value = assignment_value(node)
        if value is None:
            continue
        key = env_call_key(value)
        if key is None:
            continue
        for name in names:
            if name in required:
                rows.append({"target": name, "line": int(getattr(node, "lineno", 0)), "environment_key": key})
    return sorted(rows, key=lambda row: (row["target"], row["line"]))


def command_counts(data: bytes | None, commands: list[str]) -> dict[str, int]:
    text = data.decode("utf-8", errors="replace") if data is not None else ""
    return {command: text.count(command) for command in commands}


def unit_active(unit: str) -> bool:
    proc = subprocess.run(["systemctl", "is-active", unit], text=True, capture_output=True, check=False)
    return proc.returncode == 0 and proc.stdout.strip() == "active"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    out_dir = root / "runtime/exact25_edge_v1/r7a1a4b1_assignment_shape_correction"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"

    previous = load_json(root / "runtime/exact25_edge_v1/r7a1a4b_environment_binding_plan/status_latest.json")
    canonical_path = "services/telegram/zel_q4r3_telegram_pos_adapter_v2.py"
    deployed_path = Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py")
    required = {"token", "chat_id"}
    commands = ["/pos", "/pnl", "/view"]
    unit = "zel-q4r3-telegram-pos-adapter-v2.service"

    before = protected_snapshot(root)
    canonical = git_bytes(root, args.sha, canonical_path)
    deployed = deployed_path.read_bytes() if deployed_path.is_file() else None

    deployed_records = assignment_shape_records(deployed, required)
    canonical_records = canonical_env_records(canonical, required)
    deployed_counts = {name: sum(1 for row in deployed_records if row["target"] == name) for name in sorted(required)}
    canonical_counts = {name: sum(1 for row in canonical_records if row["target"] == name) for name in sorted(required)}
    duplicate_count = sum(max(0, count - 1) for count in deployed_counts.values())
    canonical_command_counts = command_counts(canonical, commands)
    deployed_command_counts = command_counts(deployed, commands)
    command_parity = canonical_command_counts == deployed_command_counts
    active = unit_active(unit)

    blockers: list[str] = []
    previous_blockers = previous.get("blockers") if isinstance(previous.get("blockers"), list) else []
    if previous.get("state") != "HOLD" or previous_blockers != ["DEPLOYED_SENSITIVE_ASSIGNMENT_COUNT_0"]:
        blockers.append("UNEXPECTED_A1A4B_PRECONDITION")
    if canonical is None:
        blockers.append("CANONICAL_SOURCE_MISSING")
    if deployed is None:
        blockers.append("DEPLOYED_SOURCE_MISSING")
    if deployed_counts != {"chat_id": 1, "token": 1}:
        blockers.append(f"DEPLOYED_TARGET_ASSIGNMENT_COUNTS_{deployed_counts}")
    if duplicate_count != 0:
        blockers.append(f"DEPLOYED_DUPLICATE_TARGET_COUNT_{duplicate_count}")
    if canonical_counts != {"chat_id": 1, "token": 1}:
        blockers.append(f"CANONICAL_ENV_ASSIGNMENT_COUNTS_{canonical_counts}")
    if not command_parity:
        blockers.append("COMMAND_SURFACE_MISMATCH")
    if not active:
        blockers.append("TELEGRAM_UNIT_NOT_ACTIVE")

    after = protected_snapshot(root)
    changed = [name for name in before if before.get(name) != after.get(name)]
    if changed:
        blockers.append("PROTECTED_RUNTIME_CHANGED")

    state = "PASS" if not blockers else "HOLD"
    next_stage = "R7.A1A4C_ENVIRONMENT_BINDING_CANARY" if state == "PASS" else "R7.A1A4B1_DIAGNOSE"
    payload: dict[str, Any] = {
        "schema": "r7a1a4b1_assignment_shape_correction_status_v1",
        "official_stage": "R7.A1A4B1",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "mutation_count": 0,
        "runtime_mutation_count": len(changed),
        "systemd_mutation_count": 0,
        "value_exposure_count": 0,
        "deployed_target_assignments": deployed_records,
        "deployed_target_counts": deployed_counts,
        "deployed_duplicate_target_count": duplicate_count,
        "canonical_environment_assignments": canonical_records,
        "canonical_target_counts": canonical_counts,
        "canonical_command_counts": canonical_command_counts,
        "deployed_command_counts": deployed_command_counts,
        "command_surface_parity": command_parity,
        "telegram_unit_active": active,
        "protected_change_count": len(changed),
        "next_stage": next_stage,
    }
    atomic_write(status_path, payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A4B1 Assignment Shape Correction",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- deployed targets: `{deployed_records}`",
            f"- canonical environment targets: `{canonical_records}`",
            f"- command surface parity: `{command_parity}`",
            f"- Telegram unit active: `{active}`",
            f"- protected runtime changes: `{changed}`",
            f"- next: `{next_stage}`",
            "",
            "No assignment value was read, stored, or printed.",
        ]) + "\n",
        encoding="utf-8",
    )

    print("R7A1A4B1_ASSIGNMENT_SHAPE_CORRECTION_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print("MUTATION_COUNT=0")
    print(f"RUNTIME_MUTATION_COUNT={len(changed)}")
    print("SYSTEMD_MUTATION_COUNT=0")
    print(f"DEPLOYED_TARGET_ASSIGNMENT_COUNT={len(deployed_records)}")
    print(f"DEPLOYED_DUPLICATE_TARGET_COUNT={duplicate_count}")
    print(f"CANONICAL_ENV_ASSIGNMENT_COUNT={len(canonical_records)}")
    print(f"COMMAND_SURFACE_PARITY={str(command_parity).lower()}")
    print(f"TELEGRAM_UNIT_ACTIVE={str(active).lower()}")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
