from __future__ import annotations

import importlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
mx: Any = importlib.import_module(
    "backend.research.rebuild.a1_strategy_regime_alpha_matrix_v1"
)

ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "cross_sectional_mean_reversion_v1.json"
TF_MULT = 6  # exact 5m -> 30m
LOOKBACK_BARS = 12  # 6h
SPREAD_THRESHOLD = 0.03
HOLD_BARS = 8  # 4h


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in sorted(rows, key=lambda x: int(x["exit_ts"]))]
    wins, losses = [x for x in vals if x > 0], [-x for x in vals if x < 0]
    eq = peak = dd = 0.0
    streak = max_streak = 0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if value < 0 else 0
        max_streak = max(max_streak, streak)
    return {
        "T": len(vals),
        "WR": len(wins) / len(vals) if vals else None,
        "Net_bps": sum(vals),
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": sum(wins) / sum(losses) if losses else None,
        "DD_bps": dd,
        "MaxLossStreak": max_streak,
    }


def monthly(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = datetime.fromtimestamp(
            int(row["exit_ts"]) / 1000, tz=timezone.utc
        ).strftime("%Y-%m")
        grouped[key].append(row)
    return {key: metrics(grouped[key]) for key in sorted(grouped)}


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


def regime_lookup() -> tuple[np.ndarray, list[str], int]:
    feat, cutoff, q = mx.build_features()
    ts = feat["ts_ms"].to_numpy(dtype=np.int64)
    labels = [mx.regime(row, q) for _, row in feat.iterrows()]
    return ts, labels, cutoff


def replay() -> tuple[list[dict[str, Any]], int, dict[str, float]]:
    common, close, open_px = build_market()
    feature_ts, regimes, cutoff = regime_lookup()
    authority = v2.read_json(v2.COST_PATH)
    costs = {
        symbol: float(
            v2.cost_ev.fetch_execution_snapshot(symbol, authority)[
                "pretrade_verified_cost_bps"
            ]
        )
        for symbol in v2.SYMS6
    }
    ret = close / close.shift(LOOKBACK_BARS) - 1.0
    trades: list[dict[str, Any]] = []
    blocked_until = -1
    i = max(20, LOOKBACK_BARS + 2)
    while i < len(common) - HOLD_BARS - 1:
        if i <= blocked_until:
            i += 1
            continue
        current, previous = ret.iloc[i], ret.iloc[i - 1]
        leader, laggard = str(current.idxmax()), str(current.idxmin())
        spread = float(current[leader] - current[laggard])
        prev_spread = float(previous.max() - previous.min())
        same_extremes = previous.idxmax() == leader and previous.idxmin() == laggard
        first_contraction = spread < prev_spread
        if spread < SPREAD_THRESHOLD or not same_extremes or not first_contraction:
            i += 1
            continue
        signal_ts = int(common[i])
        entry_long = float(open_px.iloc[i + 1][laggard])
        entry_short = float(open_px.iloc[i + 1][leader])
        exit_long = float(close.iloc[i + HOLD_BARS][laggard])
        exit_short = float(close.iloc[i + HOLD_BARS][leader])
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
                "exit_ts": int(common[i + HOLD_BARS]),
                "long_symbol": laggard,
                "short_symbol": leader,
                "spread6h": spread,
                "gross_bps": gross,
                "cost_bps": cost,
                "net_bps": gross - cost,
                "regime": regimes[pos] if pos >= 0 else "NO_CONTEXT",
            }
        )
        blocked_until = i + HOLD_BARS
        i += 1
    return trades, cutoff, costs


def diagnostics(trades: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    train = [t for t in trades if int(t["signal_ts"]) <= cutoff]
    hold = [t for t in trades if int(t["signal_ts"]) > cutoff]
    by_regime: dict[str, Any] = {}
    for regime in sorted({str(t["regime"]) for t in trades}):
        by_regime[regime] = metrics([t for t in trades if t["regime"] == regime])
    leave_one_out = {
        symbol: metrics(
            [
                t
                for t in trades
                if t["long_symbol"] != symbol and t["short_symbol"] != symbol
            ]
        )
        for symbol in v2.SYMS6
    }
    wins = sorted(
        (float(t["net_bps"]) for t in trades if float(t["net_bps"]) > 0), reverse=True
    )
    net = sum(float(t["net_bps"]) for t in trades)
    gross_profit = sum(wins)
    return {
        "full": metrics(trades),
        "train60_time": metrics(train),
        "holdout40_time": metrics(hold),
        "months": monthly(trades),
        "by_regime": by_regime,
        "leave_one_symbol_out": leave_one_out,
        "concentration": {
            "top1_over_net": wins[0] / net if wins and net > 0 else None,
            "top3_over_net": sum(wins[:3]) / net if wins and net > 0 else None,
            "top1_over_gross_profit": wins[0] / gross_profit if gross_profit else None,
        },
    }


def overlap_with_directional_core(trades: list[dict[str, Any]]) -> dict[str, Any]:
    a2: Any = importlib.import_module(
        "backend.research.rebuild.a1_economic_core_loss_autopsy_v2"
    )
    feat, _, _, rider_raw, source, hg = a2.build_inputs()
    rider = a2.attach_context(feat, rider_raw, source)
    core_hours = {int(x["signal_ts"]) // 3_600_000 for x in [*hg, *rider]}
    overlap = sum(int(t["signal_ts"]) // 3_600_000 in core_hours for t in trades)
    return {
        "trade_count": len(trades),
        "same_hour_overlap_count": overlap,
        "same_hour_overlap_rate": overlap / len(trades) if trades else None,
    }


def main() -> int:
    trades, cutoff, costs = replay()
    diag = diagnostics(trades, cutoff)
    span_days = (
        max(
            (
                max(int(t["exit_ts"]) for t in trades)
                - min(int(t["signal_ts"]) for t in trades)
            )
            / 86_400_000.0,
            1e-9,
        )
        if trades
        else 0.0
    )
    out = {
        "schema": "zel.cross_sectional_mean_reversion.v1",
        "state": "DEV_SURVIVOR_HISTORY_INSPECTED_FRESH_FORWARD_REQUIRED",
        "architecture": "30m market-neutral long laggard / short leader after a 6h cross-sectional 3% stretch begins contracting",
        "rules_frozen": {
            "timeframe": "30m",
            "lookback_bars": LOOKBACK_BARS,
            "spread_threshold": SPREAD_THRESHOLD,
            "confirmation": "same leader/laggard as prior bar and cross-sectional spread contracts",
            "entry": "next 30m open",
            "hold_bars": HOLD_BARS,
            "gross_exposure": "1.0x total: 0.5x long + 0.5x short",
            "occupancy": "one pair globally until exit",
        },
        "costs_bps_per_leg_round_trip": costs,
        "economics": diag,
        "T_per_day": len(trades) / span_days if span_days else 0.0,
        "directional_core_overlap": overlap_with_directional_core(trades),
        "selection_note": "3% threshold retained after a bounded 2%-3% development bracket; 2.5% midpoint failed holdout and no further threshold search is authorized",
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "fresh_forward_required": True,
        "trades": trades,
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "XSEC_MEAN_REVERSION="
        + json.dumps(
            {
                "full": diag["full"],
                "train": diag["train60_time"],
                "hold": diag["holdout40_time"],
                "T_per_day": out["T_per_day"],
                "overlap": out["directional_core_overlap"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
