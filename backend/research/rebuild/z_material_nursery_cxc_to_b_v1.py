#!/usr/bin/env python3
"""Economic nursery for synthesis materials.

Grade-C donors may combine only with another grade-C donor. The child is promoted
to grade B only when independent economic quality improves versus both parents.
Grade-B is the minimum donor grade allowed to touch Top5 hosts.
"""
from __future__ import annotations

import json
from pathlib import Path


def grade(parent_a: dict, parent_b: dict, child: dict) -> dict:
    checks = {
        "child_T_ge_12": int(child["trades"]) >= 12,
        "child_net_positive": float(child["net_pnl_bps"]) > 0,
        "child_expectancy_positive": float(child["net_expectancy_bps"]) > 0,
        "child_pf_gt_1": float(child["profit_factor"]) > 1,
        "child_payoff_gt_1": float(child["payoff"]) > 1,
        "expectancy_beats_both": float(child["net_expectancy_bps"]) > max(float(parent_a["net_expectancy_bps"]), float(parent_b["net_expectancy_bps"])),
        "pf_beats_both": float(child["profit_factor"]) > max(float(parent_a["profit_factor"]), float(parent_b["profit_factor"])),
        "dd_below_worst_parent": float(child["drawdown_bps"]) < max(float(parent_a["drawdown_bps"]), float(parent_b["drawdown_bps"])),
    }
    passed = all(checks.values())
    return {
        "schema_version": "zel.material_nursery.cxc_to_b.v1",
        "state": "PASS_GRADE_B_MATERIAL" if passed else "HOLD_GRADE_C_MATERIAL",
        "input_grade": "C",
        "output_grade": "B" if passed else "C",
        "checks": checks,
        "top5_host_eligible": passed,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def main() -> int:
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--parent-a", type=Path, required=True)
    ap.add_argument("--parent-b", type=Path, required=True)
    ap.add_argument("--child", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/z_material_nursery_cxc_to_b_v1.json"))
    a=json.loads(args.parent_a.read_text()); b=json.loads(args.parent_b.read_text()); c=json.loads(args.child.read_text())
    r=grade(a,b,c)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"state":r["state"],"checks":r["checks"]},sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
