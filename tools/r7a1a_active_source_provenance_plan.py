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
import time
from pathlib import Path
from typing import Any


def run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return payload


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    temp = Path(raw)
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def python_shape(text: str) -> dict[str, Any]:
    tree = ast.parse(text)
    imports: set[str] = set()
    functions: set[str] = set()
    classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
    return {
        "imports": sorted(imports),
        "functions": sorted(functions),
        "classes": sorted(classes),
    }


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def shape_score(left: dict[str, Any], right: dict[str, Any]) -> float:
    return round(
        0.25 * jaccard(set(left["imports"]), set(right["imports"]))
        + 0.60 * jaccard(set(left["functions"]), set(right["functions"]))
        + 0.15 * jaccard(set(left["classes"]), set(right["classes"])),
        6,
    )


def git_python_inventory(root: Path, target_sha: str) -> list[dict[str, Any]]:
    listing = run(["git", "-C", str(root), "-c", f"safe.directory={root}", "ls-tree", "-r", target_sha], timeout=90)
    if listing.returncode != 0:
        raise RuntimeError("GIT_LS_TREE_FAILED:" + listing.stderr[-300:])
    entries: list[tuple[str, str]] = []
    excluded = {".venv", "venv", "site-packages", "node_modules", "runtime", "backup", "backups", "archive", "archives", "rollback", "rollbacks", "cache", "caches"}
    for line in listing.stdout.splitlines():
        try:
            meta, path = line.split("\t", 1)
            blob = meta.split()[2]
        except (ValueError, IndexError):
            continue
        if not path.endswith(".py") or set(Path(path).parts) & excluded:
            continue
        entries.append((path, blob))
    if not entries:
        return []
    batch = subprocess.run(
        ["git", "-C", str(root), "-c", f"safe.directory={root}", "cat-file", "--batch"],
        input="".join(blob + "\n" for _, blob in entries).encode(),
        capture_output=True,
        timeout=120,
    )
    if batch.returncode != 0:
        raise RuntimeError("GIT_CAT_FILE_FAILED")
    result: list[dict[str, Any]] = []
    cursor = 0
    raw_output = batch.stdout
    for path, blob in entries:
        end = raw_output.find(b"\n", cursor)
        if end < 0:
            break
        header = raw_output[cursor:end].decode(errors="replace").split()
        cursor = end + 1
        if len(header) < 3 or header[1] != "blob":
            continue
        size = int(header[2])
        raw = raw_output[cursor:cursor + size]
        cursor += size + 1
        text = raw.decode("utf-8", errors="ignore")
        try:
            shape = python_shape(text)
            compile_ok = True
        except (SyntaxError, ValueError):
            shape = {"imports": [], "functions": [], "classes": []}
            compile_ok = False
        result.append({
            "path": path,
            "blob": blob,
            "sha256": sha256_bytes(raw),
            "shape": shape,
            "compile_ok": compile_ok,
        })
    return result


def unit_properties(unit: str) -> dict[str, Any]:
    props = ["Id", "LoadState", "ActiveState", "SubState", "UnitFileState", "MainPID", "ExecStart", "FragmentPath", "User", "Group"]
    command = ["systemctl", "show", unit]
    for prop in props:
        command += ["-p", prop]
    result = run(command)
    data: dict[str, Any] = {"returncode": result.returncode}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return data


