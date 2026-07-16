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
        wt / "tests/test_q4r3_team_advisor_r21_bot_sgrade_revalidation.py",
        wt / "tests/test_q4r3_team_advisor_r22_sbot_sgrade.py",
        wt / "tests/test_q4r3_team_advisor_r23_lbot_sgrade.py",
    ]
    validator = wt / "tools/q4r3_team_advisor_r23_validate_lbot_sgrade.py"
    r21 = root / "runtime/exact25_edge_v1/team_advisor_r21_bot_sgrade_revalidation/status_latest.json"
    r22 = root / "runtime/exact25_edge_v1/team_advisor_r22_sbot_sgrade/status_latest.json"
    contract = wt / "config/q4r3_lbot_sgrade_contract_v1.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r23_lbot_sgrade/status_latest.json"
    required = [
        *tests, validator, r21, r22, contract,
        wt / "canonical/bots/lbot.py",
        wt / "canonical/bots/sbot.py",
        wt / "canonical/bots/contracts.py",
        wt / "canonical/bots/base.py",
        wt / "tools/q4r3_team_advisor_r21_bot_sgrade_revalidation.py",
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    py_files = [str(path) for path in required if path.suffix == ".py"]
    subprocess.run([py, "-m", "py_compile", *py_files], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", *map(str, tests)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(validator),
        "--worktree", str(wt),
        "--r21", str(r21),
        "--r22", str(r22),
        "--contract", str(contract),
        "--output", str(output),
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R23_LBOT_SGRADE_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
