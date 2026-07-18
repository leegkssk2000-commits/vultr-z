from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/q4r3_exact25_r73b4u6_restore_pos_source.py"
SPEC = importlib.util.spec_from_file_location("r73b4u6_restore", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_command_count_requires_all_three_commands() -> None:
    source = "A='/pos'\nB='/pnl'\nC='/view'\n"
    assert module.command_count(source) >= 3


def test_select_clean_backup_rejects_ast_rewrite(tmp_path: Path) -> None:
    bad = tmp_path / "telegram.1.py"
    bad.write_text("_r73b4u3_payload = 1\nA='/pos'\nB='/pnl'\nC='/view'\n", encoding="utf-8")
    good = tmp_path / "telegram.2.py"
    good.write_text("A='/pos'\nB='/pnl'\nC='/view'\n", encoding="utf-8")
    assert module.select_clean_backup(str(tmp_path / "telegram.*.py")) == good


def test_clean_backup_compiles(tmp_path: Path) -> None:
    path = tmp_path / "telegram.1.py"
    path.write_text("def handler():\n    return ('/pos', '/pnl', '/view')\n", encoding="utf-8")
    assert module.select_clean_backup(str(tmp_path / "telegram.*.py")) == path
