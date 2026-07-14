from __future__ import annotations

from pathlib import Path

from tools.q4r3_safe_disk_hygiene import Candidate, path_related, tree_size


def test_path_related_protects_parent_and_child(tmp_path: Path) -> None:
    protected = tmp_path / "runtime"
    child = protected / "evidence"
    sibling = tmp_path / "cache"
    child.mkdir(parents=True)
    sibling.mkdir()
    assert path_related(child, {protected}) is True
    assert path_related(protected, {child}) is True
    assert path_related(sibling, {protected}) is False


def test_tree_size_counts_regular_files(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    (root / "a.bin").write_bytes(b"a" * 10)
    nested = root / "nested"
    nested.mkdir()
    (nested / "b.bin").write_bytes(b"b" * 7)
    assert tree_size(root) >= 17


def test_candidate_defaults_are_explicit() -> None:
    item = Candidate(
        path="/tmp/example",
        category="temporary_workspace",
        size_bytes=123,
        protected=False,
        reason="unregistered_unreferenced_tmp",
    )
    assert item.protected is False
    assert item.size_bytes == 123
