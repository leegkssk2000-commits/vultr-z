#!/usr/bin/env python3
"""Exit-only RR-grid promotion gate for frozen Top5 parents.

This file does not generate exits. It judges shadow child receipts produced by the
existing replay engine. Frozen parent/G5 policy is immutable.
"""
from __future__ import annotations

import json
from pathlib import Path


def judge(parent: dict, child: dict) -> dict:
    p=parent; c=child
    checks={
        "trade_count_retained": int(c["trades"]) >= int(p["trades"]),
        "wr_non_decrease": float(c["win_rate"]) >= float(p["win_rate"]),
        "pnl_non_decrease": float(c["net_pnl_bps"]) >= float(p["net_pnl_bps"]),
        "expectancy_non_decrease": float(c["net_expectancy_bps"]) >= float(p["net_expectancy_bps"]),
        "pf_non_decrease": float(c["profit_factor"]) >= float(p["profit_factor"]),
        "payoff_non_decrease": float(c["payoff"]) >= float(p["payoff"]),
        "dd_non_increase": float(c["drawdown_bps"]) <= float(p["drawdown_bps"]),
    }
    passed=all(checks.values())
    return {
        "schema_version":"zel.top5.rr_grid_shadow_gate.v1",
        "state":"PASS_RR_SHADOW_CHILD" if passed else "HOLD_RR_SHADOW_CHILD",
        "checks":checks,
        "parent_mutated":False,
        "exit_only":True,
        "selection_authority":False,
        "promotion_authority":False,
        "execution_authority":"NONE",
        "order_authority":"BLOCKED",
        "live_trade_authority":"BLOCKED",
    }


def main()->int:
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--parent",type=Path,required=True)
    ap.add_argument("--child",type=Path,required=True)
    ap.add_argument("--out",type=Path,default=Path("out/z_top5_rr_grid_shadow_gate_v1.json"))
    args=ap.parse_args()
    p=json.loads(args.parent.read_text()); c=json.loads(args.child.read_text())
    r=judge(p,c)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"state":r["state"],"checks":r["checks"]},sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
