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
    "backend/contracts/ZOS_EXACT25_R73B4W_ZERO_EPOCH_SHADOW_START_CANARY_v1.json",
    "tools/q4r3_exact25_r73b4w_zero_epoch_shadow_start_canary.py",
    "tests/test_q4r3_exact25_r73b4w_zero_epoch_shadow_start_canary.py",
)
STATUS = Path("/home/z/z/runtime/exact25_edge_v1/exact25_r73b4w_zero_epoch_shadow_start_canary/status_latest.json")


def output(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def pybin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python", root / "backend/.venv/bin/python"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


def materialize(root: Path, sha: str, wt: Path, repo_path: str) -> Path:
    target = wt / repo_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output(["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{sha}:{repo_path}"]) + "\n", encoding="utf-8")
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("/home/z/z"))
    ap.add_argument("--sha", required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    py = pybin(root)
    with tempfile.TemporaryDirectory(prefix="q4r3_exact25_r73b4w_") as raw:
        wt = Path(raw)
        contract = materialize(root, args.sha, wt, FILES[0])
        tool = materialize(root, args.sha, wt, FILES[1])
        test = materialize(root, args.sha, wt, FILES[2])
        tool.chmod(0o755)
        subprocess.run([py, "-m", "pytest", "-q", str(test)], check=True, cwd=wt)
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([py, str(tool), "--contract", str(contract), "--status", str(STATUS)], text=True, capture_output=True)
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        payload = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.is_file() else {}
        print("Q4R3_EXACT25_R73B4W_BOOTSTRAP_COMPLETE")
        print("OFFICIAL_STAGE=R7.3B4W")
        for key in (
            "state", "blocker_count", "mutation_count", "rollback_performed",
            "resolved_shadow_unit_count", "shadow_unit", "unit_active_after_start",
            "shadow_runtime_error_count", "runtime_active", "formal_ledger_bound",
            "formal_ledger_change_count", "order_blocked", "execution_none",
            "paper_open", "live_open", "epoch_closed", "pnl_r",
            "telegram_closed_count", "telegram_pnl_r", "alimi_http_status",
            "rollback_ready", "next_stage"
        ):
            print(f"{key.upper()}={payload.get(key)}")
        print(f"EVIDENCE={STATUS}")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
