from backend.production.zel_production_paper_account_state_v1 import build_account_state


def policy():
    return {
        "schema_version": "zel.production_paper_account_policy.v1",
        "mode": "PAPER",
        "initial_equity_usdt": 1_000.0,
        "risk_day_timezone": "UTC",
        "required_env_when_null": {},
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def snapshot(total=0.0, state="FLAT"):
    return {
        "canonical": {
            "pnl": {"total": total},
            "position": {"state": state},
        }
    }


def test_initial_state_without_snapshot_is_flat_and_zero_dd():
    row = build_account_state(policy=policy(), snapshot=None, prior=None, now_ms=1_000)
    assert row["equity_usdt"] == 1_000.0
    assert row["available_balance_usdt"] == 1_000.0
    assert row["dd_day_pct"] == 0.0
    assert row["dd_total_pct"] == 0.0


def test_closed_profit_updates_equity():
    row = build_account_state(policy=policy(), snapshot=snapshot(20.0), prior=None, now_ms=1_000)
    assert row["equity_usdt"] == 1_020.0
    assert row["pnl_total_usdt"] == 20.0


def test_prior_peak_produces_total_drawdown():
    prior = {
        "initial_equity_usdt": 1_000.0,
        "peak_equity_usdt": 1_100.0,
        "risk_day": "1970-01-01",
        "day_start_equity_usdt": 1_100.0,
    }
    row = build_account_state(policy=policy(), snapshot=snapshot(50.0), prior=prior, now_ms=2_000)
    assert round(row["dd_total_pct"], 6) == round((1_100.0 - 1_050.0) / 1_100.0 * 100.0, 6)


def test_open_position_blocks_new_available_margin():
    row = build_account_state(policy=policy(), snapshot=snapshot(0.0, "LONG"), prior=None, now_ms=1_000)
    assert row["available_balance_usdt"] == 0.0
