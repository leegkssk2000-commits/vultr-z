from __future__ import annotations

from typing import Any, Mapping

SCHEMA = "zel.a1.loss_streak_pareto_scaffold_policy.v1"


def classify(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    p_wr = parent.get("win_rate")
    c_wr = child.get("win_rate")
    p_pnl = float(parent.get("net_pnl_bps") or 0.0)
    c_pnl = float(child.get("net_pnl_bps") or 0.0)
    p_dd = float(parent.get("max_drawdown_bps") or 0.0)
    c_dd = float(child.get("max_drawdown_bps") or 0.0)
    wr_up = p_wr is not None and c_wr is not None and float(c_wr) > float(p_wr)
    wr_down = p_wr is not None and c_wr is not None and float(c_wr) < float(p_wr)
    pnl_up = c_pnl > p_pnl
    pnl_down = c_pnl < p_pnl
    economically_alive = c_pnl > 0.0

    if wr_up and pnl_up:
        state = "PASS_DUAL_GAIN"
        scaffold_axis = "BOTH"
        next_step = "FRESH25_H4_H5"
    elif wr_up and pnl_down and economically_alive:
        state = "PARK_WR_SCAFFOLD_RECOVER_PNL"
        scaffold_axis = "WIN_RATE"
        next_step = "PRESERVE_CHILD_WR_AS_FLOOR_AND_RECOVER_PNL_WITH_NEXT_DISTINCT_CAUSAL_AXIS"
    elif pnl_up and wr_down and economically_alive:
        state = "PARK_PNL_SCAFFOLD_RECOVER_WR"
        scaffold_axis = "NET_PNL"
        next_step = "PRESERVE_CHILD_PNL_AS_FLOOR_AND_RECOVER_WR_WITH_NEXT_DISTINCT_CAUSAL_AXIS"
    elif not wr_down and not pnl_down and economically_alive:
        state = "PARK_NONDOMINATED_SCAFFOLD"
        scaffold_axis = "PARETO"
        next_step = "CONTINUE_DISTINCT_CAUSAL_IMPROVEMENT_FROM_CHILD"
    else:
        state = "REJECT_DOMINATED_OR_ECONOMICALLY_DEAD_CHILD"
        scaffold_axis = None
        next_step = "RETURN_TO_BEST_EXISTING_SCAFFOLD_AND_TRY_NEXT_DISTINCT_CAUSAL_AXIS"

    return {
        "schema_version": SCHEMA,
        "state": state,
        "scaffold_axis": scaffold_axis,
        "parent": dict(parent),
        "child": dict(child),
        "deltas": {
            "win_rate_pp": None if p_wr is None or c_wr is None else 100.0 * (float(c_wr) - float(p_wr)),
            "net_pnl_bps": c_pnl - p_pnl,
            "max_drawdown_bps": c_dd - p_dd,
        },
        "economically_alive": economically_alive,
        "discard_one_metric_gain_only_because_other_metric_fell": False,
        "same_filter_cross_strategy_copy_forbidden": True,
        "generalize_methodology_only": True,
        "fresh_25_h4_h5_required_for_promotion": True,
        "next": next_step,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def self_test() -> int:
    parent = {"win_rate": 14/24, "net_pnl_bps": 24812.448723667734, "max_drawdown_bps": 680.758041352281}
    wr_scaffold = {"win_rate": 0.8, "net_pnl_bps": 21196.60152461874, "max_drawdown_bps": 219.06777382538348}
    r = classify(parent, wr_scaffold)
    assert r["state"] == "PARK_WR_SCAFFOLD_RECOVER_PNL"
    assert r["scaffold_axis"] == "WIN_RATE"
    assert r["economically_alive"] is True
    assert r["fresh_25_h4_h5_required_for_promotion"] is True
    dominated = classify(parent, {"win_rate": 0.5, "net_pnl_bps": 10000.0, "max_drawdown_bps": 700.0})
    assert dominated["state"] == "REJECT_DOMINATED_OR_ECONOMICALLY_DEAD_CHILD"
    print("PASS_A1_LOSS_STREAK_PARETO_SCAFFOLD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
