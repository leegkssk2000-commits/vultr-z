#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    run([
        py, "-m", "pytest", "-q",
        str(args.worktree / "tests/test_q4r3_exact25_r73b4_readonly_display_parity_smoke.py"),
        str(args.worktree / "tests/test_q4r3_exact25_r73b4_metric_helpers_v3.py"),
        str(args.worktree / "tests/test_q4r3_exact25_r73b4_binding_discovery.py"),
        str(args.worktree / "tests/test_q4r3_exact25_r73b4_binding_resolver_v6.py"),
    ])
    collected = subprocess.run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b4_readonly_display_parity_smoke_v7.py"),
        "--contract", str(contract), "--parent-status", str(parent),
        "--parent-validation", str(parent_validation), "--ledger", str(ledger), "--output", str(status),
    ], check=False)
    if status.is_file():
        payload = json.loads(status.read_text(encoding="utf-8"))
        print("R73B4_DETAIL=" + json.dumps({
            "blockers": payload.get("blockers", []),
            "canonical_metrics": payload.get("canonical_metrics", {}),
            "view_url": payload.get("view_url", ""),
            "view_metrics": payload.get("view_metrics", {}),
            "view_problems": payload.get("view_problems", []),
            "view_read_errors": payload.get("view_read_errors", []),
            "telegram_artifact_path": payload.get("telegram_artifact_path", ""),
            "telegram_artifact_metrics": payload.get("telegram_artifact_metrics", {}),
            "telegram_problems": payload.get("telegram_problems", []),
            "binding_discovery": payload.get("binding_discovery", {}),
        }, sort_keys=True))
    if collected.returncode != 0:
        return collected.returncode
    validated = subprocess.run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b4_validate_readonly_display_parity_smoke.py"),
        "--contract", str(contract), "--status", str(status), "--output", str(validation),
    ], check=False)
    if validated.returncode != 0:
        return validated.returncode
    print("Q4R3_EXACT25_R73B4_READONLY_DISPLAY_PARITY_SMOKE_COMPLETE")
    print(f"STATUS={status}")
    print(f"VALIDATION={validation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