def secret_scan(text: str, markers: list[str]) -> dict[str, Any]:
    categories: dict[str, int] = {}
    lowered = text.lower()
    for marker in markers:
        count = lowered.count(marker.lower())
        if count:
            categories[marker] = count
    token_like = len(re.findall(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", text))
    private_key = int("-----BEGIN PRIVATE KEY-----" in text or "-----BEGIN RSA PRIVATE KEY-----" in text)
    if token_like:
        categories["telegram_token_pattern"] = token_like
    if private_key:
        categories["private_key_block"] = private_key
    return {"category_count": len(categories), "hit_count": sum(categories.values()), "categories": categories}


def fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    probe = f"{url}{'&' if '?' in url else '?'}r7a1a={time.time_ns()}"
    command = ["curl", "-sS", "-L", "--max-time", "15", "-H", "Cache-Control: no-cache", "-w", "\n%{http_code}"]
    if url.startswith("https://alimi.z-os.vip/"):
        command += ["--resolve", "alimi.z-os.vip:443:127.0.0.1"]
    command.append(probe)
    result = run(command, timeout=20)
    body, _, code_raw = result.stdout.rpartition("\n")
    try:
        code = int(code_raw)
    except ValueError:
        code = 0
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}
    return code, payload if isinstance(payload, dict) else {}


def deep_first(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for child in value.values():
            found = deep_first(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = deep_first(child, keys)
            if found is not None:
                return found
    return None


def integer(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def writer_surface(payload: dict[str, Any]) -> dict[str, Any]:
    writers = deep_first(payload, ("writers", "writer_registry"))
    configured = deep_first(payload, ("configured_writer_count", "writer_registry_count"))
    active = deep_first(payload, ("active_writer_count", "active_writers"))
    if configured is None and isinstance(writers, list):
        configured = len(writers)
    return {
        "configured_writer_count": integer(configured),
        "active_writer_count": integer(active),
        "runtime_active": deep_first(payload, ("runtime_active",)),
        "epoch": deep_first(payload, ("epoch_id", "epoch")),
        "snapshot_sha256": deep_first(payload, ("source_snapshot_sha256", "snapshot_sha256")),
    }


def classify_writer(shadow: dict[str, Any], alimi: dict[str, Any], http_status: int) -> str:
    if http_status != 200:
        return "ALIMI_UNREACHABLE"
    if shadow.get("configured_writer_count") != alimi.get("configured_writer_count"):
        return "CONFIGURED_WRITER_REGISTRY_MISMATCH"
    if shadow.get("active_writer_count") == alimi.get("active_writer_count"):
        return "WRITER_PARITY"
    if shadow.get("runtime_active") is True and shadow.get("active_writer_count") == 1 and alimi.get("active_writer_count") == 0:
        return "ALIMI_PREBIND_ACTIVE_WRITER_STALE"
    return "ACTIVE_WRITER_AUTHORITY_MISMATCH"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(args.contract)
    root = Path(contract["repo_root"]).resolve()
    base_path = Path(contract["target_sha_source"])
    runtime = contract["runtime_files"]
    shadow_path = Path(runtime["shadow_snapshot"])
    ledger_path = Path(runtime["formal_ledger"])
    errors: list[str] = []

    if not base_path.is_file():
        errors.append("R7A1_BASE_STATUS_MISSING")
        base = {}
    else:
        base = read_json(base_path)
    if base.get("plan_execution", {}).get("state") != contract["pass_conditions"]["base_plan_state"]:
        errors.append("R7A1_BASE_NOT_PASS")
    if int(base.get("plan_execution", {}).get("mutation_count", -1)) != int(contract["pass_conditions"]["base_mutation_count"]):
        errors.append("R7A1_BASE_MUTATION_INVALID")

    before_sources = {row["source"]: sha256_file(Path(row["source"])) for row in contract["targets"]}
    before_ledger = sha256_file(ledger_path)
    before_shadow = sha256_file(shadow_path)
    repo_files = git_python_inventory(root, args.target_sha)

    source_rows: list[dict[str, Any]] = []
    for target in contract["targets"]:
        path = Path(target["source"])
        unit = unit_properties(target["unit"])
        exists = path.is_file()
        regular = exists and not path.is_symlink()
        text = path.read_text(encoding="utf-8", errors="strict") if exists else ""
        compile_ok = False
        shape = {"imports": [], "functions": [], "classes": []}
        compile_error = ""
        if exists:
            try:
                compile(text, str(path), "exec")
                shape = python_shape(text)
                compile_ok = True
            except Exception as exc:
                compile_error = f"{type(exc).__name__}:{exc}"
        source_sha = sha256_file(path)
        exact = [row["path"] for row in repo_files if source_sha and row["sha256"] == source_sha]
        basename = [row["path"] for row in repo_files if Path(row["path"]).name == path.name]
        similar = []
        if compile_ok:
            for row in repo_files:
                score = shape_score(shape, row["shape"])
                if score >= 0.35:
                    similar.append({"path": row["path"], "score": score})
            similar.sort(key=lambda row: row["score"], reverse=True)
        scan = secret_scan(text, list(contract["secret_markers"])) if exists else {"category_count": 0, "hit_count": 0, "categories": {}}
        exec_start = str(unit.get("ExecStart", ""))
        exact_ref = str(path) in exec_start
        if not exists:
            action = "RECOVER_SOURCE_OR_RETIRE_UNIT"
        elif exact:
            action = "PIN_EXISTING_EXACT_GIT_PATH_IN_RELEASE_MANIFEST"
        elif scan["hit_count"]:
            action = "REDACT_SECRET_MATERIAL_THEN_IMPORT_TO_CANONICAL_GIT_PATH"
        else:
            action = "IMPORT_DEPLOYED_SOURCE_TO_CANONICAL_GIT_PATH"
        row = {
            "unit": target["unit"],
            "source": str(path),
            "canonical_path": target["canonical_path"],
            "exists": exists,
            "regular_file": regular,
            "mode": oct(path.stat().st_mode & 0o777) if exists else None,
            "uid": path.stat().st_uid if exists else None,
            "gid": path.stat().st_gid if exists else None,
            "size_bytes": path.stat().st_size if exists else None,
            "mtime_ns": path.stat().st_mtime_ns if exists else None,
            "sha256": source_sha,
            "compile_ok": compile_ok,
            "compile_error": compile_error,
            "shape": shape,
            "secret_scan": scan,
            "unit_properties": unit,
            "unit_references_exact_source": exact_ref,
            "exact_git_matches": exact,
            "basename_git_matches": basename,
            "structural_candidates": similar[:10],
            "action": action,
        }
        source_rows.append(row)
        if not exists:
            errors.append(f"SOURCE_MISSING:{path}")
        if exists and not compile_ok:
            errors.append(f"SOURCE_COMPILE_FAILED:{path}")
        if not exact_ref:
            errors.append(f"UNIT_SOURCE_REFERENCE_MISMATCH:{target['unit']}")

    shadow_obj = read_json(shadow_path) if shadow_path.is_file() else {}
    alimi_http, alimi_obj = fetch_json(runtime["alimi_endpoint"])
    shadow_surface = writer_surface(shadow_obj)
    alimi_surface = writer_surface(alimi_obj)
    writer_class = classify_writer(shadow_surface, alimi_surface, alimi_http)

    after_sources = {row["source"]: sha256_file(Path(row["source"])) for row in contract["targets"]}
    after_ledger = sha256_file(ledger_path)
    after_shadow = sha256_file(shadow_path)
    changed = [path for path, value in before_sources.items() if after_sources.get(path) != value]
    if before_ledger != after_ledger:
        changed.append(str(ledger_path))
    if before_shadow != after_shadow:
        changed.append(str(shadow_path))
    mutation_count = len(changed)
    if mutation_count:
        errors.append("PROTECTED_INPUT_CHANGED_DURING_PLAN")

    unresolved = [row for row in source_rows if not row["exact_git_matches"]]
    state = "PASS" if not errors else "HOLD"
    next_stage = contract["next_stage_on_untracked"] if unresolved else contract["next_stage_on_provenance_resolved"]
    payload = {
        "schema": "zos_r7a1a_active_source_provenance_plan_status_v1",
        "official_stage": "R7.A1A",
        "state": state,
        "blockers": errors,
        "blocker_count": len(errors),
        "mutation_count": mutation_count,
        "changed_protected_inputs": changed,
        "target_sha": args.target_sha,
        "source_count": len(source_rows),
        "unresolved_source_count": len(unresolved),
        "sources": source_rows,
        "writer_parity": {
            "class": writer_class,
            "alimi_http_status": alimi_http,
            "shadow": shadow_surface,
            "alimi": alimi_surface,
        },
        "next_stage": next_stage,
        "evidence_paths": {"json": str(args.output), "markdown": str(args.report)},
    }
    atomic_json(args.output, payload)

    lines = [
        "# R7.A1A Active Source Provenance Plan", "",
        f"- State: **{state}**", f"- Mutation count: **{mutation_count}**",
        f"- Unresolved active sources: **{len(unresolved)}**", f"- Writer parity: **{writer_class}**", "",
        "## Active sources", "",
        "| Unit | Source | Compile | Exact Git match | Secret hits | Action |", "|---|---|---:|---:|---:|---|",
    ]
    for row in source_rows:
        lines.append(
            f"| {row['unit']} | `{row['source']}` | {row['compile_ok']} | {len(row['exact_git_matches'])} | "
            f"{row['secret_scan']['hit_count']} | {row['action']} |"
        )
    lines += ["", "## Writer surface", "", f"- Shadow: `{json.dumps(shadow_surface, sort_keys=True)}`", f"- ALIMI: `{json.dumps(alimi_surface, sort_keys=True)}`", "", f"Next stage: **{next_stage}**", ""]
    atomic_text(args.report, "\n".join(lines))

    print("R7A1A_ACTIVE_SOURCE_PROVENANCE_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(errors)}")
    print(f"MUTATION_COUNT={mutation_count}")
    print(f"SOURCE_COUNT={len(source_rows)}")
    print(f"UNRESOLVED_SOURCE_COUNT={len(unresolved)}")
    for index, row in enumerate(source_rows, 1):
        print(
            f"SOURCE_{index}={row['unit']}|{row['source']}|{row['sha256']}|compile={row['compile_ok']}|"
            f"secret_hits={row['secret_scan']['hit_count']}|exact_git={len(row['exact_git_matches'])}|"
            f"canonical={row['canonical_path']}|{row['action']}"
        )
    print(f"WRITER_PARITY_CLASS={writer_class}")
    print(f"SHADOW_CONFIGURED_WRITER_COUNT={shadow_surface.get('configured_writer_count')}")
    print(f"SHADOW_ACTIVE_WRITER_COUNT={shadow_surface.get('active_writer_count')}")
    print(f"ALIMI_CONFIGURED_WRITER_COUNT={alimi_surface.get('configured_writer_count')}")
    print(f"ALIMI_ACTIVE_WRITER_COUNT={alimi_surface.get('active_writer_count')}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={args.output}")
    print(f"EVIDENCE_REPORT={args.report}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
