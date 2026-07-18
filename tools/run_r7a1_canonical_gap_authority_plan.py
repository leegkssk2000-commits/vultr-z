#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def git_show(root: Path, sha: str, path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{sha}:{path}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GIT_SHOW_FAILED:{path}:{result.stderr[-300:]}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    source = root / "runtime/exact25_edge_v1/r7a0c_audit_correctness_patch/status_latest.json"
    output_dir = root / "runtime/exact25_edge_v1/r7a1_canonical_gap_authority_plan"
    if not source.is_file() or source.stat().st_size == 0:
        raise SystemExit("R7A0C_STATUS_MISSING")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r7a1.") as raw:
        work = Path(raw)
        contract = work / "contract.json"
        planner = work / "plan.py"
        contract.write_text(git_show(root, args.sha, "backend/contracts/ZOS_R7A1_CANONICAL_GAP_AUTHORITY_PLAN_v1.json"), encoding="utf-8")
        planner.write_text(git_show(root, args.sha, "tools/r7a1_canonical_gap_authority_plan.py"), encoding="utf-8")
        compile_result = subprocess.run([sys.executable, "-m", "py_compile", str(planner)], check=False)
        if compile_result.returncode != 0:
            raise SystemExit("R7A1_PLANNER_COMPILE_FAILED")
        command = [
            sys.executable,
            str(planner),
            "--contract", str(contract),
            "--input", str(source),
            "--output", str(output_dir / "status_latest.json"),
            "--report", str(output_dir / "report_latest.md"),
        ]
        return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
