from __future__ import annotations

import json
from pathlib import Path

from backend.research.strategy11_ensemble_correlation_analyzer_v1 import analyze_candidates
from backend.research.strategy11_portfolio_governor_v1 import govern_portfolio

OUT = Path("artifacts/strategy11_portfolio_governor_v1")

CORRELATION_POLICY = {
    "policy_id": "FIXTURE_CORRELATION_ONLY",
    "max_cosine_similarity": 0.85,
    "max_abs_pnl_correlation": 0.80,
    "max_loss_concurrence": 0.70,
    "max_drawdown_concurrence": 0.85,
    "rolling_window": 4,
    "min_combination_size": 2,
    "max_combination_size": 3,
    "max_candidate_combinations": 3,
}

GOVERNOR_POLICY = {
    "policy_id": "FIXTURE_ONLY_NOT_PRODUCTION_THRESHOLD_AUTHORITY",
    "portfolio_notional_usdt": 10000.0,
    "min_weight_pct": 20.0,
    "max_weight_pct": 80.0,
    "weight_step_pct": 10.0,
    "max_turnover_pct": 100.0,
    "max_joint_drawdown_r": 0.45,
    "min_cost_adjusted_net_r": 0.50,
    "min_net_retention_ratio": 0.90,
    "max_material_count": 3,
    "max_target_candidates": 3,
    "rebalance_tolerance_pct": 5.0,
}


def sha(char: str) -> str:
    return char * 64


def candidate(strategy_id: str, marker: str, classification: str, rows: list[tuple[str, float, str, str]]) -> dict:
    return {
        "strategy_id": strategy_id,
        "candidate_sha": sha(marker),
        "proposal_sha": sha(marker.upper()),
        "classification_sha": sha(str((int(marker, 16) + 1) % 10)),
        "classification": classification,
        "trades": [
            {"timestamp": timestamp, "net_r": net_r, "symbol": symbol, "regime": regime}
            for timestamp, net_r, symbol, regime in rows
        ],
    }


def material(candidate_row: dict, current_weight: float, risk_budget: float) -> dict:
    return {
        "strategy_id": candidate_row["strategy_id"],
        "candidate_sha": candidate_row["candidate_sha"],
        "proposal_sha": candidate_row["proposal_sha"],
        "classification_sha": candidate_row["classification_sha"],
        "current_weight_pct": current_weight,
        "risk_budget_pct": risk_budget,
        "capacity_notional_usdt": 20000.0,
        "turnover_cost_r": 0.05,
        "trades": candidate_row["trades"],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    alpha = candidate("alpha_combo", "a", "CORE", [
        ("t01", 1.0, "BTCUSDT", "UPTREND"),
        ("t03", -0.5, "ETHUSDT", "RANGE"),
        ("t05", 1.2, "SOLUSDT", "UPTREND"),
        ("t07", -0.4, "BTCUSDT", "HIGH_VOL"),
        ("t09", 1.0, "ETHUSDT", "UPTREND"),
    ])
    turtle = candidate("turtle_trend", "b", "CORE", [
        ("t02", 0.7, "XRPUSDT", "DOWNTREND"),
        ("t04", -0.2, "LINKUSDT", "LOW_VOL"),
        ("t06", 0.8, "XRPUSDT", "DOWNTREND"),
        ("t08", 0.5, "LINKUSDT", "RANGE"),
        ("t10", -0.1, "XRPUSDT", "LOW_VOL"),
    ])
    alpha_clone = candidate("alpha_clone_material", "c", "SYNTHESIS", [
        ("t01", 0.9, "BTCUSDT", "UPTREND"),
        ("t03", -0.45, "ETHUSDT", "RANGE"),
        ("t05", 1.1, "SOLUSDT", "UPTREND"),
        ("t07", -0.35, "BTCUSDT", "HIGH_VOL"),
        ("t09", 0.95, "ETHUSDT", "UPTREND"),
    ])

    analysis = analyze_candidates([alpha, turtle, alpha_clone], CORRELATION_POLICY)
    result = govern_portfolio(
        analysis,
        [
            material(alpha, 50.0, 80.0),
            material(turtle, 50.0, 80.0),
            material(alpha_clone, 0.0, 60.0),
        ],
        GOVERNOR_POLICY,
    )
    assert result["state"] == "PASS_SHADOW_PORTFOLIO_TARGETS", result
    assert result["target_weights_created"] is True
    assert result["selected_target"] is not None
    target = result["selected_target"]
    assert abs(sum(target["target_weights_pct"].values()) - 100.0) < 1e-9
    assert not ({"alpha_combo", "alpha_clone_material"} <= set(target["members"]))
    assert target["joint_drawdown_r"] <= GOVERNOR_POLICY["max_joint_drawdown_r"]
    assert target["turnover_pct"] <= GOVERNOR_POLICY["max_turnover_pct"]
    assert result["risk_budget_enforced"] is True
    assert result["capacity_enforced"] is True
    assert result["turnover_enforced"] is True
    assert result["single_score_used"] is False
    assert result["rebalance_mode"] == "SHADOW_ONLY"
    assert result["rollback_rule"]["automatic_order_action"] is False

    (OUT / "governor.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "state": "PASS_PORTFOLIO_GOVERNOR",
        "governor_sha": result["governor_sha"],
        "evaluated_target_count": result["evaluated_target_count"],
        "pareto_target_count": result["pareto_target_count"],
        "selected_members": target["members"],
        "selected_target_weights_pct": target["target_weights_pct"],
        "selected_joint_drawdown_r": target["joint_drawdown_r"],
        "selected_cost_adjusted_net_r": target["cost_adjusted_net_r"],
        "selected_turnover_pct": target["turnover_pct"],
        "production_threshold_authority": False,
        "next": "STRATEGY_ATTRIBUTION_LEDGER",
        "runtime_bound": False,
        "shadow_only": True,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"], target["target_weights_pct"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
