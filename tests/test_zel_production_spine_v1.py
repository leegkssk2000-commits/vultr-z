from backend.production.zel_production_spine_v1 import build_ledger_event, evaluate_spine


def base_payload():
    return {
        "mode": "SHADOW",
        "symbol": "BTCUSDT",
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.none",
        "alpha_state": "NONE",
        "signal": "LONG",
        "risk_state": "PASS",
        "position_state": "FLAT",
        "market_data_ok": True,
        "signal_ts": "2026-08-11T00:00:00Z",
        "position_id": "paper.test.1",
        "cost_model_id": "bingx.cost.bound",
    }


def test_zero_survivor_holds_but_engine_runs():
    row = evaluate_spine(base_payload())
    assert row.state == "HOLD"
    assert row.action == "hold"
    assert row.order_intent == "NONE"
    assert row.reason == "NO_VALIDATED_ALPHA"


def test_shadow_validated_alpha_builds_simulated_order_plan():
    p = base_payload()
    p.update(alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.real.1")
    row = evaluate_spine(p)
    assert row.state == "ORDER_PLAN_READY"
    assert row.order_intent == "OPEN_LONG"
    assert row.submit_exchange_order is False
    assert row.ledger_event_required is True
    ledger = build_ledger_event(p, row)
    assert ledger["simulated"] is True
    assert ledger["exchange_order_submitted"] is False
    assert ledger["event_sha256"]


def test_live_is_blocked_even_with_valid_alpha():
    p = base_payload()
    p.update(mode="LIVE", alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.real.1")
    row = evaluate_spine(p)
    assert row.state == "BLOCKED"
    assert row.action == "block"
    assert row.reason == "LIVE_NOT_ACTIVATED"
    assert row.submit_exchange_order is False


def test_duplicate_open_is_forbidden():
    p = base_payload()
    p.update(alpha_state="SURVIVOR_ACTIVE", position_state="LONG", alpha_id="alpha.real.1")
    row = evaluate_spine(p)
    assert row.order_intent == "NONE"
    assert row.reason == "DUPLICATE_OPEN_FORBIDDEN"


def test_exit_requires_existing_position():
    p = base_payload()
    p.update(alpha_state="SURVIVOR_ACTIVE", signal="EXIT", position_state="LONG", alpha_id="alpha.real.1")
    row = evaluate_spine(p)
    assert row.order_intent == "CLOSE"
    assert row.ledger_event_required is True


def test_market_integrity_fail_holds():
    p = base_payload()
    p.update(market_data_ok=False, alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.real.1")
    row = evaluate_spine(p)
    assert row.state == "HOLD"
    assert row.reason == "MARKET_DATA_INTEGRITY_FAIL"


def test_emergency_stop_precedes_everything():
    p = base_payload()
    p.update(emergency_stop=True)
    row = evaluate_spine(p)
    assert row.state == "STOPPED"
    assert row.action == "stop"
    assert row.order_intent == "NONE"
