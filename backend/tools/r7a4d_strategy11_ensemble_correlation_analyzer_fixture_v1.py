from __future__ import annotations

import json
from pathlib import Path

from backend.research.strategy11_ensemble_correlation_analyzer_v1 import analyze_candidates

OUT = Path("artifacts/strategy11_ensemble_correlation_analyzer_v1")

POLICY = {
    "policy_id": "FIXTURE_ONLY_NOT_PRODUCTION_THRESHOLD_AUTHORITY",
    "max_cosine_similarity": 0.85,
    "max_abs_pnl_correlation": 0.80,
    "max_loss_concurrence": 0.70,
    "max_drawdown_concurrence": 0.85,
    "rolling_window": 4,
    "min_combination_size": 2,
    "max_combination_size": 3,
    "max_candidate_combinations": 3,
}


def sha(char: str) -> str:
    return char * 64


def candidate(strategy_id: str, marker: str, classification: str, rows: list[tuple[str, float, str, str]]) -> dict:
    return {
        "strategy_id": strategy_id,
        "candidate_sha": sha(marker),
        "proposal_sha": sha(marker.upper()),
        "classification_sha": sha(str((int(marker, 16) + 1) % 16)[-1]),
        "classification": classification,
        "trades": [
            {"timestamp": timestamp, "net_r": net_r, "symbol": symbol, "regime": regime}
            for timestamp, net_r, symbol, regime in rows
        ],
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

    result = analyze_candidates([alpha, turtle, alpha_clone], POLICY)
    assert result["blocked_pair_count"] == 1, result
    blocked = [row for row in result["pair_matrix"] if not row["compatible"]]
    assert blocked[0]["pair"] == ["alpha_clone_material", "alpha_combo"], blocked
    assert "COSINE_SIMILARITY_HIGH" in blocked[0]["blocker_codes"]
    assert result["target_weights_created"] is False
    assert result["single_score_used"] is False
    assert result["diagnostic_equal_weight_only"] is True
    assert result["shadow_only_candidate_combinations"], result
    assert all(
        not ({"alpha_combo", "alpha_clone_material"} <= set(row["members"]))
        for row in result["shadow_only_candidate_combinations"]
    )

    (OUT / "analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "state": "PASS_ENSEMBLE_CORRELATION_ANALYZER",
        "analysis_sha": result["analysis_sha"],
        "candidate_count": result["candidate_count"],
        "blocked_pair_count": result["blocked_pair_count"],
        "compatible_combination_count": result["compatible_combination_count"],
        "selected_combination_count": len(result["shadow_only_candidate_combinations"]),
        "duplicate_alpha_material_blocked": True,
        "target_weights_created": False,
        "next": "PORTFOLIO_GOVERNOR",
        "production_threshold_authority": False,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
