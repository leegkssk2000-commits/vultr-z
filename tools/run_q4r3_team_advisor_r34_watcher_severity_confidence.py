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
    tests = [
        wt / "tests/test_q4r3_team_advisor_r33_dynamic_role_helper_reserve.py",
        wt / "tests/test_q4r3_team_advisor_r34_watcher_severity_confidence.py",
    ]
    validator = wt / "tools/q4r3_team_advisor_r34_validate_watcher_severity_confidence.py"
    r33 = root / "runtime/exact25_edge_v1/team_advisor_r33_dynamic_role_helper_reserve/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r34_watcher_severity_confidence/status_latest.json"
    compile_files = [
        wt / "canonical/teams/policy_contracts.py",
        wt / "canonical/teams/role_engine.py",
        wt / "canonical/teams/watcher_confidence.py",
        validator,
        *tests,
    ]
    for path in [*compile_files, r33]:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    subprocess.run([py, "-m", "py_compile", *map(str, compile_files)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", *map(str, tests)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([py, str(validator), "--r33", str(r33), "--output", str(output)], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R34_WATCHER_SEVERITY_CONFIDENCE_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
