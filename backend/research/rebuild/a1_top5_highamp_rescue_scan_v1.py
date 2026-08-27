#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import strict, metrics, payoff, trade_key, run as trend_rescue_run

ROOT = Path(__file__).resolve().parents[3]
KELTNER = ROOT / "backend/research/rebuild/a1_keltner_58pct_research_incumbent_v1.json"
SUPER = ROOT / "backend/research/rebuild/a1_supertrend_5455_research_incumbent_v1.json"
SCHEMA = "zel.a1.top5.highamp_rescue_scan.v1"
MIN_T = 25


def read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def select_semantic_parent(broad: dict[str, Any], incumbent: dict[str, Any]) -> list[dict[str, Any]]:
    by = {trade_key(x): dict(x) for x in broad.get("trades") or []}
    keys = [tuple(x) for x in incumbent.get("semantic_trade_keys") or []]
    missing = [k for k in keys if k not in by]
    if missing:
        raise RuntimeError(f"SEMANTIC_PARENT_KEYS_MISSING:{incumbent.get('strategy_id')}:{missing[:3]}")
    parent = [by[k] for k in keys]
    m = metrics(parent)
    exp = incumbent.get("metrics") or {}
    if int(m["trades"]) != int(exp["trades"]):
        raise RuntimeError("PARENT_T_MISMATCH")
    if abs(float(m["win_rate"]) - float(exp["win_rate"])) > 1e-12:
        raise RuntimeError("PARENT_WR_MISMATCH")
    if abs(float(m["net_pnl_bps"]) - float(exp["net_pnl_bps"])) > 0.1:
        raise RuntimeError("PARENT_PNL_MISMATCH")
    return parent


def select_break_parent(broad: dict[str, Any]) -> list[dict[str, Any]]:
    parent = [
        dict(x) for x in broad.get("trades") or []
        if datetime.fromtimestamp(int(x["signal_ts"])/1000, tz=timezone.utc).hour in (13,14,15)
    ]
    m = metrics(parent)
    if int(m["trades"]) != 9 or abs(float(m["win_rate"]) - 5/9) > 1e-12 or abs(float(m["net_pnl_bps"]) - 9063.67059948244) > 0.1:
        raise RuntimeError(f"BREAK_PARENT_MISMATCH:{m}")
    return parent


def compact(t: dict[str, Any]) -> dict[str, Any]:
    return {k:t.get(k) for k in ("symbol","signal_ts","entry_ts","side","net_bps","reason")}


def hypothetical(x: float, i: int) -> dict[str, Any]:
    ts = 10_000_000_000_000 + i
    return {"symbol":f"FUTURE-{i}","signal_ts":ts,"entry_ts":ts,"side":"long","net_bps":x,"reason":"DIAGNOSTIC_FUTURE_WIN"}


def required_equal_future(parent: list[dict[str, Any]], fixed: list[dict[str, Any]], n: int) -> float | None:
    if n <= 0:
        return 0.0 if strict(parent, fixed)[0] else None
    def ok(x: float) -> bool:
        return strict(parent, fixed + [hypothetical(x, i) for i in range(n)])[0]
    if not ok(100_000.0):
        return None
    lo, hi = 0.0, 100_000.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if ok(mid): hi = mid
        else: lo = mid
    return hi


def scan_lane(strategy_id: str, parent: list[dict[str, Any]], broad: list[dict[str, Any]], frozen_metrics: dict[str, Any]) -> dict[str, Any]:
    pkeys = {trade_key(x) for x in parent}
    donor = [dict(x) for x in broad if trade_key(x) not in pkeys]
    positive = [x for x in donor if float(x.get("net_bps") or 0) > 0]
    strict_subsets: list[list[dict[str, Any]]] = []
    for n in range(1, len(positive)+1):
        for comb in itertools.combinations(positive, n):
            subset = [dict(x) for x in comb]
            if strict(parent, subset)[0]:
                strict_subsets.append(subset)
    strict_subsets.sort(key=lambda s:(len(s), float(metrics(parent+s)["net_pnl_bps"])), reverse=True)
    best = strict_subsets[0] if strict_subsets else []
    best_ok, best_checks, best_added_m, best_combined_m, best_payoff = strict(parent, best) if best else (False, {}, metrics([]), metrics(parent), payoff(parent))
    current_t = len(parent) + len(best)
    need = max(0, MIN_T - current_t)
    req = required_equal_future(parent, best, need)
    avg_win = sum(float(x["net_bps"]) for x in parent if float(x["net_bps"]) > 0) / max(1, sum(1 for x in parent if float(x["net_bps"]) > 0))
    highamp = [x for x in positive if float(x["net_bps"]) >= avg_win]
    return {
        "strategy_id": strategy_id,
        "state": "STRICT25_HISTORICAL_FEASIBLE_NONPROMOTABLE" if current_t >= MIN_T else "STRICT_RESCUE_PARTIAL_FEASIBLE_NEEDS_FRESH_HIGHAMP",
        "parent_T": len(parent),
        "parent_metrics_recomputed": metrics(parent),
        "parent_frozen_metrics": frozen_metrics,
        "parent_payoff_recomputed": payoff(parent),
        "parent_average_winner_bps": avg_win,
        "broad_T": len(broad),
        "distinct_donor_T": len(donor),
        "positive_donor_T": len(positive),
        "highamp_donor_at_least_parent_avgwin_T": len(highamp),
        "historical_strict_subset_count": len(strict_subsets),
        "best_historical_strict_added_T": len(best),
        "best_historical_strict_combined_T": current_t,
        "best_historical_strict_added_metrics": best_added_m,
        "best_historical_strict_combined_metrics": best_combined_m,
        "best_historical_strict_combined_payoff": best_payoff,
        "best_historical_strict_rows": [compact(x) for x in best],
        "best_historical_strict_checks": best_checks,
        "T_needed_to_25": need,
        "required_equal_future_winner_bps_for_25": req,
        "historical_subset_is_promotion_evidence": False,
        "future_requirement_is_diagnostic_only": True,
    }


