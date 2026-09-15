"""Explicit calendar / cost / evidence partitions for Scalp7 research receipts.

Trade-bps sums are equal-notional diagnostics, not account percentage returns.
This module has no promotion thresholds, economic search, or order authority.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import math
from typing import Any

SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
BUCKET_MS = 900_000
DAY_MS = 86_400_000


def _number(value: Any, name: str) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"NONFINITE_METRIC:{name}")
    return v


def _time(value: Any, name: str) -> int:
    n = _number(value, name)
    if not n.is_integer():
        raise ValueError(f"NONINTEGER_TIMESTAMP:{name}")
    return int(n)


def _span(start_ms: int, end_ms: int) -> None:
    if _time(end_ms, "end_ms") <= _time(start_ms, "start_ms"):
        raise ValueError("POSITIVE_CALENDAR_SPAN_REQUIRED")


def partition_rows(
    rows: Sequence[Mapping[str, Any]], start_ms: int, end_ms: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Signal and outcome both belong to this half-open observed window."""
    _span(start_ms, end_ms)
    included: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    for raw in rows:
        row = dict(raw)
        signal = _time(row["signal_ts_ms"], "signal_ts_ms")
        entry = _time(row["entry_ts_ms"], "entry_ts_ms")
        exited = _time(row["exit_ts_ms"], "exit_ts_ms")
        available = _time(row["outcome_available_ts_ms"], "outcome_available_ts_ms")
        if not signal <= entry <= exited <= available:
            raise ValueError("TRADE_CAUSAL_TIMESTAMPS_INVALID")
        if signal < start_ms:
            excluded["SIGNAL_BEFORE_WINDOW_CARRY_IN_EXCLUDED"] += 1
        elif signal >= end_ms:
            excluded["SIGNAL_AT_OR_AFTER_WINDOW_END"] += 1
        elif available >= end_ms:
            excluded["OUTCOME_AT_OR_AFTER_WINDOW_END_UNAVAILABLE"] += 1
        else:
            included.append(row)
    return included, dict(excluded)


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    offset = (len(ordered) - 1) * q
    lo, hi = math.floor(offset), math.ceil(offset)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (offset - lo)


