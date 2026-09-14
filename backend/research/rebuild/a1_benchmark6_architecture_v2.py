from __future__ import annotations
import gzip
import json
from pathlib import Path
from typing import Any, Callable
import pandas as pd

CACHE = Path("/home/z/z/runtime/three_lane_5m_180d_v2/data")
SYMS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
COST = 14.0


def load(sym: str) -> pd.DataFrame:
    rows = []
    p = CACHE / f"{sym.replace('-','')}_5m.jsonl.gz"
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    d = pd.DataFrame(rows).rename(columns={"timestamp_ms": "ts"})
    d["ts"] = d["ts"].astype("int64")
    for c in ["open", "high", "low", "close", "volume"]:
        d[c] = pd.to_numeric(d[c])
    pc = d["close"].shift(1)
    tr = pd.concat(
        [(d.high - d.low), (d.high - pc).abs(), (d.low - pc).abs()], axis=1
    ).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    for n in (8, 21, 34, 55):
        d[f"e{n}"] = d["close"].ewm(span=n, adjust=False).mean()
    d["volma50"] = d["volume"].rolling(50).mean()
    d["volr"] = d["volume"] / d["volma50"]
    d["bodyatr"] = (d["close"] - d["open"]).abs() / d["atr"]
    d["atrpct"] = d["atr"] / d["close"] * 100
    return d


def metrics(tr: list[dict[str, Any]]) -> dict[str, Any]:
    tr = sorted(tr, key=lambda x: (x["exit_ts"], x["symbol"]))
    v = [x["net"] for x in tr]
    w = [x for x in v if x > 0]
    losses = [-x for x in v if x < 0]
    eq = pk = dd = 0.0
    for x in v:
        eq += x
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    return {
        "T": len(v),
        "WR": len(w) / len(v) if v else None,
        "Net_bps": sum(v),
        "Exp_bps_T": sum(v) / len(v) if v else None,
        "PF": sum(w) / sum(losses) if losses else None,
        "DD_bps": dd,
    }


def split(tr: list[dict[str, Any]]) -> dict[str, Any]:
    tr = sorted(tr, key=lambda x: (x["exit_ts"], x["symbol"]))
    c = int(len(tr) * 0.6)
    return {
        "full": metrics(tr),
        "train60": metrics(tr[:c]),
        "holdout40": metrics(tr[c:]),
    }


def run_strategy(
    sym: str,
    d: pd.DataFrame,
    signal: Callable[[pd.DataFrame, int], tuple[int, float, float, float] | None],
) -> list[dict[str, Any]]:
    out = []
    blocked = -1
    n = len(d)
    for i in range(60, n - 1):
        if i <= blocked:
            continue
        s = signal(d, i)
        if not s:
            continue
        side, stop_mult, rr, timeout = s
        entry = float(d.open.iloc[i + 1])
        a = float(d.atr.iloc[i])
        sig = float(d.close.iloc[i])
        stop = sig - side * stop_mult * a
        tp = sig + side * (stop_mult * a * rr)
        last = min(n - 1, i + 1 + int(timeout))
        px = None
        reason = "TIMEOUT"
        jexit = last
        for j in range(i + 1, last + 1):
            lo = float(d.low.iloc[j])
            hi = float(d.high.iloc[j])
            if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
                px = stop
                reason = "SL"
                jexit = j
                break
            if (side == 1 and hi >= tp) or (side == -1 and lo <= tp):
                px = tp
                reason = "TP"
                jexit = j
                break
        if px is None:
            px = float(d.close.iloc[last])
        net = side * (px - entry) / entry * 10000 - COST
        out.append(
            {
                "symbol": sym,
                "signal_ts": int(d.ts.iloc[i]),
                "entry_ts": int(d.ts.iloc[i + 1]),
                "exit_ts": int(d.ts.iloc[jexit]),
                "net": net,
                "reason": reason,
            }
        )
        blocked = jexit
    return out


