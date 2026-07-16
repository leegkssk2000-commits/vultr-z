#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "q4r3-team-advisor-r61-zbot-shadow-observer-integration-gate-v2"
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


def unit_pids() -> dict[str, str]:
    return {name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"]) for name, unit in UNITS.items()}


def digest(path: Path) -> str:
    if not path.is_file():
        return "missing"
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


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
    worktree = Path(f"/tmp/q4r3_team_advisor_r61_{args.sha[:12]}")
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    r55 = root / "runtime/exact25_edge_v1/team_advisor_r55_zbot_attribution_drift_sgrade_lock/status_latest.json"
    if not ledger.is_file():
        raise SystemExit(f"LEDGER_MISSING={ledger}")
    if not r55.is_file():
        raise SystemExit(f"R55_STATUS_MISSING={r55}")
    before_pids = unit_pids()
    before_host_zbot = digest(HOST_ZBOT)
    before_r55 = digest(r55)
    with tempfile.NamedTemporaryFile(prefix="q4r3_r61_ledger_", delete=False) as handle:
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
            str(worktree / "tools/run_q4r3_team_advisor_r61_zbot_shadow_observer_integration_gate.py"),
            "--root", str(root),
            "--worktree", str(worktree),
        ])
        after_pids = unit_pids()
        after_host_zbot = digest(HOST_ZBOT)
        after_r55 = digest(r55)
        if after_pids != before_pids:
            raise RuntimeError(f"SERVICE_PID_CHANGED:{before_pids}:{after_pids}")
        if after_host_zbot != before_host_zbot:
            raise RuntimeError("HOST_ZBOT_CHANGED")
        if after_r55 != before_r55:
            raise RuntimeError("R55_STATUS_CHANGED")
        with ledger.open("rb") as current, ledger_copy.open("rb") as previous:
            if current.read(prefix_size) != previous.read(prefix_size):
                raise RuntimeError("LEDGER_PREFIX_CHANGED")

        status = root / "runtime/exact25_edge_v1/team_advisor_r61_zbot_shadow_observer_integration_gate/status_latest.json"
        evidence = worktree / "evidence/q4r3_team_advisor_r61_zbot_shadow_observer_integration_gate_latest.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(status, evidence)
        run(["git", "add", str(evidence.relative_to(worktree))], cwd=worktree)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
            run([
                "git", "-c", "user.name=ZEL Runtime Evidence",
                "-c", "user.email=zel-runtime-evidence@localhost",
                "commit", "-m", "Record R6.1 ZBot shadow observer gate evidence",
            ], cwd=worktree)
            run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree)
        print("Q4R3_TEAM_ADVISOR_R61_BOOTSTRAP_PASS")
        print("OFFICIAL_STAGE=R6.1")
        for name, value in after_pids.items():
            print(f"{name}={value}")
        print(f"HOST_ZBOT_SHA256={after_host_zbot}")
        print(f"R55_STATUS_SHA256={after_r55}")
        print("PROVIDER_INVOCATION_ENABLED=false")
        print("RUNTIME_BINDING_ENABLED=false")
        print("EVIDENCE=evidence/q4r3_team_advisor_r61_zbot_shadow_observer_integration_gate_latest.json")
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
