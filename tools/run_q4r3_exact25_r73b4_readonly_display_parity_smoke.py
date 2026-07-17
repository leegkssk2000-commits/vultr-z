#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args()
    py = str(args.root / ".venv/bin/python") if (args.root / ".venv/bin/python").is_file() else sys.executable
    runtime = args.root / "runtime/exact25_edge_v1/exact25_r73b4_readonly_display_parity_smoke"
    status = runtime / "status_latest.json"
    validation = runtime / "validation_latest.json"
    contract = args.worktree / "backend/contracts/ZOS_EXACT25_R73B4_READONLY_DISPLAY_PARITY_SMOKE_v1.json"
    parent = args.root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary/status_latest.json"
    parent_validation = args.root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary/validation_latest.json"
    ledger = args.root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    run([py, "-m", "pytest", "-q", str(args.worktree / "tests/test_q4r3_exact25_r73b4_readonly_display_parity_smoke.py")])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b4_readonly_display_parity_smoke.py"),
        "--contract", str(contract), "--parent-status", str(parent),
        "--parent-validation", str(parent_validation), "--ledger", str(ledger), "--output", str(status),
    ])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b4_validate_readonly_display_parity_smoke.py"),
        "--contract", str(contract), "--status", str(status), "--output", str(validation),
    ])
    print("Q4R3_EXACT25_R73B4_READONLY_DISPLAY_PARITY_SMOKE_COMPLETE")
    print(f"STATUS={status}")
    print(f"VALIDATION={validation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
