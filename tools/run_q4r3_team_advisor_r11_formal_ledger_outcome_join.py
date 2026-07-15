#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    test = wt / "tests/test_q4r3_team_advisor_r11_formal_ledger_outcome_join.py"
    module = wt / "canonical/zlice/outcome_join.py"
    validator = wt / "tools/q4r3_team_advisor_r11_validate_formal_ledger_outcome_join.py"
    config = wt / "config/q4r3_r11_formal_ledger_outcome_join_ssot_v1.json"
    r10 = root / "runtime/exact25_edge_v1/team_advisor_r10_zlice_core_projection_boundary/status_latest.json"
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    output = root / "runtime/exact25_edge_v1/team_advisor_r11_formal_ledger_outcome_join/status_latest.json"
    for path in (test, module, validator, config, r10, ledger):
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")
    r10_value = json.loads(r10.read_text(encoding="utf-8"))
    if r10_value.get("state") != "PASS":
        raise SystemExit("R1_0_ZLICE_BOUNDARY_NOT_PASS")
    config_value = json.loads(config.read_text(encoding="utf-8"))
    if config_value.get("official_stage") != "R1.1":
        raise SystemExit("R1_1_STAGE_CONTRACT_INVALID")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(wt)
    subprocess.run([py, "-m", "py_compile", str(module), str(validator)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([py, str(validator), "--ledger", str(ledger), "--output", str(output)], env=env, check=True)
    result = json.loads(output.read_text(encoding="utf-8"))
    if result.get("state") != "PASS" or result.get("official_stage") != "R1.1":
        raise SystemExit(f"R1_1_OUTPUT_GATE_FAIL={result}")
    print("Q4R3_TEAM_ADVISOR_R1_1_OUTCOME_JOIN_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
