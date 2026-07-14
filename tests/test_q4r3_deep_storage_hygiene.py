from __future__ import annotations

from pathlib import Path

from tools.q4r3_deep_storage_hygiene import (
    content_manifest,
    path_touches,
    quick_manifest,
    retention_set,
)


def test_manifests_distinguish_content_with_equal_sizes(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "x.txt").write_text("abc", encoding="utf-8")
    (second / "x.txt").write_text("xyz", encoding="utf-8")
    assert quick_manifest(first) == quick_manifest(second)
    assert content_manifest(first) != content_manifest(second)


def test_content_manifest_matches_exact_duplicate(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "x.txt").write_text("same", encoding="utf-8")
    (second / "x.txt").write_text("same", encoding="utf-8")
    assert content_manifest(first) == content_manifest(second)


def test_path_touches_detects_reference_inside_snapshot(tmp_path: Path) -> None:
    snapshot = tmp_path / "backups" / "20260101"
    target = snapshot / "state.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    assert path_touches(snapshot, {target}) is True


def test_retention_keeps_newest_and_oldest(tmp_path: Path) -> None:
    children = []
    for index in range(8):
        path = tmp_path / f"snapshot-{index}"
        path.mkdir()
        path.touch()
        children.append(path)
    ordered = list(reversed(children))
    keep = retention_set(ordered)
    assert set(ordered[:5]).issubset(keep)
    assert ordered[-1] in keep
