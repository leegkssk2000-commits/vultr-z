#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "q4r3-exact25-r73b4u2-rendered-surface-diagnosis-v1"
FILES = (
    "backend/contracts/ZOS_EXACT25_R73B4U2_RENDERED_SURFACE_DIAGNOSIS_v1.json",
    "tools/q4r3_exact25_r73b4u2_rendered_surface_diagnosis.py",
    "tests/test_q4r3_exact25_r73b4u2_rendered_surface_diagnosis.py",
)
STATUS = Path("/home/z/z/runtime/exact25_edge_v1/exact25_r73b4u2_rendered_surface_diagnosis/status_latest.json")


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def python_bin(root: Path) -> str:
    for path in (
        root / ".venv/bin/python",
        root / "venv/bin/python",
        root / "backend/.venv/bin/python",
    ):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


def materialize(root: Path, sha: str, worktree: Path, repo_path: str) -> Path:
    target = worktree / repo_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        output(["git", "-C", str(root), "-c", f"safe.directory={root}", "show", f"{sha}:{repo_path}"]) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", default=BRANCH)
    args = parser.parse_args()
    root = args.root.resolve()
    py = python_bin(root)

    with tempfile.TemporaryDirectory(prefix="q4r3_exact25_r73b4u2_") as raw:
        worktree = Path(raw)
        contract = materialize(root, args.sha, worktree, FILES[0])
        tool = materialize(root, args.sha, worktree, FILES[1])
        test = materialize(root, args.sha, worktree, FILES[2])
        tool.chmod(0o755)

        subprocess.run([py, "-m", "pytest", "-q", str(test)], check=True, cwd=worktree)
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [py, str(tool), "--contract", str(contract), "--status", str(STATUS)],
            text=True,
            capture_output=True,
        )
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)

        payload = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.is_file() else {}
        print("Q4R3_EXACT25_R73B4U2_BOOTSTRAP_COMPLETE")
        print("OFFICIAL_STAGE=R7.3B4U2")
        print(f"STATE={payload.get('state')}")
        print(f"BLOCKER_COUNT={payload.get('blocker_count')}")
        print(f"WARNING_COUNT={payload.get('warning_count')}")
        renderer = payload.get("telegram_renderer", {})
        view = payload.get("view_renderer", {})
        print(f"TELEGRAM_SOURCE={renderer.get('source_path')}")
        print(f"TELEGRAM_SPLIT_SOURCE_SUSPECTED={renderer.get('split_source_suspected')}")
        print(f"TELEGRAM_SECONDARY_JSON_PATH_COUNT={len(renderer.get('secondary_json_paths', []))}")
        print(f"TELEGRAM_FALLBACK_EXPRESSION_COUNT={renderer.get('fallback_expression_count')}")
        print(f"VIEW_WRITERS7_PROJECTION_GAP={view.get('writers7_projection_gap')}")
        print(f"VIEW_LEGACY_LEDGER_LABEL={view.get('legacy_ledger_label_present')}")
        print(f"MUTATION_COUNT={payload.get('mutation_count')}")
        print(f"NEXT_STAGES={','.join(payload.get('next_stages', []))}")
        print(f"EVIDENCE={STATUS}")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
