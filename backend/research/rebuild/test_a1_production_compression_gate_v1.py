import json
from pathlib import Path

from backend.research.rebuild import a1_production_compression_gate_v1 as gate

HARD = {
    "survivor_gate": {
        "minimum_expectancy_R": 0.0,
        "minimum_net_R": 0.0,
        "minimum_payoff_ratio": 1.0,
        "minimum_profit_factor": 1.0,
        "minimum_retention_pct": 60.0,
    }
}


def m(trades, pnl, exp, pf, payoff, dd):
    return {
        "trades": trades,
        "net_pnl_bps": pnl,
        "net_expectancy_bps": exp,
        "profit_factor": pf,
        "payoff": payoff,
        "drawdown_bps": dd,
    }


def test_break_zero_trade_dd_is_not_improvement():
    parent = m(9, 9059.905788282187, 1006.6561986980208, 16.379364749557258, 4.0, 589.0949292000505)
    child = m(0, 0.0, None, None, None, 0.0)
    out = gate.evaluate_child(parent, child, HARD)
    assert out["production_ready"] is False
    assert "NO_TRADES" in out["blockers"]
    assert out["trade_retention_pct"] == 0.0


def test_supertrend_dd_tradeoff_rejects_economic_regression():
    parent = m(9, 3713.563248004183, 412.61813866713146, 7.57329610968171, 2.0, 223.13453260982578)
    child = m(7, 2146.833589174235, 306.6905127391764, 7.59991523339377, 2.0, 170.51152272604122)
    out = gate.evaluate_child(parent, child, HARD)
    assert out["production_ready"] is False
    assert "PARENT_RELATIVE_PNL_AND_EXPECTANCY_REGRESSION" in out["blockers"]


def test_true_economic_upgrade_passes():
    parent = m(10, 3000.0, 300.0, 4.0, 2.0, 250.0)
    child = m(9, 3400.0, 377.7777777778, 4.5, 2.2, 220.0)
    out = gate.evaluate_child(parent, child, HARD)
    assert out["production_ready"] is True
    assert out["trade_retention_pct"] == 90.0


def test_strategy_routes_and_trend_rider_roles():
    policy_path = Path(__file__).resolve().parent / "a1_production_compression_policy_v1.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert gate.strategy_route("trend_rider", policy) == "SURVIVOR_HOST_DIRECT_IMPROVEMENT"
    assert gate.strategy_route("ema_ribbon_scalp", policy) == "DONOR_MODULE_EVOLUTION_RANK1"
    assert gate.strategy_route("session_bias", policy) == "DONOR_MODULE_EVOLUTION_RANK2"
    assert gate.strategy_route("liquidity_sweep", policy) == "ARCHIVE_DIRECT_DISABLED"
    assert policy["trend_rider_roles"]["primary"] == "WR81_25_FROZEN_INCUMBENT"
    assert policy["trend_rider_roles"]["control"] == "WR70_FROZEN_BASELINE"
