#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes()) if path.is_file() else None
    except OSError:
        return None


def stable_sha(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def local_bundle(source_paths: list[str]) -> tuple[str | None, dict[str, str | None]]:
    rows: list[dict[str, str]] = []
    hashes: dict[str, str | None] = {}
    for source_path in sorted(source_paths):
        if source_path.startswith("external:"):
            hashes[source_path] = None
            continue
        digest = file_sha(ROOT / source_path)
        hashes[source_path] = digest
        if digest is not None:
            rows.append({"path": source_path, "sha256": digest})
    internal = [x for x in source_paths if not x.startswith("external:")]
    if not internal or len(rows) != len(source_paths):
        return None, hashes
    return stable_sha(rows), hashes


def reconcile(pin: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    runtime_modules = {str(x.get("module_id")): x for x in runtime.get("module_source_rows", [])}
    modules: list[dict[str, Any]] = []
    runtime_drift_modules = 0
    pin_stale_modules = 0
    file_drift_count = 0
    runtime_missing_count = 0

    for module in pin.get("modules", []):
        module_id = str(module.get("module_id"))
        expected = str(module.get("source_bundle_sha256") or "") or None
        source_paths = [str(x) for x in module.get("source_paths", [])]
        repo_bundle, repo_hashes = local_bundle(source_paths)
        remote = runtime_modules.get(module_id, {})
        runtime_bundle = remote.get("computed_source_bundle_sha256")
        runtime_match = bool(remote.get("source_bundle_match"))
        repo_match = (repo_bundle == expected) if repo_bundle is not None and expected else None

        drift_paths: list[dict[str, Any]] = []
        remote_file_map = {str(x.get("source_path")): x for x in remote.get("files", [])}
        for source_path in source_paths:
            if source_path.startswith("external:"):
                continue
            repo_sha = repo_hashes.get(source_path)
            rr = remote_file_map.get(source_path, {})
            runtime_sha = rr.get("runtime_sha256", rr.get("sha256"))
            runtime_exists = bool(rr.get("exists"))
            if not runtime_exists and repo_sha is not None:
                runtime_missing_count += 1
                drift_paths.append({"path": source_path, "kind": "RUNTIME_MISSING_REPO_PRESENT", "repo_sha256": repo_sha, "runtime_sha256": None})
            elif repo_sha is not None and runtime_sha is not None and repo_sha != runtime_sha:
                file_drift_count += 1
                drift_paths.append({"path": source_path, "kind": "RUNTIME_HASH_DIFFERS_FROM_REPO", "repo_sha256": repo_sha, "runtime_sha256": runtime_sha})

        if runtime_match:
            diagnosis = "MATCH_PIN"
        elif repo_match is True:
            diagnosis = "RUNTIME_DRIFT_FROM_CURRENT_REPO"
            runtime_drift_modules += 1
        elif repo_match is False:
            diagnosis = "PIN_STALE_VS_CURRENT_REPO"
            pin_stale_modules += 1
        elif source_paths and all(x.startswith("external:") for x in source_paths):
            diagnosis = "EXTERNAL_RUNTIME_PIN_MISMATCH" if not runtime_match else "MATCH_PIN"
        else:
            diagnosis = "UNCLASSIFIED_PIN_OR_RUNTIME_MISMATCH"

        modules.append({
            "module_id": module_id,
            "diagnosis": diagnosis,
            "expected_pin_bundle_sha256": expected,
            "repo_bundle_sha256": repo_bundle,
            "repo_matches_pin": repo_match,
            "runtime_bundle_sha256": runtime_bundle,
            "runtime_matches_pin": runtime_match,
            "drift_paths": drift_paths,
        })

    legacy_runtime = {str(x.get("strategy")): x for x in runtime.get("legacy25_rows", [])}
    legacy_drift: list[dict[str, Any]] = []
    for name in pin_legacy_names(runtime):
        rel = f"backend/strategies/{name}.py"
        repo_sha = file_sha(ROOT / rel)
        rr = legacy_runtime.get(name, {})
        runtime_sha = rr.get("runtime_sha256", rr.get("sha256"))
        if repo_sha is not None and runtime_sha is not None and repo_sha != runtime_sha:
            legacy_drift.append({"strategy": name, "path": rel, "repo_sha256": repo_sha, "runtime_sha256": runtime_sha})

    state = "PASS_RUNTIME_SOURCE_RECONCILIATION" if runtime.get("state") == "PASS_G0_RUNTIME_CENSUS" and not runtime_drift_modules and not pin_stale_modules else "HOLD_RUNTIME_SOURCE_RECONCILIATION"
    return {
        "schema_version": "zel.g0.runtime_source_reconciliation.v1",
        "state": state,
        "runtime_state": runtime.get("state"),
        "runtime_git_head": runtime.get("runtime_git_head"),
        "runtime_git_branch": runtime.get("runtime_git_branch"),
        "runtime_tracked_dirty_line_count": runtime.get("tracked_dirty_line_count"),
        "runtime_drift_module_count": runtime_drift_modules,
        "pin_stale_module_count": pin_stale_modules,
        "runtime_file_hash_drift_count": file_drift_count,
        "runtime_missing_repo_present_count": runtime_missing_count,
        "legacy25_hash_drift_count": len(legacy_drift),
        "legacy25_hash_drift": legacy_drift,
        "modules": modules,
        "runtime_mutated": False,
        "destructive_cleanup_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def pin_legacy_names(runtime: dict[str, Any]) -> list[str]:
    return [str(x.get("strategy")) for x in runtime.get("legacy25_rows", []) if x.get("strategy")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", type=Path, required=True)
    ap.add_argument("--runtime", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    pin = json.loads(args.pin.read_text(encoding="utf-8"))
    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    result = reconcile(pin, runtime)
    result["receipt_sha256"] = stable_sha(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "runtime_drift_module_count": result["runtime_drift_module_count"],
        "pin_stale_module_count": result["pin_stale_module_count"],
        "runtime_file_hash_drift_count": result["runtime_file_hash_drift_count"],
        "runtime_missing_repo_present_count": result["runtime_missing_repo_present_count"],
        "legacy25_hash_drift_count": result["legacy25_hash_drift_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
