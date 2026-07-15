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
    test = wt / "tests/test_q4r3_team_advisor_r21_bot_sgrade_revalidation.py"
    audit = wt / "tools/q4r3_team_advisor_r21_bot_sgrade_revalidation.py"
    r10 = root / "runtime/exact25_edge_v1/team_advisor_r10_zlice_core_projection_boundary/status_latest.json"
    r11 = root / "runtime/exact25_edge_v1/team_advisor_r11_formal_ledger_outcome_join/status_latest.json"
    r12 = root / "runtime/exact25_edge_v1/team_advisor_r12_zico_minimal_fsm/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r21_bot_sgrade_revalidation/status_latest.json"
    required = [test, audit, r10, r11, r12, wt / "canonical/bots/contracts.py", wt / "canonical/bots/base.py"]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    subprocess.run([py, "-m", "py_compile", str(audit), str(test)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py, str(audit), "--worktree", str(wt), "--r10", str(r10),
        "--r11", str(r11), "--r12", str(r12), "--output", str(output)
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R21_BOT_SGRADE_REVALIDATION_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
