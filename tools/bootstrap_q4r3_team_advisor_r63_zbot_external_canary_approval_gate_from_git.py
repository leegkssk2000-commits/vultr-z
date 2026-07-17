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

BRANCH = "q4r3-team-advisor-r63-zbot-external-canary-approval-gate-v1"
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
    return {
        name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"])
        for name, unit in UNITS.items()
    }


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
    worktree = Path(f"/tmp/q4r3_team_advisor_r63_{args.sha[:12]}")
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    r62_status = root / "runtime/exact25_edge_v1/team_advisor_r62_zbot_provider_dryrun_canary/status_latest.json"
    if not ledger.is_file():
        raise SystemExit(f"LEDGER_MISSING={ledger}")
    if not r62_status.is_file():
        raise SystemExit(f"R62_STATUS_MISSING={r62_status}")

    before_pids = unit_pids()
    before_host_zbot = digest(HOST_ZBOT)
    before_r62 = digest(r62_status)
    with tempfile.NamedTemporaryFile(prefix="q4r3_r63_ledger_", delete=False) as handle:
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
            str(worktree / "tools/run_q4r3_team_advisor_r63_zbot_external_canary_approval_gate.py"),
            "--root", str(root),
            "--worktree", str(worktree),
        ])

        after_pids = unit_pids()
        after_host_zbot = digest(HOST_ZBOT)
        after_r62 = digest(r62_status)
        if after_pids != before_pids:
            raise RuntimeError(f"SERVICE_PID_CHANGED:{before_pids}:{after_pids}")
        if after_host_zbot != before_host_zbot:
            raise RuntimeError("HOST_ZBOT_CHANGED")
        if after_r62 != before_r62:
            raise RuntimeError("R62_STATUS_CHANGED")
        with ledger.open("rb") as current, ledger_copy.open("rb") as previous:
            if current.read(prefix_size) != previous.read(prefix_size):
                raise RuntimeError("LEDGER_PREFIX_CHANGED")

        status = root / "runtime/exact25_edge_v1/team_advisor_r63_zbot_external_canary_approval_gate/status_latest.json"
        payload = json.loads(status.read_text(encoding="utf-8"))
        if payload.get("state") != "PASS":
            raise RuntimeError("R63_STATUS_NOT_PASS")
        authority = payload.get("authority", {})
        report = payload.get("report", {})
        if authority.get("external_canary_approved") is not False:
            raise RuntimeError("EXTERNAL_CANARY_UNEXPECTEDLY_APPROVED")
        if report.get("network_call_count") != 0 or report.get("credential_resolution_count") != 0:
            raise RuntimeError("R63_EXTERNAL_SIDE_EFFECT_DETECTED")

        evidence = worktree / "evidence/q4r3_team_advisor_r63_zbot_external_canary_approval_gate_latest.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(status, evidence)
        run(["git", "add", str(evidence.relative_to(worktree))], cwd=worktree)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
            run([
                "git",
                "-c", "user.name=ZEL Runtime Evidence",
                "-c", "user.email=zel-runtime-evidence@localhost",
                "commit", "-m", "Record R6.3 ZBot external canary approval gate evidence",
            ], cwd=worktree)
            run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree)

        print("Q4R3_TEAM_ADVISOR_R63_BOOTSTRAP_PASS")
        print("OFFICIAL_STAGE=R6.3")
        for name, value in after_pids.items():
            print(f"{name}={value}")
        print(f"HOST_ZBOT_SHA256={after_host_zbot}")
        print(f"R62_STATUS_SHA256={after_r62}")
        print("EXTERNAL_CANARY_APPROVED=false")
        print("PROVIDER_INVOCATION_ENABLED=false")
        print("NETWORK_CALL_COUNT=0")
        print("CREDENTIAL_RESOLUTION_COUNT=0")
        print("EVIDENCE=evidence/q4r3_team_advisor_r63_zbot_external_canary_approval_gate_latest.json")
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
