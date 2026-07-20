#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def git_bytes(root: Path, revision: str, repo_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "show", f"{revision}:{repo_path}"],
        cwd=root,
        capture_output=True,
        timeout=45,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def is_git_tracked(root: Path, repo_path: str) -> bool:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "ls-files", "--error-unmatch", "--", repo_path],
        cwd=root,
        capture_output=True,
        timeout=20,
        check=False,
    )
    return result.returncode == 0


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


def prior_gate(status: dict[str, Any], expected: int) -> bool:
    required = {
        "official_stage": "R7.A3E5",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": expected,
        "registry_entry_count": expected,
        "unique_strategy_id_count": expected,
        "source_sha_match_count": expected,
        "callable_resolved_count": expected,
        "config_resolved_count": expected,
        "adapter_resolved_count": expected,
        "adapter_read_only_count": expected,
        "route_blocked_count": expected,
        "execution_blocked_count": expected,
        "fail_closed_count": expected,
        "hold_decision_count": expected,
        "binding_artifact_reference_count": 0,
        "duplicate_binding_count": 0,
        "strategy_module_import_count": 0,
        "target_git_source_parity_count": expected,
        "target_git_registry_parity_count": 1,
        "target_git_config_parity_count": 1,
        "adapter_target_git_parity_count": 1,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "active_entry_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "next_stage": "R7.A4_SIMULATION_REPLAY_INPUT_FREEZE",
    }
    return all(status.get(key) == value for key, value in required.items())


def text_sample(path: Path, max_bytes: int = 262144) -> str:
    try:
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="ignore").lower()
    except Exception:
        return ""


def category_for(
    repo_path: str,
    path: Path,
    category_terms: dict[str, list[str]],
    data_extensions: set[str],
) -> set[str]:
    lower_path = repo_path.lower()
    name = path.name.lower()
    excluded_name_terms = {
        "bootstrap", "verify", "verification", "audit", "reaudit", "diagnose",
        "contract", "proof", "status", "test_", "_test", "handoff",
    }
    if any(term in name for term in excluded_name_terms):
        return set()

    sample = ""
    categories: set[str] = set()
    for category, terms in category_terms.items():
        path_hit = any(term in lower_path for term in terms)
        if category == "market_data":
            if path_hit and path.suffix.lower() in data_extensions:
                categories.add(category)
            continue
        if path_hit:
            if category == "replay_harness":
                if path.suffix.lower() not in {".py", ".sh", ".json", ".yaml", ".yml"}:
                    continue
                sample = sample or text_sample(path)
                if any(token in sample for token in ("__main__", "def run", "def replay", "def simulate", "class ")):
                    categories.add(category)
            else:
                categories.add(category)

    if path.suffix.lower() in {".py", ".sh", ".json", ".yaml", ".yml"}:
        sample = sample or text_sample(path)
        if "execution_cost" not in categories and any(
            token in sample for token in ("slippage", "commission", "maker_fee", "taker_fee", "latency_ms", "funding_8h")
        ):
            categories.add("execution_cost")
        if "regime_context" not in categories and any(
            token in sample for token in ("market_regime", "regime_label", "market_quality", "volatility_regime", "liquidity_regime")
        ):
            categories.add("regime_context")
    return categories


