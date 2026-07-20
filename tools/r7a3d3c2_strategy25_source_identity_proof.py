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
from typing import Any


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


def file_sha(path: str) -> str | None:
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return digest


def git_text(root: Path, commit: str, path: str) -> str | None:
    cp = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        text=True,
        capture_output=True,
        timeout=60,
    )
    return cp.stdout if cp.returncode == 0 else None


def git_blob(root: Path, commit: str, path: str) -> str | None:
    cp = subprocess.run(
        ["git", "-C", str(root), "rev-parse", f"{commit}:{path}"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    return cp.stdout.strip() if cp.returncode == 0 else None


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def find_callable(tree: ast.AST, name: str) -> ast.AST | None:
    target = name.split(".")[-1]
    nodes = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target
    ]
    return nodes[0] if len(nodes) == 1 else None


def string_constants(node: ast.AST) -> list[str]:
    return [
        value.value for value in ast.walk(node)
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    ]


def ref_has_strategy_id(ref: dict[str, Any], strategy_id: str) -> bool:
    needle = normalize(strategy_id)
    values = [
        ref.get("source_path"), ref.get("target_path"), ref.get("callable"),
        ref.get("json_path"), ref.get("line"), *(ref.get("config_keys") or []),
    ]
    return any(needle and needle in normalize(str(value or "")) for value in values)


def inspect_candidate(root: Path, commit: str, strategy_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
    path = str(candidate.get("implementation_path") or "")
    callable_name = str(candidate.get("callable") or "")
    source = git_text(root, commit, path) if path else None
    blob = git_blob(root, commit, path) if path else None
    result: dict[str, Any] = {
        **candidate,
        "source_exists": source is not None,
        "actual_blob_sha": blob,
        "blob_parity": bool(blob and blob == candidate.get("git_blob_sha")),
        "callable_exists": False,
        "callable_body_sha256": None,
        "identity_score": 0,
        "identity_reasons": [],
    }
    if source is None or not callable_name or not path.endswith(".py"):
        return result
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return result
    node = find_callable(tree, callable_name)
    if node is None:
        return result
    result["callable_exists"] = True
    body_dump = ast.dump(node, annotate_fields=True, include_attributes=False)
    result["callable_body_sha256"] = hashlib.sha256(body_dump.encode()).hexdigest()
    constants = string_constants(node)
    sid_norm = normalize(strategy_id)
    path_match = normalize(Path(path).stem) == sid_norm
    callable_match = normalize(callable_name.split(".")[-1]) == sid_norm
    callable_literal = any(normalize(value) == sid_norm for value in constants)
    binding_match = any(
        ref_has_strategy_id(ref, strategy_id)
        for ref in candidate.get("binding_refs", []) if isinstance(ref, dict)
    )
    checks = (
        (path_match, 160, "EXACT_PATH_STEM"),
        (callable_match, 160, "EXACT_CALLABLE_NAME"),
        (callable_literal, 120, "EXACT_CALLABLE_LITERAL"),
        (binding_match, 140, "EXACT_BINDING_REFERENCE"),
        (candidate.get("direct_name_match") is True, 120, "PRIOR_DIRECT_NAME"),
        (candidate.get("explicit_binding") is True and binding_match, 80, "EXPLICIT_BINDING_WITH_ID"),
        (result["blob_parity"], 20, "BLOB_PARITY"),
    )
    for condition, points, label in checks:
        if condition:
            result["identity_score"] += points
            result["identity_reasons"].append(label)
    result["identity_anchor"] = any(
        label in result["identity_reasons"]
        for label in ("EXACT_PATH_STEM", "EXACT_CALLABLE_NAME", "EXACT_CALLABLE_LITERAL", "EXACT_BINDING_REFERENCE")
    )
    return result


def classify(root: Path, commit: str, row: dict[str, Any], minimum_margin: int) -> dict[str, Any]:
    strategy_id = str(row.get("strategy_id") or "")
    if row.get("registry_patch_ready") is True and row.get("canonical_mapping"):
        return {
            "strategy_id": strategy_id,
            "classification": "PRIOR_PROVEN",
            "proven": True,
            "canonical_mapping": row.get("canonical_mapping"),
            "candidate_count": 0,
        }
    candidates = [
        inspect_candidate(root, commit, strategy_id, candidate)
        for candidate in row.get("top_candidates", []) if isinstance(candidate, dict)
    ]
    candidates.sort(key=lambda item: (item.get("identity_score", 0), item.get("implementation_path", "")), reverse=True)
    complete = [item for item in candidates if item.get("source_exists") and item.get("callable_exists") and item.get("actual_blob_sha")]
    anchored = [item for item in complete if item.get("identity_anchor")]
    top = anchored[0] if anchored else None
    second = anchored[1] if len(anchored) > 1 else None
    margin = (top["identity_score"] - second["identity_score"]) if top else 0
    if top and margin >= minimum_margin:
        mapping = {
            "implementation_path": top.get("implementation_path"),
            "callable": top.get("callable"),
            "binding_kind": top.get("binding_kind"),
            "source_blob_sha": top.get("actual_blob_sha"),
            "binding_source": "A3D3C2_SOURCE_IDENTITY_PROOF",
            "binding_evidence": top.get("identity_reasons"),
        }
        return {
            "strategy_id": strategy_id,
            "classification": "EXISTING_IMPLEMENTATION_BOUND",
            "proven": True,
            "canonical_mapping": mapping,
            "candidate_count": len(candidates),
            "identity_margin": margin,
            "candidate_proofs": candidates,
        }
    body_hashes = {item.get("callable_body_sha256") for item in complete if item.get("callable_body_sha256")}
    if complete and len(body_hashes) == 1:
        classification = "SHARED_ENGINE_REQUIRES_EXPLICIT_BINDING"
    elif complete:
        classification = "MULTIPLE_IMPLEMENTATIONS_WITHOUT_IDENTITY_BINDING"
    else:
        classification = "NO_CALLABLE_IMPLEMENTATION_PROVEN"
    return {
        "strategy_id": strategy_id,
        "classification": classification,
        "proven": False,
        "canonical_mapping": None,
        "candidate_count": len(candidates),
        "identity_margin": margin,
        "candidate_proofs": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    contract = load(Path(args.contract))
    prior_status = load(root / contract["prior_status_path"])
    prior_plan = load(root / contract["prior_plan_path"])
    expected = int(contract.get("expected_strategy_count", 25))
    blockers: list[str] = []
    if not (prior_status.get("state") == "PASS" and prior_status.get("blocker_count") == 0):
        blockers.append("PRIOR_A3D3C_INVALID")
    if prior_status.get("registry_patch_ready_count") != int(contract.get("expected_prior_ready_count", 2)):
        blockers.append("PRIOR_READY_COUNT_MISMATCH")
    if prior_status.get("source_diff_required_count") != int(contract.get("expected_prior_source_diff_count", 23)):
        blockers.append("PRIOR_SOURCE_DIFF_COUNT_MISMATCH")
    rows = [row for row in prior_plan.get("mappings", []) if isinstance(row, dict)]
    if len(rows) != expected:
        blockers.append("PRIOR_PLAN_MAPPING_COUNT_NOT_25")
    commit_cp = subprocess.run(["git", "-C", str(root), "rev-parse", f"{args.target_sha}^{{commit}}"], text=True, capture_output=True)
    commit = commit_cp.stdout.strip() if commit_cp.returncode == 0 else ""
    if not commit:
        blockers.append("TARGET_COMMIT_UNRESOLVED")
    before = {path: file_sha(path) for path in contract.get("protected_paths", [])}
    results = [classify(root, commit, row, int(contract.get("minimum_identity_margin", 40))) for row in rows] if commit else []
    proven = sum(bool(row.get("proven")) for row in results)
    class_counts: dict[str, int] = {}
    for row in results:
        key = str(row.get("classification"))
        class_counts[key] = class_counts.get(key, 0) + 1
    after = {path: file_sha(path) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")
    state = "PASS" if not blockers else "HOLD"
    gap_count = expected - proven
    next_stage = contract["next_stage_fail"] if blockers else (
        contract["next_stage_all_proven"] if gap_count == 0 else contract["next_stage_gap"]
    )
    proof = {
        "schema": "r7a3d3c2_strategy25_source_identity_proof_v1",
        "official_stage": "R7.A3D3C2",
        "read_only": True,
        "target_commit": commit,
        "strategy_count": len(results),
        "proven_mapping_count": proven,
        "implementation_gap_count": gap_count,
        "classification_counts": class_counts,
        "mappings": results,
    }
    atomic(root / contract["proof_path"], proof)
    status = {
        "official_stage": "R7.A3D3C2",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(results),
        "proven_mapping_count": proven,
        "implementation_gap_count": gap_count,
        "classification_counts": class_counts,
        "canonical_mapping_mutation_count": 0,
        "strategy_logic_mutation_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "proof_path": str(root / contract["proof_path"]),
        "next_stage": next_stage,
    }
    atomic(root / contract["status_path"], status)
    for key in ("state", "blocker_count", "strategy_count", "proven_mapping_count", "implementation_gap_count", "canonical_mapping_mutation_count", "protected_change_count", "next_stage"):
        print(f"{key.upper()}={status[key]}")
    print("CLASSIFICATION_COUNTS=" + json.dumps(class_counts, ensure_ascii=False, sort_keys=True))
    print("IMPLEMENTATION_GAPS=" + json.dumps([
        {"strategy_id": row["strategy_id"], "classification": row["classification"], "candidate_count": row.get("candidate_count", 0)}
        for row in results if not row.get("proven")
    ], ensure_ascii=False))
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
