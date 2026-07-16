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
    primary_test = worktree / "tests/test_q4r3_team_advisor_r54_zbot_response_arbitration_receipt.py"
    scalar_test = worktree / "tests/test_q4r3_team_advisor_r54_zbot_response_bool_regression.py"
    files = [
        worktree / "canonical/zbot.py",
        worktree / "policy/zbot_prompt.py",
        worktree / "policy/zbot_budget.py",
        worktree / "policy/zbot_reliability.py",
        worktree / "policy/zbot_idempotency.py",
        worktree / "policy/zbot_response.py",
        worktree / "policy/zbot_arbitration.py",
        worktree / "policy/zbot_receipt.py",
        primary_test,
        scalar_test,
        worktree / "tools/q4r3_team_advisor_r54_validate_zbot_response_arbitration_receipt.py",
    ]
    contract = worktree / "config/q4r3_zbot_response_arbitration_receipt_v1.json"
    r53 = root / "runtime/exact25_edge_v1/team_advisor_r53_zbot_reliability_budget_prompt_idempotency/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r54_zbot_response_arbitration_receipt/status_latest.json"
    for path in [*files, contract, r53]:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    subprocess.run([py, "-m", "py_compile", *map(str, files)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(primary_test), str(scalar_test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(worktree / "tools/q4r3_team_advisor_r54_validate_zbot_response_arbitration_receipt.py"),
        "--r53", str(r53),
        "--contract", str(contract),
        "--output", str(output),
    ], env=env, check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("state") != "PASS":
        raise SystemExit(f"R54_VALIDATION_HOLD={payload.get('blockers', [])}")
    print("Q4R3_TEAM_ADVISOR_R54_ZBOT_RESPONSE_ARBITRATION_RECEIPT_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
