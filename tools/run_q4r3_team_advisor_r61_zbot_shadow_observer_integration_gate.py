#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    worktree = args.worktree.resolve()
    py = python_bin(root)
    files = [
        worktree / "canonical/zbot.py",
        worktree / "policy/zbot_shadow_types.py",
        worktree / "policy/zbot_shadow_validation.py",
        worktree / "policy/zbot_shadow_router.py",
        worktree / "tests/test_q4r3_team_advisor_r61_shadow_observer_core.py",
        worktree / "tests/test_q4r3_team_advisor_r61_shadow_observer_failclosed.py",
        worktree / "tools/q4r3_team_advisor_r61_validate_zbot_shadow_observer_integration_gate.py",
    ]
    contract = worktree / "config/q4r3_zbot_shadow_observer_integration_gate_v1.json"
    r55 = root / "runtime/exact25_edge_v1/team_advisor_r55_zbot_attribution_drift_sgrade_lock/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r61_zbot_shadow_observer_integration_gate/status_latest.json"
    for path in [*files, contract, r55]:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    subprocess.run([py, "-m", "py_compile", *map(str, files)], env=env, check=True)
    subprocess.run([
        py,
        "-m",
        "pytest",
        "-q",
        str(worktree / "tests/test_q4r3_team_advisor_r61_shadow_observer_core.py"),
        str(worktree / "tests/test_q4r3_team_advisor_r61_shadow_observer_failclosed.py"),
    ], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(worktree / "tools/q4r3_team_advisor_r61_validate_zbot_shadow_observer_integration_gate.py"),
        "--r55", str(r55),
        "--contract", str(contract),
        "--output", str(output),
    ], env=env, check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("state") != "PASS":
        raise SystemExit(f"R61_VALIDATION_HOLD={payload.get('blockers', [])}")
    print("Q4R3_TEAM_ADVISOR_R61_ZBOT_SHADOW_OBSERVER_INTEGRATION_GATE_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
