import pytest

from backend.production.zel_production_risk_sizing_v1 import build_risk_sizing


def policy(**updates):
    row = {
        "schema_version": "zel.production_risk_sizing_policy.v1",
        "mode": "PAPER",
        "allowed_symbols": ["BTCUSDT", "ETHUSDT"],
        "allowed_leverage_x": [10, 15, 20],
        "allowed_position_pct": [5, 10, 15, 20],
        "conditional_25x_enabled": False,
        "market_data_stale_ms": 5_000,
        "account_state_stale_ms": 5_000,
        "max_dd_day_pct": 5.0,
        "max_dd_total_pct": 10.0,
        "required_env_when_null": {},
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    row.update(updates)
    return row


def authority(**updates):
    row = {
        "alpha_state": "SURVIVOR_ACTIVE",
        "research_only": False,
        "promotion_authority": True,
        "execution_allowed": True,
        "runtime_bound": True,
        "symbol": "BTCUSDT",
        "signal": "LONG",
        "risk_request": {"leverage_x": 10, "position_pct": 10},
        "receipt_sha256": "alpha-sha",
    }
    row.update(updates)
    return row


def market(**updates):
    row = {
        "state": "PASS_BINGX_FRESH",
        "symbol": "BTCUSDT",
        "age_ms": 100,
        "reference_price": 100.0,
        "receipt_sha256": "market-sha",
    }
    row.update(updates)
    return row


def account(**updates):
    row = {
        "mode": "PAPER",
        "state": "PASS_PAPER_ACCOUNT_STATE",
        "updated_at_ms": 9_000,
        "equity_usdt": 1_000.0,
        "available_balance_usdt": 1_000.0,
        "dd_day_pct": 0.0,
        "dd_total_pct": 0.0,
    }
    row.update(updates)
    return row


def test_long_sizing_uses_explicit_preset_without_default():
    row = build_risk_sizing(authority(), market(), account(), policy(), now_ms=10_000)
    assert row["qty"] == 10.0
    assert row["notional_usdt"] == 1_000.0
    assert row["leverage_x"] == 10
    assert row["position_pct"] == 10.0
    assert row["exposure_pct"] == 100.0
    assert row["exchange_order_submitted"] is False


def test_25x_is_rejected():
    bad = authority(risk_request={"leverage_x": 25, "position_pct": 10})
    with pytest.raises(RuntimeError, match="LEVERAGE_NOT_ALLOWED"):
        build_risk_sizing(bad, market(), account(), policy(), now_ms=10_000)


def test_stale_account_and_dd_breach_fail_closed():
    with pytest.raises(RuntimeError, match="ACCOUNT_STATE_STALE"):
        build_risk_sizing(authority(), market(), account(updated_at_ms=1), policy(), now_ms=10_000)
    with pytest.raises(RuntimeError, match="DD_DAY_EXCEEDED"):
        build_risk_sizing(authority(), market(), account(dd_day_pct=5.1), policy(), now_ms=10_000)


def test_non_active_authority_is_rejected():
    with pytest.raises(RuntimeError, match="SURVIVOR_ACTIVE"):
        build_risk_sizing(authority(alpha_state="NONE"), market(), account(), policy(), now_ms=10_000)


def test_exit_never_invents_close_quantity():
    row = build_risk_sizing(authority(signal="EXIT"), market(), account(), policy(), now_ms=10_000)
    assert row["qty"] == 0.0
    assert row["notional_usdt"] == 0.0
