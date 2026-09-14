# mypy: follow_imports=skip

from __future__ import annotations

import argparse
from collections import deque
import gzip
import importlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd

cost_ev: Any = importlib.import_module(
    "backend.research.rebuild." + "a1_exact25_generic_evaluator_three_lane_v1"
)


REBUILD_DIR = Path(__file__).resolve().parent
if str(REBUILD_DIR) not in sys.path:
    sys.path.insert(0, str(REBUILD_DIR))
_native_policy: Any = importlib.import_module("benchmark25_donor_native_policy_v1")
load_spec = _native_policy.load_spec

ROOT = Path(__file__).resolve().parents[3]
CACHE = Path("/home/z/z/runtime/three_lane_5m_180d_v2")
MICRO = Path("/home/z/z/runtime/benchmark6_micro_5m_v1.jsonl.gz")
SYMS6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
MICRO_REQUIRED = {"liquidity_sweep", "scalp_snap", "vol_spike_fade", "vwap_revert"}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_5m() -> dict[str, pd.DataFrame]:
    manifest = read_json(CACHE / "MANIFEST.json")
    if manifest.get("state") != "PASS_SHARED_CACHE_COMPLETE":
        raise RuntimeError("SHARED_CACHE_NOT_COMPLETE")
    out: dict[str, pd.DataFrame] = {}
    for symbol in SYMS6:
        path = CACHE / "data" / f"{symbol.replace('-', '')}_5m.jsonl.gz"
        rows = []
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                x = json.loads(line)
                rows.append(
                    (
                        int(x["timestamp_ms"]),
                        float(x["open"]),
                        float(x["high"]),
                        float(x["low"]),
                        float(x["close"]),
                        float(x["volume"]),
                    )
                )
        out[symbol] = pd.DataFrame(
            rows, columns=["ts_ms", "open", "high", "low", "close", "volume"]
        )
    return out


