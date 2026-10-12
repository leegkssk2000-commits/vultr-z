#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_exit_asymmetry_optimizer_v1 as v1

SCHEMA = "zel.a1.top5_exit_asymmetry_optimizer.v2"


def _pareto(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    c_trades = int(candidate.get("completed_trades") or 0)
    b_trades = int(baseline.get("completed_trades") or 0)
    if c_trades < 8:
        reasons.append("MIN_SAMPLE_LT_8")
    if c_trades < b_trades:
        reasons.append("TRADE_COUNT_DECREASE")
    for key, reason in (
        ("net_pnl_bps", "NET_PNL_WORSE"),
        ("net_expectancy_bps", "EXPECTANCY_WORSE"),
        ("avg_win_bps", "AVG_WIN_WORSE"),
        ("best_win_bps", "BEST_WIN_WORSE"),
    ):
        c, b = candidate.get(key), baseline.get(key)
        if c is None or b is None or float(c) + 1e-9 < float(b):
            reasons.append(reason)
    for key, reason in (
        ("avg_loss_bps", "AVG_LOSS_WORSE"),
        ("worst_loss_bps", "WORST_LOSS_WORSE"),
        ("max_drawdown_bps", "DRAWDOWN_WORSE"),
    ):
        c, b = candidate.get(key), baseline.get(key)
        if c is None or b is None or float(c) > float(b) + 1e-9:
            reasons.append(reason)
    return not reasons, reasons


def run(strategy_id: str, out: Path) -> dict[str, Any]:
    old_pareto, old_schema = v1._pareto, v1.SCHEMA
    try:
        v1._pareto = _pareto
        v1.SCHEMA = SCHEMA
        result = v1.run(strategy_id, out)
        result["tail_gate"] = {
            "completed_trades_nondecrease": True,
            "avg_loss_nonincrease": True,
            "worst_loss_nonincrease": True,
            "avg_win_nondecrease": True,
            "best_win_nondecrease": True,
        }
        result["receipt_sha256"] = v1.ev.stable_sha({k: value for k, value in result.items() if k != "receipt_sha256"})
        out.write_text(v1.json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return result
    finally:
        v1._pareto = old_pareto
        v1.SCHEMA = old_schema


def self_test() -> int:
    base = {
        "completed_trades": 10,
        "net_pnl_bps": 1000.0,
        "net_expectancy_bps": 100.0,
        "avg_win_bps": 200.0,
        "best_win_bps": 500.0,
        "avg_loss_bps": 100.0,
        "worst_loss_bps": 180.0,
        "max_drawdown_bps": 300.0,
    }
    good = dict(base)
    good.update({"net_pnl_bps": 1100.0, "net_expectancy_bps": 110.0,
                 "avg_win_bps": 210.0, "best_win_bps": 520.0,
                 "avg_loss_bps": 95.0, "worst_loss_bps": 170.0,
                 "max_drawdown_bps": 280.0})
    passed, reasons = _pareto(good, base)
    assert passed and not reasons
    bad_tail = dict(good); bad_tail["worst_loss_bps"] = 181.0
    passed, reasons = _pareto(bad_tail, base)
    assert not passed and "WORST_LOSS_WORSE" in reasons
    bad_best = dict(good); bad_best["best_win_bps"] = 499.0
    passed, reasons = _pareto(bad_best, base)
    assert not passed and "BEST_WIN_WORSE" in reasons
    fewer = dict(good); fewer["completed_trades"] = 9
    passed, reasons = _pareto(fewer, base)
    assert not passed and "TRADE_COUNT_DECREASE" in reasons
    print("PASS_A1_TOP5_EXIT_ASYMMETRY_OPTIMIZER_V2_SELF_TEST")
    print("PASS_TOP5_EXIT_TRADE_DENSITY_NONDECREASE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy-id", choices=v1.TOP5)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_exit_asymmetry_v2_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.strategy_id:
        raise SystemExit("--strategy-id required")
    result = run(args.strategy_id, args.out)
    selected = result["final_selected"]
    print("FINAL_TOP5_EXIT_V2 " + v1.json.dumps({
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
