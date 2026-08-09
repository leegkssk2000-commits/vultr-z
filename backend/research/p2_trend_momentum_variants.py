#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import p2_trend_momentum_base as base


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--base-result", type=Path, required=True)
    ap.add_argument("--cost-model", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    plan = json.loads(ns.plan.read_text())
    manifest = json.loads(ns.manifest.read_text())
    base_result = json.loads(ns.base_result.read_text())
    cost = json.loads(ns.cost_model.read_text())

    if plan.get("state") != "FROZEN_BEFORE_VARIANT_REPLAY" or plan.get("predeclared_before_any_variant_replay") is not True:
        raise SystemExit("HOLD_VARIANT_PLAN_NOT_FROZEN")
    if base_result.get("state") != "FAIL_P2_TREND_MOMENTUM_BASE_EDGE":
        raise SystemExit("HOLD_BASE_RESULT_NOT_TERMINAL_FAIL")
    if not str(manifest.get("state", "")).startswith("PASS_") or int(manifest.get("forward_overlap_count", -1)) != 0:
        raise SystemExit("HOLD_HISTORICAL_MANIFEST")
    if plan.get("timeframe") != "15m" or plan.get("common", {}).get("same_bar_fill") is not False:
        raise SystemExit("HOLD_VARIANT_PLAN_DRIFT")
    variants = list(plan.get("variants", []))
    if len(variants) != 2:
        raise SystemExit("HOLD_VARIANT_COUNT_NOT_TWO")
    lookbacks = [int(v["lookback_bars"]) for v in variants]
    if lookbacks != [32, 96]:
        raise SystemExit(f"HOLD_VARIANT_LOOKBACK_DRIFT:{lookbacks}")

    base.require_cost(cost)
    c = base.worst_cost(cost)
    all_results: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []

    for variant in variants:
        candidate_id = str(variant["candidate_id"])
        lookback = int(variant["lookback_bars"])
        hours = float(variant["lookback_clock_hours"])
        results: list[dict[str, Any]] = []
        for window in (plan["data"]["development_window"], plan["data"]["oos_window"]):
            for symbol in plan["symbols"]:
                r = base.evaluate_window(ns.data_root, manifest, window, symbol, lookback, c, None)
                r["candidate_id"] = candidate_id
                r["lookback_bars"] = lookback
                r["lookback_clock_hours"] = hours
                results.append(r)
                all_results.append(r)
        oos = [x for x in results if x["window"] == plan["data"]["oos_window"]]
        pass_symbols = [x["symbol"] for x in oos if x["base_edge_pass"]]
        fail_symbols = [x["symbol"] for x in oos if not x["base_edge_pass"]]
        candidate_rows.append({
            "candidate_id": candidate_id,
            "lookback_bars": lookback,
            "lookback_clock_hours": hours,
            "rationale": variant["rationale"],
            "W2_edge_pass_symbols": pass_symbols,
            "W2_edge_fail_symbols": fail_symbols,
            "any_W2_edge_pass": bool(pass_symbols),
            "all_W2_edge_pass": len(pass_symbols) == len(oos) and bool(oos),
            "results": results,
        })

    passing_candidates = [x["candidate_id"] for x in candidate_rows if x["any_W2_edge_pass"]]
    if passing_candidates:
        state = "PASS_P2_VARIANT_EDGE_EXISTS_HOLD_SURVIVOR_GATE"
        nxt = "resolve DD SSOT and durability for passing candidate(s) without changing signal/exit; W3 remains untouched until gate authorization"
    else:
        state = "FAIL_P2_TREND_MOMENTUM_FAMILY_SIMPLE_DONCHIAN"
        nxt = "terminal-fail this simple Trend/Momentum mechanism and route to P3 carry_flow; do not add filters or optimize exits"

    receipt = {
        "schema_version": "zel.p2.trend_momentum_variants.replay.v1",
        "state": state,
        "family": "trend_momentum",
        "base_candidate": base_result.get("candidate_id"),
        "base_state": base_result.get("state"),
        "variants_predeclared_before_replay": True,
        "parameter_selection_performed": False,
        "exit_optimization_performed": False,
        "additional_filters_added": False,
        "timeframe": "15m",
        "symbols": plan["symbols"],
        "data": {
            "branch": plan["data"]["source_branch"],
            "development_window": plan["data"]["development_window"],
            "oos_window": plan["data"]["oos_window"],
            "untouched_window": plan["data"]["untouched_window"],
            "untouched_window_accessed": False,
            "forward_overlap_count": manifest.get("forward_overlap_count"),
        },
        "cost_source": {
            "receipt_sha256": cost["receipt_sha256"],
            "source_tier": cost["source_tier"],
            "observed_at": cost.get("observed_at"),
            "shared_worst_available_cost_envelope": c,
            "notional_bucket_selection_performed": False,
        },
        "candidate_rows": candidate_rows,
        "passing_candidates": passing_candidates,
        "dd_ssot": "UNRESOLVED_AND_NOT_EVALUATED_UNLESS_W2_EDGE_PASSES",
        "win_rate_is_pass_gate": False,
        "untouched_w3_accessed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": nxt,
    }
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "state": state,
        "passing_candidates": passing_candidates,
        "W3_accessed": False,
        "candidate_summary": [
            {"candidate_id": x["candidate_id"], "W2_pass": x["W2_edge_pass_symbols"], "W2_fail": x["W2_edge_fail_symbols"]}
            for x in candidate_rows
        ],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
