#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
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
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def git_bytes(root: Path, revision: str, repo_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "show", f"{revision}:{repo_path}"],
        cwd=root,
        capture_output=True,
        timeout=45,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def split_config_ref(value: str) -> tuple[str, str]:
    if "#" not in value:
        raise ValueError(f"CONFIG_REF_INVALID:{value}")
    path, pointer = value.split("#", 1)
    if not pointer.startswith("/"):
        raise ValueError(f"CONFIG_POINTER_INVALID:{value}")
    return safe_repo_path(path), pointer


def json_pointer(value: Any, pointer: str) -> Any:
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"CONFIG_POINTER_UNRESOLVED:{pointer}")
    return current


def callable_names(source: str, filename: str) -> set[str]:
    tree = ast.parse(source, filename=filename)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}.{child.name}")
    return names


def load_adapter(path: Path):
    spec = importlib.util.spec_from_file_location("r7a3e5_adapter_reaudit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ADAPTER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prior_gate(status: dict[str, Any], expected: int) -> bool:
    required = {
        "official_stage": "R7.A3E4",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": expected,
        "adapter_resolved_count": expected,
        "adapter_read_only_count": expected,
        "route_blocked_count": expected,
        "execution_blocked_count": expected,
        "fail_closed_count": expected,
        "hold_decision_count": expected,
        "strategy_module_import_count": 0,
        "adapter_target_git_parity_count": 1,
        "target_git_source_parity_count": expected,
        "target_git_registry_parity_count": 1,
        "target_git_config_parity_count": 1,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "active_entry_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "next_stage": "R7.A3E5_STRATEGY25_CANONICAL_REAUDIT",
    }
    return all(status.get(key) == value for key, value in required.items())


def has_artifact_binding(path: str, artifact_parts: set[str]) -> bool:
    parts = {part.lower() for part in PurePosixPath(path).parts}
    return bool(parts & artifact_parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    registry_repo = str(contract["registry_path"])
    config_repo = str(contract["canonical_config_path"])
    adapter_repo = str(contract["adapter_path"])
    registry_path = root / registry_repo
    config_path = root / config_repo
    adapter_path = root / adapter_repo
    prior_status = load_json(root / str(contract["prior_status_path"]))
    registry = load_json(registry_path)
    config = load_json(config_path)
    artifact_parts = {str(item).lower() for item in contract.get("artifact_parts", [])}
    blockers: list[str] = []
    findings: list[dict[str, Any]] = []

    if not prior_gate(prior_status, expected):
        blockers.append("PRIOR_A3E4_STATUS_INVALID")
    if registry.get("schema") != "canonical_strategy25_registry_v1":
        blockers.append("REGISTRY_SCHEMA_INVALID")
    if registry.get("fail_closed") is not True or int(registry.get("active_entry_count", -1)) != 0:
        blockers.append("REGISTRY_AUTHORITY_INVALID")
    if config.get("fail_closed") is not True or int(config.get("active_entry_count", -1)) != 0:
        blockers.append("CONFIG_AUTHORITY_INVALID")

    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    strategies = config.get("strategies") if isinstance(config.get("strategies"), dict) else {}
    if len(entries) != expected:
        blockers.append(f"REGISTRY_COUNT_INVALID:{len(entries)}")
    if len(strategies) != expected:
        blockers.append(f"CONFIG_STRATEGY_COUNT_INVALID:{len(strategies)}")
    if not adapter_path.is_file() or adapter_path.is_symlink():
        blockers.append("ADAPTER_FILE_INVALID")

    source_paths: list[Path] = []
    source_repo_paths: list[str] = []
    strategy_ids: list[str] = []
    binding_keys: list[tuple[str, str, str]] = []
    source_sha_match_count = 0
    callable_resolved_count = 0
    config_resolved_count = 0
    active_entry_count = 0
    binding_artifact_reference_count = 0

    for row in entries:
        strategy_id = str(row.get("strategy_id") or "")
        strategy_ids.append(strategy_id)
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        try:
            implementation_path = safe_repo_path(str(engine.get("implementation_path") or ""))
        except ValueError as exc:
            implementation_path = ""
            blockers.append(f"{exc}:{strategy_id}")
        callable_name = str(engine.get("callable") or "")
        expected_sha = str(engine.get("source_sha256") or "")
        config_ref = str(row.get("config_ref") or "")
        active_entry_count += int(row.get("active_allowed") is True)

        if row.get("active_allowed") is not False or row.get("fail_closed") is not True:
            blockers.append(f"ENTRY_AUTHORITY_INVALID:{strategy_id}")
        if not strategy_id:
            blockers.append("EMPTY_STRATEGY_ID")
        if implementation_path and not implementation_path.startswith("backend/strategies/"):
            blockers.append(f"SOURCE_PREFIX_INVALID:{strategy_id}:{implementation_path}")
        if implementation_path:
            source_repo_paths.append(implementation_path)
            source_path = root / implementation_path
            source_paths.append(source_path)
            if source_path.is_file() and not source_path.is_symlink():
                source_bytes = source_path.read_bytes()
                actual_sha = sha256_bytes(source_bytes)
                source_sha_match_count += int(bool(expected_sha) and actual_sha == expected_sha)
                try:
                    names = callable_names(source_bytes.decode("utf-8", errors="replace"), implementation_path)
                    callable_resolved_count += int(callable_name in names)
                except SyntaxError:
                    blockers.append(f"SOURCE_SYNTAX_INVALID:{strategy_id}")
            else:
                blockers.append(f"SOURCE_FILE_INVALID:{strategy_id}:{implementation_path}")

        try:
            config_ref_path, pointer = split_config_ref(config_ref)
            if config_ref_path != config_repo:
                blockers.append(f"CONFIG_PATH_NOT_CANONICAL:{strategy_id}:{config_ref_path}")
            value = json_pointer(config, pointer)
            direct_value = strategies.get(strategy_id)
            config_resolved_count += int(value is not None and value == direct_value)
            binding_artifact_reference_count += int(
                has_artifact_binding(implementation_path, artifact_parts)
                or has_artifact_binding(config_ref_path, artifact_parts)
            )
        except ValueError as exc:
            blockers.append(f"{exc}:{strategy_id}")

        binding_keys.append((implementation_path, callable_name, config_ref))
        findings.append({
            "strategy_id": strategy_id,
            "implementation_path": implementation_path,
            "callable": callable_name,
            "config_ref": config_ref,
            "active_allowed": row.get("active_allowed"),
            "fail_closed": row.get("fail_closed"),
        })

    unique_strategy_id_count = len(set(strategy_ids))
    duplicate_binding_count = len(binding_keys) - len(set(binding_keys))
    if unique_strategy_id_count != expected or set(strategy_ids) != set(strategies):
        blockers.append("STRATEGY_ID_SET_MISMATCH")
    if duplicate_binding_count:
        blockers.append(f"DUPLICATE_BINDING:{duplicate_binding_count}")
    if binding_artifact_reference_count:
        blockers.append(f"ACTIVE_BINDING_ARTIFACT_REFERENCE:{binding_artifact_reference_count}")

    canonical_paths = [registry_path, config_path, adapter_path, *source_paths]
    protected_paths = [Path(str(path)) for path in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)

    target_source_parity = 0
    for repo_path, path in zip(source_repo_paths, source_paths):
        target = git_bytes(root, args.target_sha, repo_path)
        target_source_parity += int(target is not None and path.is_file() and sha256_file(path) == sha256_bytes(target))
    target_registry = git_bytes(root, args.target_sha, registry_repo)
    target_config = git_bytes(root, args.target_sha, config_repo)
    target_adapter = git_bytes(root, args.target_sha, adapter_repo)
    target_registry_parity = int(target_registry is not None and sha256_file(registry_path) == sha256_bytes(target_registry))
    target_config_parity = int(target_config is not None and sha256_file(config_path) == sha256_bytes(target_config))
    target_adapter_parity = int(target_adapter is not None and sha256_file(adapter_path) == sha256_bytes(target_adapter))
    if target_source_parity != expected or target_registry_parity != 1 or target_config_parity != 1 or target_adapter_parity != 1:
        blockers.append("TARGET_GIT_PARITY_FAILED")

    adapter_resolved_count = 0
    adapter_read_only_count = 0
    route_blocked_count = 0
    execution_blocked_count = 0
    fail_closed_count = 0
    hold_decision_count = 0
    strategy_module_import_count = 0
    adapter_errors: list[str] = []

    if not blockers:
        modules_before = {name for name in sys.modules if name.startswith("backend.strategies.")}
        try:
            module = load_adapter(adapter_path)
            adapter = module.ReadOnlyStrategy25RegistryAdapter(root, expected_count=expected)
            adapter_ids = adapter.strategy_ids()
            if set(adapter_ids) != set(strategy_ids) or len(adapter_ids) != expected:
                adapter_errors.append("ADAPTER_ID_SET_MISMATCH")
            for strategy_id in adapter_ids:
                view = adapter.resolve_for_router(strategy_id)
                adapter_resolved_count += 1
                adapter_read_only_count += int(view.get("read_only") is True)
                route_blocked_count += int(view.get("route_allowed") is False)
                execution_blocked_count += int(view.get("execution_allowed") is False)
                fail_closed_count += int(view.get("fail_closed") is True and view.get("active_allowed") is False)
                hold_decision_count += int(view.get("decision") == "hold")
            try:
                adapter.resolve_for_router("__unknown_strategy__")
                adapter_errors.append("UNKNOWN_STRATEGY_NOT_REJECTED")
            except module.RegistryContractError:
                pass
        except Exception as exc:
            adapter_errors.append(f"ADAPTER_RUNTIME_ERROR:{type(exc).__name__}:{exc}")
        modules_after = {name for name in sys.modules if name.startswith("backend.strategies.")}
        strategy_module_import_count = len(modules_after - modules_before)
        if strategy_module_import_count:
            adapter_errors.append(f"STRATEGY_MODULE_IMPORT_DETECTED:{strategy_module_import_count}")

    after = snapshot(canonical_paths + protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    canonical_set = {str(item) for item in canonical_paths}
    protected_set = {str(item) for item in protected_paths}
    canonical_mutation_count = sum(1 for path in mutation_paths if path in canonical_set)
    protected_change_count = sum(1 for path in mutation_paths if path in protected_set)
    if mutation_paths:
        blockers.append("READ_ONLY_MUTATION_DETECTED")

    all_blockers = list(dict.fromkeys(blockers + adapter_errors))
    expected_counts = (
        source_sha_match_count,
        callable_resolved_count,
        config_resolved_count,
        adapter_resolved_count,
        adapter_read_only_count,
        route_blocked_count,
        execution_blocked_count,
        fail_closed_count,
        hold_decision_count,
    )
    success = bool(
        not all_blockers
        and all(value == expected for value in expected_counts)
        and unique_strategy_id_count == expected
        and duplicate_binding_count == 0
        and binding_artifact_reference_count == 0
        and active_entry_count == 0
        and strategy_module_import_count == 0
        and target_source_parity == expected
        and target_registry_parity == 1
        and target_config_parity == 1
        and target_adapter_parity == 1
        and canonical_mutation_count == 0
        and protected_change_count == 0
    )
    state = "PASS" if success else "HOLD"
    next_stage = str(contract["next_stage_pass"] if success else contract["next_stage_fail"])

    proof = {
        "schema": "r7a3e5_strategy25_canonical_reaudit_proof_v1",
        "official_stage": "R7.A3E5",
        "target_commit": args.target_sha,
        "state": state,
        "findings": findings,
        "mutation_paths": mutation_paths,
        "blockers": all_blockers,
    }
    status = {
        "official_stage": "R7.A3E5",
        "state": state,
        "blocker_count": len(all_blockers),
        "blockers": all_blockers,
        "strategy_count": expected,
        "registry_entry_count": len(entries),
        "unique_strategy_id_count": unique_strategy_id_count,
        "source_sha_match_count": source_sha_match_count,
        "callable_resolved_count": callable_resolved_count,
        "config_resolved_count": config_resolved_count,
        "adapter_resolved_count": adapter_resolved_count,
        "adapter_read_only_count": adapter_read_only_count,
        "route_blocked_count": route_blocked_count,
        "execution_blocked_count": execution_blocked_count,
        "fail_closed_count": fail_closed_count,
        "hold_decision_count": hold_decision_count,
        "binding_artifact_reference_count": binding_artifact_reference_count,
        "duplicate_binding_count": duplicate_binding_count,
        "strategy_module_import_count": strategy_module_import_count,
        "target_git_source_parity_count": target_source_parity,
        "target_git_registry_parity_count": target_registry_parity,
        "target_git_config_parity_count": target_config_parity,
        "adapter_target_git_parity_count": target_adapter_parity,
        "canonical_mutation_count": canonical_mutation_count,
        "protected_change_count": protected_change_count,
        "active_entry_count": active_entry_count,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "next_stage": next_stage,
        "proof_path": str(root / str(contract["proof_path"])),
    }
    atomic_json(root / str(contract["proof_path"]), proof)
    atomic_json(root / str(contract["status_path"]), status)

    for key in (
        "state", "blocker_count", "strategy_count", "registry_entry_count",
        "unique_strategy_id_count", "source_sha_match_count", "callable_resolved_count",
        "config_resolved_count", "adapter_resolved_count", "adapter_read_only_count",
        "route_blocked_count", "execution_blocked_count", "fail_closed_count",
        "hold_decision_count", "binding_artifact_reference_count", "duplicate_binding_count",
        "strategy_module_import_count", "target_git_source_parity_count",
        "target_git_registry_parity_count", "target_git_config_parity_count",
        "adapter_target_git_parity_count", "canonical_mutation_count",
        "protected_change_count", "active_entry_count", "router_mutation_count",
        "service_mutation_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("BLOCKERS=" + json.dumps(all_blockers, ensure_ascii=False))
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + ("0" if success else "2"))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
