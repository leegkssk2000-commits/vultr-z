#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

PLAN_PATH = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_short_exchange_bot_benchmark_v2_execution_72")

EXPECTED_BOTS = 6
EXPECTED_LANES = 12
EXPECTED_SEGMENTS = 24
EXPECTED_STRESS_PER_LANE = 6
EXPECTED_CELLS = 72
EXPECTED_FOLDS = 6

BASE_CELL = ("cost_profile_0", "timing_0")
ADVERSE_CELL = ("cost_profile_1", "timing_1")
SEVERE_CELL = ("cost_profile_2", "timing_1")
MINIMUM_LANE_TRADES = 24
MINIMUM_SYMBOL_COUNT = 3
MINIMUM_POSITIVE_FOLDS = 4
MINIMUM_POSITIVE_PRIMARY_CELLS = 3

BOT_PARAMETERS: dict[str, dict[str, Any]] = {
    "dual_ma_trend_bot": {
        "fast_ema": 12, "slow_ema": 26, "atr_period": 14,
        "stop_atr": 1.50, "target_atr": 3.00, "max_hold_bars": 48,
    },
    "dual_donchian_trend_bot": {
        "lookback": 20, "atr_period": 14,
        "stop_atr": 1.50, "target_atr": 3.00, "max_hold_bars": 40,
    },
    "dual_atr_volatility_bot": {
        "atr_period": 14, "range_atr_min": 1.35, "volume_z_min": 0.50,
        "stop_atr": 1.50, "target_atr": 3.50, "max_hold_bars": 30,
    },
    "dual_vwap_mean_reversion_bot": {
        "lookback": 24, "entry_std": 1.50, "atr_period": 14,
        "stop_atr": 1.00, "max_hold_bars": 24,
    },
    "neutral_multi_level_grid_bot": {
        "lookback": 48, "atr_period": 14, "minimum_width_atr": 4.0,
        "maximum_width_atr": 12.0, "maximum_slope_atr": 0.08,
        "stop_atr": 0.75, "max_hold_bars": 24,
    },
    "directional_trend_grid_bot": {
        "ema_period": 50, "atr_period": 14, "minimum_slope_atr": 0.04,
        "stop_atr": 1.75, "target_atr": 1.50, "max_hold_bars": 30,
    },
}


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return count, digest.hexdigest()


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False, min_periods=span).mean()


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()


def rolling_vwap(frame: pd.DataFrame, lookback: int) -> pd.Series:
    volume = frame["volume"].astype(float)
    typical = (
        frame["high"].astype(float)
        + frame["low"].astype(float)
        + frame["close"].astype(float)
    ) / 3.0
    weighted = (typical * volume).rolling(lookback, min_periods=lookback).sum()
    volume_sum = volume.rolling(lookback, min_periods=lookback).sum()
    fallback = typical.rolling(lookback, min_periods=lookback).mean()
    return weighted.div(volume_sum.where(volume_sum > 0)).fillna(fallback)


def edge_trigger(condition: pd.Series) -> pd.Series:
    clean = condition.fillna(False).astype(bool)
    return clean & ~clean.shift(1, fill_value=False)


def next_true_distance(condition: pd.Series, start: int, maximum: int) -> int:
    upper = min(len(condition), start + maximum + 1)
    for index in range(start + 1, upper):
        if bool(condition.iloc[index]):
            return max(2, index - start)
    return maximum


def base_round_trip_cost(plan: dict[str, Any]) -> float:
    model = plan.get("corrected_execution_model", {})
    for profile in model.get("profiles", []):
        if isinstance(profile, dict) and str(profile.get("id")) == "cost_profile_0":
            return finite(profile.get("round_trip_cost_pct"), math.nan)
    return math.nan


def signal_admission(
    side: str,
    entry: float,
    stop: float,
    target: float,
    base_cost_pct: float,
) -> tuple[bool, dict[str, float]]:
    if not all(math.isfinite(value) for value in (entry, stop, target, base_cost_pct)):
        return False, {}
    if entry <= 0 or base_cost_pct <= 0:
        return False, {}
    if side == "long":
        geometry_valid = 0 < stop < entry < target
    elif side == "short":
        geometry_valid = stop > entry > target > 0
    else:
        return False, {}
    if not geometry_valid:
        return False, {}
    risk_pct = abs(entry - stop) / entry * 100.0
    target_move_pct = abs(target - entry) / entry * 100.0
    target_to_cost = target_move_pct / base_cost_pct
    risk_to_cost = risk_pct / base_cost_pct
    return (
        target_to_cost >= 3.0 and risk_to_cost >= 2.0,
        {
            "risk_pct_at_admission": risk_pct,
            "target_move_pct_at_admission": target_move_pct,
            "target_to_base_cost_ratio": target_to_cost,
            "risk_to_base_cost_ratio": risk_to_cost,
        },
    )


