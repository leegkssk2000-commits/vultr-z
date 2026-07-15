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
    test = wt / "tests/test_q4r3_team_advisor_r10_zlice_core_projection_boundary.py"
    validator = wt / "tools/q4r3_team_advisor_r10_validate_zlice_core_projection_boundary.py"
    r09 = root / "runtime/exact25_edge_v1/team_advisor_r09_team_proposal_attribution/status_latest.json"
    architecture = wt / "config/q4r3_zlice_architecture_v1.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r10_zlice_core_projection_boundary/status_latest.json"
    required = [
        test,
        validator,
        r09,
        architecture,
        wt / "canonical/zlice/contracts.py",
        wt / "canonical/zlice/ledger.py",
        wt / "canonical/zlice/projection.py",
        wt / "canonical/performance/evaluator.py",
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    python_sources = [str(path) for path in required if path.suffix == ".py"]
    subprocess.run([py, "-m", "py_compile", *python_sources], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(validator),
        "--r09", str(r09),
        "--architecture", str(architecture),
        "--output", str(output),
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R10_ZLICE_CORE_PROJECTION_BOUNDARY_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
