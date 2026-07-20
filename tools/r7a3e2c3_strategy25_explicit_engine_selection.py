#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from r7a3e2c3_engine_selection_lib import (
    import_hits,
    literal_hits,
    module_variants,
    path_kind,
    score_candidate,
    select_candidate,
)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic(path: Path, value: dict[str, Any]) -> None:
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


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=30)
        return (result.stdout or "") + (result.stderr or "")
    except Exception:
        return ""


def runtime_evidence() -> tuple[str, int]:
    units_text = command([
        "systemctl", "list-units", "--type=service", "--state=running",
        "--no-legend", "--no-pager",
    ])
    units = [line.split()[0] for line in units_text.splitlines() if line.split()]
    chunks = [units_text, command(["ps", "-eo", "pid=,args="])]
    for unit in units:
        chunks.append(command([
            "systemctl", "show", unit, "--no-pager",
            "-p", "ExecStart", "-p", "MainPID", "-p", "FragmentPath",
        ]))
    return "\n".join(chunks), len(units)


def source_records(snapshot: Path) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    suffixes = {".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".service", ".sh"}
    for path in snapshot.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes or path.stat().st_size > 2_000_000:
            continue
        repo_path = path.relative_to(snapshot).as_posix()
        records.append((repo_path, path_kind(repo_path), path.read_text(encoding="utf-8", errors="replace")))
    return records


def history(root: Path, target_sha: str, repo_path: str) -> dict[str, Any]:
    text = command([
        "git", "-c", f"safe.directory={root}", "log", "-1",
        "--format=%H%x09%ct%x09%an", target_sha, "--", repo_path,
    ], cwd=root).strip()
    parts = text.split("\t", 2) if text else []
    return {
        "last_commit_sha": parts[0] if len(parts) > 0 else None,
        "last_commit_epoch": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
        "last_commit_author": parts[2] if len(parts) > 2 else None,
    }


def evidence_for(
    candidate: dict[str, Any],
    strategy_id: str,
    snapshot: Path,
    records: list[tuple[str, str, str]],
    runtime_text: str,
) -> dict[str, int]:
    candidate_path = str(candidate.get("path") or candidate.get("implementation_path") or "")
    candidate_source_path = snapshot / candidate_path
    candidate_source = candidate_source_path.read_text(encoding="utf-8", errors="replace") if candidate_source_path.is_file() else ""
    modules = module_variants(candidate_path)
    runtime_hits = int(candidate_path in runtime_text)
    runtime_hits += sum(1 for module in modules if len(module) >= 6 and module in runtime_text)
    prod_import = prod_literal = test = config = 0
    for repo_path, kind, source in records:
        if repo_path == candidate_path:
            continue
        if kind == "SOURCE" and repo_path.endswith(".py"):
            prod_import += import_hits(source, candidate_path)
            literal, _ = literal_hits(source, candidate_path, strategy_id)
            prod_literal += literal
        elif kind == "DIAGNOSTIC":
            literal, _ = literal_hits(source, candidate_path, strategy_id)
            test += literal
        elif kind == "CONFIG":
            literal, _ = literal_hits(source, candidate_path, strategy_id)
            config += literal
    return {
        "runtime_hits": runtime_hits,
        "production_import_hits": prod_import,
        "production_literal_hits": prod_literal,
        "config_hits": config,
        "test_hits": test,
        "candidate_strategy_literal_hits": candidate_source.count(strategy_id),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    snapshot = Path(args.snapshot).resolve()
    contract = load(Path(args.contract))
    prior_status = load(root / contract["prior_status_path"])
    prior_proof = load(root / contract["prior_proof_path"])
    prior_matrix = load(root / contract["prior_matrix_path"])
    blockers: list[str] = []

    if not (prior_status.get("state") == "PASS" and prior_status.get("blocker_count") == 0):
        blockers.append("PRIOR_A3E2C_INVALID")
    if prior_status.get("ambiguous_engine_count") != int(contract.get("expected_ambiguous_count", 23)):
        blockers.append("PRIOR_AMBIGUOUS_COUNT_MISMATCH")
    if prior_status.get("implementation_gap_count") != 0:
        blockers.append("PRIOR_IMPLEMENTATION_GAP_NOT_ZERO")
    if not snapshot.is_dir():
        blockers.append("TARGET_SNAPSHOT_INVALID")

    proof_entries = [row for row in prior_proof.get("entries", []) if isinstance(row, dict)]
    ambiguous = [row for row in proof_entries if row.get("classification") == "MULTIPLE_PRODUCTION_MATCHES"]
    if len(ambiguous) != int(contract.get("expected_ambiguous_count", 23)):
        blockers.append("AMBIGUOUS_ENTRY_COUNT_NOT_23")
    matrix_entries = [row for row in prior_matrix.get("entries", []) if isinstance(row, dict)]
    if len(matrix_entries) != int(contract.get("expected_strategy_count", 25)):
        blockers.append("PRIOR_MATRIX_COUNT_NOT_25")

    before = {path: sha256(Path(path)) for path in contract.get("protected_paths", [])}
    runtime_text, active_units = runtime_evidence()
    records = source_records(snapshot) if not blockers else []
    minimum_margin = int(contract.get("minimum_score_margin", 80))
    results: list[dict[str, Any]] = []

    for row in sorted(ambiguous, key=lambda item: str(item.get("strategy_id"))):
        strategy_id = str(row.get("strategy_id") or "")
        source_matches = [item for item in row.get("source_matches", []) if isinstance(item, dict)]
        ranked: list[dict[str, Any]] = []
        for candidate in source_matches:
            evidence = evidence_for(candidate, strategy_id, snapshot, records, runtime_text)
            scored = score_candidate(candidate, evidence, strategy_id)
            candidate_path = str(candidate.get("path") or candidate.get("implementation_path") or "")
            scored["history"] = history(root, args.target_sha, candidate_path)
            ranked.append(scored)
        selected, ranked, reason = select_candidate(ranked, minimum_margin)
        alternate = None
        if selected and len(ranked) == 2:
            alternate = next(
                (item for item in ranked if str(item.get("path")) != str(selected.get("path")) or str(item.get("callable")) != str(selected.get("callable"))),
                None,
            )
        results.append({
            "strategy_id": strategy_id,
            "selected": selected,
            "alternate": alternate,
            "selection_state": "CANONICAL_SELECTED" if selected else "EXPLICIT_OWNER_RECORD_REQUIRED",
            "reason": reason,
            "ranked_candidates": ranked,
            "active_allowed": False,
            "alternate_state": "LEGACY_NOT_ACTIVE_PLANNED" if alternate else None,
        })

    selected_count = sum(row.get("selected") is not None for row in results)
    owner_required_count = len(results) - selected_count
    after = {path: sha256(Path(path)) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")
    blockers = list(dict.fromkeys(blockers))
    state = "PASS" if not blockers else "HOLD"
    if blockers:
        next_stage = contract["next_stage_fail"]
    elif owner_required_count:
        next_stage = contract["next_stage_owner_required"]
    else:
        next_stage = contract["next_stage_all_selected"]

    selection = {
        "schema": "strategy25_explicit_engine_selection_v1",
        "official_stage": "R7.A3E2C3",
        "read_only": True,
        "target_commit": args.target_sha,
        "strategy_count": int(contract.get("expected_strategy_count", 25)),
        "prior_engine_bound_count": int(contract.get("expected_prior_engine_bound_count", 2)),
        "ambiguous_input_count": len(ambiguous),
        "selected_count": selected_count,
        "owner_record_required_count": owner_required_count,
        "active_runtime_unit_count": active_units,
        "active_entry_count": 0,
        "entries": results,
    }
    atomic(root / contract["selection_path"], selection)
    status = {
        "official_stage": "R7.A3E2C3",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": int(contract.get("expected_strategy_count", 25)),
        "prior_engine_bound_count": int(contract.get("expected_prior_engine_bound_count", 2)),
        "ambiguous_input_count": len(ambiguous),
        "canonical_selected_count": selected_count,
        "owner_record_required_count": owner_required_count,
        "active_runtime_unit_count": active_units,
        "active_entry_count": 0,
        "canonical_registry_mutation_count": 0,
        "strategy_logic_mutation_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "selection_path": str(root / contract["selection_path"]),
        "next_stage": next_stage,
    }
    atomic(root / contract["status_path"], status)
    for key in (
        "state", "blocker_count", "strategy_count", "prior_engine_bound_count",
        "ambiguous_input_count", "canonical_selected_count", "owner_record_required_count",
        "active_runtime_unit_count", "active_entry_count", "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("OWNER_RECORD_REQUIRED=" + json.dumps([
        {"strategy_id": row["strategy_id"], "reason": row["reason"],
         "scores": [item.get("selection_score") for item in row["ranked_candidates"]],
         "paths": [item.get("path") for item in row["ranked_candidates"]]}
        for row in results if row["selected"] is None
    ], ensure_ascii=False))
    print("SELECTION_JSON=" + status["selection_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
