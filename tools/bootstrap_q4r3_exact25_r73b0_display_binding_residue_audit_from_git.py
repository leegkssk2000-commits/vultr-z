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

BRANCH = "q4r3-exact25-r73b0-display-binding-residue-audit-v1"
UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
}
HOST_ZBOT = Path("/usr/local/bin/zel_alimi_w210_zbot_control_advisor.py")


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def pids() -> dict[str, str]:
    return {name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"]) for name, unit in UNITS.items()}


def systemd_snapshot() -> str:
    services = output(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager"])
    timers = output(["systemctl", "list-timers", "--all", "--no-legend", "--no-pager"])
    return hashlib.sha256((services + "\n--TIMERS--\n" + timers).encode()).hexdigest()


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
    worktree = Path(f"/tmp/q4r3_exact25_r73b0_{args.sha[:12]}")
    runtime = root / "runtime/exact25_edge_v1/exact25_r73b0_display_binding_residue_audit"
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    protected = {
        "HOST_ZBOT": HOST_ZBOT,
        "ACTIVE_SKILL_REGISTRY": root / "backend/contracts/ZOS_SKILL_REGISTRY_v1.json",
        "ACTIVE_SKILL_RESOLVER": root / "backend/engine/skill_resolver.py",
        "R73A_STATUS": root / "runtime/exact25_edge_v1/exact25_r73a_source_entry_bridge_prebind/status_latest.json",
        "R72_STATUS": root / "runtime/exact25_edge_v1/exact25_r72_raw_100_lane_shadow_projection/status_latest.json",
    }
    for path in (ledger, *protected.values()):
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")
    before_pids = pids()
    before_systemd = systemd_snapshot()
    before_hashes = {name: sha(path) for name, path in protected.items()}
    with tempfile.NamedTemporaryFile(prefix="q4r3_r73b0_ledger_", delete=False) as handle:
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
            python_bin(root), str(worktree / "tools/run_q4r3_exact25_r73b0_display_binding_residue_audit.py"),
            "--root", str(root), "--worktree", str(worktree),
        ])
        after_pids = pids()
        after_systemd = systemd_snapshot()
        after_hashes = {name: sha(path) for name, path in protected.items()}
        if after_pids != before_pids:
            raise RuntimeError(f"SERVICE_PID_CHANGED:{before_pids}:{after_pids}")
        if after_systemd != before_systemd:
            raise RuntimeError("SYSTEMD_INVENTORY_CHANGED")
        if after_hashes != before_hashes:
            raise RuntimeError(f"PROTECTED_SURFACE_CHANGED:{before_hashes}:{after_hashes}")
        with ledger.open("rb") as current, ledger_copy.open("rb") as previous:
            if current.read(prefix_size) != previous.read(prefix_size):
                raise RuntimeError("FORMAL_LEDGER_PREFIX_CHANGED")
        status = runtime / "status_latest.json"
        inventory = runtime / "inventory_latest.json"
        payload = json.loads(status.read_text(encoding="utf-8"))
        if payload.get("state") != "PASS" or payload.get("blockers"):
            raise RuntimeError(f"R73B0_STATUS_NOT_PASS:{payload}")
        evidence_status = worktree / "evidence/q4r3_exact25_r73b0_display_binding_residue_audit_latest.json"
        evidence_inventory = worktree / "evidence/q4r3_exact25_r73b0_display_binding_residue_inventory_latest.json"
        evidence_status.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(status, evidence_status)
        shutil.copyfile(inventory, evidence_inventory)
        run(["git", "add", str(evidence_status.relative_to(worktree)), str(evidence_inventory.relative_to(worktree))], cwd=worktree)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
            run([
                "git", "-c", "user.name=ZEL Runtime Evidence", "-c", "user.email=zel-runtime-evidence@localhost",
                "commit", "-m", "Record R7.3B0 Telegram View residue audit evidence",
            ], cwd=worktree)
            run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree)
        print("Q4R3_EXACT25_R73B0_BOOTSTRAP_PASS")
        print("OFFICIAL_STAGE=R7.3B0")
        for name, value in after_pids.items(): print(f"{name}={value}")
        print(f"RECORD_COUNT={payload.get('record_count', 0)}")
        print(f"WRITER_CANDIDATE_COUNT={payload.get('writer_candidate_count', 0)}")
        print(f"STATIC_LOCK_COUNT={payload.get('static_lock_count', 0)}")
        print("CLEANUP_APPLIED=false")
        print("SERVICE_MUTATION_ALLOWED=false")
        print("FORMAL_LEDGER_WRITE_ALLOWED=false")
        print("EVIDENCE=evidence/q4r3_exact25_r73b0_display_binding_residue_audit_latest.json")
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
