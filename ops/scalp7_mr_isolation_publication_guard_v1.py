"""Verify the authorized MR source relocation plus the unchanged old publication.

The completed measurement campaign forbids *any* unrelated backend edit.  This
narrow adapter proves the two exact MR byte identities in the real checkout,
then invokes that unchanged historic validator in a disclosed temporary view.
Only the already-proved relocation and this exact workflow wrapper are projected
back to the published view.  Every other backend change and sealed artifact is
still checked by the original validator.  No hashes/results/tolerances change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PUBLICATION = "a2361cd859f150951ec5d815073eaf57f291c9cd"
LEGACY = "scripts/verify_scalp7_measurement_exact25_closure_v1.py"
WORKFLOW = ".github/workflows/scalp7-measurement-exact25-closure-v1.yml"
ADAPTER = "ops/scalp7_mr_isolation_publication_guard_v1.py"
OLD = "backend/research/rebuild/scalp7_mr_formation_v2.py"
NEW = "backend/research/rebuild/issue1377_mr_formation_cost2_v1.py"
ORIGINAL_SHA = "1674f245d57ed8b6d2b7ddd1984c1dade37af49172ef8fdd4341b8bbb873e6e5"
EXTENSION_SHA = "b0ef459e4084fbd477c1597cf32454918321d0c07b0d869b3d289ff4ddad54f3"
WORKFLOW_SHA = "d1598791a8eb6ea0b2849ceeb075928085576d34944054790fd105db65a7426e"
SEAL = "research/campaigns/scalp7_20261001/measurement_exact25_closure_v1/INPUT_SEAL.json"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False
    )
    require(result.returncode == 0, "GIT_FAILED:" + result.stderr.decode(errors="replace"))
    return result.stdout


def read_safe(repo: Path, path: str) -> bytes:
    target = repo / path
    require(target.is_file() and not target.is_symlink(), "MISSING_OR_SYMLINK:" + path)
    require(target.resolve().is_relative_to(repo), "PATH_OUTSIDE_REPO:" + path)
    return target.read_bytes()


def adapted_workflow(original: bytes) -> bytes:
    """Only the entrypoint changes; events, base provenance and checks remain."""
    require(digest(original) == WORKFLOW_SHA, "HISTORIC_WORKFLOW_CHANGED")
    text = original.decode("utf-8")
    changes = {
        'origin "$HISTORY_BASE_SHA" 7bb11442454053c011082fd6034d965631e719ef':
            'origin "$HISTORY_BASE_SHA" 7bb11442454053c011082fd6034d965631e719ef ' + PUBLICATION,
        'HISTORY_SCRIPT="' + LEGACY + '"':
            'HISTORY_SCRIPT="' + ADAPTER + '"',
        'run: python ' + LEGACY + ' --base-sha':
            'run: python ' + ADAPTER + ' --base-sha',
    }
    for before, after in changes.items():
        require(text.count(before) == 1, "WORKFLOW_TRANSFORM_PROFILE:" + before)
        text = text.replace(before, after)
    return text.encode("utf-8")


def relocation_plan(base_old: str, base_new: str | None,
                    current_old: str, current_new: str) -> bool:
    require(current_old == ORIGINAL_SHA, "RESTORED_ORIGINAL_BYTES_MISMATCH")
    require(current_new == EXTENSION_SHA, "PRESERVED_EXTENSION_BYTES_MISMATCH")
    if base_old == EXTENSION_SHA and base_new is None:
        return True
    require(base_old == ORIGINAL_SHA and base_new == EXTENSION_SHA,
            "UNREVIEWED_MIGRATION_BASE")
    return False


def run(args: argparse.Namespace) -> dict:
    repo = args.repo.resolve()
    for value in (args.base_sha, args.checkout_sha):
        require(bool(re.fullmatch(r"[0-9a-f]{40}", value)), "EXPLICIT_COMMIT_REQUIRED")
    require(git(repo, "rev-parse", "HEAD").decode().strip() == args.checkout_sha,
            "CHECKOUT_MISMATCH")
    require(not git(repo, "status", "--porcelain", "--untracked-files=all").strip(),
            "UNCOMMITTED_CHECKOUT_REJECTED")
    frozen_workflow = git(repo, "show", PUBLICATION + ":" + WORKFLOW)
    require(read_safe(repo, WORKFLOW) == adapted_workflow(frozen_workflow),
            "UNREVIEWED_WORKFLOW_CHANGE")
    publication_seal = json.loads(git(repo, "show", PUBLICATION + ":" + SEAL))
    require(digest(read_safe(repo, LEGACY)) == publication_seal["covered_files"][LEGACY],
            "HISTORIC_VERIFIER_CHANGED")
    base_old = git(repo, "show", args.base_sha + ":" + OLD)
    has_new = bool(git(repo, "ls-tree", "--name-only", args.base_sha, "--", NEW).strip())
    base_new = git(repo, "show", args.base_sha + ":" + NEW) if has_new else None
    projected = relocation_plan(
        digest(base_old), digest(base_new) if base_new is not None else None,
        digest(read_safe(repo, OLD)), digest(read_safe(repo, NEW)),
    )
    changed_view = [WORKFLOW]
    with tempfile.TemporaryDirectory(prefix="mr-publication-proof-") as directory:
        view = Path(directory) / "view"
        git(repo, "worktree", "add", "--detach", str(view), args.checkout_sha)
        try:
            (view / WORKFLOW).write_bytes(frozen_workflow)
            if projected:
                (view / OLD).write_bytes(base_old)
                (view / NEW).unlink()
                changed_view.extend([OLD, NEW])
            command = [
                sys.executable, str(view / LEGACY), "--repo", str(view),
                "--base-sha", args.base_sha, "--checkout-sha", args.checkout_sha,
                "--base-source", args.base_source, "--default-branch", args.default_branch,
            ]
            if args.history_only:
                command.append("--history-only")
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            require(result.returncode == 0,
                    "UNCHANGED_LEGACY_VALIDATOR_FAILED:\n" + result.stdout + result.stderr)
            legacy_result = json.loads(result.stdout.strip().splitlines()[-1])
            require(legacy_result.get("status") == "PASS", "LEGACY_NOT_PASS")
        finally:
            git(repo, "worktree", "remove", "--force", str(view))
    return {
        "status": "PASS",
        "scope": "EXACT_AUTHORIZED_MR_RELOCATION_AND_UNCHANGED_HISTORIC_PUBLICATION",
        "original_sha256": ORIGINAL_SHA,
        "extension_sha256": EXTENSION_SHA,
        "historic_workflow_sha256": WORKFLOW_SHA,
        "historic_verifier_changed": False,
        "disclosed_projection_paths": changed_view,
        "other_current_backend_changes_checked_by_original_guard": True,
        "sealed_results_or_hashes_changed": False,
        "legacy_result": legacy_result,
        "economic_runs": 0,
        "order_live_paper_deploy": "BLOCKED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--checkout-sha", required=True)
    parser.add_argument("--base-source", required=True,
                        choices=("PR_EVENT_BASE", "DEFAULT_BRANCH_PUSH_BEFORE", "PUBLISHED_DEFAULT_BRANCH"))
    parser.add_argument("--default-branch", required=True)
    parser.add_argument("--history-only", action="store_true")
    print(json.dumps(run(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
