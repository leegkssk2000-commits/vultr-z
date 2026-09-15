from __future__ import annotations
import importlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
cr: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_crabel_orb_v8"
)
GATES = (
    "NONE",
    "TREND5_ALIGN",
    "PRIOR_CONTRACTION",
    "PRIOR_CONTRACTION_STRICT",
    "PRIOR_CLOSE_EDGE",
    "TREND5_CONTRACTION",
    "CONTRACTION_EDGE",
)


def dkey(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def features(sym: str, df: pd.DataFrame) -> dict[str, dict[str, float]]:
    rows: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(df["ts_ms"].astype(int)):
        rows[dkey(int(ts))].append(i)
    days = sorted(rows)
    out = {}
    closes = []
    ranges = []
    for p, day in enumerate(days):
        part = df.iloc[rows[day]]
        o = float(part.iloc[0]["open"])
        h = float(part["high"].max())
        low = float(part["low"].min())
        c = float(part.iloc[-1]["close"])
        rg = h - low
        closes.append(c)
        ranges.append(rg)
        if p < 10:
            continue
        avg10 = float(np.mean(ranges[p - 10 : p]))
        trend5 = (o - closes[p - 5]) / max(closes[p - 5], 1e-12)
        prev_h = float(df.iloc[rows[days[p - 1]]]["high"].max())
        prev_l = float(df.iloc[rows[days[p - 1]]]["low"].min())
        prev_c = float(df.iloc[rows[days[p - 1]][-1]]["close"])
        prev_r = max(prev_h - prev_l, 1e-12)
        clv = (prev_c - prev_l) / prev_r
        out[day] = {
            "prior_range_ratio": ranges[p - 1] / max(avg10, 1e-12),
            "trend5": trend5,
            "prior_clv": clv,
            "open": o,
        }
    return out


def allow(g: str, t: dict[str, Any], f: dict[str, float]) -> bool:
    side = 1 if t["side"] == "long" else -1
    align = (f["trend5"] * side) > 0
    contra = f["prior_range_ratio"] <= 1.0
    strict = f["prior_range_ratio"] <= 0.8
    edge = f["prior_clv"] >= 0.7 if side == 1 else f["prior_clv"] <= 0.3
    return {
        "NONE": True,
        "TREND5_ALIGN": align,
        "PRIOR_CONTRACTION": contra,
        "PRIOR_CONTRACTION_STRICT": strict,
        "PRIOR_CLOSE_EDGE": edge,
        "TREND5_CONTRACTION": align and contra,
        "CONTRACTION_EDGE": contra and edge,
    }[g]


def main() -> int:
    src = json.load(open("/home/z/z/runtime/benchmark_web_crabel_orb_v8.json"))
    base = next(x for x in src["variants"] if x["variant"] == "BASELINE")
    trades = sorted(base["trades"], key=lambda t: (int(t["exit_ts"]), str(t["symbol"])))
    cut = int(len(trades) * 0.6)
    boundary = int(trades[cut - 1]["exit_ts"])
    frames = cr.prepare_30m()
    fmap = {s: features(s, frames[s]) for s in v2.SYMS6}
    rows = []
    for g in GATES:
        selected = []
        for t in trades:
            f = fmap[t["symbol"]].get(dkey(int(t["signal_ts"])))
            if f and allow(g, t, f):
                selected.append(t)
        train = [t for t in selected if int(t["exit_ts"]) <= boundary]
        hold = [t for t in selected if int(t["exit_ts"]) > boundary]
        m = v2.metrics(selected)
        mt = v2.metrics(train)
        mh = v2.metrics(hold)
        rows.append(
            {"gate": g, "metrics": m, "train60_fixed": mt, "holdout40_fixed": mh}
        )
        print(
            "CRABEL_REGIME_V12="
            + json.dumps(
                {
                    "gate": g,
                    "T": m["T"],
                    "NetExp": m["Exp_bps_T"],
                    "PF": m["PF"],
                    "TrainT": mt["T"],
                    "TrainNetExp": mt["Exp_bps_T"],
                    "HoldT": mh["T"],
                    "HoldNetExp": mh["Exp_bps_T"],
                    "HoldPF": mh["PF"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    elig = [
        r
        for r in rows
        if int(r["train60_fixed"]["T"] or 0) >= 80
        and float(r["train60_fixed"]["Exp_bps_T"] or -1e9)
        > float(rows[0]["train60_fixed"]["Exp_bps_T"] or -1e9)
    ]
    chosen = (
        max(
            elig,
            key=lambda r: (
                float(r["train60_fixed"]["Exp_bps_T"]),
                int(r["train60_fixed"]["T"]),
            ),
        )["gate"]
        if elig
        else "NONE"
    )
    out = {
        "schema": "zel.a1.benchmark_web.crabel_regime.v12",
        "state": "DEV_REGIME_DIAG_COMPLETE",
        "selection": "TRAIN60_ONLY_IMPROVE_NETEXP_MIN80_TRADES",
        "chosen": chosen,
        "rows": rows,
        "research_only": True,
        "live": "BLOCKED",
    }
    Path("/home/z/z/runtime/benchmark_web_crabel_regime_v12.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n"
    )
    print("CRABEL_REGIME_CHOSEN", chosen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
