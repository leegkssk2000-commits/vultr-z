from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from backend.tools import strategy11_unattended_improvement_v2 as v2


def policy() -> dict:
    return {
        "schema_version": "2.0",
        "version": "STRATEGY11_UNATTENDED_IMPROVEMENT_POLICY_V2",
        "authority": "RESEARCH_ONLY_NO_PROMOTION",
        "continue_until_utc": "2026-08-01T08:30:00Z",
        "universe_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"],
        "lane_thresholds": {
            "A_ENTRY_LIVENESS_REPAIR": {"trade_count_min": 0, "trade_count_max": 0},
            "B_COVERAGE_EXPANSION": {"trade_count_min": 1, "trade_count_max": 4},
            "C_DISCOVERY_OPTIMIZATION": {"trade_count_min": 5, "trade_count_max": 9},
            "D_QUALITY_OPTIMIZATION": {"trade_count_min": 10, "trade_count_max": 1000000},
        },
        "selection_rules": {
            "max_candidates_per_strategy_cycle": 2,
            "distinct_axis_required": True,
            "gate_only_forbidden_in_lanes": ["A_ENTRY_LIVENESS_REPAIR", "B_COVERAGE_EXPANSION"],
            "lane_a_priority": ["SYMBOL_COVERAGE", "SURGERY_BLOCKER", "ENTRY_CONTEXT_RELAX"],
            "lane_b_priority": ["SYMBOL_COVERAGE", "SURGERY_BLOCKER", "ENTRY_CONTEXT_RELAX", "EXIT_SHAPE"],
            "lane_c_priority": ["SYMBOL_COVERAGE", "EXIT_SHAPE", "CONTEXT_GATE"],
            "lane_d_positive_priority": ["EXIT_SHAPE", "CONTEXT_GATE"],
            "lane_d_repair_priority": ["EXIT_SHAPE", "CONTEXT_GATE", "SYMBOL_COVERAGE"],
        },
        "exit_candidates": [
            {"candidate_id": "EXIT_TIME24", "axis": "EXIT_SHAPE", "priority": 10, "changes": {"time_stop_bars": 24}},
            {"candidate_id": "EXIT_BE075", "axis": "EXIT_SHAPE", "priority": 20, "changes": {"breakeven_r": 0.75}},
        ],
        "classification": {
            "normal_worst_net_loss_R_min": -0.9,
            "stress_worst_net_loss_R_min": -0.95,
            "lane_a_positive_windows_pct_min": 33.3333333333,
            "lane_b_target_trade_count": 5,
            "lane_b_min_trade_gain": 1,
            "lane_b_max_net_degradation_pct_points": 1.0,
            "lane_c_quality_trade_count": 10,
            "lane_c_improved_primary_metrics_min": 2,
            "lane_d_near_pareto_improved_metrics_min": 2,
            "lane_d_near_pareto_retention_pct_min": 60.0,
            "lane_d_near_pareto_max_net_degradation_pct_points": 0.5,
        },
        **v2.SAFETY,
    }


def catalog() -> dict:
    rows = []
    families = sorted(set(v2.FAMILY_MAP.values()))
    for index in range(50):
        rows.append({
            "candidate_id": f"GATE_{index:02d}",
            "kind": "GATE",
            "causal": True,
            "axis": f"CONTEXT_{index % 9}",
            "compatible_families": families,
            "required": ["trend_ema20_50"],
            "forbidden": [],
            "indicator_family": f"INDICATOR_{index % 14}",
            "components": ["trend_ema20_50"],
            "priority": index + 1,
        })
    return {"authority": "RESEARCH_ONLY_NO_PROMOTION", "candidates": rows, **v2.SAFETY}


def variant(trades: int, net: float, pf: float, payoff: float, dd: float, *, ladder_pass: bool = False) -> dict:
    return {
        "variant_id": "X",
        "trade_count": trades,
        "net_return_pct_sum": net,
        "net_profit_factor": pf,
        "payoff_ratio": payoff,
        "max_drawdown_pct": dd,
        "positive_fresh_windows_pct": 66.6666667,
        "loss_metrics": {"normal_worst_net_loss_R": -0.7, "loss_cap_breach_count": 0},
        "stress_2x_p95_plus_one": {
            "loss_metrics": {"normal_worst_net_loss_R": -0.85, "loss_cap_breach_count": 0}
        },
        "parity": {"state": "PASS", "duplicate_trade_count": 0},
        "ladder_check": {"research_pass": ladder_pass, "trade_retention_pct": 100.0},
    }


def control(strategy_id: str, trades: int, *, gate_required=(), surgery=None, symbols=("BTCUSDT", "ETHUSDT"), net=0.0, pf=0.0) -> dict:
    row = variant(trades, net, pf, 1.0, 1.0)
    row["variant_id"] = "NO_CHANGE_CONTROL"
    row["candidate_config"] = {
        "strategy_id": strategy_id,
        "candidate_id": "NO_CHANGE_CONTROL",
        "axis": "NO_CHANGE",
        "kind": "CONTROL",
        "gate": {
            "gate_id": "BASE" if not gate_required else "STRICT",
            "family": v2.FAMILY_MAP[strategy_id],
            "required": list(gate_required),
            "forbidden": [],
            "description": "",
        },
        "exit": {"exit_id": "ORIG", "stop_mult": 1.0, "target_mult": 1.0},
        "surgery": surgery,
        "symbols": list(symbols),
    }
    row["candidate_config_sha256"] = v2.stable_sha(row["candidate_config"])
    return row


