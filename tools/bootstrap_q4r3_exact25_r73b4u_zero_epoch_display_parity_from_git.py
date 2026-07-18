#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BRANCH = "q4r3-exact25-r73b4u-zero-epoch-display-parity-v1"
CORE_UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
}


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def pids() -> dict[str, str]:
    return {name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"])
            for name, unit in CORE_UNITS.items()}


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python", root / "backend/.venv/bin/python"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", default=BRANCH)
    args = parser.parse_args()
    root = args.root.resolve()
    worktree = Path(f"/tmp/q4r3_exact25_r73b4u_{args.sha[:12]}")
    runtime = root / "runtime/exact25_edge_v1/exact25_r73b4u_zero_epoch_display_parity"
    status = runtime / "status_latest.json"
    before = pids()
    if any(value in {"", "0"} for value in before.values()):
        print(f"R73B4U_HOLD=CORE_PID_INVALID:{before}")
        return 2
    if worktree.exists():
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
        shutil.rmtree(worktree, ignore_errors=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.sha], check=True)
    py = python_bin(root)
    tests = subprocess.run([py, "-m", "pytest", "-q",
                            str(worktree / "tests/test_q4r3_exact25_r73b4u_zero_epoch_display_parity.py")], check=False)
    if tests.returncode != 0:
        print("R73B4U_HOLD=TEST_FAILURE")
        return tests.returncode
    status.parent.mkdir(parents=True, exist_ok=True)
    status.unlink(missing_ok=True)
    result = subprocess.run([
        py, str(worktree / "tools/q4r3_exact25_r73b4u_zero_epoch_display_parity.py"),
        "--contract", str(worktree / "backend/contracts/ZOS_EXACT25_R73B4U_ZERO_EPOCH_DISPLAY_PARITY_v1.json"),
        "--adapter-source", str(worktree / "tools/q4r3_exact25_r73b4u_strict_display_adapter.py"),
        "--status", str(status),
    ], check=False)
    if not status.is_file():
        print(f"R73B4U_HOLD=STATUS_MISSING:rc={result.returncode}")
        return 2
    payload = json.loads(status.read_text(encoding="utf-8"))
    after = pids()
    if after != before:
        print(f"R73B4U_HOLD=CORE_PID_CHANGED:before={before}:after={after}")
        return 2
    evidence = worktree / "evidence/q4r3_exact25_r73b4u_zero_epoch_display_parity_latest.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(status, evidence)
    subprocess.run(["git", "add", str(evidence.relative_to(worktree))], cwd=worktree, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
        subprocess.run(["git", "-c", "user.name=ZEL Runtime Evidence", "-c",
                        "user.email=zel-runtime-evidence@localhost", "commit", "-m",
                        "Record R7.3B4U zero-epoch display parity evidence"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree, check=True)
    subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
    print("Q4R3_EXACT25_R73B4U_BOOTSTRAP_COMPLETE")
    print("OFFICIAL_STAGE=R7.3B4U")
    print(f"STATE={payload.get('state')}")
    print(f"BLOCKERS={json.dumps(payload.get('blockers', []), separators=(',', ':'))}")
    print(f"MUTATION_COUNT={payload.get('mutation_count', 0)}")
    print(f"ROLLBACK_PERFORMED={str(payload.get('rollback_performed', False)).lower()}")
    print(f"ALIMI_HTTP_STATUS={payload.get('endpoint_http_status', 0)}")
    print(f"ALIMI_RESIDUAL_COUNT={payload.get('alimi_residual_count')}")
    print(f"TELEGRAM_RESIDUAL_COUNT={payload.get('telegram_residual_count')}")
    print(f"ALIMI_CLOSED_COUNT={payload.get('alimi_closed_count')}")
    print(f"TELEGRAM_CLOSED_COUNT={payload.get('telegram_closed_count')}")
    print(f"ALIMI_ROWS={payload.get('alimi_rows')}")
    print(f"TELEGRAM_RECENT_ROWS={payload.get('telegram_recent_rows')}")
    print(f"ALIMI_PNL_R={payload.get('alimi_pnl_r')}")
    print(f"TELEGRAM_PNL_R={payload.get('telegram_pnl_r')}")
    print(f"FORMAL_LEDGER_CHANGE_COUNT={payload.get('formal_ledger_change_count', 0)}")
    print(f"RUNTIME_ACTIVE={str(payload.get('runtime_active', False)).lower()}")
    print(f"NEXT_STAGE={payload.get('next_stage')}")
    print("EVIDENCE=evidence/q4r3_exact25_r73b4u_zero_epoch_display_parity_latest.json")
    return 0 if payload.get("state") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
