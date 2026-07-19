#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

TEXT_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".toml", ".service", ".sh", ".md", ".txt", ".rst"}
PRODUCTION_PREFIXES = ("backend/", "tools/", "config/", "scripts/", "systemd/", "services/")
TEST_PREFIXES = ("tests/", "test/")
MAX_BYTES = 2_000_000

EVIDENCE_KEYWORDS = {
    "trigger": ("trigger", "setup", "entry_condition", "entry_signal", "signal"),
    "invalidation": ("invalidation", "invalidate", "stop_loss", "loss_cap"),
    "risk": ("risk", "position_size", "leverage", "loss_cap", "liquidation"),
    "cost": ("fee", "slippage", "funding", "cost_r", "commission"),
    "replay": ("replay", "simulation", "walk_forward", "point_in_time", "lookahead"),
}
RECEIPT_KEYS = ("strategy_id", "source_sha", "event_id", "feature_ts", "signal", "invalidation")


def run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
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


def prior_a2_valid(value: dict[str, Any]) -> bool:
    return (
        value.get("official_stage") == "R7.A2"
        and value.get("state") == "PASS"
        and int(value.get("blocker_count", -1)) == 0
        and int(value.get("axis_count", -1)) == 7
        and int(value.get("axis_contracts_frozen", -1)) == 7
        and int(value.get("protected_change_count", -1)) == 0
        and int(value.get("runtime_mutation_count", -1)) == 0
        and value.get("next_stage") == "R7.A3_STRATEGY25_S_GRADE"
    )


def list_tree(repo: Path, target_sha: str) -> tuple[str, dict[str, dict[str, Any]]]:
    resolved = run(["git", "-C", str(repo), "rev-parse", f"{target_sha}^{{commit}}"])
    if resolved.returncode != 0:
        raise RuntimeError("TARGET_SHA_NOT_RESOLVED")
    commit = resolved.stdout.strip()
    cp = run(["git", "-C", str(repo), "ls-tree", "-r", "--long", commit], timeout=180)
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


def git_text(repo: Path, commit: str, path: str, size: int = 0) -> str:
    if size > MAX_BYTES:
        return ""
    cp = run(["git", "-C", str(repo), "show", f"{commit}:{path}"])
    return cp.stdout if cp.returncode == 0 else ""


