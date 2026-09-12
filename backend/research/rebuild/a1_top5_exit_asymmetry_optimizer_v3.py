#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_exit_asymmetry_optimizer_v1 as v1
from backend.research.rebuild import a1_top5_exit_asymmetry_optimizer_v2 as v2

SCHEMA = "zel.a1.top5_exit_asymmetry_optimizer.v3"


def _pareto(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> tuple[bool, list[str]]:
    passed, reasons = v2._pareto(candidate, baseline)
    reasons = list(reasons)
    c_completed = int(candidate.get("completed_trades") or 0)
    b_completed = int(baseline.get("completed_trades") or 0)
    c_admitted = int(candidate.get("admitted_total") or c_completed)
    b_admitted = int(baseline.get("admitted_total") or b_completed)
    if c_completed < b_completed:
        reasons.append("PRODUCTION_TRADE_COUNT_DECREASE")
    if c_admitted < b_admitted:
        reasons.append("ADMISSION_DENSITY_DECREASE")
    return (not reasons), reasons


def run(strategy_id: str, out: Path) -> dict[str, Any]:
    old_pareto, old_schema = v1._pareto, v1.SCHEMA
    try:
        v1._pareto = _pareto
        v1.SCHEMA = SCHEMA
        result = v1.run(strategy_id, out)
        result["production_density_gate"] = {
            "completed_trades_must_not_decrease": True,
            "admitted_total_must_not_decrease": True,
            "reason": "PREVENT_FALSE_RR_IMPROVEMENT_BY_SIGNAL_SUPPRESSION_OR_LONG_POSITION_OCCUPANCY",
        }
        result["receipt_sha256"] = v1.ev.stable_sha({k: value for k, value in result.items() if k != "receipt_sha256"})
        out.write_text(v1.json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return result
    finally:
        v1._pareto = old_pareto
        v1.SCHEMA = old_schema


def self_test() -> int:
    base = {
        "completed_trades": 20, "admitted_total": 21,
        "net_pnl_bps": 1000.0, "net_expectancy_bps": 50.0,
        "avg_win_bps": 200.0, "best_win_bps": 500.0,
        "avg_loss_bps": 100.0, "worst_loss_bps": 180.0,
        "max_drawdown_bps": 300.0,
    }
    pretty_but_sparse = dict(base)
    pretty_but_sparse.update({
        "completed_trades": 15, "admitted_total": 16,
        "net_pnl_bps": 1500.0, "net_expectancy_bps": 100.0,
        "avg_win_bps": 300.0, "best_win_bps": 700.0,
        "avg_loss_bps": 70.0, "worst_loss_bps": 130.0,
        "max_drawdown_bps": 200.0,
    })
    passed, reasons = _pareto(pretty_but_sparse, base)
    assert not passed
    assert "PRODUCTION_TRADE_COUNT_DECREASE" in reasons
    assert "ADMISSION_DENSITY_DECREASE" in reasons
    same_density = dict(base)
    same_density.update({
        "net_pnl_bps": 1100.0, "net_expectancy_bps": 55.0,
        "avg_win_bps": 210.0, "best_win_bps": 520.0,
        "avg_loss_bps": 95.0, "worst_loss_bps": 170.0,
        "max_drawdown_bps": 280.0,
    })
    passed, reasons = _pareto(same_density, base)
    assert passed and not reasons
    print("PASS_A1_TOP5_EXIT_ASYMMETRY_OPTIMIZER_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy-id", choices=v1.TOP5)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_exit_asymmetry_v3_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.strategy_id:
        raise SystemExit("--strategy-id required")
    result = run(args.strategy_id, args.out)
    selected = result["final_selected"]
    print("FINAL_TOP5_EXIT_V3 " + v1.json.dumps({
        "strategy_id": args.strategy_id,
        "state": result["state"],
        "baseline": result["baseline"]["metrics"],
        "selected_geometry": {
            "timeout_bars": selected["timeout_bars"],
            "stop_scale_vs_incumbent": selected["stop_scale_vs_incumbent"],
            "be_trigger_r": selected["be_trigger_r"],
            "hard_tp_r": None,
        },
        "selected": selected["metrics"],
        "score": result["final_score_vs_incumbent"],
        "fresh_oos_required": True,
    }, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
