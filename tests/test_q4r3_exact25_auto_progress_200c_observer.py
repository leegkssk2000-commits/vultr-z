from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_exact25_auto_progress_200c_observer.py"
spec = importlib.util.spec_from_file_location("auto_progress", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def observer(**extra):
    payload = {
        "state": "PASS",
        "verdict": "HEALTHY",
        "observer_only": True,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
    }
    payload.update(extra)
    return payload


def evaluate(tmp_path: Path, count: int, status_count: int | None = None):
    current = count if status_count is None else status_count
    paths = {name: tmp_path / f"{name}.json" for name in (
        "storage", "checkpoint", "integrity", "trigger", "projection", "pair", "risk", "scoreboard"
    )}
    return module.evaluate(
        ledger_lines=[f'{{"event_id":"c{i}"}}' for i in range(count)],
        storage={"state": "PASS", "verdict": "STORAGE_REGROWTH_GUARD_HEALTHY"},
        checkpoint_100=observer(current_closed_count=current),
        integrity=observer(
            current_closed_count=current,
            critical_count=0,
            major_count=0,
            integrity_gate_locked=False,
            lineage_coverage_pct=100.0,
        ),
        trigger=observer(skill_triggered_count=1, skill_blocked_count=3, close_outcome_joined_count=1),
        projection=observer(profile_count=6),
        pair=observer(exact_pair_count=1),
        risk=observer(scenario_count=12),
        scoreboard=observer(method_count=6),
        snapshot_100_path=tmp_path / "snapshot_100.json",
        snapshot_200_path=tmp_path / "snapshot_200.json",
        source_paths=paths,
    )


def test_95c_accumulates_to_100c(tmp_path: Path) -> None:
    status, violations = evaluate(tmp_path, 95)
    assert status["state"] == "PASS"
    assert status["stage"] == "ACCUMULATING_TO_100C"
    assert status["remaining_to_100c"] == 5
    assert status["remaining_to_200c"] == 105
    assert violations["count"] == 0


def test_100c_creates_snapshot_and_continues(tmp_path: Path) -> None:
    status, _ = evaluate(tmp_path, 100)
    assert status["stage"] == "ACCUMULATING_100C_TO_200C"
    assert status["snapshot_100_ready"] is True
    assert (tmp_path / "snapshot_100.json").exists()
    assert status["producer_stop_at_100c"] is False


def test_waits_for_100c_observer_refresh(tmp_path: Path) -> None:
    status, _ = evaluate(tmp_path, 100, status_count=99)
    assert status["state"] == "PASS"
    assert status["stage"] == "WAITING_100C_OBSERVER_REFRESH"


def test_200c_creates_second_snapshot(tmp_path: Path) -> None:
    status, _ = evaluate(tmp_path, 200)
    assert status["stage"] == "REACHED_200C"
    assert status["snapshot_100_ready"] is True
    assert status["snapshot_200_ready"] is True
    assert status["producer_stop_at_200c"] is False
    assert status["verdict"] == "AUTO_PROGRESS_200C_REACHED_MIDPOINT_AUDIT_REQUIRED"


def test_integrity_lock_holds_at_100c(tmp_path: Path) -> None:
    status, violations = module.evaluate(
        ledger_lines=[f'{{"event_id":"c{i}"}}' for i in range(100)],
        storage={"state": "PASS", "verdict": "STORAGE_REGROWTH_GUARD_HEALTHY"},
        checkpoint_100=observer(current_closed_count=100),
        integrity=observer(
            current_closed_count=100,
            state="HOLD",
            critical_count=1,
            major_count=0,
            integrity_gate_locked=True,
            lineage_coverage_pct=100.0,
        ),
        trigger=observer(),
        projection=observer(),
        pair=observer(),
        risk=observer(),
        scoreboard=observer(),
        snapshot_100_path=tmp_path / "snapshot_100.json",
        snapshot_200_path=tmp_path / "snapshot_200.json",
        source_paths={},
    )
    assert status["state"] == "HOLD"
    assert status["critical_count"] >= 1
    assert violations["count"] >= 1
