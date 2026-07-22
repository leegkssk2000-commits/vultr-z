#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

EXECUTION_PLAN_PATH = Path(
    "runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json"
)
ADAPTER_EVIDENCE_PATH = Path(
    "runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json"
)
OUTPUT_DIR = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution")
EXPECTED_LAYOUT = [6, 0, 1, 2, 3, 4]
EXPECTED_LANES = 36
EXPECTED_SEGMENTS = 24
EXPECTED_SCANS = 864
WARMUP_TARGET_BARS = 128
MINIMUM_STRATEGY_CALL_BARS = 32
SHORT_ACTIONS = {"enter", "add"}


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


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixed_ohlcv_frame(path: Path, expected_sha: str) -> pd.DataFrame:
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha:
        raise ValueError(f"SOURCE_SHA_MISMATCH:{path}:{actual_sha}:{expected_sha}")
    payload = load_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) < 640:
        raise ValueError(f"SOURCE_ROWS_INVALID:{path}:{len(rows) if isinstance(rows, list) else -1}")
    if any(not isinstance(row, list) or len(row) != 6 for row in rows):
        raise ValueError(f"SOURCE_LAYOUT_INVALID:{path}")
    matrix = np.asarray(rows, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != 6 or not np.isfinite(matrix).all():
        raise ValueError(f"SOURCE_NUMERIC_INVALID:{path}")
    timestamp = matrix[:, 0]
    if np.mean(np.diff(timestamp) > 0) < 0.999:
        raise ValueError(f"SOURCE_TIMESTAMP_NOT_STRICT:{path}")
    open_v, high_v, low_v, close_v, volume_v = (
        matrix[:, 1], matrix[:, 2], matrix[:, 3], matrix[:, 4], matrix[:, 5]
    )
    geometry = (
        (open_v > 0)
        & (high_v >= np.maximum(open_v, close_v))
        & (low_v <= np.minimum(open_v, close_v))
        & (high_v >= low_v)
        & (volume_v >= 0)
    )
    if float(np.mean(geometry)) < 0.999:
        raise ValueError(f"SOURCE_GEOMETRY_INVALID:{path}:{float(np.mean(geometry))}")
    declared = payload.get("row_count")
    if declared is not None and int(declared) != len(rows):
        raise ValueError(f"SOURCE_ROW_COUNT_MISMATCH:{path}:{declared}:{len(rows)}")
    symbol = str(payload.get("symbol") or path.stem.split("_")[1] if "_" in path.stem else path.stem)
    frame = pd.DataFrame({
        "__timestamp": timestamp,
        "open": open_v,
        "high": high_v,
        "low": low_v,
        "close": close_v,
        "volume": volume_v,
        "symbol": symbol,
        "timeframe": str(payload.get("interval") or "1m"),
        "__source_index": np.arange(len(rows), dtype=int),
    })
    return frame


def timeframe_factor(timeframe: str) -> int:
    mapping = {"1m": 1, "5m": 5, "15m": 15}
    if timeframe not in mapping:
        raise ValueError(f"TIMEFRAME_UNSUPPORTED:{timeframe}")
    return mapping[timeframe]


def resample_for_segment(
    source: pd.DataFrame,
    start_row: int,
    end_row_exclusive: int,
    timeframe: str,
) -> pd.DataFrame:
    factor = timeframe_factor(timeframe)
    if not (0 <= start_row < end_row_exclusive <= len(source)):
        raise ValueError(f"SEGMENT_RANGE_INVALID:{start_row}:{end_row_exclusive}:{len(source)}")
    warmup_source_bars = WARMUP_TARGET_BARS * factor + factor
    load_start = max(0, start_row - warmup_source_bars)
    sample = source.iloc[load_start:end_row_exclusive].copy().reset_index(drop=True)
    if factor == 1:
        result = sample.copy()
        result["__first_source_index"] = result["__source_index"].astype(int)
        result["__last_source_index"] = result["__source_index"].astype(int)
        result["__complete_bucket"] = True
        result["timeframe"] = timeframe
        return result.reset_index(drop=True)

    timestamps = sample["__timestamp"].astype(float).to_numpy()
    diffs = np.diff(timestamps)
    positive = diffs[diffs > 0]
    if positive.size == 0:
        raise ValueError("RESAMPLE_TIMESTAMP_STEP_MISSING")
    base_step = float(np.median(positive))
    bucket_width = base_step * factor
    bucket = np.floor(timestamps / bucket_width).astype(np.int64)
    sample["__bucket"] = bucket
    grouped = sample.groupby("__bucket", sort=True, observed=True)
    result = grouped.agg({
        "__timestamp": "first",
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "symbol": "last",
        "__source_index": ["first", "last", "count"],
    })
    result.columns = [
        "__timestamp", "open", "high", "low", "close", "volume", "symbol",
        "__first_source_index", "__last_source_index", "__bucket_count",
    ]
    result = result.reset_index(drop=True)
    result["__complete_bucket"] = result["__bucket_count"].astype(int) == factor
    result["timeframe"] = timeframe
    geometry = (
        (result["open"] > 0)
        & (result["high"] >= result[["open", "close"]].max(axis=1))
        & (result["low"] <= result[["open", "close"]].min(axis=1))
        & (result["high"] >= result["low"])
    )
    if not bool(geometry.all()):
        raise ValueError("RESAMPLED_GEOMETRY_INVALID")
    return result


def measurement_mask(frame: pd.DataFrame, start_row: int, end_row_exclusive: int) -> pd.Series:
    return (
        frame["__complete_bucket"].astype(bool)
        & (frame["__first_source_index"].astype(int) >= start_row)
        & (frame["__last_source_index"].astype(int) < end_row_exclusive)
    )


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rolling_vwap(frame: pd.DataFrame, lookback: int) -> pd.Series:
    volume = frame["volume"].astype(float)
    price = frame["close"].astype(float)
    weighted = (price * volume).rolling(lookback, min_periods=lookback).sum()
    volume_sum = volume.rolling(lookback, min_periods=lookback).sum()
    mean = price.rolling(lookback, min_periods=lookback).mean()
    return weighted.div(volume_sum.where(volume_sum > 0)).fillna(mean)


def edge_trigger(condition: pd.Series) -> pd.Series:
    clean = condition.fillna(False).astype(bool)
    return clean & ~clean.shift(1, fill_value=False)


def parameter_id(parameters: dict[str, Any]) -> str:
    encoded = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def benchmark_signals(lane: dict[str, Any], frame: pd.DataFrame) -> list[dict[str, Any]]:
    family = str(lane["family"])
    grid = lane.get("parameter_grid") if isinstance(lane.get("parameter_grid"), dict) else {}
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    signals: list[dict[str, Any]] = []

    def append_series(condition: pd.Series, parameters: dict[str, Any], reason: str) -> None:
        triggered = edge_trigger(condition)
        for index in np.flatnonzero(triggered.to_numpy(dtype=bool)):
            signals.append({
                "bar_index": int(index),
                "semantic_source": "simple_benchmark",
                "reason": reason,
                "parameters": parameters,
                "parameter_id": parameter_id(parameters),
                "declared_sl": None,
                "declared_tp": None,
                "intent": "benchmark_enter_short",
            })

    if family == "trend":
        for pair, slope_bars in itertools.product(
            grid.get("ema_pairs", []), grid.get("slow_slope_lookback_bars", [])
        ):
            fast_span, slow_span = int(pair[0]), int(pair[1])
            slow = ema(close, slow_span)
            fast = ema(close, fast_span)
            condition = (close < slow) & (fast < slow) & (slow.diff(int(slope_bars)) < 0)
            parameters = {"fast_ema": fast_span, "slow_ema": slow_span, "slope_bars": int(slope_bars)}
            append_series(condition, parameters, "ema_trend_short")
    elif family == "mean_reversion":
        for lookback, threshold, stall in itertools.product(
            grid.get("fair_value_lookback_bars", []),
            grid.get("entry_zscore", []),
            grid.get("momentum_stall_bars", []),
        ):
            lookback_i = int(lookback)
            fair = rolling_vwap(frame, lookback_i)
            deviation = close - fair
            std = deviation.rolling(lookback_i, min_periods=lookback_i).std(ddof=0)
            zscore = deviation.div(std.where(std > 0))
            momentum_stall = close.diff().rolling(int(stall), min_periods=int(stall)).mean() <= 0
            condition = (zscore >= float(threshold)) & momentum_stall
            parameters = {"lookback": lookback_i, "zscore": float(threshold), "stall_bars": int(stall)}
            append_series(condition, parameters, "vwap_zscore_revert_short")
    elif family == "scalp":
        base_round_trip_friction_pct = 0.12
        for pair, horizon, multiple in itertools.product(
            grid.get("ema_pairs", []),
            grid.get("impulse_horizon_bars", []),
            grid.get("minimum_excursion_to_friction_multiple", []),
        ):
            fast_span, slow_span = int(pair[0]), int(pair[1])
            fast = ema(close, fast_span)
            slow = ema(close, slow_span)
            downside_excursion_pct = (1.0 - close.div(close.shift(int(horizon)))) * 100.0
            condition = (
                (fast < slow)
                & (downside_excursion_pct >= base_round_trip_friction_pct * float(multiple))
            )
            parameters = {
                "fast_ema": fast_span,
                "slow_ema": slow_span,
                "horizon_bars": int(horizon),
                "friction_multiple": float(multiple),
            }
            append_series(condition, parameters, "fast_ema_impulse_short")
    elif family == "grid_range":
        for lookback, levels in itertools.product(
            grid.get("range_lookback_bars", []), grid.get("equal_spacing_level_count", [])
        ):
            lookback_i, levels_i = int(lookback), int(levels)
            upper = high.rolling(lookback_i, min_periods=lookback_i).max().shift(1)
            lower = low.rolling(lookback_i, min_periods=lookback_i).min().shift(1)
            spacing = (upper - lower) / max(levels_i, 1)
            condition = (close >= upper - spacing) & (upper > lower)
            parameters = {"lookback": lookback_i, "levels": levels_i}
            append_series(condition, parameters, "equal_spacing_range_grid_short")
    elif family == "event_reversal":
        upside_bar = (high.div(frame["open"].astype(float)) - 1.0) * 100.0
        for lookback, quantile, confirmation in itertools.product(
            grid.get("event_lookback_bars", []),
            grid.get("event_quantile", []),
            grid.get("failed_continuation_confirmation_bars", []),
        ):
            lookback_i, confirmation_i = int(lookback), int(confirmation)
            threshold = upside_bar.rolling(lookback_i, min_periods=lookback_i).quantile(float(quantile)).shift(confirmation_i)
            prior_event = upside_bar.shift(confirmation_i) >= threshold
            prior_high = high.shift(confirmation_i)
            prior_close = close.shift(confirmation_i)
            failed = (high <= prior_high) & (close < prior_close)
            if confirmation_i > 1:
                failed = failed & (high.rolling(confirmation_i).max() <= prior_high)
            condition = prior_event & failed
            parameters = {
                "lookback": lookback_i,
                "event_quantile": float(quantile),
                "confirmation_bars": confirmation_i,
            }
            append_series(condition, parameters, "extreme_bar_fade_short")
    else:
        raise ValueError(f"BENCHMARK_FAMILY_UNSUPPORTED:{family}")
    return signals


def strategy_signals(
    lane: dict[str, Any],
    frame: pd.DataFrame,
    regime: str,
    owner: type[Any],
    method_name: str,
    runner: Any,
    base_cost: dict[str, Any],
    side_effect_attempts: list[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    instance = owner()
    public_columns = [
        column for column in frame.columns
        if not str(column).startswith("__") and column != "__bucket_count"
    ]
    records = frame[public_columns].to_dict(orient="records")
    position = {"side": "", "qty": 0.0, "avg_entry": 0.0, "add_count": 0, "last_add_price": 0.0}
    signals: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    with runner.side_effect_guard(side_effect_attempts):
        for index in range(MINIMUM_STRATEGY_CALL_BARS - 1, len(frame) - 1):
            context = runner.build_context(
                str(lane["strategy_id"]), records[: index + 1], position, regime, base_cost
            )
            decision = getattr(instance, method_name)(context)
            fields = runner.decision_fields(decision)
            legacy = runner.legacy_signal(fields)
            intent = str(fields.get("intent") or "")
            side = str(legacy.get("side") or "").lower()
            action = str(legacy.get("action") or "").lower()
            if side == "short" and action in SHORT_ACTIONS:
                counts["legacy_short_signal"] += 1
                semantic_ok = bool(fields.get("ok")) and intent == "hold"
                if semantic_ok:
                    counts["legacy_short_hold"] += 1
                else:
                    counts["semantic_mismatch"] += 1
                signals.append({
                    "bar_index": index,
                    "semantic_source": "legacy_short_hold" if semantic_ok else "legacy_short_mismatch",
                    "reason": str(legacy.get("why") or fields.get("reason") or ""),
                    "parameters": {},
                    "parameter_id": "canonical",
                    "declared_sl": finite_or_none(legacy.get("sl")),
                    "declared_tp": finite_or_none(legacy.get("tp")),
                    "intent": intent,
                    "semantic_eligible": semantic_ok,
                })
            elif intent == "enter_short" and bool(fields.get("ok")):
                counts["direct_short_intent"] += 1
                signals.append({
                    "bar_index": index,
                    "semantic_source": "direct_short_intent",
                    "reason": str(fields.get("reason") or ""),
                    "parameters": {},
                    "parameter_id": "canonical",
                    "declared_sl": finite_or_none(legacy.get("sl")),
                    "declared_tp": finite_or_none(legacy.get("tp")),
                    "intent": intent,
                    "semantic_eligible": True,
                })
    return signals, dict(counts)


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def latest_swing_high(frame: pd.DataFrame, signal_index: int, lookback: int) -> float | None:
    start = max(1, signal_index - lookback)
    highs = frame["high"].astype(float)
    candidates: list[float] = []
    for index in range(start, signal_index):
        if index + 1 >= len(frame):
            break
        value = float(highs.iloc[index])
        if value > float(highs.iloc[index - 1]) and value >= float(highs.iloc[index + 1]):
            candidates.append(value)
    if candidates:
        return candidates[-1]
    window = highs.iloc[max(0, signal_index - lookback + 1): signal_index + 1]
    return float(window.max()) if not window.empty else None


def structural_stop_candidates(
    family: str,
    frame: pd.DataFrame,
    signal_index: int,
    entry_price: float,
    declared_sl: float | None,
) -> list[tuple[str, float]]:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    candidates: list[tuple[str, float]] = []
    if declared_sl is not None and declared_sl > entry_price:
        candidates.append(("strategy_declared_sl", declared_sl))
    signal_high = float(high.iloc[signal_index])
    if family == "trend":
        swing = latest_swing_high(frame, signal_index, 32)
        if swing is not None:
            candidates.append(("latest_confirmed_swing_high", swing))
        atr = true_range(frame).rolling(14, min_periods=14).mean().iloc[signal_index]
        if math.isfinite(float(atr)):
            candidates.append(("atr_envelope_high", entry_price + 1.5 * float(atr)))
    elif family == "mean_reversion":
        candidates.append(("signal_bar_high", signal_high))
        recent = high.iloc[max(0, signal_index - 31): signal_index + 1]
        candidates.append(("recent_excursion_high", float(recent.max())))
    elif family == "scalp":
        candidates.append(("signal_bar_high", signal_high))
        swing = latest_swing_high(frame, signal_index, 12)
        if swing is not None:
            candidates.append(("micro_swing_high", swing))
    elif family == "grid_range":
        window_high = high.iloc[max(0, signal_index - 63): signal_index + 1]
        window_low = low.iloc[max(0, signal_index - 63): signal_index + 1]
        upper = float(window_high.max())
        lower = float(window_low.min())
        spacing = max((upper - lower) / 4.0, 0.0)
        candidates.append(("range_upper_boundary", upper))
        candidates.append(("inventory_risk_boundary", upper + spacing))
    elif family == "event_reversal":
        recent = high.iloc[max(0, signal_index - 15): signal_index + 1]
        event_high = float(recent.max())
        candidates.append(("event_extreme_high", event_high))
        candidates.append(("post_event_failed_continuation_high", max(event_high, signal_high)))
    else:
        raise ValueError(f"GEOMETRY_FAMILY_UNSUPPORTED:{family}")
    unique: dict[tuple[str, float], None] = {}
    for name, value in candidates:
        if math.isfinite(value) and value > entry_price:
            unique[(name, round(value, 12))] = None
    return [(name, value) for name, value in unique]


def friction_profiles(cost_profiles: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for profile in cost_profiles:
        profile_id = str(profile["id"])
        per_side_bps = float(profile["fee_bps_per_side"]) + float(profile["slippage_bps_per_side"])
        result[profile_id] = 2.0 * per_side_bps / 100.0
    return result


def geometry_rows_for_signal(
    lane: dict[str, Any],
    segment: dict[str, Any],
    frame: pd.DataFrame,
    signal: dict[str, Any],
    measurement: pd.Series,
    costs_pct: dict[str, float],
) -> list[dict[str, Any]]:
    signal_index = int(signal["bar_index"])
    entry_index = signal_index + 1
    if entry_index >= len(frame) or not bool(measurement.iloc[signal_index]) or not bool(measurement.iloc[entry_index]):
        return []
    measurement_indices = np.flatnonzero(measurement.to_numpy(dtype=bool))
    future_indices = measurement_indices[measurement_indices >= entry_index]
    if future_indices.size == 0:
        return []
    end_index = int(future_indices[-1])
    future = frame.iloc[entry_index: end_index + 1]
    if future.empty:
        return []
    entry_price = float(frame.iloc[entry_index]["open"])
    if entry_price <= 0:
        return []
    lows = future["low"].astype(float).to_numpy()
    highs = future["high"].astype(float).to_numpy()
    min_position = int(np.argmin(lows))
    max_position = int(np.argmax(highs))
    mfe_pct = max((entry_price - float(lows[min_position])) / entry_price * 100.0, 0.0)
    mae_pct = max((float(highs[max_position]) - entry_price) / entry_price * 100.0, 0.0)
    time_to_mfe_bars = min_position
    time_to_mae_bars = max_position
    declared_tp = finite_or_none(signal.get("declared_tp"))
    declared_tp_distance_pct = (
        (entry_price - declared_tp) / entry_price * 100.0
        if declared_tp is not None and 0 < declared_tp < entry_price
        else None
    )
    rows: list[dict[str, Any]] = []
    candidates = structural_stop_candidates(
        str(lane["family"]), frame, signal_index, entry_price, finite_or_none(signal.get("declared_sl"))
    )
    for stop_name, stop_price in candidates:
        stop_distance_pct = (stop_price - entry_price) / entry_price * 100.0
        if stop_distance_pct <= 0:
            continue
        friction_r = {key: value / stop_distance_pct for key, value in costs_pct.items()}
        net_available_r = {key: (mfe_pct - value) / stop_distance_pct for key, value in costs_pct.items()}
        rows.append({
            "lane_id": lane["lane_id"],
            "lane_type": lane["lane_type"],
            "family": lane["family"],
            "strategy_id": lane.get("strategy_id"),
            "benchmark_id": lane.get("benchmark_id"),
            "timeframe": lane["timeframe"],
            "segment_id": segment["segment_id"],
            "regime": segment["regime"],
            "fold": int(segment["fold"]),
            "symbol": str(frame.iloc[signal_index].get("symbol") or ""),
            "signal_timestamp": float(frame.iloc[signal_index]["__timestamp"]),
            "entry_timestamp": float(frame.iloc[entry_index]["__timestamp"]),
            "signal_bar_index": signal_index,
            "entry_bar_index": entry_index,
            "semantic_source": signal.get("semantic_source"),
            "semantic_eligible": bool(signal.get("semantic_eligible", True)),
            "intent": signal.get("intent"),
            "reason": signal.get("reason"),
            "parameter_id": signal.get("parameter_id"),
            "parameters": signal.get("parameters"),
            "entry_price": entry_price,
            "structural_stop_name": stop_name,
            "structural_stop_price": stop_price,
            "structural_stop_distance_pct": stop_distance_pct,
            "declared_tp": declared_tp,
            "declared_tp_distance_pct": declared_tp_distance_pct,
            "full_forward_mfe_pct": mfe_pct,
            "full_forward_mae_pct": mae_pct,
            "time_to_mfe_bars": time_to_mfe_bars,
            "time_to_mae_bars": time_to_mae_bars,
            "available_gross_payoff_ratio": mfe_pct / stop_distance_pct,
            "round_trip_friction_pct_by_cost_profile": costs_pct,
            "friction_r_by_cost_profile": friction_r,
            "net_available_r_after_friction_by_cost_profile": net_available_r,
            "funding_excluded_from_raw_geometry": True,
            "future_selection_allowed": False,
        })
    return rows


def numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    result: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            result.append(float(value))
    return result


def summarize_group(scan_rows: list[dict[str, Any]], geometry_rows: list[dict[str, Any]]) -> dict[str, Any]:
    stops = numeric_values(geometry_rows, "structural_stop_distance_pct")
    mfe = numeric_values(geometry_rows, "full_forward_mfe_pct")
    mae = numeric_values(geometry_rows, "full_forward_mae_pct")
    severe_frictions = [
        float(row.get("friction_r_by_cost_profile", {}).get("cost_profile_2"))
        for row in geometry_rows
        if isinstance(row.get("friction_r_by_cost_profile"), dict)
        and isinstance(row["friction_r_by_cost_profile"].get("cost_profile_2"), (int, float))
    ]
    severe_net = [
        float(row.get("net_available_r_after_friction_by_cost_profile", {}).get("cost_profile_2"))
        for row in geometry_rows
        if isinstance(row.get("net_available_r_after_friction_by_cost_profile"), dict)
        and isinstance(row["net_available_r_after_friction_by_cost_profile"].get("cost_profile_2"), (int, float))
    ]
    return {
        "scan_count": len(scan_rows),
        "completed_scan_count": sum(1 for row in scan_rows if row.get("completed") is True),
        "failed_scan_count": sum(1 for row in scan_rows if row.get("completed") is not True),
        "raw_signal_count": sum(int(row.get("raw_signal_count") or 0) for row in scan_rows),
        "measurement_signal_count": sum(int(row.get("measurement_signal_count") or 0) for row in scan_rows),
        "semantic_eligible_signal_count": sum(int(row.get("semantic_eligible_signal_count") or 0) for row in scan_rows),
        "semantic_mismatch_count": sum(int(row.get("semantic_mismatch_count") or 0) for row in scan_rows),
        "geometry_row_count": len(geometry_rows),
        "median_structural_stop_distance_pct": statistics.median(stops) if stops else None,
        "median_full_forward_mfe_pct": statistics.median(mfe) if mfe else None,
        "median_full_forward_mae_pct": statistics.median(mae) if mae else None,
        "median_severe_friction_r": statistics.median(severe_frictions) if severe_frictions else None,
        "severe_net_available_r_positive_rate_pct": (
            sum(1 for value in severe_net if value > 0) / len(severe_net) * 100.0 if severe_net else 0.0
        ),
        "symbol_histogram": dict(sorted(Counter(str(row.get("symbol") or "") for row in geometry_rows).items())),
        "regime_histogram": dict(sorted(Counter(str(row.get("regime") or "") for row in geometry_rows).items())),
    }


def aggregate_results(scans: list[dict[str, Any]], geometry: list[dict[str, Any]]) -> dict[str, Any]:
    scans_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    geometry_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scans_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    geometry_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scans:
        scans_by_lane[str(row.get("lane_id"))].append(row)
        scans_by_family[str(row.get("family"))].append(row)
    for row in geometry:
        geometry_by_lane[str(row.get("lane_id"))].append(row)
        geometry_by_family[str(row.get("family"))].append(row)
    return {
        "overall": summarize_group(scans, geometry),
        "by_lane": {
            key: summarize_group(value, geometry_by_lane.get(key, []))
            for key, value in sorted(scans_by_lane.items())
        },
        "by_family": {
            key: summarize_group(value, geometry_by_family.get(key, []))
            for key, value in sorted(scans_by_family.items())
        },
    }


def validate_inputs(
    execution_plan: dict[str, Any],
    adapter: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    a4d_contract: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if execution_plan.get("state") != "PASS_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN":
        blockers.append("EXECUTION_PLAN_NOT_PASS")
    if int(execution_plan.get("blocker_count", -1)) != 0:
        blockers.append("EXECUTION_PLAN_BLOCKED")
    if int(execution_plan.get("total_execution_lane_count", -1)) != EXPECTED_LANES:
        blockers.append("EXECUTION_LANE_COUNT_INVALID")
    if int(execution_plan.get("raw_geometry_scan_target", -1)) != EXPECTED_SCANS:
        blockers.append("RAW_GEOMETRY_TARGET_INVALID")
    if execution_plan.get("universal_rr_allowed") is not False:
        blockers.append("UNIVERSAL_RR_NOT_DISABLED")
    if execution_plan.get("fixed_candidate_quota_allowed") is not False:
        blockers.append("FIXED_CANDIDATE_QUOTA_NOT_DISABLED")
    if adapter.get("state") != "PASS_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND":
        blockers.append("OHLCV_ADAPTER_NOT_PASS")
    layout = adapter.get("layout_signature")
    if layout != EXPECTED_LAYOUT:
        blockers.append(f"OHLCV_LAYOUT_INVALID:{layout}")
    selected_segments = manifest.get("selected_segments")
    if manifest.get("state") != "PASS" or not isinstance(selected_segments, list) or len(selected_segments) != EXPECTED_SEGMENTS:
        blockers.append("SELECTED_MANIFEST_INVALID")
    entries = registry.get("entries")
    if not isinstance(entries, list) or int(registry.get("active_entry_count", -1)) != 0:
        blockers.append("REGISTRY_INVALID")
    if len(a4d_contract.get("cost_profiles", [])) != 3:
        blockers.append("COST_PROFILE_COUNT_INVALID")
    if len(a4d_contract.get("perturbations", [])) != 2:
        blockers.append("PERTURBATION_COUNT_INVALID")
    return blockers


def self_test() -> int:
    rows = []
    for index in range(1000):
        open_v = 100.0 + index * 0.01
        close_v = open_v - (0.02 if index % 7 == 0 else 0.0)
        rows.append({
            "__timestamp": 1_700_000_000_000 + index * 60_000,
            "open": open_v,
            "high": max(open_v, close_v) + 0.05,
            "low": min(open_v, close_v) - 0.05,
            "close": close_v,
            "volume": 10.0,
            "symbol": "TESTUSDT",
            "timeframe": "1m",
            "__source_index": index,
        })
    source = pd.DataFrame(rows)
    resampled = resample_for_segment(source, 500, 820, "5m")
    measured = measurement_mask(resampled, 500, 820)
    assert int(measured.sum()) == 64
    assert bool((resampled.loc[measured, "high"] >= resampled.loc[measured, ["open", "close"]].max(axis=1)).all())
    costs = friction_profiles([
        {"id": "cost_profile_0", "fee_bps_per_side": 5, "slippage_bps_per_side": 1},
        {"id": "cost_profile_1", "fee_bps_per_side": 7.5, "slippage_bps_per_side": 3},
        {"id": "cost_profile_2", "fee_bps_per_side": 10, "slippage_bps_per_side": 6},
    ])
    assert costs == {"cost_profile_0": 0.12, "cost_profile_1": 0.21, "cost_profile_2": 0.32}
    print("STATE=PASS_SHORT_RAW_GEOMETRY_BENCHMARK_EXECUTION_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=False, default="SELF_TEST")
    parser.add_argument("--runner", required=False)
    parser.add_argument("--a4d-contract", required=False)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.runner or not args.a4d_contract:
        raise SystemExit("--runner and --a4d-contract required")

    root = Path(args.root).resolve()
    runner = import_module(Path(args.runner).resolve(), "r7a4d2_raw_geometry_runner_dependency")
    execution_plan = load_json(root / EXECUTION_PLAN_PATH)
    adapter = load_json(root / ADAPTER_EVIDENCE_PATH)
    data_contract = execution_plan.get("data_contract") if isinstance(execution_plan.get("data_contract"), dict) else {}
    manifest_path = root / str(data_contract.get("selected_manifest_path") or "")
    registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    config_path = root / "backend/strategy25/canonical_strategy25_config_v1.json"
    manifest = load_json(manifest_path)
    registry = load_json(registry_path)
    a4d_contract = load_json(Path(args.a4d_contract).resolve())
    blockers = validate_inputs(execution_plan, adapter, manifest, registry, a4d_contract)

    lanes = [
        row for row in execution_plan.get("strategy_lanes", []) + execution_plan.get("benchmark_lanes", [])
        if isinstance(row, dict)
    ]
    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    if len(lanes) != EXPECTED_LANES or len({str(row.get("lane_id")) for row in lanes}) != EXPECTED_LANES:
        blockers.append(f"LANE_SET_INVALID:{len(lanes)}")
    if len(segments) != EXPECTED_SEGMENTS or len({str(row.get("segment_id")) for row in segments}) != EXPECTED_SEGMENTS:
        blockers.append(f"SEGMENT_SET_INVALID:{len(segments)}")

    allowlist = {
        str(row.get("source_path") or "")
        for row in adapter.get("source_allowlist", [])
        if isinstance(row, dict)
    }
    required_sources = {str(row.get("source_path") or "") for row in segments}
    if not required_sources.issubset(allowlist):
        blockers.append("SELECTED_SOURCE_NOT_IN_ADAPTER_ALLOWLIST")

    registry_by_id = {
        str(row.get("strategy_id")): row
        for row in registry.get("entries", [])
        if isinstance(row, dict) and row.get("strategy_id")
    }
    canonical_paths: list[Path] = [manifest_path, registry_path, config_path]
    for lane in lanes:
        if lane.get("lane_type") != "strategy":
            continue
        strategy_id = str(lane.get("strategy_id") or "")
        entry = registry_by_id.get(strategy_id)
        if entry is None:
            blockers.append(f"STRATEGY_REGISTRY_MISSING:{strategy_id}")
            continue
        engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
        try:
            implementation = root / safe_repo_path(str(engine.get("implementation_path") or ""))
            canonical_paths.append(implementation)
            expected_sha = str(engine.get("source_sha256") or "")
            if expected_sha and sha256_file(implementation) != expected_sha:
                blockers.append(f"STRATEGY_SOURCE_SHA_MISMATCH:{strategy_id}")
        except Exception as exc:
            blockers.append(f"STRATEGY_PATH_INVALID:{strategy_id}:{type(exc).__name__}:{exc}")
    protected_paths = [Path(str(value)) for value in a4d_contract.get("protected_paths", [])]

    if blockers:
        unique = list(dict.fromkeys(blockers))
        print("STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_INPUT")
        print("BLOCKER_COUNT=" + str(len(unique)))
        print("BLOCKERS=" + json.dumps(unique, ensure_ascii=False))
        print("NEXT_STAGE=R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION")
        print("RC=2")
        return 2

    before = snapshot(canonical_paths + protected_paths)
    source_cache: dict[str, pd.DataFrame] = {}
    source_sha_by_path = {
        str(row.get("source_path") or ""): str(row.get("source_sha256") or "")
        for row in segments
    }
    for source_path in sorted(required_sources):
        source_cache[source_path] = fixed_ohlcv_frame(root / safe_repo_path(source_path), source_sha_by_path[source_path])
        canonical_paths.append(root / safe_repo_path(source_path))
    before = snapshot(canonical_paths + protected_paths)

    strategy_bindings: dict[str, tuple[type[Any], str]] = {}
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    try:
        for lane in lanes:
            if lane.get("lane_type") != "strategy":
                continue
            strategy_id = str(lane["strategy_id"])
            if strategy_id in strategy_bindings:
                continue
            entry = registry_by_id[strategy_id]
            engine = entry["canonical_engine"]
            module = runner.load_module(root, safe_repo_path(str(engine["implementation_path"])), strategy_id)
            strategy_bindings[strategy_id] = runner.resolve_callable(module, str(engine["callable"]))
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    cost_profiles = [row for row in a4d_contract.get("cost_profiles", []) if isinstance(row, dict)]
    base_cost = next(row for row in cost_profiles if str(row.get("id")) == "cost_profile_0")
    costs_pct = friction_profiles(cost_profiles)
    scans: list[dict[str, Any]] = []
    geometry: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    side_effect_attempts: list[str] = []
    total = len(lanes) * len(segments)
    completed_index = 0

    for lane in sorted(lanes, key=lambda row: str(row["lane_id"])):
        for segment in sorted(segments, key=lambda row: str(row["segment_id"])):
            completed_index += 1
            scan: dict[str, Any] = {
                "lane_id": lane["lane_id"],
                "lane_type": lane["lane_type"],
                "family": lane["family"],
                "strategy_id": lane.get("strategy_id"),
                "benchmark_id": lane.get("benchmark_id"),
                "timeframe": lane["timeframe"],
                "segment_id": segment.get("segment_id"),
                "regime": segment.get("regime"),
                "fold": segment.get("fold"),
                "source_path": segment.get("source_path"),
                "completed": False,
                "error": None,
            }
            try:
                source_path = str(segment["source_path"])
                frame = resample_for_segment(
                    source_cache[source_path],
                    int(segment["start_row"]),
                    int(segment["end_row_exclusive"]),
                    str(lane["timeframe"]),
                )
                measured = measurement_mask(
                    frame, int(segment["start_row"]), int(segment["end_row_exclusive"])
                )
                if int(measured.sum()) < 2:
                    raise ValueError(f"MEASUREMENT_BAR_COUNT_INSUFFICIENT:{int(measured.sum())}")
                if lane["lane_type"] == "strategy":
                    owner, method_name = strategy_bindings[str(lane["strategy_id"])]
                    raw_signals, semantic_counts = strategy_signals(
                        lane, frame, str(segment["regime"]), owner, method_name, runner, base_cost, side_effect_attempts
                    )
                else:
                    raw_signals = benchmark_signals(lane, frame)
                    semantic_counts = {}
                measured_signals = [
                    signal for signal in raw_signals
                    if int(signal["bar_index"]) < len(measured)
                    and bool(measured.iloc[int(signal["bar_index"])])
                ]
                eligible_signals = [
                    signal for signal in measured_signals if bool(signal.get("semantic_eligible", True))
                ]
                generated_geometry: list[dict[str, Any]] = []
                for signal in eligible_signals:
                    generated_geometry.extend(
                        geometry_rows_for_signal(lane, segment, frame, signal, measured, costs_pct)
                    )
                geometry.extend(generated_geometry)
                scan.update({
                    "completed": True,
                    "resampled_bar_count": len(frame),
                    "measurement_bar_count": int(measured.sum()),
                    "warmup_bar_count": int((~measured & (frame["__last_source_index"] < int(segment["start_row"]))).sum()),
                    "minimum_strategy_call_bars": MINIMUM_STRATEGY_CALL_BARS,
                    "raw_signal_count": len(raw_signals),
                    "measurement_signal_count": len(measured_signals),
                    "semantic_eligible_signal_count": len(eligible_signals),
                    "semantic_mismatch_count": int(semantic_counts.get("semantic_mismatch", 0)),
                    "geometry_row_count": len(generated_geometry),
                    "semantic_counts": semantic_counts,
                    "insufficient_warmup": bool(lane["lane_type"] == "strategy" and len(frame) < MINIMUM_STRATEGY_CALL_BARS),
                })
            except Exception as exc:
                scan["error"] = f"{type(exc).__name__}:{exc}"
                failures.append({
                    "lane_id": lane.get("lane_id"),
                    "segment_id": segment.get("segment_id"),
                    "error": scan["error"],
                })
            scans.append(scan)
            if completed_index % 50 == 0 or completed_index == total:
                failed_now = sum(1 for row in scans if row.get("completed") is not True)
                print(
                    f"A4D2_RAW_GEOMETRY_PROGRESS={completed_index}/{total} FAILED={failed_now} SIGNAL_GEOMETRY_ROWS={len(geometry)}",
                    flush=True,
                )

    after = snapshot(canonical_paths + protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    aggregate = aggregate_results(scans, geometry)
    aggregate.update({
        "schema": "r7a4d2_short_raw_geometry_and_simple_benchmark_execution_aggregate_v1",
        "official_stage": "R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION",
        "target_commit": args.target_sha,
        "scan_target": EXPECTED_SCANS,
        "scan_count": len(scans),
        "completed_scan_count": sum(1 for row in scans if row.get("completed") is True),
        "failed_scan_count": sum(1 for row in scans if row.get("completed") is not True),
        "geometry_row_count": len(geometry),
        "strategy_lane_count": int(execution_plan["strategy_timeframe_lane_count"]),
        "benchmark_lane_count": int(execution_plan["benchmark_timeframe_lane_count"]),
        "universal_rr_applied": False,
        "future_pnl_selection_allowed": False,
        "side_effect_attempt_count": len(side_effect_attempts),
        "protected_mutation_path_count": len(mutation_paths),
        "failure_count": len(failures),
        "failure_histogram": dict(sorted(Counter(str(row["error"]).split(":", 1)[0] for row in failures).items())),
    })

    output = root / OUTPUT_DIR
    scan_count, scan_sha = atomic_jsonl(output / "scan_results_v1.jsonl", scans)
    geometry_count, geometry_sha = atomic_jsonl(output / "signal_geometry_v1.jsonl", geometry)
    aggregate["scan_results_sha256"] = scan_sha
    aggregate["signal_geometry_sha256"] = geometry_sha
    blockers_out: list[str] = []
    if scan_count != EXPECTED_SCANS:
        blockers_out.append(f"SCAN_COUNT_INVALID:{scan_count}")
    failed_count = sum(1 for row in scans if row.get("completed") is not True)
    if failed_count:
        blockers_out.append(f"SCAN_FAILURES:{failed_count}")
    if side_effect_attempts:
        blockers_out.append(f"SIDE_EFFECT_ATTEMPTS:{len(side_effect_attempts)}")
    if mutation_paths:
        blockers_out.append(f"PROTECTED_MUTATIONS:{len(mutation_paths)}")
    state = "PASS_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION" if not blockers_out else "HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION"
    aggregate["state"] = state
    aggregate["blocker_count"] = len(blockers_out)
    aggregate["blockers"] = blockers_out
    aggregate["next_stage"] = (
        "R7.A4D2_SHORT_DISCOVERY_EXIT_AND_PARAMETER_LOCK"
        if not blockers_out
        else "R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_DIAGNOSE"
    )
    atomic_json(output / "aggregate_v1.json", aggregate)
    proof = {
        "schema": "r7a4d2_short_raw_geometry_and_simple_benchmark_execution_proof_v1",
        "official_stage": "R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION",
        "state": state,
        "target_commit": args.target_sha,
        "scan_results_sha256": scan_sha,
        "signal_geometry_sha256": geometry_sha,
        "scan_count": scan_count,
        "geometry_row_count": geometry_count,
        "side_effect_attempts": side_effect_attempts,
        "mutation_paths": mutation_paths,
        "failures": failures[:100],
        "blockers": blockers_out,
    }
    atomic_json(output / "proof_v1.json", proof)

    overall = aggregate["overall"]
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers_out)))
    print("SCAN_TARGET=" + str(EXPECTED_SCANS))
    print("SCAN_COUNT=" + str(scan_count))
    print("COMPLETED_SCAN_COUNT=" + str(aggregate["completed_scan_count"]))
    print("FAILED_SCAN_COUNT=" + str(aggregate["failed_scan_count"]))
    print("STRATEGY_LANE_COUNT=" + str(aggregate["strategy_lane_count"]))
    print("BENCHMARK_LANE_COUNT=" + str(aggregate["benchmark_lane_count"]))
    print("RAW_SIGNAL_COUNT=" + str(overall["raw_signal_count"]))
    print("MEASUREMENT_SIGNAL_COUNT=" + str(overall["measurement_signal_count"]))
    print("SEMANTIC_ELIGIBLE_SIGNAL_COUNT=" + str(overall["semantic_eligible_signal_count"]))
    print("SEMANTIC_MISMATCH_COUNT=" + str(overall["semantic_mismatch_count"]))
    print("GEOMETRY_ROW_COUNT=" + str(geometry_count))
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("FAILURE_COUNT=" + str(len(failures)))
    print("FAMILY_SUMMARY=" + json.dumps(aggregate["by_family"], ensure_ascii=False, sort_keys=True))
    print("AGGREGATE_JSON=" + str(output / "aggregate_v1.json"))
    print("NEXT_STAGE=" + str(aggregate["next_stage"]))
    print("BLOCKERS=" + json.dumps(blockers_out, ensure_ascii=False))
    print("RC=" + ("0" if not blockers_out else "2"))
    print("R7A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_COMPLETE")
    return 0 if not blockers_out else 2


if __name__ == "__main__":
    raise SystemExit(main())