def recursive_lists(value: Any, path: str = "$") -> Iterable[tuple[str, list[Any]]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(child, list):
                yield child_path, child
            yield from recursive_lists(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from recursive_lists(child, f"{path}[{index}]")


def list_ids(value: list[Any]) -> list[str]:
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            for key in ("strategy_id", "id", "name"):
                raw = item.get(key)
                if isinstance(raw, str) and raw.strip():
                    result.append(raw.strip())
                    break
    return result


def discover_manifest(
    repo: Path,
    commit: str,
    tree: dict[str, dict[str, Any]],
    expected_count: int,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for path, meta in tree.items():
        low = path.lower()
        if not low.endswith(".json"):
            continue
        if not any(token in low for token in ("strategy", "exact25", "matrix", "registry", "universe", "manifest")):
            continue
        text = git_text(repo, commit, path, int(meta.get("size", 0)))
        if not text:
            continue
        try:
            obj = json.loads(text)
        except Exception:
            continue
        for json_path, value in recursive_lists(obj):
            ids = sorted(set(list_ids(value)))
            if len(ids) < 5:
                continue
            descriptor = f"{path} {json_path}".lower()
            score = 0
            if len(ids) == expected_count:
                score += 100
            score -= abs(len(ids) - expected_count) * 4
            if "strategy" in descriptor:
                score += 25
            if "exact25" in descriptor or "exact_25" in descriptor:
                score += 35
            if "canonical" in descriptor or "registry" in descriptor or "universe" in descriptor:
                score += 15
            candidates.append({
                "path": path,
                "json_path": json_path,
                "count": len(ids),
                "ids": ids,
                "score": score,
                "blob_sha": meta.get("blob_sha"),
            })
    candidates.sort(key=lambda row: (row["score"], row["path"]), reverse=True)
    exact = [row for row in candidates if row["count"] == expected_count]
    selected = exact[0] if exact else None
    ambiguous = bool(
        len(exact) > 1
        and exact[0]["score"] == exact[1]["score"]
        and exact[0]["ids"] != exact[1]["ids"]
    )
    return {"selected": selected, "ambiguous": ambiguous, "candidates": candidates[:30]}


def path_kind(path: str) -> str:
    low = path.lower()
    if low.startswith(TEST_PREFIXES) or "/tests/" in low or low.endswith("_test.py"):
        return "test"
    if "/contracts/" in low or low.startswith("docs/") or Path(low).suffix in {".md", ".txt", ".rst"}:
        return "contract"
    if low.startswith(PRODUCTION_PREFIXES):
        return "production"
    return "other"


def grep_paths(repo: Path, commit: str, identifier: str) -> list[str]:
    scopes = ["backend", "tools", "config", "scripts", "systemd", "services", "tests", "docs"]
    cp = run(["git", "-C", str(repo), "grep", "-l", "-I", "-F", identifier, commit, "--", *scopes], timeout=120)
    if cp.returncode not in (0, 1):
        return []
    prefix = f"{commit}:"
    paths = []
    for line in cp.stdout.splitlines():
        path = line[len(prefix):] if line.startswith(prefix) else line
        if path:
            paths.append(path)
    return sorted(set(paths))


def grade_strategy(
    strategy_id: str,
    references: list[str],
    texts: dict[str, str],
    tree: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    production = [path for path in references if path_kind(path) == "production"]
    tests = [path for path in references if path_kind(path) == "test"]
    contracts = [path for path in references if path_kind(path) == "contract"]
    combined = "\n".join(texts.get(path, "") for path in references).lower()
    evidence = {
        key: any(token in combined for token in tokens)
        for key, tokens in EVIDENCE_KEYWORDS.items()
    }
    evidence["receipt"] = all(key in combined for key in RECEIPT_KEYS)
    source_shas = {
        path: tree[path]["blob_sha"]
        for path in production
        if path in tree and tree[path].get("blob_sha")
    }
    static_s_ready = bool(
        production
        and tests
        and source_shas
        and all(evidence.values())
    )
    if static_s_ready:
        grade = "S_STATIC_READY"
    elif production and tests and evidence["trigger"] and evidence["invalidation"] and evidence["risk"]:
        grade = "A"
    elif production:
        grade = "B"
    elif contracts:
        grade = "C"
    else:
        grade = "D"
    missing = []
    if not production:
        missing.append("implementation")
    if not tests:
        missing.append("tests")
    if not source_shas:
        missing.append("source_sha")
    missing.extend(key for key, present in evidence.items() if not present)
    return {
        "strategy_id": strategy_id,
        "grade": grade,
        "static_s_ready": static_s_ready,
        "implementation_refs": production,
        "test_refs": tests,
        "contract_refs": contracts,
        "source_shas": source_shas,
        "evidence": evidence,
        "missing": sorted(set(missing)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    status_path = root / str(contract.get("status_path", "runtime/r7a3_strategy25_s_grade_audit/status_latest.json"))
    prior_path = root / str(contract.get("prior_a2_status_path", "runtime/r7a2_seven_axis_s_grade_contract_freeze/status_latest.json"))
    expected_count = int(contract.get("expected_strategy_count", 25))
    protected_paths = [str(path) for path in contract.get("protected_paths", [])]
    before = fingerprints(protected_paths)
    blockers: list[str] = []

    prior = load_json(prior_path)
    if not prior_a2_valid(prior):
        blockers.append("PRIOR_A2_INVALID")

    try:
        commit, tree = list_tree(root, args.target_sha)
    except Exception as exc:
        commit, tree = "", {}
        blockers.append(str(exc))

    manifest = discover_manifest(root, commit, tree, expected_count) if commit else {"selected": None, "ambiguous": False, "candidates": []}
    selected = manifest.get("selected")
    if not selected:
        blockers.append("CANONICAL_STRATEGY25_MANIFEST_NOT_FOUND")
    elif int(selected.get("count", -1)) != expected_count:
        blockers.append("STRATEGY_COUNT_NOT_25")
    if manifest.get("ambiguous"):
        blockers.append("CONFLICTING_STRATEGY25_MANIFESTS")

    per_strategy: list[dict[str, Any]] = []
    if selected:
        text_cache: dict[str, str] = {}
        for strategy_id in selected["ids"]:
            refs = grep_paths(root, commit, strategy_id)
            for path in refs:
                if path not in text_cache and path in tree and Path(path).suffix.lower() in TEXT_EXTENSIONS:
                    text_cache[path] = git_text(root, commit, path, int(tree[path].get("size", 0)))
            per_strategy.append(grade_strategy(strategy_id, refs, text_cache, tree))

    after = fingerprints(protected_paths)
    protected_changes = [
        {"path": path, "before": before.get(path), "after": after.get(path)}
        for path in protected_paths
        if before.get(path) != after.get(path)
    ]
    if protected_changes:
        blockers.append("PROTECTED_PATH_CHANGED")

    counts = Counter(row["grade"] for row in per_strategy)
    static_ready_count = sum(1 for row in per_strategy if row["static_s_ready"])
    implementation_count = sum(1 for row in per_strategy if row["implementation_refs"])
    tested_count = sum(1 for row in per_strategy if row["test_refs"])
    state = "PASS" if not blockers else "HOLD"
    if state == "PASS":
        next_stage = (
            "R7.A4_TRADE_LIFECYCLE_S_GRADE"
            if static_ready_count == expected_count
            else "R7.A3B_STRATEGY25_STATIC_GAP_CLOSURE"
        )
    else:
        next_stage = "R7.A3_DIAGNOSE"

    payload = {
        "schema": "r7a3_strategy25_s_grade_audit_status_v1",
        "official_stage": "R7.A3",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "read_only": True,
        "target_commit": commit,
        "prior_a2_valid": prior_a2_valid(prior),
        "expected_strategy_count": expected_count,
        "manifest": manifest,
        "strategy_count": len(per_strategy),
        "implementation_count": implementation_count,
        "tested_count": tested_count,
        "static_s_ready_count": static_ready_count,
        "performance_s_promoted_count": 0,
        "grade_counts": dict(counts),
        "strategies": per_strategy,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "runtime_mutation_count": 0,
        "selection_funnel": contract.get("selection_funnel", {}),
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)

    print("R7A3_STRATEGY25_S_GRADE_AUDIT_COMPLETE")
    for key, value in (
        ("STATE", state),
        ("BLOCKER_COUNT", len(blockers)),
        ("BLOCKERS", json.dumps(blockers, ensure_ascii=False)),
        ("PRIOR_A2_VALID", str(prior_a2_valid(prior)).lower()),
        ("STRATEGY_COUNT", len(per_strategy)),
        ("IMPLEMENTATION_COUNT", implementation_count),
        ("TESTED_COUNT", tested_count),
        ("STATIC_S_READY_COUNT", static_ready_count),
        ("PERFORMANCE_S_PROMOTED_COUNT", 0),
        ("GRADE_COUNTS", json.dumps(dict(counts), ensure_ascii=False, sort_keys=True)),
        ("PROTECTED_CHANGE_COUNT", len(protected_changes)),
        ("RUNTIME_MUTATION_COUNT", 0),
        ("NEXT_STAGE", next_stage),
        ("EVIDENCE_JSON", str(status_path)),
        ("RC", 0 if state == "PASS" else 2),
    ):
        print(f"{key}={value}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
