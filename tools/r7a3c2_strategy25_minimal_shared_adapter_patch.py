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
from typing import Any, Iterable

MAX_BYTES = 2_000_000
PYTHON_PREFIX_SCORE = {
    "backend/": 60,
    "services/": 50,
    "scripts/": 40,
    "tools/": 20,
    "config/": 10,
}
GENERIC_ENTRYPOINTS = (
    "evaluate",
    "generate_signal",
    "signal",
    "run",
    "apply",
    "decide",
    "dispatch",
    "execute",
    "strategy",
)


def run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprints(paths: Iterable[str]) -> dict[str, str | None]:
    return {path: sha256_file(Path(path)) for path in paths}


def list_tree(repo: Path, target_sha: str) -> tuple[str, dict[str, dict[str, Any]]]:
    resolved = run(["git", "-C", str(repo), "rev-parse", f"{target_sha}^{{commit}}"])
    if resolved.returncode != 0:
        raise RuntimeError("TARGET_SHA_NOT_RESOLVED")
    commit = resolved.stdout.strip()
    cp = run(["git", "-C", str(repo), "ls-tree", "-r", "--long", commit])
    if cp.returncode != 0:
        raise RuntimeError("GIT_TREE_LIST_FAILED")
    result: dict[str, dict[str, Any]] = {}
    for line in cp.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        fields = meta.split()
        if len(fields) < 4:
            continue
        try:
            size = int(fields[3])
        except ValueError:
            size = 0
        result[path] = {"blob_sha": fields[2], "size": size}
    return commit, result


def git_text(repo: Path, commit: str, path: str, tree: dict[str, dict[str, Any]]) -> str:
    meta = tree.get(path, {})
    if int(meta.get("size", 0) or 0) > MAX_BYTES:
        return ""
    cp = run(["git", "-C", str(repo), "show", f"{commit}:{path}"])
    return cp.stdout if cp.returncode == 0 else ""


def prior_a3c1_valid(value: dict[str, Any], expected_count: int) -> bool:
    patch = value.get("patch_plan") if isinstance(value.get("patch_plan"), dict) else {}
    return (
        value.get("official_stage") == "R7.A3C1"
        and value.get("state") == "PASS"
        and int(value.get("blocker_count", -1)) == 0
        and int(value.get("strategy_count", -1)) == expected_count
        and int(value.get("proven_shared_caller_count", -1)) == 0
        and int(value.get("parameterized_test_candidate_count", -1)) == 0
        and patch.get("classification") == "SHARED_ADAPTER_AND_TEST_CLOSURE_REQUIRED"
        and int(patch.get("missing_test_count", -1)) > 0
        and value.get("next_stage")
        == "R7.A3C2_STRATEGY25_MINIMAL_SHARED_ADAPTER_AND_TEST_PATCH"
    )


def normalize_rows(a3: dict[str, Any], expected_count: int) -> tuple[list[dict[str, Any]], list[str]]:
    raw_rows = a3.get("strategies")
    if not isinstance(raw_rows, list):
        return [], ["A3_STRATEGIES_NOT_LIST"]
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            blockers.append("A3_STRATEGY_ROW_NOT_OBJECT")
            continue
        sid = str(raw.get("strategy_id", "")).strip()
        if not sid or sid in seen:
            blockers.append(f"A3_STRATEGY_ID_INVALID:{sid}")
            continue
        seen.add(sid)
        refs = sorted({str(x) for x in raw.get("implementation_refs", []) if str(x)})
        source_shas = raw.get("source_shas") if isinstance(raw.get("source_shas"), dict) else {}
        rows.append(
            {
                "strategy_id": sid,
                "implementation_refs": refs,
                "source_shas": {str(k): str(v) for k, v in source_shas.items()},
                "test_refs": sorted({str(x) for x in raw.get("test_refs", []) if str(x)}),
            }
        )
    rows.sort(key=lambda row: row["strategy_id"])
    if len(rows) != expected_count:
        blockers.append(f"STRATEGY_COUNT_{len(rows)}_NE_{expected_count}")
    return rows, blockers


def _normalized_tokens(strategy_id: str) -> list[str]:
    return [part for part in re.split(r"[^a-z0-9]+", strategy_id.lower()) if len(part) >= 3]


