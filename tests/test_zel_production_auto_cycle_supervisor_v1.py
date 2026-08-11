from backend.production.zel_production_auto_cycle_supervisor_v1 import (
    ProductionAutoCycleSupervisor,
    SupervisorPolicy,
    cycle_key_for,
    evaluate_improvement,
)
from backend.production.zel_production_owner_binding_v1 import ProductionEventLedger


def payload(**updates):
    row = {
        "mode": "PAPER",
        "symbol": "BTCUSDT",
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.none",
        "alpha_state": "NONE",
        "signal": "LONG",
        "risk_state": "PASS",
        "market_data_ok": True,
        "price": 100.0,
        "qty": 2.0,
        "signal_ts": "2026-08-11T00:00:00Z",
        "event_id": "event-1",
        "decision_id": "decision-1",
        "cost_model_id": "bingx.cost.bound",
    }
    row.update(updates)
    return row


def fake_result(state="READY", reason="NO_ACTION_SIGNAL"):
    return {
        "decision": {"state": state, "action": "hold", "reason": reason},
        "fill": None,
        "snapshot": {"canonical": {"snapshot_sha256": "fixture"}},
        "exchange_order_submitted": False,
    }


class Clock:
    def __init__(self, value=0.0):
        self.value = float(value)

    def __call__(self):
        return self.value


def test_duplicate_cycle_replays_without_second_execution(tmp_path):
    calls = []

    def runner(row, ledger):
        calls.append(dict(row))
        return fake_result()

    supervisor = ProductionAutoCycleSupervisor(tmp_path / "supervisor.sqlite", run_fn=runner)
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    first = supervisor.supervise(payload(), ledger)
    second = supervisor.supervise(payload(), ledger)

    assert len(calls) == 1
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert second["replayed"] is True
    assert second["exchange_order_submitted"] is False


def test_single_flight_overlap_holds_without_execution(tmp_path):
    clock = Clock(1.0)
    calls = []

    def runner(row, ledger):
        calls.append(1)
        return fake_result()

    supervisor = ProductionAutoCycleSupervisor(
        tmp_path / "supervisor.sqlite", run_fn=runner, clock=clock
    )
    row = payload()
    key = cycle_key_for(row)
    claimed = supervisor.store.claim(key, "other-owner", clock(), 30.0)
    assert claimed["kind"] == "CLAIMED"

    receipt = supervisor.supervise(row, ProductionEventLedger(tmp_path / "ledger.sqlite"))
    assert receipt["state"] == "HOLD"
    assert receipt["reason"] == "SINGLE_FLIGHT_ACTIVE"
    assert calls == []


def test_stale_lease_is_recovered_after_ttl(tmp_path):
    clock = Clock(0.0)
    calls = []

    def runner(row, ledger):
        calls.append(1)
        return fake_result()

    supervisor = ProductionAutoCycleSupervisor(
        tmp_path / "supervisor.sqlite",
        policy=SupervisorPolicy(lease_ttl_s=5.0),
        run_fn=runner,
        clock=clock,
    )
    row = payload()
    supervisor.store.claim(cycle_key_for(row), "dead-owner", clock(), 5.0)
    clock.value = 6.0

    receipt = supervisor.supervise(row, ProductionEventLedger(tmp_path / "ledger.sqlite"))
    assert receipt["state"] == "COMPLETED"
    assert receipt["stale_lease_recovered"] is True
    assert calls == [1]


def test_transient_runtime_failure_retries_within_bound(tmp_path):
    calls = []

    def runner(row, ledger):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("temporary")
        return fake_result()

    supervisor = ProductionAutoCycleSupervisor(
        tmp_path / "supervisor.sqlite",
        policy=SupervisorPolicy(max_attempts=2, retry_backoff_s=0.0, retry_budget_s=5.0),
        run_fn=runner,
        sleeper=lambda _: None,
    )
    receipt = supervisor.supervise(payload(), ProductionEventLedger(tmp_path / "ledger.sqlite"))
    assert receipt["state"] == "COMPLETED"
    assert receipt["attempts"] == 2
    assert len(calls) == 2


def test_retry_exhaustion_fails_closed_and_records_reason(tmp_path):
    def runner(row, ledger):
        raise RuntimeError("still-bad")

    supervisor = ProductionAutoCycleSupervisor(
        tmp_path / "supervisor.sqlite",
        policy=SupervisorPolicy(max_attempts=2, retry_backoff_s=0.0),
        run_fn=runner,
    )
    receipt = supervisor.supervise(payload(), ProductionEventLedger(tmp_path / "ledger.sqlite"))
    assert receipt["state"] == "FAILED"
    assert receipt["action"] == "hold"
    assert receipt["attempts"] == 2
    assert receipt["exchange_order_submitted"] is False
    assert supervisor.store.reason_counts()["RuntimeError:still-bad"] == 1


def test_missing_improvement_evidence_never_promotes():
    result = evaluate_improvement(None, SupervisorPolicy())
    assert result["state"] == "HOLD"
    assert result["promotion_allowed"] is False
    assert result["strategy_mutation_applied"] is False


def test_candidate_requires_allowlisted_knobs():
    evidence = {
        "candidate": {"candidate_id": "c1", "knobs": {"cooldown_s": 30}},
        "incumbent_id": "i1",
        "incumbent_hash": "abc",
        "sample_count": 100,
        "candidate_score": 1.2,
        "incumbent_score": 1.0,
        "candidate_max_dd_pct": 2.0,
        "incumbent_max_dd_pct": 2.0,
        "error_count": 0,
    }
    blocked = evaluate_improvement(evidence, SupervisorPolicy())
    assert blocked["reason"] == "CANDIDATE_KNOB_NOT_ALLOWLISTED"
    assert blocked["promotion_allowed"] is False

    allowed = evaluate_improvement(
        evidence, SupervisorPolicy(allowlisted_knobs=("cooldown_s",))
    )
    assert allowed["state"] == "PROMOTION_ELIGIBLE"
    assert allowed["promotion_allowed"] is True
    assert allowed["action"] == "hold"
    assert allowed["strategy_mutation_applied"] is False


def test_post_promotion_regression_requires_rollback():
    evidence = {
        "candidate": {"candidate_id": "c1", "knobs": {}},
        "incumbent_id": "i1",
        "incumbent_hash": "abc",
        "sample_count": 100,
        "candidate_score": 1.2,
        "incumbent_score": 1.0,
        "candidate_max_dd_pct": 2.0,
        "incumbent_max_dd_pct": 2.0,
        "error_count": 1,
        "promoted": True,
    }
    result = evaluate_improvement(evidence, SupervisorPolicy(error_budget=0))
    assert result["state"] == "ROLLBACK_REQUIRED"
    assert result["action"] == "rollback"
    assert result["rollback_required"] is True
    assert result["strategy_mutation_applied"] is False


def test_live_mode_remains_blocked_under_supervisor(tmp_path):
    supervisor = ProductionAutoCycleSupervisor(tmp_path / "supervisor.sqlite")
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    receipt = supervisor.supervise(
        payload(mode="LIVE", alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture"),
        ledger,
    )
    assert receipt["state"] == "HOLD"
    assert receipt["reason"] == "LIVE_NOT_ACTIVATED"
    assert receipt["result"]["decision"]["state"] == "BLOCKED"
    assert receipt["result"]["fill"] is None
    assert receipt["exchange_order_submitted"] is False
    assert receipt["strategy_mutation_applied"] is False
    assert receipt["self_modification_applied"] is False
    assert ledger.count() == 0