def _distribution(
    rows: Sequence[Mapping[str, Any]], nets: Sequence[float], axis: str
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    total_positive = sum(max(0.0, n) for n in nets)
    for row, net in zip(rows, nets):
        if axis == "month":
            label = datetime.fromtimestamp(
                int(row["outcome_available_ts_ms"]) / 1000, timezone.utc
            ).strftime("%Y-%m")
        elif axis == "session":
            hour = datetime.fromtimestamp(
                int(row["entry_ts_ms"]) / 1000, timezone.utc
            ).hour
            label = ("UTC_00_08", "UTC_08_16", "UTC_16_24")[hour // 8]
        else:
            label = str(row["symbol"])
        group = grouped.setdefault(
            label, {"T": 0, "Net_bps": 0.0, "positive_trade_profit_bps": 0.0}
        )
        group["T"] += 1
        group["Net_bps"] += net
        group["positive_trade_profit_bps"] += max(0.0, net)
    for group in grouped.values():
        group["trade_count_share"] = group["T"] / len(rows)
        group["positive_profit_share"] = (
            group["positive_trade_profit_bps"] / total_positive
            if total_positive > 0
            else None
        )
    return {
        "groups": grouped,
        "largest_trade_count_share": max(
            (g["trade_count_share"] for g in grouped.values()), default=None
        ),
        "largest_positive_profit_share": max(
            (
                g["positive_profit_share"]
                for g in grouped.values()
                if g["positive_profit_share"] is not None
            ),
            default=None,
        ),
        "profit_share_denominator": "sum of positive net trades; negative periods are preserved separately",
    }


def summarize(
    rows: Sequence[Mapping[str, Any]],
    start_ms: int,
    end_ms: int,
    cost_multiplier: float = 1,
) -> dict[str, Any]:
    selected, excluded = partition_rows(rows, start_ms, end_ms)
    multiplier = _number(cost_multiplier, "cost_multiplier")
    if multiplier <= 0:
        raise ValueError("POSITIVE_COST_MULTIPLIER_REQUIRED")
    selected.sort(
        key=lambda r: (
            r["outcome_available_ts_ms"],
            r["exit_ts_ms"],
            str(r["symbol"]),
            str(r["identity"]),
            r["signal_ts_ms"],
        )
    )
    gross: list[float] = []
    costs: list[float] = []
    nets: list[float] = []
    holds: list[float] = []
    for row in selected:
        g = _number(row["gross_bps"], "gross_bps")
        c = _number(row["cost_bps"], "cost_bps")
        n = _number(row["net_bps"], "net_bps")
        if c < 0 or not math.isclose(n, g - c, rel_tol=1e-9, abs_tol=1e-7):
            raise ValueError("BASE_COST_NET_RECONCILIATION_FAILED")
        gross.append(g)
        costs.append(c * multiplier)
        nets.append(g - c * multiplier)
        holds.append((int(row["exit_ts_ms"]) - int(row["entry_ts_ms"])) / 60_000)
    positives = [n for n in nets if n > 0]
    losses = sorted(n for n in nets if n < 0)
    positive_sum, loss_sum = sum(positives), -sum(losses)
    pf = positive_sum / loss_sum if loss_sum > 0 else None
    pf_reason = None if loss_sum > 0 else "NO_LOSING_TRADES" if nets else "NO_TRADES"
    streak = max_streak = 0
    cohorts: dict[int, float] = defaultdict(float)
    for row, net in zip(selected, nets):
        cohorts[int(row["outcome_available_ts_ms"])] += net
        streak = streak + 1 if net < 0 else 0
        max_streak = max(max_streak, streak)
    equity = peak = dd = 0.0
    for stamp in sorted(cohorts):
        equity += cohorts[stamp]
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    worst_loss_count = math.ceil(len(losses) * 0.05)
    worst_all_count = math.ceil(len(nets) * 0.05)
    tail = {
        "worst_trade_bps": min(nets) if nets else None,
        "worst_5pct_losing_trades_mean_bps": (
            sum(losses[:worst_loss_count]) / worst_loss_count
            if worst_loss_count
            else None
        ),
        "worst_5pct_losing_trade_count": worst_loss_count,
        "expected_shortfall_5pct_all_trades_bps": (
            sum(sorted(nets)[:worst_all_count]) / worst_all_count
            if worst_all_count
            else None
        ),
        "all_trade_tail_count": worst_all_count,
    }
    return {
        "schema": "zel.scalp7.calendar_metrics.v2",
        "state": "DIAGNOSTIC_ONLY" if nets else "HOLD_NO_COMPLETE_TRADES",
        "start_ms": start_ms,
        "end_ms": end_ms,
        "calendar_days": (end_ms - start_ms) / DAY_MS,
        "partition": "signal>=start, signal<end, outcome_available<end; carry-in and exact-end outcomes excluded",
        "excluded_counts": excluded,
        "T": len(nets),
        "T_per_day": len(nets) / ((end_ms - start_ms) / DAY_MS),
        "WR": len(positives) / len(nets) if nets else None,
        "WR_pct": len(positives) / len(nets) * 100 if nets else None,
        "Gross_bps": sum(gross),
        "Cost_bps": sum(costs),
        "Net_bps": sum(nets),
        "NetExp_bps_T": sum(nets) / len(nets) if nets else None,
        "PF": pf,
        "PF_null_reason": pf_reason,
        "DD_bps": dd,
        "DD_kind": "realized_equal_notional_trade_bps; simultaneous outcome cohorts netted together",
        "mark_to_market_DD_bps": None,
        "mark_to_market_DD_state": "UNBOUND_NO_MARK_CURVE",
        "MaxLossStreak": max_streak,
        "loss_streak_order": "outcome_available,exit,symbol,identity,signal; zero-net ends streak",
        "loss_tail": tail,
        "hold_median_min": _quantile(holds, 0.5),
        "hold_p95_min": _quantile(holds, 0.95),
        "hold_definition": "actual exit timestamp minus entry timestamp in minutes",
        "largest_winner_contribution": (
            max(positives) / positive_sum if positive_sum > 0 else None
        ),
        "largest_winner_denominator": "sum positive cost-adjusted net trade bps",
        "cost_multiplier": multiplier,
        "concentration": {
            axis: _distribution(selected, nets, axis)
            for axis in ("month", "symbol", "session")
        },
        "authority": {"promotion": False, "order": "BLOCKED", "live": "BLOCKED"},
        "risk_limits": {
            "status": "UNBOUND_REQUIRES_SSOT",
            "account_DD_pct": None,
            "leverage": None,
            "exposure_limit": None,
        },
        "metric_limitations": [
            "summed trade bps are not portfolio/account percentage return",
            "no open mark-to-market path is inferred from realized trades",
            "source and cost authority must be bound externally",
        ],
    }


def rolling_summary(
    rows: Sequence[Mapping[str, Any]],
    windows: Sequence[Mapping[str, Any]],
    cost_multiplier: float = 1,
) -> dict[str, Any]:
    results = []
    for window in windows:
        report = summarize(
            rows, int(window["start_ms"]), int(window["end_ms"]), cost_multiplier
        )
        results.append({"label": str(window.get("label", "")), **report})
    observed = [r for r in results if r["T"] > 0]
    positive = sum(r["Net_bps"] > 0 for r in observed)
    return {
        "windows": results,
        "window_count": len(results),
        "nonempty_window_count": len(observed),
        "positive_window_count": positive,
        "rolling_positive_window_ratio": positive / len(results) if results else None,
        "nonempty_positive_window_ratio": (
            positive / len(observed) if observed else None
        ),
        "empty_window_policy": "counts in full preregistered denominator; zero trades is not positive",
        "promotion": False,
    }


def _exposure_vector(
    rows: Sequence[Mapping[str, Any]],
    start_ms: int,
    end_ms: int,
) -> dict[tuple[str, int], float]:
    vector: dict[tuple[str, int], float] = defaultdict(float)
    for row in rows:
        entry = _time(row["entry_ts_ms"], "entry_ts_ms")
        exited = _time(row["exit_ts_ms"], "exit_ts_ms")
        if exited < entry:
            raise ValueError("NEGATIVE_HOLD_TIME")
        first, last = max(entry, start_ms), min(exited, end_ms)
        if last <= first:
            continue
        legs = row.get("legs") or [
            {"symbol": row["symbol"], "side": row["side"], "weight": 1.0}
        ]
        risk = _number(row.get("risk_weight", 1.0), "risk_weight")
        if risk < 0:
            raise ValueError("NEGATIVE_EXPOSURE")
        for leg in legs:
            symbol = str(leg["symbol"])
            side = _number(leg["side"], "side")
            weight = _number(leg.get("weight", 1.0), "leg_weight")
            if symbol not in SYMBOLS or side not in (-1, 1) or weight <= 0:
                raise ValueError("EXPOSURE_LEG_INVALID")
            bucket = first // BUCKET_MS * BUCKET_MS
            while bucket < last:
                overlap = max(0, min(last, bucket + BUCKET_MS) - max(first, bucket))
                vector[(symbol, bucket)] += side * weight * risk * overlap / BUCKET_MS
                bucket += BUCKET_MS
    return dict(vector)


def behavior_cosine(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    """Signed original-notional occupancy of all trades, never a winner-only subset.

    Every six-symbol UTC15m bucket in the calendar exists; sparse zeros are
    algebraically identical to explicit zeros for an uncentered cosine.
    """
    _span(start_ms, end_ms)
    a, b = _exposure_vector(rows_a, start_ms, end_ms), _exposure_vector(
        rows_b, start_ms, end_ms
    )
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    cosine = max(-1.0, min(1.0, dot / (norm_a * norm_b))) if norm_a and norm_b else None
    buckets = math.ceil(end_ms / BUCKET_MS) - math.floor(start_ms / BUCKET_MS)
    return {
        "behavior_cosine": cosine,
        "null_reason": None if cosine is not None else "ZERO_EXPOSURE_NORM",
        "vector": "signed time-weighted original-notional occupancy in fixed six-symbol UTC15m buckets; all outcomes included",
        "exposure_limitation": "original weight retained until final exit; partial fills are not reconstructed",
        "full_vector_dimensions": len(SYMBOLS) * buckets,
        "symbols": list(SYMBOLS),
        "nonzero_a": sum(v != 0 for v in a.values()),
        "nonzero_b": sum(v != 0 for v in b.values()),
        "carry_in_policy": "actual exposure overlapping window included; economics uses separate strict outcome partition",
        "duplicate_by_user_rule": cosine >= 0.85 if cosine is not None else None,
        "fusion_authority": False,
    }
