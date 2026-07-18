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

BRANCH = "q4r3-exact25-r73b4s-explicit-binding-plan-v1"
UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
    "ALIMI_PID": "zel-alimi-paper-control-api-w208.service",
    "TELEGRAM_PID": "zel-q4r3-telegram-pos-adapter-v2.service",
}


def output(args: list[str]) -> str:
    return subprocess.check_output(args, text=True).strip()


def pids() -> dict[str, str]:
    return {name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"])
            for name, unit in UNITS.items()}


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
    worktree = Path(f"/tmp/q4r3_exact25_r73b4s_{args.sha[:12]}")
    snapshot = root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json"
    parent_status = root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/prebind_status_latest.json"
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    runtime = root / "runtime/exact25_edge_v1/exact25_r73b4s_explicit_binding_plan"
    plan = runtime / "plan_latest.json"
    for path in (snapshot, parent_status, ledger):
        if not path.is_file():
            print(f"R73B4S_HOLD=REQUIRED_INPUT_MISSING:{path}")
            return 2
    parent = json.loads(parent_status.read_text(encoding="utf-8"))
    if parent.get("state") != "PASS":
        print("R73B4S_HOLD=R73B4R_NOT_PASS")
        return 2
    before_pids = pids()
    if any(value in {"", "0"} for value in before_pids.values()):
        print(f"R73B4S_HOLD=PID_INVALID:{before_pids}")
        return 2
    snapshot_hash = sha256(snapshot)
    ledger_size = ledger.stat().st_size
    ledger_prefix = sha256(ledger, ledger_size)
    if worktree.exists():
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
        shutil.rmtree(worktree, ignore_errors=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.sha], check=True)
    py = python_bin(root)
    tests = subprocess.run([py, "-m", "pytest", "-q",
                            str(worktree / "tests/test_q4r3_exact25_r73b4s_explicit_binding_plan.py")], check=False)
    if tests.returncode != 0:
        print("R73B4S_HOLD=TEST_FAILURE")
        return tests.returncode
    runtime.mkdir(parents=True, exist_ok=True)
    plan.unlink(missing_ok=True)
    run = subprocess.run([
        py, str(worktree / "tools/q4r3_exact25_r73b4s_explicit_binding_plan.py"),
        "--contract", str(worktree / "backend/contracts/ZOS_EXACT25_R73B4S_EXPLICIT_BINDING_PLAN_v1.json"),
        "--snapshot", str(snapshot), "--output", str(plan),
    ], check=False)
    if run.returncode != 0 or not plan.is_file():
        print(f"R73B4S_HOLD=PLAN_NOT_PASS:rc={run.returncode}")
        return 2
    payload = json.loads(plan.read_text(encoding="utf-8"))
    blockers: list[str] = []
    if payload.get("state") != "PASS": blockers.append("STATUS_NOT_PASS")
    if pids() != before_pids: blockers.append("PID_CHANGED")
    if sha256(snapshot) != snapshot_hash: blockers.append("SNAPSHOT_CHANGED")
    if sha256(ledger, ledger_size) != ledger_prefix: blockers.append("FORMAL_LEDGER_PREFIX_CHANGED")
    for row in payload.get("consumers", []):
        source = Path(str(row.get("source_path", "")))
        if not source.is_file() or sha256(source) != row.get("source_sha256"):
            blockers.append(f"SOURCE_CHANGED:{row.get('unit')}")
    if blockers:
        print("R73B4S_HOLD=" + ",".join(blockers))
        return 2
    evidence = worktree / "evidence/q4r3_exact25_r73b4s_explicit_binding_plan_latest.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plan, evidence)
    subprocess.run(["git", "add", str(evidence.relative_to(worktree))], cwd=worktree, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
        subprocess.run(["git", "-c", "user.name=ZEL Runtime Evidence", "-c",
                        "user.email=zel-runtime-evidence@localhost", "commit", "-m",
                        "Record R7.3B4S explicit binding plan evidence"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree, check=True)
    subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
    print("Q4R3_EXACT25_R73B4S_BOOTSTRAP_PASS")
    print("OFFICIAL_STAGE=R7.3B4S")
    for key, value in before_pids.items(): print(f"{key}={value}")
    for key in ("consumer_count", "active_consumer_count", "source_resolved_count", "rollback_ready_count",
                "current_snapshot_binding_count", "current_formal_ledger_binding_count", "mutation_count"):
        print(f"{key.upper()}={payload.get(key)}")
    print("NEXT_STAGE=R7.3B4T_EXPLICIT_BINDING_CANARY")
    print("EVIDENCE=evidence/q4r3_exact25_r73b4s_explicit_binding_plan_latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
