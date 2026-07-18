#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BRANCH = "q4r3-exact25-r73b4s-explicit-binding-plan-v1"
CORE_UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
}


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def pids() -> dict[str, str]:
    return {key: output(["systemctl", "show", unit, "-p", "MainPID", "--value"])
            for key, unit in CORE_UNITS.items()}


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
    worktree = Path(f"/tmp/q4r3_exact25_r73b4s3_{args.sha[:12]}")
    runtime = root / "runtime/exact25_edge_v1/exact25_r73b4s3_alimi_telegram_binding_plan"
    status = runtime / "status_latest.json"
    snapshot = root / "runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json"
    parent = root / "runtime/exact25_edge_v1/exact25_r73b4s2_alimi_endpoint_origin_resolver/status_latest.json"
    caddy = Path("/etc/caddy/Caddyfile")
    telegram = Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py")
    for path in (snapshot, parent, caddy, telegram):
        if not path.is_file():
            print(f"R73B4S3_HOLD=REQUIRED_INPUT_MISSING:{path}")
            return 2
    before = pids()
    if any(value in {"", "0"} for value in before.values()):
        print(f"R73B4S3_HOLD=CORE_PID_INVALID:{before}")
        return 2
    if worktree.exists():
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
        shutil.rmtree(worktree, ignore_errors=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.sha], check=True)
    py = python_bin(root)
    tests = subprocess.run([
        py, "-m", "pytest", "-q",
        str(worktree / "tests/test_q4r3_exact25_r73b4s3_alimi_telegram_binding_plan.py"),
    ], check=False)
    if tests.returncode != 0:
        print("R73B4S3_HOLD=TEST_FAILURE")
        return tests.returncode
    status.unlink(missing_ok=True)
    run = subprocess.run([
        py, str(worktree / "tools/q4r3_exact25_r73b4s3_alimi_telegram_binding_plan.py"),
        "--contract", str(worktree / "backend/contracts/ZOS_EXACT25_R73B4S3_ALIMI_TELEGRAM_BINDING_PLAN_v1.json"),
        "--snapshot", str(snapshot),
        "--parent", str(parent),
        "--caddy", str(caddy),
        "--telegram", str(telegram),
        "--output", str(status),
    ], check=False)
    if not status.is_file():
        print(f"R73B4S3_HOLD=STATUS_MISSING:rc={run.returncode}")
        return 2
    payload = json.loads(status.read_text(encoding="utf-8"))
    after = pids()
    blockers: list[str] = []
    if after != before:
        blockers.append("CORE_PID_CHANGED")
    if payload.get("read_only") is not True or payload.get("mutation_count") != 0:
        blockers.append("READ_ONLY_CONTRACT_BROKEN")
    if blockers:
        print("R73B4S3_HOLD=" + ",".join(blockers))
        return 2
    evidence = worktree / "evidence/q4r3_exact25_r73b4s3_alimi_telegram_binding_plan_latest.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(status, evidence)
    subprocess.run(["git", "add", str(evidence.relative_to(worktree))], cwd=worktree, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
        subprocess.run([
            "git", "-c", "user.name=ZEL Runtime Evidence", "-c",
            "user.email=zel-runtime-evidence@localhost", "commit", "-m",
            "Record R7.3B4S3 binding plan evidence",
        ], cwd=worktree, check=True)
        subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree, check=True)
    subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
    print("Q4R3_EXACT25_R73B4S3_BOOTSTRAP_COMPLETE")
    print("OFFICIAL_STAGE=R7.3B4S3")
    print(f"STATE={payload.get('state')}")
    print(f"BLOCKERS={json.dumps(payload.get('blockers', []), separators=(',', ':'))}")
    print(f"PLANNED_ADAPTER_COUNT={payload.get('planned_adapter_count')}")
    print(f"PLANNED_OUTPUT_COUNT={payload.get('planned_output_count')}")
    print(f"ALIMI_ROUTE_ANCHOR_COUNT={payload.get('alimi_plan', {}).get('anchor_count')}")
    print(f"TELEGRAM_COMMAND_COUNT={payload.get('telegram_plan', {}).get('command_count')}")
    print(f"ROLLBACK_READY_COUNT={payload.get('rollback_ready_count')}")
    print("MUTATION_COUNT=0")
    print(f"NEXT_STAGE={payload.get('next_stage')}")
    print("EVIDENCE=evidence/q4r3_exact25_r73b4s3_alimi_telegram_binding_plan_latest.json")
    return 0 if payload.get("state") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
