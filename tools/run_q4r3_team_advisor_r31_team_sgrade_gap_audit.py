#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    wt = args.worktree.resolve()
    py = python_bin(root)
    test = wt / "tests/test_q4r3_team_advisor_r31_team_sgrade_gap_audit.py"
    validator = wt / "tools/q4r3_team_advisor_r31_team_sgrade_gap_audit.py"
    r26 = root / "runtime/exact25_edge_v1/team_advisor_r26_four_bot_sgrade_lock/status_latest.json"
    contract = wt / "config/q4r3_team_sgrade_gap_audit_contract_v1.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r31_team_sgrade_gap_audit/status_latest.json"
    required = [
        test, validator, r26, contract,
        wt / "canonical/teams/registry.py",
        wt / "canonical/teams/models.py",
        wt / "canonical/teams/binding.py",
        wt / "canonical/teams/proposal.py",
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    py_files = [str(path) for path in required if path.suffix == ".py"]
    subprocess.run([py, "-m", "py_compile", *py_files], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py, str(validator),
        "--worktree", str(wt),
        "--r26", str(r26),
        "--contract", str(contract),
        "--output", str(output),
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R31_TEAM_SGRADE_GAP_AUDIT_COMPLETE")
    print("OFFICIAL_STAGE=R3.1")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
