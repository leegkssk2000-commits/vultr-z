from __future__ import annotations

import json
from pathlib import Path

from backend.production import zel_production_a1_jump_liquidity_gate_v1 as m


def policy() -> dict:
    return json.loads(Path("config/zel_production_a1_jump_liquidity_autopsy_v1.json").read_text())


def row(symbol: str, bucket: int = 1_800_000) -> dict:
    return {
        "schema_version": m.HISTORY_SCHEMA,
        "capture_bucket_ms": bucket,
        "captured_at_ms": bucket + 123,
        "symbol": symbol,
        "provider": "BINGX_PUBLIC_USDT_PERPETUAL",
        "history_gate_decision": "UNSET_BY_COLLECTOR",
        "economic_signal_enabled": False,
        "klines": [{"time_ms": bucket, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 10.0}],
        "l2": {"bids": [[100.9, 2.0], [100.8, 3.0]], "asks": [[101.1, 2.5], [101.2, 3.5]]},
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def summary() -> dict:
    return {
        "schema_version": m.SUMMARY_SCHEMA,
        "state": "PASS_BINGX_L2_PROSPECTIVE_HISTORY_ACCUMULATING",
        "prospective_history_started": True,
        "history_gate_decision": "UNSET_BY_COLLECTOR",
        "economic_signal_enabled": False,
        "observation_count_by_symbol": {"BTC-USDT": 1, "ETH-USDT": 1},
        "total_observation_count": 2,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def test_preregistered_architecture_holds_while_history_gate_is_unset():
    result = m.evaluate_gate(policy(), history_rows=[row("BTC-USDT"), row("ETH-USDT")], summary=summary(), now_ms=1_800_123)
    assert result["state"] == "HOLD_A1_JUMP_LIQUIDITY_HISTORY_ACCUMULATING"
    assert result["architecture_result"] == "PRE_REGISTERED_NOT_EVALUATED"
    assert result["admission_state"] == "HOLD_ADMISSION_TEMPLATE_REQUIRED"
    assert result["source_ready"] is False
    assert result["template_ready"] is False
    assert result["economic_replay_allowed"] is False
    ctx = result["source_context"]
    assert ctx["ohlcv_transport_bound"] is True
    assert ctx["volume_transport_bound"] is True
    assert ctx["l2_order_book_transport_bound"] is True
    assert ctx["ohlcv_source_bound"] is True
    assert ctx["volume_source_bound"] is True
    assert ctx["l2_order_book_source_bound"] is False
    assert ctx["history_coverage_bound"] is False
    assert ctx["history_gate_decision"] == "UNSET_BY_COLLECTOR"
    assert result["selection_authority"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] == "NONE"
    assert result["order_authority"] == "BLOCKED"
    assert result["live_trade_authority"] == "BLOCKED"
    assert result["exchange_order_submitted"] is False


def test_missing_latest_symbol_fails_closed():
    result = m.evaluate_gate(policy(), history_rows=[row("BTC-USDT")], summary=summary(), now_ms=1_800_123)
    assert result["state"] == "HOLD_A1_JUMP_LIQUIDITY_LATEST_SOURCE_INCOMPLETE"
    assert result["source_ready"] is False
    assert result["economic_replay_allowed"] is False


def test_policy_forbids_premature_template_replay_and_authority():
    mutations = [
        ("admission_template_id", "invented_template"),
        ("economic_replay_allowed", True),
        ("selection_authority", True),
        ("order_authority", "OPEN"),
        ("numeric_signal_thresholds", [1.0]),
        ("parameter_search", True),
    ]
    for key, value in mutations:
        bad = policy()
        bad[key] = value
        try:
            m.validate_policy(bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"{key} drift must fail closed")


def test_autopsy_has_full_strategy_architecture_and_exact_sources():
    cfg = m.validate_policy(policy())
    assert sorted(cfg["required_sources_exact"]) == ["l2_order_book", "ohlcv", "volume"]
    assert "A1-E02-SSRN-4080253" in cfg["evidence_ids"]
    assert "A1-E06-ARXIV-2602.00776" in cfg["evidence_ids"]
    assert cfg["architecture_result"] == "PRE_REGISTERED_NOT_EVALUATED"
    assert cfg["admission_state"] == "HOLD_ADMISSION_TEMPLATE_REQUIRED"
    assert cfg["admission_template_id"] is None
    assert cfg["numeric_signal_thresholds"] == []
    assert cfg["parameter_search"] is False
