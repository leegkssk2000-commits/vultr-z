#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import (
    ROOT,
    HARDENING_POLICY,
    _maps,
    concentration,
    economic_gate,
    keep_liquidity,
    keep_volatility_regime,
    metrics,
    read,
    stable,
    trade_identity,
)

SCHEMA = "zel.a1.break.vol_liquidity_dual_owner_arch.v1"
STRATEGY_ID = "break_and_continue"
ARCHITECTURE_ID = "break_vol_high_immediate__vol_low_liquidity_confirmed_v1"
CHANGED_AXIS = "VOLATILITY_LIQUIDITY_DUAL_OWNER_ROUTING"


def route_decision(*, high_vol: bool, liquid: bool) -> str:
    if high_vol:
        return "VOL_HIGH_BREAKOUT_OWNER"
    if liquid:
        return "VOL_LOW_LIQUIDITY_CONFIRMED_OWNER"
    return "REJECT_VOL_LOW_UNCONFIRMED"


def _ratio_ge(child: Any, parent: Any) -> bool:
    if child is None or parent is None:
        return child is parent
    return float(child) + 1e-12 >= float(parent)


def evaluate(parent_path: Path) -> dict[str, Any]:
    parent = read(parent_path)
    if parent.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError(f"BREAK_PARENT_ID_MISMATCH:{parent.get('strategy_id')}")
    if parent.get("parameter_sweep") not in (False, None):
        raise RuntimeError("BREAK_PARENT_PARAMETER_SWEEP_NOT_FALSE")

    hard = read(HARDENING_POLICY)
    bars_by, maps = _maps(parent)
    parent_trades = [dict(x) for x in parent.get("trades") or []]
    if not parent_trades:
        raise RuntimeError("BREAK_PARENT_EMPTY")

    child: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    counts = {
        "VOL_HIGH_BREAKOUT_OWNER": 0,
        "VOL_LOW_LIQUIDITY_CONFIRMED_OWNER": 0,
        "REJECT_VOL_LOW_UNCONFIRMED": 0,
    }

    for trade in parent_trades:
        high = bool(keep_volatility_regime(trade, bars_by, maps))
        liquid = bool(keep_liquidity(trade, bars_by, maps))
        route = route_decision(high_vol=high, liquid=liquid)
        counts[route] += 1
        decisions.append({
            "trade_id": trade_identity(trade),
            "symbol": trade.get("symbol"),
            "signal_ts": trade.get("signal_ts"),
            "side": trade.get("side"),
            "volatility_owner_high": high,
            "liquidity_confirmed": liquid,
            "route": route,
        })
        if route != "REJECT_VOL_LOW_UNCONFIRMED":
            child.append(trade)

    parent_ids = {trade_identity(x) for x in parent_trades}
    child_ids = {trade_identity(x) for x in child}
    if not child_ids.issubset(parent_ids):
        raise RuntimeError("BREAK_DUAL_OWNER_CHILD_NOT_PARENT_SUBSET")

    pm = metrics(parent_trades)
    cm = metrics(child)
    parent_h5 = concentration(parent_trades, bars_by, maps, hard)
    child_h5 = concentration(child, bars_by, maps, hard)
    retention = 100.0 * len(child) / len(parent_trades)
    economic_ok, economic_blockers = economic_gate(cm, retention, hard)

    strict_checks = {
        "positive_net": float(cm.get("net_pnl_bps") or 0.0) > 0.0,
        "net_not_below_parent": float(cm.get("net_pnl_bps") or 0.0) + 1e-12 >= float(pm.get("net_pnl_bps") or 0.0),
        "expectancy_not_below_parent": _ratio_ge(cm.get("net_expectancy_bps"), pm.get("net_expectancy_bps")),
        "pf_not_below_parent": _ratio_ge(cm.get("profit_factor"), pm.get("profit_factor")),
        "payoff_positive": cm.get("payoff") is not None and float(cm.get("payoff")) > 1.0,
        "dd_not_above_parent": float(cm.get("drawdown_bps") or 0.0) <= float(pm.get("drawdown_bps") or 0.0) + 1e-12,
        "economic_gate_pass": bool(economic_ok),
        "h5_blocker_reduced": int(child_h5.get("blocker_count") or 0) < int(parent_h5.get("blocker_count") or 0),
    }
    ready = all(strict_checks.values())

    out = {
        "schema_version": SCHEMA,
        "state": "PASS_BREAK_ARCHITECTURE_DEVELOPMENT_READY" if ready else "FAIL_BREAK_ARCHITECTURE_REPLACE_NEXT_DISTINCT_MECHANISM",
        "strategy_id": STRATEGY_ID,
        "architecture_id": ARCHITECTURE_ID,
        "changed_axis": CHANGED_AXIS,
        "changed_axis_count": 1,
        "mechanism": {
            "vol_high_owner": "existing_breakout_owner_when_ATR14_GE_ATR50",
            "vol_low_owner": "existing_breakout_trade_only_when_quote_liquidity_GE_prior20_median",
            "numeric_threshold_sweep": False,
            "post_outcome_threshold_fit": False,
            "source_geometry": "a1_a4_exact_parent_repair_batch_v1.py",
        },
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "parent_metrics": pm,
        "child_metrics": cm,
        "trade_retention_pct": retention,
        "route_counts": counts,
        "parent_concentration": parent_h5,
        "child_concentration": child_h5,
        "economic_gate_pass": economic_ok,
        "economic_gate_blockers": economic_blockers,
        "strict_checks": strict_checks,
        "development_candidate_ready": ready,
        "fresh_prospective_required_before_promotion": True,
        "parent_trade_identity_subset": True,
        "new_trade_admission": False,
        "parent_entry_geometry_mutated": False,
        "parent_stop_timeout_cost_mutated": False,
        "parameter_sweep": False,
        "post_outcome_trade_deletion": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "exchange_order_submitted": False,
        "decisions": decisions,
    }
    out["receipt_sha256"] = stable(out)
    return out


def self_test() -> None:
    assert route_decision(high_vol=True, liquid=False) == "VOL_HIGH_BREAKOUT_OWNER"
    assert route_decision(high_vol=True, liquid=True) == "VOL_HIGH_BREAKOUT_OWNER"
    assert route_decision(high_vol=False, liquid=True) == "VOL_LOW_LIQUIDITY_CONFIRMED_OWNER"
    assert route_decision(high_vol=False, liquid=False) == "REJECT_VOL_LOW_UNCONFIRMED"
    assert CHANGED_AXIS == "VOLATILITY_LIQUIDITY_DUAL_OWNER_ROUTING"
    print("PASS_BREAK_VOL_LIQUIDITY_DUAL_OWNER_SELF_TEST")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parent")
    p.add_argument("--out")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.parent or not args.out:
        raise SystemExit("--parent and --out required")
    out = evaluate(Path(args.parent))
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": out["state"],
        "parent": out["parent_metrics"],
        "child": out["child_metrics"],
        "retention": out["trade_retention_pct"],
        "routes": out["route_counts"],
        "strict": out["strict_checks"],
        "ready": out["development_candidate_ready"],
        "receipt": out["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
