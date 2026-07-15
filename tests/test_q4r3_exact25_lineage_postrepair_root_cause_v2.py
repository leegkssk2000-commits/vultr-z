from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_exact25_lineage_postrepair_root_cause_v2.py"
SPEC = importlib.util.spec_from_file_location("postrepair", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def close(pid: str, start: str, end: str) -> dict:
    return {"position_id": pid, "entry_ts": start, "exit_ts": end, "event_type": "closed"}


def invocation(ts: str, failed: bool = False) -> dict:
    value = module.parse_ts(ts)
    assert value is not None
    return {"start_ts": value, "end_ts": value + 0.2, "failed": failed, "invocation_id": ts}


def test_no_invocation_during_open_is_cadence_gap() -> None:
    row = module.classify_gap(
        close("p1", "2026-07-15T12:00:00+00:00", "2026-07-15T12:00:05+00:00"),
        [],
        [invocation("2026-07-15T12:00:10+00:00")],
    )
    assert row["cause"] == "MISSED_OPEN_WINDOW_NO_OBSERVER_INVOCATION"
    assert row["observer_invocation_count_between"] == 0


def test_failed_invocation_is_separate_cause() -> None:
    row = module.classify_gap(
        close("p2", "2026-07-15T12:00:00+00:00", "2026-07-15T12:00:30+00:00"),
        [],
        [invocation("2026-07-15T12:00:10+00:00", failed=True)],
    )
    assert row["cause"] == "OBSERVER_INVOCATION_FAILED_DURING_OPEN"


def test_invocation_without_skill_is_envelope_gap() -> None:
    row = module.classify_gap(
        close("p3", "2026-07-15T12:00:00+00:00", "2026-07-15T12:00:30+00:00"),
        [{"position_id": "p3", "method_id": "m1"}],
        [invocation("2026-07-15T12:00:10+00:00")],
    )
    assert row["cause"] == "OBSERVER_INVOKED_WITHOUT_EXPLICIT_SKILL"


def test_invocation_with_skill_without_event_is_write_gap() -> None:
    row = module.classify_gap(
        close("p4", "2026-07-15T12:00:00+00:00", "2026-07-15T12:00:30+00:00"),
        [{"position_id": "p4", "skill_id": "SK_PARTIAL30"}],
        [invocation("2026-07-15T12:00:10+00:00")],
    )
    assert row["cause"] == "OBSERVER_INVOKED_WITH_SKILL_BUT_NO_EVENT"
    assert row["explicit_skill_values"] == ["SK_PARTIAL30"]


def test_journal_groups_by_systemd_invocation(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    rows = [
        {"_SYSTEMD_INVOCATION_ID": "a", "__REALTIME_TIMESTAMP": "1780000000000000", "MESSAGE": "start", "PRIORITY": "6"},
        {"_SYSTEMD_INVOCATION_ID": "a", "__REALTIME_TIMESTAMP": "1780000000100000", "MESSAGE": "done", "PRIORITY": "6"},
        {"_SYSTEMD_INVOCATION_ID": "b", "__REALTIME_TIMESTAMP": "1780000010000000", "MESSAGE": "Traceback", "PRIORITY": "3"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    invocations, errors = module.journal_invocations(path)
    assert not errors
    assert len(invocations) == 2
    assert invocations[0]["failed"] is False
    assert invocations[1]["failed"] is True


def test_runner_contract_contains_no_runtime_mutation() -> None:
    runner = (ROOT / "tools/run_q4r3_exact25_lineage_postrepair_root_cause_v2.sh").read_text(encoding="utf-8")
    forbidden = (
        "systemctl restart", "systemctl stop", "systemctl start", "systemctl enable",
        "systemctl disable", "systemctl mask", "systemctl unmask", "sed -i",
        "git reset", "git clean", "git checkout", "git switch", "rm -rf",
    )
    for token in forbidden:
        assert token not in runner
    assert "cmp -n" in runner
    assert "journalctl" in runner


def test_runner_normalizes_rfc3339_for_journalctl() -> None:
    runner = (ROOT / "tools/run_q4r3_exact25_lineage_postrepair_root_cause_v2.sh").read_text(encoding="utf-8")
    assert "datetime.fromisoformat" in runner
    assert "astimezone(timezone.utc)" in runner
    assert "strftime('%Y-%m-%d %H:%M:%S UTC')" in runner
    assert 'journalctl -u "$OBSERVER_UNIT" --since "$JOURNAL_SINCE"' in runner
    assert 'journalctl -u "$OBSERVER_UNIT" --since "$ACTIVATED_AT"' not in runner
    assert "OBSERVER_JOURNAL_EMPTY_AFTER_ACTIVATION" in runner
