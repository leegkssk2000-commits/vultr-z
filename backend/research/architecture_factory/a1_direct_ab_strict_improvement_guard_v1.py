#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

EPS = 1e-12


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--receipt", required=True)
    args = p.parse_args()
    path = Path(args.receipt)
    r = json.loads(path.read_text(encoding="utf-8"))
    d = r.get("delta") or {}
    strict_improvement = any([
        float(d.get("win_rate_pp") or 0.0) > EPS,
        float(d.get("net_expectancy_bps") or 0.0) > EPS,
        float(d.get("net_pnl_bps") or 0.0) > EPS,
        float(d.get("profit_factor") or 0.0) > EPS,
        float(d.get("payoff") or 0.0) > EPS,
        float(d.get("drawdown_bps") or 0.0) < -EPS,
    ])
    if r.get("integrity_defects"):
        r["state"] = "HOLD_BASELINE_OR_AXIS_INTEGRITY"
        r["development_pareto_candidate"] = False
    elif not strict_improvement:
        r["state"] = "FAIL_DIRECT_AB_NO_IMPROVEMENT_ROUTE_NEXT_DISTINCT_AXIS"
        r["development_pareto_candidate"] = False
    r["strict_improvement_required"] = True
    r["strict_improvement_observed"] = strict_improvement
    path.write_text(json.dumps(r, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": r.get("state"), "strict_improvement_observed": strict_improvement, "delta": d}, sort_keys=True))
    return 2 if r.get("integrity_defects") else 0

if __name__ == "__main__":
    raise SystemExit(main())
