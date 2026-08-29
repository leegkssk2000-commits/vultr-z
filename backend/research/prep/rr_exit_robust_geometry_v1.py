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
    lo = int(i); hi = min(lo + 1, len(ys) - 1); w = i - lo
    return float(ys[lo] * (1.0 - w) + ys[hi] * w)


def finite_pf(value: Any, metrics: Mapping[str, Any] | None = None) -> float:
    if value == "INF":
        return 1e6
    if value is None and metrics is not None and float(metrics.get("win_rate") or 0.0) == 1.0:
        return 1e6
    return float(value or 0.0)


def econ(metrics: Mapping[str, Any], payoff: float | None) -> bool:
    trades = int(metrics.get("trades") or 0)
    net = float(metrics.get("net_pnl_bps") or 0.0)
    exp = float(metrics.get("net_expectancy_bps") or 0.0)
    wr = float(metrics.get("win_rate") or 0.0)
    pf = finite_pf(metrics.get("profit_factor"), metrics)
    # An all-win validation slice has no loss denominator, so payoff/PF may be null.
    # Treat that as positive economics, not as a failure. It still must beat the native
    # validation profit below before any fresh child is allowed.
    payoff_ok = wr == 1.0 or float(payoff or 0.0) >= 1.0
    return bool(trades > 0 and net > 0 and exp > 0 and pf >= 1.0 and payoff_ok)


def objective(metrics: Mapping[str, Any], payoff: float | None) -> float:
    # Profit is primary; PF/payoff/DD are constraints/tiebreak quality, not substitutes for profit.
    return float(metrics.get("net_expectancy_bps") or -1e18)


