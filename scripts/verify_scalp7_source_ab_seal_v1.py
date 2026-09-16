"""Seal PR1339 publications without modifying a frozen economic experiment.

The pinned Git tree is the reviewed 3694620 publication, not a new selection.
All bytes, filenames, file modes and the handoff are covered. No replay is run.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ARTIFACT_DIR = "research/campaigns/scalp7_20260916/source_ab_v1"
REVIEWED_REVISION = "369462085cc59f4e374c609e06d01ae1aa7b4c19"
REVIEWED_TREE = "6e57bb97fb043101be0d363eb1c20e4132304d8b"
WORKFLOW = ".github/workflows/scalp7-source-ab-saved-v1.yml"
CAMPAIGN_FREEZE = (
    "research/campaigns/scalp7_20260915/broad_rebuild_v2/"
    "CAMPAIGN_PREREGISTERED_V2.json"
)


def git_object_id(kind: str, data: bytes) -> str:
    """Git object identity; SHA-1 here is an exact Git pin, not a security claim."""
    payload = (
        kind.encode("ascii") + b" " + str(len(data)).encode("ascii") + b"\0" + data
    )
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()


def tree_id(directory: Path) -> tuple[str, int]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("PUBLICATION_DIRECTORY_REQUIRED")
    entries: list[tuple[bytes, bytes]] = []
    files = 0
    for path in directory.iterdir():
        if path.is_symlink():
            raise ValueError("PUBLICATION_SYMLINK_REJECTED")
        name = path.name.encode("utf-8")
        if path.is_dir():
            oid, count = tree_id(path)
            mode, sort_key = b"40000", name + b"/"
        elif path.is_file():
            oid, count = git_object_id("blob", path.read_bytes()), 1
            mode = b"100755" if path.stat().st_mode & 0o111 else b"100644"
            sort_key = name
        else:
            raise ValueError("PUBLICATION_SPECIAL_FILE_REJECTED")
        entries.append((sort_key, mode + b" " + name + b"\0" + bytes.fromhex(oid)))
        files += count
    data = b"".join(entry for _, entry in sorted(entries))
    return git_object_id("tree", data), files


def verify_publication(
    directory: Path, expected: str = REVIEWED_TREE
) -> dict[str, Any]:
    actual, files = tree_id(directory)
    if actual != expected:
        raise ValueError("PUBLISHED_ARTIFACT_DRIFT:" + actual)
    return {"git_tree_sha1": actual, "file_count": files}


def path_filters(text: str) -> dict[str, list[str]]:
    """Read the deliberately simple quoted path lists in this fixed workflow.

    Fail closed on an unsupported path-list syntax. This is not a YAML parser.
    """
    result: dict[str, list[str]] = {}
    event: str | None = None
    reading = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"  (pull_request|push):\s*", line)
        if match:
            event, reading = match.group(1), False
            if event in result:
                raise ValueError("DUPLICATE_WORKFLOW_EVENT")
            result[event] = []
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 2:
            event, reading = None, False
        elif event and line == "    paths:":
            reading = True
        elif indent <= 4:
            reading = False
        elif event and reading:
            if not line.startswith("      - "):
                raise ValueError("UNSUPPORTED_WORKFLOW_PATH_SYNTAX")
            value = ast.literal_eval(line[8:])
            if not isinstance(value, str) or value.startswith("!"):
                raise ValueError("POSITIVE_WORKFLOW_PATH_REQUIRED")
            result[event].append(value)
    if set(result) != {"pull_request", "push"} or not all(result.values()):
        raise ValueError("BOTH_EVENT_PATH_FILTERS_REQUIRED")
    return result


def matches(path: str, pattern: str) -> bool:
    # Match the *, ** patterns used below with GitHub's slash distinction.
    expression = re.escape(pattern).replace(r"\*\*", "\x00")
    expression = expression.replace(r"\*", "[^/]*").replace("\x00", ".*")
    return re.fullmatch(expression, path) is not None


def assert_coverage(filters: dict[str, list[str]], dependencies: set[str]) -> None:
    for event in ("pull_request", "push"):
        patterns = filters.get(event, [])
        missing = sorted(
            p for p in dependencies if not any(matches(p, x) for x in patterns)
        )
        if missing:
            raise ValueError(
                "FROZEN_DEPENDENCY_NOT_WATCHED:" + event + ":" + ",".join(missing)
            )


def verify_coverage(root: Path) -> int:
    frozen = json.loads((root / ARTIFACT_DIR / "FREEZE.json").read_text())
    campaign = json.loads((root / CAMPAIGN_FREEZE).read_text())
    dependencies = set(frozen["hashes"])
    dependencies.update(campaign["code_hashes"])
    dependencies.update(campaign["data_hashes"])
    dependencies.update(
        {
            ARTIFACT_DIR + "/FREEZE.json",
            CAMPAIGN_FREEZE,
            WORKFLOW,
            "scripts/verify_scalp7_source_ab_seal_v1.py",
            "tests/test_scalp7_source_ab_seal_v1.py",
        }
    )
    assert_coverage(path_filters((root / WORKFLOW).read_text()), dependencies)
    return len(dependencies)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    root = parser.parse_args().repo.resolve()
    publication = verify_publication(root / ARTIFACT_DIR)
    dependencies = verify_coverage(root)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.research.rebuild.scalp7_source_ab_runner_v1",
            "verify",
        ],
        cwd=root,
        check=True,
    )
    print(
        json.dumps(
            {
                "state": "PASS_PUBLISHED_SOURCE_AB_SEAL_AND_TRIGGER_COVERAGE",
                "reviewed_revision": REVIEWED_REVISION,
                "publication": publication,
                "watched_frozen_dependencies": dependencies,
                "new_economic_executions": 0,
                "order_live_authority": "BLOCKED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
