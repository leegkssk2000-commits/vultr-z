import json
from pathlib import Path

from backend.production.zel_production_improvement_controller_v1 import controller_tick


def write(path: Path, row):
    path.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")


def policy(tmp_path):
    return {
        "schema_version": "zel.production_improvement_policy.v1",
        "mode": "PAPER",
        "candidate_budget": 2,
        "mutation_class": "CONFIG_ONLY",
        "registry_path": str(tmp_path / "registry.json"),
        "authority_path": str(tmp_path / "authority.json"),
        "evidence_path": str(tmp_path / "evidence.json"),
        "candidate_queue_path": str(tmp_path / "queue.json"),
        "thresholds": {
            "min_trades": 30,
            "min_expectancy": 0.01,
            "min_profit_factor": 1.1,
            "min_net_pnl": 1.0,
            "max_dd_pct": 10.0,
            "min_score_gain": 0.1,
            "max_dd_regression_pct": 1.0,
            "error_budget": 0,
        },
        "required_env_when_null": {},
        "candidate_rules": {
            "max_changed_axes": 1,
            "allow_new_features": False,
            "allow_new_strategy_family": False,
            "allow_source_code_mutation": False,
            "require_incumbent_candidate_values": True,
        },
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def integrity():
    return {
        "source_parity": True,
        "ledger_parity": True,
        "cost_parity": True,
        "paper_only": True,
        "no_live_orders": True,
        "error_count": 0,
    }


def metrics(score=1.0, expectancy=0.1, pf=1.5, pnl=10.0, dd=5.0, trades=60):
    return {
        "trade_count": trades,
        "net_expectancy": expectancy,
        "profit_factor": pf,
        "net_pnl": pnl,
        "max_dd_pct": dd,
        "score": score,
    }


def seed_authority():
    return {
        "strategy_id": "alpha_primary",
        "alpha_id": "alpha.seed",
        "symbol": "BTCUSDT",
        "cost_model_id": "bingx.cost.bound",
        "risk_request": {"leverage_x": 10, "position_pct": 10},
        "source_hashes": ["seed-source"],
        "knobs": {"hold_hours": 4},
        "tunable_axes": ["hold_hours"],
        "candidate_values": {"hold_hours": [4, 6, 8]},
    }


def test_no_incumbent_no_evidence_holds_without_mutation(tmp_path):
    row = controller_tick(policy(tmp_path), now_ms=1_000)
    assert row["state"] == "HOLD_NO_SEED_SURVIVOR"
    assert not (tmp_path / "authority.json").exists()
    assert row["exchange_order_submitted"] is False


def test_seed_promote_candidate_promote_then_health_rollback(tmp_path):
    cfg = policy(tmp_path)
    evidence_path = Path(cfg["evidence_path"])

    write(
        evidence_path,
        {
            "schema_version": "zel.production_improvement_evidence.v1",
            "state": "PASS_IMPROVEMENT_EVIDENCE",
            "kind": "SEED_SURVIVOR",
            "integrity": integrity(),
            "authority_candidate": seed_authority(),
            "metrics": metrics(score=1.0),
            "receipt_sha256": "seed-evidence",
        },
    )
    seeded = controller_tick(cfg, now_ms=1_000)
    assert seeded["state"] == "PROMOTED_SEED_INCUMBENT"
    authority = json.loads(Path(cfg["authority_path"]).read_text())
    assert authority["alpha_state"] == "SURVIVOR_ACTIVE"
    assert authority["runtime_authority"]["execution_authority"] == "PAPER_SIM_ONLY"
    assert authority["runtime_authority"]["order_authority"] == "BLOCKED"
    queue = json.loads(Path(cfg["candidate_queue_path"]).read_text())
    assert queue["candidate_count"] == 2
    assert {row["changed_axis"] for row in queue["candidates"]} == {"hold_hours"}
    assert {row["knob_changes"]["hold_hours"] for row in queue["candidates"]} == {6, 8}

    candidate = queue["candidates"][0]
    write(
        evidence_path,
        {
            "schema_version": "zel.production_improvement_evidence.v1",
            "state": "PASS_IMPROVEMENT_EVIDENCE",
            "kind": "CANDIDATE_COMPARISON",
            "integrity": integrity(),
            "candidate": candidate,
            "incumbent_metrics": metrics(score=1.0, dd=5.0),
            "candidate_metrics": metrics(score=1.3, dd=5.5, pnl=15.0),
            "receipt_sha256": "candidate-evidence",
        },
    )
    promoted = controller_tick(cfg, now_ms=2_000)
    assert promoted["state"] == "PROMOTED_NEW_INCUMBENT"
    promoted_authority = json.loads(Path(cfg["authority_path"]).read_text())
    assert promoted_authority["knobs"]["hold_hours"] == candidate["knob_changes"]["hold_hours"]
    assert promoted_authority["alpha_id"].startswith("alpha.seed.cfg.")
    registry = json.loads(Path(cfg["registry_path"]).read_text())
    assert len(registry["history"]) == 1

    write(
        evidence_path,
        {
            "schema_version": "zel.production_improvement_evidence.v1",
            "state": "PASS_IMPROVEMENT_EVIDENCE",
            "kind": "INCUMBENT_HEALTH",
            "integrity": integrity(),
            "metrics": metrics(score=-1.0, expectancy=-0.5, pf=0.5, pnl=-20.0, dd=20.0),
            "receipt_sha256": "health-regression",
        },
    )
    rolled = controller_tick(cfg, now_ms=3_000)
    assert rolled["state"] == "ROLLED_BACK_TO_PREVIOUS_INCUMBENT"
    assert rolled["action"] == "rollback"
    rolled_authority = json.loads(Path(cfg["authority_path"]).read_text())
    assert rolled_authority["alpha_id"] == "alpha.seed"
    assert rolled_authority["knobs"]["hold_hours"] == 4
    assert rolled_authority["exchange_order_submitted"] is False


def test_same_evidence_is_idempotent(tmp_path):
    cfg = policy(tmp_path)
    evidence_path = Path(cfg["evidence_path"])
    row = {
        "schema_version": "zel.production_improvement_evidence.v1",
        "state": "PASS_IMPROVEMENT_EVIDENCE",
        "kind": "SEED_SURVIVOR",
        "integrity": integrity(),
        "authority_candidate": seed_authority(),
        "metrics": metrics(),
        "receipt_sha256": "same-evidence",
    }
    write(evidence_path, row)
    controller_tick(cfg, now_ms=1_000)
    replay = controller_tick(cfg, now_ms=2_000)
    assert replay["state"] == "HOLD_EVIDENCE_ALREADY_APPLIED"
