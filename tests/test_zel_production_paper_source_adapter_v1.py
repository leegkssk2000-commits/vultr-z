import json

import pytest

from backend.production.zel_production_owner_binding_v1 import ProductionEventLedger, run_cycle
from backend.production.zel_production_paper_source_adapter_v1 import (
    CanonicalPaperSourceAdapter,
    build_payload,
)


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
        "cost_model_id": "bingx.cost.bound",
        "risk_request": {"leverage_x": 10, "position_pct": 10},
        "source_hashes": ["authority-source"],
        "runtime_authority": {
            "execution_authority": "PAPER_SIM_ONLY",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
    }
    row.update(updates)
    return row


def active_signal(signal_name="LONG", signal_ts=9_900):
    return {
        "schema_version": "zel.production_alpha_signal.v1",
        "state": "PASS_ACTIVE_ALPHA_SIGNAL",
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.v1",
        "symbol": "BTCUSDT",
        "signal": signal_name,
        "signal_ts": signal_ts,
        "source_hashes": ["signal-source"],
    }


def market(price=100.0):
    return {
        "state": "PASS_BINGX_FRESH",
        "symbol": "BTCUSDT",
        "age_ms": 100,
        "reference_price": price,
        "provider": "bingx_public",
        "source_timestamp_ms": 9_900,
        "spread_bps": 2.0,
        "receipt_sha256": "market-sha",
    }


def account():
    return {
        "mode": "PAPER",
        "state": "PASS_PAPER_ACCOUNT_STATE",
        "updated_at_ms": 9_900,
        "equity_usdt": 1_000.0,
        "available_balance_usdt": 1_000.0,
        "dd_day_pct": 0.0,
        "dd_total_pct": 0.0,
        "receipt_sha256": "account-sha",
    }


def test_missing_authority_emits_stable_no_alpha_without_market_or_sizing_values():
    row = build_payload(None)
    assert row["mode"] == "PAPER"
    assert row["alpha_state"] == "NONE"
    assert row["signal"] == "FLAT"
    assert row["risk_state"] == "HOLD"
    assert row["source_state"] == "NO_VALIDATED_ALPHA"
    assert row["authority_state"] == "ALPHA_AUTHORITY_MISSING"
    assert row["exchange_order_submitted"] is False
    assert "price" not in row
    assert "qty" not in row
    assert "signal_ts" not in row


def test_research_only_strategy11_style_authority_is_not_executable():
    row = build_payload(
        {
            "alpha_state": "SURVIVOR_ACTIVE",
            "research_only": True,
            "promotion_authority": False,
            "execution_allowed": False,
            "runtime_bound": False,
        }
    )
    assert row["alpha_state"] == "NONE"
    assert row["authority_state"] == "ALPHA_AUTHORITY_NON_EXECUTABLE"
    assert "price" not in row
    assert "qty" not in row


def test_active_alpha_builds_price_and_qty_only_after_all_authorities_pass():
    row = build_payload(
        authority(),
        active_signal=active_signal(),
        market_receipt=market(),
        account_state=account(),
        active_policy=active_policy(),
        risk_policy=risk_policy(),
        account_policy=account_policy(),
        now_ms=10_000,
    )
    assert row["source_state"] == "PROMOTED_ACTIVE_ALPHA"
    assert row["alpha_state"] == "SURVIVOR_ACTIVE"
    assert row["signal"] == "LONG"
    assert row["price"] == 100.0
    assert row["qty"] == 10.0
    assert row["risk"]["leverage_x"] == 10
    assert row["risk"]["position_pct"] == 10.0
    assert row["market"]["provider"] == "bingx_public"
    assert row["exchange_order_submitted"] is False


def test_executable_alpha_missing_runtime_binding_fails_closed():
    with pytest.raises(RuntimeError, match="ACTIVE_ALPHA_RUNTIME_INPUTS_REQUIRED"):
        build_payload(authority())


def test_adapter_writes_exact_canonical_no_alpha_payload(tmp_path):
    authority_path = tmp_path / "authority.json"
    output = tmp_path / "input.json"
    adapter = CanonicalPaperSourceAdapter(authority_path, output)
    row = adapter.write()
    assert output.exists()
    assert json.loads(output.read_text()) == row
    assert row["authority_state"] == "ALPHA_AUTHORITY_MISSING"
    assert "price" not in row
    assert "qty" not in row


def test_invalid_authority_json_object_contract_fails_closed(tmp_path):
    authority_path = tmp_path / "authority.json"
    output = tmp_path / "input.json"
    authority_path.write_text("[]")
    adapter = CanonicalPaperSourceAdapter(authority_path, output)
    with pytest.raises(ValueError, match="ALPHA_AUTHORITY_MUST_BE_JSON_OBJECT"):
        adapter.write()
    assert not output.exists()


def test_no_alpha_payload_runs_full_owner_cycle_without_event_or_fake_price(tmp_path):
    row = build_payload(None)
    ledger = ProductionEventLedger(tmp_path / "events.sqlite")
    result = run_cycle(row, ledger)
    assert result["decision"]["state"] == "HOLD"
    assert result["decision"]["reason"] == "NO_VALIDATED_ALPHA"
    assert result["decision"]["order_intent"] == "NONE"
    assert result["fill"] is None
    assert result["snapshot"]["canonical"]["ledger_event_count"] == 0
    assert result["exchange_order_submitted"] is False
    assert ledger.count() == 0
