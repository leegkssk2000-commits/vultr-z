from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "q4r3_exact25_lineage_gap_root_cause.py"
SPEC = importlib.util.spec_from_file_location("diag", MODULE_PATH)
assert SPEC and SPEC.loader
diag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diag)


def test_missed_window_classification() -> None:
    close = {
        "position_id": "p1",
        "entry_ts": "2026-07-15T12:00:00+00:00",
        "exit_ts": "2026-07-15T12:00:30+00:00",
    }
    row = diag.classify_gap(close, [], [], [diag.parse_ts("2026-07-15T12:01:00+00:00")])
    assert row["cause"] == "MISSED_OPEN_WINDOW_NO_OBSERVER_TICK"
    assert row["confidence"] == "HIGH"


def test_tick_without_skill_classification() -> None:
    close = {
        "position_id": "p2",
        "entry_ts": "2026-07-15T12:00:00+00:00",
        "exit_ts": "2026-07-15T12:02:00+00:00",
    }
    runs = [diag.parse_ts("2026-07-15T12:01:00+00:00")]
    row = diag.classify_gap(close, [{"position_id": "p2", "method_id": "m1"}], [], runs)
    assert row["cause"] == "OBSERVER_TICK_WITHOUT_EXPLICIT_SKILL"
    assert row["method_values"] == ["m1"]


def test_tick_with_skill_but_no_event_classification() -> None:
    close = {
        "position_id": "p3",
        "entry_ts": "2026-07-15T12:00:00+00:00",
        "exit_ts": "2026-07-15T12:02:00+00:00",
    }
    runs = [diag.parse_ts("2026-07-15T12:01:00+00:00")]
    row = diag.classify_gap(close, [{"position_id": "p3", "skill_id": "SK_PARTIAL30"}], [], runs)
    assert row["cause"] == "OBSERVER_TICK_WITH_SKILL_BUT_NO_EVENT"
    assert row["explicit_skill_values"] == ["SK_PARTIAL30"]


def test_runner_contains_no_mutating_commands() -> None:
    runner = (Path(__file__).parents[1] / "tools" / "run_q4r3_exact25_lineage_gap_root_cause_readonly.sh").read_text()
    forbidden = (
        "systemctl restart", "systemctl stop", "systemctl start", "systemctl enable",
        "systemctl disable", "systemctl mask", "systemctl unmask",
        "git reset", "git clean", "git checkout", "git switch", "git merge",
        "sed -i", "rm -rf", "chmod ", "chown ",
    )
    for token in forbidden:
        assert token not in runner
    assert "cmp -n" in runner
    assert "/tmp/ZEL_EXACT25_LINEAGE_ROOT_CAUSE_" in runner
