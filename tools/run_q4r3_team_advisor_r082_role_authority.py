#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    worktree = args.worktree.resolve()
    py = python_bin(root)
    binding = worktree / "canonical/teams/binding.py"
    validator = worktree / "tools/q4r3_team_advisor_r082_validate_role_authority.py"
    tests = [
        worktree / "tests/test_q4r3_team_advisor_r08_team_bot_typed_binding.py",
        worktree / "tests/test_q4r3_team_advisor_r082_role_authority.py",
    ]
    r081 = root / "runtime/exact25_edge_v1/team_advisor_r081_response_lineage_latency/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r082_role_authority/status_latest.json"

    for required in (binding, validator, r081, *tests):
        if not required.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={required}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    subprocess.run([py, "-m", "py_compile", str(binding), str(validator)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", *(str(path) for path in tests)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py, str(validator),
        "--r081", str(r081),
        "--binding-source", str(binding),
        "--output", str(output),
    ], env=env, check=True)

    payload = json.loads(output.read_text(encoding="utf-8"))
    report = payload.get("report") or {}
    assert payload.get("state") == "PASS", payload
    assert payload.get("verdict") == "R082_TEAM_ROLE_AUTHORITY_LOCK_PASS", payload
    assert payload.get("blockers") == [], payload
    assert report.get("team_count") == 4, payload
    assert report.get("generic_decision_authority_count") == 8, payload
    assert report.get("watch_only_count") == 8, payload
    assert report.get("helper_non_voting_count") == 4, payload
    assert report.get("sbot_hard_veto_capability_count") == 4, payload
    print("Q4R3_TEAM_ADVISOR_R082_ROLE_AUTHORITY_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
