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
    runtime = args.root / "runtime/exact25_edge_v1/exact25_r73b0_display_binding_residue_audit"
    audit = runtime / "inventory_latest.json"
    status = runtime / "status_latest.json"
    r73a = args.root / "runtime/exact25_edge_v1/exact25_r73a_source_entry_bridge_prebind/status_latest.json"
    run([
        py, "-m", "pytest", "-q",
        str(args.worktree / "tests/test_q4r3_exact25_r73b0_display_binding_residue_audit.py"),
        str(args.worktree / "tests/test_q4r3_exact25_r73b0_r73a_schema_normalization.py"),
    ])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b0_audit_display_binding_residue_v4.py"),
        "--root", str(args.root), "--r73a", str(r73a), "--output", str(audit),
    ])
    run([
        py, str(args.worktree / "tools/q4r3_exact25_r73b0_validate_display_binding_residue_audit.py"),
        "--contract", str(args.worktree / "backend/contracts/ZOS_EXACT25_R73B0_DISPLAY_BINDING_RESIDUE_AUDIT_v1.json"),
        "--audit", str(audit), "--output", str(status),
    ])
    print("Q4R3_EXACT25_R73B0_DISPLAY_BINDING_RESIDUE_AUDIT_COMPLETE")
    print(f"STATUS={status}")
    print(f"INVENTORY={audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
