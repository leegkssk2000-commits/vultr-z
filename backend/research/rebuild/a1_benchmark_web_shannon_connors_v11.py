from __future__ import annotations

import importlib
import json
from bisect import bisect_left
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
util: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_native_replay_v1"
)

SYMS = tuple(v2.SYMS6)
TF_CASES = (1_800_000, 3_600_000)
FROZEN_COST_REPORT = Path("/home/z/z/runtime/benchmark_web_holygrail_rearm_v9.json")
DAY_MS = 86_400_000


def frozen_costs() -> dict[str, float]:
    if FROZEN_COST_REPORT.exists():
        data = json.loads(FROZEN_COST_REPORT.read_text(encoding="utf-8"))
        out: dict[str, float] = {}
        for trade in data.get("result", {}).get("trades", []):
            out[str(trade["symbol"])] = float(trade["cost_bps"])
        if all(sym in out for sym in SYMS):
            return out
    authority = v2.read_json(v2.COST_PATH)
    out = {}
    for sym in SYMS:
        snap = v2.cost_ev.fetch_execution_snapshot(sym, authority)
        out[sym] = float(snap["pretrade_verified_cost_bps"])
    return out


def prepare_frames(tf: int) -> dict[str, pd.DataFrame]:
    base = util.load_5m()
    factor = tf // 300_000
    out: dict[str, pd.DataFrame] = {}
    for sym, frame in base.items():
        x = util.enrich(util.resample_frame(frame, factor))
        n5 = 240 if tf == 1_800_000 else 120
        x["sma5d"] = x["close"].rolling(n5).mean()
        x["sma5d_slope"] = x["sma5d"] - x["sma5d"].shift(1)
        x["avwap_low5d"] = util.rolling_anchor_vwap(x, n5, True)
        x["avwap_high5d"] = util.rolling_anchor_vwap(x, n5, False)
        delta = x["close"].diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=0.5, adjust=False).mean()
        avg_loss = loss.ewm(alpha=0.5, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        x["rsi2"] = 100.0 - 100.0 / (1.0 + rs)
        x["sma5"] = x["close"].rolling(5).mean()
        out[sym] = x
    return out


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return v2.metrics(trades)


def shannon_signal(x: pd.DataFrame, i: int) -> str:
    row, prev = x.iloc[i], x.iloc[i - 1]
    if not all(
        np.isfinite(float(row[k]))
        for k in ("sma5d", "avwap_low5d", "avwap_high5d", "atr")
    ):
        return "flat"
    long_ok = (
        float(row["sma5d_slope"]) > 0
        and float(row["close"]) > float(row["sma5d"])
        and float(row["close"]) > float(row["avwap_low5d"])
        and float(prev["close"]) <= float(prev["avwap_high5d"])
        and float(row["close"]) > float(row["avwap_high5d"])
        and float(row["close"]) > float(prev["high"])
    )
    short_ok = (
        float(row["sma5d_slope"]) < 0
        and float(row["close"]) < float(row["sma5d"])
        and float(row["close"]) < float(row["avwap_high5d"])
        and float(prev["close"]) >= float(prev["avwap_low5d"])
        and float(row["close"]) < float(row["avwap_low5d"])
        and float(row["close"]) < float(prev["low"])
    )
    return "long" if long_ok else ("short" if short_ok else "flat")


def shannon_trade(
    x: pd.DataFrame, i: int, side_name: str, cost: float, partial: bool, tf: int
) -> tuple[dict[str, Any] | None, int]:
    if i + 1 >= len(x):
        return None, i
    side = 1 if side_name == "long" else -1
    entry = float(x.iloc[i + 1]["open"])
    atr = max(float(x.iloc[i]["atr"]), 1e-12)
    local_low = float(x.iloc[max(0, i - 4) : i + 1]["low"].min())
    local_high = float(x.iloc[max(0, i - 4) : i + 1]["high"].max())
    ref = (
        min(local_low, float(x.iloc[i]["avwap_low5d"]))
        if side == 1
        else max(local_high, float(x.iloc[i]["avwap_high5d"]))
    )
    stop = ref - 0.15 * atr if side == 1 else ref + 0.15 * atr
    if (side == 1 and stop >= entry) or (side == -1 and stop <= entry):
        stop = entry - side * 1.0 * atr
    risk = abs(entry - stop)
    if risk <= 0:
        return None, i
    timeout = 96 if tf == 1_800_000 else 48
    last = min(len(x) - 1, i + 1 + timeout)
    remaining = 1.0
    parts: list[float] = []
    partial_done = False
    final_px = float(x.iloc[last]["close"])
    reason = "TIMEOUT"
    exit_j = last
    for j in range(i + 1, last + 1):
        row = x.iloc[j]
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
            final_px, exit_j, reason = stop, j, "HARD_STOP"
            break
        if partial and not partial_done:
            px1 = entry + side * risk
            if (side == 1 and hi >= px1) or (side == -1 and lo <= px1):
                parts.append((1.0 / 3.0) * side * (px1 - entry) / entry * 10_000.0)
                remaining -= 1.0 / 3.0
                partial_done = True
        av = float(row["avwap_low5d"] if side == 1 else row["avwap_high5d"])
        sma = float(row["sma5d"])
        slope = float(row["sma5d_slope"])
        structure_fail = close < av if side == 1 else close > av
        trend_fail = (
            (slope <= 0 and close < sma) if side == 1 else (slope >= 0 and close > sma)
        )
        if structure_fail or trend_fail:
            final_px, exit_j, reason = close, j, "AVWAP_TREND_EXIT"
            break
    parts.append(remaining * side * (final_px - entry) / entry * 10_000.0)
    gross = sum(parts)
    return {
        "signal_ts": int(x.iloc[i]["ts_ms"]),
        "entry_ts": int(x.iloc[i + 1]["ts_ms"]),
        "exit_ts": int(x.iloc[exit_j]["ts_ms"]),
        "side": side_name,
        "entry": entry,
        "exit": final_px,
        "gross_bps": gross,
        "cost_bps": cost,
        "net_bps": gross - cost,
        "reason": reason,
    }, exit_j


def daily_context() -> dict[str, tuple[list[int], list[float], list[float]]]:
    out: dict[str, tuple[list[int], list[float], list[float]]] = {}
    for sym in SYMS:
        rows = v2.cost_ev.fetch_bars(sym, "1d", 400)
        df = pd.DataFrame(rows).sort_values("ts_ms").reset_index(drop=True)
        close = df["close"].astype(float)
        ma200 = close.rolling(200).mean()
        out[sym] = (
            [int(v) for v in df["ts_ms"].tolist()],
            [float(v) for v in close.tolist()],
            [float(v) if np.isfinite(v) else np.nan for v in ma200.tolist()],
        )
    return out


def daily_trend(ctx: tuple[list[int], list[float], list[float]], ts: int) -> int:
    times, closes, ma = ctx
    day_start = ts // DAY_MS * DAY_MS
    idx = bisect_left(times, day_start) - 1
    if idx < 0 or idx >= len(ma) or not np.isfinite(ma[idx]):
        return 0
    return 1 if closes[idx] > ma[idx] else (-1 if closes[idx] < ma[idx] else 0)


def connors_trade(
    x: pd.DataFrame, i: int, side_name: str, cost: float, exit_mode: str, tf: int
) -> tuple[dict[str, Any] | None, int]:
    if i + 1 >= len(x):
        return None, i
    side = 1 if side_name == "long" else -1
    entry = float(x.iloc[i + 1]["open"])
    atr = max(float(x.iloc[i]["atr"]), 1e-12)
    stop = entry - side * 2.0 * atr
    timeout = 48 if tf == 1_800_000 else 24
    last = min(len(x) - 2, i + 1 + timeout)
    final_px = float(x.iloc[last + 1]["open"])
    exit_j = last + 1
    reason = "TIMEOUT_NEXT_OPEN"
    for j in range(i + 1, last + 1):
        row = x.iloc[j]
        hi, lo = float(row["high"]), float(row["low"])
        if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
            final_px, exit_j, reason = stop, j, "EMERGENCY_2ATR_STOP"
            break
        rsi2 = float(row["rsi2"])
        close = float(row["close"])
        sma5 = float(row["sma5"])
        if exit_mode == "RSI2":
            exit_sig = rsi2 > 70.0 if side == 1 else rsi2 < 30.0
        else:
            exit_sig = close > sma5 if side == 1 else close < sma5
        if exit_sig and j + 1 < len(x):
            final_px, exit_j, reason = (
                float(x.iloc[j + 1]["open"]),
                j + 1,
                f"{exit_mode}_DYNAMIC_EXIT",
            )
            break
    gross = side * (final_px - entry) / entry * 10_000.0
    return {
        "signal_ts": int(x.iloc[i]["ts_ms"]),
        "entry_ts": int(x.iloc[i + 1]["ts_ms"]),
        "exit_ts": int(x.iloc[exit_j]["ts_ms"]),
        "side": side_name,
        "entry": entry,
        "exit": final_px,
        "gross_bps": gross,
        "cost_bps": cost,
        "net_bps": gross - cost,
        "reason": reason,
    }, exit_j


def replay_shannon(
    frames: dict[str, pd.DataFrame], costs: dict[str, float], tf: int, partial: bool
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    for sym in SYMS:
        x = frames[sym]
        i = 241 if tf == 1_800_000 else 121
        while i < len(x) - 2:
            side = shannon_signal(x, i)
            if side == "flat":
                i += 1
                continue
            trade, exit_j = shannon_trade(x, i, side, costs[sym], partial, tf)
            if trade is not None:
                trade["symbol"] = sym
                trades.append(trade)
            i = max(i + 1, exit_j + 1)
    return {
        "metrics": metrics(trades),
        "split": v2.split_metrics(trades),
        "trades": trades,
    }


def replay_connors(
    frames: dict[str, pd.DataFrame],
    costs: dict[str, float],
    tf: int,
    daily: dict[str, tuple[list[int], list[float], list[float]]],
    exit_mode: str,
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    for sym in SYMS:
        x = frames[sym]
        i = 201
        while i < len(x) - 2:
            trend = daily_trend(daily[sym], int(x.iloc[i]["ts_ms"]))
            rsi2 = float(x.iloc[i]["rsi2"])
            side = (
                "long"
                if trend > 0 and rsi2 < 5.0
                else ("short" if trend < 0 and rsi2 > 95.0 else "flat")
            )
            if side == "flat":
                i += 1
                continue
            trade, exit_j = connors_trade(x, i, side, costs[sym], exit_mode, tf)
            if trade is not None:
                trade["symbol"] = sym
                trades.append(trade)
            i = max(i + 1, exit_j + 1)
    return {
        "metrics": metrics(trades),
        "split": v2.split_metrics(trades),
        "trades": trades,
    }


def compact(name: str, tf: int, result: dict[str, Any]) -> dict[str, Any]:
    m = result["metrics"]
    h = result["split"]["holdout40"]
    return {
        "name": name,
        "timeframe": "30m" if tf == 1_800_000 else "1h",
        "T": m["T"],
        "WR": m["WR"],
        "GrossExp_bps_T": m["GrossExp_bps_T"],
        "NetExp_bps_T": m["Exp_bps_T"],
        "PF": m["PF"],
        "DD_bps": m["DD_bps"],
        "HoldT": h["T"],
        "HoldGrossExp_bps_T": h["GrossExp_bps_T"],
        "HoldNetExp_bps_T": h["Exp_bps_T"],
        "HoldPF": h["PF"],
    }


def main() -> int:
    costs = frozen_costs()
    daily = daily_context()
    rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    for tf in TF_CASES:
        frames = prepare_frames(tf)
        for partial in (False, True):
            key = f"shannon_{'partial33_1r' if partial else 'runner_only'}_{'30m' if tf == 1_800_000 else '1h'}"
            result = replay_shannon(frames, costs, tf, partial)
            rows.append(compact(key, tf, result))
            details[key] = result
            print("SHANNON_V11=" + json.dumps(rows[-1], sort_keys=True), flush=True)
        for mode in ("RSI2", "SMA5"):
            key = f"connors_{mode.lower()}_{'30m' if tf == 1_800_000 else '1h'}"
            result = replay_connors(frames, costs, tf, daily, mode)
            rows.append(compact(key, tf, result))
            details[key] = result
            print("CONNORS_V11=" + json.dumps(rows[-1], sort_keys=True), flush=True)
    report = {
        "schema": "zel.a1.benchmark_web.shannon_connors.v11",
        "state": "DEV_REPLAY_COMPLETE",
        "source_ids": ["SHANNON_ALPHATRENDS_PRIMARY", "CONNORS_TRADINGMARKETS_PRIMARY"],
        "source_translation": {
            "shannon": "market structure + rising/falling 5-day MA + objective AVWAP from recent low/high + fresh momentum; optional first-third risk reduction; AVWAP/trend runner exit",
            "connors": "completed-daily 200MA direction + intraday RSI2 extreme (<5/>95) + dynamic RSI2 or SMA5 exit; 2ATR emergency stop is crypto risk adaptation",
        },
        "threshold_authority": "PUBLIC_DONOR_RULE_WHERE_AVAILABLE; INTRADAY_TIMEFRAME_AND_EMERGENCY_STOP_ARE_IMPLEMENTATION_TRANSLATIONS",
        "frozen_costs_bps": costs,
        "rows": rows,
        "details": details,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    out = Path("/home/z/z/runtime/benchmark_web_shannon_connors_v11.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
