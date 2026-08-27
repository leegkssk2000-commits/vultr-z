#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_trendrider_8125_fresh2_payoff_diagnostic_v1 import (
    FRESH, PARENT, parent_algebra, read, stable, union_metrics, validate_source,
)

HORIZONS = (48, 72, 96)
SCHEMA = "zel.a1.trendrider.8125.fresh2_timeout_horizon_diagnostic.v1"


def horizon_upper(trade: dict[str, Any], bars: list[dict[str, Any]], horizon_bars: int) -> dict[str, Any]:
    entry_ts = int(trade["entry_ts"])
    end_ts = entry_ts + horizon_bars * 3_600_000
    window = [x for x in bars if entry_ts <= int(x["ts_ms"]) <= end_ts]
    if not window or int(window[0]["ts_ms"]) != entry_ts:
        raise RuntimeError(f"HORIZON_START_MISSING:{trade['symbol']}:{horizon_bars}")
    if int(window[-1]["ts_ms"]) < end_ts:
        raise RuntimeError(f"HORIZON_END_NOT_VISIBLE:{trade['symbol']}:{horizon_bars}:{int(window[-1]['ts_ms'])}:{end_ts}")
    entry = float(trade["entry"])
    sl = float(trade["sl"])
    cost = float(trade["realized_cost_bps"])
    active: list[dict[str, Any]] = []
    stop_ts = None
    for bar in window:
        active.append(bar)
        if float(bar["low"]) <= sl:
            stop_ts = int(bar["ts_ms"])
            break
    max_high = max(float(x["high"]) for x in active)
    min_low = min(float(x["low"]) for x in active)
    mfe_gross = (max_high - entry) / entry * 10_000.0
    mae_gross = (entry - min_low) / entry * 10_000.0
    return {
        "symbol": trade["symbol"],
        "horizon_bars": horizon_bars,
        "horizon_end_ts": end_ts,
        "sl_hit": stop_ts is not None,
        "sl_hit_ts": stop_ts,
        "bars_observed_until_exit_or_horizon": len(active),
        "mfe_gross_bps": mfe_gross,
        "mfe_net_upper_conservative_bps": mfe_gross - cost,
        "mae_gross_bps": mae_gross,
        "upper_bound_is_nontradable_and_optimistic_on_extended_funding": True,
    }


def run(out: Path) -> dict[str, Any]:
    parent = read(PARENT)
    source = read(FRESH)
    validate_source(source)
    p = parent_algebra(parent)
    trades = [dict(x) for x in source["trades"]]
    bars_by_symbol = {str(t["symbol"]): ev.fetch_bars(str(t["symbol"]), "1h", limit=1000) for t in trades}
    by_horizon: dict[str, Any] = {}
    required_payoff_total = len(trades) * float(p["avg_win_bps"])
    required_expectancy_total = len(trades) * float(p["net_expectancy_bps"])
    first_payoff_feasible = None
    for h in HORIZONS:
        rows = [horizon_upper(t, bars_by_symbol[str(t["symbol"])], h) for t in trades]
        upper = [float(x["mfe_net_upper_conservative_bps"]) for x in rows]
        total = sum(upper)
        union = union_metrics(p, upper)
        payoff_feasible = total >= required_payoff_total
        expectancy_feasible = total >= required_expectancy_total
        if payoff_feasible and first_payoff_feasible is None:
            first_payoff_feasible = h
        by_horizon[str(h)] = {
            "trades": rows,
            "mfe_added_total_net_upper_bps": total,
            "payoff_preservation_theoretically_feasible": payoff_feasible,
            "expectancy_preservation_theoretically_feasible": expectancy_feasible,
            "upper_bound_union": union,
        }
    if first_payoff_feasible is None:
        root = "ENTRY_AMPLITUDE_CEILING_THROUGH_96BARS"
        next_axis = "ADD_ONLY_HIGH_AMPLITUDE_ENTRY_QUALITY"
    elif first_payoff_feasible > 48:
        root = "TIMEOUT_HORIZON_CEILING"
        next_axis = f"EXIT_ONLY_TIMEOUT_EXTENSION_TO_{first_payoff_feasible}B_PREDECLARED"
    else:
        root = "EXIT_CAPTURE_DEFICIENCY_WITHIN_48BARS"
        next_axis = "EXIT_ONLY_CAUSAL_CAPTURE_RULE"
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TIMEOUT_HORIZON_ROOT_CAUSE_DIAGNOSTIC",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_primary_wr8125",
        "horizons_bars": list(HORIZONS),
        "parent_payoff": p["payoff"],
        "parent_expectancy_bps": p["net_expectancy_bps"],
        "parent_avg_win_bps": p["avg_win_bps"],
        "required_fresh2_total_bps_to_preserve_payoff": required_payoff_total,
        "required_fresh2_total_bps_to_preserve_expectancy": required_expectancy_total,
        "by_horizon": by_horizon,
        "first_payoff_feasible_horizon_bars": first_payoff_feasible,
        "root_cause": root,
        "next_axis": next_axis,
        "policy": {
            "diagnostic_upper_bound_only": True,
            "no_exit_candidate_selected": True,
            "same_entry_ids": True,
            "same_sl": True,
            "production_ssot_unchanged": True,
            "numeric_horizons_are_diagnostic_not_promotable": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    source = read(FRESH)
    validate_source(source)
    assert HORIZONS == (48, 72, 96)
    assert all(int(x["timeout_bars"]) == 48 for x in source["trades"])
    print("PASS_A1_TRENDRIDER_8125_FRESH2_TIMEOUT_HORIZON_DIAGNOSTIC_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_8125_fresh2_timeout_horizon_diagnostic_v1.json"))
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print("A1_TRENDRIDER_8125_TIMEOUT_HORIZON=" + json.dumps({
        "root_cause": r["root_cause"],
        "first_payoff_feasible_horizon_bars": r["first_payoff_feasible_horizon_bars"],
        "by_horizon": r["by_horizon"],
        "next_axis": r["next_axis"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
