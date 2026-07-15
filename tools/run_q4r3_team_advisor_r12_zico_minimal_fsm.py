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
    wt = args.worktree.resolve()
    py = python_bin(root)
    test = wt / "tests/test_q4r3_team_advisor_r12_zico_minimal_fsm.py"
    validator = wt / "tools/q4r3_team_advisor_r12_validate_zico_minimal_fsm.py"
    r11 = root / "runtime/exact25_edge_v1/team_advisor_r11_formal_ledger_outcome_join/status_latest.json"
    manifest = wt / "canonical/zico/manifest.json"
    config = wt / "config/q4r3_r12_zico_minimal_fsm_ssot_v1.json"
    control = wt / "canonical/zico/control.py"
    output = root / "runtime/exact25_edge_v1/team_advisor_r12_zico_minimal_fsm/status_latest.json"
    required = [test, validator, r11, manifest, config, control, wt / "canonical/zico/__init__.py"]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    subprocess.run([py, "-m", "py_compile", str(control), str(validator)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py, str(validator),
        "--r11", str(r11),
        "--manifest", str(manifest),
        "--config", str(config),
        "--control-source", str(control),
        "--output", str(output),
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R12_ZICO_MINIMAL_FSM_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
