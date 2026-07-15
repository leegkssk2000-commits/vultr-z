from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_exact25_lineage_cadence_repair_guard.py"
RUNNER_PATH = ROOT / "tools/run_q4r3_exact25_lineage_cadence_repair_job.sh"

spec = importlib.util.spec_from_file_location("lineage_repair", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def activation() -> dict:
    return {
        "schema": "q4r3_exact25_lineage_cadence_repair_activation_v1",
        "baseline_formal_ledger_rows": 2,
        "baseline_skill_event_rows": 1,
        "known_prior_gap_count": 15,
        "root_cause": "MISSED_OPEN_WINDOW_NO_OBSERVER_TICK",
        "observer_interval_sec": 10,
        "historical_backfill_allowed": False,
    }


def close(pid: str) -> dict:
    return {"event_id": f"{pid}:close", "position_id": pid, "event_type": "CLOSED"}


def event(pid: str, kind: str = "skill_blocked") -> dict:
    return {"event_id": f"{pid}:{kind}", "position_id": pid, "event_type": kind}


def evaluate(formal: list[dict], events: list[dict]):
    return module.evaluate(
        activation=activation(),
        formal_rows=formal,
        formal_errors=[],
        event_rows=events,
        event_errors=[],
    )


def test_armed_without_new_closes_is_pass() -> None:
    status, violations = evaluate([close("old1"), close("old2")], [event("old1")])
    assert status["state"] == "PASS"
    assert status["verdict"] == "LINEAGE_CADENCE_REPAIR_ARMED_WAITING_FORWARD_CLOSE"
    assert status["known_prior_gap_count"] == 15
    assert status["known_prior_gaps_used_for_skill_performance"] is False
    assert violations["count"] == 0


def test_twenty_forward_closes_with_lineage_pass_canary() -> None:
    old_formal = [close("old1"), close("old2")]
    old_events = [event("old1")]
    new_formal = [close(f"new{i}") for i in range(20)]
    new_events = [event(f"new{i}", "skill_triggered" if i % 2 else "skill_blocked") for i in range(20)]
    status, violations = evaluate(old_formal + new_formal, old_events + new_events)
    assert status["state"] == "PASS"
    assert status["verdict"] == "LINEAGE_CADENCE_REPAIR_20C_PASS"
    assert status["post_repair_close_count"] == 20
    assert status["post_repair_coverage_pct"] == 100.0
    assert status["remaining_to_canary"] == 0
    assert violations["count"] == 0


def test_new_close_without_lineage_holds() -> None:
    status, violations = evaluate([close("old1"), close("old2"), close("new1")], [event("old1")])
    assert status["state"] == "HOLD"
    assert status["verdict"] == "LINEAGE_CADENCE_REPAIR_NEW_GAP_DETECTED"
    assert status["post_repair_uncovered_count"] == 1
    assert violations["severity"] == "C"


def test_runner_changes_only_observer_timer_and_repair_sidecar() -> None:
    text = RUNNER_PATH.read_text(encoding="utf-8")
    assert "OnUnitInactiveSec=${INTERVAL_SEC}s" in text
    assert "INTERVAL_SEC=10" in text
    assert 'systemctl restart "$OBSERVER_UNIT.timer"' in text
    assert 'systemctl restart "$PRODUCER_UNIT"' not in text
    assert 'systemctl restart "$WRITER_UNIT"' not in text
    assert "git reset" not in text
    assert "git clean" not in text
    assert "historical_backfill_performed\":False" in text
    assert 'cmp -n "$LEDGER_SIZE_BEFORE"' in text


def test_no_runtime_authority() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for required in (
        '"paper_enabled": False',
        '"live_enabled": False',
        '"order_enabled": False',
        '"order_authority": "blocked"',
        '"execution_authority": "none"',
        '"formal_ledger_modified": False',
    ):
        assert required in source
