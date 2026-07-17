#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def python_bin(root: Path) -> str:
    for path in (
        root / ".venv/bin/python",
        root / "venv/bin/python",
        root / "backend/.venv/bin/python",
    ):
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

    files = [
        worktree / "backend/engine/exact25_raw_100_lane_projection.py",
        worktree / "tests/test_q4r3_exact25_r72_raw_100_lane_projection.py",
        worktree / "tools/q4r3_exact25_r72_validate_raw_100_lane_projection.py",
    ]
    projection_contract = worktree / "backend/contracts/ZOS_EXACT25_RAW_100_LANE_PROJECTION_v1.json"
    matrix_contract = worktree / "backend/contracts/ZOS_EXACT25_SKILL_ADJUSTED_SHADOW_MATRIX_v1.json"
    r71 = root / "runtime/exact25_edge_v1/exact25_r71_skill_adjusted_shadow_matrix_contract/status_latest.json"
    runtime_dir = root / "runtime/exact25_edge_v1/exact25_r72_raw_100_lane_shadow_projection"
    projection_output = runtime_dir / "projection_latest.json"
    status_output = runtime_dir / "status_latest.json"

    for path in [*files, projection_contract, matrix_contract, r71]:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    subprocess.run([py, "-m", "py_compile", *map(str, files)], env=env, check=True)
    subprocess.run(
        [
            py,
            "-m",
            "pytest",
            "-q",
            str(worktree / "tests/test_q4r3_exact25_r72_raw_100_lane_projection.py"),
        ],
        env=env,
        check=True,
    )
    subprocess.run(
        [
            py,
            str(worktree / "tools/q4r3_exact25_r72_validate_raw_100_lane_projection.py"),
            "--projection-contract",
            str(projection_contract),
            "--matrix-contract",
            str(matrix_contract),
            "--r71",
            str(r71),
            "--projection-output",
            str(projection_output),
            "--status-output",
            str(status_output),
        ],
        env=env,
        check=True,
    )
    status = json.loads(status_output.read_text(encoding="utf-8"))
    projection = json.loads(projection_output.read_text(encoding="utf-8"))
    if status.get("state") != "PASS":
        raise SystemExit(f"R72_VALIDATION_HOLD={status.get('blockers', [])}")
    if projection.get("state") != "PROJECTION_READY" or projection.get("lane_template_count") != 100:
        raise SystemExit("R72_PROJECTION_NOT_READY")
    if projection.get("runtime_active") is not False:
        raise SystemExit("R72_RUNTIME_UNEXPECTEDLY_ACTIVE")

    print("Q4R3_EXACT25_R72_RAW_100_LANE_PROJECTION_COMPLETE")
    print(f"STATUS={status_output}")
    print(f"PROJECTION={projection_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
