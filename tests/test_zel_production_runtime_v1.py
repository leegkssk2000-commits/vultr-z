from fastapi.testclient import TestClient

from backend.production.zel_production_runtime_v1 import create_app


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


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEL_PRODUCTION_LEDGER_PATH", str(tmp_path / "events.sqlite"))
    monkeypatch.setenv("ZEL_PRODUCTION_SNAPSHOT_PATH", str(tmp_path / "snapshot.json"))
    monkeypatch.setenv("ZEL_PRODUCTION_SUPERVISOR_PATH", str(tmp_path / "supervisor.sqlite"))
    return TestClient(create_app())


def test_no_alpha_hold_runtime_and_snapshot(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post("/api/production/cycle", json=payload())
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["reason"] == "NO_VALIDATED_ALPHA"
    assert body["fill"] is None
    assert body["snapshot"]["ledger_event_count"] == 0
    assert body["exchange_order_submitted"] is False
    health = c.get("/api/production/health").json()
    assert health["ledger_event_count"] == 0
    assert health["auto_cycle_supervisor"] == "READY"
    assert health["exchange_order_submission"] is False
    assert health["strategy_mutation_applied"] is False
    assert health["self_modification_applied"] is False


def test_paper_open_close_snapshot_parity(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    opened = c.post("/api/production/cycle", json=payload(alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture"))
    assert opened.status_code == 200
    assert opened.json()["snapshot"]["position"]["state"] == "LONG"

    closed = c.post("/api/production/cycle", json=payload(
        alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture", signal="EXIT", price=110.0,
        event_id="event-2", decision_id="decision-2", signal_ts="2026-08-11T04:00:00Z"
    ))
    assert closed.status_code == 200
    snap = closed.json()["snapshot"]
    assert snap["position"]["state"] == "FLAT"
    assert snap["pnl"]["realized"] == 20.0
    assert snap["ledger_event_count"] == 2

    prod = c.get("/api/production/snapshot").json()["snapshot"]
    alimi = c.get("/api/alimi/production").json()
    assert prod["snapshot_sha256"] == snap["snapshot_sha256"]
    assert alimi["snapshot_sha256"] == snap["snapshot_sha256"]
    assert alimi["snapshot"] == prod
    assert alimi["order_mutation"] == "blocked"


def test_live_blocked_runtime(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post("/api/production/cycle", json=payload(mode="LIVE", alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture"))
    assert r.status_code == 200
    assert r.json()["decision"]["reason"] == "LIVE_NOT_ACTIVATED"
    assert r.json()["snapshot"]["ledger_event_count"] == 0
    assert r.json()["exchange_order_submitted"] is False


def test_auto_cycle_runtime_is_idempotent_and_persists_snapshot(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    row = payload(alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture", cycle_id="cycle-1")
    first = c.post("/api/production/auto-cycle", json=row)
    second = c.post("/api/production/auto-cycle", json=row)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["state"] == "COMPLETED"
    assert first.json()["result"]["fill"]["event_type"] == "OPEN_LONG"
    assert second.json()["replayed"] is True
    assert first.json()["receipt_sha256"] == second.json()["receipt_sha256"]
    assert c.get("/api/production/snapshot").json()["snapshot"]["position"]["state"] == "LONG"
    assert c.get("/api/production/health").json()["ledger_event_count"] == 1


def test_auto_cycle_live_stays_blocked(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post(
        "/api/production/auto-cycle",
        json=payload(mode="LIVE", alpha_state="SURVIVOR_ACTIVE", alpha_id="alpha.fixture", cycle_id="live-1"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "HOLD"
    assert body["reason"] == "LIVE_NOT_ACTIVATED"
    assert body["result"]["fill"] is None
    assert body["exchange_order_submitted"] is False
    assert body["strategy_mutation_applied"] is False
    assert body["self_modification_applied"] is False


def test_existing_alimi_router_is_mounted(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.get("/api/alimi/health")
    assert r.status_code == 200
    assert r.json()["service"] == "alimi"
