import json

from backend.production.zel_production_auto_cycle_supervisor_v1 import ProductionAutoCycleSupervisor
from backend.production.zel_production_owner_binding_v1 import ProductionEventLedger
from backend.production.zel_production_paper_loop_v1 import (
    JsonFilePayloadProvider,
    PaperLoopPolicy,
    ProductionPaperLoop,
)


def payload(**updates):
    row = {
        "mode": "PAPER",
        "symbol": "BTCUSDT",
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.fixture",
        "alpha_state": "SURVIVOR_ACTIVE",
        "signal": "LONG",
        "risk_state": "PASS",
        "market_data_ok": True,
        "price": 100.0,
        "qty": 2.0,
        "signal_ts": "2026-08-11T04:00:00Z",
        "event_id": "event-1",
        "decision_id": "decision-1",
        "cost_model_id": "bingx.cost.bound",
    }
    row.update(updates)
    return row


def make_loop(tmp_path, provider, **policy_updates):
    ledger = ProductionEventLedger(tmp_path / "events.sqlite")
    supervisor = ProductionAutoCycleSupervisor(tmp_path / "supervisor.sqlite")
    policy = PaperLoopPolicy(**policy_updates) if policy_updates else PaperLoopPolicy(interval_s=0.0)
    loop = ProductionPaperLoop(
        payload_provider=provider,
        ledger=ledger,
        supervisor=supervisor,
        snapshot_path=tmp_path / "snapshot.json",
        state_path=tmp_path / "loop-state.json",
        policy=policy,
        sleeper=lambda _: None,
    )
    return loop, ledger


def test_missing_input_is_idle_and_does_not_touch_ledger(tmp_path):
    loop, ledger = make_loop(tmp_path, lambda: None)
    state = loop.run_once()
    assert state["state"] == "IDLE"
    assert state["reason"] == "PAPER_INPUT_MISSING"
    assert state["idle_count"] == 1
    assert state["circuit_open"] is False
    assert ledger.count() == 0
    assert state["exchange_order_submitted"] is False
    assert state["strategy_mutation_applied"] is False
    assert state["self_modification_applied"] is False
    assert state["live_execution"] == "BLOCKED"


def test_paper_payload_runs_supervisor_and_persists_snapshot(tmp_path):
    row = payload(cycle_id="paper-cycle-1")
    loop, ledger = make_loop(tmp_path, lambda: row)
    state = loop.run_once()
    assert state["state"] == "COMPLETED"
    assert state["cycles_executed"] == 1
    assert state["last_cycle_key"] == "paper-cycle-1"
    assert state["last_receipt_sha256"]
    assert ledger.count() == 1

    snapshot = json.loads((tmp_path / "snapshot.json").read_text())
    assert snapshot["position"]["state"] == "LONG"
    assert snapshot["ledger_event_count"] == 1
    assert snapshot["snapshot_sha256"] == state["last_snapshot_sha256"]


def test_unchanged_payload_is_deduplicated_before_second_supervisor_cycle(tmp_path):
    row = payload(cycle_id="paper-cycle-1")
    loop, ledger = make_loop(tmp_path, lambda: row)
    first = loop.run_once()
    second = loop.run_once()
    assert first["cycles_executed"] == 1
    assert second["state"] == "IDLE"
    assert second["reason"] == "PAPER_INPUT_UNCHANGED"
    assert second["cycles_executed"] == 1
    assert ledger.count() == 1


def test_changed_exit_payload_closes_existing_paper_position(tmp_path):
    rows = iter(
        [
            payload(cycle_id="paper-open-1"),
            payload(
                cycle_id="paper-close-1",
                signal="EXIT",
                price=110.0,
                signal_ts="2026-08-11T04:05:00Z",
                event_id="event-2",
                decision_id="decision-2",
            ),
        ]
    )
    loop, ledger = make_loop(tmp_path, lambda: next(rows))
    opened = loop.run_once()
    closed = loop.run_once()
    assert opened["state"] == "COMPLETED"
    assert closed["state"] == "COMPLETED"
    assert closed["cycles_executed"] == 2
    assert ledger.count() == 2

    snapshot = json.loads((tmp_path / "snapshot.json").read_text())
    assert snapshot["position"]["state"] == "FLAT"
    assert snapshot["pnl"]["realized"] == 20.0


def test_live_payload_is_hard_blocked_before_supervisor_and_opens_circuit(tmp_path):
    loop, ledger = make_loop(tmp_path, lambda: payload(mode="LIVE", cycle_id="live-cycle-1"))
    state = loop.run_once()
    assert state["state"] == "CIRCUIT_OPEN"
    assert state["reason"] == "PAPER_LOOP_REJECT_NON_PAPER_MODE:LIVE"
    assert state["circuit_open"] is True
    assert ledger.count() == 0
    assert not (tmp_path / "snapshot.json").exists()
    assert state["exchange_order_submitted"] is False
    assert state["strategy_mutation_applied"] is False
    assert state["self_modification_applied"] is False


def test_missing_mode_is_also_hard_blocked(tmp_path):
    row = payload()
    row.pop("mode")
    loop, ledger = make_loop(tmp_path, lambda: row)
    state = loop.run_once()
    assert state["state"] == "CIRCUIT_OPEN"
    assert state["reason"] == "PAPER_LOOP_REJECT_NON_PAPER_MODE:MISSING"
    assert ledger.count() == 0


def test_provider_failures_trip_bounded_circuit_breaker(tmp_path):
    def broken_provider():
        raise ValueError("broken-json")

    loop, ledger = make_loop(
        tmp_path,
        broken_provider,
        interval_s=0.0,
        max_consecutive_failures=2,
    )
    first = loop.run_once()
    second = loop.run_once()
    third = loop.run_once()
    assert first["state"] == "FAILED"
    assert first["consecutive_failures"] == 1
    assert second["state"] == "CIRCUIT_OPEN"
    assert second["consecutive_failures"] == 2
    assert third["state"] == "CIRCUIT_OPEN"
    assert third["reason"] == "PAPER_LOOP_CIRCUIT_OPEN"
    assert ledger.count() == 0


def test_circuit_reset_is_explicit_and_returns_to_idle(tmp_path):
    current = {"row": payload(mode="LIVE", cycle_id="live-cycle-1")}
    loop, ledger = make_loop(tmp_path, lambda: current["row"])
    blocked = loop.run_once()
    assert blocked["circuit_open"] is True

    reset = loop.reset_circuit()
    assert reset["circuit_open"] is False
    assert reset["reason"] == "CIRCUIT_RESET_EXPLICIT"

    current["row"] = None
    idle = loop.run_once()
    assert idle["state"] == "IDLE"
    assert idle["reason"] == "PAPER_INPUT_MISSING"
    assert ledger.count() == 0


def test_run_forever_is_bounded_for_verification(tmp_path):
    loop, ledger = make_loop(tmp_path, lambda: None)
    state = loop.run_forever(max_iterations=3)
    assert state["iterations"] == 3
    assert state["idle_count"] == 3
    assert ledger.count() == 0


def test_json_file_provider_rejects_non_object_input(tmp_path):
    path = tmp_path / "input.json"
    path.write_text("[]")
    provider = JsonFilePayloadProvider(path)
    try:
        provider()
    except ValueError as exc:
        assert str(exc) == "PAPER_INPUT_MUST_BE_JSON_OBJECT"
    else:
        raise AssertionError("expected ValueError")
