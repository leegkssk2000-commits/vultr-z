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
    model = worktree / "canonical/lico_risk.py"
    contract = worktree / "config/q4r3_lico_fee_funding_liquidation_stress_contract_v1.json"
    test = worktree / "tests/test_q4r3_team_advisor_r45_lico_fee_funding_liquidation_stress.py"
    validator = worktree / "tools/q4r3_team_advisor_r45_validate_lico_fee_funding_liquidation_stress.py"
    r44 = root / "runtime/exact25_edge_v1/team_advisor_r44_lico_execution_cost_realistic_fill/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r45_lico_fee_funding_liquidation_stress/status_latest.json"

    for path in (model, contract, test, validator, r44):
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    subprocess.run([py, "-m", "py_compile", str(model), str(test), str(validator)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(validator),
        "--worktree", str(worktree),
        "--r44", str(r44),
        "--contract", str(contract),
        "--output", str(output),
    ], env=env, check=True)

    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("state") != "PASS":
        raise SystemExit(f"R45_VALIDATION_HOLD={payload.get('blockers', [])}")

    print("Q4R3_TEAM_ADVISOR_R45_LICO_FEE_FUNDING_LIQUIDATION_STRESS_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
