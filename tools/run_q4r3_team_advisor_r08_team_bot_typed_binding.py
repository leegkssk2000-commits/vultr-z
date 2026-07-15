#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


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
    test = worktree / "tests/test_q4r3_team_advisor_r08_team_bot_typed_binding.py"
    validator = worktree / "tools/q4r3_team_advisor_r08_validate_team_bot_binding.py"
    binding_source = worktree / "canonical/teams/binding.py"
    r05 = root / "runtime/exact25_edge_v1/team_advisor_r05_canonical_team_package/status_latest.json"
    r061 = root / "runtime/exact25_edge_v1/team_advisor_r061_bot_boundary_adjudication/status_latest.json"
    r07 = root / "runtime/exact25_edge_v1/team_advisor_r07_canonical_bot_packages/status_latest.json"
    output = root / "runtime/exact25_edge_v1/team_advisor_r08_team_bot_typed_binding/status_latest.json"

    for required in (test, validator, binding_source, r05, r061, r07):
        if not required.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={required}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    subprocess.run([py, "-m", "py_compile", str(binding_source), str(validator)], env=env, check=True)
    subprocess.run([py, "-m", "pytest", "-q", str(test)], env=env, check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        py, str(validator),
        "--r05", str(r05),
        "--r061", str(r061),
        "--r07", str(r07),
        "--binding-source", str(binding_source),
        "--output", str(output),
    ], env=env, check=True)
    print("Q4R3_TEAM_ADVISOR_R08_TYPED_BINDING_COMPLETE")
    print(f"STATUS={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
