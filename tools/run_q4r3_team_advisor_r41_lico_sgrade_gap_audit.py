#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python", root / "backend/.venv/bin/python"):
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
    audit = wt / "tools/q4r3_team_advisor_r41_lico_sgrade_gap_audit.py"
    validator = wt / "tools/q4r3_team_advisor_r41_validate_lico_sgrade_gap_audit.py"
    test = wt / "tests/test_q4r3_team_advisor_r41_lico_sgrade_gap_audit.py"
    r36 = root / "runtime/exact25_edge_v1/team_advisor_r36_four_team_sgrade_lock/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r41_lico_sgrade_gap_audit/status_latest.json"

    required = [audit, validator, test, r36]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    subprocess.run([py, "-m", "py_compile", str(audit), str(validator), str(test)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(validator),
        "--root", str(root),
        "--r36", str(r36),
        "--output", str(output),
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R41_LICO_SGRADE_GAP_AUDIT_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
