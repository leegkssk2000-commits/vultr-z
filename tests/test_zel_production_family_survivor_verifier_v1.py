from __future__ import annotations

from backend.production.zel_production_family_survivor_verifier_v1 import verify


def policy() -> dict:
    return {
        "schema_version": "zel.production_family_survivor_verifier_policy.v1",
        "mode": "PAPER",
        "evidence_path": "/tmp/evidence.json",
        "verified_survivor_intake_path": "/tmp/intake.json",
        "state_path": "/tmp/state.json",
        "required_env": {
            "min_trades": "ZEL_IMPROVE_MIN_TRADES",
            "min_expectancy": "ZEL_IMPROVE_MIN_EXPECTANCY",
            "min_profit_factor": "ZEL_IMPROVE_MIN_PF",
            "min_net_pnl": "ZEL_IMPROVE_MIN_NET_PNL",
            "max_dd_pct": "ZEL_IMPROVE_MAX_DD_PCT",
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def evidence() -> dict:
    window = {"net_pnl": 1.0, "profit_factor": 1.2, "expectancy": 0.1, "payoff_ratio": 1.1, "retention": 1.0}
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
        "metrics": {"trade_count": 100, "net_expectancy": 0.1, "profit_factor": 1.2, "net_pnl": 10.0, "max_dd_pct": 2.0},
        "receipt_sha256": "evidence-sha",
    }


def bind_env(monkeypatch) -> None:
    monkeypatch.setenv("ZEL_IMPROVE_MIN_TRADES", "60")
    monkeypatch.setenv("ZEL_IMPROVE_MIN_EXPECTANCY", "0")
    monkeypatch.setenv("ZEL_IMPROVE_MIN_PF", "1")
    monkeypatch.setenv("ZEL_IMPROVE_MIN_NET_PNL", "0")
    monkeypatch.setenv("ZEL_IMPROVE_MAX_DD_PCT", "5")


def test_missing_ssot_holds_without_intake(monkeypatch) -> None:
    for key in ("ZEL_IMPROVE_MIN_TRADES","ZEL_IMPROVE_MIN_EXPECTANCY","ZEL_IMPROVE_MIN_PF","ZEL_IMPROVE_MIN_NET_PNL","ZEL_IMPROVE_MAX_DD_PCT"):
        monkeypatch.delenv(key, raising=False)
    state, intake = verify(policy(), evidence(), now_ms=1)
    assert state["state"] == "HOLD_FAMILY_SURVIVOR_SSOT_UNBOUND"
    assert state["write_verified_intake"] is False
    assert intake is None


def test_normalized_paper_evidence_emits_verified_survivor(monkeypatch) -> None:
    bind_env(monkeypatch)
    state, intake = verify(policy(), evidence(), now_ms=2)
    assert state["state"] == "PASS_FAMILY_VERIFIED_SURVIVOR_INTAKE_READY"
    assert intake is not None
    assert intake["state"] == "PASS_ECONOMIC_SURVIVOR"
    assert intake["family_id"] == "family_a"
    assert intake["order_authority"] == "BLOCKED"
    assert intake["live_trade_authority"] == "BLOCKED"


def test_missing_evidence_holds_after_ssot_bound(monkeypatch) -> None:
    bind_env(monkeypatch)
    state, intake = verify(policy(), None, now_ms=3)
    assert state["state"] == "HOLD_FAMILY_SURVIVOR_EVIDENCE_MISSING"
    assert intake is None