def ema_parent(d: pd.DataFrame, i: int):
    r = d.iloc[i]
    p = d.iloc[i - 1]
    a = float(r.atr)
    close = float(r.close)
    prev = float(p.close)
    long = (
        close > r.e8 > r.e21 > r.e55
        and r.e8 >= p.e8
        and r.e21 >= p.e21
        and close > prev + 0.10 * a
    )
    short = (
        close < r.e8 < r.e21 < r.e55
        and r.e8 <= p.e8
        and r.e21 <= p.e21
        and close < prev - 0.10 * a
    )
    ok = (
        0.12 <= r.atrpct <= 4.8 and abs(close - r.e21) / a <= 1.10 and r.bodyatr >= 0.55
    )
    return ((1 if long else -1), 0.75, 1.65, 36) if ok and long != short else None


def ema_child(
    d: pd.DataFrame, i: int, tol=0.30, body=0.25, sepmin=0.12, sepmax=0.90, rr=2.0
):
    r = d.iloc[i]
    p = d.iloc[i - 1]
    a = float(r.atr)
    ap = float(p.atr)
    close = float(r.close)
    sep = (abs(r.e8 - r.e21) + abs(r.e21 - r.e55)) / a
    long_state = close > r.e8 > r.e21 > r.e55 and r.e8 >= p.e8 and r.e21 >= p.e21
    short_state = close < r.e8 < r.e21 < r.e55 and r.e8 <= p.e8 and r.e21 <= p.e21
    long_pull = (
        float(p.low) <= float(p.e21) + tol * ap
        and float(p.close) >= float(p.e21) - 0.15 * ap
        and close > float(r.e8)
        and close > float(r.open)
    )
    short_pull = (
        float(p.high) >= float(p.e21) - tol * ap
        and float(p.close) <= float(p.e21) + 0.15 * ap
        and close < float(r.e8)
        and close < float(r.open)
    )
    ok = (
        0.12 <= r.atrpct <= 4.8
        and sepmin <= sep <= sepmax
        and abs(close - r.e21) / a <= 0.70
        and r.bodyatr >= body
    )
    return (
        ((1 if long_state and long_pull else -1), 0.80, rr, 24)
        if ok and (long_state and long_pull) != (short_state and short_pull)
        else None
    )


def session_parent(d: pd.DataFrame, i: int):
    r = d.iloc[i]
    a = float(r.atr)
    close = float(r.close)
    prev = float(d.close.iloc[i - 1])
    hi = float(d.high.iloc[i - 24 : i].max())
    lo = float(d.low.iloc[i - 24 : i].min())
    long = close > hi + 0.10 * a and close > prev + 0.16 * a and close > r.e21 > r.e55
    short = close < lo - 0.10 * a and close < prev - 0.16 * a and close < r.e21 < r.e55
    ok = 0.18 <= r.atrpct <= 5.5 and abs(close - r.e21) / a <= 1.70
    return ((1 if long else -1), 1.15, 1.90, 36) if ok and long != short else None


def session_child(d: pd.DataFrame, i: int, vol=1.15, range_atr=0.70, look=12, rr=2.0):
    r = d.iloc[i]
    a = float(r.atr)
    close = float(r.close)
    hour = pd.to_datetime(int(r.ts), unit="ms", utc=True).hour
    if hour >= 21 and hour < 24:
        return None
    hi = float(d.high.iloc[i - look : i].max())
    lo = float(d.low.iloc[i - look : i].min())
    bar_range = (float(r.high) - float(r.low)) / a
    long = close > hi + 0.05 * a and close > r.e21 > r.e55 and close > float(r.open)
    short = close < lo - 0.05 * a and close < r.e21 < r.e55 and close < float(r.open)
    ok = (
        0.18 <= r.atrpct <= 5.5
        and float(r.volr) >= vol
        and bar_range >= range_atr
        and abs(close - r.e21) / a <= 1.30
    )
    return ((1 if long else -1), 0.90, rr, 18) if ok and long != short else None