def build_entry(root: Path, repo_path: str, category: str, target_sha: str) -> dict[str, Any]:
    path = root / repo_path
    digest = sha256_file(path)
    target = git_bytes(root, target_sha, repo_path)
    return {
        "category": category,
        "path": repo_path,
        "sha256": digest,
        "size_bytes": path.stat().st_size,
        "git_tracked": is_git_tracked(root, repo_path),
        "target_git_parity": bool(target is not None and digest == sha256_bytes(target)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    registry_repo = safe_repo_path(str(contract["registry_path"]))
    config_repo = safe_repo_path(str(contract["canonical_config_path"]))
    adapter_repo = safe_repo_path(str(contract["adapter_path"]))
    registry_path = root / registry_repo
    config_path = root / config_repo
    adapter_path = root / adapter_repo
    prior_status = load_json(root / str(contract["prior_status_path"]))
    registry = load_json(registry_path)
    blockers: list[str] = []

    if not prior_gate(prior_status, expected):
        blockers.append("PRIOR_A3E5_STATUS_INVALID")

    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    if len(entries) != expected:
        blockers.append(f"REGISTRY_COUNT_INVALID:{len(entries)}")

    canonical_repo_paths = [registry_repo, config_repo, adapter_repo]
    active_entry_count = 0
    for row in entries:
        active_entry_count += int(row.get("active_allowed") is True)
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        try:
            canonical_repo_paths.append(safe_repo_path(str(engine.get("implementation_path") or "")))
        except ValueError as exc:
            blockers.append(str(exc))

    canonical_repo_paths = sorted(dict.fromkeys(canonical_repo_paths))
    canonical_paths = [root / repo_path for repo_path in canonical_repo_paths]
    protected_paths = [Path(str(path)) for path in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)

    canonical_inputs: list[dict[str, Any]] = []
    canonical_git_parity_count = 0
    for repo_path, path in zip(canonical_repo_paths, canonical_paths):
        digest = sha256_file(path)
        target = git_bytes(root, args.target_sha, repo_path)
        parity = bool(target is not None and digest is not None and digest == sha256_bytes(target))
        canonical_git_parity_count += int(parity)
        canonical_inputs.append({
            "category": "canonical",
            "path": repo_path,
            "sha256": digest,
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "git_tracked": is_git_tracked(root, repo_path),
            "target_git_parity": parity,
        })
        if digest is None:
            blockers.append(f"CANONICAL_FILE_INVALID:{repo_path}")

    scan_extensions = {str(item).lower() for item in contract.get("scan_extensions", [])}
    excluded_parts = {str(item).lower() for item in contract.get("excluded_parts", [])}
    category_terms = {
        str(category): [str(term).lower() for term in terms]
        for category, terms in contract.get("category_path_terms", {}).items()
        if isinstance(terms, list)
    }
    max_bytes = int(contract.get("max_scan_file_bytes", 16777216))
    data_extensions = {".csv", ".json", ".jsonl", ".parquet", ".feather", ".arrow", ".npz"}
    category_entries: dict[str, list[dict[str, Any]]] = {name: [] for name in contract.get("required_categories", [])}
    canonical_set = set(canonical_repo_paths)

    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            repo_path = path.relative_to(root).as_posix()
        except ValueError:
            continue
        parts = {part.lower() for part in PurePosixPath(repo_path).parts}
        if parts & excluded_parts or repo_path in canonical_set:
            continue
        if path.suffix.lower() not in scan_extensions:
            continue
        try:
            if path.stat().st_size <= 0 or path.stat().st_size > max_bytes:
                continue
        except OSError:
            continue
        for category in sorted(category_for(repo_path, path, category_terms, data_extensions)):
            if category in category_entries:
                category_entries[category].append(build_entry(root, repo_path, category, args.target_sha))

    for category in category_entries:
        dedup = {entry["path"]: entry for entry in category_entries[category]}
        category_entries[category] = [dedup[key] for key in sorted(dedup)]

    required_categories = [str(item) for item in contract.get("required_categories", [])]
    missing_categories = [category for category in required_categories if not category_entries.get(category)]
    for category in missing_categories:
        blockers.append(f"INPUT_CATEGORY_MISSING:{category}")

    after = snapshot(canonical_paths + protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    canonical_set_abs = {str(path) for path in canonical_paths}
    protected_set_abs = {str(path) for path in protected_paths}
    canonical_mutation_count = sum(1 for path in mutation_paths if path in canonical_set_abs)
    protected_change_count = sum(1 for path in mutation_paths if path in protected_set_abs)
    if mutation_paths:
        blockers.append("READ_ONLY_MUTATION_DETECTED")

    all_inputs = canonical_inputs + [
        entry
        for category in required_categories
        for entry in category_entries.get(category, [])
    ]
    fingerprint_payload = {
        "target_commit": args.target_sha,
        "inputs": [
            {key: entry.get(key) for key in ("category", "path", "sha256", "size_bytes", "git_tracked", "target_git_parity")}
            for entry in sorted(all_inputs, key=lambda item: (str(item.get("category")), str(item.get("path"))))
        ],
    }
    input_set_id = sha256_bytes(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode())
    category_counts = {category: len(category_entries.get(category, [])) for category in required_categories}
    coverage_count = sum(1 for category in required_categories if category_counts[category] > 0)
    untracked_input_count = sum(1 for entry in all_inputs if not entry.get("git_tracked"))

    expected_canonical_count = expected + 3
    all_blockers = list(dict.fromkeys(blockers))
    success = bool(
        not all_blockers
        and len(canonical_inputs) == expected_canonical_count
        and canonical_git_parity_count == expected_canonical_count
        and coverage_count == len(required_categories)
        and active_entry_count == 0
        and canonical_mutation_count == 0
        and protected_change_count == 0
    )
    state = "PASS" if success else "HOLD"
    next_stage = str(contract["next_stage_pass"] if success else contract["next_stage_fail"])

    manifest = {
        "schema": "r7a4_frozen_input_manifest_v1",
        "official_stage": "R7.A4",
        "state": state,
        "target_commit": args.target_sha,
        "input_set_id": input_set_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "canonical_inputs": canonical_inputs,
        "category_inputs": category_entries,
        "category_counts": category_counts,
        "missing_categories": missing_categories,
        "execution_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
    }
    proof = {
        "schema": "r7a4_simulation_replay_input_freeze_proof_v1",
        "official_stage": "R7.A4",
        "state": state,
        "target_commit": args.target_sha,
        "input_set_id": input_set_id,
        "mutation_paths": mutation_paths,
        "blockers": all_blockers,
    }
    status = {
        "official_stage": "R7.A4",
        "state": state,
        "blocker_count": len(all_blockers),
        "blockers": all_blockers,
        "strategy_count": expected,
        "canonical_input_count": len(canonical_inputs),
        "canonical_git_parity_count": canonical_git_parity_count,
        "replay_harness_count": category_counts.get("replay_harness", 0),
        "market_data_input_count": category_counts.get("market_data", 0),
        "execution_cost_input_count": category_counts.get("execution_cost", 0),
        "regime_context_input_count": category_counts.get("regime_context", 0),
        "required_category_coverage_count": coverage_count,
        "frozen_input_count": len(all_inputs),
        "untracked_input_count": untracked_input_count,
        "input_set_id": input_set_id,
        "active_entry_count": active_entry_count,
        "simulation_replay_execution_count": 0,
        "canonical_mutation_count": canonical_mutation_count,
        "protected_change_count": protected_change_count,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "next_stage": next_stage,
        "manifest_path": str(root / str(contract["manifest_path"])),
        "proof_path": str(root / str(contract["proof_path"])),
    }

    atomic_json(root / str(contract["manifest_path"]), manifest)
    atomic_json(root / str(contract["proof_path"]), proof)
    atomic_json(root / str(contract["status_path"]), status)

    for key in (
        "state", "blocker_count", "strategy_count", "canonical_input_count",
        "canonical_git_parity_count", "replay_harness_count", "market_data_input_count",
        "execution_cost_input_count", "regime_context_input_count",
        "required_category_coverage_count", "frozen_input_count", "untracked_input_count",
        "input_set_id", "active_entry_count", "simulation_replay_execution_count",
        "canonical_mutation_count", "protected_change_count", "router_mutation_count",
        "service_mutation_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("BLOCKERS=" + json.dumps(all_blockers, ensure_ascii=False))
    print("MANIFEST_JSON=" + status["manifest_path"])
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + ("0" if success else "2"))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
