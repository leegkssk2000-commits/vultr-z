#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args()
    py = str(args.root / ".venv/bin/python") if (args.root / ".venv/bin/python").is_file() else sys.executable
    runtime = args.root / "runtime/exact25_edge_v1/exact25_r73b2_minimal_isolation_rollback_plan"
    plan = runtime / "plan_latest.json"
    status = runtime / "status_latest.json"
    r73b1 = args.root / "runtime/exact25_edge_v1/exact25_r73b1_single_owner_plan"
    r73b1_status = r73b1 / "status_latest.json"
    r73b1_disposition = r73b1 / "plan_latest.json"
    contract = args.worktree / "backend/contracts/ZOS_EXACT25_R73B2_MINIMAL_ISOLATION_ROLLBACK_PLAN_v1.json"

    run([py, "-m", "pytest", "-q", str(args.worktree / "tests/test_q4r3_exact25_r73b2_minimal_isolation_rollback_plan.py")])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b2_build_minimal_isolation_rollback_plan.py"),
        "--contract", str(contract),
        "--status", str(r73b1_status),
        "--disposition", str(r73b1_disposition),
        "--output", str(plan),
    ])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b2_validate_minimal_isolation_rollback_plan.py"),
        "--contract", str(contract),
        "--plan", str(plan),
        "--output", str(status),
    ])
    print("Q4R3_EXACT25_R73B2_MINIMAL_ISOLATION_ROLLBACK_PLAN_COMPLETE")
    print(f"STATUS={status}")
    print(f"PLAN={plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
