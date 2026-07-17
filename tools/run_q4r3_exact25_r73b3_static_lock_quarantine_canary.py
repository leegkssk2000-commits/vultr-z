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
    parser.add_argument("--approval-token", required=True)
    args = parser.parse_args()

    py = str(args.root / ".venv/bin/python") if (args.root / ".venv/bin/python").is_file() else sys.executable
    runtime = args.root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary"
    status = runtime / "status_latest.json"
    validation = runtime / "validation_latest.json"
    contract = args.worktree / "backend/contracts/ZOS_EXACT25_R73B3_STATIC_LOCK_QUARANTINE_CANARY_v1.json"
    manifest = args.root / "runtime/exact25_edge_v1/exact25_r73b2_minimal_isolation_rollback_plan/plan_latest.json"
    ledger = args.root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"

    run([py, "-m", "pytest", "-q", str(args.worktree / "tests/test_q4r3_exact25_r73b3_static_lock_quarantine_canary.py")])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b3_static_lock_quarantine_canary.py"),
        "--contract", str(contract), "--manifest", str(manifest), "--ledger", str(ledger),
        "--status", str(status), "--approval-token", args.approval_token,
    ])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b3_validate_static_lock_quarantine_canary.py"),
        "--contract", str(contract), "--status", str(status), "--output", str(validation),
    ])
    print("Q4R3_EXACT25_R73B3_STATIC_LOCK_QUARANTINE_CANARY_COMPLETE")
    print(f"STATUS={status}")
    print(f"VALIDATION={validation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