def run(trend70_path: Path, a4_dir: Path, break_dir: Path) -> dict[str, Any]:
    trend70 = read(trend70_path)
    kdoc = read(KELTNER)
    sdoc = read(SUPER)
    kbroad = read(a4_dir / "keltner_trend_exact_parent.json")
    sbroad = read(a4_dir / "supertrend_pullback_exact_parent.json")
    bbroad = read(break_dir / "break_and_continue_exact_parent.json")

    trend_primary = trend_rescue_run(trend70_path)
    trend_primary_row = {
        "strategy_id":"trend_rider",
        "lane_id":"trend_rider_primary_wr8125",
        "state":"STRICT_RESCUE_PARTIAL_FEASIBLE_NEEDS_FRESH_HIGHAMP",
        "parent_T":16,
        "fixed_fresh2_T":2,
        "historical_oracle_donor_T":6,
        "best_metric_ceiling_T":24,
        "closest24_metrics":trend_primary["closest_24T"]["combined_metrics"],
        "closest24_payoff":trend_primary["closest_24T"]["combined_payoff"],
        "T_needed_to_25":1,
        "required_equal_future_winner_bps_for_25":trend_primary["minimum_one_unseen_winner_rescue"]["required_one_unseen_winner_bps"],
        "historical_subset_is_promotion_evidence":False,
    }

    broad70_metrics = trend70.get("metrics") or {}
    trend_broad_row = {
        "strategy_id":"trend_rider",
        "lane_id":"trend_rider_broad_wr7000",
        "state":"ALREADY_AT_OR_ABOVE_25T_T_RESCUE_NOT_REQUIRED",
        "parent_T":int(trend70.get("completed_trades") or broad70_metrics.get("trades") or 0),
        "win_rate":broad70_metrics.get("win_rate"),
        "T_needed_to_25":0,
        "next":"FULL_SURVIVOR_HARDENING_NEGATIVE_CONTROL_OOS_NOT_T_RESCUE",
    }

    kparent = select_semantic_parent(kbroad, kdoc)
    sparent = select_semantic_parent(sbroad, sdoc)
    bparent = select_break_parent(bbroad)
    krow = scan_lane("keltner_trend", kparent, [dict(x) for x in kbroad.get("trades") or []], kdoc.get("metrics") or {})
    srow = scan_lane("supertrend_pullback", sparent, [dict(x) for x in sbroad.get("trades") or []], sdoc.get("metrics") or {})
    brow = scan_lane("break_and_continue", bparent, [dict(x) for x in bbroad.get("trades") or []], {
        "trades":9,"win_rate":5/9,"net_pnl_bps":9063.67059948244,"net_expectancy_bps":1007.0745110536045,"profit_factor":16.457706602258355,"payoff":13.166165281806684,"drawdown_bps":586.3528680353038,
    })

    lanes = [trend_primary_row, trend_broad_row, brow, krow, srow]
    return {
        "schema_version":SCHEMA,
        "state":"PASS_TOP5_RESCUE_FEASIBILITY_MAPPED",
        "minimum_survivor_T":MIN_T,
        "lanes":lanes,
        "mechanism":"IMMUTABLE_HIGH_QUALITY_PARENT_PLUS_DISTINCT_DONOR_BLOCK_PLUS_FUTURE_HIGH_AMPLITUDE_WINNERS",
        "mechanism_reusable":True,
        "oracle_outcome_selection_promotable":False,
        "promotion_requires_outcome_blind_preentry_gate_and_fresh_prospective_confirmation":True,
        "selection_authority":False,
        "promotion_authority":False,
        "execution_authority":"NONE",
        "order_authority":"BLOCKED",
        "live_trade_authority":"BLOCKED",
        "action":"hold",
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--trend70-source",type=Path,required=True)
    ap.add_argument("--a4-source-dir",type=Path,required=True)
    ap.add_argument("--break-source-dir",type=Path,required=True)
    ap.add_argument("--out",type=Path,default=Path("out/a1_top5_highamp_rescue_scan_v1.json"))
    args=ap.parse_args()
    r=run(args.trend70_source,args.a4_source_dir,args.break_source_dir)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"state":r["state"],"lanes":[{"strategy_id":x["strategy_id"],"lane_id":x.get("lane_id"),"state":x["state"],"best_T":x.get("best_historical_strict_combined_T",x.get("best_metric_ceiling_T",x.get("parent_T"))),"need":x.get("T_needed_to_25"),"required_bps":x.get("required_equal_future_winner_bps_for_25")} for x in r["lanes"]]},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
