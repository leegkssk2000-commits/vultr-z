#!/usr/bin/env python3
"""TrendMA/MACD one-axis rescue evaluator.

Purpose: practical Top6 decision only. It never mutates the host strategy.
Single rescue axis: concentration-aware trim of dominant profit cluster.
If the child does not improve economic quality without destroying trade count,
TrendMA/MACD is demoted to donor-only for the next nursery stage.
"""
from __future__ import annotations

import json
from pathlib import Path

BASELINE = {
    "trades": 72,
    "win_rate": 0.2222222222222222,
    "net_pnl_bps": 3622.33,
    "net_expectancy_bps": 50.31,
    "profit_factor": 1.319,
    "payoff": 4.617,
    "drawdown_bps": 5567.92,
    "top10_profit_concentration": 0.9149,
}


def verdict(candidate: dict) -> dict:
    required = {
        "trades_retained": int(candidate["trades"]) >= 36,
        "net_pnl_positive": float(candidate["net_pnl_bps"]) > 0,
        "expectancy_improves": float(candidate["net_expectancy_bps"]) > BASELINE["net_expectancy_bps"],
        "pf_improves": float(candidate["profit_factor"]) > BASELINE["profit_factor"],
        "payoff_non_decrease": float(candidate["payoff"]) >= BASELINE["payoff"],
        "dd_improves": float(candidate["drawdown_bps"]) < BASELINE["drawdown_bps"],
        "concentration_improves": float(candidate["top10_profit_concentration"]) < BASELINE["top10_profit_concentration"],
    }
    passed = all(required.values())
    return {
        "schema_version": "zel.trendma_macd.rescue_one_axis.v1",
        "state": "PASS_TOP6_RESCUE" if passed else "FAIL_DEMOTE_TO_DONOR_ONLY",
        "strategy_id": "trend_ma_macd",
        "axis": "CONCENTRATION_AWARE_DOMINANT_CLUSTER_TRIM",
        "baseline": BASELINE,
        "candidate": candidate,
        "checks": required,
        "promotion_authority": False,
        "selection_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "next": "TOP6_FRESH_CONFIRMATION" if passed else "C_PAIR_NURSERY",
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/z_trendma_macd_rescue_one_axis_v1.json"))
    args = ap.parse_args()
    candidate = json.loads(args.candidate.read_text())
    result = verdict(candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": result["state"], "checks": result["checks"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
