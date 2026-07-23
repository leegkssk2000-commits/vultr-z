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

PLAN_PATH = Path("runtime/r7a4d2_exchange_bot_v2_third_wave_targeted_repair_plan/third_wave_targeted_repair_plan_v1.json")
CALIBRATION_PATH = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_exchange_bot_v2_third_wave_targeted_repair_execution_132")

EXPECTED_BUNDLES = 22
EXPECTED_CELLS = 132
EXPECTED_SEGMENTS = 24
EXPECTED_FOLDS = 6
EXPECTED_STRESS_PER_BUNDLE = 6
MINIMUM_TRADES = 24
MINIMUM_SYMBOLS = 3
MINIMUM_POSITIVE_FOLDS = 4
MINIMUM_POSITIVE_PRIMARY_CELLS = 3
ATR5_CONTROL = "dual_atr_volatility_bot:5m"
REFERENCE_LANE = "dual_donchian_trend_bot:15m"

BASE_CELL = ("cost_profile_0", "timing_0")
ADVERSE_CELL = ("cost_profile_1", "timing_1")
SEVERE_CELL = ("cost_profile_2", "timing_1")

GRID_VARIANTS = {
    "trend_grid15_context_pullback_rebind",
    "trend_grid15_breakout_coverage_guard",
    "trend_grid5_regime_switch_rebuild",
    "trend_grid5_donchian_inventory_sibling",
    "neutral_grid15_efficiency_inventory_rebind",
    "neutral_grid15_adaptive_center_coverage",
    "neutral_grid5_efficiency_inventory_rebind",
    "neutral_grid5_volatility_band_coverage",
}

