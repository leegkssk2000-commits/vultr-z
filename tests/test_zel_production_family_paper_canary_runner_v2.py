from __future__ import annotations

import pytest

from backend.production.zel_production_family_paper_canary_runner_v2 import evaluate_canary, validate_policy
from backend.production.zel_production_improvement_controller_v1 import stable_sha


SURVIVOR = {
    "min_trades_per_window": 60,
    "min_profit_factor": 1.0,
    "min_expectancy_exclusive": 0.0,
    "min_net_pnl_exclusive": 0.0,
    "min_payoff_ratio": 1.0,
    "min_retention": 0.60,
    "max_dd_pct": 10.0,
    "source": "FROZEN_ZEL_EDGE_TO_PORTFOLIO_CONTRACT",
}


def meta() -> dict:
    return {
        "canary_key": "canary-key",
        "family_id": "basis_oi_deleveraging",
        "strategy_id": "basis_oi_deleveraging_v1",
        "alpha_id": "basis_oi_deleveraging__canary",
        "contract_id": "contract-1",
        "contract_receipt_sha256": "c" * 64,
        "first_request_receipt_sha256": "d" * 64,
        "first_not_before_ms": 1000,
        "execution_cost_bps": 0.0,
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "risk_policy_sha256": "e" * 64,
        "survivor_contract": SURVIVOR,
        "survivor_contract_sha256": stable_sha(SURVIVOR),
        "initial_lineage": {"template_sha256": "f" * 64},
    }


def history(symbol: str, trade_bps: list[float], *, start_ms: int = 1000) -> list[dict]:
    price = 100.0
    rows: list[dict] = []
    for idx in range(len(trade_bps) + 1):
        row = {
            "schema_version": "zel.production_ai_admission_observation.v1",
            "contract_id": "contract-1",
            "family_id": "basis_oi_deleveraging",
            "template_id": "basis_oi_deleveraging_v1",
            "symbol": symbol,
            "observed_at_ms": start_ms + idx * 3_600_000,
            "outcome_candle_ts_ms": start_ms + idx * 3_600_000,
            "outcome_close": price,
            "context_pass": idx < len(trade_bps),
            "signal_side": 1 if idx < len(trade_bps) else 0,
            "canary_key": "canary-key",
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }
        row["receipt_sha256"] = stable_sha(row)
        rows.append(row)
        if idx < len(trade_bps):
            price *= 1.0 + trade_bps[idx] / 10_000.0
    return rows


def pass_window(scale: float = 1.0) -> list[float]:
    return [20.0 * scale] * 40 + [-10.0 * scale] * 20


def reject_window() -> list[float]:
    return [5.0] * 20 + [-10.0] * 40


def test_combined_180_trades_cannot_fake_one_runtime_symbol() -> None:
    rows = history("BTC-USDT", pass_window() + pass_window()[:30])
    rows += history("ETH-USDT", pass_window() + pass_window()[:30], start_ms=2000)
    result = evaluate_canary(meta(), rows)
    assert result is None


def test_single_symbol_needs_full_three_60_trade_windows() -> None:
    rows = history("BTC-USDT", pass_window() * 3)
    rows += history("ETH-USDT", pass_window(), start_ms=2000)
    result = evaluate_canary(meta(), rows)
    assert result is not None
    assert result["state"] == "PASS_FAMILY_PAPER_CANARY"
    assert result["runtime_symbol"] == "BTCUSDT"
    assert result["symbol_qualified"] is True
    assert result["symbol_evaluations"]["BTCUSDT"]["trade_count"] == 180
    assert result["symbol_evaluations"]["ETHUSDT"]["state"] == "PENDING_SYMBOL_SAMPLE"
    assert result["metrics"]["trade_count"] == 180


def test_fixed_precedence_selects_btc_when_both_symbols_pass_even_if_eth_is_stronger() -> None:
    rows = history("BTC-USDT", pass_window(1.0) * 3)
    rows += history("ETH-USDT", pass_window(3.0) * 3, start_ms=2000)
    result = evaluate_canary(meta(), rows)
    assert result is not None
    assert result["state"] == "PASS_FAMILY_PAPER_CANARY"
    assert result["runtime_symbol"] == "BTCUSDT"
    assert result["runtime_symbol_precedence"] == ["BTCUSDT", "ETHUSDT"]
    assert result["symbol_selection_method"] == "FROZEN_PRECEDENCE_FIRST_QUALIFIED_NO_METRIC_SEARCH"
    assert result["symbol_evaluations"]["ETHUSDT"]["metrics"]["net_expectancy"] > result["symbol_evaluations"]["BTCUSDT"]["metrics"]["net_expectancy"]


def test_btc_reject_eth_pending_keeps_accumulating_instead_of_terminal_reject() -> None:
    rows = history("BTC-USDT", reject_window() * 3)
    rows += history("ETH-USDT", pass_window(), start_ms=2000)
    assert evaluate_canary(meta(), rows) is None


def test_eth_can_qualify_when_btc_is_fully_rejected() -> None:
    rows = history("BTC-USDT", reject_window() * 3)
    rows += history("ETH-USDT", pass_window() * 3, start_ms=2000)
    result = evaluate_canary(meta(), rows)
    assert result is not None
    assert result["state"] == "PASS_FAMILY_PAPER_CANARY"
    assert result["runtime_symbol"] == "ETHUSDT"
    assert result["economic_gate_pass"] is True
    assert result["durability_gate_pass"] is True
    assert result["integrity_pass"] is True


def test_both_symbols_full_and_failed_terminally_reject_family_canary() -> None:
    rows = history("BTC-USDT", reject_window() * 3)
    rows += history("ETH-USDT", reject_window() * 3, start_ms=2000)
    result = evaluate_canary(meta(), rows)
    assert result is not None
    assert result["state"] == "REJECT_FAMILY_PAPER_CANARY"
    assert result["runtime_symbol"] is None
    assert result["symbol_qualified"] is False


def test_policy_requires_frozen_symbol_precedence() -> None:
    policy = {
        "schema_version": "zel.production_family_paper_canary_runner_policy.v1",
        "state": "FROZEN_PAPER_ONLY",
        "mode": "PAPER",
        "request_path": "/tmp/request.json",
        "handoff_state_path": "/tmp/handoff.json",
        "contract_state_path": "/tmp/contracts.json",
        "template_registry_path": "/tmp/templates.json",
        "l2_snapshot_path": "/tmp/l2.json",
        "carry_snapshot_path": "/tmp/carry.json",
        "history_dir": "/tmp/history",
        "state_path": "/tmp/state.json",
        "result_path": "/tmp/result.json",
        "terminal_result_path": "/tmp/terminal.json",
        "family_evidence_policy_path": "/tmp/evidence-policy.json",
        "risk_policy_path": "/tmp/risk.json",
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "runtime_symbol_precedence": ["BTCUSDT", "ETHUSDT"],
        "outcome_timeframe": "1h",
        "windows": ["W1", "W2", "W3"],
        "trades_per_window": 60,
        "retention_semantics": "WINDOW_EXPECTANCY_DIV_W1_EXPECTANCY",
        "risk_basis": "MINIMUM_FROZEN_PAPER_EXPOSURE",
        "numeric_signal_thresholds": [],
        "parameter_search": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }
    assert validate_policy(policy)["runtime_symbol_precedence"] == ["BTCUSDT", "ETHUSDT"]
    policy["runtime_symbol_precedence"] = ["ETHUSDT", "BTCUSDT"]
    with pytest.raises(RuntimeError, match="RUNTIME_SYMBOL_PRECEDENCE_DRIFT"):
        validate_policy(policy)
