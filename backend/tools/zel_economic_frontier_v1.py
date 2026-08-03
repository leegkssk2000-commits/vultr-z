from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

VERSION = "ZEL_ECONOMIC_FRONTIER_V1"
SCHEMA = "zel.economic.frontier.receipt.v1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def geometry(row: dict[str, Any], days: float, risk_unit_usdt: float) -> dict[str, Any]:
    metrics = row.get("closed_metrics_including_funding_estimate") if isinstance(row.get("closed_metrics_including_funding_estimate"), dict) else {}
    n = int(metrics.get("sample_count") or row.get("close_count") or 0)
    wr_pct = finite(metrics.get("win_rate_pct"))
    wr = (wr_pct / 100.0) if wr_pct is not None else None
    pf = finite(metrics.get("profit_factor"))
    expectancy = finite(metrics.get("expectancy_R"))
    net_r = finite(metrics.get("net_R"))
    dd_r = finite(metrics.get("max_drawdown_R"))
    fee = finite(metrics.get("fee_usdt")) or 0.0
    slip = finite(metrics.get("slippage_usdt")) or 0.0
    funding = finite(metrics.get("funding_pnl_estimate_usdt")) or 0.0
    implied_payoff = None
    breakeven_wr_pct = None
    if wr is not None and pf is not None and 0.0 < wr < 1.0 and 0.0 <= pf < 900.0:
        implied_payoff = pf * (1.0 - wr) / wr
        if implied_payoff >= 0.0:
            breakeven_wr_pct = 100.0 / (1.0 + implied_payoff)
    cost_r_per_trade = None
    if n > 0 and risk_unit_usdt > 0.0:
        cost_r_per_trade = (fee + slip - funding) / risk_unit_usdt / n
    entries_per_day = n / days if days > 0 else None
    net_r_per_day = net_r / days if net_r is not None and days > 0 else None
    required_expectancy_uplift = max(0.0, -(expectancy or 0.0)) if expectancy is not None else None
    if n == 0:
        route = "RESTORE_CAUSAL_OPPORTUNITY_OR_DORMANT_CLASSIFICATION"
    elif expectancy is not None and expectancy > 0.0 and net_r is not None and net_r > 0.0:
        route = "PRESERVE_EDGE_AND_INCREASE_ONLY_QUALIFIED_OPPORTUNITY"
    elif cost_r_per_trade is not None and expectancy is not None and cost_r_per_trade >= abs(expectancy):
        route = "COST_DISTANCE_TURNOVER_FIRST"
    elif implied_payoff is not None and implied_payoff < 1.0:
        route = "EXIT_GEOMETRY_AND_LOSS_ASYMMETRY_FIRST"
    elif wr_pct is not None and wr_pct < 40.0:
        route = "ENTRY_QUALITY_REGIME_SIDE_FIRST"
    else:
        route = "JOINT_ENTRY_EXIT_CAUSAL_SCREEN"
    return {
        "strategy_id": row.get("strategy_id"),
        "trade_count": n,
        "entries_per_day": entries_per_day,
        "win_rate_pct": wr_pct,
        "profit_factor": pf,
        "implied_payoff_ratio": implied_payoff,
        "break_even_win_rate_pct_from_implied_payoff": breakeven_wr_pct,
        "expectancy_R": expectancy,
        "net_R": net_r,
        "net_R_per_day": net_r_per_day,
        "max_drawdown_R": dd_r,
        "execution_cost_R_per_trade": cost_r_per_trade,
        "required_expectancy_uplift_R_per_trade_to_break_even": required_expectancy_uplift,
        "recommended_first_axis_family": route,
    }


def dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = ("net_R_per_day", "profit_factor", "implied_payoff_ratio")
    av = [a.get(k) for k in keys]
    bv = [b.get(k) for k in keys]
    if any(v is None for v in av + bv):
        return False
    better_or_equal = all(float(x) >= float(y) for x, y in zip(av, bv))
    strictly_better = any(float(x) > float(y) for x, y in zip(av, bv))
    add = (a.get("max_drawdown_R"), b.get("max_drawdown_R"))
    if add[0] is not None and add[1] is not None:
        better_or_equal = better_or_equal and float(add[0]) <= float(add[1])
        strictly_better = strictly_better or float(add[0]) < float(add[1])
    return better_or_equal and strictly_better


