from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "zel.production_vps_git_state.v1"


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def git(root: Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def audit(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        raise RuntimeError(f"GIT_PREFLIGHT_NOT_REPOSITORY:{root}")

    rc_head, head, err_head = git(root, "rev-parse", "HEAD")
    rc_branch, branch, _ = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    rc_status, status, err_status = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    rc_remote, remote, _ = git(root, "remote", "get-url", "origin")
    if any(rc != 0 for rc in (rc_head, rc_branch, rc_status, rc_remote)):
        raise RuntimeError(f"GIT_PREFLIGHT_COMMAND_FAILED:{err_head}:{err_status}")

    # Fetch is read-only with respect to the working tree/branch and is needed to
    # measure divergence safely. It may update remote-tracking metadata only.
    rc_fetch, _out_fetch, err_fetch = git(root, "fetch", "origin", "master", "--quiet")
    if rc_fetch != 0:
        raise RuntimeError(f"GIT_PREFLIGHT_FETCH_FAILED:{err_fetch[-300:]}")
    rc_div, divergence, err_div = git(root, "rev-list", "--left-right", "--count", "HEAD...origin/master")
    if rc_div != 0:
        raise RuntimeError(f"GIT_PREFLIGHT_DIVERGENCE_FAILED:{err_div}")
    try:
        ahead_s, behind_s = divergence.split()
        ahead = int(ahead_s)
        behind = int(behind_s)
    except Exception as exc:
        raise RuntimeError(f"GIT_PREFLIGHT_DIVERGENCE_INVALID:{divergence}") from exc

    dirty_lines = [line for line in status.splitlines() if line.strip()]
    tracked_dirty = [line for line in dirty_lines if not line.startswith("??")]
    untracked = [line for line in dirty_lines if line.startswith("??")]
    remote_matches = "leegkssk2000-commits/vultr-z" in remote
    safe_for_fast_forward = (
        remote_matches
        and branch == "master"
        and not tracked_dirty
        and ahead == 0
    )
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_VPS_GIT_SAFE_FOR_FAST_FORWARD" if safe_for_fast_forward else "HOLD_VPS_GIT_REVIEW_REQUIRED",
        "root": str(root),
        "head": head,
        "branch": branch,
        "remote_matches_repo": remote_matches,
        "tracked_dirty_count": len(tracked_dirty),
        "untracked_count": len(untracked),
        "untracked_paths": [line[3:] for line in untracked[:100]],
        "ahead_of_origin_master": ahead,
        "behind_origin_master": behind,
        "safe_for_fast_forward": safe_for_fast_forward,
        "working_tree_mutated": False,
        "service_mutated": False,
        "exchange_order_submitted": False,
        "live_trade_authority": "BLOCKED",
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