def resample_frame(df: pd.DataFrame, factor: int) -> pd.DataFrame:
    if factor == 1:
        return df.copy()
    n = len(df) // factor * factor
    x = df.iloc[:n].copy()
    group = np.arange(n) // factor
    return (
        x.groupby(group, sort=True)
        .agg(
            ts_ms=("ts_ms", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index(drop=True)
    )


def wilder_atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    h, low, c = df["high"], df["low"], df["close"]
    prev = c.shift(1)
    tr = (
        pd.concat([(h - low), (h - prev).abs(), (low - prev).abs()], axis=1)
        .max(axis=1)
        .to_numpy(float)
    )
    out = np.full(len(tr), np.nan)
    if len(tr) < length:
        return pd.Series(out, index=df.index)
    cur = float(np.mean(tr[:length]))
    out[length - 1] = cur
    for i in range(length, len(tr)):
        cur = ((length - 1) * cur + tr[i]) / length
        out[i] = cur
    return pd.Series(out, index=df.index)


def rolling_anchor_vwap(df: pd.DataFrame, window: int, want_min: bool) -> pd.Series:
    lowhigh = df["low"].to_numpy(float) if want_min else df["high"].to_numpy(float)
    tp = ((df["high"] + df["low"] + df["close"]) / 3.0).to_numpy(float)
    vol = df["volume"].to_numpy(float)
    pv = tp * vol
    cpv = np.cumsum(pv)
    cv = np.cumsum(vol)
    out = np.full(len(df), np.nan)
    q: deque[int] = deque()
    for i, value in enumerate(lowhigh):
        while q and q[0] < i - window + 1:
            q.popleft()
        while q and (
            (lowhigh[q[-1]] >= value) if want_min else (lowhigh[q[-1]] <= value)
        ):
            q.pop()
        q.append(i)
        j = q[0]
        num = cpv[i] - (cpv[j - 1] if j else 0.0)
        den = cv[i] - (cv[j - 1] if j else 0.0)
        if den > 0:
            out[i] = num / den
    return pd.Series(out, index=df.index)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["atr"] = wilder_atr(x, 14)
    for n in (8, 21, 34, 50, 55, 100):
        x[f"ema{n}"] = x["close"].ewm(span=n, adjust=False).mean()
    x["hi20"] = x["high"].shift(1).rolling(20).max()
    x["lo20"] = x["low"].shift(1).rolling(20).min()
    x["hi50"] = x["high"].shift(1).rolling(50).max()
    x["lo50"] = x["low"].shift(1).rolling(50).min()
    x["hi_pre"] = x["high"].shift(2).rolling(20).max()
    x["lo_pre"] = x["low"].shift(2).rolling(20).min()
    x["mean20"] = x["close"].rolling(20).mean()
    x["sd20"] = x["close"].rolling(20).std(ddof=0)
    x["bb_width_atr"] = 4 * x["sd20"] / x["atr"]
    x["bb_prev_width_atr"] = x["bb_width_atr"].shift(1)
    x["rel_vol20"] = x["volume"] / x["volume"].shift(1).rolling(20).mean()
    x["rel_vol50"] = x["volume"] / x["volume"].shift(1).rolling(50).mean()
    tp = (x["high"] + x["low"] + x["close"]) / 3.0
    for n in (20, 50):
        x[f"vwap{n}"] = (tp * x["volume"]).rolling(n).sum() / x["volume"].rolling(
            n
        ).sum()
    x["avwap_long"] = rolling_anchor_vwap(x, 120, True)
    x["avwap_short"] = rolling_anchor_vwap(x, 120, False)
    delta = x["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    x["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    x["rsi_prev"] = x["rsi"].shift(1)
    sign = np.sign(delta.fillna(0))
    x["obv"] = (sign * x["volume"]).cumsum()
    x["obv_delta34"] = x["obv"] - x["obv"].shift(34)
    raw = tp * x["volume"]
    pos = raw.where(tp.diff() > 0, 0.0)
    neg = raw.where(tp.diff() < 0, 0.0)
    ratio = pos.rolling(14).sum() / neg.rolling(14).sum().replace(0, np.nan)
    x["mfi"] = 100 - 100 / (1 + ratio)
    x["mfi_prev"] = x["mfi"].shift(1)
    x["hour"] = pd.to_datetime(x["ts_ms"], unit="ms", utc=True).dt.hour
    return x


def load_micro() -> dict[str, pd.DataFrame]:
    rows: dict[str, list[dict[str, Any]]] = {"BTC-USDT": [], "ETH-USDT": []}
    with gzip.open(MICRO, "rt", encoding="utf-8") as handle:
        for line in handle:
            z = json.loads(line)
            sym = str(z.get("symbol"))
            if sym in rows:
                rows[sym].append(z)
    out = {}
    for sym, xs in rows.items():
        if not xs:
            continue
        out[sym] = pd.DataFrame(xs).set_index("ts_ms").sort_index()
    return out


def micro_columns(df: pd.DataFrame, micro: pd.DataFrame | None) -> pd.DataFrame:
    x = df.copy()
    for col in (
        "trade_imbalance",
        "imbalance_delta",
        "bid_change",
        "ask_change",
        "depth_messages",
        "trade_messages",
    ):
        x[f"m_{col}"] = np.nan
    if micro is None or micro.empty:
        return x
    idx = x["ts_ms"].astype(int)
    for col in (
        "trade_imbalance",
        "imbalance_delta",
        "bid_change",
        "ask_change",
        "depth_messages",
        "trade_messages",
    ):
        if col in micro.columns:
            x[f"m_{col}"] = idx.map(micro[col])
    return x


def micro_align_mask(x: pd.DataFrame, side: str) -> pd.Series:
    valid = (
        (x["m_depth_messages"].fillna(0) > 0)
        & (x["m_trade_messages"].fillna(0) > 0)
        & x["m_trade_imbalance"].notna()
    )
    ti = x["m_trade_imbalance"].fillna(0)
    im = x["m_imbalance_delta"].fillna(0)
    bc = x["m_bid_change"].fillna(0)
    ac = x["m_ask_change"].fillna(0)
    return valid & (
        (ti > 0) & ((im > 0) | (bc > 0))
        if side == "long"
        else (ti < 0) & ((im < 0) | (ac > 0))
    )


def signal_masks(sid: str, x: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    a = x["atr"]
    c = x["close"]
    p = c.shift(1)
    ph = x["high"].shift(1)
    pl = x["low"].shift(1)
    trend_l = (
        (c > x["ema21"])
        & (x["ema21"] > x["ema55"])
        & (x["ema55"] > x["ema100"])
        & (x["ema21"] >= x["ema21"].shift(1))
    )
    trend_s = (
        (c < x["ema21"])
        & (x["ema21"] < x["ema55"])
        & (x["ema55"] < x["ema100"])
        & (x["ema21"] <= x["ema21"].shift(1))
    )
    mode = pd.Series("DEFAULT", index=x.index, dtype=object)
    false = pd.Series(False, index=x.index)
    if sid == "turtle_trend":
        return c > x["hi20"], c < x["lo20"], mode
    if sid == "bb_revert":
        flat = (x["ema21"] - x["ema55"]).abs() / a <= 0.65
        lo = x["mean20"] - 1.8 * x["sd20"]
        hi = x["mean20"] + 1.8 * x["sd20"]
        return (
            flat & (pl < lo) & (c > lo) & (c > p),
            flat & (ph > hi) & (c < hi) & (c < p),
            mode,
        )
    if sid == "anchor_vwap_trend":
        return (
            (x["ema21"] > x["ema55"])
            & (p <= x["avwap_long"])
            & (c > x["avwap_long"])
            & (x["rel_vol20"] >= 0.8),
            (x["ema21"] < x["ema55"])
            & (p >= x["avwap_short"])
            & (c < x["avwap_short"])
            & (x["rel_vol20"] >= 0.8),
            mode,
        )
    if sid == "vwap_revert":
        return (
            (p < x["vwap20"] - 0.7 * a) & (c > p) & micro_align_mask(x, "long"),
            (p > x["vwap20"] + 0.7 * a) & (c < p) & micro_align_mask(x, "short"),
            mode,
        )
    if sid == "break_and_continue":
        comp = x["bb_prev_width_atr"] <= 3.0
        dist = (c - x["ema21"]).abs() / a <= 1.5
        return (
            comp
            & (ph > x["hi_pre"])
            & (x["low"] <= x["hi_pre"] + 0.35 * a)
            & (c > x["hi_pre"])
            & dist,
            comp
            & (pl < x["lo_pre"])
            & (x["high"] >= x["lo_pre"] - 0.35 * a)
            & (c < x["lo_pre"])
            & dist,
            mode,
        )
    if sid == "keltner_trend":
        dist = (c - x["ema21"]).abs() / a
        return (
            trend_l
            & (c > x["ema21"] + 1.2 * a)
            & ((x["high"] - x["low"]) / a >= 0.8)
            & (dist <= 1.6),
            trend_s
            & (c < x["ema21"] - 1.2 * a)
            & ((x["high"] - x["low"]) / a >= 0.8)
            & (dist <= 1.6),
            mode,
        )
    if sid == "squeeze_break":
        comp = x["bb_prev_width_atr"] <= 2.2
        rng = (x["high"] - x["low"]) / a
        dist = (c - x["ema21"]).abs() / a <= 1.5
        return (
            comp & (rng >= 0.9) & (c > x["hi20"]) & (c > x["ema21"]) & dist,
            comp & (rng >= 0.9) & (c < x["lo20"]) & (c < x["ema21"]) & dist,
            mode,
        )
    if sid == "supertrend_pullback":
        return (
            trend_l & (p <= x["ema21"] + 0.6 * a) & (c > p) & (c > x["ema21"]),
            trend_s & (p >= x["ema21"] - 0.6 * a) & (c < p) & (c < x["ema21"]),
            mode,
        )
    if sid == "trend_ma_macd":
        m = (
            x["close"].ewm(span=12, adjust=False).mean()
            - x["close"].ewm(span=26, adjust=False).mean()
        )
        sig = m.ewm(span=9, adjust=False).mean()
        h = m - sig
        dist = (c - x["ema21"]).abs() / a <= 1.25
        return (
            trend_l & (h > 0) & (h.shift(1) <= 0) & dist,
            trend_s & (h < 0) & (h.shift(1) >= 0) & dist,
            mode,
        )
    if sid == "trend_rider":
        return (
            trend_l
            & (x["ema50"] >= x["ema50"].shift(1))
            & (p <= x["ema21"] + 0.8 * a)
            & (c > p)
            & ((c - x["ema21"]).abs() / a <= 1.6),
            trend_s
            & (x["ema50"] <= x["ema50"].shift(1))
            & (p >= x["ema21"] - 0.8 * a)
            & (c < p)
            & ((c - x["ema21"]).abs() / a <= 1.6),
            mode,
        )
    if sid == "liquidity_sweep":
        return (
            (x["low"] < x["lo20"]) & (c > x["lo20"]) & micro_align_mask(x, "long"),
            (x["high"] > x["hi20"]) & (c < x["hi20"]) & micro_align_mask(x, "short"),
            mode,
        )
    if sid == "scalp_snap":
        c3 = c.shift(2)
        m1 = p - c3
        m2 = c - p
        return (
            (m1 <= -0.9 * a) & (m2 >= 0.4 * a) & micro_align_mask(x, "long"),
            (m1 >= 0.9 * a) & (m2 <= -0.4 * a) & micro_align_mask(x, "short"),
            mode,
        )
    if sid == "vol_spike_fade":
        pv = x["volume"].shift(1)
        vm = x["volume"].shift(2).rolling(20).mean()
        pr = ph - pl
        po = x["open"].shift(1)
        ti = x["m_trade_imbalance"].fillna(0)
        im = x["m_imbalance_delta"].fillna(0)
        valid = (x["m_depth_messages"].fillna(0) > 0) & (
            x["m_trade_messages"].fillna(0) > 0
        )
        return (
            valid
            & (pv >= 1.8 * vm)
            & (pr >= 1.2 * a)
            & (p < po)
            & (c > p)
            & (ti >= -0.05)
            & (im > 0),
            valid
            & (pv >= 1.8 * vm)
            & (pr >= 1.2 * a)
            & (p > po)
            & (c < p)
            & (ti <= 0.05)
            & (im < 0),
            mode,
        )
    if sid == "range_fade":
        flat = (x["ema21"] - x["ema55"]).abs() / a <= 0.7
        return (
            flat & (x["low"] < x["lo20"]) & (c > x["lo20"]),
            flat & (x["high"] > x["hi20"]) & (c < x["hi20"]),
            mode,
        )
    if sid == "fvg_revert":
        pr = ph - pl
        mid = (ph + pl) / 2
        po = x["open"].shift(1)
        return (
            (pr >= 1.3 * a) & (p < po) & (c > mid),
            (pr >= 1.3 * a) & (p > po) & (c < mid),
            mode,
        )
    if sid == "pivot_reversal":
        return (
            (x["low"] < x["lo20"]) & (c > x["lo20"]) & (c >= x["vwap20"]),
            (x["high"] > x["hi20"]) & (c < x["hi20"]) & (c <= x["vwap20"]),
            mode,
        )
    if sid == "rsi_swing_fail":
        flat = (x["ema21"] - x["ema55"]).abs() / a <= 1.2
        return (
            flat
            & (x["low"] < x["lo20"])
            & (c > x["lo20"])
            & (x["rsi"] > x["rsi_prev"]),
            flat
            & (x["high"] > x["hi20"])
            & (c < x["hi20"])
            & (x["rsi"] < x["rsi_prev"]),
            mode,
        )
    if sid == "alpha_combo":
        gap = (x["ema21"] - x["ema55"]).abs() / a
        mom = gap >= 0.7
        ml = mom & trend_l & (c > x["hi20"]) & (x["rel_vol20"] >= 1.0)
        ms = mom & trend_s & (c < x["lo20"]) & (x["rel_vol20"] >= 1.0)
        rl = (~mom) & (p < x["vwap20"] - 0.6 * a) & (c > p)
        rs = (~mom) & (p > x["vwap20"] + 0.6 * a) & (c < p)
        mode.loc[ml | ms] = "MOMENTUM_REGIME"
        mode.loc[rl | rs] = "MEAN_REVERSION_REGIME"
        return ml | rl, ms | rs, mode
    if sid == "ema_ribbon_scalp":
        sep = ((x["ema8"] - x["ema21"]).abs() + (x["ema21"] - x["ema55"]).abs()) / a
        dist = (c - x["ema21"]).abs() / a
        return (
            (c > x["ema8"])
            & (x["ema8"] > x["ema21"])
            & (x["ema21"] > x["ema55"])
            & (sep >= 0.2)
            & (p <= x["ema8"] + 0.4 * a)
            & (c > p)
            & (dist <= 0.85),
            (c < x["ema8"])
            & (x["ema8"] < x["ema21"])
            & (x["ema21"] < x["ema55"])
            & (sep >= 0.2)
            & (p >= x["ema8"] - 0.4 * a)
            & (c < p)
            & (dist <= 0.85),
            mode,
        )
    if sid == "mfi_rsi_div":
        return (
            (x["low"] <= x["lo50"])
            & (c > p)
            & (x["rsi"] > x["rsi_prev"])
            & (x["mfi"] > x["mfi_prev"]),
            (x["high"] >= x["hi50"])
            & (c < p)
            & (x["rsi"] < x["rsi_prev"])
            & (x["mfi"] < x["mfi_prev"]),
            mode,
        )
    if sid == "obv_trend":
        return (
            trend_l
            & (c > x["hi20"])
            & (x["rel_vol20"] >= 1.15)
            & (x["obv_delta34"] > 0),
            trend_s
            & (c < x["lo20"])
            & (x["rel_vol20"] >= 1.15)
            & (x["obv_delta34"] < 0),
            mode,
        )
    if sid == "grid_rebalance":
        flat = (x["ema21"] - x["ema55"]).abs() / a <= 0.7
        ext = (c - x["vwap50"]) / a
        return flat & (ext <= -0.9) & (c > p), flat & (ext >= 0.9) & (c < p), mode
    if sid == "rbreaker_like":
        bl = (c > x["hi20"]) & (x["rel_vol20"] >= 1.0)
        bs = (c < x["lo20"]) & (x["rel_vol20"] >= 1.0)
        fl = (x["low"] < x["lo20"]) & (c > x["lo20"])
        fs = (x["high"] > x["hi20"]) & (c < x["hi20"])
        mode.loc[bl | bs] = "BREAKOUT"
        mode.loc[fl | fs] = "FAILED_BREAK_REVERSAL"
        return bl | fl, bs | fs, mode
    if sid == "session_bias":
        liquid = (
            (x["rel_vol20"] >= 1.05)
            & ((x["high"] - x["low"]) / a >= 0.8)
            & (~x["hour"].isin([21, 22, 23]))
        )
        return liquid & (c > x["hi20"]), liquid & (c < x["lo20"]), mode
    if sid == "sr_levels":
        cl = (c > x["hi50"]) & (x["rel_vol50"] >= 1.25)
        cs = (c < x["lo50"]) & (x["rel_vol50"] >= 1.25)
        rl = (
            (ph > x["hi50"])
            & (x["low"] <= x["hi50"])
            & (c > x["hi50"])
            & (x["rel_vol50"] >= 1.0)
        )
        rs = (
            (pl < x["lo50"])
            & (x["high"] >= x["lo50"])
            & (c < x["lo50"])
            & (x["rel_vol50"] >= 1.0)
        )
        mode.loc[cl | cs] = "CONTINUATION"
        mode.loc[rl | rs] = "BREAK_RECLAIM"
        return cl | rl, cs | rs, mode
    return false, false, mode


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(t["net_bps"]) for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    eq = peak = dd = 0.0
    for v in vals:
        eq += v
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "T": len(vals),
        "WR": len(wins) / len(vals) if vals else None,
        "Net_bps": sum(vals),
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": sum(wins) / sum(losses) if losses else None,
        "DD_bps": dd,
    }


def target_price(
    sid: str,
    row: pd.Series,
    entry: float,
    side: int,
    risk: float,
    spec: Mapping[str, Any],
) -> float | None:
    mode = str(spec.get("target_mode"))
    if mode == "rolling_mean20":
        target = float(row["mean20"])
    elif mode == "vwap20":
        target = float(row["vwap20"])
    elif mode == "vwap50":
        target = float(row["vwap50"])
    elif mode == "runner_no_fixed_tp":
        return None
    else:
        rr = spec.get("target_r")
        return None if rr is None else entry + side * float(rr) * risk
    if side == 1 and target <= entry:
        return entry + max(risk, 0.5 * float(row["atr"]))
    if side == -1 and target >= entry:
        return entry - max(risk, 0.5 * float(row["atr"]))
    return target


def initial_stop(
    sid: str, x: pd.DataFrame, i: int, entry: float, side: int, spec: Mapping[str, Any]
) -> float:
    row = x.iloc[i]
    a = float(row["atr"])
    mode = str(spec.get("stop_mode"))
    fallback = entry - side * float(spec["stop_atr_mult"]) * a
    candidate = fallback
    if mode == "event_extreme_plus_atr_buffer":
        lo = min(float(row["low"]), float(x.iloc[i - 1]["low"]))
        hi = max(float(row["high"]), float(x.iloc[i - 1]["high"]))
        candidate = lo - 0.15 * a if side == 1 else hi + 0.15 * a
    elif mode == "reference_failure_plus_atr_buffer":
        if sid == "ema_ribbon_scalp":
            candidate = (
                min(float(row["low"]), float(row["ema21"])) - 0.15 * a
                if side == 1
                else max(float(row["high"]), float(row["ema21"])) + 0.15 * a
            )
        else:
            ref = float(row["hi20"] if side == 1 else row["lo20"])
            candidate = ref - 0.25 * a if side == 1 else ref + 0.25 * a
    if (
        (side == 1 and candidate >= entry)
        or (side == -1 and candidate <= entry)
        or not np.isfinite(candidate)
    ):
        candidate = fallback
    if (side == 1 and candidate >= entry) or (side == -1 and candidate <= entry):
        raise RuntimeError("STOP_NOT_ADVERSE_TO_ENTRY")
    return float(candidate)


def simulate_trade(
    sid: str,
    x: pd.DataFrame,
    i: int,
    side_name: str,
    mode_name: str,
    spec: Mapping[str, Any],
    cost_bps: float,
) -> tuple[dict[str, Any] | None, int]:
    if i + 1 >= len(x):
        return None, i
    side = 1 if side_name == "long" else -1
    entry = float(x.iloc[i + 1]["open"])
    entry_ts = int(x.iloc[i + 1]["ts_ms"])
    stop = initial_stop(sid, x, i, entry, side, spec)
    risk = abs(entry - stop)
    if risk <= 0 or not np.isfinite(risk):
        return None, i
    tp = target_price(sid, x.iloc[i], entry, side, risk, spec)
    timeout = int(spec["timeout_bars"])
    scratch_b = int(spec["scratch_after_bars"])
    scratch_r = float(spec["scratch_if_mfe_below_r"])
    ta = spec.get("trail_activate_r")
    td = spec.get("trail_atr_mult")
    mfe = 0.0
    trail = None
    peak = entry
    last = min(len(x) - 1, i + 1 + timeout)
    exit_px = None
    exit_j = None
    reason = None
    for j in range(i + 1, last + 1):
        row = x.iloc[j]
        hi = float(row["high"])
        lo = float(row["low"])
        close = float(row["close"])
        if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
            exit_px, exit_j, reason = stop, j, "SL"
            break
        if trail is not None and (
            (side == 1 and lo <= trail) or (side == -1 and hi >= trail)
        ):
            exit_px, exit_j, reason = trail, j, "TRAIL"
            break
        if tp is not None and ((side == 1 and hi >= tp) or (side == -1 and lo <= tp)):
            exit_px, exit_j, reason = tp, j, "TP"
            break
        fav = (hi - entry) / risk if side == 1 else (entry - lo) / risk
        mfe = max(mfe, fav)
        peak = max(peak, hi) if side == 1 else min(peak, lo)
        if ta is not None and td is not None and mfe >= float(ta):
            candidate = (
                peak - float(td) * float(row["atr"])
                if side == 1
                else peak + float(td) * float(row["atr"])
            )
            trail = (
                max(trail or -np.inf, candidate)
                if side == 1
                else min(trail or np.inf, candidate)
            )
        if sid == "turtle_trend" and j >= 10:
            don = (
                float(x.iloc[j - 9 : j + 1]["low"].min())
                if side == 1
                else float(x.iloc[j - 9 : j + 1]["high"].max())
            )
            trail = (
                max(trail or -np.inf, don) if side == 1 else min(trail or np.inf, don)
            )
        if j - (i + 1) + 1 >= scratch_b and mfe < scratch_r:
            exit_px, exit_j, reason = close, j, "NO_PROGRESS_SCRATCH"
            break
        if sid in MICRO_REQUIRED and not pd.isna(row.get("m_trade_imbalance", np.nan)):
            ti = float(row.get("m_trade_imbalance") or 0.0)
            im = float(row.get("m_imbalance_delta") or 0.0)
            adverse = (ti < -0.20 and im < 0) if side == 1 else (ti > 0.20 and im > 0)
            if adverse:
                exit_px, exit_j, reason = close, j, "FLOW_OPINION_CHANGE"
                break
    if exit_px is None:
        exit_j = last
        exit_px = float(x.iloc[last]["close"])
        reason = "TIMEOUT"
    assert exit_j is not None
    gross = side * (float(exit_px) - entry) / entry * 10000.0
    net = gross - cost_bps
    return {
        "strategy_id": sid,
        "side": side_name,
        "mode": mode_name,
        "signal_ts": int(x.iloc[i]["ts_ms"]),
        "entry_ts": entry_ts,
        "exit_ts": int(x.iloc[exit_j]["ts_ms"]),
        "entry": entry,
        "exit": float(exit_px),
        "reason": reason,
        "gross_bps": gross,
        "cost_bps": cost_bps,
        "net_bps": net,
        "mfe_r": mfe,
        "benchmark_ids": spec["benchmark_ids"],
        "transfer": spec["transfer"],
        "entry_source": "DONOR_NATIVE_NOT_PARENT",
        "exit_source": "DONOR_NATIVE_NOT_PARENT",
    }, int(exit_j)


def split_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        trades, key=lambda t: (int(t["exit_ts"]), str(t.get("symbol", "")))
    )
    cut = int(len(ordered) * 0.60)
    return {"train60": metrics(ordered[:cut]), "holdout40": metrics(ordered[cut:])}


def verdict(full: Mapping[str, Any], hold: Mapping[str, Any]) -> str:
    t = int(full.get("T") or 0)
    pf = full.get("PF")
    net = float(full.get("Net_bps") or 0.0)
    hpf = hold.get("PF")
    hnet = float(hold.get("Net_bps") or 0.0)
    if t < 30:
        return "HOLD_SPARSE"
    if (
        net > 0
        and pf is not None
        and pf > 1.0
        and hnet > 0
        and hpf is not None
        and hpf > 1.0
    ):
        return "PASS_DONOR_NATIVE_ECONOMIC"
    return "FAIL_DONOR_NATIVE_ECONOMIC"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()
    spec = load_spec()
    ids = list(spec["children"])
    selected = [
        sid for i, sid in enumerate(ids) if i % args.shard_count == args.shard_index
    ]
    if args.only is not None:
        if args.only not in spec["children"]:
            raise RuntimeError(f"UNKNOWN_CHILD:{args.only}")
        selected = [args.only]
    base = load_5m()
    micro = load_micro()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    enriched: dict[tuple[int, str], pd.DataFrame] = {}
    costs: dict[str, float] = {}
    authority = cost_ev.load_json(cost_ev.COST_PATH)
    for symbol in SYMS6:
        snapshot = cost_ev.fetch_execution_snapshot(symbol, authority)
        costs[symbol] = float(snapshot["pretrade_verified_cost_bps"])

    def frame(timeframe_ms: int, symbol: str) -> pd.DataFrame:
        key = (timeframe_ms, symbol)
        if key not in enriched:
            factor = {300000: 1, 900000: 3, 3600000: 12}[timeframe_ms]
            raw = resample_frame(base[symbol], factor)
            micro_frame = micro.get(symbol) if timeframe_ms == 300000 else None
            enriched[key] = enrich(micro_columns(raw, micro_frame))
        return enriched[key]

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for sid in selected:
        out = args.out_dir / f"{sid}.json"
        try:
            child = spec["children"][sid]
            timeframe_ms = int(child["timeframe_ms"])
            symbols = (
                ("BTC-USDT", "ETH-USDT") if child["microstructure_required"] else SYMS6
            )
            all_trades: list[dict[str, Any]] = []
            signal_count = 0
            for symbol in symbols:
                x = frame(timeframe_ms, symbol)
                long_mask, short_mask, mode_mask = signal_masks(sid, x)
                blocked_until = -1
                candidate_idx = np.flatnonzero(
                    (long_mask | short_mask).fillna(False).to_numpy()
                )
                for raw_i in candidate_idx:
                    i = int(raw_i)
                    if i < 120 or i <= blocked_until or i + 1 >= len(x):
                        continue
                    is_long = bool(long_mask.iloc[i])
                    is_short = bool(short_mask.iloc[i])
                    if is_long == is_short:
                        continue
                    signal_count += 1
                    trade, end_i = simulate_trade(
                        sid,
                        x,
                        i,
                        "long" if is_long else "short",
                        str(mode_mask.iloc[i]),
                        child,
                        costs[symbol],
                    )
                    if trade is not None:
                        trade["symbol"] = symbol
                        trade["child_id"] = child["child_id"]
                        all_trades.append(trade)
                        blocked_until = end_i

            full = metrics(all_trades)
            splits = split_metrics(all_trades)
            state = verdict(full, splits["holdout40"])
            result = {
                "schema": "zel.benchmark25.donor_native_replay.v1",
                "state": state,
                "strategy_id": sid,
                "child_id": child["child_id"],
                "timeframe": child["timeframe"],
                "benchmark_ids": child["benchmark_ids"],
                "transfer": child["transfer"],
                "entry_source": child["entry_source"],
                "exit_source": child["exit_source"],
                "lifecycle_source": child["lifecycle_source"],
                "microstructure_required": child["microstructure_required"],
                "symbols": list(symbols),
                "signal_count": signal_count,
                "metrics": full,
                "split": splits,
                "cost_mode": "CURRENT_VERIFIED_PRETRADE_ROUND_TRIP_COST_CONSERVATIVE",
                "cost_bps_by_symbol": {s: costs[s] for s in symbols},
                "trades": all_trades,
                "research_only": True,
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "live_trade_authority": "BLOCKED",
            }
            out.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            rows.append(result)
            print(
                "NATIVE25_ROW="
                + json.dumps(
                    {
                        "strategy_id": sid,
                        "state": state,
                        "metrics": full,
                        "holdout": splits["holdout40"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:
            err = {"strategy_id": sid, "error": f"{type(exc).__name__}:{exc}"}
            errors.append(err)
            print("NATIVE25_ERROR=" + json.dumps(err, sort_keys=True), flush=True)

    report = {
        "schema": "zel.benchmark25.donor_native_shard.v1",
        "state": "PASS" if rows and not errors else "PARTIAL" if rows else "HOLD",
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "requested": selected,
        "success_count": len(rows),
        "error_count": len(errors),
        "errors": errors,
        "strategies": [
            {
                "strategy_id": r["strategy_id"],
                "state": r["state"],
                "metrics": r["metrics"],
            }
            for r in rows
        ],
    }
    (args.out_dir / "REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "NATIVE25_DONE="
        + json.dumps(
            {"shard": args.shard_index, "success": len(rows), "errors": len(errors)},
            sort_keys=True,
        )
    )
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
