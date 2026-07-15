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
    test = wt / "tests/test_q4r3_team_advisor_r09_team_proposal_attribution.py"
    validator = wt / "tools/q4r3_team_advisor_r09_validate_team_proposal_attribution.py"
    r082 = root / "runtime/exact25_edge_v1/team_advisor_r082_role_authority/status_latest.json"
    matrix = wt / "config/q4r3_performance_attribution_matrix_v1.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r09_team_proposal_attribution/status_latest.json"
    required = [
        test, validator, r082, matrix,
        wt / "canonical/teams/proposal.py",
        wt / "canonical/performance/contracts.py",
        wt / "canonical/zlice/contracts.py",
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    subprocess.run([py, "-m", "py_compile", *[str(path) for path in required if path.suffix == ".py"]], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py, str(validator), "--r082", str(r082), "--matrix", str(matrix), "--output", str(output)
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R09_TEAM_PROPOSAL_ATTRIBUTION_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
