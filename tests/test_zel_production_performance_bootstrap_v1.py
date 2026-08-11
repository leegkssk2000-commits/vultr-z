from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_performance_bootstrap_v1 import bootstrap_tick


def policy(tmp_path: Path) -> dict:
    return {
        "schema_version": "zel.production_performance_bootstrap_policy.v1",
        "state": "FROZEN_PAPER_ONLY",
        "mode": "PAPER",
        "inventory_path": "research/legacy_strategy25_inventory_v1.json",
        "queue_path": str(tmp_path / "queue.json"),
        "admission_evidence_path": str(tmp_path / "evidence.json"),
        "bootstrap_state_path": str(tmp_path / "state.json"),
        "improvement_registry_path": str(tmp_path / "registry.json"),
        "authority_path": str(tmp_path / "authority.json"),
        "seed_survivor_gate": {
            "required_windows": ["W1", "W2", "W3"],
            "require_window_net_pnl_gt_zero": True,
            "require_window_profit_factor_gte": 1.0,
            "require_window_expectancy_gt_zero": True,
            "require_window_payoff_ratio_gte": 1.0,
            "require_retention_gte": 0.6,
            "require_sample_gate_pass": True,
            "require_integrity_error_count": 0,
            "require_duplicate_count": 0,
            "require_censored_count": 0,
        },
        "admission_rules": {},
        "candidate_budget": 1,
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def queue(strategy_id: str = "squeeze_break") -> dict:
    return {
        "schema_version": "zel.strategy25.economic_recovery.v1",
        "state": "HOLD_ZERO_SURVIVOR_ADMISSION_QUEUE_READY",
        "economic_survivor_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "admission_queue": [{
            "queue_index": 0,
            "strategy_id": strategy_id,
            "route": "LOW_SAMPLE_EXTENSION_SAME_RULE",
            "state": "PENDING_ADMISSION_EVIDENCE",
        }],
    }


def evidence(state: str = "PASS_BOOTSTRAP_ADMISSION_EVIDENCE") -> dict:
    row = {
        "schema_version": "zel.production_bootstrap_admission_evidence.v1",
        "state": state,
        "strategy_id": "squeeze_break",
        "sample_gate_pass": True,
        "integrity": {"error_count": 0, "duplicate_count": 0, "censored_count": 0},
        "windows": {
            name: {
                "net_pnl": 1.0,
                "profit_factor": 1.2,
                "expectancy": 0.1,
                "payoff_ratio": 1.1,
                "retention": 0.8,
            }
            for name in ("W1", "W2", "W3")
        },
        "aggregate_metrics": {
            "trade_count": 180,
            "net_expectancy": 0.1,
            "profit_factor": 1.2,
            "net_pnl": 3.0,
            "max_dd_pct": 4.0,
            "score": 1.0,
        },
        "authority_candidate": {
            "strategy_id": "squeeze_break",
            "alpha_id": "squeeze_break.bootstrap.v1",
            "symbol": "BTCUSDT",
            "cost_model_id": "fixture-cost",
            "risk_request": {"leverage_x": 10, "position_pct": 5.0},
            "source_hashes": ["fixture-source-sha"],
            "knobs": {},
            "tunable_axes": [],
            "candidate_values": {},
        },
        "receipt_sha256": "fixture-admission-sha",
    }
    return row


def write(path: Path, row: dict) -> None:
    path.write_text(json.dumps(row), encoding="utf-8")


def test_missing_queue_holds_without_authority(tmp_path: Path) -> None:
    p = policy(tmp_path)
    result = bootstrap_tick(p, now_ms=1000)
    assert result["state"] == "HOLD_BOOTSTRAP_QUEUE_MISSING"
    assert not Path(p["authority_path"]).exists()
    assert not Path(p["improvement_registry_path"]).exists()


def test_queue_without_evidence_waits(tmp_path: Path) -> None:
    p = policy(tmp_path)
    write(Path(p["queue_path"]), queue())
    result = bootstrap_tick(p, now_ms=2000)
    assert result["state"] == "HOLD_BOOTSTRAP_WAIT_ADMISSION_EVIDENCE"
    assert result["candidate"]["strategy_id"] == "squeeze_break"
    assert not Path(p["authority_path"]).exists()


def test_rejected_evidence_routes_without_promotion(tmp_path: Path) -> None:
    p = policy(tmp_path)
    write(Path(p["queue_path"]), queue())
    rejected = evidence("REJECT_BOOTSTRAP_ADMISSION_EVIDENCE")
    write(Path(p["admission_evidence_path"]), rejected)
    result = bootstrap_tick(p, now_ms=3000)
    assert result["state"] == "HOLD_BOOTSTRAP_ADMISSION_REJECTED_ROUTE_CHANGE"
    assert result["next"] == "ROUTE_CHANGE_TO_NEXT_SOURCE_READY_ECONOMIC_FAMILY"
    assert not Path(p["authority_path"]).exists()
    assert not Path(p["improvement_registry_path"]).exists()


def test_full_seed_evidence_registers_incumbent_atomically(tmp_path: Path) -> None:
    p = policy(tmp_path)
    write(Path(p["queue_path"]), queue())
    write(Path(p["admission_evidence_path"]), evidence())
    result = bootstrap_tick(p, now_ms=4000)
    assert result["state"] == "PASS_BOOTSTRAP_SEED_INCUMBENT_REGISTERED"
    authority = json.loads(Path(p["authority_path"]).read_text())
    registry = json.loads(Path(p["improvement_registry_path"]).read_text())
    assert authority["strategy_id"] == "squeeze_break"
    assert authority["alpha_state"] == "SURVIVOR_ACTIVE"
    assert authority["execution_allowed"] is True
    assert authority["runtime_authority"]["execution_authority"] == "PAPER_SIM_ONLY"
    assert authority["runtime_authority"]["order_authority"] == "BLOCKED"
    assert registry["current_authority"]["strategy_id"] == "squeeze_break"
    assert registry["state"] == "PASS_INCUMBENT_REGISTRY"
    assert result["exchange_order_submitted"] is False
    assert result["source_code_mutation_applied"] is False


def test_seed_gate_rejects_bad_w2_without_promotion(tmp_path: Path) -> None:
    p = policy(tmp_path)
    write(Path(p["queue_path"]), queue())
    row = evidence()
    row["windows"]["W2"]["net_pnl"] = -0.01
    write(Path(p["admission_evidence_path"]), row)
    try:
        bootstrap_tick(p, now_ms=5000)
    except RuntimeError as exc:
        assert "BOOTSTRAP_WINDOW_NET_FAIL:W2" in str(exc)
    else:
        raise AssertionError("bad W2 evidence must fail closed")
    assert not Path(p["authority_path"]).exists()
    assert not Path(p["improvement_registry_path"]).exists()
