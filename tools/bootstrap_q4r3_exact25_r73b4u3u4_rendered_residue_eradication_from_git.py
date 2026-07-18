#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FILES = (
    "backend/contracts/ZOS_EXACT25_R73B4U3U4_RENDERED_RESIDUE_ERADICATION_v1.json",
    "tools/q4r3_exact25_r73b4u3u4_rendered_residue_eradication.py",
    "tests/test_q4r3_exact25_r73b4u3u4_rendered_residue_eradication.py",
)
STATUS = Path("/home/z/z/runtime/exact25_edge_v1/exact25_r73b4u3u4_rendered_residue_eradication/status_latest.json")


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def python_bin(root: Path) -> str:
    for path in (root / ".venv/bin/python", root / "venv/bin/python", root / "backend/.venv/bin/python"):
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
    args = parser.parse_args()
    root = args.root.resolve()
    py = python_bin(root)

    with tempfile.TemporaryDirectory(prefix="q4r3_exact25_r73b4u3u4_") as raw:
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
        print("Q4R3_EXACT25_R73B4U3U4_BOOTSTRAP_COMPLETE")
        print("OFFICIAL_STAGE=R7.3B4U3U4")
        print(f"STATE={payload.get('state')}")
        print(f"BLOCKER_COUNT={payload.get('blocker_count')}")
        print(f"MUTATION_COUNT={payload.get('mutation_count')}")
        print(f"ROLLBACK_PERFORMED={payload.get('rollback_performed')}")
        print(f"TELEGRAM_METRIC_REWRITE_COUNT={payload.get('telegram_metric_rewrite_count')}")
        print(f"TELEGRAM_SECONDARY_JSON_PATH_COUNT={payload.get('telegram_secondary_json_path_count')}")
        print(f"TELEGRAM_DIRECT_METRIC_FALLBACK_COUNT={payload.get('telegram_direct_metric_fallback_count')}")
        print(f"TELEGRAM_COMPILE_OK={payload.get('telegram_compile_ok')}")
        print(f"TELEGRAM_UNIT_ACTIVE={payload.get('telegram_unit_active')}")
        print(f"VIEW_LEGACY_MARKER_COUNT={payload.get('view_legacy_marker_count')}")
        print(f"VIEW_WRITER_CARD_CONFIGURED_LABEL={payload.get('view_writer_card_configured_label')}")
        print(f"ALIMI_HTTP_STATUS={payload.get('alimi_http_status')}")
        print(f"FORMAL_LEDGER_CHANGE_COUNT={payload.get('formal_ledger_change_count')}")
        print(f"RUNTIME_ACTIVE={payload.get('runtime_active')}")
        print(f"NEXT_STAGE={payload.get('next_stage')}")
        print(f"EVIDENCE={STATUS}")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
