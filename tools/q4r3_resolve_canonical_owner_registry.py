from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

ACCEPTED_OWNER_VERDICTS = {
    "PROPOSED_OWNER_CONFIDENT",
    "PROPOSED_OWNER_WITH_WRAPPER_ALTERNATES",
    "SINGLE_DIRECT_OWNER_CANDIDATE",
}

FALSE_AUTHORITY_ROLES = {
    "backend/trade_methods/policy.py": "POLICY_HISTORY_NOT_REGISTRY",
    "backend/trade_methods/profiles.py": "METHOD_PROFILE_HISTORY_NOT_REGISTRY",
    "data/strategy_registry_latest.json": "READONLY_DISCOVERY_INVENTORY_NOT_RUNTIME_AUTHORITY",
}


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def classify_registry(path: str, coverage_count: int) -> str:
    if path in FALSE_AUTHORITY_ROLES:
        return FALSE_AUTHORITY_ROLES[path]
    lower = path.lower()
    if "legendary_manifest" in lower:
        return "LEGENDARY_RESERVE_MANIFEST"
    if "strategy_catalog" in lower:
        return "BOT_CATALOG_PARTIAL"
    if "engine/strategy_registry" in lower:
        return "ENGINE_RUNTIME_REGISTRY_PARTIAL"
    if "config/strategies_registry" in lower:
        return "LEGACY_OR_ALTERNATE_UNIVERSE_REGISTRY"
    if coverage_count == 25 and "registry" in lower:
        return "STRUCTURAL_EXACT_25_REGISTRY_CANDIDATE"
    return "NONAUTHORITATIVE_REFERENCE_SURFACE"


def resolve(owner_matrix: Mapping[str, Any]) -> Dict[str, Any]:
    owners = owner_matrix.get("owners") if isinstance(owner_matrix.get("owners"), list) else []
    manifest_entries: Dict[str, Any] = {}
    unresolved = []
    for item in owners:
        if not isinstance(item, Mapping):
            continue
        strategy = str(item.get("strategy") or "").strip()
        verdict = str(item.get("verdict") or "").strip()
        owner = item.get("proposed_owner")
        sha = item.get("proposed_owner_sha256")
        if not strategy or verdict not in ACCEPTED_OWNER_VERDICTS or not owner or not sha:
            unresolved.append(strategy or "UNKNOWN")
            continue
        manifest_entries[strategy] = {
            "owner_path": owner,
            "owner_kind": item.get("proposed_owner_kind"),
            "owner_sha256": sha,
            "owner_verdict": verdict,
            "confidence": item.get("confidence"),
            "alternatives": item.get("alternatives") or [],
        }

    registry = owner_matrix.get("registry_audit") if isinstance(owner_matrix.get("registry_audit"), Mapping) else {}
    classified = []
    structural_exact = []
    for item in registry.get("files") or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "")
        coverage_count = int(item.get("coverage_count") or 0)
        role = classify_registry(path, coverage_count)
        row = {
            "path": path,
            "coverage_count": coverage_count,
            "coverage_pct": item.get("coverage_pct"),
            "sha256": item.get("sha256"),
            "role": role,
        }
        classified.append(row)
        if role == "STRUCTURAL_EXACT_25_REGISTRY_CANDIDATE":
            structural_exact.append(path)

    exact_25 = len(manifest_entries) == 25 and not unresolved
    if not exact_25:
        verdict = "CANONICAL_OWNER_MANIFEST_INCOMPLETE"
        next_action = "RESOLVE_REMAINING_OWNER_GAPS_BEFORE_CONTRACT_HARNESS"
    elif len(structural_exact) == 1:
        verdict = "CANONICAL_25_OWNER_MANIFEST_READY_WITH_REGISTRY_CANDIDATE"
        next_action = "VERIFY_REGISTRY_RUNTIME_CALLERS_THEN_BUILD_SHARED_CONTRACT_HARNESS"
    else:
        verdict = "CANONICAL_25_OWNER_MANIFEST_READY_REGISTRY_AUTHORITY_ABSENT"
        next_action = "USE_READONLY_OWNER_MANIFEST_AS_CANDIDATE_SSOT_FOR_SHARED_CONTRACT_HARNESS"

    return {
        "schema": "q4r3_canonical_owner_registry_resolution_v1",
        "status": "PASS_Q4R3_CANONICAL_OWNER_REGISTRY_RESOLUTION",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_strategy_count": 25,
        "resolved_owner_count": len(manifest_entries),
        "unresolved_owner_count": len(unresolved),
        "unresolved_strategies": sorted(unresolved),
        "canonical_owner_manifest": manifest_entries,
        "registry_resolution": {
            "original_verdict": registry.get("verdict"),
            "false_exact_candidates_rejected": [
                path for path in registry.get("exact_coverage_files") or [] if path in FALSE_AUTHORITY_ROLES
            ],
            "structural_exact_candidates": structural_exact,
            "classified_candidates": classified,
            "authoritative_candidate": structural_exact[0] if len(structural_exact) == 1 else None,
        },
        "safety": {
            "read_only": True,
            "production_strategy_modified": False,
            "registry_modified": False,
            "paper_live_order_modified": False,
            "persistent_forward_r_watcher_modified": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matrix = json.loads(args.owner_matrix.read_text(encoding="utf-8", errors="ignore"))
    result = resolve(matrix)
    atomic_json(args.output, result)
    print(json.dumps({
        "status": result["status"],
        "verdict": result["verdict"],
        "resolved_owner_count": result["resolved_owner_count"],
        "unresolved_owner_count": result["unresolved_owner_count"],
        "registry_authority": result["registry_resolution"]["authoritative_candidate"],
        "next_action": result["next_action"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
