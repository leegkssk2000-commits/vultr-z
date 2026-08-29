#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr
from backend.research.rebuild import a1_top5_matched_exit_attribution_v1 as matched

SCHEMA = "zel.rr_exit.robust_geometry.v1"


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def q(values: list[float], p: float) -> float:
    ys = sorted(float(x) for x in values)
    if not ys:
        raise RuntimeError("EMPTY_QUANTILE_INPUT")
    i = (len(ys) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(ys) - 1)
    w = i - lo
    return float(ys[lo] * (1.0 - w) + ys[hi] * w)


def finite_pf(value: Any) -> float:
    if value == "INF":
        return 1e6
    return float(value or 0.0)


def econ(metrics: Mapping[str, Any], payoff: float | None) -> bool:
    return bool(
        int(metrics.get("trades") or 0) > 0
        and float(metrics.get("net_pnl_bps") or 0.0) > 0
        and float(metrics.get("net_expectancy_bps") or 0.0) > 0
        and finite_pf(metrics.get("profit_factor")) >= 1.0
        and float(payoff or 0.0) >= 1.0
    )


def objective(metrics: Mapping[str, Any], payoff: float | None) -> float:
    return (
        float(metrics.get("net_expectancy_bps") or -1e18)
        * max(finite_pf(metrics.get("profit_factor")), 0.0)
        * max(float(payoff or 0.0), 0.0)
        / max(float(metrics.get("drawdown_bps") or 1e30), 1.0)
    )