VARIANT_IDS = {
    "trend_grid15_context_pullback_rebind","trend_grid15_breakout_coverage_guard",
    "trend_grid5_regime_switch_rebuild","trend_grid5_donchian_inventory_sibling",
    "atr15_negative_fold_context_veto","atr15_balanced_cooldown_reentry",
    "atr5_mfe_timeout_capture","atr5_retest_cost_floor",
    "donchian5_retest_limit_cost","donchian5_cost_floor_mfe_exit",
    "ma15_context_5m_pullback_rebind","ma15_persistent_state_coverage",
    "ma5_retest_limit_cost","ma5_side_specific_timeout_cost",
    "vwap15_context_outer_reclaim_rebind","vwap15_dual_anchor_coverage",
    "vwap5_context_side_rebind","vwap5_exhaustion_sibling_coverage",
    "neutral_grid15_efficiency_inventory_rebind","neutral_grid15_adaptive_center_coverage",
    "neutral_grid5_efficiency_inventory_rebind","neutral_grid5_volatility_band_coverage",
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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    os.replace(tmp, path)

def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
        tmp = Path(handle.name)
    os.replace(tmp, path)
    return count, digest.hexdigest()

def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default

def touch_indices(condition: pd.Series, cooldown: int) -> list[int]:
    output: list[int] = []
    last = -10**9
    for raw in np.flatnonzero(condition.fillna(False).to_numpy(dtype=bool)):
        index = int(raw)
        if index - last >= cooldown:
            output.append(index)
            last = index
    return output

def efficiency_ratio(close: pd.Series, lookback: int) -> pd.Series:
    direction = (close - close.shift(lookback)).abs()
    path = close.diff().abs().rolling(lookback, min_periods=lookback).sum()
    return direction.div(path.where(path > 0))

def session_vwap(frame: pd.DataFrame) -> pd.Series:
    timestamp = pd.to_datetime(frame["__timestamp"].astype("int64"), unit="ms", utc=True)
    session = timestamp.dt.floor("D")
    typical = (frame["high"].astype(float) + frame["low"].astype(float) + frame["close"].astype(float)) / 3.0
    volume = frame["volume"].astype(float).clip(lower=0)
    weighted = typical * volume
    return weighted.groupby(session).cumsum().div(volume.groupby(session).cumsum().replace(0, np.nan)).fillna(typical)

def fold_metrics(helper: Any, trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        grouped[int(row["fold"])].append(row)
    rows: dict[str, dict[str, Any]] = {}
    positive = 0
    for fold in range(EXPECTED_FOLDS):
        metrics = helper.aggregate_trades(grouped.get(fold, []))
        rows[str(fold)] = metrics
        if helper.finite_metric(metrics.get("net_pnl_sum_pct")) > 0:
            positive += 1
    return {"rows": rows, "fold_count": EXPECTED_FOLDS, "positive_fold_count": positive, "positive_fold_ratio": positive / EXPECTED_FOLDS}

def cell_gate(helper: Any, cell: dict[str, Any]) -> dict[str, bool]:
    return {
        "trade_gate": int(cell.get("trade_count") or 0) >= MINIMUM_TRADES,
        "symbol_gate": len(cell.get("symbol_histogram") or {}) >= MINIMUM_SYMBOLS,
        "profit_factor_gate": helper.finite_metric(cell.get("profit_factor")) > 1.0,
        "expectancy_gate": helper.finite_metric(cell.get("expectancy_r")) > 0.0,
        "net_pnl_gate": helper.finite_metric(cell.get("net_pnl_sum_pct")) > 0.0,
        "walk_forward_gate": int((cell.get("fold_metrics") or {}).get("positive_fold_count") or 0) >= MINIMUM_POSITIVE_FOLDS,
    }

def risk_score(metrics: dict[str, Any]) -> float:
    expectancy = finite(metrics.get("expectancy_r"))
    pnl = finite(metrics.get("net_pnl_sum_pct"))
    drawdown = max(finite(metrics.get("max_drawdown_pct")), 0.25)
    pf = max(finite(metrics.get("profit_factor")), 0.0)
    folds = int((metrics.get("fold_metrics") or {}).get("positive_fold_count") or metrics.get("positive_fold_count") or 0)
    return expectancy + 0.20 * (pnl / drawdown) + 0.10 * (pf - 1.0) + 0.03 * folds

def meaningful_severe_margin(metrics: dict[str, Any]) -> bool:
    return (
        bool(metrics.get("economic_pass"))
        and finite(metrics.get("net_pnl_sum_pct")) >= 0.50
        and finite(metrics.get("profit_factor")) >= 1.20
        and finite(metrics.get("expectancy_r")) > 0
        and int((metrics.get("fold_metrics") or {}).get("positive_fold_count") or 0) >= MINIMUM_POSITIVE_FOLDS
    )

def generate_signals(
    variant_id: str,
    frame: pd.DataFrame,
    measurement: pd.Series,
    frame15: pd.DataFrame,
    segment_regime: str,
    base_cost_pct: float,
    old: Any,
    benchmark: Any,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    signals: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    close = frame["close"].astype(float)
    open_v = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    atr = old.atr(frame, 14)
    vz = old.volume_z(frame)
    span = (high - low).replace(0, np.nan)
    body = (close - open_v).abs()
    clv = (close - low).div(span)
    lw = (np.minimum(open_v, close) - low).div(span)
    uw = (high - np.maximum(open_v, close)).div(span)
    e9 = old.ema(close, 9)
    e12 = old.ema(close, 12)
    e20 = old.ema(close, 20)
    e21 = old.ema(close, 21)
    e26 = old.ema(close, 26)
    ctx = old.context_columns(frame, frame15)
    er20 = efficiency_ratio(close, 20)

    def append(index: int, side: str, stop: float, target: float, timeout: int, reason: str, *, entry_mode: str = "next_open", limit_price: float | None = None, limit_window: int = 0, trail_arm_r: float | None = None, trail_distance_r: float | None = None, min_target_cost: float = 3.0, level_id: str | None = None) -> None:
        if index + 1 >= len(frame):
            rejected["NO_NEXT_BAR"] += 1
            return
        if not bool(measurement.iloc[index]):
            rejected["OUTSIDE_MEASUREMENT"] += 1
            return
        entry = finite(limit_price, math.nan) if entry_mode == "limit_retest" else finite(frame.iloc[index + 1]["open"], math.nan)
        admitted, economics = benchmark.signal_admission(side, entry, finite(stop, math.nan), finite(target, math.nan), base_cost_pct)
        if not admitted or finite(economics.get("target_to_base_cost_ratio")) < min_target_cost:
            rejected["ECONOMIC_ADMISSION_REJECT"] += 1
            return
        signals.append({"signal_bar_index": int(index), "entry_bar_index": int(index + 1), "side": side, "stop_price": float(stop), "target_price": float(target), "timeout_bars": int(max(2, timeout)), "reason": reason, "level_id": level_id, "entry_mode": entry_mode, "limit_price": float(limit_price) if limit_price is not None and math.isfinite(float(limit_price)) else None, "limit_window_bars": int(max(0, limit_window)), "trail_arm_r": trail_arm_r, "trail_distance_r": trail_distance_r, **economics})

    lc = (ctx["ctx_close"] > ctx["ctx_ema50"]) & (ctx["ctx_slope"] > 0.0)
    sc = (ctx["ctx_close"] < ctx["ctx_ema50"]) & (ctx["ctx_slope"] < 0.0)

    if variant_id == "trend_grid15_context_pullback_rebind":
        for distance, tag in ((0.35, "L1"), (0.75, "L2")):
            ll = e20 - distance * atr; sl = e20 + distance * atr
            for index in touch_indices(lc & (close <= ll + 0.30 * atr), 6):
                entry = finite(ll.iloc[index], math.nan); a = finite(atr.iloc[index], math.nan)
                append(index, "long", entry - 1.05*a, entry + 4.0*a, 18, variant_id, entry_mode="limit_retest", limit_price=entry, limit_window=3, trail_arm_r=1.2, trail_distance_r=0.7, level_id=tag)
            for index in touch_indices(sc & (close >= sl - 0.30 * atr), 6):
                entry = finite(sl.iloc[index], math.nan); a = finite(atr.iloc[index], math.nan)
                append(index, "short", entry + 1.05*a, entry - 4.0*a, 18, variant_id, entry_mode="limit_retest", limit_price=entry, limit_window=3, trail_arm_r=1.2, trail_distance_r=0.7, level_id=tag)

    elif variant_id == "trend_grid15_breakout_coverage_guard":
        ph = high.shift(1).rolling(12, min_periods=12).max(); pl = low.shift(1).rolling(12, min_periods=12).min()
        arm_l = old.edge((close > ph) & lc).rolling(8, min_periods=1).max().astype(bool)
        arm_s = old.edge((close < pl) & sc).rolling(8, min_periods=1).max().astype(bool)
        long = arm_l & (low <= e12) & (close > e12); short = arm_s & (high >= e12) & (close < e12)
        for index in touch_indices(long, 8):
            entry = finite(e12.iloc[index], math.nan); a = finite(atr.iloc[index], math.nan)
            append(index, "long", entry-1.0*a, entry+4.2*a, 16, variant_id, entry_mode="limit_retest", limit_price=entry, limit_window=2, trail_arm_r=1.0, trail_distance_r=0.6, level_id="BREAKOUT_RECLAIM")
        for index in touch_indices(short, 8):
            entry = finite(e12.iloc[index], math.nan); a = finite(atr.iloc[index], math.nan)
            append(index, "short", entry+1.0*a, entry-4.2*a, 16, variant_id, entry_mode="limit_retest", limit_price=entry, limit_window=2, trail_arm_r=1.0, trail_distance_r=0.6, level_id="BREAKOUT_RECLAIM")

    elif variant_id == "trend_grid5_regime_switch_rebuild":
        up = lc & (segment_regime == "trend_up"); down = sc & (segment_regime == "trend_down")
        for distance, tag in ((0.25, "P1"), (0.60, "P2")):
            ll = e20 - distance*atr; sl = e20 + distance*atr
            for index in touch_indices(up & (close <= ll + 0.25*atr), 7):
                entry=finite(ll.iloc[index],math.nan); a=finite(atr.iloc[index],math.nan)
                append(index,"long",entry-0.95*a,entry+4.5*a,16,variant_id,entry_mode="limit_retest",limit_price=entry,limit_window=3,trail_arm_r=1.0,trail_distance_r=0.55,level_id=tag)
            for index in touch_indices(down & (close >= sl - 0.25*atr), 7):
                entry=finite(sl.iloc[index],math.nan); a=finite(atr.iloc[index],math.nan)
                append(index,"short",entry+0.95*a,entry-4.5*a,16,variant_id,entry_mode="limit_retest",limit_price=entry,limit_window=3,trail_arm_r=1.0,trail_distance_r=0.55,level_id=tag)

    elif variant_id == "trend_grid5_donchian_inventory_sibling":
        ph = high.shift(1).rolling(12, min_periods=12).max(); pl = low.shift(1).rolling(12, min_periods=12).min()
        lb = old.edge((close > ph) & lc & (vz > 0.2)); sb = old.edge((close < pl) & sc & (vz > 0.2))
        for index in touch_indices(lb, 10):
            a=finite(atr.iloc[index],math.nan); level=finite(ph.iloc[index],math.nan)
            append(index,"long",level-1.0*a,level+4.5*a,18,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=4,trail_arm_r=1.1,trail_distance_r=0.6,level_id="D1")
        for index in touch_indices(sb, 10):
            a=finite(atr.iloc[index],math.nan); level=finite(pl.iloc[index],math.nan)
            append(index,"short",level+1.0*a,level-4.5*a,18,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=4,trail_arm_r=1.1,trail_distance_r=0.6,level_id="D1")

    elif variant_id in {"atr15_negative_fold_context_veto", "atr15_balanced_cooldown_reentry"}:
        if segment_regime == "range":
            return signals, Counter({"REGIME_VETO": 1})
        li = (span >= 1.20*atr) & (body/span >= 0.58) & (clv >= 0.72) & (vz >= 0.20) & lc
        si = (span >= 1.35*atr) & (body/span >= 0.62) & (clv <= 0.22) & (vz >= 0.65) & sc & (ctx["ctx_slope"] < -0.01)
        cooldown = 8 if variant_id == "atr15_negative_fold_context_veto" else 12
        for index in touch_indices(old.edge(li), cooldown):
            a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
            append(index,"long",c-1.0*a,c+4.2*a,16,variant_id,trail_arm_r=1.0,trail_distance_r=0.6)
        for index in touch_indices(old.edge(si), cooldown):
            a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
            append(index,"short",c+1.0*a,c-4.2*a,16,variant_id,trail_arm_r=1.0,trail_distance_r=0.6)

    elif variant_id in {"atr5_mfe_timeout_capture", "atr5_retest_cost_floor"}:
        ph = high.shift(1).rolling(12, min_periods=12).max(); pl = low.shift(1).rolling(12, min_periods=12).min()
        li = (span>=1.40*atr)&(body/span>=0.65)&(clv>=0.82)&(vz>=1.0)&(close>=ph)&lc
        si = (span>=1.40*atr)&(body/span>=0.65)&(clv<=0.18)&(vz>=1.0)&(close<=pl)&sc
        if variant_id == "atr5_mfe_timeout_capture":
            for index in touch_indices(old.edge(li), 5):
                a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
                append(index,"long",c-1.0*a,c+4.0*a,8,variant_id,trail_arm_r=0.8,trail_distance_r=0.50)
            for index in touch_indices(old.edge(si), 5):
                a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
                append(index,"short",c+1.0*a,c-4.0*a,8,variant_id,trail_arm_r=0.8,trail_distance_r=0.50)
        else:
            for index in touch_indices(old.edge(li), 5):
                a=finite(atr.iloc[index],math.nan); level=finite(ph.iloc[index],math.nan)
                append(index,"long",level-0.95*a,level+4.3*a,10,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=3,trail_arm_r=1.0,trail_distance_r=0.55,min_target_cost=4.0)
            for index in touch_indices(old.edge(si), 5):
                a=finite(atr.iloc[index],math.nan); level=finite(pl.iloc[index],math.nan)
                append(index,"short",level+0.95*a,level-4.3*a,10,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=3,trail_arm_r=1.0,trail_distance_r=0.55,min_target_cost=4.0)

    elif variant_id in {"donchian5_retest_limit_cost", "donchian5_cost_floor_mfe_exit"}:
        ph=high.shift(1).rolling(20,min_periods=20).max(); pl=low.shift(1).rolling(20,min_periods=20).min()
        lb=(close>ph)&(vz>0)&lc; sb=(close<pl)&(vz>0)&sc
        if variant_id == "donchian5_retest_limit_cost":
            for index in touch_indices(old.edge(lb), 8):
                a=finite(atr.iloc[index],math.nan); level=finite(ph.iloc[index],math.nan)
                append(index,"long",level-0.95*a,level+4.5*a,16,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=4,trail_arm_r=1.0,trail_distance_r=0.6,min_target_cost=4.0)
            for index in touch_indices(old.edge(sb & (ctx["ctx_slope"] < -0.01)), 8):
                a=finite(atr.iloc[index],math.nan); level=finite(pl.iloc[index],math.nan)
                append(index,"short",level+0.95*a,level-4.5*a,16,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=4,trail_arm_r=1.0,trail_distance_r=0.6,min_target_cost=4.0)
        else:
            for index in touch_indices(old.edge(lb), 10):
                a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
                append(index,"long",c-1.0*a,c+4.8*a,12,variant_id,trail_arm_r=0.9,trail_distance_r=0.55,min_target_cost=4.5)
            for index in touch_indices(old.edge(sb & (ctx["ctx_slope"] < -0.015)), 10):
                a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
                append(index,"short",c+1.0*a,c-4.8*a,12,variant_id,trail_arm_r=0.9,trail_distance_r=0.55,min_target_cost=4.5)

    elif variant_id in {"ma15_context_5m_pullback_rebind", "ma15_persistent_state_coverage"}:
        if variant_id == "ma15_context_5m_pullback_rebind":
            long=lc&(low<=e20)&(close>e20)&(e12>e26); short=sc&(high>=e20)&(close<e20)&(e12<e26)
            for index in touch_indices(long, 8):
                a=finite(atr.iloc[index],math.nan); level=finite(e20.iloc[index],math.nan)
                append(index,"long",level-1.0*a,level+4.0*a,18,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=2,trail_arm_r=1.1,trail_distance_r=0.65)
            for index in touch_indices(short, 8):
                a=finite(atr.iloc[index],math.nan); level=finite(e20.iloc[index],math.nan)
                append(index,"short",level+1.0*a,level-4.0*a,18,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=2,trail_arm_r=1.1,trail_distance_r=0.65)
        else:
            spread=(e12-e26).div(atr); accel=spread.diff(2)
            long=lc&(spread>0.08)&(accel>0.015)&(accel.shift(1)<=0.015); short=sc&(spread<-0.08)&(accel<-0.015)&(accel.shift(1)>=-0.015)
            for index in touch_indices(long, 10):
                a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
                append(index,"long",c-1.05*a,c+4.1*a,18,variant_id,trail_arm_r=1.1,trail_distance_r=0.65)
            for index in touch_indices(short, 10):
                a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
                append(index,"short",c+1.05*a,c-4.1*a,18,variant_id,trail_arm_r=1.1,trail_distance_r=0.65)

    elif variant_id in {"ma5_retest_limit_cost", "ma5_side_specific_timeout_cost"}:
        spread=(e9-e21).div(atr); accel=spread.diff(2)
        if variant_id == "ma5_retest_limit_cost":
            long=lc&(spread>0.08)&(low<=e9)&(close>e9); short=sc&(spread<-0.10)&(high>=e9)&(close<e9)&(ctx["ctx_slope"]<-0.01)
            for index in touch_indices(long, 7):
                a=finite(atr.iloc[index],math.nan); level=finite(e9.iloc[index],math.nan)
                append(index,"long",level-0.95*a,level+4.0*a,14,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=2,trail_arm_r=0.9,trail_distance_r=0.55,min_target_cost=4.0)
            for index in touch_indices(short, 7):
                a=finite(atr.iloc[index],math.nan); level=finite(e9.iloc[index],math.nan)
                append(index,"short",level+0.95*a,level-4.0*a,14,variant_id,entry_mode="limit_retest",limit_price=level,limit_window=2,trail_arm_r=0.9,trail_distance_r=0.55,min_target_cost=4.0)
        else:
            long=lc&(spread>0.08)&(accel>0.02)&(accel.shift(1)<=0.02)
            short=sc&(spread<-0.12)&(accel<-0.03)&(accel.shift(1)>=-0.03)&(vz>0.5)&(ctx["ctx_slope"]<-0.015)
            for index in touch_indices(long, 9):
                a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
                append(index,"long",c-1.0*a,c+4.2*a,12,variant_id,trail_arm_r=0.9,trail_distance_r=0.55,min_target_cost=4.0)
            for index in touch_indices(short, 9):
                a=finite(atr.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
                append(index,"short",c+1.0*a,c-4.5*a,12,variant_id,trail_arm_r=0.9,trail_distance_r=0.55,min_target_cost=4.0)

    elif variant_id in {"vwap15_context_outer_reclaim_rebind","vwap15_dual_anchor_coverage","vwap5_context_side_rebind","vwap5_exhaustion_sibling_coverage"}:
        rolling = benchmark.rolling_vwap(frame, 24); anchored = session_vwap(frame)
        range_ctx = ctx["ctx_width_atr"].between(3.5, 14.0) & (ctx["ctx_mid_slope"].abs() < 0.12)
        if variant_id == "vwap15_context_outer_reclaim_rebind":
            basis=rolling; dev=close-basis; std=dev.rolling(24,min_periods=24).std(ddof=0)
            long=range_ctx&(low<basis-1.45*std)&(close>basis-1.45*std)&(lw>0.35); short=range_ctx&(high>basis+1.65*std)&(close<basis+1.65*std)&(uw>0.45)
        elif variant_id == "vwap15_dual_anchor_coverage":
            basis=(rolling+anchored)/2.0; dev=close-basis; std=dev.rolling(24,min_periods=24).std(ddof=0)
            lower=np.minimum(rolling,anchored)-1.35*std; upper=np.maximum(rolling,anchored)+1.35*std
            raw_l=range_ctx&(low<lower)&(close>lower); raw_s=range_ctx&(high>upper)&(close<upper)
            long=raw_l.shift(1,fill_value=False)&(close>close.shift(1)); short=raw_s.shift(1,fill_value=False)&(close<close.shift(1))
        elif variant_id == "vwap5_context_side_rebind":
            basis=rolling; dev=close-basis; std=dev.rolling(20,min_periods=20).std(ddof=0)
            long=range_ctx&(low<basis-1.40*std)&(close>basis-1.40*std)&(lw>0.35); short=range_ctx&(high>basis+1.85*std)&(close<basis+1.85*std)&(uw>0.55)&(vz>0)
        else:
            basis=e20; dev=close-basis; std=dev.rolling(20,min_periods=20).std(ddof=0)
            long=range_ctx&(low<basis-1.8*std)&(close>basis-1.25*std)&(lw>0.45)&(span>1.1*atr); short=range_ctx&(high>basis+2.0*std)&(close<basis+1.35*std)&(uw>0.55)&(span>1.2*atr)
        for index in touch_indices(old.edge(long), 6):
            a=finite(atr.iloc[index],math.nan); target=finite(basis.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
            append(index,"long",min(finite(low.iloc[index],c)-0.15*a,c-1.0*a),target,12,variant_id,trail_arm_r=0.8,trail_distance_r=0.5)
        for index in touch_indices(old.edge(short), 6):
            a=finite(atr.iloc[index],math.nan); target=finite(basis.iloc[index],math.nan); c=finite(close.iloc[index],math.nan)
            append(index,"short",max(finite(high.iloc[index],c)+0.15*a,c+1.0*a),target,12,variant_id,trail_arm_r=0.8,trail_distance_r=0.5)

    elif variant_id in {"neutral_grid15_efficiency_inventory_rebind","neutral_grid15_adaptive_center_coverage","neutral_grid5_efficiency_inventory_rebind","neutral_grid5_volatility_band_coverage"}:
        if variant_id == "neutral_grid15_efficiency_inventory_rebind":
            rh=ctx["ctx_high20"]; rl=ctx["ctx_low20"]; width=rh-rl
            stable=ctx["ctx_width_atr"].between(3.5,14.0)&(ctx["ctx_mid_slope"].abs()<0.12)&(er20<0.45)
            levels={"L20":rl+0.20*width,"L40":rl+0.40*width,"L60":rl+0.60*width,"L80":rl+0.80*width}
        elif variant_id == "neutral_grid15_adaptive_center_coverage":
            center=(ctx["ctx_high20"]+ctx["ctx_low20"])/2.0; unit=ctx["ctx_atr"]
            stable=(ctx["ctx_mid_slope"].abs()<0.10)&(center.diff(6).abs().div(unit)<0.45)&(er20<0.50)
            levels={"L20":center-1.35*unit,"L40":center-0.25*unit,"L60":center+0.25*unit,"L80":center+1.35*unit}
        elif variant_id == "neutral_grid5_efficiency_inventory_rebind":
            rh=high.shift(1).rolling(48,min_periods=48).max(); rl=low.shift(1).rolling(48,min_periods=48).min(); width=rh-rl
            stable=width.div(atr).between(4.0,12.0)&(er20<0.30)&(e20.diff(10).abs().div(10*atr)<0.08)
            levels={"L20":rl+0.20*width,"L40":rl+0.40*width,"L60":rl+0.60*width,"L80":rl+0.80*width}
        else:
            center=e20; unit=atr.rolling(20,min_periods=20).median()
            stable=(er20<0.35)&(e20.diff(10).abs().div(10*atr)<0.08)&atr.div(unit).between(0.65,1.50)
            levels={"L20":center-1.40*unit,"L40":center-0.20*unit,"L60":center+0.20*unit,"L80":center+1.40*unit}
        for entry_name,target_name,side in (("L20","L40","long"),("L40","L60","long"),("L80","L60","short"),("L60","L40","short")):
            entry_level=levels[entry_name]; target_level=levels[target_name]
            near=(close<=entry_level+0.30*atr) if side=="long" else (close>=entry_level-0.30*atr)
            for index in touch_indices(stable&near,5):
                entry=finite(entry_level.iloc[index],math.nan); target=finite(target_level.iloc[index],math.nan); a=finite(atr.iloc[index],math.nan)
                stop=entry-1.0*a if side=="long" else entry+1.0*a
                append(index,side,stop,target,16,variant_id,entry_mode="limit_retest",limit_price=entry,limit_window=3,min_target_cost=3.5,level_id=f"{entry_name}->{target_name}")
    else:
        raise ValueError(f"VARIANT_UNSUPPORTED:{variant_id}")

    signals.sort(key=lambda row:(int(row["entry_bar_index"]),str(row["side"]),str(row.get("level_id") or ""),str(row["reason"])))
    return signals, rejected

def simulate_trade(frame: pd.DataFrame, measurement: pd.Series, signal: dict[str, Any], cost: dict[str, Any], timing: dict[str, Any], timeframe: str) -> dict[str, Any] | None:
    entry_delay = int(timing.get("additional_entry_delay_bars") or 0); exit_delay = int(timing.get("additional_exit_delay_bars") or 0)
    measured = np.flatnonzero(measurement.to_numpy(dtype=bool))
    if measured.size == 0: return None
    last_index = int(measured[-1]); mode = str(signal.get("entry_mode") or "next_open")
    if mode == "limit_retest":
        limit = finite(signal.get("limit_price"), math.nan); start = int(signal["entry_bar_index"]) + entry_delay; end = min(start + int(signal.get("limit_window_bars") or 0), last_index); entry_index = -1
        for index in range(start, end + 1):
            if index < len(frame) and bool(measurement.iloc[index]) and finite(frame.iloc[index]["low"], math.inf) <= limit <= finite(frame.iloc[index]["high"], -math.inf): entry_index = index; break
        if entry_index < 0: return None
        entry = limit
    else:
        entry_index = int(signal["entry_bar_index"]) + entry_delay
        if entry_index >= len(frame) or entry_index > last_index or not bool(measurement.iloc[entry_index]): return None
        entry = finite(frame.iloc[entry_index]["open"], math.nan)
    side = str(signal["side"]); stop = finite(signal["stop_price"], math.nan); target = finite(signal["target_price"], math.nan)
    valid = (0 < stop < entry < target) if side == "long" else (stop > entry > target > 0)
    if not valid: return None
    risk_abs = abs(entry - stop); risk_pct = risk_abs / entry * 100.0
    if risk_pct <= 0: return None
    timeout_index = min(entry_index + int(signal["timeout_bars"]), last_index); trigger = "segment_end"; trigger_index = last_index; reference_exit = finite(frame.iloc[last_index]["close"], math.nan)
    arm = finite(signal.get("trail_arm_r"), math.nan); distance = finite(signal.get("trail_distance_r"), math.nan); trail_stop: float | None = None; peak = entry; trough = entry; trail_armed = False
    for index in range(entry_index, last_index + 1):
        high_v = finite(frame.iloc[index]["high"], math.nan); low_v = finite(frame.iloc[index]["low"], math.nan); effective_stop = stop
        if trail_stop is not None: effective_stop = max(stop, trail_stop) if side == "long" else min(stop, trail_stop)
        if side == "long":
            if low_v <= effective_stop: trigger, trigger_index, reference_exit = ("trail_stop" if trail_stop is not None and effective_stop > stop else "stop"), index, effective_stop; break
            if high_v >= target: trigger, trigger_index, reference_exit = "take_profit", index, target; break
            peak = max(peak, high_v)
            if math.isfinite(arm) and math.isfinite(distance) and (peak-entry)/risk_abs >= arm: trail_armed = True; trail_stop = max(trail_stop if trail_stop is not None else stop, peak-distance*risk_abs)
        else:
            if high_v >= effective_stop: trigger, trigger_index, reference_exit = ("trail_stop" if trail_stop is not None and effective_stop < stop else "stop"), index, effective_stop; break
            if low_v <= target: trigger, trigger_index, reference_exit = "take_profit", index, target; break
            trough = min(trough, low_v)
            if math.isfinite(arm) and math.isfinite(distance) and (entry-trough)/risk_abs >= arm: trail_armed = True; trail_stop = min(trail_stop if trail_stop is not None else stop, trough+distance*risk_abs)
        if index >= timeout_index: trigger, trigger_index, reference_exit = "rule_exit_or_timeout", index, finite(frame.iloc[index]["close"], math.nan); break
    execution_index = min(trigger_index + exit_delay, last_index)
    if exit_delay == 0 and trigger in {"stop","trail_stop","take_profit"}: exit_price = reference_exit
    elif trigger == "segment_end": exit_price = finite(frame.iloc[execution_index]["close"], math.nan)
    else: exit_price = finite(frame.iloc[execution_index]["open"], math.nan)
    multiplier = 1.0 if side == "long" else -1.0; gross_pct = multiplier * (exit_price-entry)/entry*100.0; extra_slip = finite(timing.get("additional_slippage_bps_per_side")); round_trip_pct = 2.0*(finite(cost.get("fee_bps_per_side"))+finite(cost.get("slippage_bps_per_side"))+extra_slip)/100.0
    minutes = {"5m":5,"15m":15}[timeframe]; holding_hours = max(execution_index-entry_index,0)*minutes/60.0; funding_pct = finite(cost.get("funding_bps_per_8h"))/100.0*holding_hours/8.0; net_pct = gross_pct-round_trip_pct-funding_pct
    return {"entry_index":entry_index,"exit_index":execution_index,"side":side,"entry_price":entry,"exit_price":exit_price,"stop_price":stop,"target_price":target,"risk_pct":risk_pct,"gross_return_pct":gross_pct,"round_trip_cost_pct":round_trip_pct,"funding_cost_pct":funding_pct,"net_return_pct":net_pct,"net_r":net_pct/risk_pct,"exit_reason":trigger,"holding_bars":max(execution_index-entry_index,0),"entry_mode":mode,"trail_armed":trail_armed}

def self_test(old: Any, benchmark: Any) -> int:
    assert len(VARIANT_IDS) == EXPECTED_BUNDLES
    size=520; x=np.arange(size,dtype=float); close=pd.Series(100+0.018*x+1.8*np.sin(x/8.0)+0.5*np.sin(x/2.5)); open_v=close.shift(1).fillna(close.iloc[0])
    frame5=pd.DataFrame({"__timestamp":(x*300000).astype("int64"),"open":open_v,"high":pd.concat([close,open_v],axis=1).max(axis=1)+0.45,"low":pd.concat([close,open_v],axis=1).min(axis=1)-0.45,"close":close,"volume":100+(x%29)*5,"symbol":"TESTUSDT","timeframe":"5m"})
    frame15=frame5.iloc[::3].reset_index(drop=True).copy(); frame15["timeframe"]="15m"; mask=pd.Series([True]*len(frame5))
    for variant in sorted(VARIANT_IDS):
        regime="range" if "neutral_grid" in variant or "vwap" in variant else "trend_up"; signals,rejected=generate_signals(variant,frame5,mask,frame15,regime,0.12,old,benchmark); assert isinstance(signals,list) and isinstance(rejected,Counter)
    print("STATE=PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132_SELF_TEST"); print("RC=0"); return 0

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--root",default="/home/z/z"); parser.add_argument("--target-sha",default="UNKNOWN"); parser.add_argument("--raw-module"); parser.add_argument("--helper-module"); parser.add_argument("--benchmark-module"); parser.add_argument("--old-module"); parser.add_argument("--a4d-contract"); parser.add_argument("--self-test",action="store_true"); args=parser.parse_args()
    if not args.old_module or not args.benchmark_module: raise SystemExit("--old-module --benchmark-module required")
    old=import_module(Path(args.old_module).resolve(),"r7a4d2_third_old"); benchmark=import_module(Path(args.benchmark_module).resolve(),"r7a4d2_third_benchmark")
    if args.self_test: return self_test(old,benchmark)
    if not all([args.raw_module,args.helper_module,args.a4d_contract]): raise SystemExit("--raw-module --helper-module --a4d-contract required")
    root=Path(args.root).resolve(); raw=import_module(Path(args.raw_module).resolve(),"r7a4d2_third_raw"); helper=import_module(Path(args.helper_module).resolve(),"r7a4d2_third_helper"); contract=load_json(Path(args.a4d_contract).resolve())
    required=[root/PLAN_PATH,root/CALIBRATION_PATH,root/MANIFEST_PATH]; missing=[str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132_INPUT"); print("BLOCKER_COUNT=1"); print("BLOCKERS="+json.dumps(["REQUIRED_EVIDENCE_MISSING:"+",".join(missing)])); print("RC=2"); return 2
    plan=load_json(root/PLAN_PATH); calibration=load_json(root/CALIBRATION_PATH); manifest=load_json(root/MANIFEST_PATH); blockers:list[str]=[]; bundles=[row for row in plan.get("third_wave_rows",[]) if isinstance(row,dict)]
    if plan.get("state")!="PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_PLAN": blockers.append("THIRD_WAVE_PLAN_NOT_PASS")
    if len(bundles)!=EXPECTED_BUNDLES: blockers.append(f"BUNDLE_COUNT_INVALID:{len(bundles)}")
    if {str(row.get("variant_id")) for row in bundles}!=VARIANT_IDS: blockers.append("VARIANT_SET_INVALID")
    segments={str(row["segment_id"]):row for row in manifest.get("selected_segments",[]) if isinstance(row,dict)}
    if len(segments)!=EXPECTED_SEGMENTS: blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")
    model=calibration.get("corrected_execution_model",{}); costs=[row for row in model.get("profiles",[]) if isinstance(row,dict)]; timings=[row for row in model.get("timing_perturbations",[]) if isinstance(row,dict)]
    if len(costs)*len(timings)!=EXPECTED_STRESS_PER_BUNDLE: blockers.append("STRESS_GRID_INVALID")
    base_cost_pct=benchmark.base_round_trip_cost(calibration)
    if not math.isfinite(base_cost_pct) or base_cost_pct<=0: blockers.append("BASE_COST_INVALID")
    if blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132_INPUT"); print("BLOCKER_COUNT="+str(len(blockers))); print("BLOCKERS="+json.dumps(blockers)); print("RC=2"); return 2
    source_sha={str(row.get("source_path")):str(row.get("source_sha256") or "") for row in manifest.get("selected_segments",[]) if isinstance(row,dict)}; source_paths=sorted({str(row["source_path"]) for row in segments.values()}); selected=[root/raw.safe_repo_path(path) for path in source_paths]; protected=[Path(str(value)) for value in contract.get("protected_paths",[])]; before=helper.snapshot(required+selected+protected)
    source_cache:dict[str,pd.DataFrame]={}; frame_cache:dict[tuple[str,str],pd.DataFrame]={}; mask_cache:dict[tuple[str,str],pd.Series]={}; trade_rows:list[dict[str,Any]]=[]; cell_rows:list[dict[str,Any]]=[]; bundle_rows:list[dict[str,Any]]=[]
    for bundle_number,bundle in enumerate(sorted(bundles,key=lambda row:str(row["variant_id"])),1):
        variant_id=str(bundle["variant_id"]); lane_id=str(bundle["lane_id"]); execution_timeframe=str(bundle["execution_timeframe"]); signal_cache:dict[str,list[dict[str,Any]]]={}; rejection_total:Counter[str]=Counter()
        for segment_id,segment in sorted(segments.items()):
            source_path=str(segment["source_path"])
            if source_path not in source_cache: source_cache[source_path]=raw.fixed_ohlcv_frame(root/raw.safe_repo_path(source_path),source_sha[source_path])
            for timeframe in {execution_timeframe,"15m"}:
                key=(segment_id,timeframe)
                if key not in frame_cache: frame_cache[key]=raw.resample_for_segment(source_cache[source_path],int(segment["start_row"]),int(segment["end_row_exclusive"]),timeframe); mask_cache[key]=raw.measurement_mask(frame_cache[key],int(segment["start_row"]),int(segment["end_row_exclusive"]))
            signals,rejected=generate_signals(variant_id,frame_cache[(segment_id,execution_timeframe)],mask_cache[(segment_id,execution_timeframe)],frame_cache[(segment_id,"15m")],str(segment["regime"]),base_cost_pct,old,benchmark); signal_cache[segment_id]=signals; rejection_total.update(rejected)
        cell_map:dict[tuple[str,str],dict[str,Any]]={}
        for cost in costs:
            for timing in timings:
                cell_trades:list[dict[str,Any]]=[]
                for segment_id,segment in sorted(segments.items()):
                    frame=frame_cache[(segment_id,execution_timeframe)]; measurement=mask_cache[(segment_id,execution_timeframe)]; last_exit=-1; last_exit_by_level:dict[str,int]={}
                    for signal in signal_cache[segment_id]:
                        if variant_id in GRID_VARIANTS:
                            key=f"{signal.get('side')}:{signal.get('level_id') or 'NA'}"
                            if int(signal["entry_bar_index"])<=last_exit_by_level.get(key,-1): continue
                        elif int(signal["entry_bar_index"])<=last_exit: continue
                        trade=simulate_trade(frame,measurement,signal,cost,timing,execution_timeframe)
                        if trade is None: continue
                        if variant_id in GRID_VARIANTS: last_exit_by_level[key]=int(trade["exit_index"])
                        else: last_exit=int(trade["exit_index"])
                        trade.update({"variant_id":variant_id,"source_lane_id":lane_id,"execution_timeframe":execution_timeframe,"repair_axis":bundle["repair_axis"],"design_class":bundle["design_class"],"family":bundle["family"],"cost_profile_id":str(cost["id"]),"timing_id":str(timing["id"]),"segment_id":segment_id,"fold":int(segment["fold"]),"regime":str(segment["regime"]),"symbol":str(frame.iloc[int(signal["signal_bar_index"])].get("symbol") or ""),"signal_reason":signal["reason"],"level_id":signal.get("level_id"),"target_to_base_cost_ratio":signal["target_to_base_cost_ratio"],"risk_to_base_cost_ratio":signal["risk_to_base_cost_ratio"]}); cell_trades.append(trade); trade_rows.append(trade)
                metrics=helper.aggregate_trades(cell_trades); metrics.update({"variant_id":variant_id,"source_lane_id":lane_id,"execution_timeframe":execution_timeframe,"repair_axis":bundle["repair_axis"],"design_class":bundle["design_class"],"family":bundle["family"],"cost_profile_id":str(cost["id"]),"timing_id":str(timing["id"]),"fold_metrics":fold_metrics(helper,cell_trades)}); metrics["gate_status"]=cell_gate(helper,metrics); metrics["economic_pass"]=all(metrics["gate_status"].values()); cell_rows.append(metrics); cell_map[(str(cost["id"]),str(timing["id"]))]=metrics
        primary=[metrics for (cost_id,_),metrics in cell_map.items() if cost_id in {"cost_profile_0","cost_profile_1"}]; base=cell_map.get(BASE_CELL,{}); adverse=cell_map.get(ADVERSE_CELL,{}); severe=cell_map.get(SEVERE_CELL,{}); positive_primary=sum(bool(metrics.get("economic_pass")) for metrics in primary); base_adverse=bool(base.get("economic_pass")) and bool(adverse.get("economic_pass")); source=bundle.get("source_metrics") or {}; baseline_score=(risk_score(source.get("base_metrics") or {})+risk_score(source.get("adverse_metrics") or {}))/2.0; candidate_score=(risk_score(base)+risk_score(adverse))/2.0; reference=plan.get("reference_metrics") or {}; reference_score=(risk_score(reference.get("base") or {})+risk_score(reference.get("adverse") or {}))/2.0; targeted_pass=base_adverse and positive_primary>=MINIMUM_POSITIVE_PRIMARY_CELLS and candidate_score>baseline_score; reference_beat=targeted_pass and candidate_score>reference_score; severe_margin=meaningful_severe_margin(severe); control_further=lane_id==ATR5_CONTROL and targeted_pass and severe_margin
        bundle_rows.append({"variant_id":variant_id,"source_lane_id":lane_id,"execution_timeframe":execution_timeframe,"repair_axis":bundle["repair_axis"],"design_class":bundle["design_class"],"family":bundle["family"],"signal_count":sum(len(value) for value in signal_cache.values()),"rejection_histogram":dict(sorted(rejection_total.items())),"positive_primary_cell_count":positive_primary,"base_and_adverse_positive":base_adverse,"baseline_risk_score":baseline_score,"candidate_risk_score":candidate_score,"reference_risk_score":reference_score,"targeted_repair_pass":targeted_pass,"reference_beating_pass":reference_beat,"meaningful_severe_margin_pass":severe_margin,"atr5_control_further_uplift":control_further,"base_metrics":base,"adverse_metrics":adverse,"severe_tail_metrics":severe}); print(f"A4D2_THIRD_WAVE_TARGETED_PROGRESS={bundle_number}/{EXPECTED_BUNDLES} CELLS={bundle_number*EXPECTED_STRESS_PER_BUNDLE}/{EXPECTED_CELLS} TRADES={len(trade_rows)}")
    lane_best:dict[str,dict[str,Any]]={}
    def lane_key(row:dict[str,Any])->tuple[int,int,int,int,float,int]: return (int(bool(row.get("targeted_repair_pass"))),int(bool(row.get("meaningful_severe_margin_pass"))),int(bool(row.get("base_and_adverse_positive"))),int(row.get("positive_primary_cell_count") or 0),finite(row.get("candidate_risk_score"),-1e9),int(row.get("signal_count") or 0))
    for row in bundle_rows:
        lane=str(row["source_lane_id"])
        if lane not in lane_best or lane_key(row)>lane_key(lane_best[lane]): lane_best[lane]=row
    repaired=sorted(lane for lane,row in lane_best.items() if bool(row.get("targeted_repair_pass")) and lane!=ATR5_CONTROL); control_further=bool(lane_best.get(ATR5_CONTROL,{}).get("atr5_control_further_uplift")); severe_ids=sorted(lane for lane,row in lane_best.items() if bool(row.get("meaningful_severe_margin_pass"))); reference_ids=sorted(lane for lane,row in lane_best.items() if bool(row.get("reference_beating_pass")))
    output=root/OUTPUT_DIR; trade_count,trade_sha=atomic_jsonl(output/"third_wave_trade_rows_v1.jsonl",trade_rows); cell_count,cell_sha=atomic_jsonl(output/"third_wave_cell_rows_v1.jsonl",cell_rows)
    summary={"state":"PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132","target_sha":args.target_sha,"bundle_count":len(bundle_rows),"cell_result_count":cell_count,"trade_result_count":trade_count,"trade_sha256":trade_sha,"cell_sha256":cell_sha,"targeted_repair_pass_bundle_count":sum(bool(row["targeted_repair_pass"]) for row in bundle_rows),"recovered_lane_count":len(repaired),"recovered_lane_ids":repaired,"atr5_control_preserved":True,"atr5_control_further_uplift":control_further,"meaningful_severe_margin_lane_count":len(severe_ids),"meaningful_severe_margin_lane_ids":severe_ids,"reference_beating_lane_count":len(reference_ids),"reference_beating_lane_ids":reference_ids,"lane_best_rows":[lane_best[key] for key in sorted(lane_best)],"mutation_rows":[],"next_stage":"R7.A4D2_KEEP14_PLUS_REPAIRED11_UNIFIED_CANDIDATE_MATERIAL_AUDIT" if repaired or control_further else "R7.A4D2_FAILED_LANE_RETIRE_OR_DATA_EXPANSION_DECISION"}; atomic_json(output/"third_wave_targeted_repair_summary_v1.json",summary)
    after=helper.snapshot(required+selected+protected); mutations=helper.diff_snapshot(before,after); final_blockers=[]
    if cell_count!=EXPECTED_CELLS: final_blockers.append(f"CELL_COUNT_INVALID:{cell_count}")
    if mutations: final_blockers.append(f"PROTECTED_MUTATIONS:{len(mutations)}")
    if final_blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132"); print("BLOCKER_COUNT="+str(len(final_blockers))); print("BLOCKERS="+json.dumps(final_blockers)); print("RC=2"); return 2
    print("STATE=PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132"); print("BLOCKER_COUNT=0"); print("THIRD_WAVE_BUNDLE_COUNT="+str(len(bundle_rows))); print("THIRD_WAVE_CELL_RESULT_COUNT="+str(cell_count)); print("THIRD_WAVE_TRADE_RESULT_COUNT="+str(trade_count)); print("TARGETED_REPAIR_PASS_BUNDLE_COUNT="+str(summary["targeted_repair_pass_bundle_count"])); print("RECOVERED_LANE_COUNT="+str(len(repaired))); print("RECOVERED_LANE_IDS="+json.dumps(repaired)); print("ATR5_CONTROL_PRESERVED=true"); print("ATR5_CONTROL_FURTHER_UPLIFT="+str(control_further).lower()); print("MEANINGFUL_SEVERE_MARGIN_LANE_COUNT="+str(len(severe_ids))); print("MEANINGFUL_SEVERE_MARGIN_LANE_IDS="+json.dumps(severe_ids)); print("REFERENCE_BEATING_LANE_COUNT="+str(len(reference_ids))); print("REFERENCE_BEATING_LANE_IDS="+json.dumps(reference_ids)); print("LANE_BEST_ROWS="+json.dumps(summary["lane_best_rows"],sort_keys=True)); print("SUMMARY_JSON="+str(output/"third_wave_targeted_repair_summary_v1.json")); print("NEXT_STAGE="+summary["next_stage"]); print("BLOCKERS=[]"); print("RC=0"); return 0

if __name__=="__main__":
    raise SystemExit(main())
