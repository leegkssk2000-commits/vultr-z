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

PLAN_PATH = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_plan/all_11_second_wave_plan_v1.json")
CALIBRATION_PATH = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132")

EXPECTED_BUNDLES = 22
EXPECTED_CELLS = 132
EXPECTED_STRESS_PER_BUNDLE = 6
EXPECTED_SEGMENTS = 24
EXPECTED_FOLDS = 6
MINIMUM_TRADES = 24
MINIMUM_SYMBOLS = 3
MINIMUM_POSITIVE_FOLDS = 4
MINIMUM_POSITIVE_PRIMARY_CELLS = 3
PASSED_LANE = "dual_atr_volatility_bot:5m"
REFERENCE_LANE_ID = "dual_donchian_trend_bot:15m"

VARIANT_IDS = {
    "atr5_impulse_15m_alignment", "atr5_impulse_retest_cost_defense",
    "ma15_accel_first_pullback", "ma15_accel_continuation_reentry",
    "ma5_confluence_first_pullback", "ma5_accel_15m_alignment",
    "donchian5_break_retest_volume", "donchian5_15m_alignment_continuation",
    "atr15_context_5m_retest", "atr15_persistence_5m_trigger",
    "vwap15_context_5m_outer_reclaim", "vwap15_session_failed_auction",
    "vwap5_anchor_rotation", "vwap5_outer_reclaim_maker",
    "neutral_grid15_inventory_cycle", "neutral_grid15_session_reset_cycle",
    "neutral_grid5_inventory_cycle", "neutral_grid5_volatility_cycle",
    "trend_grid15_inventory_pullback", "trend_grid15_breakout_ladder",
    "trend_grid5_inventory_pullback", "trend_grid5_impulse_ladder",
}

EXECUTION_TIMEFRAME = {
    "atr15_context_5m_retest": "5m", "atr15_persistence_5m_trigger": "5m",
    "vwap15_context_5m_outer_reclaim": "5m", "vwap15_session_failed_auction": "5m",
    "neutral_grid15_inventory_cycle": "5m", "neutral_grid15_session_reset_cycle": "5m",
    "trend_grid15_inventory_pullback": "5m", "trend_grid15_breakout_ladder": "5m",
}
GRID_VARIANTS = {variant for variant in VARIANT_IDS if "grid" in variant}

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
        temporary = Path(handle.name)
    os.replace(temporary, path)

def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(); count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line); digest.update(line.encode("utf-8")); count += 1
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return count, digest.hexdigest()

def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default

def touch_indices(condition: pd.Series, cooldown: int = 3) -> list[int]:
    output: list[int] = []; last = -10**9
    for raw in np.flatnonzero(condition.fillna(False).to_numpy(dtype=bool)):
        index = int(raw)
        if index - last >= cooldown:
            output.append(index); last = index
    return output

