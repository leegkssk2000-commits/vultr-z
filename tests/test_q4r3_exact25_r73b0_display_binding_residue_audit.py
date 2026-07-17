from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b0_audit_display_binding_residue_v3.py"
SPEC = importlib.util.spec_from_file_location("r73b0", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_static_6c_lock_is_classified(tmp_path: Path) -> None:
    path = write(tmp_path, "telegram_lock.py", 'OWNER="S4G8R7F8T_TELEGRAM_ONLY_6C_LOCK"\n')
    hits = module.matching_lines(path)
    assert module.classify(str(path), hits, set()) == "STATIC_DISPLAY_LOCK"


def test_backup_is_not_owner(tmp_path: Path) -> None:
    path = write(tmp_path, "legacy_backup_view.py", "telegram view writer\n")
    hits = module.matching_lines(path)
    assert module.classify(str(path), hits, set()) == "ARCHIVE_OR_BACKUP"


def test_active_writer_is_candidate(tmp_path: Path) -> None:
    path = write(tmp_path, "display-writer.service", "ExecStart=/usr/local/bin/view_writer.py\n")
    hits = module.matching_lines(path)
    assert module.classify(str(path), hits, {path.name}) == "ACTIVE_OVERWRITER_CANDIDATE"


def test_active_consumer_is_owner_candidate(tmp_path: Path) -> None:
    path = write(tmp_path, "telegram-reader.service", "ExecStart=/usr/local/bin/telegram_reader.py\n")
    hits = module.matching_lines(path)
    assert module.classify(str(path), hits, {path.name}) == "CANONICAL_OWNER_CANDIDATE"


def test_inactive_view_path_is_residue(tmp_path: Path) -> None:
    path = write(tmp_path, "old_view.py", "render /view\n")
    hits = module.matching_lines(path)
    assert module.classify(str(path), hits, set()) == "DISABLED_RESIDUE"


def test_position_is_not_false_positive_for_pos(tmp_path: Path) -> None:
    path = write(tmp_path, "alpha.py", "position_id = 'paper.1'\n")
    assert module.matching_lines(path) == []


def test_closed_word_is_not_false_positive_without_closed_count(tmp_path: Path) -> None:
    path = write(tmp_path, "alpha.py", "state = 'closed'\n")
    assert module.matching_lines(path) == []


def test_exact_pos_command_is_detected(tmp_path: Path) -> None:
    path = write(tmp_path, "telegram.py", "COMMAND = '/pos'\n")
    hits = module.matching_lines(path)
    assert hits and "pos" in hits[0]["terms"]


def test_unrelated_file_has_no_hits(tmp_path: Path) -> None:
    path = write(tmp_path, "alpha.py", "def add(a, b): return a + b\n")
    assert module.matching_lines(path) == []


def test_large_file_is_skipped(tmp_path: Path, monkeypatch) -> None:
    path = write(tmp_path, "view.json", "/view")
    monkeypatch.setattr(module, "MAX_BYTES", 1)
    assert module.matching_lines(path) == []


def test_missing_optional_root_is_reported_not_required(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    roots, missing = module.unique_existing([existing, tmp_path / "optional-missing"])
    assert roots == [existing]
    assert missing == [str(tmp_path / "optional-missing")]


def test_duplicate_systemd_symlink_targets_are_deduplicated(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    roots, missing = module.unique_existing([real, alias])
    assert len(roots) == 1
    assert missing == []
