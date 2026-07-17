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

    contract = worktree / "backend/contracts/ZOS_EXACT25_SKILL_ADJUSTED_SHADOW_MATRIX_v1.json"
    registry = worktree / "backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json"
    event_contract = worktree / "backend/contracts/ZOS_SKILL_EVENT_CONTRACT_v1.json"
    engine = worktree / "backend/engine/exact25_skill_shadow_matrix_candidate.py"
    test_file = worktree / "tests/test_q4r3_exact25_r71_skill_adjusted_shadow_matrix.py"
    validator = worktree / "tools/q4r3_exact25_r71_validate_skill_adjusted_shadow_matrix.py"
    r63 = root / "runtime/exact25_edge_v1/team_advisor_r63_zbot_external_canary_approval_gate/status_latest.json"
    output = root / "runtime/exact25_edge_v1/exact25_r71_skill_adjusted_shadow_matrix_contract/status_latest.json"

    for path in (contract, registry, event_contract, engine, test_file, validator, r63):
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    subprocess.run([py, "-m", "py_compile", str(engine), str(test_file), str(validator)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test_file)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            py,
            str(validator),
            "--contract",
            str(contract),
            "--registry",
            str(registry),
            "--event-contract",
            str(event_contract),
            "--r63",
            str(r63),
            "--output",
            str(output),
        ],
        env=env,
        check=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("state") != "PASS":
        raise SystemExit(f"R71_VALIDATION_HOLD={payload.get('blockers', [])}")
    print("Q4R3_EXACT25_R71_SKILL_ADJUSTED_SHADOW_MATRIX_CONTRACT_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