def generate_variant_signals(variant_id: str, frame: pd.DataFrame, measurement: pd.Series, frame15: pd.DataFrame, segment_regime: str, base_cost_pct: float, old: Any) -> tuple[list[dict[str, Any]], Counter[str]]:
    signals: list[dict[str, Any]] = []; rejected: Counter[str] = Counter()
    close = frame["close"].astype(float); open_v = frame["open"].astype(float)
    high = frame["high"].astype(float); low = frame["low"].astype(float)
    volume = frame["volume"].astype(float); a = old.atr(frame, 14); vz = old.volume_z(frame)
    body = (close-open_v).abs(); span = (high-low).replace(0, np.nan); clv = (close-low).div(span)
    ctx = old.context_columns(frame, frame15)
    e9 = old.ema(close, 9); e12 = old.ema(close, 12); e20 = old.ema(close, 20)
    e21 = old.ema(close, 21); e26 = old.ema(close, 26)

    def add(index: int, side: str, risk_mult: float, reward_mult: float, timeout: int, reason: str, anchor: float | None = None, level_id: str | None = None) -> None:
        av = finite(a.iloc[index], math.nan); cv = finite(close.iloc[index], math.nan)
        if not math.isfinite(av) or av <= 0 or not math.isfinite(cv): return
        if side == "long":
            stop = min(finite(low.iloc[index], cv)-0.10*av, cv-risk_mult*av)
            target = anchor if anchor is not None and anchor > cv else cv+reward_mult*av
        else:
            stop = max(finite(high.iloc[index], cv)+0.10*av, cv+risk_mult*av)
            target = anchor if anchor is not None and 0 < anchor < cv else cv-reward_mult*av
        old.append_signal(signals, rejected, frame, measurement, base_cost_pct, index, side, stop, target, timeout, reason, level_id)

    if variant_id in {"atr5_impulse_15m_alignment", "atr5_impulse_retest_cost_defense"}:
        ph = high.shift(1).rolling(12, min_periods=12).max(); pl = low.shift(1).rolling(12, min_periods=12).min()
        li = (span>=1.40*a)&(body/span>=0.65)&(clv>=0.82)&(vz>=1.0)&(close>=ph)
        si = (span>=1.40*a)&(body/span>=0.65)&(clv<=0.18)&(vz>=1.0)&(close<=pl)
        if variant_id == "atr5_impulse_15m_alignment":
            long = li&(ctx["ctx_close"]>=ctx["ctx_ema20"])&(ctx["ctx_slope"]>-0.01)
            short = si&(ctx["ctx_close"]<=ctx["ctx_ema20"])&(ctx["ctx_slope"]<0.01)
            for raw in np.flatnonzero(old.edge(long).to_numpy(bool)): add(int(raw), "long", 1.0, 4.0, 10, variant_id)
            for raw in np.flatnonzero(old.edge(short).to_numpy(bool)): add(int(raw), "short", 1.0, 4.0, 10, variant_id)
        else:
            for index in old.retest_after_break(close, high, low, ph, li, "long", 3): add(index, "long", 0.95, 3.8, 10, variant_id)
            for index in old.retest_after_break(close, high, low, pl, si, "short", 3): add(index, "short", 0.95, 3.8, 10, variant_id)

    elif variant_id in {"ma15_accel_first_pullback", "ma15_accel_continuation_reentry"}:
        spread = (e12-e26).div(a); accel = spread.diff(2)
        trend_long = (spread>0.12)&(segment_regime=="trend_up"); trend_short = (spread<-0.12)&(segment_regime=="trend_down")
        if variant_id == "ma15_accel_first_pullback":
            arm_l = old.edge(trend_long&(accel>0.025)).rolling(8, min_periods=1).max().astype(bool)
            arm_s = old.edge(trend_short&(accel<-0.025)).rolling(8, min_periods=1).max().astype(bool)
            long = arm_l&(low<=e12)&(close>e12)&(e12>e26); short = arm_s&(high>=e12)&(close<e12)&(e12<e26)
        else:
            long = trend_long&(accel>0.015)&(accel.shift(1)<=0.015)&(close>e12)
            short = trend_short&(accel<-0.015)&(accel.shift(1)>=-0.015)&(close<e12)
        for raw in np.flatnonzero(old.edge(long).to_numpy(bool)): add(int(raw), "long", 1.15, 3.5, 36, variant_id)
        for raw in np.flatnonzero(old.edge(short).to_numpy(bool)): add(int(raw), "short", 1.15, 3.5, 36, variant_id)

    elif variant_id in {"ma5_confluence_first_pullback", "ma5_accel_15m_alignment"}:
        spread = (e9-e21).div(a)
        lc = (ctx["ctx_close"]>ctx["ctx_ema20"])&(ctx["ctx_ema20"]>ctx["ctx_ema50"])&(ctx["ctx_slope"]>0)
        sc = (ctx["ctx_close"]<ctx["ctx_ema20"])&(ctx["ctx_ema20"]<ctx["ctx_ema50"])&(ctx["ctx_slope"]<0)
        if variant_id == "ma5_confluence_first_pullback":
            long = lc&(spread>0.08)&(low<=e9)&(close>e9); short = sc&(spread<-0.08)&(high>=e9)&(close<e9)
        else:
            accel = spread.diff(2)
            long = lc&(spread>0.08)&(accel>0.02)&(accel.shift(1)<=0.02)
            short = sc&(spread<-0.08)&(accel<-0.02)&(accel.shift(1)>=-0.02)
        for raw in np.flatnonzero(old.edge(long).to_numpy(bool)): add(int(raw), "long", 1.0, 3.5, 24, variant_id)
        for raw in np.flatnonzero(old.edge(short).to_numpy(bool)): add(int(raw), "short", 1.0, 3.5, 24, variant_id)

    elif variant_id in {"donchian5_break_retest_volume", "donchian5_15m_alignment_continuation"}:
        ph = high.shift(1).rolling(20, min_periods=20).max(); pl = low.shift(1).rolling(20, min_periods=20).min()
        lb = (close>ph)&(vz>0); sb = (close<pl)&(vz>0)
        if variant_id == "donchian5_break_retest_volume":
            for index in old.retest_after_break(close, high, low, ph, lb, "long", 5): add(index, "long", 0.95, 4.0, 24, variant_id)
            for index in old.retest_after_break(close, high, low, pl, sb, "short", 5): add(index, "short", 0.95, 4.0, 24, variant_id)
        else:
            long = lb&(ctx["ctx_close"]>ctx["ctx_ema50"])&(ctx["ctx_slope"]>0)
            short = sb&(ctx["ctx_close"]<ctx["ctx_ema50"])&(ctx["ctx_slope"]<0)
            rl = long.rolling(5, min_periods=1).max().astype(bool); rs = short.rolling(5, min_periods=1).max().astype(bool)
            le = rl&(low<=e20)&(close>e20); se = rs&(high>=e20)&(close<e20)
            for raw in np.flatnonzero(old.edge(le).to_numpy(bool)): add(int(raw), "long", 1.0, 4.0, 28, variant_id)
            for raw in np.flatnonzero(old.edge(se).to_numpy(bool)): add(int(raw), "short", 1.0, 4.0, 28, variant_id)

    elif variant_id in {"atr15_context_5m_retest", "atr15_persistence_5m_trigger"}:
        lc = (ctx["ctx_close"]>ctx["ctx_high20"])&(ctx["ctx_slope"]>0); sc = (ctx["ctx_close"]<ctx["ctx_low20"])&(ctx["ctx_slope"]<0)
        if variant_id == "atr15_context_5m_retest":
            long = lc&(low<=e20)&(close>e20)&(vz>-0.5); short = sc&(high>=e20)&(close<e20)&(vz>-0.5)
        else:
            long = lc&(span>=1.15*a)&(clv>0.70)&(vz>0); short = sc&(span>=1.15*a)&(clv<0.30)&(vz>0)
        for raw in np.flatnonzero(old.edge(long).to_numpy(bool)): add(int(raw), "long", 1.0, 3.8, 20, variant_id)
        for raw in np.flatnonzero(old.edge(short).to_numpy(bool)): add(int(raw), "short", 1.0, 3.8, 20, variant_id)

    elif variant_id in {"vwap15_context_5m_outer_reclaim", "vwap15_session_failed_auction", "vwap5_anchor_rotation", "vwap5_outer_reclaim_maker"}:
        rolling = old.rolling_vwap(frame, 24); anchored = old.anchored_vwap(frame)
        basis = anchored if "anchor" in variant_id or "session" in variant_id else rolling
        deviation = close-basis; std = deviation.rolling(24, min_periods=24).std(ddof=0)
        range_ctx = ctx["ctx_width_atr"].between(4.0, 12.0)&(ctx["ctx_mid_slope"]<0.10)
        lw = (np.minimum(open_v, close)-low).div(span); uw = (high-np.maximum(open_v, close)).div(span)
        if variant_id == "vwap15_context_5m_outer_reclaim":
            long = range_ctx&(low<basis-1.8*std)&(close>basis-1.8*std); short = range_ctx&(high>basis+1.8*std)&(close<basis+1.8*std)
        elif variant_id == "vwap15_session_failed_auction":
            long = range_ctx&(low<basis-1.6*std)&(close>basis-1.6*std)&(lw>0.40)&(close>open_v)
            short = range_ctx&(high>basis+1.6*std)&(close<basis+1.6*std)&(uw>0.40)&(close<open_v)
        elif variant_id == "vwap5_anchor_rotation":
            slope = basis.diff(4).abs().div(4*a)
            long = range_ctx&(low<basis-1.5*std)&(close>basis-1.5*std)&(slope<0.05)
            short = range_ctx&(high>basis+1.5*std)&(close<basis+1.5*std)&(slope<0.05)
        else:
            raw_l = range_ctx&(low<basis-1.7*std)&(close>basis-1.7*std); raw_s = range_ctx&(high>basis+1.7*std)&(close<basis+1.7*std)
            long = raw_l.shift(1, fill_value=False)&(close>close.shift(1)); short = raw_s.shift(1, fill_value=False)&(close<close.shift(1))
        for raw in np.flatnonzero(old.edge(long).to_numpy(bool)): add(int(raw), "long", 0.95, 3.0, 18, variant_id, finite(basis.iloc[int(raw)], math.nan))
        for raw in np.flatnonzero(old.edge(short).to_numpy(bool)): add(int(raw), "short", 0.95, 3.0, 18, variant_id, finite(basis.iloc[int(raw)], math.nan))

    elif variant_id in {"neutral_grid15_inventory_cycle", "neutral_grid15_session_reset_cycle", "neutral_grid5_inventory_cycle", "neutral_grid5_volatility_cycle"}:
        if segment_regime != "range": return signals, Counter({"REGIME_VETO": 1})
        rh = ctx["ctx_high20"]; rl = ctx["ctx_low20"]; width = rh-rl
        stable = ctx["ctx_width_atr"].between(4.5, 12.0)&(ctx["ctx_mid_slope"]<(0.06 if "volatility" not in variant_id else 0.08))
        if "session_reset" in variant_id:
            center = (rh+rl)/2.0; stable &= center.diff(6).abs().div(ctx["ctx_atr"])<0.35
        if "volatility" in variant_id:
            stable &= a.div(a.rolling(30, min_periods=30).median()).between(0.70, 1.35)
        levels = {"L15": rl+0.15*width, "L35": rl+0.35*width, "L65": rl+0.65*width, "L85": rl+0.85*width}
        for entry_name, target_name, side in (("L15", "L35", "long"), ("L35", "L65", "long"), ("L85", "L65", "short"), ("L65", "L35", "short")):
            entry_level = levels[entry_name]; target_level = levels[target_name]
            cond = stable&((low<=entry_level)&(close>entry_level) if side=="long" else (high>=entry_level)&(close<entry_level))
            for index in touch_indices(cond, 4): add(index, side, 1.0, 3.2, 20, variant_id, finite(target_level.iloc[index], math.nan), f"{entry_name}->{target_name}")

    elif variant_id in {"trend_grid15_inventory_pullback", "trend_grid15_breakout_ladder", "trend_grid5_inventory_pullback", "trend_grid5_impulse_ladder"}:
        lc = (ctx["ctx_close"]>ctx["ctx_ema50"])&(ctx["ctx_slope"]>0.01); sc = (ctx["ctx_close"]<ctx["ctx_ema50"])&(ctx["ctx_slope"]<-0.01)
        if "breakout" in variant_id:
            lc &= ctx["ctx_close"]>ctx["ctx_high20"]; sc &= ctx["ctx_close"]<ctx["ctx_low20"]
        if "impulse" in variant_id:
            lc &= (span>=1.10*a)&(clv>0.65); sc &= (span>=1.10*a)&(clv<0.35)
        for distance, tag in ((0.35, "L1"), (0.75, "L2")):
            ll = e20-distance*a; sl = e20+distance*a
            long = lc&(low<=ll)&(close>ll); short = sc&(high>=sl)&(close<sl)
            for index in touch_indices(long, 4): add(index, "long", 1.1, 3.4, 20, variant_id, level_id=tag)
            for index in touch_indices(short, 4): add(index, "short", 1.1, 3.4, 20, variant_id, level_id=tag)
    else:
        raise ValueError(f"VARIANT_UNSUPPORTED:{variant_id}")
    signals.sort(key=lambda row: (int(row["entry_bar_index"]), str(row["side"]), str(row.get("level_id") or ""), str(row["reason"])))
    return signals, rejected

