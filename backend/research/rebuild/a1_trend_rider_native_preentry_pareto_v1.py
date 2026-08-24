#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev


AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(x["net_bps"]) for x in rows]
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    gross_profit, gross_loss = sum(wins), sum(losses)
    return {
        "trades": len(rows),
        "win_rate": len(wins) / len(values) if values else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "profit_factor": ev.profit_factor(gross_profit, gross_loss),
        "max_drawdown_bps": ev.max_drawdown(values),
    }


def _delta(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("trades", "win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "max_drawdown_bps"):
        p, c = parent.get(key), child.get(key)
        out[key] = None if p is None or c is None else float(c) - float(p)
    return out


def screen(target: dict[str, Any]) -> dict[str, Any]:
    rows = [dict(x) for x in target.get("preentry_trade_ledger") or []]
    rows.sort(key=lambda x: (int(x["entry_ts"]), str(x["symbol"])))
    if len(rows) != int(target.get("completed_trades") or 0):
        raise RuntimeError("COMPLETE_NATIVE_PREENTRY_LEDGER_REQUIRED")
    parent = _metrics(rows)
    parent_winners = {str(x["entry_ts"]) + ":" + str(x["symbol"]) for x in rows if float(x["net_bps"]) > 0}

    axes: list[tuple[str, str, Callable[[dict[str, Any]], bool]]] = [
        (
            "ATR_PCT_SELF_NORMALIZED_COOL_ONLY",
            "ATR14/close <= its own prior rolling-100-bar mean; fixed causal geometry, no fitted cutoff",
            lambda x: bool(x.get("atr_pct_self_normalized_cool")),
        ),
        (
            "CHASE_COOLING_OR_FLAT_ONLY",
            "current chase_atr <= prior closed-bar chase_atr; ordinal comparison, no fitted cutoff",
            lambda x: bool(x.get("chase_cooling_or_flat")),
        ),
        (
            "FROZEN_NON_US_SESSION_ONLY",
            "APAC/EU retained; frozen H5 UTC taxonomy; no fitted session boundary",
            lambda x: str(x.get("session")) != "US",
        ),
        (
            "NON_US_PLUS_US_CHASE_COOLING_OR_FLAT_ONLY",
            "APAC/EU retained; US admitted only when current chase_atr <= prior closed-bar chase_atr",
            lambda x: str(x.get("session")) != "US" or bool(x.get("chase_cooling_or_flat")),
        ),
    ]
    candidates: list[dict[str, Any]] = []
    for axis, rule, predicate in axes:
        kept = [x for x in rows if predicate(x)]
        child = _metrics(kept)
        kept_winners = {str(x["entry_ts"]) + ":" + str(x["symbol"]) for x in kept if float(x["net_bps"]) > 0}
        winner_retention = len(kept_winners & parent_winners) / len(parent_winners) if parent_winners else None
        trade_retention = len(kept) / len(rows) if rows else None
        improved = [
            key for key in ("win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor")
            if parent.get(key) is not None and child.get(key) is not None and float(child[key]) > float(parent[key])
        ]
        dd_not_worse = float(child["max_drawdown_bps"]) <= float(parent["max_drawdown_bps"])
        pareto = bool(
            len(kept) >= 3
            and trade_retention is not None and trade_retention >= 0.60
            and winner_retention is not None and winner_retention >= 0.80
            and len(improved) >= 2
            and dd_not_worse
            and float(child["net_pnl_bps"]) > 0
        )
        candidates.append({
            "axis": axis,
            "rule": rule,
            "metrics": child,
            "delta_child_minus_parent": _delta(parent, child),
            "trade_retention": trade_retention,
            "winner_retention": winner_retention,
            "improved_metrics": improved,
            "drawdown_not_worse": dd_not_worse,
            "pareto_development_ready": pareto,
            "parameter_sweep": False,
            "outcome_feature_used_at_runtime": False,
        })
    candidates.sort(key=lambda x: (
        not bool(x["pareto_development_ready"]),
        -len(x["improved_metrics"]),
        -float(x["metrics"]["net_pnl_bps"]),
    ))
    ready = [x for x in candidates if x["pareto_development_ready"]]
    result = {
        "schema_version": "zel.a1.trend_rider.native_preentry_pareto.v1",
        "state": "PASS_NATIVE_PREENTRY_PARETO_FOUND" if ready else "HOLD_NO_NATIVE_PREENTRY_PARETO",
        "strategy_id": "trend_rider",
        "native_completed_trades": len(rows),
        "parent_metrics": parent,
        "candidates": candidates,
        "development_ready_count": len(ready),
        "selected_for_new_fresh_boundary": ready[0]["axis"] if ready else None,
        "incumbent_mutated": False,
        "numeric_threshold_sweep": False,
        "next": "PREREGISTER_WINNER_ON_NEW_FUTURE_BOUNDARY" if ready else "KEEP_INCUMBENT_AND_ACCUMULATE_NATIVE_TRADES",
        **AUTH,
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    return result


def self_test() -> int:
    fake = {
        "completed_trades": 5,
        "preentry_trade_ledger": [
            {"symbol": "A", "entry_ts": 1, "net_bps": 100, "atr_pct_self_normalized_cool": True, "chase_cooling_or_flat": True, "session": "EU"},
            {"symbol": "B", "entry_ts": 2, "net_bps": 80, "atr_pct_self_normalized_cool": True, "chase_cooling_or_flat": True, "session": "APAC"},
            {"symbol": "A", "entry_ts": 3, "net_bps": 60, "atr_pct_self_normalized_cool": True, "chase_cooling_or_flat": False, "session": "EU"},
            {"symbol": "B", "entry_ts": 4, "net_bps": -20, "atr_pct_self_normalized_cool": False, "chase_cooling_or_flat": True, "session": "US"},
            {"symbol": "A", "entry_ts": 5, "net_bps": -30, "atr_pct_self_normalized_cool": False, "chase_cooling_or_flat": False, "session": "US"},
        ],
    }
    row = screen(fake)
    assert row["development_ready_count"] >= 1, row
    assert row["candidates"][0]["parameter_sweep"] is False
    assert row["execution_authority"] == "NONE" and row["order_authority"] == "BLOCKED"
    print("PASS_A1_TREND_RIDER_NATIVE_PREENTRY_PARETO_V1")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostic", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.diagnostic is None or args.out is None:
        parser.error("--diagnostic and --out are required")
    source = json.loads(args.diagnostic.read_text(encoding="utf-8"))
    target = next(x for x in source["targets"] if x["strategy_id"] == "trend_rider")
    result = screen(target)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "parent_metrics": result["parent_metrics"],
        "selected": result["selected_for_new_fresh_boundary"],
        "candidates": result["candidates"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
