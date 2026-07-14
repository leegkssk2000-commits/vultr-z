from __future__ import annotations

import os
from pathlib import Path

from tools.q4r3_deep_storage_hygiene_hotfix import (
    safe_iter_files,
    safe_path_touches,
    safe_resolve,
    safe_walk,
)


def test_safe_walk_does_not_descend_directory_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "data.txt").write_text("x", encoding="utf-8")
    link = tmp_path / "loop"
    os.symlink(tmp_path, link)
    walked = [current for current, _dirs, _files in safe_walk(tmp_path)]
    assert real in walked
    assert link not in walked


def test_safe_iter_files_skips_symlink_files(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("data", encoding="utf-8")
    link = tmp_path / "link.txt"
    os.symlink(target, link)
    files = list(safe_iter_files(tmp_path))
    assert target in files
    assert link not in files


def test_safe_resolve_rejects_embedded_null() -> None:
    assert safe_resolve("/tmp/bad\x00path") is None


def test_safe_resolve_rejects_control_character() -> None:
    assert safe_resolve("/tmp/bad\npath") is None


def test_safe_path_touches_fails_closed_for_malformed_path() -> None:
    assert safe_path_touches(Path("/tmp/bad\x00path"), {Path("/tmp")}) is True
