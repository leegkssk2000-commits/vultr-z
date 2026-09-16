from pathlib import Path
import subprocess

import pytest

from scripts.verify_scalp7_source_ab_seal_v1 import (
    assert_coverage,
    git_object_id,
    matches,
    path_filters,
    tree_id,
    verify_publication,
)

PUBLICATIONS = (
    "BASELINE_DIFF.md",
    "FREEZE.json",
    "OCCUPANCY_TRACE.json",
    "PA.json",
    "PA.trades.json.gz",
    "PAB.json",
    "PAB.trades.json.gz",
    "PB.json",
    "PB.trades.json.gz",
    "REPORT.md",
    "RESULTS.json",
    "SOURCES.md",
    "SOURCE_RECEIPTS.json",
    "SUMMARY.json",
    "WORK_NEXT.txt",
)


@pytest.fixture
def published(tmp_path):
    for name in PUBLICATIONS:
        (tmp_path / name).write_bytes((name + "\n").encode())
    return tmp_path, tree_id(tmp_path)[0]


@pytest.mark.parametrize("name", PUBLICATIONS)
def test_each_published_artifact_change_is_rejected(published, name):
    root, expected = published
    (root / name).write_bytes(b"changed result or claim\n")
    with pytest.raises(ValueError, match="PUBLISHED_ARTIFACT_DRIFT"):
        verify_publication(root, expected)


def test_unchanged_publication_is_valid(published):
    root, expected = published
    assert verify_publication(root, expected)["file_count"] == len(PUBLICATIONS)


@pytest.mark.parametrize("change", ("add", "delete", "executable"))
def test_publication_membership_and_mode_are_pinned(published, change):
    root, expected = published
    if change == "add":
        (root / "UNREVIEWED_PASS.txt").write_text("PASS")
    elif change == "delete":
        (root / "REPORT.md").unlink()
    else:
        (root / "REPORT.md").chmod(0o755)
    with pytest.raises(ValueError, match="PUBLISHED_ARTIFACT_DRIFT"):
        verify_publication(root, expected)


def test_symlink_is_not_followed(published):
    root, expected = published
    (root / "unreviewed").symlink_to(root / "REPORT.md")
    with pytest.raises(ValueError, match="SYMLINK"):
        verify_publication(root, expected)


def test_git_tree_encoding_matches_git(tmp_path):
    (tmp_path / "a.c").write_text("one\n")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x").write_text("two\n")
    (tmp_path / "z").write_text("three\n")
    (tmp_path / "z").chmod(0o755)
    expected, count = tree_id(tmp_path)
    assert count == 3
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.c", "a", "z"], check=True)
    actual = subprocess.check_output(
        ["git", "-C", str(tmp_path), "write-tree"], text=True
    ).strip()
    assert actual == expected
    assert git_object_id("blob", b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


@pytest.mark.parametrize("event", ("pull_request", "push"))
def test_missing_dependency_in_either_event_fails(event):
    filters = {"pull_request": ["backend/**"], "push": ["backend/**"]}
    filters[event] = ["tests/**"]
    with pytest.raises(ValueError, match="FROZEN_DEPENDENCY_NOT_WATCHED:" + event):
        assert_coverage(filters, {"backend/research/rebuild/scalp7_execution_v2.py"})


def test_workflow_covers_code_parent_results_and_new_guard():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github/workflows/scalp7-source-ab-saved-v1.yml").read_text()
    filters = path_filters(text)
    assert filters["pull_request"] == filters["push"]
    assert_coverage(
        filters,
        {
            "backend/research/rebuild/scalp7_execution_v2.py",
            "backend/research/rebuild/scalp7_metrics_v2.py",
            "backend/research/rebuild/scalp7_positive_lanes_v2.py",
            "backend/research/rebuild/scalp7_rolling_context_v2.py",
            "backend/research/rebuild/economic7_campaign_registry_v1.py",
            "backend/research/rebuild/benchmark25_donor_state_machine_v2.json",
            "research/campaigns/scalp7_20260915/broad_rebuild_v2/results/parent.json",
            "research/campaigns/scalp7_20260916/source_ab_v1/REPORT.md",
            "scripts/verify_scalp7_source_ab_seal_v1.py",
            "tests/test_scalp7_source_ab_seal_v1.py",
        },
    )
    assert not matches("backend/sub/a.py", "backend/*.py")
    assert matches("backend/sub/a.py", "backend/**")


@pytest.mark.parametrize(
    "text",
    (
        "on:\n  push:\n",
        "on:\n  pull_request:\n    paths:\n      - '!backend/**'\n",
    ),
)
def test_unsupported_or_incomplete_workflow_fails_closed(text):
    with pytest.raises(ValueError):
        path_filters(text)
