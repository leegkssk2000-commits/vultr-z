from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from backend.research.rebuild import a1_benchmark6_architecture_v2 as base
from backend.research.rebuild import a1_benchmark6_architecture_v3 as fast


def reclaim(
    d: pd.DataFrame,
    vol: float = 0.1,
    dist: float = 0.5,
    body: float = 0.15,
    rr: float = 2.2,
):
    hi = d.high.shift(2).rolling(50).max()
    lo = d.low.shift(2).rolling(50).min()
    p = d.shift(1)
    v = pd.concat([d.volr, p.volr], axis=1).max(axis=1)
    long_break = (
        (p.close > hi + 0.10 * p.atr)
        & (p.high > hi)
        & (p.close > p.e34)
        & (p.e34 > d.e34.shift(2))
    )
    short_break = (
        (p.close < lo - 0.10 * p.atr)
        & (p.low < lo)
        & (p.close < p.e34)
        & (p.e34 < d.e34.shift(2))
    )
    long = (
        long_break
        & (d.low <= hi + 0.15 * d.atr)
        & (d.close > hi + 0.05 * d.atr)
        & (d.close > d.open + body * d.atr)
        & (d.close > d.e34)
        & (v >= vol)
    )
    short = (
        short_break
        & (d.high >= lo - 0.15 * d.atr)
        & (d.close < lo - 0.05 * d.atr)
        & (d.close < d.open - body * d.atr)
        & (d.close < d.e34)
        & (v >= vol)
    )
    level = pd.Series(0.0, index=d.index)
    level[long] = hi[long]
    level[short] = lo[short]
    ok = d.atrpct.between(0.18, 6.2) & (
        ((d.close - level).abs() / d.atr <= dist) | (~(long | short))
    )
    return ok & long, ok & short, 0.90, rr, 18


def main() -> int:
    data = {s: base.load(s) for s in base.SYMS}
    res = {}
    for name, args in {
        "tightA": (1.2, 0.50, 0.10, 2.2),
        "tightB": (1.4, 0.45, 0.15, 2.2),
        "tightC": (1.6, 0.40, 0.20, 2.4),
    }.items():

        def fn(d, a=args):
            return reclaim(d, *a)

        m = fast.collect(data, fn)
        res[name] = m
        print("SR_FOCUS", name, json.dumps(m, sort_keys=True), flush=True)
    out = Path("/home/z/z/runtime/sr_levels_reclaim_focus_v1.json")
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
