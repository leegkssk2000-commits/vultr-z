from __future__ import annotations

import pytest

from backend.production.zel_production_family_survivor_verifier_v1 import verify
from backend.production.zel_production_improvement_controller_v1 import stable_sha


def contract() -> dict:
    return {
        "min_trades_per_window": 60.0,
        "min_profit_factor": 1.0,
        "min_expectancy_exclusive": 0.0,
        "min_net_pnl_exclusive": 0.0,
        "min_payoff_ratio": 1.0,
        "min_retention": 0.60,
        "max_dd_pct": 10.0,
        "source": "FROZEN_ZEL_EDGE_TO_PORTFOLIO_CONTRACT",
    }


def policy() -> dict:
    return {
        "schema_version": "zel.production_family_survivor_verifier_policy.v1",
        "mode": "PAPER",
        "evidence_path": "/tmp/evidence.json",
        "verified_survivor_intake_path": "/tmp/intake.json",
        "state_path": "/tmp/state.json",
        "survivor_contract": contract(),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def evidence() -> dict:
    window = {"trade_count": 60.0, "net_pnl": 1.0, "profit_factor": 1.2, "expectancy": 0.1, "payoff_ratio": 1.1, "retention": 1.0}
    c = contract()
    return {
        "schema_version": "zel.production_family_paper_evidence.v1",
        "state": "PASS_FAMILY_PAPER_EVIDENCE",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "family_id": "family_a",
        "strategy_id": "strategy_a",
        "alpha_id": "alpha_a",
        "source_hashes": ["source-a"],
        "risk_request": {"leverage_x": 10, "position_pct": 5},
        "windows": {"W1": dict(window), "W2": dict(window), "W3": dict(window)},
        "metrics": {"trade_count": 180, "net_expectancy": 0.1, "profit_factor": 1.2, "net_pnl": 10.0, "max_dd_pct": 2.0},
        "survivor_contract": c,
        "survivor_contract_sha256": stable_sha(c),
        "receipt_sha256": "evidence-sha",
    }


def test_missing_evidence_holds_without_global_env() -> None:
    state, intake = verify(policy(), None, now_ms=1)
    assert state["state"] == "HOLD_FAMILY_SURVIVOR_EVIDENCE_MISSING"
    assert state["write_verified_intake"] is False
    assert intake is None


def test_normalized_paper_evidence_emits_verified_survivor() -> None:
    state, intake = verify(policy(), evidence(), now_ms=2)
    assert state["state"] == "PASS_FAMILY_VERIFIED_SURVIVOR_INTAKE_READY"
    assert intake is not None
    assert intake["state"] == "PASS_ECONOMIC_SURVIVOR"
    assert intake["family_id"] == "family_a"
    assert intake["order_authority"] == "BLOCKED"
    assert intake["live_trade_authority"] == "BLOCKED"


def test_window_below_60_is_rejected() -> None:
    e = evidence()
    e["windows"]["W3"]["trade_count"] = 59.0
    e["metrics"]["trade_count"] = 179.0
    with pytest.raises(RuntimeError, match="WINDOW_TRADES_FAIL:W3"):
        verify(policy(), e, now_ms=3)


def test_dd_above_frozen_10pct_is_rejected() -> None:
    e = evidence()
    e["metrics"]["max_dd_pct"] = 10.0001
    with pytest.raises(RuntimeError, match="MAX_DD_FAIL"):
        verify(policy(), e, now_ms=4)


def test_contract_mismatch_is_rejected() -> None:
    e = evidence()
    e["survivor_contract"]["min_retention"] = 0.50
    with pytest.raises(RuntimeError, match="CONTRACT_MISMATCH"):
        verify(policy(), e, now_ms=5)
