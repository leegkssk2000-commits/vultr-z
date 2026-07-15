from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools/q4r3_team_advisor_r21_bot_sgrade_revalidation.py"
spec = importlib.util.spec_from_file_location("r21", MODULE)
assert spec and spec.loader
r21 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r21)


def test_all_four_bots_are_scoped() -> None:
    assert set(r21.BOT_SPECS) == {"LBot", "MBot", "OBot", "SBot"}
    assert set(r21.BOT_FILES) == set(r21.BOT_SPECS)


def test_current_lbot_is_detected_as_thin_wrapper() -> None:
    row = r21.inspect_bot(ROOT, "LBot")
    assert row["generic_passthrough"] is True
    assert row["s_grade_ready"] is False


def test_current_mbot_is_detected_as_thin_wrapper() -> None:
    row = r21.inspect_bot(ROOT, "MBot")
    assert row["generic_passthrough"] is True
    assert row["s_grade_ready"] is False


def test_current_obot_is_detected_as_thin_wrapper() -> None:
    row = r21.inspect_bot(ROOT, "OBot")
    assert row["generic_passthrough"] is True
    assert row["s_grade_ready"] is False


def test_sbot_has_explicit_logic_but_is_not_yet_full_sgrade() -> None:
    row = r21.inspect_bot(ROOT, "SBot")
    assert row["generic_passthrough"] is False
    assert row["explicit_logic_lines"] >= 1
    assert row["s_grade_ready"] is False