def metrics_pack(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    m = rr.metrics(rows)
    return {"metrics": m, "payoff": rr.payoff(rows), "economic_positive": econ(m, rr.payoff(rows))}


def neighbors(cells: list[dict[str, Any]], chosen: dict[str, Any], tp_vals: list[float], sl_vals: list[float]) -> list[dict[str, Any]]:
    ti = tp_vals.index(chosen["tp_r"])
    si = sl_vals.index(chosen["sl_r"])
    coords = {(ti - 1, si), (ti + 1, si), (ti, si - 1), (ti, si + 1)}
    out = []
    for cell in cells:
        ci = tp_vals.index(cell["tp_r"])
        cj = sl_vals.index(cell["sl_r"])
        if (ci, cj) in coords:
            out.append(cell)
    return out


def run(trend_path: Path, a4dir: Path, breakdir: Path, out: Path) -> dict[str, Any]:
    trend = rr.read(trend_path)
    lanes = rr.latest_sets(trend, a4dir, breakdir)
    broad = next(x for x in lanes if x["lane"] == "trend_rider_broad")
    base_rows = sorted([dict(x) for x in broad["rows"]], key=lambda x: (int(x["signal_ts"]), str(x["symbol"]), str(x["side"])))
    if len(base_rows) < 20:
        raise RuntimeError("RR_ROBUST_MIN_T_20")

    authority = rr.read(rr.COST)
    symbols = sorted({str(x["symbol"]) for x in base_rows})
    bars_by = {s: ev.fetch_bars(s, "1h", 1000) for s in symbols}
    snaps = {s: ev.fetch_execution_snapshot(s, authority) for s in symbols}
    path_rows = [matched.row_path(row, bars_by[str(row["symbol"])]) for row in base_rows]

    split = max(12, int(len(base_rows) * 0.70))
    split = min(split, len(base_rows) - 6)
    dev_base, val_base = base_rows[:split], base_rows[split:]
    dev_paths = path_rows[:split]
    dev_winners = [x for x in dev_paths if float(x["net_bps"]) > 0]
    dev_losers = [x for x in dev_paths if float(x["net_bps"]) < 0]
    if len(dev_winners) < 3 or len(dev_losers) < 3:
        raise RuntimeError("RR_ROBUST_DEV_WIN_LOSS_SUPPORT_INSUFFICIENT")

    ps = (0.25, 0.50, 0.75, 0.90)
    tp_vals = sorted({round(q([float(x["mfe_r"]) for x in dev_winners], p), 4) for p in ps})
    sl_vals = sorted({round(q([float(x["mae_r"]) for x in dev_losers], p), 4) for p in ps})
    tp_vals = [x for x in tp_vals if x > 0]
    sl_vals = [x for x in sl_vals if x > 0]
    if len(tp_vals) < 2 or len(sl_vals) < 2:
        raise RuntimeError("RR_ROBUST_EMPIRICAL_BOUNDS_DEGENERATE")

    cells: list[dict[str, Any]] = []
    for tp_r in tp_vals:
        for sl_r in sl_vals:
            simulated = rr.simulate(base_rows, tp_r, sl_r, bars_by, snaps)
            dev_rows, val_rows = simulated[:split], simulated[split:]
            dp, vp, fp = metrics_pack(dev_rows), metrics_pack(val_rows), metrics_pack(simulated)
            cells.append({
                "tp_r": tp_r,
                "sl_r": sl_r,
                "nominal_rr": tp_r / sl_r,
                "development": dp,
                "validation": vp,
                "full_diagnostic": fp,
                "development_score": objective(dp["metrics"], dp["payoff"]),
            })

    eligible = [x for x in cells if x["development"]["economic_positive"]]
    if not eligible:
        chosen = max(cells, key=lambda x: x["development_score"])
        state = "NO_DEVELOPMENT_POSITIVE_RR_GEOMETRY"
    else:
        chosen = max(eligible, key=lambda x: x["development_score"])
        state = "DEVELOPMENT_RR_CANDIDATE_SELECTED"

    adjacent = neighbors(cells, chosen, tp_vals, sl_vals)
    positive_neighbors = [x for x in adjacent if x["development"]["economic_positive"]]
    validation_positive = bool(chosen["validation"]["economic_positive"])
    plateau_supported = len(positive_neighbors) >= 2
    robust = state == "DEVELOPMENT_RR_CANDIDATE_SELECTED" and validation_positive and plateau_supported

    native_dev = metrics_pack(dev_base)
    native_val = metrics_pack(val_base)
    result = {
        "schema_version": SCHEMA,
        "state": "ROBUST_RR_GEOMETRY_CANDIDATE_READY" if robust else state,
        "action": "hold",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "parent_reference": broad["reference"],
        "parent_T": len(base_rows),
        "search_family": "RR_GEOMETRY",
        "search_method": "DEVELOPMENT_ONLY_EMPIRICAL_QUANTILE_GRID_THEN_NONSELECTIVE_VALIDATION",
        "historical_fixed_rr_examples_are_seeds_only": True,
        "old_fixed_cells_retested": False,
        "development_T": len(dev_base),
        "validation_T": len(val_base),
        "development_fraction": len(dev_base) / len(base_rows),
        "search_quantiles": list(ps),
        "tp_r_candidates_from_dev_winner_mfe": tp_vals,
        "sl_r_candidates_from_dev_loser_mae": sl_vals,
        "candidate_count": len(cells),
        "native_control": {"development": native_dev, "validation": native_val, "full": metrics_pack(base_rows)},
        "selected": chosen,
        "plateau": {
            "adjacent_count": len(adjacent),
            "positive_adjacent_count": len(positive_neighbors),
            "supported": plateau_supported,
        },
        "validation_positive": validation_positive,
        "robust_candidate_ready": robust,
        "fresh_child_preregistration_allowed": robust,
        "fresh_outcome_used_for_search": False,
        "g5_W2_W3_used_for_search": False,
        "sealed_holdout_used_for_search": False,
        "entry_logic_frozen": True,
        "timeout_BE_partial_trailing_runner_frozen": True,
        "cells": cells,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": "PREREGISTER_FRESH_RR_GEOMETRY_CHILD" if robust else "NO_FRESH_CHILD_KEEP_NATIVE_EXIT_AND_ROUTE_NEXT_EXIT_FAMILY",
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert q([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    fake = {"trades": 5, "net_pnl_bps": 10, "net_expectancy_bps": 2, "profit_factor": 2, "drawdown_bps": 4}
    assert econ(fake, 1.2)
    assert math.isfinite(objective(fake, 1.2))
    print("PASS_RR_EXIT_ROBUST_GEOMETRY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trend70-source", type=Path)
    ap.add_argument("--a4-source-dir", type=Path)
    ap.add_argument("--break-source-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/rr_exit_robust_geometry_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if None in (a.trend70_source, a.a4_source_dir, a.break_source_dir):
        raise SystemExit("sources required")
    r = run(a.trend70_source, a.a4_source_dir, a.break_source_dir, a.out)
    print(json.dumps({
        "state": r["state"],
        "T": r["parent_T"],
        "dev_T": r["development_T"],
        "val_T": r["validation_T"],
        "selected": {"tp_r": r["selected"]["tp_r"], "sl_r": r["selected"]["sl_r"], "rr": r["selected"]["nominal_rr"]},
        "plateau": r["plateau"],
        "validation_positive": r["validation_positive"],
        "robust": r["robust_candidate_ready"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
