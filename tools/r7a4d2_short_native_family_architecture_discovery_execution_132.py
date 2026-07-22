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
from typing import Any

import numpy as np
import pandas as pd

PLAN = Path("runtime/r7a4d2_short_vwap_native_hypothesis_and_remaining_family_rebuild_plan/rebuild_plan_v1.json")
MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
VWAP_REPORT = Path("runtime/r7a4d2_short_selective_vwap_repair_execution_54_and_remaining_uplift_audit/economic_execution_and_uplift_audit_v1.json")
PRIOR_CELLS = Path("runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_arm_cell_results_v1.jsonl")
OUTPUT_DIR = Path("runtime/r7a4d2_short_native_family_architecture_discovery_execution_132")

EXPECTED_STRATEGIES = 11
EXPECTED_BUNDLES = 22
EXPECTED_SEGMENTS = 12
EXPECTED_STRESS_PER_BUNDLE = 6
EXPECTED_CELLS = 132
SEVERE_CELL = ("cost_profile_2", "perturbation_1")
MIN_TRADES = 8


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return len(rows), digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_no}")
            rows.append(value)
    return rows


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False, min_periods=max(2, span // 2)).mean()


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat([(high - low), (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    return true_range.rolling(period, min_periods=max(3, period // 2)).mean()


def rolling_vwap(frame: pd.DataFrame, lookback: int) -> pd.Series:
    volume = frame["volume"].astype(float)
    typical = (frame["high"].astype(float) + frame["low"].astype(float) + frame["close"].astype(float)) / 3.0
    weighted = (typical * volume).rolling(lookback, min_periods=max(3, lookback // 2)).sum()
    volume_sum = volume.rolling(lookback, min_periods=max(3, lookback // 2)).sum()
    fallback = typical.rolling(lookback, min_periods=max(3, lookback // 2)).mean()
    return weighted.div(volume_sum.where(volume_sum > 0)).fillna(fallback)


def cumulative_vwap(frame: pd.DataFrame) -> pd.Series:
    volume = frame["volume"].astype(float)
    typical = (frame["high"].astype(float) + frame["low"].astype(float) + frame["close"].astype(float)) / 3.0
    return (typical * volume).cumsum().div(volume.cumsum().replace(0, np.nan)).fillna(typical.expanding().mean())


def obv(frame: pd.DataFrame) -> pd.Series:
    direction = np.sign(frame["close"].astype(float).diff().fillna(0.0))
    return pd.Series(direction * frame["volume"].astype(float), index=frame.index).cumsum()


def features(frame: pd.DataFrame) -> dict[str, pd.Series]:
    close = frame["close"].astype(float)
    open_v = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    atr14 = atr(frame, 14).bfill().fillna((high - low).rolling(3, min_periods=1).mean())
    ema8 = ema(close, 8)
    ema13 = ema(close, 13)
    ema21 = ema(close, 21)
    ema50 = ema(close, 50)
    basis = close.rolling(20, min_periods=8).mean()
    std = close.rolling(20, min_periods=8).std(ddof=0).fillna(0.0)
    vwap20 = rolling_vwap(frame, 20)
    vwap48 = rolling_vwap(frame, 48)
    cvwap = cumulative_vwap(frame)
    obv_v = obv(frame)
    vol_mean = volume.rolling(20, min_periods=8).mean()
    vol_std = volume.rolling(20, min_periods=8).std(ddof=0).replace(0, np.nan)
    volume_z = (volume - vol_mean).div(vol_std).fillna(0.0)
    range_v = (high - low).replace(0, np.nan)
    body = (close - open_v).abs()
    upper_wick = high - pd.concat([open_v, close], axis=1).max(axis=1)
    lower_wick = pd.concat([open_v, close], axis=1).min(axis=1) - low
    return {
        "open": open_v, "high": high, "low": low, "close": close, "volume": volume,
        "atr": atr14, "ema8": ema8, "ema13": ema13, "ema21": ema21, "ema50": ema50,
        "basis": basis, "std": std, "bb_upper": basis + 2 * std, "bb_lower": basis - 2 * std,
        "kc_mid": ema21, "kc_upper": ema21 + 1.5 * atr14, "kc_lower": ema21 - 1.5 * atr14,
        "vwap20": vwap20, "vwap48": vwap48, "cvwap": cvwap,
        "obv": obv_v, "obv_ema": ema(obv_v, 10), "volume_z": volume_z,
        "range_high10": high.shift(1).rolling(10, min_periods=4).max(),
        "range_low10": low.shift(1).rolling(10, min_periods=4).min(),
        "range_high20": high.shift(1).rolling(20, min_periods=8).max(),
        "range_low20": low.shift(1).rolling(20, min_periods=8).min(),
        "body": body, "upper_wick": upper_wick, "lower_wick": lower_wick,
        "bar_range": range_v.fillna(0.0), "return1": close.pct_change().fillna(0.0),
    }


def latest_completed_index(frame: pd.DataFrame, trigger_last_source_index: int) -> int | None:
    values = frame["__last_source_index"].astype(int).to_numpy()
    index = int(np.searchsorted(values, trigger_last_source_index, side="right") - 1)
    return index if index >= 0 else None


def valid_at(feat: dict[str, pd.Series], key: str, index: int | None, default: float = math.nan) -> float:
    if index is None or index < 0 or index >= len(feat[key]):
        return default
    return finite(feat[key].iloc[index], default)


def build_signal(bundle: dict[str, Any], frames: dict[str, pd.DataFrame], feats: dict[str, dict[str, pd.Series]], masks: dict[str, pd.Series], segment: dict[str, Any]) -> list[dict[str, Any]]:
    if str(segment.get("regime") or "") not in {str(value) for value in bundle.get("allowed_regimes", [])}:
        return []
    bundle_id = str(bundle["bundle_id"])
    trigger_tf = str(bundle["trigger_timeframe"])
    setup_tf = str(bundle["setup_timeframe"])
    context_tf = str(bundle["context_timeframe"])
    trigger = frames[trigger_tf]
    setup = frames[setup_tf]
    context = frames[context_tf]
    tf = feats[trigger_tf]
    sf = feats[setup_tf]
    cf = feats[context_tf]
    trigger_mask = masks[trigger_tf].astype(bool)
    signals: list[dict[str, Any]] = []
    for i in range(4, len(trigger) - 1):
        if not bool(trigger_mask.iloc[i]) or not bool(trigger_mask.iloc[i + 1]):
            continue
        trigger_last = int(trigger.iloc[i]["__last_source_index"])
        si = latest_completed_index(setup, trigger_last)
        ci = latest_completed_index(context, trigger_last)
        if si is None or ci is None or si < 3 or ci < 2:
            continue
        close = valid_at(tf, "close", i)
        open_v = valid_at(tf, "open", i)
        high = valid_at(tf, "high", i)
        atr_t = max(valid_at(tf, "atr", i, 0.0), close * 0.0005)
        setup_close = valid_at(sf, "close", si)
        setup_open = valid_at(sf, "open", si)
        setup_high = valid_at(sf, "high", si)
        setup_atr = max(valid_at(sf, "atr", si, 0.0), setup_close * 0.0005)
        condition = False
        stop = max(high, setup_high) + 0.15 * setup_atr
        target = close - max(1.2 * setup_atr, close * 0.002)
        partial = None
        timeout = 12
        if bundle_id == "vol_spike_fade:15m_context_5m_exhaustion":
            prior_high = valid_at(sf, "range_high10", si)
            condition = valid_at(sf, "volume_z", si) > 1.25 and setup_high >= prior_high and setup_close < prior_high and setup_close < setup_open and valid_at(sf, "upper_wick", si) > max(valid_at(sf, "body", si), 0.15 * setup_atr) and valid_at(cf, "ema8", ci) <= valid_at(cf, "ema21", ci) * 1.003
            target = min(valid_at(sf, "vwap20", si), setup_close - 0.8 * setup_atr); partial = setup_close - 0.6 * setup_atr; timeout = 10
        elif bundle_id == "vol_spike_fade:5m_climax_reclaim":
            prior_high = valid_at(sf, "range_high10", si)
            condition = valid_at(sf, "volume_z", si) > 1.8 and setup_high > prior_high and setup_close < setup_open and valid_at(sf, "upper_wick", si) > 0.45 * valid_at(sf, "bar_range", si, 0.0) and setup_close < valid_at(sf, "close", si - 1)
            target = min(valid_at(sf, "vwap20", si), setup_close - setup_atr); timeout = 8
        elif bundle_id == "keltner_trend:15m_slope_5m_pullback":
            condition = valid_at(cf, "ema8", ci) < valid_at(cf, "ema21", ci) and valid_at(cf, "ema21", ci) < valid_at(cf, "ema21", ci - 1) and setup_high >= valid_at(sf, "kc_mid", si) and setup_close < valid_at(sf, "kc_mid", si) and setup_close < setup_open and setup_close > valid_at(sf, "kc_lower", si) - 0.4 * setup_atr
            stop = setup_high + 0.2 * setup_atr; target = min(valid_at(sf, "range_low10", si), setup_close - 1.5 * setup_atr); partial = setup_close - setup_atr; timeout = 14
        elif bundle_id == "keltner_trend:breakdown_retest":
            condition = valid_at(cf, "ema8", ci) < valid_at(cf, "ema21", ci) and valid_at(sf, "close", si - 1) < valid_at(sf, "kc_lower", si - 1) and setup_high >= valid_at(sf, "kc_lower", si) and setup_close < valid_at(sf, "kc_lower", si) and setup_close < setup_open
            stop = setup_high + 0.15 * setup_atr; target = min(valid_at(sf, "range_low20", si), setup_close - 1.4 * setup_atr); timeout = 12
        elif bundle_id == "obv_trend:15m_distribution_5m_break":
            context_resistance = valid_at(cf, "range_high10", ci)
            condition = valid_at(cf, "close", ci) >= context_resistance - 0.6 * valid_at(cf, "atr", ci, 0.0) and valid_at(cf, "obv", ci) < valid_at(cf, "obv", ci - 2) and setup_close < valid_at(sf, "range_low10", si) and valid_at(sf, "volume_z", si) > 0.2
            stop = max(setup_high, valid_at(sf, "range_high10", si)) + 0.1 * setup_atr; target = setup_close - 1.6 * setup_atr; partial = setup_close - setup_atr; timeout = 14
        elif bundle_id == "obv_trend:volume_impulse_retest":
            impulse = valid_at(sf, "obv", si - 1) - valid_at(sf, "obv", si - 2)
            condition = valid_at(cf, "ema8", ci) < valid_at(cf, "ema21", ci) and impulse < 0 and valid_at(sf, "volume_z", si - 1) > 0.8 and setup_high >= valid_at(sf, "ema8", si) and setup_close < valid_at(sf, "ema8", si) and setup_close < setup_open and valid_at(sf, "volume", si) < valid_at(sf, "volume", si - 1)
            stop = setup_high + 0.15 * setup_atr; target = setup_close - 1.5 * setup_atr; timeout = 12
        elif bundle_id == "anchor_vwap_trend:session_anchor_retest":
            condition = valid_at(cf, "close", ci) < valid_at(cf, "cvwap", ci) and valid_at(cf, "cvwap", ci) <= valid_at(cf, "cvwap", ci - 1) and setup_high >= valid_at(sf, "cvwap", si) and setup_close < valid_at(sf, "cvwap", si) and setup_close < setup_open
            stop = setup_high + 0.15 * setup_atr; target = min(valid_at(sf, "range_low10", si), setup_close - 1.4 * setup_atr); partial = setup_close - setup_atr; timeout = 14
        elif bundle_id == "anchor_vwap_trend:event_anchor_confluence":
            resistance = valid_at(sf, "range_high20", si); anchor = valid_at(sf, "vwap48", si)
            condition = valid_at(cf, "ema8", ci) <= valid_at(cf, "ema21", ci) and abs(anchor - resistance) <= 0.8 * setup_atr and setup_high >= min(anchor, resistance) and setup_close < min(anchor, resistance) and setup_close < setup_open
            stop = max(setup_high, resistance) + 0.15 * setup_atr; target = setup_close - 1.5 * setup_atr; timeout = 12
        elif bundle_id == "vwap_revert:15m_context_5m_reclaim":
            upper = valid_at(sf, "vwap20", si) + 1.1 * valid_at(sf, "std", si, 0.0)
            condition = valid_at(cf, "vwap20", ci) <= valid_at(cf, "vwap20", ci - 1) + 0.15 * valid_at(cf, "atr", ci, 0.0) and setup_high > upper and setup_close < upper and setup_close < setup_open
            stop = setup_high + 0.12 * setup_atr; target = valid_at(sf, "vwap20", si); partial = target; timeout = 10
        elif bundle_id == "vwap_revert:5m_setup_1m_confirmation":
            upper = valid_at(sf, "vwap20", si) + valid_at(sf, "std", si, 0.0)
            condition = setup_high > upper and setup_close < upper and high < valid_at(tf, "high", i - 1) and close < open_v and close < valid_at(tf, "ema8", i)
            stop = max(setup_high, high) + 0.1 * setup_atr; target = valid_at(sf, "vwap20", si); timeout = 20
        elif bundle_id == "bb_revert:15m_neutral_5m_close_inside":
            context_slope = abs(valid_at(cf, "basis", ci) - valid_at(cf, "basis", ci - 1))
            condition = context_slope <= 0.2 * valid_at(cf, "atr", ci, 0.0) and valid_at(sf, "close", si - 1) > valid_at(sf, "bb_upper", si - 1) and setup_close < valid_at(sf, "bb_upper", si) and setup_close < setup_open
            stop = max(setup_high, valid_at(sf, "high", si - 1)) + 0.1 * setup_atr; target = valid_at(sf, "basis", si); partial = target; timeout = 12
        elif bundle_id == "bb_revert:double_excursion_lower_high":
            prior_excursions = [j for j in range(max(2, si - 8), si) if valid_at(sf, "high", j) > valid_at(sf, "bb_upper", j)]
            prior = prior_excursions[-1] if prior_excursions else None
            condition = prior is not None and setup_high > valid_at(sf, "bb_upper", si) and setup_high < valid_at(sf, "high", prior) and setup_close < valid_at(sf, "bb_upper", si) and valid_at(sf, "std", si) < valid_at(sf, "std", prior)
            stop = (valid_at(sf, "high", prior) if prior is not None else setup_high) + 0.1 * setup_atr; target = valid_at(sf, "basis", si); timeout = 12
        elif bundle_id == "range_fade:confirmed_boundary_reject":
            range_high = valid_at(cf, "range_high20", ci); range_low = valid_at(cf, "range_low20", ci); width = range_high - range_low
            touches = sum(1 for j in range(max(1, ci - 10), ci) if abs(valid_at(cf, "high", j) - range_high) <= 0.25 * valid_at(cf, "atr", ci, 0.0))
            condition = touches >= 2 and width >= 2.0 * valid_at(cf, "atr", ci, 0.0) and setup_high >= range_high - 0.3 * setup_atr and setup_close < range_high and setup_close < setup_open
            stop = max(setup_high, range_high) + 0.15 * setup_atr; target = (range_high + range_low) / 2; partial = target; timeout = 16
        elif bundle_id == "range_fade:false_break_reentry":
            boundary = valid_at(sf, "range_high20", si - 1)
            condition = valid_at(sf, "high", si - 1) > boundary and valid_at(sf, "close", si - 1) < boundary and setup_high < valid_at(sf, "high", si - 1) and setup_close < boundary and setup_close < setup_open
            stop = valid_at(sf, "high", si - 1) + 0.1 * setup_atr; target = (boundary + valid_at(sf, "range_low20", si)) / 2; timeout = 12
        elif bundle_id == "liquidity_sweep:5m_prior_high_reclaim":
            prior = valid_at(sf, "range_high10", si - 1)
            condition = valid_at(sf, "high", si - 1) > prior and valid_at(sf, "close", si - 1) < prior and setup_high < valid_at(sf, "high", si - 1) and setup_close < valid_at(sf, "close", si - 1)
            stop = valid_at(sf, "high", si - 1) + 0.12 * setup_atr; target = min(valid_at(sf, "vwap20", si), setup_close - 1.3 * setup_atr); partial = setup_close - 0.8 * setup_atr; timeout = 12
        elif bundle_id == "liquidity_sweep:equal_high_cluster":
            highs = [valid_at(sf, "high", j) for j in range(max(2, si - 8), si)]; cluster = float(np.median(highs)) if highs else math.nan; dispersion = float(np.std(highs)) if highs else math.inf
            condition = dispersion <= 0.35 * setup_atr and setup_high > cluster and setup_close < cluster and valid_at(sf, "volume_z", si) > 0.8
            stop = setup_high + 0.12 * setup_atr; target = min(valid_at(sf, "vwap20", si), setup_close - 1.2 * setup_atr); timeout = 10
        elif bundle_id == "scalp_snap:15m_down_5m_pullback_1m_trigger":
            setup_ok = valid_at(cf, "ema8", ci) < valid_at(cf, "ema21", ci) and setup_high >= valid_at(sf, "ema8", si) and setup_close < valid_at(sf, "ema8", si)
            condition = setup_ok and high < valid_at(tf, "high", i - 1) and close < open_v and close < valid_at(tf, "ema8", i)
            stop = max(setup_high, high) + 0.1 * setup_atr; target = setup_close - 1.2 * setup_atr; timeout = 25
        elif bundle_id == "scalp_snap:5m_impulse_retest":
            condition = valid_at(sf, "return1", si - 1) < -0.002 and valid_at(sf, "volume_z", si - 1) > 0.5 and high < valid_at(tf, "high", i - 1) and close < open_v and close < valid_at(tf, "ema8", i)
            stop = max(setup_high, high) + 0.1 * setup_atr; target = setup_close - 1.1 * setup_atr; partial = setup_close - 0.7 * setup_atr; timeout = 20
        elif bundle_id == "ema_ribbon_scalp:15m_stack_5m_compression_1m_retest":
            stack = valid_at(cf, "ema8", ci) < valid_at(cf, "ema13", ci) < valid_at(cf, "ema21", ci); compression = abs(valid_at(sf, "ema8", si - 1) - valid_at(sf, "ema21", si - 1)) < 0.35 * setup_atr; breakdown = setup_close < valid_at(sf, "range_low10", si)
            condition = stack and compression and breakdown and high < valid_at(tf, "high", i - 1) and close < open_v
            stop = max(setup_high, high) + 0.1 * setup_atr; target = setup_close - 1.3 * setup_atr; partial = setup_close - 0.8 * setup_atr; timeout = 24
        elif bundle_id == "ema_ribbon_scalp:5m_stack_pullback":
            stack = valid_at(sf, "ema8", si) < valid_at(sf, "ema13", si) < valid_at(sf, "ema21", si)
            condition = stack and setup_high >= valid_at(sf, "ema8", si) and setup_close < valid_at(sf, "ema8", si) and high < valid_at(tf, "high", i - 1) and close < open_v
            stop = max(setup_high, high) + 0.1 * setup_atr; target = setup_close - 1.2 * setup_atr; timeout = 20
        elif bundle_id == "grid_rebalance:15m_flat_5m_outer_quartile":
            range_high = valid_at(cf, "range_high20", ci); range_low = valid_at(cf, "range_low20", ci); width = range_high - range_low; slope = abs(valid_at(cf, "ema21", ci) - valid_at(cf, "ema21", ci - 1)); upper_quartile = range_low + 0.75 * width
            condition = slope <= 0.2 * valid_at(cf, "atr", ci, 0.0) and width >= 2.0 * valid_at(cf, "atr", ci, 0.0) and setup_high >= upper_quartile and setup_close < setup_open
            stop = max(setup_high, range_high) + 0.12 * setup_atr; target = (range_high + range_low) / 2; timeout = 16
        elif bundle_id == "grid_rebalance:5m_atr_single_cycle":
            range_high = valid_at(sf, "range_high20", si); range_low = valid_at(sf, "range_low20", si); width = range_high - range_low
            condition = 2.0 * setup_atr <= width <= 6.0 * setup_atr and setup_high >= range_high - 0.2 * setup_atr and setup_close < setup_open
            stop = max(setup_high, range_high) + 0.15 * setup_atr; target = (range_high + range_low) / 2; timeout = 14
        else:
            raise ValueError(f"BUNDLE_UNSUPPORTED:{bundle_id}")
        if not condition:
            continue
        entry_reference = float(trigger.iloc[i + 1]["open"])
        if not (math.isfinite(stop) and math.isfinite(target) and stop > entry_reference > target > 0):
            continue
        if partial is not None and not (entry_reference > partial > target):
            partial = None
        signals.append({"signal_bar_index": i, "entry_bar_index": i + 1, "stop_price": stop, "target_price": target, "partial_price": partial, "timeout_bars": max(2, int(timeout))})
    return signals


def simulate_trade(frame: pd.DataFrame, measurement: pd.Series, signal: dict[str, Any], cost: dict[str, Any], perturbation: dict[str, Any], timeframe: str) -> dict[str, Any] | None:
    entry_delay = int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_entry_delay_bars") or 0)
    exit_delay = int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_exit_delay_bars") or 0)
    entry_index = int(signal["entry_bar_index"]) + entry_delay
    measured = np.flatnonzero(measurement.to_numpy(dtype=bool))
    if measured.size == 0:
        return None
    last_index = int(measured[-1])
    if entry_index >= len(frame) or entry_index > last_index or not bool(measurement.iloc[entry_index]):
        return None
    entry = float(frame.iloc[entry_index]["open"]); stop = float(signal["stop_price"]); target = float(signal["target_price"])
    partial = signal.get("partial_price"); partial_price = float(partial) if isinstance(partial, (int, float)) and math.isfinite(float(partial)) else None
    if not (stop > entry > target > 0):
        return None
    risk_pct = (stop - entry) / entry * 100.0
    if risk_pct <= 0:
        return None
    timeout_index = min(entry_index + int(signal["timeout_bars"]), last_index)
    partial_hit = False; partial_index = None; reason = "segment_end"; trigger_index = last_index; reference_exit = float(frame.iloc[last_index]["close"]); remaining_stop = stop
    for index in range(entry_index, last_index + 1):
        high = float(frame.iloc[index]["high"]); low = float(frame.iloc[index]["low"])
        if high >= remaining_stop:
            reason = "partial30+stop" if partial_hit else "stop"; trigger_index = index; reference_exit = remaining_stop; break
        if partial_price is not None and not partial_hit and low <= partial_price:
            partial_hit = True; partial_index = index; remaining_stop = min(stop, entry)
        if low <= target:
            reason = "partial30+take_profit" if partial_hit else "take_profit"; trigger_index = index; reference_exit = target; break
        if index >= timeout_index:
            reason = "partial30+timeout" if partial_hit else "timeout"; trigger_index = index; reference_exit = float(frame.iloc[index]["close"]); break
    execution_index = min(trigger_index + exit_delay, last_index)
    if exit_delay == 0 and reason in {"stop", "take_profit", "partial30+stop", "partial30+take_profit"}:
        final_exit = reference_exit
    elif reason == "segment_end":
        final_exit = float(frame.iloc[execution_index]["close"])
    else:
        final_exit = float(frame.iloc[execution_index]["open"])
    gross_pct = 0.30 * ((entry - partial_price) / entry * 100.0) + 0.70 * ((entry - final_exit) / entry * 100.0) if partial_hit and partial_price is not None else (entry - final_exit) / entry * 100.0
    round_trip_pct = 2.0 * (float(cost.get("fee_bps_per_side") or 0.0) + float(cost.get("slippage_bps_per_side") or 0.0)) / 100.0
    minutes = {"1m": 1, "5m": 5, "15m": 15}[timeframe]; holding_hours = max(execution_index - entry_index, 0) * minutes / 60.0
    funding_pct = float(cost.get("funding_bps_per_8h") or 0.0) / 100.0 * holding_hours / 8.0; net_pct = gross_pct - round_trip_pct - funding_pct
    return {"entry_index": entry_index, "exit_index": execution_index, "entry_price": entry, "exit_price": final_exit, "stop_price": stop, "target_price": target, "partial_price": partial_price, "partial_hit": partial_hit, "partial_index": partial_index, "risk_pct": risk_pct, "gross_return_pct": gross_pct, "round_trip_cost_pct": round_trip_pct, "funding_cost_pct": funding_pct, "net_return_pct": net_pct, "net_r": net_pct / risk_pct, "exit_reason": reason, "holding_bars": max(execution_index - entry_index, 0)}


def economic_pass(helper: Any, row: dict[str, Any]) -> bool:
    return int(row.get("trade_count") or 0) >= MIN_TRADES and helper.finite_metric(row.get("profit_factor")) > 1.0 and helper.finite_metric(row.get("expectancy_r")) > 0.0 and helper.finite_metric(row.get("net_pnl_sum_pct")) > 0.0


def strict_pass(helper: Any, row: dict[str, Any]) -> bool:
    return int(row.get("trade_count") or 0) >= MIN_TRADES and helper.finite_metric(row.get("profit_factor")) > 1.25 and helper.finite_metric(row.get("expectancy_r")) > 0.15 and helper.finite_metric(row.get("net_pnl_sum_pct")) > 0.0


def reference_drawdowns(report: dict[str, Any], prior_cells: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in report.get("vwap_candidate_rows", report.get("candidate_rows", [])):
        if isinstance(row, dict) and isinstance(row.get("native_reference_severe_metrics"), dict):
            value = finite(row["native_reference_severe_metrics"].get("max_drawdown_pct"), math.inf)
            if math.isfinite(value):
                result["vwap_revert"] = min(result.get("vwap_revert", math.inf), value)
    for row in prior_cells:
        if not isinstance(row, dict) or (str(row.get("cost_profile_id")), str(row.get("perturbation_id"))) != SEVERE_CELL or int(row.get("trade_count") or 0) < MIN_TRADES:
            continue
        strategy_id = str(row.get("strategy_id") or ""); value = finite(row.get("max_drawdown_pct"), math.inf)
        if strategy_id and math.isfinite(value):
            result[strategy_id] = min(result.get(strategy_id, math.inf), value)
    return result


def self_test() -> int:
    source = pd.DataFrame({"__timestamp": np.arange(900, dtype=float), "open": 100 - np.arange(900) * 0.001, "high": 100.1 - np.arange(900) * 0.001, "low": 99.9 - np.arange(900) * 0.001, "close": 100 - np.arange(900) * 0.001, "volume": np.ones(900) * 10, "symbol": "TEST", "timeframe": "1m", "__source_index": np.arange(900, dtype=int)})
    assert len(features(source)["close"]) == 900
    signal = {"entry_bar_index": 20, "stop_price": 100.5, "target_price": 99.0, "partial_price": 99.5, "timeout_bars": 10}
    trade = simulate_trade(source, pd.Series([True] * len(source)), signal, {"fee_bps_per_side": 1, "slippage_bps_per_side": 1}, {}, "1m")
    assert trade is not None and math.isfinite(float(trade["net_r"]))
    print("STATE=PASS_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_SELF_TEST"); print("RC=0"); return 0


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", default="/home/z/z"); parser.add_argument("--target-sha", default="UNKNOWN"); parser.add_argument("--raw-module"); parser.add_argument("--helper-module"); parser.add_argument("--a4d-contract"); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test: return self_test()
    if not args.raw_module or not args.helper_module or not args.a4d_contract: raise SystemExit("--raw-module --helper-module --a4d-contract required")
    root = Path(args.root).resolve(); raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_native_family_raw"); helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_native_family_helper")
    required = [root / PLAN, root / MANIFEST, root / VWAP_REPORT, root / PRIOR_CELLS]; missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_INPUT"); print("BLOCKER_COUNT=1"); print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)])); print("RC=2"); return 2
    plan = load_json(root / PLAN); manifest = load_json(root / MANIFEST); report = load_json(root / VWAP_REPORT); prior_cells = load_jsonl(root / PRIOR_CELLS); contract = load_json(Path(args.a4d_contract).resolve()); blockers: list[str] = []
    if plan.get("state") != "PASS_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN": blockers.append("REBUILD_PLAN_NOT_PASS")
    bundles = [row for row in plan.get("architecture_bundles", []) if isinstance(row, dict)]
    if len(bundles) != EXPECTED_BUNDLES: blockers.append(f"ARCHITECTURE_BUNDLE_COUNT_INVALID:{len(bundles)}")
    if len({str(row.get("strategy_id")) for row in bundles}) != EXPECTED_STRATEGIES: blockers.append("STRATEGY_COUNT_INVALID")
    if len({str(row.get("bundle_id")) for row in bundles}) != EXPECTED_BUNDLES: blockers.append("BUNDLE_ID_DUPLICATE")
    costs = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]; perturbations = [row for row in contract.get("perturbations", []) if isinstance(row, dict)]
    if len(costs) * len(perturbations) != EXPECTED_STRESS_PER_BUNDLE: blockers.append("STRESS_CELL_COUNT_INVALID")
    segments = {str(row["segment_id"]): row for row in manifest.get("selected_segments", []) if isinstance(row, dict) and int(row.get("fold", 99)) < 3}
    if len(segments) != EXPECTED_SEGMENTS: blockers.append(f"DISCOVERY_SEGMENT_COUNT_INVALID:{len(segments)}")
    if blockers:
        print("STATE=HOLD_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_INPUT"); print("BLOCKER_COUNT=" + str(len(blockers))); print("BLOCKERS=" + json.dumps(blockers)); print("RC=2"); return 2
    source_sha = {str(row.get("source_path")): str(row.get("source_sha256") or "") for row in manifest.get("selected_segments", []) if isinstance(row, dict)}
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]; canonical_paths = [root / PLAN, root / MANIFEST, root / VWAP_REPORT, root / PRIOR_CELLS]
    for path in sorted({str(row["source_path"]) for row in segments.values()}): canonical_paths.append(root / helper.safe_repo_path(path))
    before = helper.snapshot(canonical_paths + protected)
    source_cache: dict[str, pd.DataFrame] = {}; frame_cache: dict[tuple[str, str], pd.DataFrame] = {}; mask_cache: dict[tuple[str, str], pd.Series] = {}; feature_cache: dict[tuple[str, str], dict[str, pd.Series]] = {}; signal_fingerprints: dict[str, set[tuple[str, int]]] = defaultdict(set); trade_rows: list[dict[str, Any]] = []; cell_rows: list[dict[str, Any]] = []
    for completed, bundle in enumerate(sorted(bundles, key=lambda row: (int(row.get("batch", 9)), str(row["strategy_id"]), str(row["bundle_id"]))), 1):
        bundle_id = str(bundle["bundle_id"]); trigger_tf = str(bundle["trigger_timeframe"]); bundle_signals: dict[str, list[dict[str, Any]]] = {}
        for segment_id, segment in sorted(segments.items()):
            source_path = str(segment["source_path"])
            if source_path not in source_cache: source_cache[source_path] = raw.fixed_ohlcv_frame(root / helper.safe_repo_path(source_path), source_sha[source_path])
            frames: dict[str, pd.DataFrame] = {}; feats: dict[str, dict[str, pd.Series]] = {}; masks: dict[str, pd.Series] = {}
            for timeframe in {str(bundle["context_timeframe"]), str(bundle["setup_timeframe"]), trigger_tf}:
                key = (segment_id, timeframe)
                if key not in frame_cache:
                    frame_cache[key] = raw.resample_for_segment(source_cache[source_path], int(segment["start_row"]), int(segment["end_row_exclusive"]), timeframe); mask_cache[key] = raw.measurement_mask(frame_cache[key], int(segment["start_row"]), int(segment["end_row_exclusive"])); feature_cache[key] = features(frame_cache[key])
                frames[timeframe] = frame_cache[key]; masks[timeframe] = mask_cache[key]; feats[timeframe] = feature_cache[key]
            signals = build_signal(bundle, frames, feats, masks, segment); bundle_signals[segment_id] = signals; signal_fingerprints[bundle_id].update((segment_id, int(row["signal_bar_index"])) for row in signals)
        for cost in costs:
            for perturbation in perturbations:
                cell_trades: list[dict[str, Any]] = []
                for segment_id, segment in sorted(segments.items()):
                    frame = frame_cache[(segment_id, trigger_tf)]; measurement = mask_cache[(segment_id, trigger_tf)]; last_exit = -1
                    for signal in bundle_signals[segment_id]:
                        if int(signal["entry_bar_index"]) <= last_exit: continue
                        trade = simulate_trade(frame, measurement, signal, cost, perturbation, trigger_tf)
                        if trade is None: continue
                        last_exit = int(trade["exit_index"])
                        trade.update({"bundle_id": bundle_id, "strategy_id": bundle["strategy_id"], "family": bundle["family"], "batch": bundle["batch"], "role": bundle["role"], "context_timeframe": bundle["context_timeframe"], "setup_timeframe": bundle["setup_timeframe"], "trigger_timeframe": trigger_tf, "cost_profile_id": cost["id"], "perturbation_id": perturbation["id"], "segment_id": segment_id, "regime": segment["regime"], "fold": int(segment["fold"]), "symbol": str(frame.iloc[int(signal["signal_bar_index"])].get("symbol") or ""), "signal_bar_index": int(signal["signal_bar_index"])})
                        trade_rows.append(trade); cell_trades.append(trade)
                cell_rows.append({"bundle_id": bundle_id, "strategy_id": bundle["strategy_id"], "family": bundle["family"], "batch": bundle["batch"], "role": bundle["role"], "context_timeframe": bundle["context_timeframe"], "setup_timeframe": bundle["setup_timeframe"], "trigger_timeframe": trigger_tf, "cost_profile_id": cost["id"], "perturbation_id": perturbation["id"], **helper.aggregate_trades(cell_trades)})
        print(f"A4D2_NATIVE_FAMILY_DISCOVERY_PROGRESS={completed}/{EXPECTED_BUNDLES} CELLS={len(cell_rows)}/{EXPECTED_CELLS} TRADES={len(trade_rows)}")
    if len(cell_rows) != EXPECTED_CELLS: blockers.append(f"DISCOVERY_CELL_COUNT_INVALID:{len(cell_rows)}")
    alias_groups: list[list[str]] = []; fingerprint_groups: dict[frozenset[tuple[str, int]], list[str]] = defaultdict(list)
    for bundle_id, fingerprint in signal_fingerprints.items():
        if fingerprint: fingerprint_groups[frozenset(fingerprint)].append(bundle_id)
    for group in fingerprint_groups.values():
        if len(group) > 1: alias_groups.append(sorted(group))
    if alias_groups: blockers.append(f"CROSS_STRATEGY_SIGNAL_ALIAS_GROUPS:{len(alias_groups)}")
    reference_dd = reference_drawdowns(report, prior_cells); cell_map = {(str(row["bundle_id"]), str(row["cost_profile_id"]), str(row["perturbation_id"])): row for row in cell_rows}; candidates: list[dict[str, Any]] = []
    for bundle in bundles:
        bundle_id = str(bundle["bundle_id"]); severe = cell_map[(bundle_id, *SEVERE_CELL)]; cells = [row for row in cell_rows if row["bundle_id"] == bundle_id]; positive = sum(1 for row in cells if economic_pass(helper, row)); strict_positive = sum(1 for row in cells if strict_pass(helper, row)); ref_dd = reference_dd.get(str(bundle["strategy_id"]), math.inf); severe_dd = helper.finite_metric(severe.get("max_drawdown_pct"), math.inf); dd_nonworsening = severe_dd <= ref_dd if math.isfinite(ref_dd) else True; economic = economic_pass(helper, severe) and positive >= 4 and dd_nonworsening; strict = strict_pass(helper, severe) and strict_positive >= 4 and dd_nonworsening
        candidates.append({"bundle_id": bundle_id, "strategy_id": bundle["strategy_id"], "family": bundle["family"], "batch": bundle["batch"], "role": bundle["role"], "severe_metrics": severe, "positive_stress_cell_count": positive, "strict_positive_stress_cell_count": strict_positive, "reference_max_drawdown_pct": None if not math.isfinite(ref_dd) else ref_dd, "drawdown_nonworsening_vs_reference": dd_nonworsening, "economic_survivor": economic, "strict_s_grade_survivor": strict})
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates: by_strategy[str(row["strategy_id"])].append(row)
    lock_rows: list[dict[str, Any]] = []
    for strategy_id, rows in sorted(by_strategy.items()):
        strict_rows = [row for row in rows if row["strict_s_grade_survivor"]]; economic_rows = [row for row in rows if row["economic_survivor"]]; pool = strict_rows if strict_rows else economic_rows
        pool.sort(key=lambda row: (helper.finite_metric(row["severe_metrics"].get("expectancy_r")), helper.finite_metric(row["severe_metrics"].get("profit_factor")), helper.finite_metric(row["severe_metrics"].get("net_pnl_sum_pct")), -helper.finite_metric(row["severe_metrics"].get("max_drawdown_pct"), math.inf), int(row["strict_positive_stress_cell_count"]), int(row["positive_stress_cell_count"])), reverse=True)
        selected = pool[0] if pool else None; status = "STRICT_S_GRADE_BUNDLE_LOCKED" if selected and selected["strict_s_grade_survivor"] else "PROVISIONAL_ECONOMIC_BUNDLE_LOCKED" if selected else "NO_NATIVE_ARCHITECTURE_SURVIVOR"
        lock_rows.append({"strategy_id": strategy_id, "strict_candidate_count": len(strict_rows), "economic_candidate_count": len(economic_rows), "selected_bundle_id": selected.get("bundle_id") if selected else None, "selected_metrics": selected.get("severe_metrics") if selected else None, "positive_stress_cell_count": selected.get("positive_stress_cell_count") if selected else 0, "strict_positive_stress_cell_count": selected.get("strict_positive_stress_cell_count") if selected else 0, "lock_status": status, "disjoint_validation_allowed": bool(selected and selected["strict_s_grade_survivor"])})
    after = helper.snapshot(canonical_paths + protected); mutation_paths = sorted(path for path in before if before[path] != after[path]); mutation_rows = [{"path": path, "classification": helper.classify_mutation(path, root)} for path in mutation_paths]; critical_mutations = [row for row in mutation_rows if row["classification"] != "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"]
    if critical_mutations: blockers.append(f"CRITICAL_MUTATIONS:{len(critical_mutations)}")
    output = root / OUTPUT_DIR; trade_count, trade_sha = atomic_jsonl(output / "architecture_trade_results_v1.jsonl", trade_rows); cell_count, cell_sha = atomic_jsonl(output / "architecture_cell_results_v1.jsonl", cell_rows); strict_locks = [row for row in lock_rows if row["disjoint_validation_allowed"]]; provisional_locks = [row for row in lock_rows if row["selected_bundle_id"] and not row["disjoint_validation_allowed"]]; state = "PASS_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132" if not blockers else "HOLD_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132"; next_stage = "R7.A4D2_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION" if not blockers and strict_locks else "R7.A4D2_SHORT_NATIVE_ARCHITECTURE_SECOND_GENERATION_REFINEMENT" if not blockers and provisional_locks else "R7.A4D2_SHORT_FAMILY_HYPOTHESIS_RETIRE_OR_REPLACE_AUDIT"
    summary = {"schema": "r7a4d2_short_native_family_architecture_discovery_execution_132_v1", "official_stage": "R7.A4D2_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132", "state": state, "target_commit": args.target_sha, "blocker_count": len(blockers), "blockers": blockers, "strategy_count": len(by_strategy), "architecture_bundle_count": len(bundles), "discovery_segment_count": len(segments), "stress_cell_per_bundle": EXPECTED_STRESS_PER_BUNDLE, "architecture_cell_result_count": cell_count, "architecture_trade_result_count": trade_count, "architecture_cell_results_sha256": cell_sha, "architecture_trade_results_sha256": trade_sha, "signal_alias_groups": alias_groups, "signal_count_by_bundle": {key: len(value) for key, value in sorted(signal_fingerprints.items())}, "candidate_rows": candidates, "strategy_lock_rows": lock_rows, "economic_survivor_count": sum(1 for row in candidates if row["economic_survivor"]), "strict_s_grade_survivor_count": sum(1 for row in candidates if row["strict_s_grade_survivor"]), "strict_strategy_lock_count": len(strict_locks), "provisional_strategy_lock_count": len(provisional_locks), "batch_cell_histogram": dict(sorted(Counter(str(row["batch"]) for row in cell_rows).items())), "family_cell_histogram": dict(sorted(Counter(str(row["family"]) for row in cell_rows).items())), "mutation_rows": mutation_rows, "next_stage": next_stage}
    atomic_json(output / "architecture_discovery_lock_v1.json", summary)
    print("STATE=" + state); print("BLOCKER_COUNT=" + str(len(blockers))); print("STRATEGY_COUNT=" + str(len(by_strategy))); print("ARCHITECTURE_BUNDLE_COUNT=" + str(len(bundles))); print("DISCOVERY_SEGMENT_COUNT=" + str(len(segments))); print("ARCHITECTURE_CELL_RESULT_COUNT=" + str(cell_count)); print("ARCHITECTURE_TRADE_RESULT_COUNT=" + str(trade_count)); print("ECONOMIC_SURVIVOR_COUNT=" + str(summary["economic_survivor_count"])); print("STRICT_S_GRADE_SURVIVOR_COUNT=" + str(summary["strict_s_grade_survivor_count"])); print("STRICT_STRATEGY_LOCK_COUNT=" + str(len(strict_locks))); print("PROVISIONAL_STRATEGY_LOCK_COUNT=" + str(len(provisional_locks))); print("SIGNAL_ALIAS_GROUPS=" + json.dumps(alias_groups)); print("SIGNAL_COUNT_BY_BUNDLE=" + json.dumps(summary["signal_count_by_bundle"], sort_keys=True)); print("STRATEGY_LOCK_ROWS=" + json.dumps(lock_rows, ensure_ascii=False, sort_keys=True)); print("MUTATION_ROWS=" + json.dumps(mutation_rows, ensure_ascii=False, sort_keys=True)); print("LOCK_JSON=" + str(output / "architecture_discovery_lock_v1.json")); print("NEXT_STAGE=" + next_stage); print("BLOCKERS=" + json.dumps(blockers)); print("RC=" + ("0" if not blockers else "2")); return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
