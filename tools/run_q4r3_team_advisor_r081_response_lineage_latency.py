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
    worktree = args.worktree.resolve()
    py = python_bin(root)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)

    sources = [
        worktree / "canonical/bots/contracts.py",
        worktree / "canonical/bots/base.py",
        worktree / "canonical/teams/binding.py",
        worktree / "tools/q4r3_team_advisor_r081_validate_response_lineage_latency.py",
    ]
    tests = [
        worktree / "tests/test_q4r3_team_advisor_r07_canonical_bot_packages.py",
        worktree / "tests/test_q4r3_team_advisor_r08_team_bot_typed_binding.py",
    ]
    for required in (*sources, *tests):
        if not required.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={required}")

    subprocess.run([py, "-m", "py_compile", *map(str, sources)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", *map(str, tests)], env=env, check=True)

    output = root / "runtime/exact25_edge_v1/team_advisor_r081_response_lineage_latency/status_latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(worktree / "tools/q4r3_team_advisor_r081_validate_response_lineage_latency.py"),
        "--output", str(output),
    ], env=env, check=True)

    print("Q4R3_TEAM_ADVISOR_R081_RESPONSE_LINEAGE_LATENCY_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