def generate_signals(
    bot_id: str,
    frame: pd.DataFrame,
    measurement: pd.Series,
    base_cost_pct: float,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    params = BOT_PARAMETERS[bot_id]
    close = frame["close"].astype(float)
    open_v = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    atr14 = atr(frame, int(params.get("atr_period", 14)))
    signals: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()

    def append(
        index: int,
        side: str,
        stop: float,
        target: float,
        timeout: int,
        reason: str,
        level_id: str | None = None,
    ) -> None:
        if index + 1 >= len(frame):
            rejected["NO_NEXT_BAR"] += 1
            return
        if not bool(measurement.iloc[index]) or not bool(measurement.iloc[index + 1]):
            rejected["OUTSIDE_MEASUREMENT"] += 1
            return
        reference_entry = finite(frame.iloc[index + 1]["open"], math.nan)
        admitted, economics = signal_admission(
            side, reference_entry, finite(stop, math.nan), finite(target, math.nan), base_cost_pct
        )
        if not admitted:
            rejected["ECONOMIC_ADMISSION_REJECT"] += 1
            return
        signals.append(
            {
                "signal_bar_index": int(index),
                "entry_bar_index": int(index + 1),
                "side": side,
                "stop_price": float(stop),
                "target_price": float(target),
                "timeout_bars": int(max(2, timeout)),
                "reason": reason,
                "level_id": level_id,
                **economics,
            }
        )

    if bot_id == "dual_ma_trend_bot":
        fast = ema(close, int(params["fast_ema"]))
        slow = ema(close, int(params["slow_ema"]))
        long_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1)) & (close > slow)
        short_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1)) & (close < slow)
        for index in np.flatnonzero(edge_trigger(long_cross).to_numpy(dtype=bool)):
            i = int(index)
            a = finite(atr14.iloc[i], math.nan)
            append(
                i, "long",
                min(float(low.iloc[i]), float(close.iloc[i]) - float(params["stop_atr"]) * a),
                float(close.iloc[i]) + float(params["target_atr"]) * a,
                next_true_distance(short_cross, i, int(params["max_hold_bars"])),
                "ema_12_26_up_cross",
            )
        for index in np.flatnonzero(edge_trigger(short_cross).to_numpy(dtype=bool)):
            i = int(index)
            a = finite(atr14.iloc[i], math.nan)
            append(
                i, "short",
                max(float(high.iloc[i]), float(close.iloc[i]) + float(params["stop_atr"]) * a),
                float(close.iloc[i]) - float(params["target_atr"]) * a,
                next_true_distance(long_cross, i, int(params["max_hold_bars"])),
                "ema_12_26_down_cross",
            )

    elif bot_id == "dual_donchian_trend_bot":
        lookback = int(params["lookback"])
        prior_high = high.shift(1).rolling(lookback, min_periods=lookback).max()
        prior_low = low.shift(1).rolling(lookback, min_periods=lookback).min()
        midpoint = (prior_high + prior_low) / 2.0
        long_break = close > prior_high
        short_break = close < prior_low
        long_reclaim = close < midpoint
        short_reclaim = close > midpoint
        for index in np.flatnonzero(edge_trigger(long_break).to_numpy(dtype=bool)):
            i = int(index)
            a = finite(atr14.iloc[i], math.nan)
            append(
                i, "long", float(close.iloc[i]) - float(params["stop_atr"]) * a,
                float(close.iloc[i]) + float(params["target_atr"]) * a,
                next_true_distance(long_reclaim, i, int(params["max_hold_bars"])),
                "donchian_20_up_break",
            )
        for index in np.flatnonzero(edge_trigger(short_break).to_numpy(dtype=bool)):
            i = int(index)
            a = finite(atr14.iloc[i], math.nan)
            append(
                i, "short", float(close.iloc[i]) + float(params["stop_atr"]) * a,
                float(close.iloc[i]) - float(params["target_atr"]) * a,
                next_true_distance(short_reclaim, i, int(params["max_hold_bars"])),
                "donchian_20_down_break",
            )

    elif bot_id == "dual_atr_volatility_bot":
        bar_range = high - low
        vol_mean = volume.rolling(20, min_periods=20).mean()
        vol_std = volume.rolling(20, min_periods=20).std(ddof=0).replace(0, np.nan)
        volume_z = (volume - vol_mean).div(vol_std)
        prior_high = high.shift(1).rolling(10, min_periods=10).max()
        prior_low = low.shift(1).rolling(10, min_periods=10).min()
        long_break = (
            (close > open_v)
            & (bar_range >= float(params["range_atr_min"]) * atr14)
            & (volume_z >= float(params["volume_z_min"]))
            & (close >= prior_high)
        )
        short_break = (
            (close < open_v)
            & (bar_range >= float(params["range_atr_min"]) * atr14)
            & (volume_z >= float(params["volume_z_min"]))
            & (close <= prior_low)
        )
        for index in np.flatnonzero(edge_trigger(long_break).to_numpy(dtype=bool)):
            i = int(index)
            a = finite(atr14.iloc[i], math.nan)
            append(
                i, "long",
                min(float(low.iloc[i]), float(close.iloc[i]) - float(params["stop_atr"]) * a),
                float(close.iloc[i]) + float(params["target_atr"]) * a,
                int(params["max_hold_bars"]), "atr_volume_up_break",
            )
        for index in np.flatnonzero(edge_trigger(short_break).to_numpy(dtype=bool)):
            i = int(index)
            a = finite(atr14.iloc[i], math.nan)
            append(
                i, "short",
                max(float(high.iloc[i]), float(close.iloc[i]) + float(params["stop_atr"]) * a),
                float(close.iloc[i]) - float(params["target_atr"]) * a,
                int(params["max_hold_bars"]), "atr_volume_down_break",
            )

    elif bot_id == "dual_vwap_mean_reversion_bot":
        lookback = int(params["lookback"])
        vwap = rolling_vwap(frame, lookback)
        deviation = close - vwap
        std = deviation.rolling(lookback, min_periods=lookback).std(ddof=0)
        upper = vwap + float(params["entry_std"]) * std
        lower = vwap - float(params["entry_std"]) * std
        short_reclaim = (high > upper) & (close < upper) & (close < open_v)
        long_reclaim = (low < lower) & (close > lower) & (close > open_v)
        for index in np.flatnonzero(edge_trigger(long_reclaim).to_numpy(dtype=bool)):
            i = int(index)
            a = finite(atr14.iloc[i], math.nan)
            append(
                i, "long",
                min(float(low.iloc[i]) - 0.10 * a, float(close.iloc[i]) - float(params["stop_atr"]) * a),
                finite(vwap.iloc[i], math.nan),
                int(params["max_hold_bars"]), "vwap_lower_excursion_close_inside",
            )
        for index in np.flatnonzero(edge_trigger(short_reclaim).to_numpy(dtype=bool)):
            i = int(index)
            a = finite(atr14.iloc[i], math.nan)
            append(
                i, "short",
                max(float(high.iloc[i]) + 0.10 * a, float(close.iloc[i]) + float(params["stop_atr"]) * a),
                finite(vwap.iloc[i], math.nan),
                int(params["max_hold_bars"]), "vwap_upper_excursion_close_inside",
            )

    elif bot_id == "neutral_multi_level_grid_bot":
        lookback = int(params["lookback"])
        range_high = high.shift(1).rolling(lookback, min_periods=lookback).max()
        range_low = low.shift(1).rolling(lookback, min_periods=lookback).min()
        width = range_high - range_low
        midpoint = (range_high + range_low) / 2.0
        midpoint_slope = midpoint.diff(10).abs().div(10.0 * atr14)
        stable = (
            width.ge(float(params["minimum_width_atr"]) * atr14)
            & width.le(float(params["maximum_width_atr"]) * atr14)
            & midpoint_slope.le(float(params["maximum_slope_atr"]))
        )
        levels = {
            "L20": range_low + 0.20 * width,
            "L40": range_low + 0.40 * width,
            "L60": range_low + 0.60 * width,
            "L80": range_low + 0.80 * width,
        }
        for entry_name, target_name in (("L20", "L40"), ("L40", "L60")):
            condition = stable & (low <= levels[entry_name]) & (close > levels[entry_name])
            for index in np.flatnonzero(edge_trigger(condition).to_numpy(dtype=bool)):
                i = int(index)
                a = finite(atr14.iloc[i], math.nan)
                append(
                    i, "long",
                    finite(range_low.iloc[i], math.nan) - float(params["stop_atr"]) * a,
                    finite(levels[target_name].iloc[i], math.nan),
                    int(params["max_hold_bars"]),
                    "neutral_grid_long_cycle", f"{entry_name}->{target_name}",
                )
        for entry_name, target_name in (("L80", "L60"), ("L60", "L40")):
            condition = stable & (high >= levels[entry_name]) & (close < levels[entry_name])
            for index in np.flatnonzero(edge_trigger(condition).to_numpy(dtype=bool)):
                i = int(index)
                a = finite(atr14.iloc[i], math.nan)
                append(
                    i, "short",
                    finite(range_high.iloc[i], math.nan) + float(params["stop_atr"]) * a,
                    finite(levels[target_name].iloc[i], math.nan),
                    int(params["max_hold_bars"]),
                    "neutral_grid_short_cycle", f"{entry_name}->{target_name}",
                )

    elif bot_id == "directional_trend_grid_bot":
        trend = ema(close, int(params["ema_period"]))
        slope = trend.diff(10).div(10.0 * atr14)
        up = (close > trend) & slope.ge(float(params["minimum_slope_atr"]))
        down = (close < trend) & slope.le(-float(params["minimum_slope_atr"]))
        for distance in (0.50, 1.00):
            long_level = trend - distance * atr14
            long_reclaim = up & (low <= long_level) & (close > long_level)
            for index in np.flatnonzero(edge_trigger(long_reclaim).to_numpy(dtype=bool)):
                i = int(index)
                a = finite(atr14.iloc[i], math.nan)
                append(
                    i, "long",
                    finite(long_level.iloc[i], math.nan) - float(params["stop_atr"]) * a,
                    finite(trend.iloc[i], math.nan) + float(params["target_atr"]) * a,
                    int(params["max_hold_bars"]),
                    "trend_grid_long_reclaim", f"EMA-{distance:.2f}ATR",
                )
            short_level = trend + distance * atr14
            short_reclaim = down & (high >= short_level) & (close < short_level)
            for index in np.flatnonzero(edge_trigger(short_reclaim).to_numpy(dtype=bool)):
                i = int(index)
                a = finite(atr14.iloc[i], math.nan)
                append(
                    i, "short",
                    finite(short_level.iloc[i], math.nan) + float(params["stop_atr"]) * a,
                    finite(trend.iloc[i], math.nan) - float(params["target_atr"]) * a,
                    int(params["max_hold_bars"]),
                    "trend_grid_short_reclaim", f"EMA+{distance:.2f}ATR",
                )
    else:
        raise ValueError(f"BOT_UNSUPPORTED:{bot_id}")

    signals.sort(
        key=lambda row: (
            int(row["entry_bar_index"]),
            str(row["side"]),
            str(row.get("level_id") or ""),
            str(row["reason"]),
        )
    )
    return signals, rejected


