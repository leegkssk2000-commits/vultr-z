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
    owner = worktree / "canonical/lico.py"
    contract = worktree / "config/q4r3_lico_source_consensus_contract_v1.json"
    test = worktree / "tests/test_q4r3_team_advisor_r42_lico_canonical_source_consensus.py"
    validator = worktree / "tools/q4r3_team_advisor_r42_validate_lico_canonical_source_consensus.py"
    r41 = root / "runtime/exact25_edge_v1/team_advisor_r41_lico_sgrade_gap_audit/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r42_lico_canonical_source_consensus/status_latest.json"

    required = [owner, contract, test, validator, r41]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    subprocess.run([py, "-m", "py_compile", str(owner), str(test), str(validator)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py,
        str(validator),
        "--worktree", str(worktree),
        "--r41", str(r41),
        "--contract", str(contract),
        "--output", str(output),
    ], env=env, check=True)

    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("state") != "PASS":
        raise SystemExit(f"R42_VALIDATION_HOLD={payload.get('blockers', [])}")

    print("Q4R3_TEAM_ADVISOR_R42_LICO_CANONICAL_SOURCE_CONSENSUS_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
