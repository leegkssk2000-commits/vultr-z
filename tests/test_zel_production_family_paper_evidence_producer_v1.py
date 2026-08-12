from __future__ import annotations

import pytest

from backend.production.zel_production_family_paper_evidence_producer_v1 import tick
from backend.production.zel_production_improvement_controller_v1 import stable_sha


POLICY = {
    "schema_version": "zel.production_family_paper_evidence_producer_policy.v1",
    "state": "FROZEN_PAPER_ONLY",
    "mode": "PAPER",
    "canary_result_path": "/tmp/canary.json",
    "evidence_path": "/tmp/evidence.json",
    "state_path": "/tmp/state.json",
    "survivor_contract": {
        "min_trades_per_window": 60,
        "min_profit_factor": 1.0,
        "min_expectancy_exclusive": 0.0,
        "min_net_pnl_exclusive": 0.0,
        "min_payoff_ratio": 1.0,
        "min_retention": 0.60,
        "max_dd_pct": 10.0,
        "source": "FROZEN_ZEL_EDGE_TO_PORTFOLIO_CONTRACT",
    },
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
}


def canary() -> dict:
    windows = {
        n: {"trade_count": 60, "net_pnl": 2.0, "profit_factor": 1.2, "expectancy": 0.05, "payoff_ratio": 1.3, "retention": 0.8}
        for n in ("W1", "W2", "W3")
    }
    metrics = {"trade_count": 180, "net_expectancy": 0.05, "profit_factor": 1.2, "net_pnl": 6.0, "max_dd_pct": 4.0}
    row = {
        "schema_version": "zel.production_family_paper_canary_result.v1",
        "state": "PASS_FAMILY_PAPER_CANARY",
        "symbol_qualified": True,
        "runtime_symbol": "BTCUSDT",
        "runtime_symbol_precedence": ["BTCUSDT", "ETHUSDT"],
        "symbol_selection_method": "FROZEN_PRECEDENCE_FIRST_QUALIFIED_NO_METRIC_SEARCH",
        "symbol_evaluations": {
            "BTCUSDT": {"state": "PASS_SYMBOL_PAPER_CANARY", "windows": windows, "metrics": metrics},
            "ETHUSDT": {"state": "PENDING_SYMBOL_SAMPLE", "windows": None, "metrics": None},
        },
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "family_id": "family_x",
        "strategy_id": "strategy_x",
        "alpha_id": "alpha_x",
        "canary_key": "canary-x",
        "contract_id": "contract-x",
        "contract_receipt_sha256": "c" * 64,
        "source_hashes": ["a" * 64, "b" * 64],
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "windows": windows,
        "metrics": metrics,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def test_missing_canary_holds_without_env_dependency(monkeypatch):
    from backend.production import zel_production_family_paper_evidence_producer_v1 as m
    monkeypatch.setattr(m, "read_json", lambda *a, **k: None)
    state, evidence = tick(POLICY)
    assert state["state"] == "HOLD_FAMILY_PAPER_CANARY_MISSING"
    assert evidence is None
    assert state["order_authority"] == "BLOCKED"


def test_legacy_unqualified_canary_holds_without_writing_evidence(monkeypatch):
    from backend.production import zel_production_family_paper_evidence_producer_v1 as m
    legacy = canary()
    legacy.pop("runtime_symbol_precedence")
    monkeypatch.setattr(m, "read_json", lambda *a, **k: legacy)
    state, evidence = tick(POLICY)
    assert state["state"] == "HOLD_FAMILY_PAPER_CANARY_SYMBOL_QUALIFICATION_REQUIRED"
    assert evidence is None


def test_valid_explicit_risk_and_symbol_qualified_contract_produces_normalized_evidence(monkeypatch):
    from backend.production import zel_production_family_paper_evidence_producer_v1 as m
    monkeypatch.setattr(m, "read_json", lambda *a, **k: canary())
    state, evidence = tick(POLICY)
    assert state["state"] == "PASS_FAMILY_PAPER_EVIDENCE_READY"
    assert evidence is not None
    assert evidence["schema_version"] == "zel.production_family_paper_evidence.v1"
    assert evidence["runtime_symbol"] == "BTCUSDT"
    assert evidence["canary_key"] == "canary-x"
    assert evidence["contract_id"] == "contract-x"
    assert evidence["contract_receipt_sha256"] == "c" * 64
    assert evidence["risk_request"] == {"leverage_x": 10, "position_pct": 5.0}
    assert evidence["survivor_contract"]["min_trades_per_window"] == 60.0
    assert evidence["survivor_contract"]["max_dd_pct"] == 10.0
    assert evidence["promotion_authority"] is False
    assert evidence["order_authority"] == "BLOCKED"


def test_low_window_sample_is_rejected(monkeypatch):
    from backend.production import zel_production_family_paper_evidence_producer_v1 as m
    bad = canary()
    bad["windows"]["W2"]["trade_count"] = 59
    bad["metrics"]["trade_count"] = 179
    bad["symbol_evaluations"]["BTCUSDT"]["windows"] = bad["windows"]
    bad["symbol_evaluations"]["BTCUSDT"]["metrics"] = bad["metrics"]
    bad["receipt_sha256"] = stable_sha({k: v for k, v in bad.items() if k != "receipt_sha256"})
    monkeypatch.setattr(m, "read_json", lambda *a, **k: bad)
    with pytest.raises(RuntimeError, match="WINDOW_TRADES_FAIL:W2"):
        tick(POLICY)


def test_missing_or_disallowed_risk_never_defaults(monkeypatch):
    from backend.production import zel_production_family_paper_evidence_producer_v1 as m
    bad = canary()
    bad["risk_request"] = {"leverage_x": 25, "position_pct": 5.0}
    bad["receipt_sha256"] = stable_sha({k: v for k, v in bad.items() if k != "receipt_sha256"})
    monkeypatch.setattr(m, "read_json", lambda *a, **k: bad)
    with pytest.raises(RuntimeError, match="RISK_REQUEST_NOT_ALLOWED"):
        tick(POLICY)
