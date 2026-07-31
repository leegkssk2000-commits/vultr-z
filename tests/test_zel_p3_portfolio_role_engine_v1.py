from __future__ import annotations

import copy
import math

from backend.research.zel_portfolio_role_engine_v1_1 import evaluate

FAMILIES = ("TREND", "MEAN_REVERSION", "BREAKOUT", "HYBRID")


def policy() -> dict:
    return {
        "source_ref": "fixture:portfolio_policy",
        "source_sha256": "f" * 64,
        "current_regime": "TRENDING",
        "minimum_return_points": 20,
        "maximum_pair_correlation": 0.8,
        "maximum_signal_overlap": 0.8,
        "maximum_family_weight": 0.6,
        "maximum_symbol_weight": 0.8,
        "maximum_side_weight": 0.9,
        "maximum_joint_dd_pct": 10.0,
        "minimum_marginal_score": 0.0,
        "active_ensemble_min": 2,
        "active_ensemble_max": 3,
        "family_ensemble_min": 3,
        "family_ensemble_max": 5,
        "standalone_min": 4,
        "standalone_max": 7,
        "s_material_min": 6,
        "s_material_max": 10,
        "edge_weight": 1.0,
        "diversification_weight": 0.5,
        "regime_weight": 0.5,
        "total_risk_budget": 0.03,
        "max_material_weight": 0.6,
        "min_material_weight": 0.1,
        "max_turnover": 2.0,
    }


def base_series(frequency: int, phase: float = 0.0) -> dict[str, float]:
    return {
        f"t{index:02d}": round(math.sin((index + phase) * frequency) * 0.01, 10)
        for index in range(30)
    }


def candidates() -> list[dict]:
    rows: list[dict] = []
    for family_index, family in enumerate(FAMILIES, start=1):
        primary_series = base_series(family_index)
        for member in range(2):
            material_id = f"{family.lower()}.{member}"
            series = primary_series if member == 0 else {
                key: value * 0.99 + 0.000001 for key, value in primary_series.items()
            }
            rows.append({
                "material_id": material_id,
                "strategy_id": f"strategy_{family_index}_{member}",
                "strategy_source_sha256": f"{family_index}{member}".ljust(64, "a")[:64],
                "family": family,
                "classification": "CORE",
                "material_sealed": True,
                "net_after_cost": 3.0 - member * 0.2 + family_index * 0.1,
                "confidence": 0.8,
                "uncertainty": 0.2,
                "dd_pct": 2.0 + family_index * 0.1,
                "joint_tail_dd_pct": 1.0,
                "cost_pct": 0.1,
                "capacity_score": 0.9,
                "incumbent_weight": 0.0,
                "standalone_eligible": member == 0 or family_index <= 2,
                "eligible_regimes": ["TRENDING", "RANGE"] if family != "MEAN_REVERSION" else ["TRENDING", "RANGE"],
                "return_series": series,
                "signal_event_ids": [f"{family}.shared", f"{material_id}.unique"],
                "symbol_weights": {"BTCUSDT": 0.5, "SOLUSDT": 0.5},
                "side": "LONG" if family != "MEAN_REVERSION" else "BIDIRECTIONAL",
                "sbot_veto": False,
                "lineage_verified": True,
            })
    return rows


def test_p3_builds_family_ensembles_and_prunes_duplicate_members() -> None:
    result = evaluate(candidates(), policy())
    assert result["status"] == "PASS_P3_SHADOW_PORTFOLIO_TARGETS"
    assert result["s_material_count"] == 8
    assert result["standalone_strategy_count"] == 6
    assert result["family_ensemble_count"] == 4
    assert result["active_ensemble_count"] == 3
    assert len(result["correlation_pruned_rows"]) == 4
    assert result["sbot_veto_override_count"] == 0
    assert result["capital_activation_allowed"] is False
    assert len(result["observer_control_ids"]) == 8
    assert abs(sum(result["family_weight_ratios"].values()) - 1.0) < 1e-9
    assert max(result["symbol_weight_ratios"].values()) <= 0.8


def test_sbot_veto_removes_candidate_without_deleting_observer_control() -> None:
    rows = candidates()
    rows[1]["sbot_veto"] = True
    result = evaluate(rows, policy())
    assert rows[1]["material_id"] in result["vetoed_material_ids"]
    assert rows[1]["material_id"] in result["observer_control_ids"]
    assert rows[1]["material_id"] not in {
        member for ensemble in result["family_ensembles"] for member in ensemble["member_ids"]
    }
    assert result["sbot_veto_override_count"] == 0


def test_high_correlation_only_blocks_when_selected_ensembles_conflict() -> None:
    rows = candidates()
    breakout_primary = next(row for row in rows if row["material_id"] == "breakout.0")
    hybrid_primary = next(row for row in rows if row["material_id"] == "hybrid.0")
    hybrid_secondary = next(row for row in rows if row["material_id"] == "hybrid.1")
    hybrid_primary["return_series"] = copy.deepcopy(breakout_primary["return_series"])
    hybrid_secondary["return_series"] = {
        key: value * 0.99 for key, value in breakout_primary["return_series"].items()
    }
    result = evaluate(rows, policy())
    assert result["status"] == "HOLD_P3_PORTFOLIO_GAPS"
    assert any(blocker.startswith("ACTIVE_PAIR_CORRELATION") for blocker in result["blockers"])


def test_normalized_side_exposure_can_hold_without_changing_weights() -> None:
    constrained = policy()
    constrained["maximum_side_weight"] = 0.5
    result = evaluate(candidates(), constrained)
    assert result["status"] == "HOLD_P3_PORTFOLIO_GAPS"
    assert "SIDE_WEIGHT_LIMIT" in result["blockers"]
    assert result["target_risk_weights"]
    assert result["capital_activation_allowed"] is False
