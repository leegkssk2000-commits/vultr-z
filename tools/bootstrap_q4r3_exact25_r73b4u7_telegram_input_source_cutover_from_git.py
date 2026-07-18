#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FILES = (
    "backend/contracts/ZOS_EXACT25_R73B4U7_TELEGRAM_INPUT_SOURCE_CUTOVER_v1.json",
    "tools/q4r3_exact25_r73b4u7_telegram_input_source_cutover_v2.py",
    "tests/test_q4r3_exact25_r73b4u7_telegram_input_source_cutover_v2.py",
)
STATUS = Path("/home/z/z/runtime/exact25_edge_v1/exact25_r73b4u7_telegram_input_source_cutover/status_latest.json")


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python", root / "backend/.venv/bin/python"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


def materialize(root: Path, sha: str, worktree: Path, repo_path: str) -> Path:
    target = worktree / repo_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output(["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{sha}:{repo_path}"]) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    py = python_bin(root)

    with tempfile.TemporaryDirectory(prefix="q4r3_exact25_r73b4u7_") as raw:
        worktree = Path(raw)
        contract = materialize(root, args.sha, worktree, FILES[0])
        tool = materialize(root, args.sha, worktree, FILES[1])
        test = materialize(root, args.sha, worktree, FILES[2])
        tool.chmod(0o755)
        subprocess.run([py, "-m", "pytest", "-q", str(test)], check=True, cwd=worktree)
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([py, str(tool), "--contract", str(contract), "--status", str(STATUS)], text=True, capture_output=True)
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        payload = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.is_file() else {}
        print("Q4R3_EXACT25_R73B4U7_BOOTSTRAP_COMPLETE")
        print("OFFICIAL_STAGE=R7.3B4U7")
        for key in (
            "state", "blocker_count", "mutation_count", "rollback_performed",
            "telegram_source_change_count", "telegram_command_count", "telegram_compile_ok",
            "telegram_unit_active", "telegram_runtime_error_count", "legacy_input_path_count",
            "legacy_input_cutover_count", "canonical_closed_count", "canonical_recent_rows",
            "canonical_last12_r", "canonical_winrate_pct", "canonical_ev_r", "canonical_pnl_r",
            "canonical_last_close", "formal_ledger_change_count", "runtime_active", "next_stage"
        ):
            print(f"{key.upper()}={payload.get(key)}")
        print(f"EVIDENCE={STATUS}")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
