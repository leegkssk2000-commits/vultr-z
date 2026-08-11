from backend.production.zel_production_owner_binding_v1 import ProductionEventLedger, run_cycle
from backend.production.zel_production_paper_source_adapter_v1 import build_payload


def active_policy():
    return {
        "schema_version": "zel.production_active_alpha_policy.v1",
        "mode": "PAPER",
        "signal_stale_ms": 1_000,
        "required_env_when_null": {},
        "allowed_signals": ["LONG", "SHORT", "EXIT", "FLAT"],
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def risk_policy():
    return {
        "schema_version": "zel.production_risk_sizing_policy.v1",
        "mode": "PAPER",
        "allowed_symbols": ["BTCUSDT", "ETHUSDT"],
        "allowed_leverage_x": [10, 15, 20],
        "allowed_position_pct": [5, 10, 15, 20],
        "conditional_25x_enabled": False,
        "market_data_stale_ms": 1_000,
        "account_state_stale_ms": 1_000,
        "max_dd_day_pct": 5.0,
        "max_dd_total_pct": 10.0,
        "required_env_when_null": {},
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def account_policy():
    return {
        "schema_version": "zel.production_paper_account_policy.v1",
        "mode": "PAPER",
        "initial_equity_usdt": 1_000.0,
        "risk_day_timezone": "UTC",
        "required_env_when_null": {},
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def authority():
    return {
        "alpha_state": "SURVIVOR_ACTIVE",
        "research_only": False,
        "promotion_authority": True,
        "execution_allowed": True,
        "runtime_bound": True,
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.v1",
        "symbol": "BTCUSDT",
        "cost_model_id": "bingx.cost.bound",
        "risk_request": {"leverage_x": 10, "position_pct": 10},
        "source_hashes": ["authority-source"],
        "runtime_authority": {
            "execution_authority": "PAPER_SIM_ONLY",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
    }


def signal(name, ts):
    return {
        "schema_version": "zel.production_alpha_signal.v1",
        "state": "PASS_ACTIVE_ALPHA_SIGNAL",
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.v1",
        "symbol": "BTCUSDT",
        "signal": name,
        "signal_ts": ts,
        "source_hashes": [f"signal-{name.lower()}"],
    }


def market(price, ts):
    return {
        "state": "PASS_BINGX_FRESH",
        "symbol": "BTCUSDT",
        "age_ms": 100,
        "reference_price": price,
        "provider": "bingx_public",
        "source_timestamp_ms": ts,
        "spread_bps": 2.0,
        "receipt_sha256": f"market-{price}",
    }


def account(updated_at_ms, available=1_000.0):
    return {
        "mode": "PAPER",
        "state": "PASS_PAPER_ACCOUNT_STATE",
        "updated_at_ms": updated_at_ms,
        "equity_usdt": 1_000.0,
        "available_balance_usdt": available,
        "dd_day_pct": 0.0,
        "dd_total_pct": 0.0,
        "receipt_sha256": f"account-{updated_at_ms}",
    }


def source_payload(signal_name, price, now_ms, available=1_000.0):
    return build_payload(
        authority(),
        active_signal=signal(signal_name, now_ms - 100),
        market_receipt=market(price, now_ms - 100),
        account_state=account(now_ms - 100, available),
        active_policy=active_policy(),
        risk_policy=risk_policy(),
        account_policy=account_policy(),
        now_ms=now_ms,
    )


def test_strict_source_open_close_ledger_pnl_e2e(tmp_path):
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    opened = run_cycle(source_payload("LONG", 100.0, 10_000), ledger)
    assert opened["decision"]["order_intent"] == "OPEN_LONG"
    assert opened["snapshot"]["canonical"]["position"]["state"] == "LONG"
    assert opened["exchange_order_submitted"] is False
    assert ledger.count() == 1

    closed = run_cycle(source_payload("EXIT", 110.0, 20_000, available=0.0), ledger)
    assert closed["decision"]["order_intent"] == "CLOSE"
    assert closed["fill"]["event_type"] == "CLOSE"
    # 10x @ 10% of 1000 USDT = 1000 USDT notional = qty 10 at 100.
    assert closed["fill"]["qty"] == 10.0
    assert closed["fill"]["realized_pnl"] == 100.0
    assert ledger.count() == 2
    snap = closed["snapshot"]["canonical"]
    assert snap["position"]["state"] == "FLAT"
    assert snap["pnl"]["realized"] == 100.0
    assert snap["pnl"]["total"] == 100.0
    assert closed["snapshot"]["alimi"]["snapshot_sha256"] == snap["snapshot_sha256"]
    assert closed["snapshot"]["telegram"]["snapshot_sha256"] == snap["snapshot_sha256"]
    assert closed["exchange_order_submitted"] is False


def test_no_alpha_path_creates_no_trade_event(tmp_path):
    ledger = ProductionEventLedger(tmp_path / "ledger.sqlite")
    result = run_cycle(build_payload(None), ledger)
    assert result["decision"]["reason"] == "NO_VALIDATED_ALPHA"
    assert result["fill"] is None
    assert ledger.count() == 0
