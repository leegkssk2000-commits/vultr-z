from backend.production.zel_production_owner_binding_v1 import ProductionEventLedger, run_cycle


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


def test_zero_survivor_engine_runs_and_holds(tmp_path):
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    result = run_cycle(payload(), ledger)
    assert result["decision"]["state"] == "HOLD"
    assert result["decision"]["reason"] == "NO_VALIDATED_ALPHA"
    assert result["fill"] is None
    assert ledger.count() == 0
    assert result["exchange_order_submitted"] is False


def test_paper_open_close_recomputes_pnl_and_surface_parity(tmp_path):
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    opened = run_cycle(
        payload(alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture", signal="LONG", price=100.0),
        ledger,
    )
    assert opened["decision"]["order_intent"] == "OPEN_LONG"
    assert opened["fill"]["event_type"] == "OPEN_LONG"
    assert opened["snapshot"]["canonical"]["position"]["state"] == "LONG"
    assert opened["snapshot"]["canonical"]["pnl"]["realized"] == 0.0
    assert opened["exchange_order_submitted"] is False

    closed = run_cycle(
        payload(
            alpha_state="SURVIVOR_ACTIVE",
            alpha_id="alpha.fixture",
            signal="EXIT",
            price=110.0,
            event_id="event-2",
            decision_id="decision-2",
            signal_ts="2026-08-11T04:00:00Z",
        ),
        ledger,
    )
    assert closed["decision"]["order_intent"] == "CLOSE"
    assert closed["fill"]["event_type"] == "CLOSE"
    assert closed["fill"]["realized_pnl"] == 20.0
    assert ledger.count() == 2
    snap = closed["snapshot"]["canonical"]
    assert snap["position"]["state"] == "FLAT"
    assert snap["pnl"]["realized"] == 20.0
    assert snap["pnl"]["unrealized"] == 0.0
    assert snap["pnl"]["total"] == 20.0
    assert closed["snapshot"]["alimi"]["snapshot_sha256"] == snap["snapshot_sha256"]
    assert closed["snapshot"]["telegram"]["snapshot_sha256"] == snap["snapshot_sha256"]
    assert closed["snapshot"]["alimi"]["snapshot"] == closed["snapshot"]["telegram"]["snapshot"]


def test_shadow_uses_noop_execution_but_records_simulated_fill(tmp_path):
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    result = run_cycle(
        payload(mode="SHADOW", alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture", signal="SHORT", price=100.0),
        ledger,
    )
    assert result["decision"]["order_intent"] == "OPEN_SHORT"
    assert result["fill"]["execution_result"]["effective_route"] == "noop"
    assert result["fill"]["exchange_order_submitted"] is False
    assert ledger.position("BTCUSDT", "alpha_primary")["state"] == "SHORT"


def test_duplicate_open_and_close_are_not_written(tmp_path):
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    first = payload(alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture", signal="LONG", price=100.0)
    run_cycle(first, ledger)
    again = run_cycle(first, ledger)
    assert again["decision"]["reason"] == "DUPLICATE_OPEN_FORBIDDEN"
    assert ledger.count() == 1

    close = payload(
        alpha_state="SURVIVOR_ACTIVE",
        alpha_id="alpha.fixture",
        signal="EXIT",
        price=105.0,
        event_id="event-2",
        decision_id="decision-2",
        signal_ts="2026-08-11T04:00:00Z",
    )
    run_cycle(close, ledger)
    close_again = run_cycle(close, ledger)
    assert close_again["decision"]["reason"] == "DUPLICATE_CLOSE_FORBIDDEN"
    assert ledger.count() == 2


def test_live_never_routes_exchange_order(tmp_path):
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    result = run_cycle(
        payload(mode="LIVE", alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture", signal="LONG"),
        ledger,
    )
    assert result["decision"]["state"] == "BLOCKED"
    assert result["decision"]["reason"] == "LIVE_NOT_ACTIVATED"
    assert result["fill"] is None
    assert ledger.count() == 0
    assert result["exchange_order_submitted"] is False


def test_market_data_failure_holds_before_order(tmp_path):
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    result = run_cycle(
        payload(alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture", market_data_ok=False),
        ledger,
    )
    assert result["decision"]["reason"] == "MARKET_DATA_INTEGRITY_FAIL"
    assert ledger.count() == 0
