from __future__ import annotations

import importlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v1: Any = importlib.import_module(
    "backend.research.rebuild.a1_cross_sectional_mean_reversion_v1"
)
v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)

ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "cross_sectional_mean_reversion_v2.json"
TF_MULT = 6  # 30m
LOOKBACK_BARS = 6  # 3h dislocation
MAX_HOLD_BARS = 8  # 4h hard ceiling
CONVERGENCE_FRACTION = 0.50
COST_MULTIPLE = 6.0


def monthly(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = datetime.fromtimestamp(
            int(row["exit_ts"]) / 1000, tz=timezone.utc
        ).strftime("%Y-%m")
        grouped[key].append(row)
    return {key: v1.metrics(grouped[key]) for key in sorted(grouped)}


def build_market() -> tuple[list[int], pd.DataFrame, pd.DataFrame]:
    base = v2.util.load_5m()
    frames = {
        symbol: v2.util.resample_frame(base[symbol], TF_MULT).set_index("ts_ms")
        for symbol in v2.SYMS6
    }
    common = sorted(
        set.intersection(*(set(frame.index.astype(int)) for frame in frames.values()))
    )
    close = pd.DataFrame(
        {
            symbol: frames[symbol].loc[common, "close"].astype(float).values
            for symbol in v2.SYMS6
        },
        index=common,
    )
    open_px = pd.DataFrame(
        {
            symbol: frames[symbol].loc[common, "open"].astype(float).values
            for symbol in v2.SYMS6
        },
        index=common,
    )
    return common, close, open_px


def replay() -> tuple[list[dict[str, Any]], int, dict[str, float]]:
    common, close, open_px = build_market()
    feature_ts, regimes, cutoff = v1.regime_lookup()
    authority = v2.read_json(v2.COST_PATH)
    costs = {}
    for symbol in v2.SYMS6:
        snap = v2.cost_ev.fetch_execution_snapshot(symbol, authority)
        costs[symbol] = float(snap["pretrade_verified_cost_bps"])
    ret = close / close.shift(LOOKBACK_BARS) - 1.0
    trades: list[dict[str, Any]] = []
    blocked_until = -1
    i = max(20, LOOKBACK_BARS + 2)
    while i < len(common) - MAX_HOLD_BARS - 1:
        if i <= blocked_until:
            i += 1
            continue
        current = ret.iloc[i]
        previous = ret.iloc[i - 1]
        leader = str(current.idxmax())
        laggard = str(current.idxmin())
        spread = float(current[leader] - current[laggard])
        prev_spread = float(previous.max() - previous.min())
        pair_cost = 0.5 * (costs[leader] + costs[laggard])
        min_spread = COST_MULTIPLE * pair_cost / 10_000.0
        same_extremes = previous.idxmax() == leader and previous.idxmin() == laggard
        if spread < min_spread or not same_extremes or spread >= prev_spread:
            i += 1
            continue
        signal_ts = int(common[i])
        entry_long = float(open_px.iloc[i + 1][laggard])
        entry_short = float(open_px.iloc[i + 1][leader])
        entry_spread = spread
        exit_i = i + MAX_HOLD_BARS
        exit_reason = "TIME_CAP"
        for j in range(i + 1, min(i + MAX_HOLD_BARS + 1, len(common))):
            now = ret.iloc[j]
            now_spread = float(now[leader] - now[laggard])
            if now_spread <= CONVERGENCE_FRACTION * entry_spread:
                exit_i = j
                exit_reason = "SPREAD_HALF_LIFE"
                break
        exit_long = float(close.iloc[exit_i][laggard])
        exit_short = float(close.iloc[exit_i][leader])
        gross = 0.5 * (
            (exit_long - entry_long) / entry_long * 10_000.0
            + (entry_short - exit_short) / entry_short * 10_000.0
        )
        pos = int(np.searchsorted(feature_ts, signal_ts, side="right") - 1)
        trades.append(
            {
                "signal_ts": signal_ts,
                "entry_ts": int(common[i + 1]),
                "exit_ts": int(common[exit_i]),
                "long_symbol": laggard,
                "short_symbol": leader,
                "spread3h": spread,
                "gross_bps": gross,
                "cost_bps": pair_cost,
                "net_bps": gross - pair_cost,
                "exit_reason": exit_reason,
                "regime": regimes[pos] if pos >= 0 else "NO_CONTEXT",
            }
        )
        blocked_until = exit_i
        i += 1
    return trades, cutoff, costs


def diagnostics(trades: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    train = [t for t in trades if int(t["signal_ts"]) <= cutoff]
    hold = [t for t in trades if int(t["signal_ts"]) > cutoff]
    by_regime = {
        regime: v1.metrics([t for t in trades if t["regime"] == regime])
        for regime in sorted({str(t["regime"]) for t in trades})
    }
    leave_one_out = {
        symbol: v1.metrics(
            [
                t
                for t in trades
                if t["long_symbol"] != symbol and t["short_symbol"] != symbol
            ]
        )
        for symbol in v2.SYMS6
    }
    return {
        "full": v1.metrics(trades),
        "train60_time": v1.metrics(train),
        "holdout40_time": v1.metrics(hold),
        "months": monthly(trades),
        "by_regime": by_regime,
        "leave_one_symbol_out": leave_one_out,
        "exit_reasons": {
            str(k): int(v)
            for k, v in pd.Series([t["exit_reason"] for t in trades])
            .value_counts()
            .items()
        },
    }


def main() -> int:
    trades, cutoff, costs = replay()
    diag = diagnostics(trades, cutoff)
    if trades:
        days = max(
            (
                max(int(t["exit_ts"]) for t in trades)
                - min(int(t["signal_ts"]) for t in trades)
            )
            / 86_400_000.0,
            1e-9,
        )
    else:
        days = 0.0
    out = {
        "schema": "zel.cross_sectional_mean_reversion.v2",
        "state": "DEV_ARCHITECTURE_TEST_FRESH_FORWARD_REQUIRED",
        "architecture": "30m market-neutral 3h relative-value dislocation, first contraction, cost-scaled opportunity gate, dynamic half-spread exit",
        "rules_frozen": {
            "timeframe": "30m",
            "lookback_bars": LOOKBACK_BARS,
            "cost_multiple": COST_MULTIPLE,
            "confirmation": "same leader/laggard as prior bar and first contraction",
            "exit": f"spread <= {CONVERGENCE_FRACTION:.2f}x entry spread or {MAX_HOLD_BARS} bars",
            "occupancy": "one pair globally until exit",
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
        "XSEC_MEAN_REVERSION_V2="
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