def metrics_pack(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    m = rr.metrics(rows); p = rr.payoff(rows)
    return {"metrics": m, "payoff": p, "economic_positive": econ(m, p)}


def neighbors(cells: list[dict[str, Any]], chosen: dict[str, Any], tp_vals: list[float], sl_vals: list[float]) -> list[dict[str, Any]]:
    ti = tp_vals.index(chosen["tp_r"]); si = sl_vals.index(chosen["sl_r"])
    coords = {(ti - 1, si), (ti + 1, si), (ti, si - 1), (ti, si + 1)}
    return [c for c in cells if (tp_vals.index(c["tp_r"]), sl_vals.index(c["sl_r"])) in coords]


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

    split = max(12, int(len(base_rows) * 0.70)); split = min(split, len(base_rows) - 6)
    dev_base, val_base = base_rows[:split], base_rows[split:]
    dev_paths = path_rows[:split]
    dev_winners = [x for x in dev_paths if float(x["net_bps"]) > 0]
    dev_losers = [x for x in dev_paths if float(x["net_bps"]) < 0]
    if len(dev_winners) < 3 or len(dev_losers) < 3:
        raise RuntimeError("RR_ROBUST_DEV_WIN_LOSS_SUPPORT_INSUFFICIENT")

    ps = (0.25, 0.50, 0.75, 0.90)
    tp_vals = sorted({round(q([float(x["mfe_r"]) for x in dev_winners], p), 4) for p in ps if q([float(x["mfe_r"]) for x in dev_winners], p) > 0})
    sl_vals = sorted({round(q([float(x["mae_r"]) for x in dev_losers], p), 4) for p in ps if q([float(x["mae_r"]) for x in dev_losers], p) > 0})
    if len(tp_vals) < 2 or len(sl_vals) < 2:
        raise RuntimeError("RR_ROBUST_EMPIRICAL_BOUNDS_DEGENERATE")

    # Search only the development slice. Do not expose every candidate to validation.
    cells: list[dict[str, Any]] = []
    for tp_r in tp_vals:
        for sl_r in sl_vals:
            dev_rows = rr.simulate(dev_base, tp_r, sl_r, bars_by, snaps)
            dp = metrics_pack(dev_rows)
            cells.append({
                "tp_r": tp_r,
                "sl_r": sl_r,
                "nominal_rr": tp_r / sl_r,
                "development": dp,
                "development_score": objective(dp["metrics"], dp["payoff"]),
            })

    eligible = [x for x in cells if x["development"]["economic_positive"]]
    chosen = max(eligible or cells, key=lambda x: x["development_score"])
    dev_state = "DEVELOPMENT_RR_CANDIDATE_SELECTED" if eligible else "NO_DEVELOPMENT_POSITIVE_RR_GEOMETRY"
    adjacent = neighbors(cells, chosen, tp_vals, sl_vals)
    positive_neighbors = [x for x in adjacent if x["development"]["economic_positive"]]
    plateau_supported = len(positive_neighbors) >= 2

    # Exactly one development-selected candidate touches validation.
    selected_val_rows = rr.simulate(val_base, chosen["tp_r"], chosen["sl_r"], bars_by, snaps)
    selected_full_rows = rr.simulate(base_rows, chosen["tp_r"], chosen["sl_r"], bars_by, snaps)
    selected_val = metrics_pack(selected_val_rows)
    selected_full = metrics_pack(selected_full_rows)
    chosen = dict(chosen)
    chosen["validation"] = selected_val
    chosen["full_diagnostic"] = selected_full

    native_dev = metrics_pack(dev_base); native_val = metrics_pack(val_base); native_full = metrics_pack(base_rows)
    validation_positive = bool(selected_val["economic_positive"])
    cand_val_exp = float(selected_val["metrics"].get("net_expectancy_bps") or 0.0)
    native_val_exp = float(native_val["metrics"].get("net_expectancy_bps") or 0.0)
    cand_val_dd = float(selected_val["metrics"].get("drawdown_bps") or 0.0)
    native_val_dd = float(native_val["metrics"].get("drawdown_bps") or 0.0)
    validation_net_noninferior = cand_val_exp >= native_val_exp
    validation_dd_noninferior = cand_val_dd <= native_val_dd
    validation_net_delta_bps_per_trade = cand_val_exp - native_val_exp
    validation_net_delta_pct = None if native_val_exp == 0 else validation_net_delta_bps_per_trade / abs(native_val_exp)

    robust = bool(
        dev_state == "DEVELOPMENT_RR_CANDIDATE_SELECTED"
        and plateau_supported
        and validation_positive
        and validation_net_noninferior
        and validation_dd_noninferior
    )
    if robust:
        state = "ROBUST_RR_GEOMETRY_CANDIDATE_READY"
        next_action = "PREREGISTER_FRESH_RR_GEOMETRY_CHILD"
    elif dev_state == "DEVELOPMENT_RR_CANDIDATE_SELECTED" and not validation_net_noninferior:
        state = "RR_GEOMETRY_REJECT_VALIDATION_NET_REGRESSION"
        next_action = "KEEP_NATIVE_EXIT_AND_ROUTE_NEXT_DISTINCT_EXIT_FAMILY"
    else:
        state = dev_state
        next_action = "NO_FRESH_CHILD_KEEP_NATIVE_EXIT_AND_ROUTE_NEXT_EXIT_FAMILY"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "parent_reference": broad["reference"],
        "parent_T": len(base_rows),
        "search_family": "RR_GEOMETRY",
        "search_method": "DEVELOPMENT_ONLY_EMPIRICAL_QUANTILE_GRID_THEN_SINGLE_CANDIDATE_NONSELECTIVE_VALIDATION",
        "historical_fixed_rr_examples_are_seeds_only": True,
        "old_fixed_cells_retested": False,
        "development_T": len(dev_base),
        "validation_T": len(val_base),
        "development_fraction": len(dev_base) / len(base_rows),
        "search_quantiles": list(ps),
        "tp_r_candidates_from_dev_winner_mfe": tp_vals,
        "sl_r_candidates_from_dev_loser_mae": sl_vals,
        "candidate_count": len(cells),
        "native_control": {"development": native_dev, "validation": native_val, "full": native_full},
        "selected": chosen,
        "plateau": {"adjacent_count": len(adjacent), "positive_adjacent_count": len(positive_neighbors), "supported": plateau_supported},
        "validation": {
            "economic_positive": validation_positive,
            "net_expectancy_noninferior_to_native": validation_net_noninferior,
            "dd_noninferior_to_native": validation_dd_noninferior,
            "net_expectancy_delta_bps_per_trade": validation_net_delta_bps_per_trade,
            "net_expectancy_delta_pct": validation_net_delta_pct,
            "all_win_null_payoff_is_not_failure": True,
        },
        "robust_candidate_ready": robust,
        "fresh_child_preregistration_allowed": robust,
        "fresh_outcome_used_for_search": False,
        "g5_W2_W3_used_for_search": False,
        "sealed_holdout_used_for_search": False,
        "validation_used_to_select_candidate": False,
        "same_validation_reuse_for_alternate_rr_candidate_forbidden": True,
        "entry_logic_frozen": True,
        "timeout_BE_partial_trailing_runner_frozen": True,
        "development_cells": cells,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": next_action,
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert q([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    fake = {"trades": 5, "net_pnl_bps": 10, "net_expectancy_bps": 2, "profit_factor": 2, "drawdown_bps": 4, "win_rate": 0.8}
    assert econ(fake, 1.2)
    all_win = {"trades": 5, "net_pnl_bps": 10, "net_expectancy_bps": 2, "profit_factor": None, "drawdown_bps": 0, "win_rate": 1.0}
    assert econ(all_win, None)
    assert objective(fake, 1.2) == 2
    print("PASS_RR_EXIT_ROBUST_GEOMETRY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trend70-source", type=Path); ap.add_argument("--a4-source-dir", type=Path); ap.add_argument("--break-source-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/rr_exit_robust_geometry_v1.json")); ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test: return self_test()
    if None in (a.trend70_source, a.a4_source_dir, a.break_source_dir): raise SystemExit("sources required")
    r = run(a.trend70_source, a.a4_source_dir, a.break_source_dir, a.out)
    print(json.dumps({"state": r["state"], "T": r["parent_T"], "dev_T": r["development_T"], "val_T": r["validation_T"], "selected": {"tp_r": r["selected"]["tp_r"], "sl_r": r["selected"]["sl_r"], "rr": r["selected"]["nominal_rr"]}, "plateau": r["plateau"], "validation": r["validation"], "robust": r["robust_candidate_ready"], "receipt": r["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
