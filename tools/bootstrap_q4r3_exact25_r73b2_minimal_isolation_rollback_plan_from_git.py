#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "q4r3-exact25-r73b2-minimal-isolation-rollback-plan-v1"
UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
}
TARGET_UNITS = (
    "zel-s4g8r7f8t-telegram-6c-lock-only.timer",
    "zel-s4g8r7f8t-telegram-6c-lock-only.service",
)


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def pids() -> dict[str, str]:
    return {name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"]) for name, unit in UNITS.items()}


def unit_state(unit: str, mode: str) -> str:
    result = subprocess.run(
        ["systemctl", mode, unit],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout.strip() or f"rc={result.returncode}"


def target_states() -> dict[str, dict[str, str]]:
    return {
        unit: {
            "active": unit_state(unit, "is-active"),
            "enabled": unit_state(unit, "is-enabled"),
        }
        for unit in TARGET_UNITS
    }


def sha(path: Path) -> str:
    if not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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
    worktree = Path(f"/tmp/q4r3_exact25_r73b2_{args.sha[:12]}")
    runtime = root / "runtime/exact25_edge_v1/exact25_r73b2_minimal_isolation_rollback_plan"
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    target_files = {
        unit: Path("/etc/systemd/system") / unit
        for unit in TARGET_UNITS
    }
    protected = {
        "R73B1_STATUS": root / "runtime/exact25_edge_v1/exact25_r73b1_single_owner_plan/status_latest.json",
        "R73B1_PLAN": root / "runtime/exact25_edge_v1/exact25_r73b1_single_owner_plan/plan_latest.json",
        "R73B0_STATUS": root / "runtime/exact25_edge_v1/exact25_r73b0_display_binding_residue_audit/status_latest.json",
        "R73A_STATUS": root / "runtime/exact25_edge_v1/exact25_r73a_source_entry_bridge_prebind/status_latest.json",
        "SKILL_REGISTRY": root / "backend/contracts/ZOS_SKILL_REGISTRY_v1.json",
        "SKILL_RESOLVER": root / "backend/engine/skill_resolver.py",
    }
    for path in (ledger, *protected.values(), *target_files.values()):
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    before_pids = pids()
    before_hashes = {name: sha(path) for name, path in protected.items()}
    before_target_hashes = {name: sha(path) for name, path in target_files.items()}
    before_target_states = target_states()
    with tempfile.NamedTemporaryFile(prefix="q4r3_r73b2_ledger_", delete=False) as handle:
        ledger_copy = Path(handle.name)
    shutil.copyfile(ledger, ledger_copy)
    prefix_size = ledger_copy.stat().st_size
    passed = False
    try:
        if worktree.exists():
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
            shutil.rmtree(worktree, ignore_errors=True)
        run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.sha])
        run([
            python_bin(root),
            str(worktree / "tools/run_q4r3_exact25_r73b2_minimal_isolation_rollback_plan.py"),
            "--root", str(root),
            "--worktree", str(worktree),
        ])

        after_pids = pids()
        after_hashes = {name: sha(path) for name, path in protected.items()}
        after_target_hashes = {name: sha(path) for name, path in target_files.items()}
        after_target_states = target_states()
        if after_pids != before_pids:
            raise RuntimeError(f"SERVICE_PID_CHANGED:{before_pids}:{after_pids}")
        if after_hashes != before_hashes:
            raise RuntimeError(f"PROTECTED_SURFACE_CHANGED:{before_hashes}:{after_hashes}")
        if after_target_hashes != before_target_hashes:
            raise RuntimeError(f"TARGET_UNIT_FILE_CHANGED:{before_target_hashes}:{after_target_hashes}")
        if after_target_states != before_target_states:
            raise RuntimeError(f"TARGET_UNIT_STATE_CHANGED:{before_target_states}:{after_target_states}")
        with ledger.open("rb") as current, ledger_copy.open("rb") as previous:
            if current.read(prefix_size) != previous.read(prefix_size):
                raise RuntimeError("FORMAL_LEDGER_PREFIX_CHANGED")

        status = runtime / "status_latest.json"
        plan = runtime / "plan_latest.json"
        payload = json.loads(status.read_text(encoding="utf-8"))
        if payload.get("state") != "PASS" or payload.get("blockers"):
            raise RuntimeError(f"R73B2_STATUS_NOT_PASS:{payload}")
        evidence_status = worktree / "evidence/q4r3_exact25_r73b2_minimal_isolation_rollback_plan_latest.json"
        evidence_plan = worktree / "evidence/q4r3_exact25_r73b2_minimal_isolation_rollback_manifest_latest.json"
        evidence_status.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(status, evidence_status)
        shutil.copyfile(plan, evidence_plan)
        run(["git", "add", str(evidence_status.relative_to(worktree)), str(evidence_plan.relative_to(worktree))], cwd=worktree)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
            run([
                "git", "-c", "user.name=ZEL Runtime Evidence", "-c", "user.email=zel-runtime-evidence@localhost",
                "commit", "-m", "Record R7.3B2 minimal isolation rollback evidence",
            ], cwd=worktree)
            run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree)

        print("Q4R3_EXACT25_R73B2_BOOTSTRAP_PASS")
        print("OFFICIAL_STAGE=R7.3B2")
        for name, value in after_pids.items():
            print(f"{name}={value}")
        print(f"PROTECTED_UNIT_COUNT={payload.get('protected_unit_count', 0)}")
        print(f"TARGET_COUNT={payload.get('target_count', 0)}")
        print(f"TARGET_PROTECTED_OVERLAP_COUNT={payload.get('target_protected_overlap_count', 0)}")
        print(f"MISSING_TARGET_COUNT={payload.get('missing_target_count', 0)}")
        print(f"HASH_READY_COUNT={payload.get('hash_ready_count', 0)}")
        print(f"ROLLBACK_READY_COUNT={payload.get('rollback_ready_count', 0)}")
        print("CLEANUP_APPLIED=false")
        print("MUTATION_AUTHORITY=none")
        print("EVIDENCE=evidence/q4r3_exact25_r73b2_minimal_isolation_rollback_plan_latest.json")
        passed = True
        return 0
    finally:
        ledger_copy.unlink(missing_ok=True)
        if passed:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
        else:
            print(f"WORKTREE_PRESERVED_FOR_DIAGNOSIS={worktree}")


if __name__ == "__main__":
    raise SystemExit(main())