def main() -> int:
    p = policy()
    c = catalog()
    v2.validate_policy(p)
    gates = v2.validate_gate_catalog(c)

    a = control("bb_revert", 0, symbols=("BTCUSDT", "ETHUSDT"))
    pool, priority, diagnosis = v2.candidate_pool("bb_revert", a, v2.LANES[0], gates, p)
    selected = v2.choose_distinct("bb_revert", 1, pool, set(), 2, priority)
    assert [row["candidate_id"] for row in selected] == ["COVERAGE_SYMBOL_ALL5"]
    assert diagnosis == "INTERNAL_TRIGGER_OR_REGIME_DORMANT"

    b = control(
        "liquidity_sweep",
        2,
        gate_required=("rejection_long",),
        surgery={"surgery_id": "BLOCK_X", "kind": "bool"},
    )
    pool, priority, _ = v2.candidate_pool("liquidity_sweep", b, v2.LANES[1], gates, p)
    selected = v2.choose_distinct("liquidity_sweep", 1, pool, set(), 2, priority)
    assert {row["axis"] for row in selected} == {"SYMBOL_COVERAGE", "SURGERY_BLOCKER"}
    assert all(row["kind"] != "GATE" for row in selected)

    c_control = control("trend_ma_macd", 6, gate_required=("trend_ema20_50",))
    pool, priority, _ = v2.candidate_pool("trend_ma_macd", c_control, v2.LANES[2], gates, p)
    selected = v2.choose_distinct("trend_ma_macd", 1, pool, set(), 2, priority)
    assert {row["axis"] for row in selected} == {"SYMBOL_COVERAGE", "EXIT_SHAPE"}

    d = control("alpha_combo", 30, gate_required=("trend_ema20_50",), symbols=("BTCUSDT", "ETHUSDT", "XRPUSDT", "LINKUSDT"), net=18.0, pf=3.0)
    pool, priority, _ = v2.candidate_pool("alpha_combo", d, v2.LANES[3], gates, p)
    selected = v2.choose_distinct("alpha_combo", 1, pool, set(), 2, priority)
    assert {row["axis"] for row in selected} == {"EXIT_SHAPE", "CONTEXT_0"}

    status, details = v2.classify_variant(v2.LANES[0], variant(3, 0.5, 1.2, 1.1, 0.5), control("bb_revert", 0), p)
    assert status == "PASS_LIVENESS_REPAIR_RESEARCH" and details["hard_risk_ok"]
    status, _ = v2.classify_variant(v2.LANES[1], variant(6, 0.2, 1.1, 1.0, 0.7), control("liquidity_sweep", 2, net=0.1, pf=1.0), p)
    assert status == "PASS_COVERAGE_EXPANSION_RESEARCH"
    status, _ = v2.classify_variant(v2.LANES[1], variant(2, 0.75, 3.2, 1.4, 0.3), control("rsi_swing_fail", 2, net=-0.28, pf=0.72), p)
    assert status == "HOLD_COVERAGE_QUALITY_IMPROVED"
    status, _ = v2.classify_variant(v2.LANES[2], variant(8, 0.8, 1.4, 1.3, 0.7), control("trend_ma_macd", 6, net=0.2, pf=1.1), p)
    assert status == "HOLD_DISCOVERY_IMPROVED"
    status, _ = v2.classify_variant(v2.LANES[3], variant(30, 19.0, 3.2, 1.2, 0.8, ladder_pass=True), d, p)
    assert status == "PASS_QUALITY_RESEARCH"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "policy.json").write_text(json.dumps(p), encoding="utf-8")
        (root / "catalog.json").write_text(json.dumps(c), encoding="utf-8")
        rows = []
        lane_trades = [0, 2, 6, 30]
        for index, strategy_id in enumerate(v2.STRATEGIES):
            trades = lane_trades[index % 4]
            rows.append({"strategy_id": strategy_id, "variants": [control(strategy_id, trades)]})
        baseline = {"rows": rows}
        (root / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
        args = SimpleNamespace(
            policy=str(root / "policy.json"),
            catalog=str(root / "catalog.json"),
            baseline_final=str(root / "baseline.json"),
            previous_ledger=None,
            now_utc="2026-07-30T12:00:00Z",
            out=str(root / "out"),
        )
        assert v2.build_plan(args) == 0
        plan = json.loads((root / "out/plan.json").read_text())
        assert plan["state"] == "PASS_UNATTENDED_IMPROVEMENT_PLAN"
        assert plan["candidate_count"] > 0
        assert all(len(row["candidate_ids"]) <= 2 for row in plan["rows"])
        assert all(len({row["candidate_specs"][cid]["axis"] for cid in row["candidate_ids"]}) == len(row["candidate_ids"]) for row in plan["rows"])

    print(json.dumps({"state": "PASS_UNATTENDED_IMPROVEMENT_V2_FIXTURE", "lanes": list(v2.LANES)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
