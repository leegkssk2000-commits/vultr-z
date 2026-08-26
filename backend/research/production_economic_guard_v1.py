#!/usr/bin/env python3
from __future__ import annotations

import math
from typing import Any, Mapping

SCHEMA = "zel.research.production_economic_guard.v1"


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def snapshot(raw: Mapping[str, Any] | None) -> dict[str, float | int | None]:
    raw = raw or {}
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), Mapping) else raw

    def first(*keys: str) -> Any:
        for key in keys:
            if metrics.get(key) is not None:
                return metrics.get(key)
            if raw.get(key) is not None:
                return raw.get(key)
        return None

    trades_raw = first("trades", "completed_trades")
    try:
        trades = int(trades_raw) if trades_raw is not None else 0
    except (TypeError, ValueError):
        trades = 0
    return {
        "trades": trades,
        "net_pnl_bps": _finite(first("net_pnl_bps")),
        "net_expectancy_bps": _finite(first("net_expectancy_bps")),
        "profit_factor": _finite(first("profit_factor", "net_profit_factor")),
        "drawdown_bps": _finite(first("drawdown_bps", "max_drawdown_bps")),
        "win_rate": _finite(first("win_rate")),
    }


def evaluate(parent: Mapping[str, Any] | None, child: Mapping[str, Any] | None) -> dict[str, Any]:
    p = snapshot(parent)
    c = snapshot(child)
    reasons: list[str] = []

    # Production invariant: a repair/donor may not create a prettier DD by
    # suppressing the incumbent's usable trades. This also covers admission
    # collapse without inventing a new percentage threshold.
    if c["trades"] == 0:
        reasons.append("ZERO_TRADE_CHILD")
    if p["trades"] > 0 and c["trades"] < p["trades"]:
        reasons.append("TRADE_COUNT_DECREASE")

    pnl_worse = (
        p["net_pnl_bps"] is not None
        and c["net_pnl_bps"] is not None
        and float(c["net_pnl_bps"]) < float(p["net_pnl_bps"])
    )
    expectancy_worse = (
        p["net_expectancy_bps"] is not None
        and c["net_expectancy_bps"] is not None
        and float(c["net_expectancy_bps"]) < float(p["net_expectancy_bps"])
    )
    if pnl_worse and expectancy_worse:
        reasons.append("PNL_EXPECTANCY_BOTH_WORSE")

    dd_improved = (
        p["drawdown_bps"] is not None
        and c["drawdown_bps"] is not None
        and float(c["drawdown_bps"]) < float(p["drawdown_bps"])
    )
    dd_improvement_valid = bool(dd_improved and c["trades"] > 0 and c["trades"] >= p["trades"])

    return {
        "schema_version": SCHEMA,
        "pass": not reasons,
        "hard_fail": bool(reasons),
        "reasons": reasons,
        "parent": p,
        "child": c,
        "trade_delta": int(c["trades"]) - int(p["trades"]),
        "pnl_worse": pnl_worse,
        "expectancy_worse": expectancy_worse,
        "drawdown_improved_observed": dd_improved,
        "drawdown_improvement_valid": dd_improvement_valid,
        "zero_trade_dd_improvement_invalid": bool(c["trades"] == 0 and dd_improved),
        "donor_admission_density_collapse": bool(p["trades"] > 0 and c["trades"] < p["trades"]),
        "incumbent_state_action": "PRESERVE_UNCHANGED" if reasons else "KEEP_EVALUATING",
        "fresh25_state_action": "PRESERVE_UNCHANGED" if reasons else "UNCHANGED_BY_GUARD",
    }


def self_test() -> int:
    parent = {"trades": 9, "net_pnl_bps": 900.0, "net_expectancy_bps": 100.0, "drawdown_bps": 300.0}
    zero = {"trades": 0, "net_pnl_bps": 0.0, "net_expectancy_bps": None, "drawdown_bps": 0.0}
    g0 = evaluate(parent, zero)
    assert g0["hard_fail"] and "ZERO_TRADE_CHILD" in g0["reasons"] and "TRADE_COUNT_DECREASE" in g0["reasons"]
    assert g0["drawdown_improvement_valid"] is False and g0["zero_trade_dd_improvement_invalid"] is True

    fewer = {"trades": 7, "net_pnl_bps": 1000.0, "net_expectancy_bps": 140.0, "drawdown_bps": 200.0}
    gf = evaluate(parent, fewer)
    assert gf["hard_fail"] and gf["donor_admission_density_collapse"] is True

    worse = {"trades": 10, "net_pnl_bps": 800.0, "net_expectancy_bps": 80.0, "drawdown_bps": 250.0}
    gw = evaluate(parent, worse)
    assert gw["hard_fail"] and "PNL_EXPECTANCY_BOTH_WORSE" in gw["reasons"]

    good = {"trades": 10, "net_pnl_bps": 1000.0, "net_expectancy_bps": 110.0, "drawdown_bps": 250.0}
    gg = evaluate(parent, good)
    assert gg["pass"] and not gg["reasons"] and gg["drawdown_improvement_valid"] is True
    print("PASS_PRODUCTION_ECONOMIC_GUARD_V1_SELF_TEST")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