def simulate_trade(
    frame: pd.DataFrame,
    measurement: pd.Series,
    signal: dict[str, Any],
    cost: dict[str, Any],
    timing: dict[str, Any],
    timeframe: str,
) -> dict[str, Any] | None:
    entry_delay = int(timing.get("additional_entry_delay_bars") or 0)
    exit_delay = int(timing.get("additional_exit_delay_bars") or 0)
    entry_index = int(signal["entry_bar_index"]) + entry_delay
    measured_indices = np.flatnonzero(measurement.to_numpy(dtype=bool))
    if measured_indices.size == 0:
        return None
    last_index = int(measured_indices[-1])
    if entry_index >= len(frame) or entry_index > last_index or not bool(measurement.iloc[entry_index]):
        return None

    side = str(signal["side"])
    entry = finite(frame.iloc[entry_index]["open"], math.nan)
    stop = finite(signal["stop_price"], math.nan)
    target = finite(signal["target_price"], math.nan)
    if side == "long":
        valid = 0 < stop < entry < target
    elif side == "short":
        valid = stop > entry > target > 0
    else:
        return None
    if not valid:
        return None

    risk_pct = abs(entry - stop) / entry * 100.0
    if risk_pct <= 0:
        return None

    timeout_index = min(entry_index + int(signal["timeout_bars"]), last_index)
    trigger = "segment_end"
    trigger_index = last_index
    reference_exit = finite(frame.iloc[last_index]["close"], math.nan)
    for index in range(entry_index, last_index + 1):
        high_v = finite(frame.iloc[index]["high"], math.nan)
        low_v = finite(frame.iloc[index]["low"], math.nan)
        if side == "long":
            if low_v <= stop:
                trigger, trigger_index, reference_exit = "stop", index, stop
                break
            if high_v >= target:
                trigger, trigger_index, reference_exit = "take_profit", index, target
                break
        else:
            if high_v >= stop:
                trigger, trigger_index, reference_exit = "stop", index, stop
                break
            if low_v <= target:
                trigger, trigger_index, reference_exit = "take_profit", index, target
                break
        if index >= timeout_index:
            trigger, trigger_index = "rule_exit_or_timeout", index
            reference_exit = finite(frame.iloc[index]["close"], math.nan)
            break

    execution_index = min(trigger_index + exit_delay, last_index)
    if exit_delay == 0 and trigger in {"stop", "take_profit"}:
        exit_price = reference_exit
    elif trigger == "segment_end":
        exit_price = finite(frame.iloc[execution_index]["close"], math.nan)
    else:
        exit_price = finite(frame.iloc[execution_index]["open"], math.nan)

    side_multiplier = 1.0 if side == "long" else -1.0
    gross_pct = side_multiplier * (exit_price - entry) / entry * 100.0
    additional_slippage = finite(timing.get("additional_slippage_bps_per_side"))
    round_trip_pct = 2.0 * (
        finite(cost.get("fee_bps_per_side"))
        + finite(cost.get("slippage_bps_per_side"))
        + additional_slippage
    ) / 100.0
    minutes = {"5m": 5, "15m": 15}[timeframe]
    holding_hours = max(execution_index - entry_index, 0) * minutes / 60.0
    funding_pct = finite(cost.get("funding_bps_per_8h")) / 100.0 * holding_hours / 8.0
    net_pct = gross_pct - round_trip_pct - funding_pct
    return {
        "entry_index": entry_index,
        "exit_index": execution_index,
        "side": side,
        "entry_price": entry,
        "exit_price": exit_price,
        "stop_price": stop,
        "target_price": target,
        "risk_pct": risk_pct,
        "gross_return_pct": gross_pct,
        "round_trip_cost_pct": round_trip_pct,
        "funding_cost_pct": funding_pct,
        "net_return_pct": net_pct,
        "net_r": net_pct / risk_pct,
        "exit_reason": trigger,
        "holding_bars": max(execution_index - entry_index, 0),
    }


