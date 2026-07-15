#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args()
    output = args.root / "runtime/exact25_edge_v1/team_advisor_r07_canonical_bot_packages/status_latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(args.worktree)
    tests = args.worktree / "tests/test_q4r3_team_advisor_r07_canonical_bot_packages.py"
    validator = args.worktree / "tools/q4r3_team_advisor_r07_validate_canonical_bot_packages.py"
    subprocess.run([sys.executable, "-m", "pytest", "-q", str(tests)], check=True, env=env)
    subprocess.run([
        sys.executable, str(validator),
        "--root", str(args.worktree),
        "--manifest", str(args.worktree / "canonical/bots/manifest.json"),
        "--boundary-evidence", str(args.root / "runtime/exact25_edge_v1/team_advisor_r061_bot_boundary_adjudication/status_latest.json"),
        "--output", str(output),
    ], check=True, env=env)
    print("R07_RUN_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
