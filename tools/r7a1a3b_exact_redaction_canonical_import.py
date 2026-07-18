#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

TOKEN_LITERAL = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{20,}")
TARGET_NAMES = {"token", "chat_id"}


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def digest(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def compile_check(path: Path) -> bool:
    return run(["python3", "-m", "py_compile", str(path)]).returncode == 0


def surface(text: str) -> dict[str, Any]:
    tree = ast.parse(text)
    functions = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
    classes = sorted({node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)})
    payload = json.dumps({"functions": functions, "classes": classes}, sort_keys=True)
    return {
        "functions": functions,
        "classes": classes,
        "sha256": text_digest(payload),
    }


def target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        values: list[str] = []
        for item in node.elts:
            values.extend(target_names(item))
        return values
    return []


def assignment_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        values: list[str] = []
        for target in node.targets:
            values.extend(target_names(target))
        return values
    if isinstance(node, ast.AnnAssign):
        return target_names(node.target)
    return []


def has_os_import(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == "os" for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            return True
    return False


def import_insert_index(text: str, tree: ast.Module) -> int:
    lines = text.splitlines(keepends=True)
    index = 0
    if lines and lines[0].startswith("#!"):
        index = 1
    if index < len(lines) and "coding" in lines[index]:
        index += 1
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        index = max(index, int(body[0].end_lineno or body[0].lineno))
        body = body[1:]
    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            index = max(index, int(node.end_lineno or node.lineno))
        else:
            break
    return index


def is_allowed_env_call(node: ast.AST, expected_env: str) -> bool:
    if not isinstance(node, ast.Call) or not node.args:
        return False
    first = node.args[0]
    if not isinstance(first, ast.Constant) or first.value != expected_env:
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "get" and isinstance(func.value, ast.Attribute):
        return isinstance(func.value.value, ast.Name) and func.value.value.id == "os" and func.value.attr == "environ"
    return False


def hardcoded_secret_count(text: str, redactions: dict[str, str]) -> int:
    tree = ast.parse(text)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and TOKEN_LITERAL.search(node.value):
            count += 1
        names = assignment_targets(node)
        for name in names:
            if name not in redactions:
                continue
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if value is None or not is_allowed_env_call(value, redactions[name]):
                count += 1
    return count


def sanitize_telegram(text: str, redactions: dict[str, str]) -> tuple[str, dict[str, Any]]:
    tree = ast.parse(text)
    candidates: dict[str, ast.AST] = {}
    duplicates: list[str] = []
    for node in ast.walk(tree):
        names = assignment_targets(node)
        for name in names:
            if name not in redactions:
                continue
            if name in candidates:
                duplicates.append(name)
            else:
                candidates[name] = node
    missing = sorted(set(redactions) - set(candidates))
    if missing or duplicates:
        raise ValueError(f"REDACTION_TARGET_ERROR:missing={missing}:duplicates={sorted(set(duplicates))}")

    lines = text.splitlines(keepends=True)
    replacements: list[tuple[int, int, str, str]] = []
    for name, node in candidates.items():
        start = int(node.lineno) - 1
        end = int(node.end_lineno or node.lineno)
        original = "".join(lines[start:end])
        indent = re.match(r"^[ \t]*", lines[start]).group(0)
        newline = "\n" if original.endswith("\n") else ""
        replacement = f'{indent}{name} = os.environ.get("{redactions[name]}", ""){newline}'
        replacements.append((start, end, replacement, name))

    for start, end, replacement, _ in sorted(replacements, reverse=True):
        lines[start:end] = [replacement]

    sanitized = "".join(lines)
    sanitized_tree = ast.parse(sanitized)
    os_import_added = False
    if not has_os_import(sanitized_tree):
        index = import_insert_index(sanitized, sanitized_tree)
        new_lines = sanitized.splitlines(keepends=True)
        new_lines[index:index] = ["import os\n"]
        sanitized = "".join(new_lines)
        os_import_added = True

    before_surface = surface(text)
    after_surface = surface(sanitized)
    diff = list(difflib.unified_diff(text.splitlines(), sanitized.splitlines(), lineterm=""))
    return sanitized, {
        "target_count": len(replacements),
        "target_names": sorted(redactions),
        "os_import_added": os_import_added,
        "surface_preserved": before_surface == after_surface,
        "before_surface_sha256": before_surface["sha256"],
        "after_surface_sha256": after_surface["sha256"],
        "diff_line_count": len(diff),
    }


def systemd_fingerprint(units: list[str]) -> str:
    rows: list[str] = []
    for unit in sorted(units):
        p = run([
            "systemctl", "show", unit,
            "-p", "Id", "-p", "ActiveState", "-p", "SubState",
            "-p", "MainPID", "-p", "FragmentPath", "-p", "ExecStart",
        ])
        rows.append(unit + "\n" + p.stdout)
    return text_digest("\n".join(rows))


def remote_branch_sha(root: Path, branch: str) -> str:
    p = run(["git", "-C", str(root), "ls-remote", "--heads", "origin", f"refs/heads/{branch}"])
    if p.returncode != 0 or not p.stdout.strip():
        return ""
    return p.stdout.split()[0]


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
    if parent.get("state") != "PASS" or parent.get("mutation_count") != 0 or parent.get("blocker_count") != 0:
        blockers.append("PARENT_NOT_PASS")

    parent_sources = {row.get("source"): row for row in parent.get("sources", []) if isinstance(row, dict)}
    runtime_snapshot = root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json"
    formal_ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    units = [row["unit"] for row in contract["targets"]]
    deployed_paths = [Path(row["source"]) for row in contract["targets"]]
    protected_before = {
        "runtime_snapshot": digest(runtime_snapshot),
        "formal_ledger": digest(formal_ledger),
        "systemd": systemd_fingerprint(units),
        "deployed_sources": {str(path): digest(path) for path in deployed_paths},
    }

    branch = contract["target_branch"]
    remote_before = remote_branch_sha(root, branch)
    if remote_before != args.target_sha:
        blockers.append(f"REMOTE_BRANCH_HEAD_DRIFT:{remote_before}")

    results: list[dict[str, Any]] = []
    git_commit_sha = ""
    git_push_performed = False

    with tempfile.TemporaryDirectory(prefix="r7a1a3b.") as raw:
        work = Path(raw)
        checkout = work / "repo"
        if not blockers:
            add = run(["git", "-C", str(root), "-c", f"safe.directory={root}", "worktree", "add", "--detach", str(checkout), args.target_sha])
            if add.returncode != 0:
                blockers.append("WORKTREE_ADD_FAILED")

        if not blockers:
            for target in contract["targets"]:
                source = Path(target["source"])
                canonical = checkout / target["canonical_path"]
                row: dict[str, Any] = {
                    "unit": target["unit"],
                    "source": target["source"],
                    "canonical_path": target["canonical_path"],
                    "mode": target["mode"],
                    "source_sha256": digest(source),
                }
                parent_row = parent_sources.get(str(source), {})
                if not source.is_file():
                    blockers.append("SOURCE_MISSING:" + str(source))
                    results.append(row)
                    continue
                if row["source_sha256"] != parent_row.get("sha256"):
                    blockers.append("SOURCE_HASH_DRIFT:" + str(source))
                if canonical.exists():
                    blockers.append("CANONICAL_TARGET_EXISTS:" + target["canonical_path"])
                    results.append(row)
                    continue
                canonical.parent.mkdir(parents=True, exist_ok=True)
                if target["mode"] == "BYTE_IDENTICAL_COPY":
                    shutil.copyfile(source, canonical)
                    row["byte_identical"] = digest(canonical) == digest(source)
                    if not row["byte_identical"]:
                        blockers.append("BYTE_COPY_MISMATCH:" + target["canonical_path"])
                else:
                    original = source.read_text(encoding="utf-8")
                    sanitized, meta = sanitize_telegram(original, target["redactions"])
                    canonical.write_text(sanitized, encoding="utf-8")
                    row.update(meta)
                    row["hardcoded_secret_count"] = hardcoded_secret_count(sanitized, target["redactions"])
                    row["command_counts_before"] = {cmd: original.count(cmd) for cmd in target["required_commands"]}
                    row["command_counts_after"] = {cmd: sanitized.count(cmd) for cmd in target["required_commands"]}
                    if row["target_count"] != 2:
                        blockers.append("TELEGRAM_REDACTION_TARGET_COUNT")
                    if row["hardcoded_secret_count"] != 0:
                        blockers.append("TELEGRAM_SECRET_REMAINS")
                    if not row["surface_preserved"]:
                        blockers.append("TELEGRAM_SURFACE_CHANGED")
                    if row["command_counts_before"] != row["command_counts_after"]:
                        blockers.append("TELEGRAM_COMMAND_SURFACE_CHANGED")
                row["canonical_sha256"] = digest(canonical)
                row["compile_ok"] = compile_check(canonical)
                if not row["compile_ok"]:
                    blockers.append("CANONICAL_COMPILE_FAILED:" + target["canonical_path"])
                results.append(row)

        protected_mid = {
            "runtime_snapshot": digest(runtime_snapshot),
            "formal_ledger": digest(formal_ledger),
            "systemd": systemd_fingerprint(units),
            "deployed_sources": {str(path): digest(path) for path in deployed_paths},
        }
        if protected_before != protected_mid:
            blockers.append("PROTECTED_RUNTIME_CHANGED_BEFORE_COMMIT")

        if not blockers:
            run(["git", "config", "user.name", "ZEL Canonical Import"], cwd=checkout)
            run(["git", "config", "user.email", "zel-canonical-import@localhost"], cwd=checkout)
            paths = [target["canonical_path"] for target in contract["targets"]]
            add = run(["git", "add", "--", *paths], cwd=checkout)
            if add.returncode != 0:
                blockers.append("GIT_ADD_FAILED")
            if not blockers:
                commit = run(["git", "commit", "-m", "Import active canonical sources with secret-safe Telegram config"], cwd=checkout)
                if commit.returncode != 0:
                    blockers.append("GIT_COMMIT_FAILED")
                else:
                    git_commit_sha = run(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()
            if not blockers:
                remote_now = remote_branch_sha(root, branch)
                if remote_now != args.target_sha:
                    blockers.append(f"REMOTE_BRANCH_MOVED_BEFORE_PUSH:{remote_now}")
            if not blockers:
                push = run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=checkout)
                if push.returncode != 0:
                    blockers.append("GIT_PUSH_FAILED")
                else:
                    git_push_performed = True

        if checkout.exists():
            run(["git", "-C", str(root), "-c", f"safe.directory={root}", "worktree", "remove", "--force", str(checkout)])

    protected_after = {
        "runtime_snapshot": digest(runtime_snapshot),
        "formal_ledger": digest(formal_ledger),
        "systemd": systemd_fingerprint(units),
        "deployed_sources": {str(path): digest(path) for path in deployed_paths},
    }
    runtime_mutation_count = 0 if protected_before == protected_after else 1
    if runtime_mutation_count:
        blockers.append("PROTECTED_RUNTIME_CHANGED")

    remote_after = remote_branch_sha(root, branch)
    if git_push_performed and remote_after != git_commit_sha:
        blockers.append("REMOTE_COMMIT_VERIFICATION_FAILED")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": contract["schema"] + "_status",
        "official_stage": contract["official_stage"],
        "state": state,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "runtime_mutation_count": runtime_mutation_count,
        "git_mutation_count": 1 if git_push_performed else 0,
        "target_branch": branch,
        "target_sha_before": args.target_sha,
        "canonical_commit_sha": git_commit_sha,
        "remote_sha_after": remote_after,
        "sources": results,
        "protected_before": protected_before,
        "protected_after": protected_after,
        "next_stage": contract["next_stage"] if state == "PASS" else "R7.A1A3B_DIAGNOSE",
    }
    atomic(args.output, payload)

    lines = [
        "# R7.A1A3B Exact Redaction and Canonical Import",
        "",
        f"- State: **{state}**",
        f"- Runtime mutation count: **{runtime_mutation_count}**",
        f"- Git mutation count: **{payload['git_mutation_count']}**",
        f"- Canonical commit: `{git_commit_sha or 'none'}`",
        "",
        "| Unit | Mode | Compile | Byte identical | Secret count | Surface preserved |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in results:
        lines.append(
            f"| {row['unit']} | {row['mode']} | {row.get('compile_ok')} | "
            f"{row.get('byte_identical', '-')} | {row.get('hardcoded_secret_count', '-')} | "
            f"{row.get('surface_preserved', '-')} |"
        )
    lines += ["", "No deployed source values or secret values are written to this report.", ""]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8")

    print("R7A1A3B_EXACT_REDACTION_CANONICAL_IMPORT_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"RUNTIME_MUTATION_COUNT={runtime_mutation_count}")
    print(f"GIT_MUTATION_COUNT={payload['git_mutation_count']}")
    print(f"CANONICAL_COMMIT_SHA={git_commit_sha or 'none'}")
    for index, row in enumerate(results, 1):
        print(
            f"SOURCE_{index}={row['unit']}|mode={row['mode']}|compile={row.get('compile_ok')}|"
            f"byte_identical={row.get('byte_identical')}|secret_count={row.get('hardcoded_secret_count')}|"
            f"surface_preserved={row.get('surface_preserved')}"
        )
    print(f"NEXT_STAGE={payload['next_stage']}")
    print(f"EVIDENCE_JSON={args.output}")
    print(f"EVIDENCE_REPORT={args.report}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
