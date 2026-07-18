#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

FILES = (
    "backend/contracts/ZOS_R7A1A_ACTIVE_SOURCE_PROVENANCE_PLAN_v1.json",
    "tools/r7a1a_active_source_provenance_plan.py",
)


def git_show(root: Path, sha: str, repo_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{sha}:{repo_path}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GIT_SHOW_FAILED:{repo_path}:{result.stderr[-300:]}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = root / "runtime/exact25_edge_v1/r7a1a_active_source_provenance_plan"
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="r7a1a.") as raw:
        work = Path(raw)
        contract = work / "contract.json"
        planner = work / "planner.py"
        contract.write_text(git_show(root, args.sha, FILES[0]), encoding="utf-8")
        planner.write_text(git_show(root, args.sha, FILES[1]), encoding="utf-8")
        compile_result = subprocess.run([sys.executable, "-m", "py_compile", str(planner)], check=False)
        if compile_result.returncode != 0:
            raise SystemExit("R7A1A_PLANNER_COMPILE_FAILED")
        command = [
            sys.executable,
            str(planner),
            "--contract", str(contract),
            "--target-sha", args.sha,
            "--output", str(output_dir / "status_latest.json"),
            "--report", str(output_dir / "report_latest.md"),
        ]
        return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
