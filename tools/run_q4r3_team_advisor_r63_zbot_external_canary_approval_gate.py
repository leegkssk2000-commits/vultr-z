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

    contract = worktree / "config/q4r3_zbot_external_canary_approval_gate_v1.json"
    r62 = root / "runtime/exact25_edge_v1/team_advisor_r62_zbot_provider_dryrun_canary/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r63_zbot_external_canary_approval_gate/status_latest.json"
    files = [
        worktree / "policy/zbot_external_canary_types.py",
        worktree / "policy/zbot_external_canary_approval.py",
        worktree / "tests/q4r3_r63_fixture.py",
        worktree / "tests/test_q4r3_team_advisor_r63_external_canary_approval_core.py",
        worktree / "tests/test_q4r3_team_advisor_r63_external_canary_approval_failclosed.py",
        worktree / "tools/q4r3_team_advisor_r63_validate_zbot_external_canary_approval_gate.py",
    ]
    for path in (*files, contract, r62):
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
        str(worktree / "tests/test_q4r3_team_advisor_r63_external_canary_approval_core.py"),
        str(worktree / "tests/test_q4r3_team_advisor_r63_external_canary_approval_failclosed.py"),
    ], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(worktree / "tools/q4r3_team_advisor_r63_validate_zbot_external_canary_approval_gate.py"),
        "--r62", str(r62),
        "--contract", str(contract),
        "--output", str(output),
    ], env=env, check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("state") != "PASS":
        raise SystemExit(f"R63_VALIDATION_HOLD={payload.get('blockers', [])}")
    if payload.get("authority", {}).get("external_canary_approved") is not False:
        raise SystemExit("R63_EXTERNAL_CANARY_APPROVAL_BOUNDARY_INVALID")
    if payload.get("report", {}).get("network_call_count") != 0:
        raise SystemExit("R63_NETWORK_CALL_COUNT_NONZERO")
    print("Q4R3_TEAM_ADVISOR_R63_ZBOT_EXTERNAL_CANARY_APPROVAL_GATE_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