def sr_parent(d: pd.DataFrame, i: int):
    r = d.iloc[i]
    a = float(r.atr)
    close = float(r.close)
    hi = float(d.high.iloc[i - 50 : i].max())
    lo = float(d.low.iloc[i - 50 : i].min())
    long = (
        close > hi + 0.12 * a
        and r.volr >= 1.80
        and close > r.e34
        and r.e34 > d.e34.iloc[i - 1]
    )
    short = (
        close < lo - 0.12 * a
        and r.volr >= 1.80
        and close < r.e34
        and r.e34 < d.e34.iloc[i - 1]
    )
    ok = 0.22 <= r.atrpct <= 6.2 and abs(close - r.e34) / a <= 1.80
    return ((1 if long else -1), 1.20, 2.0, 36) if ok and long != short else None


def sr_child(d: pd.DataFrame, i: int, rel=0.1, vol=1.20, rr=2.0):
    r = d.iloc[i]
    p = d.iloc[i - 1]
    a = float(r.atr)
    close = float(r.close)
    hi = float(d.high.iloc[i - 51 : i - 1].max())
    lo = float(d.low.iloc[i - 51 : i - 1].min())
    v = max(float(r.volr), float(p.volr))
    long_cont = (
        close > hi + 0.05 * a
        and close > r.e34
        and r.e34 > d.e34.iloc[i - 1]
        and v >= 1.45
    )
    short_cont = (
        close < lo - 0.05 * a
        and close < r.e34
        and r.e34 < d.e34.iloc[i - 1]
        and v >= 1.45
    )
    long_reclaim = (
        float(p.high) > hi
        and close > hi + rel * a
        and float(r.low) <= hi + 0.25 * a
        and close > r.e34
        and v >= vol
    )
    short_reclaim = (
        float(p.low) < lo
        and close < lo - rel * a
        and float(r.high) >= lo - 0.25 * a
        and close < r.e34
        and v >= vol
    )
    long = long_cont or long_reclaim
    short = short_cont or short_reclaim
    level = hi if long else lo if short else close
    ok = 0.18 <= r.atrpct <= 6.2 and abs(close - level) / a <= 0.90
    return ((1 if long else -1), 1.0, rr, 24) if ok and long != short else None


def main() -> int:
    data = {s: load(s) for s in SYMS}
    tests = {
        "ema_ribbon_scalp": {
            "parent": ema_parent,
            "pullbackA": lambda d, i: ema_child(d, i, 0.30, 0.25, 0.12, 0.90, 2.0),
            "pullbackB": lambda d, i: ema_child(d, i, 0.45, 0.20, 0.08, 1.0, 1.8),
        },
        "session_bias": {
            "parent": session_parent,
            "handoffA": lambda d, i: session_child(d, i, 1.15, 0.70, 12, 2.0),
            "handoffB": lambda d, i: session_child(d, i, 1.05, 0.60, 18, 1.8),
        },
        "sr_levels": {
            "parent": sr_parent,
            "reclaimA": lambda d, i: sr_child(d, i, 0.10, 1.20, 2.0),
            "reclaimB": lambda d, i: sr_child(d, i, 0.05, 1.10, 1.8),
        },
    }
    res = {
        "schema": "zel.a1.benchmark6.architecture.v2",
        "cost_bps": COST,
        "research_only": True,
        "strategies": {},
    }
    for sid, variants in tests.items():
        item = {}
        for name, fn in variants.items():
            tr = []
            for s, d in data.items():
                tr += run_strategy(s, d, fn)
            item[name] = split(tr)
            print(
                "ARCH_ROW",
                sid,
                name,
                json.dumps(item[name], sort_keys=True),
                flush=True,
            )
        res["strategies"][sid] = item
    out = Path("/home/z/z/runtime/benchmark6_architecture_v2/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
