#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def canonical_value_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def safe_repo_path(value: str) -> str | None:
    if not value or "\x00" in value or "\\" in value:
        return None
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return pure.as_posix()


def split_config_ref(value: str) -> tuple[str | None, str | None]:
    if "#" not in value:
        return None, None
    path, pointer = value.split("#", 1)
    return safe_repo_path(path), pointer


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


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def is_artifact_path(path: str, artifact_parts: set[str]) -> bool:
    safe = safe_repo_path(path)
    if not safe:
        return True
    return bool(set(PurePosixPath(safe.lower()).parts) & artifact_parts)


def git_show(root: Path, revision: str, repo_path: str) -> bytes | None:
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


def git_history(root: Path, repo_path: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "log", "--all", "--format=%H", "--", repo_path],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    seen: set[str] = set()
    revisions: list[str] = []
    for line in result.stdout.splitlines():
        revision = line.strip()
        if revision and revision not in seen:
            seen.add(revision)
            revisions.append(revision)
    return revisions[:200]


def decode_pointer(document_bytes: bytes, pointer: str) -> tuple[bool, Any]:
    try:
        value = json.loads(document_bytes.decode("utf-8"))
    except Exception:
        return False, None
    return json_pointer(value, pointer)


def resolve_config_value(
    root: Path,
    target_sha: str,
    repo_path: str,
    pointer: str,
) -> tuple[Any | None, dict[str, Any] | None, list[str]]:
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_documents: set[str] = set()

    def add_candidate(document: bytes | None, revision: str) -> None:
        if document is None:
            return
        document_sha = sha256_bytes(document)
        if document_sha in seen_documents:
            return
        seen_documents.add(document_sha)
        ok, value = decode_pointer(document, pointer)
        if not ok or value is None:
            errors.append(f"POINTER_UNRESOLVED:{revision}:{repo_path}#{pointer}")
            return
        candidates.append({
            "value": value,
            "value_sha256": canonical_value_sha(value),
            "document_sha256": document_sha,
            "source_revision": revision,
            "source_path": repo_path,
            "source_pointer": pointer,
        })

    worktree_path = root / repo_path
    if worktree_path.is_file():
        try:
            add_candidate(worktree_path.read_bytes(), "WORKTREE")
        except OSError:
            errors.append(f"WORKTREE_READ_FAILED:{repo_path}")

    add_candidate(git_show(root, target_sha, repo_path), target_sha)
    for revision in git_history(root, repo_path):
        add_candidate(git_show(root, revision, repo_path), revision)

    by_value: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_value.setdefault(str(candidate["value_sha256"]), []).append(candidate)
    if not by_value:
        return None, None, errors + [f"CONFIG_VALUE_NOT_FOUND:{repo_path}#{pointer}"]
    if len(by_value) != 1:
        return None, None, errors + [
            f"CONFIG_HISTORY_AMBIGUOUS:{repo_path}#{pointer}:variants={len(by_value)}"
        ]

    selected_group = next(iter(by_value.values()))
    priority = {"WORKTREE": 0, target_sha: 1}
    selected = sorted(
        selected_group,
        key=lambda row: (priority.get(str(row["source_revision"]), 2), str(row["source_revision"])),
    )[0]
    return selected["value"], {key: value for key, value in selected.items() if key != "value"}, errors


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def backup_file(root: Path, backup_root: Path, path: Path) -> Path:
    relative = path.relative_to(root)
    backup = backup_root / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    return backup


def rollback(created: list[Path], overwritten: dict[Path, Path]) -> None:
    for path in reversed(created):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for destination, backup in overwritten.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, destination)


