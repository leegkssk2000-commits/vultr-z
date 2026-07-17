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
    runtime = args.root / "runtime/exact25_edge_v1/exact25_r73b1_single_owner_plan"
    plan = runtime / "plan_latest.json"
    status = runtime / "status_latest.json"
    r73b0_runtime = args.root / "runtime/exact25_edge_v1/exact25_r73b0_display_binding_residue_audit"
    r73b0_status = r73b0_runtime / "status_latest.json"
    r73b0_inventory = r73b0_runtime / "inventory_latest.json"
    contract = args.worktree / "backend/contracts/ZOS_EXACT25_R73B1_SINGLE_OWNER_PLAN_v1.json"
    run([py, "-m", "pytest", "-q", str(args.worktree / "tests/test_q4r3_exact25_r73b1_single_owner_plan.py")])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b1_build_single_owner_plan.py"),
        "--contract", str(contract), "--status", str(r73b0_status),
        "--inventory", str(r73b0_inventory), "--output", str(plan),
    ])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b1_validate_single_owner_plan.py"),
        "--contract", str(contract), "--plan", str(plan), "--output", str(status),
    ])
    print("Q4R3_EXACT25_R73B1_SINGLE_OWNER_PLAN_COMPLETE")
    print(f"STATUS={status}")
    print(f"PLAN={plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
