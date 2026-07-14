from __future__ import annotations

import argparse
import os
from pathlib import Path

from tools import q4r3_exact25_skill_registry_v2_audit as audit


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