def fold_metrics(helper: Any, trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in trades: grouped[int(row["fold"])].append(row)
    rows: dict[str, dict[str, Any]] = {}; positive = 0
    for fold in range(EXPECTED_FOLDS):
        metrics = helper.aggregate_trades(grouped.get(fold, [])); rows[str(fold)] = metrics
        if helper.finite_metric(metrics.get("net_pnl_sum_pct")) > 0: positive += 1
    return {"rows": rows, "fold_count": EXPECTED_FOLDS, "positive_fold_count": positive, "positive_fold_ratio": positive/EXPECTED_FOLDS}

def cell_gate(helper: Any, cell: dict[str, Any]) -> dict[str, bool]:
    return {"trade_gate": int(cell.get("trade_count") or 0)>=MINIMUM_TRADES, "symbol_gate": len(cell.get("symbol_histogram") or {})>=MINIMUM_SYMBOLS, "profit_factor_gate": helper.finite_metric(cell.get("profit_factor"))>1.0, "expectancy_gate": helper.finite_metric(cell.get("expectancy_r"))>0.0, "net_pnl_gate": helper.finite_metric(cell.get("net_pnl_sum_pct"))>0.0, "walk_forward_gate": int((cell.get("fold_metrics") or {}).get("positive_fold_count") or 0)>=MINIMUM_POSITIVE_FOLDS}

def risk_score(metrics: dict[str, Any]) -> float:
    expectancy = finite(metrics.get("expectancy_r")); pnl = finite(metrics.get("net_pnl_sum_pct")); drawdown = max(finite(metrics.get("max_drawdown_pct")), 0.25); pf = max(finite(metrics.get("profit_factor")), 0.0); folds = int((metrics.get("fold_metrics") or {}).get("positive_fold_count") or metrics.get("positive_fold_count") or 0)
    return expectancy+0.20*(pnl/drawdown)+0.10*(pf-1.0)+0.03*folds

def self_test(old: Any) -> int:
    assert len(VARIANT_IDS)==EXPECTED_BUNDLES and len(EXECUTION_TIMEFRAME)==8
    size=420; x=np.arange(size, dtype=float); close=pd.Series(100+0.02*x+1.7*np.sin(x/7.0)); open_v=close.shift(1).fillna(close.iloc[0])
    frame5=pd.DataFrame({"__timestamp":x*300000,"open":open_v,"high":pd.concat([close,open_v],axis=1).max(axis=1)+0.35,"low":pd.concat([close,open_v],axis=1).min(axis=1)-0.35,"close":close,"volume":100+(x%23)*5,"symbol":"TEST","timeframe":"5m"})
    frame15=frame5.iloc[::3].reset_index(drop=True).copy(); frame15["timeframe"]="15m"; mask5=pd.Series([True]*len(frame5)); mask15=pd.Series([True]*len(frame15))
    for variant_id in sorted(VARIANT_IDS):
        timeframe=EXECUTION_TIMEFRAME.get(variant_id, "5m" if "5" in variant_id else "15m"); frame=frame5 if timeframe=="5m" else frame15; mask=mask5 if timeframe=="5m" else mask15; regime="range" if "grid" in variant_id or "vwap" in variant_id else "trend_up"
        signals,rejected=generate_variant_signals(variant_id,frame,mask,frame15,regime,0.12,old); assert isinstance(signals,list) and isinstance(rejected,Counter)
    print("STATE=PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_SELF_TEST"); print("RC=0"); return 0

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--root",default="/home/z/z"); parser.add_argument("--target-sha",default="UNKNOWN"); parser.add_argument("--raw-module"); parser.add_argument("--helper-module"); parser.add_argument("--benchmark-module"); parser.add_argument("--old-uplift-module"); parser.add_argument("--a4d-contract"); parser.add_argument("--self-test",action="store_true"); args=parser.parse_args()
    if not args.old_uplift_module: raise SystemExit("--old-uplift-module required")
    old=import_module(Path(args.old_uplift_module).resolve(),"r7a4d2_second_wave_old")
    if args.self_test: return self_test(old)
    if not all([args.raw_module,args.helper_module,args.benchmark_module,args.a4d_contract]): raise SystemExit("--raw-module --helper-module --benchmark-module --a4d-contract required")
    root=Path(args.root).resolve(); raw=import_module(Path(args.raw_module).resolve(),"r7a4d2_second_wave_raw"); helper=import_module(Path(args.helper_module).resolve(),"r7a4d2_second_wave_helper"); benchmark=import_module(Path(args.benchmark_module).resolve(),"r7a4d2_second_wave_benchmark"); contract=load_json(Path(args.a4d_contract).resolve())
    required=[root/PLAN_PATH,root/CALIBRATION_PATH,root/MANIFEST_PATH]; missing=[str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT"); print("BLOCKER_COUNT=1"); print("BLOCKERS="+json.dumps(["REQUIRED_EVIDENCE_MISSING:"+",".join(missing)])); print("RC=2"); return 2
    plan=load_json(root/PLAN_PATH); calibration=load_json(root/CALIBRATION_PATH); manifest=load_json(root/MANIFEST_PATH); blockers:list[str]=[]
    if plan.get("state")!="PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_PLAN": blockers.append("SECOND_WAVE_PLAN_NOT_PASS")
    bundles=[row for row in plan.get("second_wave_rows",[]) if isinstance(row,dict)]
    if len(bundles)!=EXPECTED_BUNDLES: blockers.append(f"BUNDLE_COUNT_INVALID:{len(bundles)}")
    if {str(row.get("variant_id")) for row in bundles}!=VARIANT_IDS: blockers.append("VARIANT_SET_INVALID")
    segments={str(row["segment_id"]):row for row in manifest.get("selected_segments",[]) if isinstance(row,dict)}
    if len(segments)!=EXPECTED_SEGMENTS: blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")
    model=calibration.get("corrected_execution_model",{}); costs=[row for row in model.get("profiles",[]) if isinstance(row,dict)]; timings=[row for row in model.get("timing_perturbations",[]) if isinstance(row,dict)]
    if len(costs)*len(timings)!=EXPECTED_STRESS_PER_BUNDLE: blockers.append("STRESS_GRID_INVALID")
    base_cost_pct=old.base_round_trip_cost(calibration)
    if not math.isfinite(base_cost_pct) or base_cost_pct<=0: blockers.append("BASE_COST_INVALID")
    if blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT"); print("BLOCKER_COUNT="+str(len(blockers))); print("BLOCKERS="+json.dumps(blockers)); print("RC=2"); return 2
    source_sha={str(row.get("source_path")):str(row.get("source_sha256") or "") for row in manifest.get("selected_segments",[]) if isinstance(row,dict)}; source_paths=sorted({str(row["source_path"]) for row in segments.values()}); selected=[root/raw.safe_repo_path(path) for path in source_paths]; protected=[Path(str(value)) for value in contract.get("protected_paths",[])]; before=helper.snapshot(required+selected+protected)
    source_cache:dict[str,pd.DataFrame]={}; frame_cache:dict[tuple[str,str],pd.DataFrame]={}; mask_cache:dict[tuple[str,str],pd.Series]={}; trade_rows:list[dict[str,Any]]=[]; cell_rows:list[dict[str,Any]]=[]; bundle_rows:list[dict[str,Any]]=[]
    for bundle_number,bundle in enumerate(sorted(bundles,key=lambda row:str(row["variant_id"])),1):
        variant_id=str(bundle["variant_id"]); source_lane=str(bundle["lane_id"]); original_timeframe=source_lane.rsplit(":",1)[1]; execution_timeframe=EXECUTION_TIMEFRAME.get(variant_id,original_timeframe); signal_cache:dict[str,list[dict[str,Any]]]={}; rejection_total:Counter[str]=Counter()
        for segment_id,segment in sorted(segments.items()):
            source_path=str(segment["source_path"])
            if source_path not in source_cache: source_cache[source_path]=raw.fixed_ohlcv_frame(root/raw.safe_repo_path(source_path),source_sha[source_path])
            for timeframe in {execution_timeframe,"15m"}:
                key=(segment_id,timeframe)
                if key not in frame_cache:
                    frame_cache[key]=raw.resample_for_segment(source_cache[source_path],int(segment["start_row"]),int(segment["end_row_exclusive"]),timeframe); mask_cache[key]=raw.measurement_mask(frame_cache[key],int(segment["start_row"]),int(segment["end_row_exclusive"]))
            signals,rejected=generate_variant_signals(variant_id,frame_cache[(segment_id,execution_timeframe)],mask_cache[(segment_id,execution_timeframe)],frame_cache[(segment_id,"15m")],str(segment["regime"]),base_cost_pct,old); signal_cache[segment_id]=signals; rejection_total.update(rejected)
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
                        else:
                            if int(signal["entry_bar_index"])<=last_exit: continue
                        trade=benchmark.simulate_trade(frame,measurement,signal,cost,timing,execution_timeframe)
                        if trade is None: continue
                        if variant_id in GRID_VARIANTS: last_exit_by_level[key]=int(trade["exit_index"])
                        else: last_exit=int(trade["exit_index"])
                        trade.update({"variant_id":variant_id,"source_lane_id":source_lane,"execution_timeframe":execution_timeframe,"repair_class":bundle["repair_class"],"family":bundle["family"],"cost_profile_id":str(cost["id"]),"timing_id":str(timing["id"]),"segment_id":segment_id,"fold":int(segment["fold"]),"regime":str(segment["regime"]),"symbol":str(frame.iloc[int(signal["signal_bar_index"])].get("symbol") or ""),"signal_reason":signal["reason"],"level_id":signal.get("level_id"),"target_to_base_cost_ratio":signal["target_to_base_cost_ratio"],"risk_to_base_cost_ratio":signal["risk_to_base_cost_ratio"]}); cell_trades.append(trade); trade_rows.append(trade)
                metrics=helper.aggregate_trades(cell_trades); metrics.update({"variant_id":variant_id,"source_lane_id":source_lane,"execution_timeframe":execution_timeframe,"repair_class":bundle["repair_class"],"family":bundle["family"],"cost_profile_id":str(cost["id"]),"timing_id":str(timing["id"]),"fold_metrics":fold_metrics(helper,cell_trades)}); metrics["gate_status"]=cell_gate(helper,metrics); metrics["economic_pass"]=all(metrics["gate_status"].values()); cell_rows.append(metrics); cell_map[(str(cost["id"]),str(timing["id"]))]=metrics
        primary=[metrics for (cost_id,_),metrics in cell_map.items() if cost_id in {"cost_profile_0","cost_profile_1"}]; base=cell_map.get(("cost_profile_0","timing_0"),{}); adverse=cell_map.get(("cost_profile_1","timing_1"),{}); severe=cell_map.get(("cost_profile_2","timing_1"),{}); positive_primary=sum(1 for metrics in primary if bool(metrics.get("economic_pass"))); base_adverse=bool(base.get("economic_pass")) and bool(adverse.get("economic_pass")); baseline=bundle.get("baseline_metrics") or {}; baseline_score=(risk_score(baseline.get("base") or {})+risk_score(baseline.get("adverse") or {}))/2.0; candidate_score=(risk_score(base)+risk_score(adverse))/2.0; reference=plan.get("reference_metrics") or {}; reference_score=(risk_score(reference.get("base") or {})+risk_score(reference.get("adverse") or {}))/2.0; uplift=base_adverse and positive_primary>=MINIMUM_POSITIVE_PRIMARY_CELLS and candidate_score>baseline_score; reference_beat=uplift and candidate_score>reference_score
        bundle_rows.append({"variant_id":variant_id,"source_lane_id":source_lane,"execution_timeframe":execution_timeframe,"repair_class":bundle["repair_class"],"family":bundle["family"],"signal_count":sum(len(value) for value in signal_cache.values()),"rejection_histogram":dict(sorted(rejection_total.items())),"positive_primary_cell_count":positive_primary,"base_and_adverse_positive":base_adverse,"baseline_risk_score":baseline_score,"candidate_risk_score":candidate_score,"reference_risk_score":reference_score,"uplift_discovery_pass":uplift,"reference_beating_discovery_pass":reference_beat,"base_metrics":base,"adverse_metrics":adverse,"severe_tail_metrics":severe}); print(f"A4D2_ALL_11_SECOND_WAVE_PROGRESS={bundle_number}/{EXPECTED_BUNDLES} CELLS={bundle_number*EXPECTED_STRESS_PER_BUNDLE}/{EXPECTED_CELLS} TRADES={len(trade_rows)}")
    lane_best:dict[str,dict[str,Any]]={}
    for row in bundle_rows:
        lane_id=str(row["source_lane_id"])
        if lane_id not in lane_best or finite(row["candidate_risk_score"],-1e9)>finite(lane_best[lane_id]["candidate_risk_score"],-1e9): lane_best[lane_id]=row
    uplifted=sorted([lane_id for lane_id,row in lane_best.items() if bool(row["uplift_discovery_pass"])]); reference_beats=sorted([lane_id for lane_id,row in lane_best.items() if bool(row["reference_beating_discovery_pass"])]); failed_recovered=sorted([lane_id for lane_id in uplifted if lane_id!=PASSED_LANE]); passed_further_uplift=PASSED_LANE in uplifted
    output=root/OUTPUT_DIR; trade_count,trade_sha=atomic_jsonl(output/"second_wave_trade_rows_v1.jsonl",trade_rows); cell_count,cell_sha=atomic_jsonl(output/"second_wave_cell_rows_v1.jsonl",cell_rows)
    summary={"state":"PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132","target_sha":args.target_sha,"bundle_count":len(bundle_rows),"cell_result_count":cell_count,"trade_result_count":trade_count,"trade_sha256":trade_sha,"cell_sha256":cell_sha,"uplift_discovery_pass_bundle_count":sum(bool(row["uplift_discovery_pass"]) for row in bundle_rows),"reference_beating_bundle_count":sum(bool(row["reference_beating_discovery_pass"]) for row in bundle_rows),"uplifted_lane_count":len(uplifted),"uplifted_lane_ids":uplifted,"failed_lane_recovered_count":len(failed_recovered),"failed_lane_recovered_ids":failed_recovered,"passed_lane_further_uplift":passed_further_uplift,"reference_beating_lane_count":len(reference_beats),"reference_beating_lane_ids":reference_beats,"lane_best_rows":[lane_best[key] for key in sorted(lane_best)],"mutation_rows":[],"next_stage":"R7.A4D2_EXCHANGE_BOT_V2_SECOND_WAVE_DISJOINT_VALIDATION" if uplifted else "R7.A4D2_EXCHANGE_BOT_V2_FEATURE_AND_DATA_EXPANSION_REDESIGN"}; atomic_json(output/"all_11_second_wave_summary_v1.json",summary)
    after=helper.snapshot(required+selected+protected); mutations=helper.diff_snapshot(before,after); final_blockers=[]
    if cell_count!=EXPECTED_CELLS: final_blockers.append(f"CELL_COUNT_INVALID:{cell_count}")
    if mutations: final_blockers.append(f"PROTECTED_MUTATIONS:{len(mutations)}")
    if final_blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132"); print("BLOCKER_COUNT="+str(len(final_blockers))); print("BLOCKERS="+json.dumps(final_blockers)); print("RC=2"); return 2
    print("STATE=PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132"); print("BLOCKER_COUNT=0"); print("SECOND_WAVE_BUNDLE_COUNT="+str(len(bundle_rows))); print("SECOND_WAVE_CELL_RESULT_COUNT="+str(cell_count)); print("SECOND_WAVE_TRADE_RESULT_COUNT="+str(trade_count)); print("UPLIFT_DISCOVERY_PASS_BUNDLE_COUNT="+str(summary["uplift_discovery_pass_bundle_count"])); print("UPLIFTED_LANE_COUNT="+str(len(uplifted))); print("UPLIFTED_LANE_IDS="+json.dumps(uplifted)); print("FAILED_LANE_RECOVERED_COUNT="+str(len(failed_recovered))); print("FAILED_LANE_RECOVERED_IDS="+json.dumps(failed_recovered)); print("PASSED_LANE_FURTHER_UPLIFT="+str(passed_further_uplift).lower()); print("REFERENCE_BEATING_LANE_COUNT="+str(len(reference_beats))); print("REFERENCE_BEATING_LANE_IDS="+json.dumps(reference_beats)); print("LANE_BEST_ROWS="+json.dumps(summary["lane_best_rows"],sort_keys=True)); print("SUMMARY_JSON="+str(output/"all_11_second_wave_summary_v1.json")); print("NEXT_STAGE="+summary["next_stage"]); print("BLOCKERS=[]"); print("RC=0"); return 0

if __name__=="__main__":
    raise SystemExit(main())
