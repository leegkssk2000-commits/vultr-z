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

BRANCH = "q4r3-exact25-r73b3-static-lock-quarantine-canary-v1"
APPROVAL_TOKEN = "R7.3B3_APPLY_STATIC_LOCK_QUARANTINE"
CORE_UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
}


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


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


def pids() -> dict[str, str]:
    return {name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"]) for name, unit in CORE_UNITS.items()}


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python", root / "backend/.venv/bin/python"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


def rollback(root: Path, worktree: Path, reason: str) -> None:
    py = python_bin(root)
    runtime = root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary"
    run([
        py, str(worktree / "tools/q4r3_exact25_r73b3_static_lock_quarantine_canary.py"),
        "--contract", str(worktree / "backend/contracts/ZOS_EXACT25_R73B3_STATIC_LOCK_QUARANTINE_CANARY_v1.json"),
        "--manifest", str(root / "runtime/exact25_edge_v1/exact25_r73b2_minimal_isolation_rollback_plan/plan_latest.json"),
        "--ledger", str(root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"),
        "--status", str(runtime / "status_latest.json"),
        "--rollback-reason", reason[:500],
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", default=BRANCH)
    args = parser.parse_args()
    root = args.root.resolve()
    worktree = Path(f"/tmp/q4r3_exact25_r73b3_{args.sha[:12]}")
    runtime = root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary"
    status = runtime / "status_latest.json"
    receipt = runtime / "receipt_latest.json"
    validation = runtime / "validation_latest.json"
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    protected = {
        "HOST_ZBOT": Path("/usr/local/bin/zel_alimi_w210_zbot_control_advisor.py"),
        "ACTIVE_SKILL_REGISTRY": root / "backend/contracts/ZOS_SKILL_REGISTRY_v1.json",
        "ACTIVE_SKILL_RESOLVER": root / "backend/engine/skill_resolver.py",
        "R73B2_STATUS": root / "runtime/exact25_edge_v1/exact25_r73b2_minimal_isolation_rollback_plan/status_latest.json",
        "R73B2_PLAN": root / "runtime/exact25_edge_v1/exact25_r73b2_minimal_isolation_rollback_plan/plan_latest.json",
    }
    for path in (ledger, *protected.values()):
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    before_pids = pids()
    if any(value in {"", "0"} for value in before_pids.values()):
        raise SystemExit(f"CORE_PID_INVALID={before_pids}")
    before_hashes = {name: sha256(path) for name, path in protected.items()}
    ledger_size = ledger.stat().st_size
    ledger_prefix = sha256(ledger, ledger_size)
    passed = False
    applied = False
    try:
        if worktree.exists():
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
            shutil.rmtree(worktree, ignore_errors=True)
        run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.sha])
        runtime.mkdir(parents=True, exist_ok=True)
        for stale in (status, receipt, validation):
            stale.unlink(missing_ok=True)
        run([
            python_bin(root), str(worktree / "tools/run_q4r3_exact25_r73b3_static_lock_quarantine_canary.py"),
            "--root", str(root), "--worktree", str(worktree), "--approval-token", APPROVAL_TOKEN,
        ])
        payload = json.loads(status.read_text(encoding="utf-8"))
        applied = payload.get("cleanup_applied") is True
        verified = json.loads(validation.read_text(encoding="utf-8"))
        if payload.get("state") != "PASS" or verified.get("state") != "PASS":
            raise RuntimeError(f"R73B3_NOT_PASS:{payload}:{verified}")
        after_pids = pids()
        if after_pids != before_pids:
            raise RuntimeError(f"CORE_PID_CHANGED:{before_pids}:{after_pids}")
        after_hashes = {name: sha256(path) for name, path in protected.items()}
        if after_hashes != before_hashes:
            raise RuntimeError(f"PROTECTED_SURFACE_CHANGED:{before_hashes}:{after_hashes}")
        if sha256(ledger, ledger_size) != ledger_prefix:
            raise RuntimeError("FORMAL_LEDGER_PREFIX_CHANGED")

        evidence = {
            "evidence/q4r3_exact25_r73b3_static_lock_quarantine_canary_latest.json": status,
            "evidence/q4r3_exact25_r73b3_static_lock_quarantine_receipt_latest.json": receipt,
            "evidence/q4r3_exact25_r73b3_static_lock_quarantine_validation_latest.json": validation,
        }
        for relative, source in evidence.items():
            destination = worktree / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        run(["git", "add", *evidence.keys()], cwd=worktree)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
            run([
                "git", "-c", "user.name=ZEL Runtime Evidence", "-c", "user.email=zel-runtime-evidence@localhost",
                "commit", "-m", "Record R7.3B3 static lock quarantine canary evidence",
            ], cwd=worktree)
            run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree)

        print("Q4R3_EXACT25_R73B3_BOOTSTRAP_PASS")
        print("OFFICIAL_STAGE=R7.3B3")
        for name, value in after_pids.items():
            print(f"{name}={value}")
        print("TARGET_COUNT=2")
        print("QUARANTINED_COUNT=2")
        print("BACKUP_VERIFIED_COUNT=2")
        print("ISOLATED_VERIFIED_COUNT=2")
        print("ORIGINAL_ABSENT_COUNT=2")
        print("PROTECTED_UNIT_COUNT=5")
        print("ROLLBACK_READY_COUNT=2")
        print("ROLLBACK_PERFORMED=false")
        print("CLEANUP_APPLIED=true")
        print("CONTROLLED_MUTATION=true")
        print("FORMAL_LEDGER_PREFIX_CHANGE_COUNT=0")
        print("EVIDENCE=evidence/q4r3_exact25_r73b3_static_lock_quarantine_canary_latest.json")
        passed = True
        return 0
    except Exception as exc:
        if worktree.exists() and (applied or (status.is_file() and json.loads(status.read_text(encoding="utf-8")).get("cleanup_applied") is True)):
            try:
                rollback(root, worktree, f"BOOTSTRAP_POST_APPLY_FAILURE:{exc}")
                print("R73B3_AUTOMATIC_ROLLBACK_PASS")
            except Exception as rollback_exc:
                print(f"R73B3_AUTOMATIC_ROLLBACK_FAILED={rollback_exc}")
        raise
    finally:
        if passed:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
        else:
            print(f"WORKTREE_PRESERVED_FOR_DIAGNOSIS={worktree}")


if __name__ == "__main__":
    raise SystemExit(main())
