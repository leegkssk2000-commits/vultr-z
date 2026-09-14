from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from backend.research.rebuild import a1_benchmark6_architecture_v2 as base


def sim(
    sym: str,
    d: pd.DataFrame,
    long: pd.Series,
    short: pd.Series,
    stop_mult: float,
    rr: float,
    timeout: int,
):
    out = []
    blocked = -1
    sig = np.flatnonzero((long.fillna(False) | short.fillna(False)).to_numpy())
    o = d.open.to_numpy()
    h = d.high.to_numpy()
    low_arr = d.low.to_numpy()
    c = d.close.to_numpy()
    a = d.atr.to_numpy()
    ts = d.ts.to_numpy()
    for i in sig:
        if i <= blocked or i + 1 >= len(d):
            continue
        side = 1 if bool(long.iloc[i]) else -1
        entry = float(o[i + 1])
        stop = float(c[i]) - side * stop_mult * float(a[i])
        tp = float(c[i]) + side * stop_mult * float(a[i]) * rr
        last = min(len(d) - 1, i + 1 + timeout)
        px = None
        jx = last
        reason = "TIMEOUT"
        for j in range(i + 1, last + 1):
            if (side == 1 and low_arr[j] <= stop) or (side == -1 and h[j] >= stop):
                px = stop
                jx = j
                reason = "SL"
                break
            if (side == 1 and h[j] >= tp) or (side == -1 and low_arr[j] <= tp):
                px = tp
                jx = j
                reason = "TP"
                break
        if px is None:
            px = float(c[last])
        out.append(
            {
                "symbol": sym,
                "signal_ts": int(ts[i]),
                "entry_ts": int(ts[i + 1]),
                "exit_ts": int(ts[jx]),
                "net": side * (px - entry) / entry * 10000 - base.COST,
                "reason": reason,
            }
        )
        blocked = jx
    return out


def collect(data, fn):
    tr = []
    for s, d in data.items():
        long, short, sm, rr, to = fn(d)
        tr += sim(s, d, long, short, sm, rr, to)
    return base.split(tr)


def ema_parent(d):
    p = d.shift(1)
    ok = (
        (d.atrpct.between(0.12, 4.8))
        & ((d.close - d.e21).abs() / d.atr <= 1.10)
        & (d.bodyatr >= 0.55)
    )
    long = (
        ok
        & (d.close > d.e8)
        & (d.e8 > d.e21)
        & (d.e21 > d.e55)
        & (d.e8 >= p.e8)
        & (d.e21 >= p.e21)
        & (d.close > p.close + 0.10 * d.atr)
    )
    short = (
        ok
        & (d.close < d.e8)
        & (d.e8 < d.e21)
        & (d.e21 < d.e55)
        & (d.e8 <= p.e8)
        & (d.e21 <= p.e21)
        & (d.close < p.close - 0.10 * d.atr)
    )
    return long, short, 0.75, 1.65, 36


def ema_child(d, tol=0.30, body=0.25, sepmin=0.12, sepmax=0.90, rr=2.0):
    p = d.shift(1)
    sep = ((d.e8 - d.e21).abs() + (d.e21 - d.e55).abs()) / d.atr
    ok = (
        d.atrpct.between(0.12, 4.8)
        & sep.between(sepmin, sepmax)
        & ((d.close - d.e21).abs() / d.atr <= 0.70)
        & (d.bodyatr >= body)
    )
    ls = (
        (d.close > d.e8)
        & (d.e8 > d.e21)
        & (d.e21 > d.e55)
        & (d.e8 >= p.e8)
        & (d.e21 >= p.e21)
    )
    ss = (
        (d.close < d.e8)
        & (d.e8 < d.e21)
        & (d.e21 < d.e55)
        & (d.e8 <= p.e8)
        & (d.e21 <= p.e21)
    )
    lp = (
        (p.low <= p.e21 + tol * p.atr)
        & (p.close >= p.e21 - 0.15 * p.atr)
        & (d.close > d.e8)
        & (d.close > d.open)
    )
    sp = (
        (p.high >= p.e21 - tol * p.atr)
        & (p.close <= p.e21 + 0.15 * p.atr)
        & (d.close < d.e8)
        & (d.close < d.open)
    )
    return ok & ls & lp, ok & ss & sp, 0.80, rr, 24


def session_parent(d):
    hi = d.high.shift(1).rolling(24).max()
    lo = d.low.shift(1).rolling(24).min()
    p = d.shift(1)
    ok = d.atrpct.between(0.18, 5.5) & ((d.close - d.e21).abs() / d.atr <= 1.70)
    long = (
        ok
        & (d.close > hi + 0.10 * d.atr)
        & (d.close > p.close + 0.16 * d.atr)
        & (d.close > d.e21)
        & (d.e21 > d.e55)
    )
    short = (
        ok
        & (d.close < lo - 0.10 * d.atr)
        & (d.close < p.close - 0.16 * d.atr)
        & (d.close < d.e21)
        & (d.e21 < d.e55)
    )
    return long, short, 1.15, 1.90, 36


