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

BRANCH = "q4r3-exact25-r73b4-readonly-display-parity-smoke-v1"
CORE_UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
}


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python", root / "backend/.venv/bin/python"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


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
    return {name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"])
            for name, unit in CORE_UNITS.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", default=BRANCH)
    args = parser.parse_args()
    root = args.root.resolve()
    worktree = Path(f"/tmp/q4r3_exact25_r73b4_{args.sha[:12]}")
    runtime = root / "runtime/exact25_edge_v1/exact25_r73b4_readonly_display_parity_smoke"
    status = runtime / "status_latest.json"
    validation = runtime / "validation_latest.json"
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    protected = {
        "HOST_ZBOT": Path("/usr/local/bin/zel_alimi_w210_zbot_control_advisor.py"),
        "ACTIVE_SKILL_REGISTRY": root / "backend/contracts/ZOS_SKILL_REGISTRY_v1.json",
        "ACTIVE_SKILL_RESOLVER": root / "backend/engine/skill_resolver.py",
        "R73B3_STATUS": root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary/status_latest.json",
        "R73B3_VALIDATION": root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary/validation_latest.json",
        "R73B3_RECEIPT": root / "runtime/exact25_edge_v1/exact25_r73b3_static_lock_quarantine_canary/receipt_latest.json",
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
    try:
        if worktree.exists():
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
            shutil.rmtree(worktree, ignore_errors=True)
        runtime.mkdir(parents=True, exist_ok=True)
        status.unlink(missing_ok=True)
        validation.unlink(missing_ok=True)
        run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.sha])
        run([
            python_bin(root), str(worktree / "tools/run_q4r3_exact25_r73b4_readonly_display_parity_smoke.py"),
            "--root", str(root), "--worktree", str(worktree),
        ])
        payload = json.loads(status.read_text(encoding="utf-8"))
        verified = json.loads(validation.read_text(encoding="utf-8"))
        if payload.get("state") != "PASS" or verified.get("state") != "PASS":
            raise RuntimeError(f"R73B4_NOT_PASS:{payload}:{verified}")
        after_pids = pids()
        if after_pids != before_pids:
            raise RuntimeError(f"CORE_PID_CHANGED:{before_pids}:{after_pids}")
        after_hashes = {name: sha256(path) for name, path in protected.items()}
        if after_hashes != before_hashes:
            raise RuntimeError(f"PROTECTED_SURFACE_CHANGED:{before_hashes}:{after_hashes}")
        if sha256(ledger, ledger_size) != ledger_prefix:
            raise RuntimeError("FORMAL_LEDGER_PREFIX_CHANGED")
        evidence = {
            "evidence/q4r3_exact25_r73b4_readonly_display_parity_smoke_latest.json": status,
            "evidence/q4r3_exact25_r73b4_readonly_display_parity_validation_latest.json": validation,
        }
        for relative, source in evidence.items():
            destination = worktree / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        run(["git", "add", *evidence.keys()], cwd=worktree)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
            run(["git", "-c", "user.name=ZEL Runtime Evidence", "-c",
                 "user.email=zel-runtime-evidence@localhost", "commit", "-m",
                 "Record R7.3B4 read-only display parity evidence"], cwd=worktree)
            run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree)
        canonical = payload["canonical_metrics"]
        print("Q4R3_EXACT25_R73B4_BOOTSTRAP_PASS")
        print("OFFICIAL_STAGE=R7.3B4")
        for name, value in after_pids.items():
            print(f"{name}={value}")
        print(f"CLOSED_COUNT={canonical['closed_count']}")
        print(f"WINRATE_PCT={canonical['winrate_pct']}")
        print(f"TOTAL_R={canonical['total_r']}")
        print(f"LATEST_TRACE_ID={canonical['latest_trace_id']}")
        print("VIEW_PARITY_READY=true")
        print("TELEGRAM_PARITY_READY=true")
        print("FORBIDDEN_MARKER_COUNT=0")
        print("USER_VISIBLE_CONFIRMATION_REQUIRED=true")
        print("MUTATION_COUNT=0")
        print("EVIDENCE=evidence/q4r3_exact25_r73b4_readonly_display_parity_smoke_latest.json")
        passed = True
        return 0
    finally:
        if passed:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
        else:
            print(f"WORKTREE_PRESERVED_FOR_DIAGNOSIS={worktree}")


if __name__ == "__main__":
    raise SystemExit(main())
