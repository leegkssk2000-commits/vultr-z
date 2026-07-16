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
        wt / "tests/test_q4r3_team_advisor_r22_sbot_sgrade.py",
        wt / "tests/test_q4r3_team_advisor_r23_lbot_sgrade.py",
        wt / "tests/test_q4r3_team_advisor_r24_mbot_sgrade.py",
        wt / "tests/test_q4r3_team_advisor_r25_obot_sgrade.py",
        wt / "tests/test_q4r3_team_advisor_r26_four_bot_sgrade_lock.py",
    ]
    validator = wt / "tools/q4r3_team_advisor_r26_validate_four_bot_sgrade_lock.py"
    statuses = {
        "r22": root / "runtime/exact25_edge_v1/team_advisor_r22_sbot_sgrade/status_latest.json",
        "r23": root / "runtime/exact25_edge_v1/team_advisor_r23_lbot_sgrade/status_latest.json",
        "r24": root / "runtime/exact25_edge_v1/team_advisor_r24_mbot_sgrade/status_latest.json",
        "r25": root / "runtime/exact25_edge_v1/team_advisor_r25_obot_sgrade/status_latest.json",
    }
    contract = wt / "config/q4r3_four_bot_sgrade_lock_v1.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r26_four_bot_sgrade_lock/status_latest.json"
    required = [
        *tests, validator, *statuses.values(), contract,
        wt / "canonical/bots/contracts.py",
        wt / "canonical/bots/base.py",
        wt / "canonical/bots/lbot.py",
        wt / "canonical/bots/mbot.py",
        wt / "canonical/bots/obot.py",
        wt / "canonical/bots/sbot.py",
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
        py, str(validator),
        "--worktree", str(wt),
        "--r22", str(statuses["r22"]),
        "--r23", str(statuses["r23"]),
        "--r24", str(statuses["r24"]),
        "--r25", str(statuses["r25"]),
        "--contract", str(contract),
        "--output", str(output),
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R26_FOUR_BOT_SGRADE_LOCK_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