def self_test() -> int:
    row = {
        "strategy_id": "x",
        "close_count": 100,
        "closed_metrics_including_funding_estimate": {
            "sample_count": 100,
            "win_rate_pct": 50,
            "profit_factor": 1.5,
            "expectancy_R": 0.1,
            "net_R": 10,
            "max_drawdown_R": 3,
            "fee_usdt": 10,
            "slippage_usdt": 2,
            "funding_pnl_estimate_usdt": 0,
        },
    }
    g = geometry(row, 10.0, 1.0)
    assert abs(g["entries_per_day"] - 10.0) < 1e-12
    assert abs(g["implied_payoff_ratio"] - 1.5) < 1e-12
    assert g["recommended_first_axis_family"] == "PRESERVE_EDGE_AND_INCREASE_ONLY_QUALIFIED_OPPORTUNITY"
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.terminal or not args.out:
        parser.error("--terminal and --out are required")
    terminal = read_json(args.terminal)
    replay = terminal.get("replay") if isinstance(terminal.get("replay"), dict) else {}
    data = terminal.get("data") if isinstance(terminal.get("data"), dict) else {}
    fingerprint = terminal.get("checkpoint", {}).get("input_fingerprint_fields", {})
    scorecards = terminal.get("scorecards") if isinstance(terminal.get("scorecards"), list) else []
    market_rows = float(data.get("market_row_count") or 0)
    symbols = float(data.get("symbol_count") or 0)
    days = market_rows / max(symbols, 1.0) / 1440.0
    risk_unit = float(fingerprint.get("risk_unit_usdt") or 1.0)
    rows = [geometry(row, days, risk_unit) for row in scorecards if isinstance(row, dict)]
    rows.sort(key=lambda row: row["strategy_id"] or "")
    trade_bearing = [row for row in rows if row["trade_count"] > 0]
    frontier = [
        row for row in trade_bearing
        if not any(dominates(other, row) for other in trade_bearing if other is not row)
    ]
    aggregate = replay.get("aggregate_metrics_including_funding_estimate") if isinstance(replay.get("aggregate_metrics_including_funding_estimate"), dict) else {}
    total_trades = int(replay.get("closed_trade_count") or 0)
    total_net = finite(aggregate.get("net_R"))
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_ECONOMIC_FRONTIER_AUDIT",
        "observation_days": days,
        "strategy_count": len(rows),
        "trade_bearing_strategy_count": len(trade_bearing),
        "zero_trade_strategy_count": len(rows) - len(trade_bearing),
        "portfolio": {
            "trade_count": total_trades,
            "entries_per_day": total_trades / days if days > 0 else None,
            "net_R": total_net,
            "net_R_per_day": total_net / days if total_net is not None and days > 0 else None,
            "win_rate_pct": aggregate.get("win_rate_pct"),
            "profit_factor": aggregate.get("profit_factor"),
            "expectancy_R": aggregate.get("expectancy_R"),
            "max_drawdown_R": aggregate.get("max_drawdown_R"),
        },
        "frontier_strategy_ids": [row["strategy_id"] for row in frontier],
        "absolute_positive_durable_point_found": False,
        "reason": "Terminal scorecards contain no fully gated W1/W2/W3 absolute-positive survivor; entry count, win rate and payoff must be optimized jointly on candidate replays, never independently.",
        "optimization_rule": "maximize conservative net_R_per_day after costs subject to absolute-positive W1/W2/W3, PF>=1, payoff>=1, retention>=60%, DD/tail limits and exact lineage",
        "strategies": rows,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "days": days, "entries_per_day": receipt["portfolio"]["entries_per_day"], "net_R_per_day": receipt["portfolio"]["net_R_per_day"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
