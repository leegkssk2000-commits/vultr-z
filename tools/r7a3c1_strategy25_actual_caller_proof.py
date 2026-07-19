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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

TEXT_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".toml", ".service", ".sh", ".md", ".txt", ".rst"}
PRODUCTION_PREFIXES = ("backend/", "tools/", "config/", "scripts/", "systemd/", "services/")
TEST_PREFIXES = ("tests/", "test/")
MAX_BYTES = 2_000_000

RECEIPT_MARKERS = ("strategy_receipt", "receipt", "event_id", "feature_ts", "source_sha", "invalidation")
REPLAY_MARKERS = ("replay", "simulation", "point_in_time", "lookahead", "completed_bar", "event_ts")
CALLER_MARKERS = ("strategy", "signal", "evaluate", "dispatch", "router", "orchestr", "producer")
DYNAMIC_TEST_MARKERS = ("pytest.mark.parametrize", "for strategy", "strategy_count", "manifest", "entrypoint", "implementation_refs")


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


def prior_a3b_valid(value: dict[str, Any], expected_count: int) -> bool:
    plan = value.get("plan") if isinstance(value.get("plan"), dict) else {}
    return (
        value.get("official_stage") == "R7.A3B"
        and value.get("state") == "PASS"
        and int(value.get("blocker_count", -1)) == 0
        and int(value.get("strategy_count", -1)) == expected_count
        and plan.get("closure_mode") == "MIXED"
        and int(plan.get("missing_test_count", -1)) > 0
        and {"receipt", "replay"}.issubset(set(plan.get("shared_gap_candidates", [])))
        and int(value.get("protected_change_count", -1)) == 0
        and int(value.get("runtime_mutation_count", -1)) == 0
        and value.get("next_stage") == "R7.A3C_STRATEGY25_MIXED_STATIC_CLOSURE"
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


def git_text(repo: Path, commit: str, path: str, tree: dict[str, dict[str, Any]]) -> str:
    meta = tree.get(path, {})
    if int(meta.get("size", 0) or 0) > MAX_BYTES:
        return ""
    cp = run(["git", "-C", str(repo), "show", f"{commit}:{path}"])
    return cp.stdout if cp.returncode == 0 else ""


def path_kind(path: str) -> str:
    low = path.lower()
    if low.startswith(TEST_PREFIXES) or "/tests/" in low or low.endswith("_test.py"):
        return "test"
    if "/contracts/" in low or low.startswith("docs/") or Path(low).suffix in {".md", ".txt", ".rst"}:
        return "contract"
    if low.startswith(PRODUCTION_PREFIXES):
        return "production"
    return "other"


def ast_shape(text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text)
    except Exception as exc:
        return {"parse_ok": False, "error": type(exc).__name__, "functions": [], "classes": [], "imports": []}
    functions = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return {
        "parse_ok": True,
        "functions": sorted(set(functions)),
        "classes": sorted(set(classes)),
        "imports": sorted(set(filter(None, imports))),
    }


def marker_score(text: str, markers: tuple[str, ...]) -> tuple[int, list[str]]:
    low = text.lower()
    found = sorted({marker for marker in markers if marker in low})
    return len(found), found


def normalize_rows(a3: dict[str, Any], expected_count: int) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    raw_rows = a3.get("strategies")
    if not isinstance(raw_rows, list):
        return [], ["A3_STRATEGIES_NOT_LIST"]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            blockers.append("A3_STRATEGY_ROW_NOT_OBJECT")
            continue
        sid = str(raw.get("strategy_id", "")).strip()
        if not sid:
            blockers.append("A3_STRATEGY_ID_MISSING")
            continue
        if sid in seen:
            blockers.append(f"A3_DUPLICATE_STRATEGY_ID:{sid}")
            continue
        seen.add(sid)
        rows.append({
            "strategy_id": sid,
            "implementation_refs": sorted({str(x) for x in raw.get("implementation_refs", []) if str(x)}),
            "test_refs": sorted({str(x) for x in raw.get("test_refs", []) if str(x)}),
            "missing": sorted({str(x) for x in raw.get("missing", []) if str(x)}),
            "source_shas": raw.get("source_shas", {}),
        })
    rows.sort(key=lambda row: row["strategy_id"])
    if len(rows) != expected_count:
        blockers.append(f"A3_STRATEGY_COUNT_{len(rows)}_NE_{expected_count}")
    return rows, blockers


def candidate_common_callers(
    repo: Path,
    commit: str,
    tree: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    coverage: Counter[str] = Counter()
    strategies_by_path: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for path in row["implementation_refs"]:
            if path_kind(path) != "production" or path not in tree:
                continue
            coverage[path] += 1
            strategies_by_path[path].append(row["strategy_id"])

    candidates: list[dict[str, Any]] = []
    for path, count in coverage.items():
        text = git_text(repo, commit, path, tree)
        if not text:
            continue
        receipt_score, receipt_found = marker_score(text, RECEIPT_MARKERS)
        replay_score, replay_found = marker_score(text, REPLAY_MARKERS)
        caller_score, caller_found = marker_score(text, CALLER_MARKERS)
        shape = ast_shape(text) if path.endswith(".py") else {"parse_ok": True, "functions": [], "classes": [], "imports": []}
        executable_surface = bool(shape.get("functions") or shape.get("classes")) if path.endswith(".py") else path.endswith((".sh", ".service"))
        score = count * 10 + receipt_score * 8 + replay_score * 8 + caller_score * 2 + int(executable_surface) * 10
        candidates.append({
            "path": path,
            "strategy_coverage_count": count,
            "strategy_ids": sorted(strategies_by_path[path]),
            "receipt_markers": receipt_found,
            "replay_markers": replay_found,
            "caller_markers": caller_found,
            "ast": shape,
            "executable_surface": executable_surface,
            "score": score,
            "actual_shared_caller_candidate": bool(
                count >= 20 and receipt_score >= 3 and replay_score >= 2 and caller_score >= 2 and executable_surface
            ),
        })
    candidates.sort(key=lambda row: (row["score"], row["strategy_coverage_count"], row["path"]), reverse=True)
    return candidates[:100]


def dynamic_test_candidates(
    repo: Path,
    commit: str,
    tree: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    test_paths = sorted({
        path
        for row in rows
        for path in row["test_refs"]
        if path_kind(path) == "test" and path in tree
    })
    candidates: list[dict[str, Any]] = []
    strategy_ids = [row["strategy_id"] for row in rows]
    for path in test_paths:
        text = git_text(repo, commit, path, tree)
        low = text.lower()
        literals = sorted(sid for sid in strategy_ids if sid.lower() in low)
        dynamic_found = sorted(marker for marker in DYNAMIC_TEST_MARKERS if marker in low)
        shape = ast_shape(text) if path.endswith(".py") else {"parse_ok": True, "functions": [], "classes": []}
        executable = bool(shape.get("functions") or shape.get("classes"))
        candidates.append({
            "path": path,
            "literal_strategy_count": len(literals),
            "literal_strategy_ids": literals,
            "dynamic_markers": dynamic_found,
            "executable_surface": executable,
            "real_parameterized_candidate": bool(
                executable and len(dynamic_found) >= 2 and ("entrypoint" in low or "implementation_refs" in low)
            ),
        })
    candidates.sort(
        key=lambda row: (
            row["real_parameterized_candidate"],
            len(row["dynamic_markers"]),
            row["literal_strategy_count"],
            row["path"],
        ),
        reverse=True,
    )
    return candidates


def derive_patch_targets(
    rows: list[dict[str, Any]],
    callers: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    a3b: dict[str, Any],
) -> dict[str, Any]:
    plan = a3b.get("plan") if isinstance(a3b.get("plan"), dict) else {}
    missing_test_ids = sorted({str(x) for x in plan.get("missing_test_strategy_ids", []) if str(x)})
    proven_callers = [row for row in callers if row["actual_shared_caller_candidate"]]
    parameterized_tests = [row for row in tests if row["real_parameterized_candidate"]]
    if proven_callers and parameterized_tests and not missing_test_ids:
        classification = "EXISTING_BINDING_PROVEN"
        next_stage = "R7.A3_REAUDIT_AFTER_EXISTING_BINDING_PROOF"
    elif proven_callers:
        classification = "TEST_CLOSURE_REQUIRED"
        next_stage = "R7.A3C2_STRATEGY25_REAL_ENTRYPOINT_TEST_CLOSURE"
    elif callers:
        classification = "SHARED_ADAPTER_AND_TEST_CLOSURE_REQUIRED"
        next_stage = "R7.A3C2_STRATEGY25_MINIMAL_SHARED_ADAPTER_AND_TEST_PATCH"
    else:
        classification = "NO_COMMON_CALLER_PROVEN"
        next_stage = "R7.A3C2_STRATEGY25_EXACT_CALLER_BINDING_PATCH"
    primary = callers[0] if callers else None
    return {
        "classification": classification,
        "next_stage": next_stage,
        "primary_caller_candidate": primary,
        "proven_shared_callers": proven_callers,
        "parameterized_test_candidates": parameterized_tests,
        "missing_test_strategy_ids": missing_test_ids,
        "missing_test_count": len(missing_test_ids),
        "patch_boundaries": {
            "strategy_logic_edit_allowed": False,
            "parameter_edit_allowed": False,
            "shared_adapter_max_new_files": 2,
            "existing_common_caller_max_modified_files": 1,
            "real_entrypoint_test_files_max": 2,
            "required_receipt_keys": ["strategy_id", "source_sha", "event_id", "feature_ts", "signal", "invalidation"],
            "required_replay_guards": ["point_in_time", "lookahead_zero", "cost_model_bound"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected_count = int(contract.get("expected_strategy_count", 25))
    a3_path = root / str(contract.get("prior_a3_status_path"))
    a3b_path = root / str(contract.get("prior_a3b_status_path"))
    status_path = root / str(contract.get("status_path"))
    protected_paths = [str(x) for x in contract.get("protected_paths", [])]
    before = fingerprints(protected_paths)

    blockers: list[str] = []
    a3 = load_json(a3_path)
    a3b = load_json(a3b_path)
    if not prior_a3b_valid(a3b, expected_count):
        blockers.append("PRIOR_A3B_INVALID")

    rows, row_blockers = normalize_rows(a3, expected_count)
    blockers.extend(row_blockers)

    try:
        commit, tree = list_tree(root, args.target_sha)
    except Exception as exc:
        commit, tree = "", {}
        blockers.append(str(exc))

    callers = candidate_common_callers(root, commit, tree, rows) if commit and rows else []
    tests = dynamic_test_candidates(root, commit, tree, rows) if commit and rows else []
    patch_plan = derive_patch_targets(rows, callers, tests, a3b) if rows else {
        "classification": "UNKNOWN",
        "next_stage": "R7.A3C1_DIAGNOSE",
        "missing_test_strategy_ids": [],
        "missing_test_count": 0,
    }

    after = fingerprints(protected_paths)
    protected_changes = [
        {"path": path, "before": before.get(path), "after": after.get(path)}
        for path in protected_paths
        if before.get(path) != after.get(path)
    ]
    if protected_changes:
        blockers.append("PROTECTED_PATH_CHANGED")

    state = "PASS" if not blockers else "HOLD"
    next_stage = patch_plan.get("next_stage") if state == "PASS" else "R7.A3C1_DIAGNOSE"
    proven_count = sum(1 for row in callers if row["actual_shared_caller_candidate"])
    parameterized_count = sum(1 for row in tests if row["real_parameterized_candidate"])

    payload = {
        "schema": "r7a3c1_strategy25_actual_caller_proof_status_v1",
        "official_stage": "R7.A3C1",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "read_only": True,
        "target_commit": commit,
        "prior_a3b_valid": prior_a3b_valid(a3b, expected_count),
        "strategy_count": len(rows),
        "common_caller_candidate_count": len(callers),
        "proven_shared_caller_count": proven_count,
        "parameterized_test_candidate_count": parameterized_count,
        "caller_candidates": callers,
        "test_candidates": tests,
        "patch_plan": patch_plan,
        "performance_s_promoted_count": 0,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "runtime_mutation_count": 0,
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)

    print("R7A3C1_STRATEGY25_ACTUAL_CALLER_PROOF_COMPLETE")
    for key, value in (
        ("STATE", state),
        ("BLOCKER_COUNT", len(blockers)),
        ("BLOCKERS", json.dumps(blockers, ensure_ascii=False)),
        ("PRIOR_A3B_VALID", str(prior_a3b_valid(a3b, expected_count)).lower()),
        ("STRATEGY_COUNT", len(rows)),
        ("COMMON_CALLER_CANDIDATE_COUNT", len(callers)),
        ("PROVEN_SHARED_CALLER_COUNT", proven_count),
        ("PARAMETERIZED_TEST_CANDIDATE_COUNT", parameterized_count),
        ("CLASSIFICATION", patch_plan.get("classification")),
        ("MISSING_TEST_COUNT", patch_plan.get("missing_test_count")),
        ("PERFORMANCE_S_PROMOTED_COUNT", 0),
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
