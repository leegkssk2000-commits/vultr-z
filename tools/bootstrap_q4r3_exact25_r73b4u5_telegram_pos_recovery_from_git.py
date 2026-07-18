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
    "backend/contracts/ZOS_EXACT25_R73B4U5_TELEGRAM_POS_RECOVERY_v1.json",
    "tools/q4r3_exact25_r73b4u5_telegram_pos_recovery.py",
    "tests/test_q4r3_exact25_r73b4u5_telegram_pos_recovery.py",
)
STATUS = Path("/home/z/z/runtime/exact25_edge_v1/exact25_r73b4u5_telegram_pos_recovery/status_latest.json")


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
    target.write_text(
        output(["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{sha}:{repo_path}"]) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    py = python_bin(root)

    with tempfile.TemporaryDirectory(prefix="q4r3_exact25_r73b4u5_") as raw:
        worktree = Path(raw)
        contract = materialize(root, args.sha, worktree, FILES[0])
        tool = materialize(root, args.sha, worktree, FILES[1])
        test = materialize(root, args.sha, worktree, FILES[2])
        tool.chmod(0o755)

        subprocess.run([py, "-m", "pytest", "-q", str(test)], check=True, cwd=worktree)
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [py, str(tool), "--contract", str(contract), "--status", str(STATUS)],
            text=True,
            capture_output=True,
        )
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)

        payload = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.is_file() else {}
        print("Q4R3_EXACT25_R73B4U5_BOOTSTRAP_COMPLETE")
        print("OFFICIAL_STAGE=R7.3B4U5")
        print(f"STATE={payload.get('state')}")
        print(f"BLOCKER_COUNT={payload.get('blocker_count')}")
        print(f"MUTATION_COUNT={payload.get('mutation_count')}")
        print(f"ROLLBACK_PERFORMED={payload.get('rollback_performed')}")
        print(f"RESTORED_FROM_BACKUP={payload.get('restored_from_backup')}")
        print(f"TELEGRAM_COMMAND_COUNT={payload.get('telegram_command_count')}")
        print(f"TELEGRAM_COMPILE_OK={payload.get('telegram_compile_ok')}")
        print(f"TELEGRAM_UNIT_ACTIVE={payload.get('telegram_unit_active')}")
        print(f"TELEGRAM_STARTUP_ERROR_COUNT={payload.get('telegram_startup_error_count')}")
        print(f"SECONDARY_SOURCE_ALIAS_COUNT={payload.get('secondary_source_alias_count')}")
        print(f"CANONICAL_CLOSED_COUNT={payload.get('canonical_closed_count')}")
        print(f"CANONICAL_RECENT_ROWS={payload.get('canonical_recent_rows')}")
        print(f"CANONICAL_PNL_R={payload.get('canonical_pnl_r')}")
        print(f"VIEW_WRITER_CARD_EXACT={payload.get('view_writer_card_exact')}")
        print(f"FORMAL_LEDGER_CHANGE_COUNT={payload.get('formal_ledger_change_count')}")
        print(f"RUNTIME_ACTIVE={payload.get('runtime_active')}")
        print(f"NEXT_STAGE={payload.get('next_stage')}")
        print(f"EVIDENCE={STATUS}")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