def engine_fingerprint(entries: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in entries:
        strategy_id = str(row.get("strategy_id") or "")
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        result[strategy_id] = json.dumps(engine, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return result


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
    artifact_parts = {str(value).lower() for value in contract.get("artifact_parts", [])}
    prior_status = load_json(root / str(contract["prior_status_path"]))
    prior_proof = load_json(root / str(contract["prior_proof_path"]))
    registry_path = root / str(contract["registry_path"])
    config_path = root / str(contract["canonical_config_path"])
    registry = load_json(registry_path)
    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    blockers: list[str] = []
    resolution_errors: list[dict[str, Any]] = []

    expected_prior_artifacts = int(contract.get("expected_prior_artifact_reference_count", expected))
    prior_gate = bool(
        prior_status.get("state") == "HOLD"
        and int(prior_status.get("strategy_count", -1)) == expected
        and int(prior_status.get("source_count", -1)) == expected
        and int(prior_status.get("callable_count", -1)) == expected
        and int(prior_status.get("source_sha_parity_count", -1)) == expected
        and int(prior_status.get("config_ref_count", -1)) == expected
        and int(prior_status.get("config_resolved_count", -1)) == 0
        and int(prior_status.get("receipt_contract_count", -1)) == expected
        and int(prior_status.get("replay_contract_count", -1)) == 0
        and int(prior_status.get("artifact_reference_count", -1)) == expected_prior_artifacts
        and int(prior_status.get("active_entry_count", -1)) == 0
        and int(prior_status.get("static_risk_count", -1)) == 0
        and int(prior_status.get("mutation_count", -1)) == 0
        and prior_status.get("next_stage") == "R7.A3E3C_CONFIG_REFERENCE_CLOSURE"
    )
    if not prior_gate:
        blockers.append("PRIOR_A3E3_CONFIG_GAP_CONTRACT_INVALID")
    if prior_proof.get("semantic_pass") is True:
        blockers.append("PRIOR_A3E3_ALREADY_SEMANTIC_PASS")
    if not registry_path.is_file() or registry.get("schema") != "canonical_strategy25_registry_v1":
        blockers.append("REGISTRY_INVALID")
    strategy_ids = [str(row.get("strategy_id") or "") for row in entries]
    if len(entries) != expected or len(set(strategy_ids)) != expected or any(not value for value in strategy_ids):
        blockers.append("REGISTRY_ENTRY_COUNT_INVALID")
    if registry.get("fail_closed") is not True or int(registry.get("active_entry_count", -1)) != 0:
        blockers.append("REGISTRY_AUTHORITY_INVALID")
    if any(row.get("active_allowed") is not False or row.get("fail_closed") is not True for row in entries):
        blockers.append("ENTRY_AUTHORITY_INVALID")

    protected_paths = [Path(path) for path in contract.get("protected_paths", [])]
    protected_before = snapshot(protected_paths)
    engines_before = engine_fingerprint(entries)
    prior_artifact_ref_count = 0
    resolved_values: dict[str, Any] = {}
    provenance: dict[str, Any] = {}

    if not blockers:
        for row in sorted(entries, key=lambda item: str(item.get("strategy_id"))):
            strategy_id = str(row["strategy_id"])
            config_ref = str(row.get("config_ref") or "")
            repo_path, pointer = split_config_ref(config_ref)
            if not repo_path or pointer is None:
                resolution_errors.append({"strategy_id": strategy_id, "errors": ["CONFIG_REF_INVALID"]})
                continue
            prior_artifact_ref_count += int(is_artifact_path(repo_path, artifact_parts))
            value, receipt, errors = resolve_config_value(root, args.target_sha, repo_path, pointer)
            if value is None or receipt is None:
                resolution_errors.append({"strategy_id": strategy_id, "errors": errors or ["CONFIG_VALUE_UNRESOLVED"]})
                continue
            resolved_values[strategy_id] = value
            provenance[strategy_id] = {
                **receipt,
                "previous_config_ref": config_ref,
                "input_artifact_path": is_artifact_path(repo_path, artifact_parts),
            }

    created: list[Path] = []
    overwritten: dict[Path, Path] = {}
    verification_errors: list[str] = []
    applied = False
    backup_root = root / str(contract["rollback_root"]) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if args.apply and not blockers and not resolution_errors and len(resolved_values) == expected:
        try:
            canonical_config = {
                "schema": "canonical_strategy25_config_v1",
                "official_stage": "R7.A3E3C",
                "strategy_count": expected,
                "active_entry_count": 0,
                "fail_closed": True,
                "strategies": {key: resolved_values[key] for key in sorted(resolved_values)},
                "provenance": {key: provenance[key] for key in sorted(provenance)},
            }
            patched_registry = json.loads(json.dumps(registry))
            patched_entries = [row for row in patched_registry.get("entries", []) if isinstance(row, dict)]
            for row in patched_entries:
                strategy_id = str(row["strategy_id"])
                row["config_ref"] = (
                    f"{contract['canonical_config_path']}#/strategies/{pointer_token(strategy_id)}"
                )
                row["config_binding_source"] = "R7.A3E3C_CANONICAL_CONFIG_BUNDLE"
            patched_registry["entries"] = sorted(patched_entries, key=lambda row: str(row["strategy_id"]))

            for destination in (config_path, registry_path):
                if destination.is_file():
                    overwritten[destination] = backup_file(root, backup_root, destination)
                else:
                    created.append(destination)
            atomic_json(config_path, canonical_config)
            atomic_json(registry_path, patched_registry)

            reread_config = load_json(config_path)
            reread_registry = load_json(registry_path)
            reread_entries = [row for row in reread_registry.get("entries", []) if isinstance(row, dict)]
            if reread_config.get("schema") != "canonical_strategy25_config_v1":
                raise RuntimeError("CANONICAL_CONFIG_SCHEMA_INVALID")
            if int(reread_config.get("strategy_count", -1)) != expected:
                raise RuntimeError("CANONICAL_CONFIG_COUNT_INVALID")
            if set(reread_config.get("strategies", {})) != set(strategy_ids):
                raise RuntimeError("CANONICAL_CONFIG_IDS_INVALID")
            if len(reread_entries) != expected or len({str(row.get('strategy_id')) for row in reread_entries}) != expected:
                raise RuntimeError("PATCHED_REGISTRY_IDS_INVALID")
            if engine_fingerprint(reread_entries) != engines_before:
                raise RuntimeError("SOURCE_ENGINE_MUTATION_DETECTED")
            for row in reread_entries:
                strategy_id = str(row["strategy_id"])
                if row.get("active_allowed") is not False or row.get("fail_closed") is not True:
                    raise RuntimeError(f"ENTRY_AUTHORITY_CHANGED:{strategy_id}")
                repo_path, pointer = split_config_ref(str(row.get("config_ref") or ""))
                if repo_path != str(contract["canonical_config_path"]) or pointer is None:
                    raise RuntimeError(f"CANONICAL_CONFIG_REF_INVALID:{strategy_id}")
                ok, value = json_pointer(reread_config, pointer)
                if not ok or value != resolved_values[strategy_id]:
                    raise RuntimeError(f"CANONICAL_CONFIG_VALUE_MISMATCH:{strategy_id}")
                if is_artifact_path(repo_path, artifact_parts):
                    raise RuntimeError(f"ARTIFACT_CONFIG_REF_RETAINED:{strategy_id}")
            applied = True
        except Exception as exc:
            verification_errors.append(f"APPLY_FAILED:{type(exc).__name__}:{exc}")
            rollback(created, overwritten)
            applied = False

    protected_after = snapshot(protected_paths)
    protected_changed = sorted(path for path in protected_before if protected_before[path] != protected_after[path])
    if protected_changed:
        blockers.append("PROTECTED_PATH_CHANGED")
        if applied:
            rollback(created, overwritten)
            applied = False

    final_registry = load_json(registry_path)
    final_config = load_json(config_path)
    final_entries = [row for row in final_registry.get("entries", []) if isinstance(row, dict)]
    config_resolved_count = 0
    artifact_reference_after_count = 0
    rewritten_count = 0
    for row in final_entries:
        repo_path, pointer = split_config_ref(str(row.get("config_ref") or ""))
        if repo_path:
            artifact_reference_after_count += int(is_artifact_path(repo_path, artifact_parts))
        if repo_path == str(contract["canonical_config_path"]) and pointer is not None:
            rewritten_count += 1
            ok, value = json_pointer(final_config, pointer)
            config_resolved_count += int(ok and value is not None)

    source_engine_mutation_count = sum(
        engines_before.get(key) != engine_fingerprint(final_entries).get(key)
        for key in set(engines_before) | set(engine_fingerprint(final_entries))
    )
    active_count = sum(bool(row.get("active_allowed")) for row in final_entries)
    pass_gate = bool(
        applied
        and prior_artifact_ref_count == expected_prior_artifacts
        and rewritten_count == expected
        and config_resolved_count == expected
        and artifact_reference_after_count == 0
        and source_engine_mutation_count == 0
        and active_count == 0
        and not blockers
        and not resolution_errors
        and not verification_errors
        and not protected_changed
    )
    state = "PASS" if pass_gate else "HOLD"
    next_stage = str(contract["next_stage_pass"] if pass_gate else contract["next_stage_fail"])

    proof = {
        "schema": "r7a3e3c_config_reference_closure_proof_v1",
        "official_stage": "R7.A3E3C",
        "target_commit": args.target_sha,
        "state": state,
        "applied": applied,
        "prior_artifact_reference_count": prior_artifact_ref_count,
        "canonical_config_path": str(contract["canonical_config_path"]),
        "entries": [
            {
                "strategy_id": strategy_id,
                "canonical_config_ref": f"{contract['canonical_config_path']}#/strategies/{pointer_token(strategy_id)}",
                "config_value_sha256": canonical_value_sha(resolved_values[strategy_id]),
                "provenance": provenance[strategy_id],
            }
            for strategy_id in sorted(resolved_values)
        ],
        "resolution_errors": resolution_errors,
        "verification_errors": verification_errors,
        "protected_changed": protected_changed,
    }
    status = {
        "official_stage": "R7.A3E3C",
        "state": state,
        "blocker_count": len(blockers) + len(resolution_errors) + len(verification_errors),
        "blockers": blockers + verification_errors,
        "strategy_count": len(final_entries),
        "prior_artifact_reference_count": prior_artifact_ref_count,
        "config_value_resolved_count": len(resolved_values),
        "config_ref_rewritten_count": rewritten_count,
        "config_resolved_count": config_resolved_count,
        "artifact_reference_after_count": artifact_reference_after_count,
        "source_engine_mutation_count": source_engine_mutation_count,
        "active_entry_count": active_count,
        "protected_change_count": len(protected_changed),
        "runtime_mutation_count": 0,
        "canonical_config_path": str(config_path),
        "registry_path": str(registry_path),
        "proof_path": str(root / str(contract["proof_path"])),
        "next_stage": next_stage,
    }
    atomic_json(root / str(contract["proof_path"]), proof)
    atomic_json(root / str(contract["status_path"]), status)

    for key in (
        "state", "blocker_count", "strategy_count", "prior_artifact_reference_count",
        "config_value_resolved_count", "config_ref_rewritten_count", "config_resolved_count",
        "artifact_reference_after_count", "source_engine_mutation_count", "active_entry_count",
        "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("BLOCKERS=" + json.dumps(status["blockers"], ensure_ascii=False))
    print("RESOLUTION_ERRORS=" + json.dumps(resolution_errors, ensure_ascii=False))
    print("VERIFICATION_ERRORS=" + json.dumps(verification_errors, ensure_ascii=False))
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + str(0 if pass_gate else 2))
    return 0 if pass_gate else 2


if __name__ == "__main__":
    raise SystemExit(main())
