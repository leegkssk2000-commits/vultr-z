#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

DIAGNOSTIC = ("audit", "smoke", "bootstrap", "display", "probe", "readiness", "diagnose", "report", "test")


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


def sha256(path: str) -> str | None:
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    digest.update(target.read_bytes())
    return digest.hexdigest()


def diagnostic_path(path: str) -> bool:
    low = path.lower()
    return low.startswith(("tests/", "test/", "docs/")) or any(token in low for token in DIAGNOSTIC)


def score_candidate(candidate: dict[str, Any]) -> tuple[int, list[str]]:
    path = str(candidate.get("implementation_path") or "")
    reasons: list[str] = []
    score = 0
    checks = (
        (candidate.get("git_path_exists") is True, 30, "git_path"),
        (bool(candidate.get("callable")), 30, "callable"),
        (bool(candidate.get("git_blob_sha")), 20, "git_blob"),
        (candidate.get("git_blob_sha") == candidate.get("candidate_source_blob_sha") and bool(candidate.get("git_blob_sha")), 20, "blob_parity"),
        (candidate.get("direct_name_match") is True, 120, "direct_name"),
        (candidate.get("explicit_binding") is True, 90, "explicit_binding"),
        (bool(candidate.get("active_import_chain")), 35, "active_import_chain"),
        (bool(candidate.get("active_exact_units")), 35, "active_exact_unit"),
        (candidate.get("binding_kind") == "direct", 30, "direct_kind"),
        (candidate.get("binding_kind") == "git_path", 20, "git_path_kind"),
        (candidate.get("binding_kind") == "registry_or_shared", 10, "registry_kind"),
        ("strategy" in path.lower(), 10, "strategy_path"),
    )
    for condition, points, label in checks:
        if condition:
            score += points
            reasons.append(f"{label}:+{points}")
    if diagnostic_path(path):
        score -= 250
        reasons.append("diagnostic:-250")
    return score, reasons


def plan_mapping(row: dict[str, Any], minimum_margin: int) -> dict[str, Any]:
    strategy_id = str(row.get("strategy_id") or "")
    if row.get("resolved") is True and row.get("canonical_mapping"):
        return {
            "strategy_id": strategy_id,
            "resolution": "PRIOR_RESOLVED",
            "registry_patch_ready": True,
            "canonical_mapping": row.get("canonical_mapping"),
            "candidate_count": 0,
            "score_margin": None,
        }

    candidates = []
    for candidate in row.get("candidate_proofs", []):
        if not isinstance(candidate, dict):
            continue
        score, reasons = score_candidate(candidate)
        candidates.append({**candidate, "selection_score": score, "selection_reasons": reasons})
    candidates.sort(key=lambda item: (item["selection_score"], item.get("implementation_path", "")), reverse=True)
    top = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    margin = (top["selection_score"] - second["selection_score"]) if top else 0
    identity_anchor = bool(top and (top.get("direct_name_match") is True or top.get("explicit_binding") is True))
    complete = bool(top and top.get("git_path_exists") and top.get("callable") and top.get("git_blob_sha"))
    unique = bool(top and complete and identity_anchor and margin >= minimum_margin)
    selected = None
    if unique:
        selected = {
            "implementation_path": top.get("implementation_path"),
            "callable": top.get("callable"),
            "binding_kind": top.get("binding_kind"),
            "source_blob_sha": top.get("git_blob_sha"),
            "binding_source": "A3D3C_EXPLICIT_PLAN",
            "binding_evidence": top.get("selection_reasons"),
        }
    return {
        "strategy_id": strategy_id,
        "resolution": "REGISTRY_PATCH_READY" if unique else "SOURCE_DIFF_REQUIRED",
        "registry_patch_ready": unique,
        "canonical_mapping": selected,
        "candidate_count": len(candidates),
        "top_score": top.get("selection_score") if top else None,
        "score_margin": margin,
        "top_candidates": candidates[:3],
        "unresolved_reason": None if unique else "NO_UNIQUE_IDENTITY_ANCHORED_CANDIDATE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    contract = load(Path(args.contract))
    status = load(root / contract["prior_status_path"])
    proof = load(root / contract["prior_proof_path"])
    expected = int(contract.get("expected_strategy_count", 25))
    blockers: list[str] = []
    if not (status.get("state") == "PASS" and status.get("blocker_count") == 0):
        blockers.append("PRIOR_A3D3B_INVALID")
    if status.get("resolved_mapping_count") != int(contract.get("expected_prior_resolved_count", 2)):
        blockers.append("PRIOR_RESOLVED_COUNT_MISMATCH")
    if status.get("unresolved_mapping_count") != int(contract.get("expected_prior_unresolved_count", 23)):
        blockers.append("PRIOR_UNRESOLVED_COUNT_MISMATCH")
    mappings = [row for row in proof.get("mappings", []) if isinstance(row, dict)]
    if len(mappings) != expected:
        blockers.append("PRIOR_PROOF_MAPPING_COUNT_NOT_25")

    before = {path: sha256(path) for path in contract.get("protected_paths", [])}
    plans = [plan_mapping(row, int(contract.get("minimum_selection_margin", 30))) for row in mappings]
    ready = sum(bool(row.get("registry_patch_ready")) for row in plans)
    source_diff = sum(row.get("resolution") == "SOURCE_DIFF_REQUIRED" for row in plans)
    registry = {
        "schema": "canonical_strategy_registry_v1",
        "read_only_plan": True,
        "target_path": contract["future_registry_path"],
        "strategy_count": len(plans),
        "registry_patch_ready_count": ready,
        "source_diff_required_count": source_diff,
        "required_entry_fields": ["strategy_id", "implementation_path", "callable", "source_blob_sha", "binding_source"],
        "mappings": plans,
    }
    atomic(root / contract["plan_path"], registry)
    after = {path: sha256(path) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")
    state = "PASS" if not blockers else "HOLD"
    if blockers:
        next_stage = contract["next_stage_fail"]
    elif source_diff:
        next_stage = contract["next_stage_source_diff"]
    else:
        next_stage = contract["next_stage_all_planned"]
    result = {
        "official_stage": "R7.A3D3C",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(plans),
        "registry_patch_ready_count": ready,
        "source_diff_required_count": source_diff,
        "canonical_mapping_mutation_count": 0,
        "strategy_logic_mutation_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "performance_s_promoted_count": 0,
        "plan_path": str(root / contract["plan_path"]),
        "next_stage": next_stage,
    }
    atomic(root / contract["status_path"], result)
    for key in ("state", "blocker_count", "strategy_count", "registry_patch_ready_count", "source_diff_required_count", "canonical_mapping_mutation_count", "protected_change_count", "next_stage"):
        print(f"{key.upper()}={result[key]}")
    print("SOURCE_DIFF_REQUIRED=" + json.dumps([{"strategy_id": row["strategy_id"], "candidate_count": row["candidate_count"], "top_score": row.get("top_score"), "margin": row.get("score_margin")} for row in plans if row["resolution"] == "SOURCE_DIFF_REQUIRED"], ensure_ascii=False))
    print("PLAN_JSON=" + result["plan_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
