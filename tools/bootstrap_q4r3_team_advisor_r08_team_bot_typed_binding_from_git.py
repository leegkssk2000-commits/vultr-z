#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "q4r3-team-advisor-r08-team-bot-typed-binding-v1"
UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
}


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def unit_pids() -> dict[str, str]:
    return {name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"]) for name, unit in UNITS.items()}


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python"):
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
    worktree = Path(f"/tmp/q4r3_team_advisor_r08_{args.sha[:12]}")
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    if not ledger.is_file():
        raise SystemExit(f"LEDGER_MISSING={ledger}")

    before_pids = unit_pids()
    with tempfile.NamedTemporaryFile(prefix="q4r3_r08_ledger_", delete=False) as handle:
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
            str(worktree / "tools/run_q4r3_team_advisor_r08_team_bot_typed_binding.py"),
            "--root", str(root),
            "--worktree", str(worktree),
        ])

        after_pids = unit_pids()
        if after_pids != before_pids:
            raise RuntimeError(f"SERVICE_PID_CHANGED:{before_pids}:{after_pids}")
        with ledger.open("rb") as current, ledger_copy.open("rb") as previous:
            if current.read(prefix_size) != previous.read(prefix_size):
                raise RuntimeError("LEDGER_PREFIX_CHANGED")

        status = root / "runtime/exact25_edge_v1/team_advisor_r08_team_bot_typed_binding/status_latest.json"
        evidence = worktree / "evidence/q4r3_team_advisor_r08_team_bot_typed_binding_latest.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(status, evidence)
        run(["git", "add", str(evidence.relative_to(worktree))], cwd=worktree)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
            run([
                "git", "-c", "user.name=ZEL Runtime Evidence",
                "-c", "user.email=zel-runtime-evidence@localhost",
                "commit", "-m", "Record R0.8 Team-to-Bot typed binding evidence",
            ], cwd=worktree)
            run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree)

        print("Q4R3_TEAM_ADVISOR_R08_BOOTSTRAP_PASS")
        for name, value in after_pids.items():
            print(f"{name}={value}")
        print("EVIDENCE=evidence/q4r3_team_advisor_r08_team_bot_typed_binding_latest.json")
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
