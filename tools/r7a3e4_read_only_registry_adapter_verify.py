#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
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


def load_adapter(path: Path):
    spec = importlib.util.spec_from_file_location("r7a3e4_read_only_registry_adapter_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ADAPTER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prior_gate(status: dict[str, Any], expected: int) -> bool:
    required = {
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": expected,
        "persist_file_count": expected + 2,
        "persisted_source_count": expected,
        "persisted_registry_count": 1,
        "persisted_config_count": 1,
        "target_git_source_parity_count": expected,
        "target_git_registry_parity_count": 1,
        "target_git_config_parity_count": 1,
        "persistence_gap_count": 0,
        "artifact_reference_count": 0,
        "active_entry_count": 0,
        "protected_change_count": 0,
        "next_stage": "R7.A3E4_READ_ONLY_REGISTRY_ADAPTER",
    }
    return all(status.get(key) == value for key, value in required.items())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    adapter_repo = str(contract["adapter_path"])
    registry_repo = str(contract["registry_path"])
    config_repo = str(contract["canonical_config_path"])
    adapter_path = root / adapter_repo
    registry_path = root / registry_repo
    config_path = root / config_repo
    prior_status = load_json(root / str(contract["prior_status_path"]))
    registry = load_json(registry_path)
    blockers: list[str] = []

    if not prior_gate(prior_status, expected):
        blockers.append("PRIOR_A3E3B_STATUS_INVALID")
    if not adapter_path.is_file() or adapter_path.is_symlink():
        blockers.append("ADAPTER_FILE_INVALID")
    if registry.get("schema") != "canonical_strategy25_registry_v1":
        blockers.append("REGISTRY_SCHEMA_INVALID")
    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    if len(entries) != expected:
        blockers.append(f"REGISTRY_COUNT_INVALID:{len(entries)}")

    source_paths: list[Path] = []
    source_repo_paths: list[str] = []
    for row in entries:
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        repo_path = str(engine.get("implementation_path") or "")
        source_repo_paths.append(repo_path)
        source_paths.append(root / repo_path)

    canonical_paths = [registry_path, config_path, *source_paths]
    protected_paths = [Path(str(path)) for path in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)

    adapter_target = git_bytes(root, args.target_sha, adapter_repo)
    adapter_git_parity = int(
        adapter_target is not None
        and adapter_path.is_file()
        and sha256_file(adapter_path) == sha256_bytes(adapter_target)
    )
    if adapter_git_parity != 1:
        blockers.append("ADAPTER_TARGET_GIT_PARITY_FAILED")

    adapter_source = adapter_path.read_text(encoding="utf-8", errors="replace") if adapter_path.is_file() else ""
    forbidden_hits = [token for token in contract.get("forbidden_adapter_tokens", []) if str(token) in adapter_source]
    if forbidden_hits:
        blockers.append("ADAPTER_FORBIDDEN_TOKEN:" + ",".join(forbidden_hits))

    target_source_parity = 0
    for repo_path, path in zip(source_repo_paths, source_paths):
        target = git_bytes(root, args.target_sha, repo_path)
        target_source_parity += int(target is not None and path.is_file() and sha256_file(path) == sha256_bytes(target))
    target_registry = git_bytes(root, args.target_sha, registry_repo)
    target_config = git_bytes(root, args.target_sha, config_repo)
    target_registry_parity = int(target_registry is not None and sha256_file(registry_path) == sha256_bytes(target_registry))
    target_config_parity = int(target_config is not None and sha256_file(config_path) == sha256_bytes(target_config))
    if target_source_parity != expected or target_registry_parity != 1 or target_config_parity != 1:
        blockers.append("CANONICAL_TARGET_GIT_PARITY_FAILED")

    resolved_count = fail_closed_count = hold_count = read_only_count = 0
    route_blocked_count = execution_blocked_count = 0
    strategy_module_import_count = 0
    adapter_errors: list[str] = []
    views: list[dict[str, Any]] = []

    if not blockers:
        modules_before = {name for name in sys.modules if name.startswith("backend.strategies.")}
        try:
            module = load_adapter(adapter_path)
            adapter = module.ReadOnlyStrategy25RegistryAdapter(root, expected_count=expected)
            ids = adapter.strategy_ids()
            if len(ids) != expected or len(set(ids)) != expected:
                adapter_errors.append(f"ADAPTER_ID_SET_INVALID:{len(ids)}")
            for strategy_id in ids:
                view = adapter.resolve_for_router(strategy_id)
                resolved_count += 1
                read_only_count += int(view.get("read_only") is True)
                route_blocked_count += int(view.get("route_allowed") is False)
                execution_blocked_count += int(view.get("execution_allowed") is False)
                fail_closed_count += int(view.get("fail_closed") is True and view.get("active_allowed") is False)
                hold_count += int(view.get("decision") == "hold")
                views.append({
                    "strategy_id": strategy_id,
                    "read_only": view.get("read_only"),
                    "route_allowed": view.get("route_allowed"),
                    "execution_allowed": view.get("execution_allowed"),
                    "active_allowed": view.get("active_allowed"),
                    "fail_closed": view.get("fail_closed"),
                    "decision": view.get("decision"),
                    "reason": view.get("reason"),
                })
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
    canonical_mutation_count = sum(1 for path in mutation_paths if path in {str(item) for item in canonical_paths})
    protected_change_count = sum(1 for path in mutation_paths if path in {str(item) for item in protected_paths})
    if mutation_paths:
        blockers.append("READ_ONLY_MUTATION_DETECTED")

    counts_ok = all(value == expected for value in (
        resolved_count,
        fail_closed_count,
        hold_count,
        read_only_count,
        route_blocked_count,
        execution_blocked_count,
    ))
    success = bool(
        not blockers
        and not adapter_errors
        and counts_ok
        and adapter_git_parity == 1
        and target_source_parity == expected
        and target_registry_parity == 1
        and target_config_parity == 1
        and strategy_module_import_count == 0
        and canonical_mutation_count == 0
        and protected_change_count == 0
    )
    state = "PASS" if success else "HOLD"
    next_stage = str(contract["next_stage_pass"] if success else contract["next_stage_fail"])
    all_blockers = list(dict.fromkeys(blockers + adapter_errors))

    proof = {
        "schema": "r7a3e4_read_only_registry_adapter_proof_v1",
        "official_stage": "R7.A3E4",
        "target_commit": args.target_sha,
        "state": state,
        "views": views,
        "mutation_paths": mutation_paths,
        "blockers": all_blockers,
    }
    status = {
        "official_stage": "R7.A3E4",
        "state": state,
        "blocker_count": len(all_blockers),
        "blockers": all_blockers,
        "strategy_count": expected,
        "adapter_resolved_count": resolved_count,
        "adapter_read_only_count": read_only_count,
        "route_blocked_count": route_blocked_count,
        "execution_blocked_count": execution_blocked_count,
        "fail_closed_count": fail_closed_count,
        "hold_decision_count": hold_count,
        "strategy_module_import_count": strategy_module_import_count,
        "adapter_target_git_parity_count": adapter_git_parity,
        "target_git_source_parity_count": target_source_parity,
        "target_git_registry_parity_count": target_registry_parity,
        "target_git_config_parity_count": target_config_parity,
        "canonical_mutation_count": canonical_mutation_count,
        "protected_change_count": protected_change_count,
        "active_entry_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "next_stage": next_stage,
        "proof_path": str(root / str(contract["proof_path"])),
    }
    atomic_json(root / str(contract["proof_path"]), proof)
    atomic_json(root / str(contract["status_path"]), status)

    for key in (
        "state", "blocker_count", "strategy_count", "adapter_resolved_count",
        "adapter_read_only_count", "route_blocked_count", "execution_blocked_count",
        "fail_closed_count", "hold_decision_count", "strategy_module_import_count",
        "adapter_target_git_parity_count", "target_git_source_parity_count",
        "target_git_registry_parity_count", "target_git_config_parity_count",
        "canonical_mutation_count", "protected_change_count", "active_entry_count",
        "router_mutation_count", "service_mutation_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("BLOCKERS=" + json.dumps(all_blockers, ensure_ascii=False))
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + ("0" if success else "2"))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
