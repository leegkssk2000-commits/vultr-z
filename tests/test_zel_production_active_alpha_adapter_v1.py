import pytest

from backend.production.zel_production_active_alpha_adapter_v1 import bind_active_alpha


def policy():
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


def authority(**updates):
    row = {
        "alpha_state": "SURVIVOR_ACTIVE",
        "research_only": False,
        "promotion_authority": True,
        "execution_allowed": True,
        "runtime_bound": True,
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.v1",
        "symbol": "BTCUSDT",
        "source_hashes": ["authority-source"],
        "risk_request": {"leverage_x": 10, "position_pct": 10},
        "runtime_authority": {
            "execution_authority": "PAPER_SIM_ONLY",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
    }
    row.update(updates)
    return row


def signal(**updates):
    row = {
        "schema_version": "zel.production_alpha_signal.v1",
        "state": "PASS_ACTIVE_ALPHA_SIGNAL",
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.v1",
        "symbol": "BTCUSDT",
        "signal": "LONG",
        "signal_ts": 9_900,
        "source_hashes": ["signal-source"],
    }
    row.update(updates)
    return row


def test_promoted_authority_binds_fresh_signal():
    row = bind_active_alpha(authority(), signal(), policy(), now_ms=10_000)
    assert row["state"] == "PASS_ACTIVE_ALPHA_BOUND"
    assert row["signal"] == "LONG"
    assert row["signal_age_ms"] == 100
    assert set(row["source_hashes"]) == {"authority-source", "signal-source"}
    assert row["exchange_order_submitted"] is False


def test_stale_signal_and_identity_mismatch_fail_closed():
    with pytest.raises(RuntimeError, match="SIGNAL_STALE"):
        bind_active_alpha(authority(), signal(signal_ts=1), policy(), now_ms=10_000)
    with pytest.raises(RuntimeError, match="STRATEGY_MISMATCH"):
        bind_active_alpha(authority(), signal(strategy_id="other"), policy(), now_ms=10_000)


def test_research_only_authority_is_rejected():
    with pytest.raises(RuntimeError, match="AUTHORITY_NOT_EXECUTABLE"):
        bind_active_alpha(authority(research_only=True), signal(), policy(), now_ms=10_000)