def fold_metrics(helper: Any, trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        grouped[int(row["fold"])].append(row)
    rows: dict[str, dict[str, Any]] = {}
    positive = 0
    for fold in range(EXPECTED_FOLDS):
        metrics = helper.aggregate_trades(grouped.get(fold, []))
        rows[str(fold)] = metrics
        if helper.finite_metric(metrics.get("net_pnl_sum_pct")) > 0.0:
            positive += 1
    return {
        "rows": rows,
        "fold_count": EXPECTED_FOLDS,
        "positive_fold_count": positive,
        "positive_fold_ratio": positive / EXPECTED_FOLDS,
    }


def cell_gate(helper: Any, cell: dict[str, Any]) -> dict[str, bool]:
    trade_count = int(cell.get("trade_count") or 0)
    symbol_count = len(cell.get("symbol_histogram") or {})
    folds = cell.get("fold_metrics") or {}
    return {
        "trade_gate": trade_count >= MINIMUM_LANE_TRADES,
        "symbol_gate": symbol_count >= MINIMUM_SYMBOL_COUNT,
        "profit_factor_gate": helper.finite_metric(cell.get("profit_factor")) > 1.0,
        "expectancy_gate": helper.finite_metric(cell.get("expectancy_r")) > 0.0,
        "net_pnl_gate": helper.finite_metric(cell.get("net_pnl_sum_pct")) > 0.0,
        "walk_forward_gate": int(folds.get("positive_fold_count") or 0) >= MINIMUM_POSITIVE_FOLDS,
    }


def cell_pass(helper: Any, cell: dict[str, Any]) -> bool:
    return all(cell_gate(helper, cell).values())


def self_test() -> int:
    size = 420
    x = np.arange(size, dtype=float)
    close = pd.Series(100.0 + 0.015 * x + 1.2 * np.sin(x / 9.0))
    open_v = close.shift(1).fillna(close.iloc[0])
    frame = pd.DataFrame(
        {
            "__timestamp": x,
            "open": open_v,
            "high": pd.concat([close, open_v], axis=1).max(axis=1) + 0.25,
            "low": pd.concat([close, open_v], axis=1).min(axis=1) - 0.25,
            "close": close,
            "volume": 100.0 + (x % 31) * 3.0,
            "symbol": "TESTUSDT",
            "__source_index": x.astype(int),
            "__first_source_index": x.astype(int),
            "__last_source_index": x.astype(int),
            "__complete_bucket": True,
            "timeframe": "5m",
        }
    )
    measurement = pd.Series([True] * size)
    for bot_id in BOT_PARAMETERS:
        signals, rejected = generate_signals(bot_id, frame, measurement, 0.12)
        assert isinstance(signals, list)
        assert isinstance(rejected, Counter)

    long_signal = {
        "entry_bar_index": 101,
        "side": "long",
        "stop_price": float(frame.iloc[101]["open"]) - 1.0,
        "target_price": float(frame.iloc[101]["open"]) + 1.0,
        "timeout_bars": 10,
    }
    short_signal = {
        "entry_bar_index": 101,
        "side": "short",
        "stop_price": float(frame.iloc[101]["open"]) + 1.0,
        "target_price": float(frame.iloc[101]["open"]) - 1.0,
        "timeout_bars": 10,
    }
    cost = {
        "fee_bps_per_side": 1.0,
        "slippage_bps_per_side": 1.0,
        "funding_bps_per_8h": 0.0,
    }
    timing = {
        "additional_entry_delay_bars": 0,
        "additional_exit_delay_bars": 0,
        "additional_slippage_bps_per_side": 0.0,
    }
    assert simulate_trade(frame, measurement, long_signal, cost, timing, "5m") is not None
    assert simulate_trade(frame, measurement, short_signal, cost, timing, "5m") is not None
    admitted, metrics = signal_admission("long", 100.0, 99.7, 100.5, 0.10)
    assert admitted and metrics["target_to_base_cost_ratio"] >= 3.0
    print("STATE=PASS_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--raw-module")
    parser.add_argument("--helper-module")
    parser.add_argument("--a4d-contract")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not all([args.raw_module, args.helper_module, args.a4d_contract]):
        raise SystemExit("--raw-module --helper-module --a4d-contract required")

    root = Path(args.root).resolve()
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_exchange_bot_raw")
    helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_exchange_bot_helper")
    contract = load_json(Path(args.a4d_contract).resolve())
    required = [root / PLAN_PATH, root / MANIFEST_PATH]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    plan = load_json(root / PLAN_PATH)
    manifest = load_json(root / MANIFEST_PATH)
    blockers: list[str] = []

    if plan.get("state") != "PASS_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN":
        blockers.append("ECONOMIC_CALIBRATION_PLAN_NOT_PASS")

    bots = [
        row for row in plan.get("exchange_bot_benchmarks_v2", []) if isinstance(row, dict)
    ]
    if len(bots) != EXPECTED_BOTS:
        blockers.append(f"BOT_COUNT_INVALID:{len(bots)}")
    bot_ids = {str(row.get("bot_id")) for row in bots}
    if bot_ids != set(BOT_PARAMETERS):
        blockers.append("BOT_ID_SET_INVALID")

    lanes = [
        {
            "bot_id": str(row["bot_id"]),
            "family": str(row["family"]),
            "execution_style": str(row.get("execution") or ""),
            "timeframe": str(timeframe),
            "lane_id": f"{row['bot_id']}:{timeframe}",
        }
        for row in bots
        for timeframe in row.get("timeframes", [])
    ]
    if len(lanes) != EXPECTED_LANES:
        blockers.append(f"LANE_COUNT_INVALID:{len(lanes)}")

    segments = {
        str(row["segment_id"]): row
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict)
    }
    if len(segments) != EXPECTED_SEGMENTS:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")

    model = plan.get("corrected_execution_model", {})
    costs = [row for row in model.get("profiles", []) if isinstance(row, dict)]
    timings = [row for row in model.get("timing_perturbations", []) if isinstance(row, dict)]
    if len(costs) * len(timings) != EXPECTED_STRESS_PER_LANE:
        blockers.append("STRESS_CELL_COUNT_INVALID")
    if any(int(row.get("latency_bars") or 0) != 0 for row in costs):
        blockers.append("BAR_LATENCY_NOT_ZERO")
    base_cost_pct = base_round_trip_cost(plan)
    if not math.isfinite(base_cost_pct) or base_cost_pct <= 0:
        blockers.append("BASE_COST_INVALID")

    if blockers:
        print("STATE=HOLD_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    source_sha = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict)
    }
    source_paths = sorted({str(row["source_path"]) for row in segments.values()})
    selected_source_paths = [root / raw.safe_repo_path(path) for path in source_paths]
    canonical_paths = required + selected_source_paths
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = helper.snapshot(canonical_paths + protected)

    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    mask_cache: dict[tuple[str, str], pd.Series] = {}
    signal_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    reject_cache: dict[tuple[str, str], Counter[str]] = {}
    trade_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []

    for lane_number, lane in enumerate(sorted(lanes, key=lambda row: row["lane_id"]), 1):
        bot_id = lane["bot_id"]
        timeframe = lane["timeframe"]
        for segment_id, segment in sorted(segments.items()):
            source_path = str(segment["source_path"])
            if source_path not in source_cache:
                source_cache[source_path] = raw.fixed_ohlcv_frame(
                    root / raw.safe_repo_path(source_path), source_sha[source_path]
                )
            key = (segment_id, timeframe)
            if key not in frame_cache:
                frame_cache[key] = raw.resample_for_segment(
                    source_cache[source_path],
                    int(segment["start_row"]),
                    int(segment["end_row_exclusive"]),
                    timeframe,
                )
                mask_cache[key] = raw.measurement_mask(
                    frame_cache[key],
                    int(segment["start_row"]),
                    int(segment["end_row_exclusive"]),
                )
            signals, rejected = generate_signals(
                bot_id, frame_cache[key], mask_cache[key], base_cost_pct
            )
            signal_cache[(lane["lane_id"], segment_id)] = signals
            reject_cache[(lane["lane_id"], segment_id)] = rejected

        for cost in costs:
            for timing in timings:
                cell_trades: list[dict[str, Any]] = []
                for segment_id, segment in sorted(segments.items()):
                    frame = frame_cache[(segment_id, timeframe)]
                    measurement = mask_cache[(segment_id, timeframe)]
                    last_exit = -1
                    for signal in signal_cache[(lane["lane_id"], segment_id)]:
                        if int(signal["entry_bar_index"]) <= last_exit:
                            continue
                        trade = simulate_trade(
                            frame, measurement, signal, cost, timing, timeframe
                        )
                        if trade is None:
                            continue
                        last_exit = int(trade["exit_index"])
                        trade.update(
                            {
                                "lane_id": lane["lane_id"],
                                "bot_id": bot_id,
                                "family": lane["family"],
                                "execution_style": lane["execution_style"],
                                "timeframe": timeframe,
                                "cost_profile_id": str(cost["id"]),
                                "timing_id": str(timing["id"]),
                                "segment_id": segment_id,
                                "fold": int(segment["fold"]),
                                "regime": str(segment["regime"]),
                                "symbol": str(
                                    frame.iloc[int(signal["signal_bar_index"])].get("symbol")
                                    or ""
                                ),
                                "signal_bar_index": int(signal["signal_bar_index"]),
                                "signal_reason": str(signal["reason"]),
                                "level_id": signal.get("level_id"),
                                "target_to_base_cost_ratio": signal[
                                    "target_to_base_cost_ratio"
                                ],
                                "risk_to_base_cost_ratio": signal[
                                    "risk_to_base_cost_ratio"
                                ],
                            }
                        )
                        trade_rows.append(trade)
                        cell_trades.append(trade)

                metrics = helper.aggregate_trades(cell_trades)
                direction_histogram = dict(
                    sorted(Counter(str(row["side"]) for row in cell_trades).items())
                )
                cell = {
                    "lane_id": lane["lane_id"],
                    "bot_id": bot_id,
                    "family": lane["family"],
                    "execution_style": lane["execution_style"],
                    "timeframe": timeframe,
                    "cost_profile_id": str(cost["id"]),
                    "timing_id": str(timing["id"]),
                    **metrics,
                    "direction_histogram": direction_histogram,
                    "fold_metrics": fold_metrics(helper, cell_trades),
                }
                cell["gate_status"] = cell_gate(helper, cell)
                cell["economic_pass"] = all(cell["gate_status"].values())
                cell_rows.append(cell)

        print(
            f"A4D2_EXCHANGE_BOT_V2_PROGRESS={lane_number}/{EXPECTED_LANES} "
            f"CELLS={len(cell_rows)}/{EXPECTED_CELLS} TRADES={len(trade_rows)}"
        )

    if len(cell_rows) != EXPECTED_CELLS:
        blockers.append(f"CELL_COUNT_INVALID:{len(cell_rows)}")

    lane_rows: list[dict[str, Any]] = []
    for lane in sorted(lanes, key=lambda row: row["lane_id"]):
        cells = [row for row in cell_rows if row["lane_id"] == lane["lane_id"]]
        by_key = {
            (str(row["cost_profile_id"]), str(row["timing_id"])): row for row in cells
        }
        missing_keys = [key for key in (BASE_CELL, ADVERSE_CELL, SEVERE_CELL) if key not in by_key]
        if missing_keys:
            blockers.append(f"LANE_REQUIRED_CELL_MISSING:{lane['lane_id']}:{missing_keys}")
            continue
        base = by_key[BASE_CELL]
        adverse = by_key[ADVERSE_CELL]
        severe = by_key[SEVERE_CELL]
        primary_cells = [
            row
            for row in cells
            if str(row["cost_profile_id"]) in {"cost_profile_0", "cost_profile_1"}
        ]
        positive_primary = sum(1 for row in primary_cells if bool(row["economic_pass"]))
        rejected = Counter()
        signal_count = 0
        for segment_id in segments:
            signal_count += len(signal_cache[(lane["lane_id"], segment_id)])
            rejected.update(reject_cache[(lane["lane_id"], segment_id)])
        lane_pass = (
            bool(base["economic_pass"])
            and bool(adverse["economic_pass"])
            and positive_primary >= MINIMUM_POSITIVE_PRIMARY_CELLS
        )
        lane_rows.append(
            {
                **lane,
                "signal_count_after_admission": signal_count,
                "rejection_histogram": dict(sorted(rejected.items())),
                "base_metrics": base,
                "adverse_metrics": adverse,
                "severe_tail_metrics": severe,
                "positive_primary_cell_count": positive_primary,
                "required_positive_primary_cell_count": MINIMUM_POSITIVE_PRIMARY_CELLS,
                "base_and_adverse_positive": bool(base["economic_pass"])
                and bool(adverse["economic_pass"]),
                "severe_tail_positive": bool(severe["economic_pass"]),
                "benchmark_v2_economic_pass": lane_pass,
            }
        )

    family_best_rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in lane_rows:
        grouped[str(row["family"])].append(row)
    for family, rows in sorted(grouped.items()):
        rows.sort(
            key=lambda row: (
                int(row["benchmark_v2_economic_pass"]),
                helper.finite_metric(row["adverse_metrics"].get("expectancy_r")),
                helper.finite_metric(row["base_metrics"].get("expectancy_r")),
                helper.finite_metric(row["adverse_metrics"].get("profit_factor")),
                helper.finite_metric(row["adverse_metrics"].get("net_pnl_sum_pct")),
                -helper.finite_metric(
                    row["adverse_metrics"].get("max_drawdown_pct"), 1e100
                ),
            ),
            reverse=True,
        )
        family_best_rows.append(
            {
                "family": family,
                "selected_lane_id": rows[0]["lane_id"],
                "selected_benchmark_v2_economic_pass": rows[0][
                    "benchmark_v2_economic_pass"
                ],
                "base_metrics": rows[0]["base_metrics"],
                "adverse_metrics": rows[0]["adverse_metrics"],
                "severe_tail_metrics": rows[0]["severe_tail_metrics"],
            }
        )

    after = helper.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    mutation_rows = [
        {"path": path, "classification": helper.classify_mutation(path, root)}
        for path in mutation_paths
    ]
    critical_mutations = [
        row
        for row in mutation_rows
        if row["classification"] != "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"
    ]
    if critical_mutations:
        blockers.append(f"CRITICAL_MUTATIONS:{len(critical_mutations)}")

    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(
        output / "exchange_bot_v2_trade_results_v1.jsonl", trade_rows
    )
    cell_count, cell_sha = atomic_jsonl(
        output / "exchange_bot_v2_cell_results_v1.jsonl", cell_rows
    )
    pass_lanes = [row for row in lane_rows if row["benchmark_v2_economic_pass"]]
    state = (
        "PASS_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72"
        if not blockers
        else "HOLD_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72"
    )
    next_stage = (
        "R7.A4D2_SHORT_FACTOR_ENGINE_REBUILD_AGAINST_EXCHANGE_BOT_V2"
        if not blockers and pass_lanes
        else (
            "R7.A4D2_SHORT_EXCHANGE_BOT_V2_CAUSAL_DIAGNOSE_AND_SAMPLE_EXPANSION"
            if not blockers
            else "R7.A4D2_SHORT_EXCHANGE_BOT_V2_EXECUTION_DIAGNOSE"
        )
    )

    summary = {
        "schema": "r7a4d2_short_exchange_bot_benchmark_v2_execution_72_v1",
        "official_stage": "R7.A4D2_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "bot_count": EXPECTED_BOTS,
        "lane_count": len(lanes),
        "selected_segment_count": len(segments),
        "stress_cell_per_lane": EXPECTED_STRESS_PER_LANE,
        "cell_result_count": cell_count,
        "trade_result_count": trade_count,
        "cell_results_sha256": cell_sha,
        "trade_results_sha256": trade_sha,
        "base_cell": list(BASE_CELL),
        "adverse_cell": list(ADVERSE_CELL),
        "severe_tail_cell": list(SEVERE_CELL),
        "minimum_lane_trades": MINIMUM_LANE_TRADES,
        "minimum_symbol_count": MINIMUM_SYMBOL_COUNT,
        "minimum_positive_folds": MINIMUM_POSITIVE_FOLDS,
        "minimum_positive_primary_cells": MINIMUM_POSITIVE_PRIMARY_CELLS,
        "benchmark_v2_economic_pass_lane_count": len(pass_lanes),
        "benchmark_v2_economic_pass_lane_ids": [
            row["lane_id"] for row in pass_lanes
        ],
        "lane_rows": lane_rows,
        "family_best_rows": family_best_rows,
        "negative_benchmark_relative_promotion_allowed": False,
        "severe_profile_primary_selection_allowed": False,
        "parameter_optimization_allowed": False,
        "bar_latency_as_exchange_latency_allowed": False,
        "next_bar_fill_required": True,
        "strategy_mutation_allowed": False,
        "market_source_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "mutation_rows": mutation_rows,
        "next_stage": next_stage,
    }
    atomic_json(output / "exchange_bot_v2_summary_v1.json", summary)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("EXCHANGE_BOT_V2_COUNT=" + str(EXPECTED_BOTS))
    print("EXCHANGE_BOT_V2_LANE_COUNT=" + str(len(lanes)))
    print("SELECTED_SEGMENT_COUNT=" + str(len(segments)))
    print("EXCHANGE_BOT_V2_CELL_RESULT_COUNT=" + str(cell_count))
    print("EXCHANGE_BOT_V2_TRADE_RESULT_COUNT=" + str(trade_count))
    print("ECONOMIC_PASS_LANE_COUNT=" + str(len(pass_lanes)))
    print(
        "ECONOMIC_PASS_LANE_IDS="
        + json.dumps([row["lane_id"] for row in pass_lanes])
    )
    print("LANE_ROWS=" + json.dumps(lane_rows, ensure_ascii=False, sort_keys=True))
    print(
        "FAMILY_BEST_ROWS="
        + json.dumps(family_best_rows, ensure_ascii=False, sort_keys=True)
    )
    print("MUTATION_ROWS=" + json.dumps(mutation_rows, ensure_ascii=False, sort_keys=True))
    print("SUMMARY_JSON=" + str(output / "exchange_bot_v2_summary_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
