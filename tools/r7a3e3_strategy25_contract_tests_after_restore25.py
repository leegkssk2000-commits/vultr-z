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
from pathlib import Path, PurePosixPath
from typing import Any


ID_RE = re.compile(r"^[a-z0-9_]+$")


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
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def safe_repo_path(value: str) -> str | None:
    if not value or "\x00" in value or "\\" in value:
        return None
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return pure.as_posix()


def allowed_path(value: str, prefixes: list[str], artifact_parts: set[str]) -> bool:
    path = safe_repo_path(value)
    if not path or not path.startswith(tuple(prefixes)):
        return False
    return not bool(set(PurePosixPath(path.lower()).parts) & artifact_parts)


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


def json_pointer(value: Any, pointer: str) -> tuple[bool, Any]:
    if pointer in {"", "/"}:
        return True, value
    if not pointer.startswith("/"):
        return False, None
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return False, None
    return True, current


def split_config_ref(value: str) -> tuple[str | None, str | None]:
    if "#" not in value:
        return None, None
    path, pointer = value.split("#", 1)
    return safe_repo_path(path), pointer


def git_bytes(root: Path, revision: str, repo_path: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "show", f"{revision}:{repo_path}"],
            cwd=root,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    artifact_parts = {str(value).lower() for value in contract.get("artifact_parts", [])}
    source_prefixes = [str(value) for value in contract.get("allowed_source_prefixes", [])]
    config_prefixes = [str(value) for value in contract.get("allowed_config_prefixes", [])]

    prior_status = load_json(root / str(contract["prior_status_path"]))
    prior_verification = load_json(root / str(contract["prior_verification_path"]))
    restore_matrix = load_json(root / str(contract["prior_matrix_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    if not (
        prior_status.get("state") == "PASS"
        and int(prior_status.get("blocker_count", -1)) == 0
        and int(prior_status.get("total_source_count", -1)) == expected
        and int(prior_status.get("callable_valid_count", -1)) == expected
        and int(prior_status.get("config_bound_count", -1)) == expected
        and int(prior_status.get("canonical_unique_count", -1)) == expected
    ):
        blockers.append("PRIOR_RESTORE25_STATUS_INVALID")
    if not (
        prior_verification.get("applied") is True
        and int(prior_verification.get("total_source_count", -1)) == expected
        and int(prior_verification.get("callable_valid_count", -1)) == expected
        and int(prior_verification.get("config_bound_count", -1)) == expected
        and not prior_verification.get("errors")
    ):
        blockers.append("PRIOR_RESTORE25_VERIFICATION_INVALID")

    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    matrix_entries = [row for row in restore_matrix.get("entries", []) if isinstance(row, dict)]
    registry_ids = [str(row.get("strategy_id") or "") for row in entries]
    matrix_ids = {str(row.get("strategy_id") or "") for row in matrix_entries}

    if not registry_path.is_file():
        blockers.append("REGISTRY_MISSING")
    if registry.get("schema") != "canonical_strategy25_registry_v1":
        blockers.append("REGISTRY_SCHEMA_INVALID")
    if len(entries) != expected or len(set(registry_ids)) != expected or any(not ID_RE.fullmatch(value) for value in registry_ids):
        blockers.append("REGISTRY_IDS_INVALID")
    if set(registry_ids) != matrix_ids or len(matrix_ids) != expected:
        blockers.append("RESTORE_MATRIX_REGISTRY_ID_MISMATCH")
    if registry.get("fail_closed") is not True or int(registry.get("active_entry_count", -1)) != 0:
        blockers.append("REGISTRY_AUTHORITY_CONTRACT_INVALID")

    candidate_paths: list[Path] = [registry_path]
    for path in contract.get("protected_paths", []):
        candidate_paths.append(Path(str(path)))
    protected_before = snapshot(candidate_paths)

    proof_entries: list[dict[str, Any]] = []
    source_count = callable_count = sha_count = config_ref_count = 0
    config_resolved_count = receipt_count = replay_count = 0
    target_source_parity = target_config_parity = 0
    active_count = artifact_reference_count = 0
    side_effect_risk_count = 0
    config_paths: set[str] = set()
    binding_keys: list[tuple[str, str, str]] = []

    for row in sorted(entries, key=lambda item: str(item.get("strategy_id"))):
        strategy_id = str(row.get("strategy_id") or "")
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        implementation_path = str(engine.get("implementation_path") or "")
        callable_name = str(engine.get("callable") or "")
        expected_sha = str(engine.get("source_sha256") or "")
        config_ref = str(row.get("config_ref") or "")
        entry_errors: list[str] = []

        active_count += int(bool(row.get("active_allowed")))
        if row.get("active_allowed") is not False or row.get("fail_closed") is not True:
            entry_errors.append("ENTRY_NOT_INACTIVE_FAIL_CLOSED")

        if not allowed_path(implementation_path, source_prefixes, artifact_parts):
            entry_errors.append("SOURCE_PATH_INVALID_OR_ARTIFACT")
            artifact_reference_count += 1
        source_path = root / implementation_path if safe_repo_path(implementation_path) else root / "__invalid__"
        source = ""
        names: set[str] = set()
        current_sha = None
        if source_path.is_file():
            source_count += 1
            candidate_paths.append(source_path)
            source = source_path.read_text(encoding="utf-8", errors="replace")
            current_sha = sha256_bytes(source.encode())
            names = callable_names(source, implementation_path)
            if not names:
                entry_errors.append("SOURCE_AST_OR_CALLABLE_SET_INVALID")
            if any(token in source.lower() for token in ("lookahead=true", "future_data=true", "real_order_enabled=true")):
                side_effect_risk_count += 1
        else:
            entry_errors.append("SOURCE_FILE_MISSING")

        if callable_name and callable_name in names:
            callable_count += 1
        else:
            entry_errors.append("CALLABLE_NOT_RESOLVED")
        if expected_sha and current_sha == expected_sha:
            sha_count += 1
        else:
            entry_errors.append("SOURCE_SHA_MISMATCH")

        target_source = git_bytes(root, args.target_sha, implementation_path) if safe_repo_path(implementation_path) else None
        source_git_parity = bool(target_source is not None and current_sha == sha256_bytes(target_source))
        target_source_parity += int(source_git_parity)

        config_path, pointer = split_config_ref(config_ref)
        config_ok = False
        config_git_parity = False
        if config_ref:
            config_ref_count += 1
        if not config_path or pointer is None or not allowed_path(config_path, config_prefixes, artifact_parts):
            entry_errors.append("CONFIG_REF_INVALID_OR_ARTIFACT")
            if config_path and set(PurePosixPath(config_path.lower()).parts) & artifact_parts:
                artifact_reference_count += 1
        else:
            config_paths.add(config_path)
            manifest_path = root / config_path
            candidate_paths.append(manifest_path)
            manifest = load_json(manifest_path)
            pointer_ok, value = json_pointer(manifest, pointer)
            config_ok = bool(manifest_path.is_file() and pointer_ok and value is not None)
            if config_ok:
                config_resolved_count += 1
            else:
                entry_errors.append("CONFIG_POINTER_UNRESOLVED")
            target_config = git_bytes(root, args.target_sha, config_path)
            config_git_parity = bool(
                target_config is not None
                and manifest_path.is_file()
                and sha256_file(manifest_path) == sha256_bytes(target_config)
            )

        binding_keys.append((implementation_path, callable_name, config_ref))
        receipt_ok = bool(
            strategy_id and implementation_path and callable_name and expected_sha and config_ref
            and engine.get("binding_source") and engine.get("decision_reason")
        )
        receipt_count += int(receipt_ok)
        replay_ok = bool(
            source_path.is_file() and callable_name in names and current_sha == expected_sha
            and config_ok and row.get("active_allowed") is False and row.get("fail_closed") is True
        )
        replay_count += int(replay_ok)

        proof_entries.append({
            "strategy_id": strategy_id,
            "implementation_path": implementation_path,
            "callable": callable_name,
            "source_sha256": current_sha,
            "source_sha_parity": current_sha == expected_sha,
            "target_git_source_parity": source_git_parity,
            "config_ref": config_ref,
            "config_resolved": config_ok,
            "target_git_config_parity": config_git_parity,
            "receipt_contract": receipt_ok,
            "replay_contract": replay_ok,
            "errors": entry_errors,
        })

    for config_path in config_paths:
        manifest_path = root / config_path
        target = git_bytes(root, args.target_sha, config_path)
        target_config_parity += int(
            target is not None and manifest_path.is_file() and sha256_file(manifest_path) == sha256_bytes(target)
        )

    target_registry = git_bytes(root, args.target_sha, str(contract["registry_path"]))
    target_registry_parity = int(
        target_registry is not None and registry_path.is_file() and sha256_file(registry_path) == sha256_bytes(target_registry)
    )
    duplicate_binding_count = len(binding_keys) - len(set(binding_keys))
    unique_config_ref_count = len({str(row.get("config_ref") or "") for row in entries})

    protected_after = snapshot(candidate_paths)
    mutation_paths = sorted(path for path in protected_before if protected_before.get(path) != protected_after.get(path))
    mutation_count = len(mutation_paths)
    if mutation_count:
        blockers.append("READ_ONLY_CONTRACT_MUTATION_DETECTED")

    entry_error_count = sum(bool(row["errors"]) for row in proof_entries)
    semantic_pass = bool(
        not blockers
        and source_count == expected
        and callable_count == expected
        and sha_count == expected
        and config_ref_count == expected
        and config_resolved_count == expected
        and receipt_count == expected
        and replay_count == expected
        and active_count == 0
        and artifact_reference_count == 0
        and duplicate_binding_count == 0
        and unique_config_ref_count == expected
        and entry_error_count == 0
        and mutation_count == 0
    )
    persistence_gap_count = (
        expected - target_source_parity
        + (1 - target_registry_parity)
        + (len(config_paths) - target_config_parity)
    )
    persistence_complete = persistence_gap_count == 0

    if semantic_pass and persistence_complete:
        state = "PASS"
        next_stage = str(contract["next_stage_full_pass"])
        rc = 0
    elif semantic_pass:
        state = "PASS_LIVE_CANONICAL"
        next_stage = str(contract["next_stage_persistence_only"])
        rc = 0
    elif config_resolved_count < expected and source_count == expected and callable_count == expected and sha_count == expected:
        state = "HOLD"
        next_stage = str(contract["next_stage_config_gap"])
        rc = 2
    else:
        state = "HOLD"
        next_stage = str(contract["next_stage_fail"])
        rc = 2

    proof = {
        "schema": "r7a3e3_strategy25_contract_proof_v1",
        "official_stage": "R7.A3E3",
        "target_commit": args.target_sha,
        "state": state,
        "semantic_pass": semantic_pass,
        "persistence_complete": persistence_complete,
        "persistence_gap_count": persistence_gap_count,
        "unique_config_file_count": len(config_paths),
        "entries": proof_entries,
        "mutation_paths": mutation_paths,
    }
    status = {
        "official_stage": "R7.A3E3",
        "state": state,
        "blocker_count": len(blockers) + entry_error_count,
        "blockers": blockers,
        "strategy_count": len(entries),
        "source_count": source_count,
        "callable_count": callable_count,
        "source_sha_parity_count": sha_count,
        "config_ref_count": config_ref_count,
        "config_resolved_count": config_resolved_count,
        "unique_config_ref_count": unique_config_ref_count,
        "receipt_contract_count": receipt_count,
        "replay_contract_count": replay_count,
        "target_git_source_parity_count": target_source_parity,
        "target_git_registry_parity_count": target_registry_parity,
        "target_git_config_parity_count": target_config_parity,
        "unique_config_file_count": len(config_paths),
        "persistence_gap_count": persistence_gap_count,
        "duplicate_binding_count": duplicate_binding_count,
        "artifact_reference_count": artifact_reference_count,
        "active_entry_count": active_count,
        "static_risk_count": side_effect_risk_count,
        "mutation_count": mutation_count,
        "next_stage": next_stage,
        "proof_path": str(root / str(contract["proof_path"])),
    }
    atomic_json(root / str(contract["proof_path"]), proof)
    atomic_json(root / str(contract["status_path"]), status)

    for key in (
        "state", "blocker_count", "strategy_count", "source_count", "callable_count",
        "source_sha_parity_count", "config_ref_count", "config_resolved_count",
        "unique_config_ref_count", "receipt_contract_count", "replay_contract_count",
        "target_git_source_parity_count", "target_git_registry_parity_count",
        "target_git_config_parity_count", "unique_config_file_count", "persistence_gap_count",
        "duplicate_binding_count", "artifact_reference_count", "active_entry_count",
        "static_risk_count", "mutation_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("ENTRY_FAILURES=" + json.dumps(
        [{"strategy_id": row["strategy_id"], "errors": row["errors"]} for row in proof_entries if row["errors"]],
        ensure_ascii=False,
    ))
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + str(rc))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
