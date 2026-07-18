#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BRANCH = "q4r3-exact25-r73b4r-shadow-snapshot-prebind-v1"
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


def sha256(path: Path, limit: int | None = None) -> str:
    digest = hashlib.sha256()
    remaining = limit
    with path.open("rb") as handle:
        while True:
            size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
            if size <= 0:
                break
            chunk = handle.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


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
    worktree = Path(f"/tmp/q4r3_exact25_r73b4r_{args.sha[:12]}")
    runtime = root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot"
    snapshot = runtime / "latest.json"
    status = runtime / "prebind_status_latest.json"
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    parent = root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary/status_latest.json"
    validation = root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary/validation_latest.json"
    for path in (ledger, parent, validation):
        if not path.is_file():
            print(f"R73B4R_HOLD=REQUIRED_INPUT_MISSING:{path}")
            return 2
    before_pids = pids()
    if any(value in {"", "0"} for value in before_pids.values()):
        print(f"R73B4R_HOLD=CORE_PID_INVALID:{before_pids}")
        return 2
    ledger_size = ledger.stat().st_size
    ledger_prefix = sha256(ledger, ledger_size)
    if worktree.exists():
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
        shutil.rmtree(worktree, ignore_errors=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.sha], check=True)
    py = python_bin(root)
    test = subprocess.run([py, "-m", "pytest", "-q",
                           str(worktree / "tests/test_q4r3_exact25_r73b4r_shadow_snapshot_prebind.py")], check=False)
    if test.returncode != 0:
        print("R73B4R_HOLD=TEST_FAILURE")
        return test.returncode
    status.unlink(missing_ok=True)
    run = subprocess.run([
        py, str(worktree / "tools/q4r3_exact25_r73b4r_shadow_snapshot_prebind.py"),
        "--contract", str(worktree / "backend/contracts/ZOS_EXACT25_R73B4R_SHADOW_SNAPSHOT_PREBIND_v1.json"),
        "--parent-status", str(parent), "--parent-validation", str(validation),
        "--snapshot", str(snapshot), "--status", str(status),
    ], check=False)
    if run.returncode != 0 or not status.is_file():
        print(f"R73B4R_HOLD=PREBIND_NOT_PASS:rc={run.returncode}")
        return 2
    payload = json.loads(status.read_text(encoding="utf-8"))
    snap = json.loads(snapshot.read_text(encoding="utf-8"))
    after_pids = pids()
    blockers: list[str] = []
    if payload.get("state") != "PASS": blockers.append("STATUS_NOT_PASS")
    if snap.get("owner_id") != "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER": blockers.append("OWNER_INVALID")
    if snap.get("closed_count") != 0 or snap.get("sample_count") != 0: blockers.append("ZERO_EPOCH_INVALID")
    if snap.get("formal_ledger_bound") is not False: blockers.append("FORMAL_LEDGER_BOUND")
    if after_pids != before_pids: blockers.append("CORE_PID_CHANGED")
    if sha256(ledger, ledger_size) != ledger_prefix: blockers.append("FORMAL_LEDGER_PREFIX_CHANGED")
    if blockers:
        print("R73B4R_HOLD=" + ",".join(blockers))
        return 2
    evidence = {
        "evidence/q4r3_exact25_r73b4r_shadow_snapshot_prebind_latest.json": snapshot,
        "evidence/q4r3_exact25_r73b4r_shadow_snapshot_prebind_status_latest.json": status,
    }
    for relative, source in evidence.items():
        destination = worktree / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    subprocess.run(["git", "add", *evidence.keys()], cwd=worktree, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
        subprocess.run(["git", "-c", "user.name=ZEL Runtime Evidence", "-c",
                        "user.email=zel-runtime-evidence@localhost", "commit", "-m",
                        "Record R7.3B4R shadow snapshot prebind evidence"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree, check=True)
    subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
    print("Q4R3_EXACT25_R73B4R_BOOTSTRAP_PASS")
    print("OFFICIAL_STAGE=R7.3B4R")
    print("OWNER_COUNT=1")
    print("SNAPSHOT_COUNT=1")
    print("EPOCH_SAMPLE_COUNT=0")
    print("EPOCH_CLOSED_COUNT=0")
    print("FORMAL_LEDGER_BOUND=false")
    print("RUNTIME_ACTIVE=false")
    print("NEXT_STAGE=R7.3B4S_ALIMI_TELEGRAM_EXPLICIT_BINDING_PLAN")
    print("EVIDENCE=evidence/q4r3_exact25_r73b4r_shadow_snapshot_prebind_latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
