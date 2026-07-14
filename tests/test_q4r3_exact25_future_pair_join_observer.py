from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools import q4r3_exact25_future_pair_join_observer as observer


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def args(tmp_path: Path, events: list[dict], ledger: list[dict]) -> SimpleNamespace:
    trigger_status = tmp_path / "trigger_status.json"
    projection_status = tmp_path / "projection_status.json"
    activation = tmp_path / "activation.json"
    events_path = tmp_path / "events.jsonl"
    ledger_path = tmp_path / "ledger.jsonl"
    write_json(trigger_status, {"state": "PASS", "observer_only": True})
    write_json(projection_status, {"state": "PASS", "profile_count": 6})
    write_json(activation, {"baseline_ledger_rows": 0, "historical_backfill_allowed": False})
    write_jsonl(events_path, events)
    write_jsonl(ledger_path, ledger)
    return SimpleNamespace(
        trigger_status=trigger_status,
        projection_status=projection_status,
        activation=activation,
        events=events_path,
        ledger=ledger_path,
        output=tmp_path / "pairs.json",
        status=tmp_path / "status.json",
        violations=tmp_path / "violations.json",
    )


def trigger() -> dict:
    return {
        "event_id": "trigger-1",
        "event_type": "skill_triggered",
        "event_ts": "2026-07-14T18:00:00+00:00",
        "position_id": "p1",
        "strategy_id": "trend_rider",
        "method_id": "intraday/breakout_probe",
        "skill_id": "SK_ENTRY_LONG_BEAM",
        "skill_version": "2.0.0-candidate",
        "symbol": "BTCUSDT",
        "side": "long",
    }


def close() -> dict:
    return {
        "event_id": "join-1",
        "event_type": "close_outcome_joined",
        "event_ts": "2026-07-14T19:00:00+00:00",
        "closed_at": "2026-07-14T19:00:00+00:00",
        "position_id": "p1",
        "strategy_id": "trend_rider",
        "method_id": "intraday/breakout_probe",
        "skill_id": "SK_ENTRY_LONG_BEAM",
        "skill_version": "2.0.0-candidate",
        "symbol": "BTCUSDT",
        "side": "long",
        "close_event_id": "close-1",
        "realized_r": 2.5,
    }


def test_waiting_forward_trigger_is_pass(tmp_path: Path) -> None:
    value = args(tmp_path, [], [])
    assert observer.run(value) == 0
    status = json.loads(value.status.read_text())
    assert status["state"] == "PASS"
    assert status["verdict"] == "FUTURE_PAIR_JOIN_HEALTHY_WAITING_FORWARD_TRIGGER"
    assert status["exact_pair_count"] == 0


def test_exact_forward_pair_is_verified(tmp_path: Path) -> None:
    value = args(tmp_path, [trigger(), close()], [{"event_id": "close-1", "position_id": "p1", "realized_r": 2.5}])
    assert observer.run(value) == 0
    status = json.loads(value.status.read_text())
    report = json.loads(value.output.read_text())
    assert status["verdict"] == "FUTURE_PAIR_JOIN_HEALTHY_EXACT_PAIRS_ACTIVE"
    assert status["exact_pair_count"] == 1
    assert report["pairs"][0]["exact_join"] is True
    assert report["pairs"][0]["pair_state"] == "EXACT_CLOSE_JOINED"


def test_close_before_trigger_is_critical(tmp_path: Path) -> None:
    bad_close = close()
    bad_close["event_ts"] = "2026-07-14T17:00:00+00:00"
    bad_close["closed_at"] = "2026-07-14T17:00:00+00:00"
    value = args(tmp_path, [trigger(), bad_close], [{"event_id": "close-1", "position_id": "p1"}])
    assert observer.run(value) == 2
    status = json.loads(value.status.read_text())
    violations = json.loads(value.violations.read_text())
    assert status["state"] == "HOLD"
    assert any(row["code"] == "CLOSE_BEFORE_TRIGGER" for row in violations["violations"])


def test_cross_position_formal_close_is_critical(tmp_path: Path) -> None:
    value = args(tmp_path, [trigger(), close()], [{"event_id": "close-1", "position_id": "p2"}])
    assert observer.run(value) == 2
    violations = json.loads(value.violations.read_text())
    assert any(row["code"] == "FORMAL_LEDGER_CROSS_POSITION_JOIN" for row in violations["violations"])
