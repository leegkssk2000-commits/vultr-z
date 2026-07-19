#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
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


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def git_bytes(root: Path, ref: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
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


def call_env_key(node: ast.Call) -> str | None:
    if not node.args:
        return None
    func = node.func
    valid = False
    if isinstance(func, ast.Attribute) and func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        valid = True
    elif (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
        and func.value.attr == "environ"
    ):
        valid = True
    if not valid:
        return None
    key = node.args[0]
    return key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None


def assignment_target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                return target.id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def assignment_value(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Assign):
        return node.value
    if isinstance(node, ast.AnnAssign):
        return node.value
    return None


def function_name_for_line(tree: ast.AST, line: int) -> str | None:
    winner: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = int(getattr(node, "lineno", 0))
            end = int(getattr(node, "end_lineno", start))
            if start <= line <= end:
                span = end - start
                if winner is None or span < winner[0]:
                    winner = (span, node.name)
    return winner[1] if winner else None


def environment_key_records(data: bytes | None) -> list[dict[str, Any]]:
    if data is None:
        return []
    try:
        tree = ast.parse(data.decode("utf-8"))
    except Exception:
        return []
    records: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        key = call_env_key(node)
        if key is None:
            continue
        parent_target = None
        for candidate in ast.walk(tree):
            value = assignment_value(candidate)
            if value is node:
                parent_target = assignment_target_name(candidate)
                break
        line = int(getattr(node, "lineno", 0))
        records.append({
            "key": key,
            "line": line,
            "function": function_name_for_line(tree, line),
            "target": parent_target,
        })
    unique: dict[tuple[str, int], dict[str, Any]] = {}
    for row in records:
        unique[(row["key"], row["line"])] = row
    return sorted(unique.values(), key=lambda row: (row["line"], row["key"]))


def classify_keys(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    direct: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    for row in records:
        target = str(row.get("target") or "").lower()
        function = str(row.get("function") or "")
        if function == "main" and target in {"token", "chat_id"}:
            direct.append(row)
        else:
            aliases.append(row)
    return direct, aliases


def deployed_sensitive_assignments(data: bytes | None) -> list[dict[str, Any]]:
    if data is None:
        return []
    try:
        tree = ast.parse(data.decode("utf-8"))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        target = assignment_target_name(node)
        value = assignment_value(node)
        if not target or value is None:
            continue
        lowered = target.lower()
        if not ("token" in lowered or "chat_id" in lowered):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.strip():
            rows.append({
                "target": target,
                "line": int(getattr(node, "lineno", 0)),
                "kind": "nonempty_literal_assignment",
            })
    return sorted(rows, key=lambda row: (row["line"], row["target"]))


def command_counts(data: bytes | None, commands: list[str]) -> dict[str, int]:
    text = data.decode("utf-8", errors="replace") if data is not None else ""
    return {command: text.count(command) for command in commands}


def parse_environment_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("Environment="):
            stripped = stripped.split("=", 1)[1].strip().strip('"').strip("'")
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", stripped)
        if match:
            names.add(match.group(1))
    return names


def unit_binding_inventory(unit: str) -> dict[str, Any]:
    cat = run(["systemctl", "cat", unit])
    active = run(["systemctl", "is-active", unit])
    text = cat.stdout if cat.returncode == 0 else ""
    files: list[str] = []
    names = parse_environment_names(text)
    for raw in re.findall(r"(?m)^\s*EnvironmentFile\s*=\s*([^\n]+)$", text):
        candidate = raw.strip().strip('"').strip("'")
        if candidate.startswith("-"):
            candidate = candidate[1:]
        files.append(candidate)
        path = Path(candidate)
        try:
            if path.is_file():
                names.update(parse_environment_names(path.read_text(encoding="utf-8", errors="replace")))
        except Exception:
            pass
    return {
        "unit": unit,
        "active": active.returncode == 0 and active.stdout.strip() == "active",
        "cat_rc": cat.returncode,
        "fragment_fingerprint": sha256_bytes(text.encode("utf-8")),
        "environment_files": sorted(set(files)),
        "bound_key_names": sorted(names),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    out_dir = root / "runtime/exact25_edge_v1/r7a1a4b_environment_binding_plan"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"

    unit = "zel-q4r3-telegram-pos-adapter-v2.service"
    canonical_path = "services/telegram/zel_q4r3_telegram_pos_adapter_v2.py"
    deployed_path = Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py")
    commands = ["/pos", "/pnl", "/view"]

    previous = load_json(root / "runtime/exact25_edge_v1/r7a1a4_release_manifest_deployment_parity/status_latest.json")
    before = protected_snapshot(root)
    canonical = git_bytes(root, args.sha, canonical_path)
    deployed = deployed_path.read_bytes() if deployed_path.is_file() else None

    env_records = environment_key_records(canonical)
    direct_keys, alias_keys = classify_keys(env_records)
    deployed_assignments = deployed_sensitive_assignments(deployed)
    canonical_commands = command_counts(canonical, commands)
    deployed_commands = command_counts(deployed, commands)
    binding = unit_binding_inventory(unit)

    direct_names = sorted({row["key"] for row in direct_keys})
    alias_names = sorted({row["key"] for row in alias_keys})
    bound_names = set(binding["bound_key_names"])
    missing_direct = [name for name in direct_names if name not in bound_names]

    blockers: list[str] = []
    if previous.get("state") != "PASS":
        blockers.append("R7A1A4_NOT_PASS")
    if canonical is None:
        blockers.append("CANONICAL_SOURCE_MISSING")
    if deployed is None:
        blockers.append("DEPLOYED_SOURCE_MISSING")
    if len(direct_names) != 2:
        blockers.append(f"DIRECT_REQUIRED_KEY_COUNT_{len(direct_names)}")
    if len(alias_names) != 2:
        blockers.append(f"LEGACY_ALIAS_KEY_COUNT_{len(alias_names)}")
    if len(deployed_assignments) != 2:
        blockers.append(f"DEPLOYED_SENSITIVE_ASSIGNMENT_COUNT_{len(deployed_assignments)}")
    if canonical_commands != deployed_commands:
        blockers.append("COMMAND_SURFACE_MISMATCH")
    if not binding["active"]:
        blockers.append("TELEGRAM_UNIT_NOT_ACTIVE")

    after = protected_snapshot(root)
    changed = [key for key in before if before.get(key) != after.get(key)]
    if changed:
        blockers.append("PROTECTED_RUNTIME_CHANGED")

    state = "PASS" if not blockers else "HOLD"
    next_stage = "R7.A1A4C_ENVIRONMENT_BINDING_CANARY" if state == "PASS" else "R7.A1A4B_DIAGNOSE"
    payload: dict[str, Any] = {
        "schema": "r7a1a4b_environment_binding_plan_status_v1",
        "official_stage": "R7.A1A4B",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "mutation_count": 0,
        "runtime_mutation_count": len(changed),
        "systemd_mutation_count": 0,
        "unit": binding,
        "canonical": {
            "path": canonical_path,
            "sha256": sha256_bytes(canonical) if canonical is not None else None,
            "environment_key_records": env_records,
            "direct_required_keys": direct_names,
            "legacy_alias_keys": alias_names,
            "command_counts": canonical_commands,
        },
        "deployed": {
            "path": str(deployed_path),
            "sha256": sha256_bytes(deployed) if deployed is not None else None,
            "sensitive_assignments": deployed_assignments,
            "command_counts": deployed_commands,
        },
        "binding_gap": {
            "missing_direct_key_names": missing_direct,
            "legacy_aliases_not_required_for_cutover": alias_names,
            "planned_environment_file": "/etc/zel/telegram-pos-adapter.env",
            "planned_dropin": "/etc/systemd/system/zel-q4r3-telegram-pos-adapter-v2.service.d/20-canonical-environment.conf",
            "planned_environment_file_mode": "0600",
            "planned_environment_file_owner": "root:root",
            "value_exposure_count": 0,
        },
        "canary_plan": [
            "snapshot deployed source and unit/drop-in rollback inputs",
            "extract only the two deployed literal values in memory without printing them",
            "write root-only environment file atomically with canonical key names",
            "install systemd drop-in referencing the environment file",
            "daemon-reload and restart only the Telegram adapter",
            "verify active state, command surface, visible response, and protected runtime invariants",
            "rollback source/drop-in/environment file and service state on any failure",
        ],
        "protected_before": before,
        "protected_after": after,
        "protected_change_count": len(changed),
        "next_stage": next_stage,
    }
    atomic_write(status_path, payload)

    report_lines = [
        "# R7.A1A4B Environment Binding Plan",
        "",
        f"- state: `{state}`",
        f"- blockers: `{blockers}`",
        f"- direct required key names: `{direct_names}`",
        f"- legacy aliases: `{alias_names}`",
        f"- currently bound key names: `{binding['bound_key_names']}`",
        f"- missing direct keys: `{missing_direct}`",
        f"- deployed sensitive assignment lines: `{[row['line'] for row in deployed_assignments]}`",
        f"- command surface parity: `{canonical_commands == deployed_commands}`",
        f"- protected runtime changes: `{changed}`",
        f"- next: `{next_stage}`",
        "",
        "No environment value was stored or printed.",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("R7A1A4B_ENVIRONMENT_BINDING_PLAN_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print("MUTATION_COUNT=0")
    print(f"RUNTIME_MUTATION_COUNT={len(changed)}")
    print("SYSTEMD_MUTATION_COUNT=0")
    print(f"DIRECT_REQUIRED_KEY_COUNT={len(direct_names)}")
    print(f"LEGACY_ALIAS_KEY_COUNT={len(alias_names)}")
    print(f"DEPLOYED_SENSITIVE_ASSIGNMENT_COUNT={len(deployed_assignments)}")
    print(f"CURRENT_BOUND_KEY_COUNT={len(binding['bound_key_names'])}")
    print(f"MISSING_DIRECT_KEY_COUNT={len(missing_direct)}")
    print(f"COMMAND_SURFACE_PARITY={str(canonical_commands == deployed_commands).lower()}")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
