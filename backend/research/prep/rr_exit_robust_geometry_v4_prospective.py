#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import rr_exit_robust_geometry_v1 as v1

SCHEMA = "zel.rr_exit.robust_geometry.v4_prospective"
REQUIRED_FRESH_T = 6
QUANTILES = (0.25, 0.50, 0.75, 0.90)


def local_neighbors(cells: list[dict[str, Any]], cell: dict[str, Any], tp_vals: list[float], sl_vals: list[float]) -> list[dict[str, Any]]:
    return v1.neighbors(cells, cell, tp_vals, sl_vals)


def robust_rank(cell: Mapping[str, Any]) -> tuple[float, float, float]:
    # Maximise the worst local expectancy first, then the cell expectancy, then
    # prefer the less extreme nominal RR on exact ties. All terms are development-only.
    return (
        float(cell.get("local_min_expectancy_bps") or -1e18),
        float(cell.get("development_score") or -1e18),
        -float(cell.get("nominal_rr") or 1e18),
    )


def run(trend_path: Path, a4dir: Path, breakdir: Path, out: Path) -> dict[str, Any]:
    trend = v1.rr.read(trend_path)
    lanes = v1.rr.latest_sets(trend, a4dir, breakdir)
    broad = next(x for x in lanes if x["lane"] == "trend_rider_broad")
    base_rows = sorted(
        [dict(x) for x in broad["rows"]],
        key=lambda x: (int(x["signal_ts"]), str(x["symbol"]), str(x["side"])),
    )
    if len(base_rows) != 30:
        raise RuntimeError(f"RR_V4_EXPECTED_BROAD30:{len(base_rows)}")

    authority = v1.rr.read(v1.rr.COST)
    symbols = sorted({str(x["symbol"]) for x in base_rows})
    bars_by = {s: v1.ev.fetch_bars(s, "1h", 1000) for s in symbols}
    snaps = {s: v1.ev.fetch_execution_snapshot(s, authority) for s in symbols}
    paths = [v1.matched.row_path(row, bars_by[str(row["symbol"])]) for row in base_rows]
    winners = [x for x in paths if float(x["net_bps"]) > 0]
    losers = [x for x in paths if float(x["net_bps"]) < 0]
    if len(winners) < 3 or len(losers) < 3:
        raise RuntimeError(f"RR_V4_WIN_LOSS_SUPPORT:W={len(winners)}:L={len(losers)}")

    winner_mfe = [float(x["mfe_r"]) for x in winners]
    loser_mae = [float(x["mae_r"]) for x in losers]
    tp_vals = sorted({round(v1.q(winner_mfe, p), 4) for p in QUANTILES if v1.q(winner_mfe, p) > 0})
    sl_vals = sorted({round(v1.q(loser_mae, p), 4) for p in QUANTILES if v1.q(loser_mae, p) > 0})
    if len(tp_vals) < 2 or len(sl_vals) < 2:
        raise RuntimeError("RR_V4_EMPIRICAL_GRID_DEGENERATE")

    cells: list[dict[str, Any]] = []
    for tp_r in tp_vals:
        for sl_r in sl_vals:
            rows = v1.rr.simulate(base_rows, tp_r, sl_r, bars_by, snaps)
            pack = v1.metrics_pack(rows)
            cells.append({
                "tp_r": tp_r,
                "sl_r": sl_r,
                "nominal_rr": tp_r / sl_r,
                "development": pack,
                "development_score": v1.objective(pack["metrics"], pack["payoff"]),
            })

    for cell in cells:
        ns = local_neighbors(cells, cell, tp_vals, sl_vals)
        positive_ns = [n for n in ns if bool(n["development"]["economic_positive"])]
        local = [cell] + positive_ns
        cell["adjacent_count"] = len(ns)
        cell["positive_adjacent_count"] = len(positive_ns)
        cell["plateau_supported"] = bool(cell["development"]["economic_positive"] and len(positive_ns) >= 2)
        cell["local_min_expectancy_bps"] = min(
            float(x["development"]["metrics"].get("net_expectancy_bps") or -1e18) for x in local
        )

    plateau = [x for x in cells if x["plateau_supported"]]
    chosen = max(plateau, key=robust_rank) if plateau else None
    native = v1.metrics_pack(base_rows)
    development_max_exit_ts = max(int(x.get("exit_ts") or 0) for x in base_rows)
    development_max_signal_ts = max(int(x.get("signal_ts") or 0) for x in base_rows)

    if chosen is None:
        state = "HOLD_NO_FULL30_LOCAL_PLATEAU"
        next_action = "KEEP_NATIVE_EXIT_ROUTE_NEXT_DISTINCT_EXIT_FAMILY"
    else:
        state = "RR_PLATEAU_PREREGISTERED_WAIT_FRESH6"
        next_action = "FREEZE_SELECTED_RR_AND_VALIDATE_ONLY_ON_SIGNAL_TS_AFTER_DEVELOPMENT_MAX_EXIT"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "parent_reference": broad["reference"],
        "development_T": len(base_rows),
        "development_only": True,
        "historical_internal_holdout_claimed": False,
        "historical_internal_holdout_impossible_reason": "BROAD30_IS_SINGLE_CONNECTED_OVERLAP_EPISODE",
        "development_overlap_episode_sizes": [30],
        "search_family": "RR_GEOMETRY_LOCAL_PLATEAU_MAXIMIN",
        "search_quantiles": list(QUANTILES),
        "tp_r_candidates_from_full30_winner_mfe": tp_vals,
        "sl_r_candidates_from_full30_loser_mae": sl_vals,
        "candidate_count": len(cells),
        "selection_rule": "MAX_LOCAL_MIN_EXPECTANCY_THEN_CELL_EXPECTANCY_THEN_LESS_EXTREME_RR",
        "selection_uses_fresh_outcomes": False,
        "native_development_control": native,
        "selected": chosen,
        "development_cells": cells,
        "development_max_signal_ts": development_max_signal_ts,
        "development_max_exit_ts": development_max_exit_ts,
        "prospective_boundary_rule": "fresh signal_ts MUST be strictly greater than development_max_exit_ts",
        "required_fresh_T": REQUIRED_FRESH_T,
        "fresh_candidate_reoptimization_forbidden": True,
        "fresh_validation_used_to_select_candidate": False,
        "fresh_validation_metrics_required": ["net_pnl_bps", "net_expectancy_bps", "profit_factor", "payoff", "drawdown_bps", "win_rate"],
        "fresh_pass_requires_native_noninferiority": True,
        "fresh_pass_requires_positive_economics": True,
        "fresh_proof_complete": False,
        "fresh_child_preregistration_allowed": chosen is not None,
        "promotion_authority": False,
        "selection_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": next_action,
    }
    result["receipt_sha256"] = v1.stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    a={"local_min_expectancy_bps":10,"development_score":20,"nominal_rr":5}
    b={"local_min_expectancy_bps":10,"development_score":20,"nominal_rr":4}
    c={"local_min_expectancy_bps":11,"development_score":1,"nominal_rr":100}
    assert max([a,b,c],key=robust_rank) is c
    assert max([a,b],key=robust_rank) is b
    print("PASS_RR_EXIT_ROBUST_GEOMETRY_V4_PROSPECTIVE_SELF_TEST")
    return 0


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--trend70-source",type=Path)
    ap.add_argument("--a4-source-dir",type=Path)
    ap.add_argument("--break-source-dir",type=Path)
    ap.add_argument("--out",type=Path,default=Path("out/rr_exit_robust_geometry_v4_prospective.json"))
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:return self_test()
    if None in (a.trend70_source,a.a4_source_dir,a.break_source_dir):raise SystemExit("sources required")
    r=run(a.trend70_source,a.a4_source_dir,a.break_source_dir,a.out)
    s=r.get("selected") or {}
    print(json.dumps({
        "state":r["state"],"development_T":r["development_T"],
        "selected":None if not s else {"tp_r":s["tp_r"],"sl_r":s["sl_r"],"nominal_rr":s["nominal_rr"],"local_min_expectancy_bps":s["local_min_expectancy_bps"],"development":s["development"]},
        "required_fresh_T":r["required_fresh_T"],"boundary":r["development_max_exit_ts"],"next":r["next"],"receipt":r["receipt_sha256"]
    },sort_keys=True))
    return 0

if __name__=="__main__":raise SystemExit(main())
