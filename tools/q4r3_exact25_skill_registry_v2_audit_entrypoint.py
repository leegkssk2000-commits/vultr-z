from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools import q4r3_exact25_skill_registry_v2_audit as audit


ACTIVE_EXACT25_MANIFEST = Path(
    "/home/z/z/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
)


def discover_active_exact25() -> dict:
    if not ACTIVE_EXACT25_MANIFEST.is_file():
        return {
            "candidate_count": 0,
            "exact25_candidate_count": 0,
            "selected": None,
            "candidates": [],
            "state": "HOLD",
            "reason": "canonical_exact25_manifest_missing",
        }
    try:
        data = json.loads(ACTIVE_EXACT25_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "candidate_count": 1,
            "exact25_candidate_count": 0,
            "selected": None,
            "candidates": [],
            "state": "HOLD",
            "reason": "canonical_exact25_manifest_invalid",
        }

    entries = data.get("strategies") if isinstance(data, dict) else None
    entries = entries if isinstance(entries, list) else []
    names = [
        str(row.get("strategy_id")).strip()
        for row in entries
        if isinstance(row, dict) and str(row.get("strategy_id") or "").strip()
    ]
    unique = sorted(set(names))
    valid = (
        data.get("strategy_count") == 25
        and len(names) == 25
        and len(unique) == 25
        and data.get("dynamic_fallback_allowed") is False
    )
    selected = {
        "path": str(ACTIVE_EXACT25_MANIFEST),
        "strategy_count": len(unique),
        "names": unique,
        "sha256": audit.sha256(ACTIVE_EXACT25_MANIFEST),
        "runtime_binding_status": data.get("runtime_binding_status"),
        "activation_allowed": data.get("activation_allowed"),
    }
    return {
        "candidate_count": 1,
        "exact25_candidate_count": 1 if valid else 0,
        "selected": selected if valid else None,
        "candidates": [selected],
        "state": "PASS" if valid else "HOLD",
        "reason": "canonical_exact25_manifest_valid" if valid else "canonical_exact25_manifest_contract_failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path, required=True)
    args = parser.parse_args()

    worktree = args.worktree.resolve()
    audit.CANDIDATE_V2 = (
        worktree / "backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json"
    )
    audit.CANDIDATE_RESOLVER = (
        worktree / "backend/engine/skill_resolver_v2_candidate.py"
    )
    audit.discover_exact25 = discover_active_exact25

    summary = audit.run(args.output, args.matrix_output)
    print(
        "SKILL_REGISTRY_V2_AUDIT_COMPLETE "
        f"state={summary.get('state')} "
        f"verdict={summary.get('verdict')} "
        f"matrix_rows={summary.get('compatibility_matrix_rows')}"
    )
    return 0 if summary.get("state") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
