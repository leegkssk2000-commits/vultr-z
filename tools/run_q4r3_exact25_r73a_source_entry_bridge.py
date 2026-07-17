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
    root = args.root.resolve()
    worktree = args.worktree.resolve()
    python = str(root / ".venv/bin/python") if (root / ".venv/bin/python").is_file() else sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(worktree) + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(
        [python, "-m", "pytest", "-q", str(worktree / "tests/test_q4r3_exact25_r73a_source_entry_bridge.py")],
        env=env,
        check=True,
    )
    runtime = root / "runtime/exact25_edge_v1/exact25_r73a_source_entry_bridge_prebind"
    subprocess.run(
        [
            python,
            str(worktree / "tools/q4r3_exact25_r73a_validate_source_entry_bridge.py"),
            "--contract", str(worktree / "backend/contracts/ZOS_EXACT25_R73A_SOURCE_ENTRY_BRIDGE_v1.json"),
            "--r72", str(root / "runtime/exact25_edge_v1/exact25_r72_raw_100_lane_shadow_projection/status_latest.json"),
            "--projection", str(root / "runtime/exact25_edge_v1/exact25_r72_raw_100_lane_shadow_projection/projection_latest.json"),
            "--bridge-output", str(runtime / "bridge_fixture_latest.json"),
            "--status-output", str(runtime / "status_latest.json"),
        ],
        env=env,
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
