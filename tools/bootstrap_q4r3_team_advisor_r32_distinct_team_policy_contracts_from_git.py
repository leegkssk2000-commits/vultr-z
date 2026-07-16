#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "q4r3-team-advisor-r32-distinct-team-policy-contracts-v1"
UNITS = (
    ("ZICO_PID", "zico-ceo-canonical-adapter.service"),
    ("PRODUCER_PID", "q4r3-exact25-shadow-producer.service"),
    ("WRITER_PID", "q4r3-exact25-persistent-single-event-writer.service"),
)


def pybin(root: Path) -> str:
    for candidate in (root / ".venv/bin/python", root / "venv/bin/python"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def pids() -> dict[str, str]:
    return {
        name: subprocess.check_output(
            ["systemctl", "show", unit, "-p", "MainPID", "--value"], text=True
        ).strip()
        for name, unit in UNITS
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", default=BRANCH)
    args = parser.parse_args()

    root = args.root.resolve()
    wt = Path(f"/tmp/q4r3_team_advisor_r32_{args.sha[:12]}")
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    if not ledger.is_file():
        raise SystemExit(f"LEDGER_MISSING={ledger}")

    before = pids()
    with tempfile.NamedTemporaryFile(prefix="q4r3_r32_ledger_", delete=False) as handle:
        backup = Path(handle.name)
    shutil.copyfile(ledger, backup)
    prefix_size = backup.stat().st_size
    passed = False
    try:
        if wt.exists():
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(wt)], check=False)
            shutil.rmtree(wt, ignore_errors=True)
        subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", str(wt), args.sha], check=True)
        subprocess.run([
            pybin(root), str(wt / "tools/run_q4r3_team_advisor_r32_distinct_team_policy_contracts.py"),
            "--root", str(root), "--worktree", str(wt),
        ], check=True)

        after = pids()
        if after != before:
            raise RuntimeError(f"SERVICE_PID_CHANGED:{before}:{after}")
        with ledger.open("rb") as current, backup.open("rb") as previous:
            if current.read(prefix_size) != previous.read(prefix_size):
                raise RuntimeError("LEDGER_PREFIX_CHANGED")

        status = root / "runtime/exact25_edge_v1/team_advisor_r32_distinct_team_policy_contracts/status_latest.json"
        payload = json.loads(status.read_text(encoding="utf-8"))
        if payload.get("state") != "PASS" or payload.get("verdict") != "R32_DISTINCT_TEAM_POLICY_CONTRACTS_PASS":
            raise RuntimeError(f"R32_STATUS_NOT_PASS:{payload.get('blockers')}")

        evidence = wt / "evidence/q4r3_team_advisor_r32_distinct_team_policy_contracts_latest.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(status, evidence)
        subprocess.run(["git", "add", str(evidence.relative_to(wt))], cwd=wt, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=wt).returncode != 0:
            subprocess.run([
                "git", "-c", "user.name=ZEL Runtime Evidence",
                "-c", "user.email=zel-runtime-evidence@localhost",
                "commit", "-m", "Record R3.2 distinct Team policy contract evidence",
            ], cwd=wt, check=True)
            subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=wt, check=True)

        print("Q4R3_TEAM_ADVISOR_R32_BOOTSTRAP_PASS")
        print("OFFICIAL_STAGE=R3.2")
        for name, value in after.items():
            print(f"{name}={value}")
        print("EVIDENCE=evidence/q4r3_team_advisor_r32_distinct_team_policy_contracts_latest.json")
        passed = True
        return 0
    finally:
        backup.unlink(missing_ok=True)
        if passed:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(wt)], check=False)
        else:
            print(f"WORKTREE_PRESERVED_FOR_DIAGNOSIS={wt}")


if __name__ == "__main__":
    raise SystemExit(main())
