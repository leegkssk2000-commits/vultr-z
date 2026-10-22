from __future__ import annotations

import importlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

mr: Any = importlib.import_module(
    "backend.research.rebuild.a1_cross_sectional_mean_reversion_v1"
)

MIN_FAIL_BARS = 4
OUT = Path(__file__).resolve().parents[3] / (
    "research/campaigns/scalp7_20260915/SCALP7_MR_REEXPANSION_EXIT_V1.json"
)


def should_fail_reexpand(
    signal_spread: float, current_spread: float, bars_held: int
) -> bool:
    return bars_held >= MIN_FAIL_BARS and current_spread >= signal_spread


def _monthly(rows: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        month = datetime.fromtimestamp(
            int(row["exit_ts"]) / 1000, tz=timezone.utc
        ).strftime("%Y-%m")
        out[month] = out.get(month, 0.0) + float(row["net_bps"])
    return dict(sorted(out.items()))


def replay(use_reexpansion_exit: bool) -> tuple[list[dict[str, Any]], int]:
    common, close, open_px = mr.build_market()
    feature_ts, regimes, cutoff = mr.regime_lookup()
    authority = mr.v2.read_json(mr.v2.COST_PATH)
    costs = {
        symbol: float(
            mr.v2.cost_ev.fetch_execution_snapshot(symbol, authority)[
                "pretrade_verified_cost_bps"
            ]
        )
        for symbol in mr.v2.SYMS6
    }
    ret = close / close.shift(mr.LOOKBACK_BARS) - 1.0
    trades: list[dict[str, Any]] = []
    blocked_until = -1
    i = max(20, mr.LOOKBACK_BARS + 2)
    while i < len(common) - mr.HOLD_BARS - 1:
        if i <= blocked_until:
            i += 1
            continue
        current, previous = ret.iloc[i], ret.iloc[i - 1]
        leader, laggard = str(current.idxmax()), str(current.idxmin())
        spread = float(current[leader] - current[laggard])
        prev_spread = float(previous.max() - previous.min())
        same_extremes = previous.idxmax() == leader and previous.idxmin() == laggard
        if (
            spread < mr.SPREAD_THRESHOLD
            or not same_extremes
            or not spread < prev_spread
        ):
            i += 1
            continue
        signal_ts = int(common[i])
        entry_long = float(open_px.iloc[i + 1][laggard])
        entry_short = float(open_px.iloc[i + 1][leader])
        exit_j = i + mr.HOLD_BARS
        exit_reason = "TIME_8BAR"
        if use_reexpansion_exit:
            for j in range(i + MIN_FAIL_BARS, i + mr.HOLD_BARS + 1):
                current_spread = float(ret.iloc[j][leader] - ret.iloc[j][laggard])
                if should_fail_reexpand(spread, current_spread, j - i):
                    exit_j = j
                    exit_reason = "THESIS_REEXPAND_FAIL"
                    break
        exit_long = float(close.iloc[exit_j][laggard])
        exit_short = float(close.iloc[exit_j][leader])
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
                "exit_ts": int(common[exit_j]),
                "long_symbol": laggard,
                "short_symbol": leader,
                "signal_spread6h": spread,
                "gross_bps": gross,
                "cost_bps": cost,
                "net_bps": gross - cost,
                "regime": regimes[pos] if pos >= 0 else "NO_CONTEXT",
                "exit_reason": exit_reason,
                "hold_bars": exit_j - i,
            }
        )
        blocked_until = exit_j
        i += 1
    return trades, cutoff


def summarize(rows: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    train = [row for row in rows if int(row["signal_ts"]) <= cutoff]
    hold = [row for row in rows if int(row["signal_ts"]) > cutoff]
    span_days = max(
        (
            max(int(row["exit_ts"]) for row in rows)
            - min(int(row["signal_ts"]) for row in rows)
        )
        / 86_400_000.0,
        1e-9,
    )
    return {
        "full": mr.metrics(rows),
        "train": mr.metrics(train),
        "hold": mr.metrics(hold),
        "T_per_day": len(rows) / span_days,
        "average_hold_bars": sum(int(row["hold_bars"]) for row in rows) / len(rows),
        "exit_reasons": dict(Counter(str(row["exit_reason"]) for row in rows)),
        "months_bps": _monthly(rows),
    }


def main() -> int:
    parent_rows, cutoff = replay(False)
    child_rows, child_cutoff = replay(True)
    if cutoff != child_cutoff:
        raise RuntimeError("CUTOFF_DRIFT")
    parent = summarize(parent_rows, cutoff)
    child = summarize(child_rows, cutoff)
    out = {
        "schema": "zel.scalp7.mr_reexpansion_exit.v1",
        "state": "DEV_LIFECYCLE_CANDIDATE_HISTORY_INSPECTED_FRESH_REQUIRED",
        "strategy_id": "cross_sectional_mean_reversion_v1",
        "timeframe": "30m",
        "parent_rule": "fixed 8-bar hold after frozen 6h spread contraction entry",
        "child_rule": (
            "preserve entry; from bar 4 onward exit when original leader-laggard 6h spread "
            "re-expands to or beyond the signal spread; otherwise keep 8-bar max hold"
        ),
        "axis": "LIFECYCLE_THESIS_FAILURE_ONLY",
        "minimum_fail_bars": MIN_FAIL_BARS,
        "parent": parent,
        "child": child,
        "decision": "DEV_FREEZE_FOR_FRESH_ONLY",
        "selection_note": (
            "bounded 1-5 bar lifecycle diagnostic was inspected; bar 4 is not formal OOS selection. "
            "No further historical retune is authorized."
        ),
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "fresh_forward_required": True,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "SCALP7_MR_REEXPANSION="
        + json.dumps({"parent": parent, "child": child}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