def session_child(d, vol=1.15, range_atr=0.70, look=12, rr=2.0):
    hi = d.high.shift(1).rolling(look).max()
    lo = d.low.shift(1).rolling(look).min()
    hour = pd.to_datetime(d.ts, unit="ms", utc=True).dt.hour
    active = hour < 21
    rng = (d.high - d.low) / d.atr
    ok = (
        active
        & d.atrpct.between(0.18, 5.5)
        & (d.volr >= vol)
        & (rng >= range_atr)
        & ((d.close - d.e21).abs() / d.atr <= 1.30)
    )
    long = (
        ok
        & (d.close > hi + 0.05 * d.atr)
        & (d.close > d.e21)
        & (d.e21 > d.e55)
        & (d.close > d.open)
    )
    short = (
        ok
        & (d.close < lo - 0.05 * d.atr)
        & (d.close < d.e21)
        & (d.e21 < d.e55)
        & (d.close < d.open)
    )
    return long, short, 0.90, rr, 18


def sr_parent(d):
    hi = d.high.shift(1).rolling(50).max()
    lo = d.low.shift(1).rolling(50).min()
    p = d.shift(1)
    ok = (
        d.atrpct.between(0.22, 6.2)
        & ((d.close - d.e34).abs() / d.atr <= 1.80)
        & (d.volr >= 1.80)
    )
    long = ok & (d.close > hi + 0.12 * d.atr) & (d.close > d.e34) & (d.e34 > p.e34)
    short = ok & (d.close < lo - 0.12 * d.atr) & (d.close < d.e34) & (d.e34 < p.e34)
    return long, short, 1.20, 2.0, 36


def sr_child(d, rel=0.10, vol=1.20, rr=2.0):
    hi = d.high.shift(2).rolling(50).max()
    lo = d.low.shift(2).rolling(50).min()
    p = d.shift(1)
    v = pd.concat([d.volr, p.volr], axis=1).max(axis=1)
    lc = (
        (d.close > hi + 0.05 * d.atr)
        & (d.close > d.e34)
        & (d.e34 > p.e34)
        & (v >= 1.45)
    )
    sc = (
        (d.close < lo - 0.05 * d.atr)
        & (d.close < d.e34)
        & (d.e34 < p.e34)
        & (v >= 1.45)
    )
    lr = (
        (p.high > hi)
        & (d.close > hi + rel * d.atr)
        & (d.low <= hi + 0.25 * d.atr)
        & (d.close > d.e34)
        & (v >= vol)
    )
    sr = (
        (p.low < lo)
        & (d.close < lo - rel * d.atr)
        & (d.high >= lo - 0.25 * d.atr)
        & (d.close < d.e34)
        & (v >= vol)
    )
    long = lc | lr
    short = sc | sr
    level = pd.Series(np.where(long, hi, np.where(short, lo, d.close)), index=d.index)
    ok = d.atrpct.between(0.18, 6.2) & ((d.close - level).abs() / d.atr <= 0.90)
    return ok & long, ok & short, 1.0, rr, 24


def main() -> int:
    data = {s: base.load(s) for s in base.SYMS}
    tests = {
        "ema_ribbon_scalp": {
            "parent": ema_parent,
            "pullbackA": lambda d: ema_child(d, 0.30, 0.25, 0.12, 0.90, 2.0),
            "pullbackB": lambda d: ema_child(d, 0.45, 0.20, 0.08, 1.0, 1.8),
        },
        "session_bias": {
            "parent": session_parent,
            "handoffA": lambda d: session_child(d, 1.15, 0.70, 12, 2.0),
            "handoffB": lambda d: session_child(d, 1.05, 0.60, 18, 1.8),
        },
        "sr_levels": {
            "parent": sr_parent,
            "reclaimA": lambda d: sr_child(d, 0.10, 1.20, 2.0),
            "reclaimB": lambda d: sr_child(d, 0.05, 1.10, 1.8),
        },
    }
    res = {
        "schema": "zel.a1.benchmark6.architecture.v3",
        "research_only": True,
        "cost_bps": base.COST,
        "strategies": {},
    }
    for sid, vs in tests.items():
        item = {}
        for name, fn in vs.items():
            item[name] = collect(data, fn)
            print(
                "ARCH3", sid, name, json.dumps(item[name], sort_keys=True), flush=True
            )
        res["strategies"][sid] = item
    out = Path("/home/z/z/runtime/benchmark6_architecture_v3/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
