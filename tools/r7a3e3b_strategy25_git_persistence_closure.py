#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() and not path.is_symlink() else None


def safe_repo_path(value: str) -> str | None:
    if not value or "\x00" in value or "\\" in value:
        return None
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return pure.as_posix()


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def callable_names(source: str, filename: str) -> set[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}.{child.name}")
    return names


def run(root: Path, args: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def git_bytes(root: Path, revision: str, repo_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "show", f"{revision}:{repo_path}"],
        cwd=root,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def remote_head(root: Path, remote: str, branch: str) -> str | None:
    result = run(root, ["git", "ls-remote", "--heads", remote, f"refs/heads/{branch}"], timeout=60)
    if result.returncode != 0:
        return None
    line = next((line for line in result.stdout.splitlines() if line.strip()), "")
    return line.split()[0] if line else None


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def restore_bytes(path: Path, value: bytes | None) -> None:
    if value is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def prior_gate(status: dict[str, Any], proof: dict[str, Any], expected: int, expected_gap: int) -> bool:
    required = {
        "strategy_count": expected,
        "source_count": expected,
        "callable_count": expected,
        "source_sha_parity_count": expected,
        "config_ref_count": expected,
        "config_resolved_count": expected,
        "unique_config_ref_count": expected,
        "receipt_contract_count": expected,
        "replay_contract_count": expected,
        "target_git_source_parity_count": 0,
        "target_git_registry_parity_count": 0,
        "target_git_config_parity_count": 0,
        "unique_config_file_count": 1,
        "persistence_gap_count": expected_gap,
        "duplicate_binding_count": 0,
        "artifact_reference_count": 0,
        "active_entry_count": 0,
        "static_risk_count": 0,
        "mutation_count": 0,
    }
    return bool(
        status.get("state") == "PASS_LIVE_CANONICAL"
        and int(status.get("blocker_count", -1)) == 0
        and status.get("next_stage") == "R7.A3E3B_GIT_PERSISTENCE_CLOSURE"
        and all(status.get(key) == value for key, value in required.items())
        and proof.get("semantic_pass") is True
        and proof.get("persistence_complete") is False
        and int(proof.get("persistence_gap_count", -1)) == expected_gap
    )


def collect_persist_files(root: Path, contract: dict[str, Any]) -> tuple[list[str], list[str]]:
    expected = int(contract["expected_strategy_count"])
    registry_repo = str(contract["registry_path"])
    config_repo = str(contract["canonical_config_path"])
    registry_path = root / registry_repo
    config_path = root / config_repo
    registry = load_json(registry_path)
    config = load_json(config_path)
    errors: list[str] = []
    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    ids = [str(row.get("strategy_id") or "") for row in entries]
    if registry.get("schema") != "canonical_strategy25_registry_v1":
        errors.append("REGISTRY_SCHEMA_INVALID")
    if len(entries) != expected or len(set(ids)) != expected or any(not value for value in ids):
        errors.append("REGISTRY_IDS_INVALID")
    if registry.get("fail_closed") is not True or int(registry.get("active_entry_count", -1)) != 0:
        errors.append("REGISTRY_AUTHORITY_INVALID")
    if config.get("schema") != "canonical_strategy25_config_v1":
        errors.append("CONFIG_SCHEMA_INVALID")
    strategies = config.get("strategies") if isinstance(config.get("strategies"), dict) else {}
    if int(config.get("strategy_count", -1)) != expected or set(strategies) != set(ids):
        errors.append("CONFIG_IDS_INVALID")
    if config.get("fail_closed") is not True or int(config.get("active_entry_count", -1)) != 0:
        errors.append("CONFIG_AUTHORITY_INVALID")

    prefixes = tuple(str(value) for value in contract.get("allowed_source_prefixes", []))
    artifact_parts = {str(value).lower() for value in contract.get("artifact_parts", [])}
    source_paths: list[str] = []
    for row in entries:
        strategy_id = str(row.get("strategy_id") or "")
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        repo_path = safe_repo_path(str(engine.get("implementation_path") or ""))
        callable_name = str(engine.get("callable") or "")
        expected_sha = str(engine.get("source_sha256") or "")
        if row.get("active_allowed") is not False or row.get("fail_closed") is not True:
            errors.append(f"ENTRY_AUTHORITY_INVALID:{strategy_id}")
        if not repo_path or not repo_path.startswith(prefixes):
            errors.append(f"SOURCE_PATH_INVALID:{strategy_id}")
            continue
        if set(PurePosixPath(repo_path.lower()).parts) & artifact_parts:
            errors.append(f"SOURCE_ARTIFACT_PATH:{strategy_id}")
            continue
        source_path = root / repo_path
        if not source_path.is_file() or source_path.is_symlink():
            errors.append(f"SOURCE_FILE_INVALID:{strategy_id}:{repo_path}")
            continue
        current_sha = sha256_file(source_path)
        if not expected_sha or current_sha != expected_sha:
            errors.append(f"SOURCE_SHA_MISMATCH:{strategy_id}")
        names = callable_names(source_path.read_text(encoding="utf-8", errors="replace"), repo_path)
        if callable_name not in names:
            errors.append(f"CALLABLE_INVALID:{strategy_id}:{callable_name}")
        expected_ref = f"{config_repo}#/strategies/{pointer_token(strategy_id)}"
        if str(row.get("config_ref") or "") != expected_ref:
            errors.append(f"CONFIG_REF_INVALID:{strategy_id}")
        source_paths.append(repo_path)

    if len(source_paths) != expected or len(set(source_paths)) != expected:
        errors.append("SOURCE_PATH_SET_INVALID")
    files = sorted(set(source_paths + [registry_repo, config_repo]))
    if len(files) != int(contract["expected_persist_file_count"]):
        errors.append(f"PERSIST_FILE_COUNT_INVALID:{len(files)}")
    for repo_path in files:
        path = root / repo_path
        if not path.is_file() or path.is_symlink():
            errors.append(f"PERSIST_FILE_INVALID:{repo_path}")
    return files, list(dict.fromkeys(errors))


def build_commit(root: Path, target_sha: str, files: list[str]) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="r7a3e3b_index_") as temp_name:
        index_path = Path(temp_name) / "index"
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(index_path)
        for key, fallback in (
            ("GIT_AUTHOR_NAME", "Z Ops Persistence"),
            ("GIT_COMMITTER_NAME", "Z Ops Persistence"),
            ("GIT_AUTHOR_EMAIL", "z-ops@localhost"),
            ("GIT_COMMITTER_EMAIL", "z-ops@localhost"),
        ):
            env.setdefault(key, fallback)
        result = run(root, ["git", "read-tree", target_sha], env=env)
        if result.returncode != 0:
            return None, [f"READ_TREE_FAILED:{result.stderr.strip()}"]
        for repo_path in files:
            blob_result = run(root, ["git", "hash-object", "-w", "--", repo_path])
            if blob_result.returncode != 0:
                errors.append(f"HASH_OBJECT_FAILED:{repo_path}:{blob_result.stderr.strip()}")
                continue
            blob = blob_result.stdout.strip()
            update = run(root, ["git", "update-index", "--add", "--cacheinfo", "100644", blob, repo_path], env=env)
            if update.returncode != 0:
                errors.append(f"UPDATE_INDEX_FAILED:{repo_path}:{update.stderr.strip()}")
        if errors:
            return None, errors
        tree_result = run(root, ["git", "write-tree"], env=env)
        if tree_result.returncode != 0:
            return None, [f"WRITE_TREE_FAILED:{tree_result.stderr.strip()}"]
        message = "R7.A3E3B persist canonical Strategy25 sources, registry, and config\n"
        commit_result = run(
            root,
            ["git", "commit-tree", tree_result.stdout.strip(), "-p", target_sha],
            env=env,
            input_text=message,
        )
        if commit_result.returncode != 0:
            return None, [f"COMMIT_TREE_FAILED:{commit_result.stderr.strip()}"]
        commit_sha = commit_result.stdout.strip()

    diff = run(root, ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", target_sha, commit_sha])
    changed = sorted(line.strip() for line in diff.stdout.splitlines() if line.strip())
    if diff.returncode != 0 or changed != sorted(files):
        errors.append(f"COMMIT_SCOPE_INVALID:{json.dumps(changed, ensure_ascii=False)}")
    for repo_path in files:
        committed = git_bytes(root, commit_sha, repo_path)
        current = (root / repo_path).read_bytes()
        if committed is None or sha256_bytes(committed) != sha256_bytes(current):
            errors.append(f"COMMIT_PARITY_FAILED:{repo_path}")
    return (commit_sha if not errors else None), errors


def push_ref(root: Path, remote: str, branch: str, old_sha: str, new_sha: str) -> tuple[bool, str]:
    result = run(
        root,
        [
            "git", "push",
            f"--force-with-lease=refs/heads/{branch}:{old_sha}",
            remote,
            f"{new_sha}:refs/heads/{branch}",
        ],
        timeout=180,
    )
    return result.returncode == 0, (result.stderr or result.stdout).strip()


def run_a3e3_reverify(root: Path, commit_sha: str, contract: dict[str, Any]) -> tuple[dict[str, Any], list[str], dict[Path, bytes | None]]:
    verifier_repo = str(contract["a3e3_verifier_path"])
    a3e3_contract_repo = str(contract["a3e3_contract_path"])
    verifier = git_bytes(root, commit_sha, verifier_repo)
    contract_bytes = git_bytes(root, commit_sha, a3e3_contract_repo)
    if verifier is None or contract_bytes is None:
        return {}, ["A3E3_VERIFIER_MATERIALIZATION_FAILED"], {}
    with tempfile.TemporaryDirectory(prefix="r7a3e3b_reverify_") as temp_name:
        temp = Path(temp_name)
        verifier_path = temp / "verifier.py"
        a3e3_contract_path = temp / "contract.json"
        verifier_path.write_bytes(verifier)
        a3e3_contract_path.write_bytes(contract_bytes)
        a3e3_contract = json.loads(contract_bytes.decode("utf-8"))
        status_path = root / str(a3e3_contract["status_path"])
        proof_path = root / str(a3e3_contract["proof_path"])
        backups = {
            status_path: status_path.read_bytes() if status_path.is_file() else None,
            proof_path: proof_path.read_bytes() if proof_path.is_file() else None,
        }
        result = run(
            root,
            ["python3", str(verifier_path), "--root", str(root), "--target-sha", commit_sha, "--contract", str(a3e3_contract_path)],
            timeout=180,
        )
        status = load_json(status_path)
        expected = int(contract["expected_strategy_count"])
        required = {
            "state": "PASS",
            "blocker_count": 0,
            "strategy_count": expected,
            "source_count": expected,
            "callable_count": expected,
            "source_sha_parity_count": expected,
            "config_ref_count": expected,
            "config_resolved_count": expected,
            "unique_config_ref_count": expected,
            "receipt_contract_count": expected,
            "replay_contract_count": expected,
            "target_git_source_parity_count": expected,
            "target_git_registry_parity_count": 1,
            "target_git_config_parity_count": 1,
            "unique_config_file_count": 1,
            "persistence_gap_count": 0,
            "duplicate_binding_count": 0,
            "artifact_reference_count": 0,
            "active_entry_count": 0,
            "static_risk_count": 0,
            "mutation_count": 0,
            "next_stage": contract["next_stage_pass"],
        }
        errors = []
        if result.returncode != 0:
            errors.append(f"A3E3_REVERIFY_RC:{result.returncode}:{result.stdout[-2000:]}:{result.stderr[-1000:]}")
        errors.extend(
            f"A3E3_REVERIFY_MISMATCH:{key}:{status.get(key)}!={value}"
            for key, value in required.items()
            if status.get(key) != value
        )
        return status, errors, backups


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    expected_files = int(contract.get("expected_persist_file_count", 27))
    expected_gap = int(contract.get("expected_prior_persistence_gap_count", 27))
    status_path = root / str(contract["status_path"])
    proof_path = root / str(contract["proof_path"])
    prior_status = load_json(root / str(contract["prior_status_path"]))
    prior_proof = load_json(root / str(contract["prior_proof_path"]))
    blockers: list[str] = []

    if not prior_gate(prior_status, prior_proof, expected, expected_gap):
        blockers.append("PRIOR_A3E3_LIVE_CANONICAL_GATE_INVALID")
    target_check = run(root, ["git", "cat-file", "-e", f"{args.target_sha}^{{commit}}"])
    if target_check.returncode != 0:
        blockers.append("TARGET_SHA_INVALID")
    files, file_errors = collect_persist_files(root, contract)
    blockers.extend(file_errors)

    protected_paths = [Path(str(path)) for path in contract.get("protected_paths", [])]
    protected_before = snapshot(protected_paths)
    remote = str(contract.get("remote_name", "origin"))
    branch = str(contract["persistence_branch"])
    remote_before = remote_head(root, remote, branch)
    if remote_before != args.target_sha:
        blockers.append(f"REMOTE_HEAD_MISMATCH:{remote_before}!={args.target_sha}")

    commit_sha: str | None = None
    pushed = False
    reverify_status: dict[str, Any] = {}
    verification_errors: list[str] = []
    rollback_errors: list[str] = []

    if args.apply and not blockers:
        commit_sha, build_errors = build_commit(root, args.target_sha, files)
        verification_errors.extend(build_errors)
        if commit_sha and not verification_errors:
            pushed, push_message = push_ref(root, remote, branch, args.target_sha, commit_sha)
            if not pushed:
                verification_errors.append(f"PUSH_FAILED:{push_message}")
            elif remote_head(root, remote, branch) != commit_sha:
                verification_errors.append("REMOTE_POST_PUSH_PARITY_FAILED")
        if pushed and commit_sha and not verification_errors:
            reverify_status, reverify_errors, a3e3_backups = run_a3e3_reverify(root, commit_sha, contract)
            verification_errors.extend(reverify_errors)
        else:
            a3e3_backups = {}

        protected_after = snapshot(protected_paths)
        changed = sorted(path for path in protected_before if protected_before[path] != protected_after[path])
        if changed:
            verification_errors.append("PROTECTED_PATH_CHANGED:" + json.dumps(changed, ensure_ascii=False))

        if verification_errors and pushed and commit_sha:
            ok, message = push_ref(root, remote, branch, commit_sha, args.target_sha)
            if not ok or remote_head(root, remote, branch) != args.target_sha:
                rollback_errors.append(f"REMOTE_ROLLBACK_FAILED:{message}")
            for path, value in a3e3_backups.items():
                try:
                    restore_bytes(path, value)
                except OSError as exc:
                    rollback_errors.append(f"A3E3_STATUS_ROLLBACK_FAILED:{path}:{exc}")
            pushed = False

    final_remote = remote_head(root, remote, branch)
    success = bool(
        args.apply
        and not blockers
        and not verification_errors
        and not rollback_errors
        and commit_sha
        and pushed
        and final_remote == commit_sha
        and reverify_status.get("state") == "PASS"
    )
    state = "PASS" if success else ("PLAN" if not args.apply and not blockers else "HOLD")
    next_stage = str(contract["next_stage_pass"] if success else contract["next_stage_fail"])
    all_blockers = list(dict.fromkeys(blockers + verification_errors + rollback_errors))
    proof = {
        "schema": "r7a3e3b_strategy25_git_persistence_proof_v1",
        "official_stage": "R7.A3E3B",
        "state": state,
        "target_commit": args.target_sha,
        "persistence_commit": commit_sha,
        "remote_before": remote_before,
        "remote_after": final_remote,
        "persistence_branch": branch,
        "persist_files": files,
        "persist_file_count": len(files),
        "a3e3_reverify_status": reverify_status,
        "blockers": all_blockers,
    }
    status = {
        "official_stage": "R7.A3E3B",
        "state": state,
        "blocker_count": len(all_blockers),
        "blockers": all_blockers,
        "strategy_count": expected,
        "persist_file_count": len(files),
        "persisted_source_count": expected if success else 0,
        "persisted_registry_count": 1 if success else 0,
        "persisted_config_count": 1 if success else 0,
        "target_git_source_parity_count": reverify_status.get("target_git_source_parity_count", 0),
        "target_git_registry_parity_count": reverify_status.get("target_git_registry_parity_count", 0),
        "target_git_config_parity_count": reverify_status.get("target_git_config_parity_count", 0),
        "persistence_gap_count": reverify_status.get("persistence_gap_count", expected_gap),
        "artifact_reference_count": reverify_status.get("artifact_reference_count", 0),
        "active_entry_count": reverify_status.get("active_entry_count", 0),
        "protected_change_count": 0 if snapshot(protected_paths) == protected_before else 1,
        "persistence_commit": commit_sha,
        "persistence_branch": branch,
        "next_stage": next_stage,
        "proof_path": str(proof_path),
    }
    atomic_json(proof_path, proof)
    atomic_json(status_path, status)

    for key in (
        "state", "blocker_count", "strategy_count", "persist_file_count",
        "persisted_source_count", "persisted_registry_count", "persisted_config_count",
        "target_git_source_parity_count", "target_git_registry_parity_count",
        "target_git_config_parity_count", "persistence_gap_count",
        "artifact_reference_count", "active_entry_count", "protected_change_count",
        "persistence_commit", "persistence_branch", "next_stage",
    ):
        print(f"{key.upper()}={status.get(key)}")
    print("BLOCKERS=" + json.dumps(all_blockers, ensure_ascii=False))
    print("PERSIST_FILES=" + json.dumps(files, ensure_ascii=False))
    print("PROOF_JSON=" + str(proof_path))
    rc = 0 if state in {"PASS", "PLAN"} else 2
    print(f"RC={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
