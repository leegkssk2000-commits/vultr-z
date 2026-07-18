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
    "backend/contracts/ZOS_EXACT25_R73B4U8_TELEGRAM_VISIBLE_RENDER_SINGLE_SOURCE_v1.json",
    "tools/q4r3_exact25_r73b4u8_visible_patch.py",
    "tests/test_q4r3_exact25_r73b4u8_visible_patch.py",
)
STATUS = Path("/home/z/z/runtime/exact25_edge_v1/exact25_r73b4u8_visible_patch/status_latest.json")


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).rstrip("\n")


def interpreter(root: Path) -> str:
    for candidate in (root / ".venv/bin/python", root / "venv/bin/python", root / "backend/.venv/bin/python"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def materialize(root: Path, sha: str, directory: Path, repo_path: str) -> Path:
    target = directory / repo_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output(["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{sha}:{repo_path}"]) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    py = interpreter(root)
    with tempfile.TemporaryDirectory(prefix="q4r3_exact25_r73b4u8_") as raw:
        worktree = Path(raw)
        contract = materialize(root, args.sha, worktree, FILES[0])
        tool = materialize(root, args.sha, worktree, FILES[1])
        test = materialize(root, args.sha, worktree, FILES[2])
        tool.chmod(0o755)
        subprocess.run([py, "-m", "pytest", "-q", str(test)], cwd=worktree, check=True)
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([py, str(tool), "--contract", str(contract), "--status", str(STATUS)], text=True, capture_output=True)
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        data = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.is_file() else {}
        print("Q4R3_EXACT25_R73B4U8_BOOTSTRAP_COMPLETE")
        print("OFFICIAL_STAGE=R7.3B4U8")
        for key in (
            "state", "blocker_count", "mutation_count", "rollback_performed",
            "telegram_source_change_count", "telegram_assignment_patch_count",
            "telegram_path_patch_count", "telegram_local_fallback_count",
            "telegram_compile_ok", "telegram_unit_active", "telegram_runtime_error_count",
            "canonical_closed_count", "canonical_recent_rows", "canonical_last12_r",
            "canonical_winrate_pct", "canonical_ev_r", "canonical_pnl_r",
            "canonical_last_close", "formal_ledger_change_count", "runtime_active", "next_stage"):
            print(f"{key.upper()}={data.get(key)}")
        print(f"EVIDENCE={STATUS}")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
