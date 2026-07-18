#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

NAME_PATTERN = re.compile(r"(?:TOKEN|SECRET|API_KEY|CHAT_ID|CHAT_IDS|OWNER_ID|ADMIN_ID|ALLOWED_ID)", re.I)
TOKEN_LITERAL = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{20,}")


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def digest(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    os.close(fd)
    tmp = Path(raw)
    try:
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"NOT_OBJECT:{path}")
    return value


def git_exists(root: Path, sha: str, repo_path: str) -> bool:
    p = run(["git", "-C", str(root), "-c", f"safe.directory={root}", "cat-file", "-e", f"{sha}:{repo_path}"])
    return p.returncode == 0


def compile_check(path: Path) -> bool:
    p = run(["python3", "-m", "py_compile", str(path)])
    return p.returncode == 0


def surface(text: str) -> dict[str, Any]:
    tree = ast.parse(text)
    functions = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
    classes = sorted({node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)})
    payload = json.dumps({"functions": functions, "classes": classes}, sort_keys=True)
    return {
        "function_count": len(functions),
        "class_count": len(classes),
        "surface_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def target_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            names.extend(target_names(item))
    return names


def redaction_locations(text: str) -> list[dict[str, Any]]:
    tree = ast.parse(text)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names: list[str] = []
            for target in node.targets:
                names.extend(target_names(target))
            for name in names:
                if NAME_PATTERN.search(name):
                    key = (int(node.lineno), name, "named_assignment")
                    if key not in seen:
                        rows.append({"line": int(node.lineno), "name": name, "category": "named_assignment"})
                        seen.add(key)
        elif isinstance(node, ast.AnnAssign):
            for name in target_names(node.target):
                if NAME_PATTERN.search(name):
                    key = (int(node.lineno), name, "named_assignment")
                    if key not in seen:
                        rows.append({"line": int(node.lineno), "name": name, "category": "named_assignment"})
                        seen.add(key)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and TOKEN_LITERAL.search(node.value):
            key = (int(getattr(node, "lineno", 0)), "<literal>", "telegram_token_literal")
            if key not in seen:
                rows.append({"line": key[0], "name": key[1], "category": key[2]})
                seen.add(key)
    return sorted(rows, key=lambda row: (row["line"], row["name"], row["category"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--target-sha", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    contract = load(args.contract)
    root = Path(contract["repo_root"]).resolve()
    parent = load(Path(contract["parent_status"]))
    blockers: list[str] = []
    if parent.get("state") != "PASS" or parent.get("mutation_count") != 0:
        blockers.append("PARENT_NOT_PASS")
    if parent.get("source_plan_count") != 3:
        blockers.append("PARENT_SOURCE_PLAN_COUNT")

    runtime_snapshot = root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json"
    formal_ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    protected_before = {"runtime": digest(runtime_snapshot), "ledger": digest(formal_ledger)}
    parent_map = {row.get("deployed_source"): row for row in parent.get("source_plans", []) if isinstance(row, dict)}
    results: list[dict[str, Any]] = []

    for unit, source_raw, canonical, mode in contract["targets"]:
        source = Path(source_raw)
        row: dict[str, Any] = {
            "unit": unit,
            "source": source_raw,
            "canonical_path": canonical,
            "mode": mode,
            "source_exists": source.is_file(),
            "canonical_exists_at_target_sha": git_exists(root, args.target_sha, canonical),
        }
        if not source.is_file():
            blockers.append("SOURCE_MISSING:" + source_raw)
            results.append(row)
            continue
        text = source.read_text(encoding="utf-8")
        row.update({
            "sha256": digest(source),
            "compile_ok": compile_check(source),
            "surface": surface(text),
            "command_counts": {cmd: text.count(cmd) for cmd in contract["required_commands"]},
        })
        planned = parent_map.get(source_raw, {})
        if row["sha256"] != planned.get("deployed_sha256"):
            blockers.append("SOURCE_HASH_DRIFT:" + source_raw)
        if row["canonical_exists_at_target_sha"]:
            blockers.append("CANONICAL_TARGET_ALREADY_EXISTS:" + canonical)
        if not row["compile_ok"]:
            blockers.append("COMPILE_FAILED:" + source_raw)
        if mode == "REDACT":
            row["redaction_locations"] = redaction_locations(text)
            row["redaction_location_count"] = len(row["redaction_locations"])
            missing_commands = [cmd for cmd, count in row["command_counts"].items() if count == 0]
            if missing_commands:
                blockers.append("TELEGRAM_COMMAND_MISSING:" + ",".join(missing_commands))
            if row["redaction_location_count"] == 0:
                blockers.append("TELEGRAM_REDACTION_LOCATION_NOT_FOUND")
        results.append(row)

    protected_after = {"runtime": digest(runtime_snapshot), "ledger": digest(formal_ledger)}
    mutation_count = sum(protected_before[key] != protected_after[key] for key in protected_before)
    if mutation_count:
        blockers.append("PROTECTED_STATE_CHANGED")
    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": contract["schema"] + "_status",
        "official_stage": "R7.A1A3",
        "state": state,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "mutation_count": mutation_count,
        "sources": results,
        "protected_before": protected_before,
        "protected_after": protected_after,
        "next_stage": contract["next_stage"],
    }
    atomic(args.output, payload)

    lines = [
        "# R7.A1A3 Canonical Import Preflight",
        "",
        f"- State: **{state}**",
        f"- Mutation count: **{mutation_count}**",
        "",
        "| Unit | Mode | Compile | Canonical exists | Redaction locations |",
        "|---|---|---:|---:|---:|",
    ]
    for row in results:
        lines.append(f"| {row['unit']} | {row['mode']} | {row.get('compile_ok')} | {row['canonical_exists_at_target_sha']} | {row.get('redaction_location_count', 0)} |")
    lines += ["", "No source values are written to this report.", ""]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8")

    print("R7A1A3_CANONICAL_IMPORT_PREFLIGHT_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"MUTATION_COUNT={mutation_count}")
    for index, row in enumerate(results, 1):
        print(f"SOURCE_{index}={row['unit']}|mode={row['mode']}|compile={row.get('compile_ok')}|canonical_exists={row['canonical_exists_at_target_sha']}|redaction_locations={row.get('redaction_location_count', 0)}")
        if row.get("redaction_locations"):
            safe = ",".join(f"L{x['line']}:{x['name']}:{x['category']}" for x in row["redaction_locations"])
            print(f"SOURCE_{index}_REDACTION_MAP={safe}")
    print(f"NEXT_STAGE={contract['next_stage']}")
    print(f"EVIDENCE_JSON={args.output}")
    print(f"EVIDENCE_REPORT={args.report}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