def _python_symbols(text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except Exception:
        return []
    symbols: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                symbols.append({"name": node.name, "kind": "function", "line": node.lineno})
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = [
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not child.name.startswith("_")
            ]
            symbols.append(
                {
                    "name": node.name,
                    "kind": "class",
                    "line": node.lineno,
                    "methods": methods,
                }
            )
    return symbols


def _path_score(path: str) -> int:
    low = path.lower()
    if any(token in low for token in ("/contracts/", "r7a3", "audit", "gap_closure", "actual_caller_proof")):
        return -500
    score = 0
    for prefix, value in PYTHON_PREFIX_SCORE.items():
        if low.startswith(prefix):
            score = max(score, value)
    if "strategy" in low:
        score += 20
    if "exact25" in low or "exact_25" in low:
        score += 15
    return score


def resolve_entrypoint(
    repo: Path,
    commit: str,
    tree: dict[str, dict[str, Any]],
    row: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    sid = row["strategy_id"]
    tokens = _normalized_tokens(sid)
    candidates: list[dict[str, Any]] = []
    for path in row["implementation_refs"]:
        if path not in tree:
            continue
        source_sha = row["source_shas"].get(path) or tree[path].get("blob_sha")
        if not source_sha:
            continue
        low = path.lower()
        if low.endswith(".py"):
            text = git_text(repo, commit, path, tree)
            for symbol in _python_symbols(text):
                name_low = symbol["name"].lower()
                token_hits = sum(token in name_low or token in low for token in tokens)
                generic_hits = sum(marker in name_low for marker in GENERIC_ENTRYPOINTS)
                method_hits = sum(
                    1
                    for method in symbol.get("methods", [])
                    if any(marker in method.lower() for marker in GENERIC_ENTRYPOINTS)
                )
                score = _path_score(path) + token_hits * 25 + generic_hits * 15 + method_hits * 10
                candidates.append(
                    {
                        "strategy_id": sid,
                        "path": path,
                        "symbol": symbol["name"],
                        "kind": symbol["kind"],
                        "line": symbol["line"],
                        "source_sha": source_sha,
                        "score": score,
                    }
                )
        elif low.endswith(".sh"):
            candidates.append(
                {
                    "strategy_id": sid,
                    "path": path,
                    "symbol": "__script__",
                    "kind": "script",
                    "line": 1,
                    "source_sha": source_sha,
                    "score": _path_score(path),
                }
            )
    candidates.sort(key=lambda item: (item["score"], item["path"], item["symbol"]), reverse=True)
    return (candidates[0] if candidates else None), candidates[:10]


def build_binding_registry(
    repo: Path,
    target_sha: str,
    a3: dict[str, Any],
    expected_count: int = 25,
) -> tuple[dict[str, Any], list[str]]:
    commit, tree = list_tree(repo, target_sha)
    rows, blockers = normalize_rows(a3, expected_count)
    bindings: list[dict[str, Any]] = []
    diagnostics: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        selected, candidates = resolve_entrypoint(repo, commit, tree, row)
        diagnostics[row["strategy_id"]] = candidates
        if selected is None:
            blockers.append(f"ENTRYPOINT_NOT_RESOLVED:{row['strategy_id']}")
            continue
        bindings.append(
            {
                "strategy_id": row["strategy_id"],
                "source_sha": selected["source_sha"],
                "entrypoint_ref": f"{selected['path']}:{selected['symbol']}",
                "entrypoint_kind": selected["kind"],
                "entrypoint_line": selected["line"],
                "existing_test_refs": row["test_refs"],
                "coverage_source": "r7a3_audit_implementation_refs",
            }
        )
    bindings.sort(key=lambda item: item["strategy_id"])
    if len(bindings) != expected_count:
        blockers.append(f"BINDING_COUNT_{len(bindings)}_NE_{expected_count}")
    if len({item["strategy_id"] for item in bindings}) != len(bindings):
        blockers.append("DUPLICATE_BINDING_STRATEGY_ID")
    registry = {
        "schema": "r7a3c2_strategy25_binding_registry_v1",
        "target_commit": commit,
        "expected_strategy_count": expected_count,
        "binding_count": len(bindings),
        "receipt_keys": [
            "strategy_id",
            "source_sha",
            "event_id",
            "feature_ts",
            "signal",
            "invalidation",
        ],
        "replay_guards": ["point_in_time", "lookahead_zero", "cost_model_bound"],
        "order_authority": "none",
        "ledger_write_authority": "none",
        "runtime_activation_default": False,
        "bindings": bindings,
        "diagnostics": diagnostics,
    }
    return registry, sorted(set(blockers))


def adapter_contract_valid(text: str) -> bool:
    required = (
        "CanonicalStrategy25Adapter",
        "StrategyBinding",
        "ReplayContext",
        "StrategyReceipt",
        "point_in_time",
        "lookahead_zero",
        "cost_model_bound",
        'order_authority = "none"',
        'ledger_write_authority = "none"',
    )
    return all(token in text for token in required)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected_count = int(contract.get("expected_strategy_count", 25))
    a3 = load_json(root / str(contract.get("prior_a3_status_path")))
    a3c1 = load_json(root / str(contract.get("prior_a3c1_status_path")))
    status_path = root / str(contract.get("status_path"))
    registry_path = root / str(contract.get("binding_registry_path"))
    protected_paths = [str(x) for x in contract.get("protected_paths", [])]
    before = fingerprints(protected_paths)
    blockers: list[str] = []

    if not prior_a3c1_valid(a3c1, expected_count):
        blockers.append("PRIOR_A3C1_INVALID")

    try:
        commit, tree = list_tree(root, args.target_sha)
    except Exception as exc:
        commit, tree = "", {}
        blockers.append(str(exc))

    adapter_path = str(contract.get("adapter_path"))
    adapter_text = git_text(root, commit, adapter_path, tree) if commit and adapter_path in tree else ""
    if not adapter_text:
        blockers.append("SHARED_ADAPTER_NOT_FOUND")
    elif not adapter_contract_valid(adapter_text):
        blockers.append("SHARED_ADAPTER_CONTRACT_INVALID")

    if commit:
        try:
            registry, registry_blockers = build_binding_registry(root, commit, a3, expected_count)
            blockers.extend(registry_blockers)
        except Exception as exc:
            registry = {}
            blockers.append(f"BINDING_REGISTRY_BUILD_FAILED:{type(exc).__name__}")
    else:
        registry = {}

    if registry:
        atomic_json(registry_path, registry)

    after = fingerprints(protected_paths)
    protected_changes = [
        {"path": path, "before": before.get(path), "after": after.get(path)}
        for path in protected_paths
        if before.get(path) != after.get(path)
    ]
    if protected_changes:
        blockers.append("PROTECTED_PATH_CHANGED")

    binding_count = int(registry.get("binding_count", 0)) if registry else 0
    source_sha_count = sum(1 for row in registry.get("bindings", []) if row.get("source_sha")) if registry else 0
    entrypoint_count = sum(1 for row in registry.get("bindings", []) if row.get("entrypoint_ref")) if registry else 0
    state = "PASS" if not blockers else "HOLD"
    next_stage = (
        "R7.A3D_STRATEGY25_SHARED_EVIDENCE_REAUDIT"
        if state == "PASS"
        else "R7.A3C2_DIAGNOSE"
    )
    payload = {
        "schema": "r7a3c2_strategy25_minimal_shared_adapter_status_v1",
        "official_stage": "R7.A3C2",
        "state": state,
        "blocker_count": len(set(blockers)),
        "blockers": sorted(set(blockers)),
        "read_only_runtime": True,
        "target_commit": commit,
        "prior_a3c1_valid": prior_a3c1_valid(a3c1, expected_count),
        "strategy_count": expected_count,
        "binding_count": binding_count,
        "source_sha_count": source_sha_count,
        "entrypoint_count": entrypoint_count,
        "shared_adapter_contract_valid": bool(adapter_text and adapter_contract_valid(adapter_text)),
        "parameterized_static_entrypoint_coverage_count": binding_count,
        "performance_s_promoted_count": 0,
        "runtime_activation_count": 0,
        "order_authority": "none",
        "ledger_write_authority": "none",
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "runtime_mutation_count": 0,
        "binding_registry_path": str(registry_path),
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)

    print("R7A3C2_STRATEGY25_MINIMAL_SHARED_ADAPTER_PATCH_COMPLETE")
    for key, value in (
        ("STATE", state),
        ("BLOCKER_COUNT", len(set(blockers))),
        ("BLOCKERS", json.dumps(sorted(set(blockers)), ensure_ascii=False)),
        ("PRIOR_A3C1_VALID", str(prior_a3c1_valid(a3c1, expected_count)).lower()),
        ("STRATEGY_COUNT", expected_count),
        ("BINDING_COUNT", binding_count),
        ("SOURCE_SHA_COUNT", source_sha_count),
        ("ENTRYPOINT_COUNT", entrypoint_count),
        ("SHARED_ADAPTER_CONTRACT_VALID", str(bool(adapter_text and adapter_contract_valid(adapter_text))).lower()),
        ("PARAMETERIZED_STATIC_ENTRYPOINT_COVERAGE_COUNT", binding_count),
        ("PERFORMANCE_S_PROMOTED_COUNT", 0),
        ("RUNTIME_ACTIVATION_COUNT", 0),
        ("PROTECTED_CHANGE_COUNT", len(protected_changes)),
        ("RUNTIME_MUTATION_COUNT", 0),
        ("NEXT_STAGE", next_stage),
        ("EVIDENCE_JSON", str(status_path)),
        ("BINDING_REGISTRY_JSON", str(registry_path)),
        ("RC", 0 if state == "PASS" else 2),
    ):
        print(f"{key}={value}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
