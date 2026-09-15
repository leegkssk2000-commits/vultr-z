from __future__ import annotations

import importlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

v1: Any = importlib.import_module(
    "backend.research.rebuild.a1_cross_sectional_mean_reversion_v1"
)
v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)

ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "cross_sectional_mean_reversion_concurrent_v3.json"


def monthly(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = datetime.fromtimestamp(
            int(row["exit_ts"]) / 1000, tz=timezone.utc
        ).strftime("%Y-%m")
        grouped[key].append(row)
    return {key: v1.metrics(grouped[key]) for key in sorted(grouped)}


def replay() -> tuple[list[dict[str, Any]], int, dict[str, float]]:
    common, close, open_px = v1.build_market()
    feature_ts, regimes, cutoff = v1.regime_lookup()
    authority = v2.read_json(v2.COST_PATH)
    costs = {}
    for symbol in v2.SYMS6:
        snap = v2.cost_ev.fetch_execution_snapshot(symbol, authority)
        costs[symbol] = float(snap["pretrade_verified_cost_bps"])
    ret = close / close.shift(v1.LOOKBACK_BARS) - 1.0
    trades: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    i = max(20, v1.LOOKBACK_BARS + 2)
    while i < len(common) - v1.HOLD_BARS - 1:
        active = [x for x in active if int(x["exit_i"]) > i]
        used = {sym for x in active for sym in (x["leader"], x["laggard"])}
        current, previous = ret.iloc[i], ret.iloc[i - 1]
        leader, laggard = str(current.idxmax()), str(current.idxmin())
        spread = float(current[leader] - current[laggard])
        prev_spread = float(previous.max() - previous.min())
        same_extremes = previous.idxmax() == leader and previous.idxmin() == laggard
        first_contraction = spread < prev_spread
        if spread < v1.SPREAD_THRESHOLD or not same_extremes or not first_contraction:
            i += 1
            continue
        if leader in used or laggard in used:
            i += 1
            continue
        signal_ts = int(common[i])
        entry_long = float(open_px.iloc[i + 1][laggard])
        entry_short = float(open_px.iloc[i + 1][leader])
        exit_i = i + v1.HOLD_BARS
        exit_long = float(close.iloc[exit_i][laggard])
        exit_short = float(close.iloc[exit_i][leader])
        gross = 0.5 * (
            (exit_long - entry_long) / entry_long * 10_000.0
            + (entry_short - exit_short) / entry_short * 10_000.0
        )
        cost = 0.5 * (costs[laggard] + costs[leader])
        pos = int(np.searchsorted(feature_ts, signal_ts, side="right") - 1)
        trades.append(
            {
                "signal_ts": signal_ts,
                "entry_ts": int(common[i + 1]),
                "exit_ts": int(common[exit_i]),
                "long_symbol": laggard,
                "short_symbol": leader,
                "spread6h": spread,
                "gross_bps": gross,
                "cost_bps": cost,
                "net_bps": gross - cost,
                "regime": regimes[pos] if pos >= 0 else "NO_CONTEXT",
            }
        )
        active.append({"leader": leader, "laggard": laggard, "exit_i": exit_i})
        i += 1
    return trades, cutoff, costs


def diagnostics(trades: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    train = [t for t in trades if int(t["signal_ts"]) <= cutoff]
    hold = [t for t in trades if int(t["signal_ts"]) > cutoff]
    return {
        "full": v1.metrics(trades),
        "train60_time": v1.metrics(train),
        "holdout40_time": v1.metrics(hold),
        "months": monthly(trades),
        "leave_one_symbol_out": {
            symbol: v1.metrics(
                [
                    t
                    for t in trades
                    if t["long_symbol"] != symbol and t["short_symbol"] != symbol
                ]
            )
            for symbol in v2.SYMS6
        },
    }


def main() -> int:
    trades, cutoff, costs = replay()
    diag = diagnostics(trades, cutoff)
    days = 0.0
    if trades:
        days = max(
            (
                max(int(t["exit_ts"]) for t in trades)
                - min(int(t["signal_ts"]) for t in trades)
            )
            / 86_400_000.0,
            1e-9,
        )
    out = {
        "schema": "zel.cross_sectional_mean_reversion.concurrent.v3",
        "state": "DEV_ARCHITECTURE_TEST_FRESH_FORWARD_REQUIRED",
        "architecture": "v1 exact entry logic with non-overlapping concurrent pairs; no threshold relaxation",
        "rules_frozen": {
            "timeframe": "30m",
            "lookback_bars": v1.LOOKBACK_BARS,
            "spread_threshold": v1.SPREAD_THRESHOLD,
            "hold_bars": v1.HOLD_BARS,
            "portfolio_rule": "allow concurrent pairs only when no symbol overlaps any open pair",
        },
        "costs_bps_per_leg_round_trip": costs,
        "economics": diag,
        "T_per_day": len(trades) / days if days else 0.0,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "fresh_forward_required": True,
        "trades": trades,
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "XSEC_MR_CONCURRENT_V3="
        + json.dumps(
            {
                "full": diag["full"],
                "train": diag["train60_time"],
                "hold": diag["holdout40_time"],
                "T_per_day": out["T_per_day"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
