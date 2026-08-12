from __future__ import annotations

import os

import pytest

from backend.production.zel_production_family_paper_evidence_producer_v1 import tick


POLICY = {
    "schema_version": "zel.production_family_paper_evidence_producer_policy.v1",
    "state": "FROZEN_PAPER_ONLY",
    "mode": "PAPER",
    "canary_result_path": "/tmp/canary.json",
    "evidence_path": "/tmp/evidence.json",
    "state_path": "/tmp/state.json",
    "required_ssot_env": [
        "ZEL_IMPROVE_MIN_TRADES",
        "ZEL_IMPROVE_MIN_EXPECTANCY",
        "ZEL_IMPROVE_MIN_PF",
        "ZEL_IMPROVE_MIN_NET_PNL",
        "ZEL_IMPROVE_MAX_DD_PCT",
    ],
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
}


def bind_env(monkeypatch):
    for key, value in {
        "ZEL_IMPROVE_MIN_TRADES": "60",
        "ZEL_IMPROVE_MIN_EXPECTANCY": "0.01",
        "ZEL_IMPROVE_MIN_PF": "1.1",
        "ZEL_IMPROVE_MIN_NET_PNL": "1.0",
        "ZEL_IMPROVE_MAX_DD_PCT": "10.0",
    }.items():
        monkeypatch.setenv(key, value)


def canary():
    return {
        "schema_version": "zel.production_family_paper_canary_result.v1",
        "state": "PASS_FAMILY_PAPER_CANARY",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "family_id": "family_x",
        "strategy_id": "strategy_x",
        "alpha_id": "alpha_x",
        "source_hashes": ["sha-a", "sha-b"],
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "windows": {
            n: {"net_pnl": 2.0, "profit_factor": 1.2, "expectancy": 0.05, "payoff_ratio": 1.3, "retention": 0.8}
            for n in ("W1", "W2", "W3")
        },
        "metrics": {"trade_count": 100, "net_expectancy": 0.05, "profit_factor": 1.2, "net_pnl": 6.0, "max_dd_pct": 4.0},
    }


def test_missing_ssot_is_hold(monkeypatch):
    from backend.production import zel_production_family_paper_evidence_producer_v1 as m
    monkeypatch.setattr(m, "read_json", lambda *a, **k: canary())
    state, evidence = tick(POLICY)
    assert state["state"] == "HOLD_FAMILY_PAPER_EVIDENCE_SSOT_UNBOUND"
    assert evidence is None
    assert state["order_authority"] == "BLOCKED"


def test_valid_explicit_risk_and_ssot_produces_normalized_evidence(monkeypatch):
    from backend.production import zel_production_family_paper_evidence_producer_v1 as m
    bind_env(monkeypatch)
    monkeypatch.setattr(m, "read_json", lambda *a, **k: canary())
    state, evidence = tick(POLICY)
    assert state["state"] == "PASS_FAMILY_PAPER_EVIDENCE_READY"
    assert evidence is not None
    assert evidence["schema_version"] == "zel.production_family_paper_evidence.v1"
    assert evidence["risk_request"] == {"leverage_x": 10, "position_pct": 5.0}
    assert evidence["ssot_binding"]["bound"] is True
    assert "values" not in evidence["ssot_binding"]
    assert evidence["promotion_authority"] is False
    assert evidence["order_authority"] == "BLOCKED"


def test_missing_or_disallowed_risk_never_defaults(monkeypatch):
    from backend.production import zel_production_family_paper_evidence_producer_v1 as m
    bind_env(monkeypatch)
    bad = canary()
    bad["risk_request"] = {"leverage_x": 25, "position_pct": 5.0}
    monkeypatch.setattr(m, "read_json", lambda *a, **k: bad)
    with pytest.raises(RuntimeError, match="RISK_REQUEST_NOT_ALLOWED"):
        tick(POLICY)
