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

TOKEN_LITERAL = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{20,}")


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


def assignment_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        values: list[str] = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                values.append(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                values.extend(item.id for item in target.elts if isinstance(item, ast.Name))
        return values
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def assignment_value(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Assign):
        return node.value
    if isinstance(node, ast.AnnAssign):
        return node.value
    return None


def env_key(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        return first.value
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
        and func.value.attr == "environ"
    ):
        return first.value
    return None


def main_semantics(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {}
    tree = ast.parse(data.decode("utf-8"))
    main = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"), None)
    if main is None:
        return {}

    assignments: dict[str, list[dict[str, Any]]] = {"token": [], "src": [], "chat_id": []}
    src_load_lines: list[int] = []
    for node in ast.walk(main):
        for name in assignment_targets(node):
            if name not in assignments:
                continue
            value = assignment_value(node)
            row: dict[str, Any] = {
                "line": int(getattr(node, "lineno", 0)),
                "rhs_ast_type": type(value).__name__ if value is not None else None,
            }
            key = env_key(value) if value is not None else None
            if key is not None:
                row["environment_key"] = key
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                row["constant_sha256"] = sha256_bytes(value.value.encode("utf-8"))
                row["constant_matches_expected_src"] = value.value == "env:ZEL_TELEGRAM_BOT_TOKEN"
            assignments[name].append(row)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "src":
            src_load_lines.append(int(getattr(node, "lineno", 0)))

    src_assignment_lines = [row["line"] for row in assignments["src"]]
    first_src_assignment = min(src_assignment_lines) if src_assignment_lines else None
    undefined_src_use_lines = [line for line in src_load_lines if first_src_assignment is None or line <= first_src_assignment]
    return {
        "assignments": assignments,
        "src_load_lines": sorted(src_load_lines),
        "undefined_src_use_lines": sorted(undefined_src_use_lines),
    }


def hardcoded_secret_count(data: bytes | None) -> int:
    if data is None:
        return 0
    text = data.decode("utf-8", errors="replace")
    return len(TOKEN_LITERAL.findall(text))


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
    out_dir = root / "runtime/exact25_edge_v1/r7a1a4b2_telegram_src_provenance_fix"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    canonical_path = "services/telegram/zel_q4r3_telegram_pos_adapter_v2.py"
    deployed_path = Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py")
    commands = ["/pos", "/pnl", "/view"]
    unit = "zel-q4r3-telegram-pos-adapter-v2.service"

    previous = load_json(root / "runtime/exact25_edge_v1/r7a1a4b1_assignment_shape_correction/status_latest.json")
    before = protected_snapshot(root)
    canonical = git_bytes(root, args.sha, canonical_path)
    deployed = deployed_path.read_bytes() if deployed_path.is_file() else None

    semantics = main_semantics(canonical)
    assignments = semantics.get("assignments") if isinstance(semantics.get("assignments"), dict) else {}
    token_rows = assignments.get("token") if isinstance(assignments.get("token"), list) else []
    src_rows = assignments.get("src") if isinstance(assignments.get("src"), list) else []
    chat_rows = assignments.get("chat_id") if isinstance(assignments.get("chat_id"), list) else []
    undefined_src = semantics.get("undefined_src_use_lines") if isinstance(semantics.get("undefined_src_use_lines"), list) else []
    secret_count = hardcoded_secret_count(canonical)
    canonical_commands = command_counts(canonical, commands)
    deployed_commands = command_counts(deployed, commands)
    command_parity = canonical_commands == deployed_commands
    active = unit_active(unit)

    blockers: list[str] = []
    if previous.get("state") != "PASS":
        blockers.append("R7A1A4B1_NOT_PASS")
    if canonical is None:
        blockers.append("CANONICAL_SOURCE_MISSING")
    if deployed is None:
        blockers.append("DEPLOYED_SOURCE_MISSING")
    if len(token_rows) != 1 or token_rows[0].get("environment_key") != "ZEL_TELEGRAM_BOT_TOKEN":
        blockers.append("TOKEN_BINDING_INVALID")
    if len(src_rows) != 1 or not src_rows[0].get("constant_matches_expected_src"):
        blockers.append("SRC_PROVENANCE_BINDING_INVALID")
    if len(chat_rows) != 1 or chat_rows[0].get("environment_key") != "ZEL_TELEGRAM_ALLOWED_CHAT_ID":
        blockers.append("CHAT_ID_BINDING_INVALID")
    if undefined_src:
        blockers.append(f"UNDEFINED_SRC_USE_LINES_{undefined_src}")
    if secret_count != 0:
        blockers.append(f"HARDCODED_SECRET_COUNT_{secret_count}")
    if not command_parity:
        blockers.append("COMMAND_SURFACE_MISMATCH")
    if not active:
        blockers.append("TELEGRAM_UNIT_NOT_ACTIVE")

    after = protected_snapshot(root)
    changed = [name for name in before if before.get(name) != after.get(name)]
    if changed:
        blockers.append("PROTECTED_RUNTIME_CHANGED")

    state = "PASS" if not blockers else "HOLD"
    next_stage = "R7.A1A4C_ENVIRONMENT_BINDING_CANARY" if state == "PASS" else "R7.A1A4B2_DIAGNOSE"
    payload: dict[str, Any] = {
        "schema": "r7a1a4b2_telegram_src_provenance_fix_status_v1",
        "official_stage": "R7.A1A4B2",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "mutation_count": 0,
        "runtime_mutation_count": len(changed),
        "systemd_mutation_count": 0,
        "value_exposure_count": 0,
        "hardcoded_secret_count": secret_count,
        "main_semantics": semantics,
        "canonical_command_counts": canonical_commands,
        "deployed_command_counts": deployed_commands,
        "command_surface_parity": command_parity,
        "telegram_unit_active": active,
        "protected_change_count": len(changed),
        "next_stage": next_stage,
    }
    atomic_write(status_path, payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A4B2 Telegram src Provenance Fix",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- token assignment count: `{len(token_rows)}`",
            f"- src assignment count: `{len(src_rows)}`",
            f"- chat_id assignment count: `{len(chat_rows)}`",
            f"- undefined src uses: `{undefined_src}`",
            f"- hardcoded secret count: `{secret_count}`",
            f"- command surface parity: `{command_parity}`",
            f"- Telegram unit active: `{active}`",
            f"- protected runtime changes: `{changed}`",
            f"- next: `{next_stage}`",
            "",
            "No credential value was read, stored, or printed.",
        ]) + "\n",
        encoding="utf-8",
    )

    print("R7A1A4B2_TELEGRAM_SRC_PROVENANCE_FIX_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print("MUTATION_COUNT=0")
    print(f"RUNTIME_MUTATION_COUNT={len(changed)}")
    print("SYSTEMD_MUTATION_COUNT=0")
    print(f"TOKEN_BINDING_COUNT={len(token_rows)}")
    print(f"SRC_PROVENANCE_BINDING_COUNT={len(src_rows)}")
    print(f"CHAT_ID_BINDING_COUNT={len(chat_rows)}")
    print(f"UNDEFINED_SRC_USE_COUNT={len(undefined_src)}")
    print(f"HARDCODED_SECRET_COUNT={secret_count}")
    print(f"COMMAND_SURFACE_PARITY={str(command_parity).lower()}")
    print(f"TELEGRAM_UNIT_ACTIVE={str(active).lower()}")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
