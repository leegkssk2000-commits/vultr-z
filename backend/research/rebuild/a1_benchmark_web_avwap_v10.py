from __future__ import annotations
import importlib
import json
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
SYMS = v2.SYMS6


def enrich(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    x = util.enrich(df)
    a = x["atr"]
    bars5d = 240 if tf == 1_800_000 else 120
    x["ma5d"] = x["close"].rolling(bars5d).mean()
    x["ma5d_slope"] = x["ma5d"].diff()
    x["av_low"] = util.rolling_anchor_vwap(x, bars5d, True)
    x["av_high"] = util.rolling_anchor_vwap(x, bars5d, False)
    x["atr_bps"] = a / x["close"] * 10000
    return x


def metrics(ts):
    return v2.metrics(ts)


def replay(tf: int, costs: dict[str, float]) -> dict[str, Any]:
    base = util.load_5m()
    trades = []
    for sym in SYMS:
        x = enrich(util.resample_frame(base[sym], tf // 300_000), tf)
        i = max(250 if tf == 1_800_000 else 130, 2)
        while i < len(x) - 2:
            r = x.iloc[i]
            p = x.iloc[i - 1]
            a = float(r["atr"])
            c = float(r["close"])
            side = 0
            if not all(
                np.isfinite(float(r[k]))
                for k in ["ma5d", "ma5d_slope", "av_low", "av_high", "atr"]
            ):
                i += 1
                continue
            if (
                c > float(r["ma5d"])
                and float(r["ma5d_slope"]) > 0
                and c > float(r["av_low"])
                and float(p["close"]) <= float(p["av_high"])
                and c > float(r["av_high"])
                and c > float(p["high"])
            ):
                side = 1
            elif (
                c < float(r["ma5d"])
                and float(r["ma5d_slope"]) < 0
                and c < float(r["av_high"])
                and float(p["close"]) >= float(p["av_low"])
                and c < float(r["av_low"])
                and c < float(p["low"])
            ):
                side = -1
            if not side:
                i += 1
                continue
            entry = float(x.iloc[i + 1]["open"])
            cost = float(costs[sym])
            if float(r["atr_bps"]) / max(cost, 1e-9) < 3.0:
                i += 1
                continue
            stop = (
                (min(float(r["low"]), float(p["low"])) - 0.10 * a)
                if side == 1
                else (max(float(r["high"]), float(p["high"])) + 0.10 * a)
            )
            if (side == 1 and stop >= entry) or (side == -1 and stop <= entry):
                i += 1
                continue
            risk = abs(entry - stop)
            rem = 1.0
            parts = []
            partial = False
            trail = None
            peak = entry
            reason = "TIMEOUT"
            last = min(len(x) - 1, i + 1 + (32 if tf == 1_800_000 else 24))
            ej = last
            final = float(x.iloc[last]["close"])
            for j in range(i + 1, last + 1):
                q = x.iloc[j]
                hi = float(q["high"])
                lo = float(q["low"])
                close = float(q["close"])
                qa = float(q["atr"])
                if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
                    final = stop
                    ej = j
                    reason = "HARD_STOP"
                    break
                av = float(q["av_low"] if side == 1 else q["av_high"])
                if np.isfinite(av) and (
                    (side == 1 and close < av) or (side == -1 and close > av)
                ):
                    final = close
                    ej = j
                    reason = "AVWAP_INVALID"
                    break
                if trail is not None and (
                    (side == 1 and lo <= trail) or (side == -1 and hi >= trail)
                ):
                    final = trail
                    ej = j
                    reason = "TRAIL"
                    break
                fav = (hi - entry) / risk if side == 1 else (entry - lo) / risk
                peak = max(peak, hi) if side == 1 else min(peak, lo)
                if not partial and fav >= 1.5:
                    px = entry + side * 1.5 * risk
                    parts.append(0.25 * side * (px - entry) / entry * 10000)
                    rem = 0.75
                    partial = True
                if fav >= 2.0:
                    cand = peak - 1.5 * qa if side == 1 else peak + 1.5 * qa
                    trail = (
                        max(trail if trail is not None else -1e99, cand)
                        if side == 1
                        else min(trail if trail is not None else 1e99, cand)
                    )
            parts.append(rem * side * (final - entry) / entry * 10000)
            gross = sum(parts)
            net = gross - cost
            trades.append(
                {
                    "strategy_id": "anchor_vwap_trend",
                    "symbol": sym,
                    "side": "long" if side == 1 else "short",
                    "signal_ts": int(r["ts_ms"]),
                    "entry_ts": int(x.iloc[i + 1]["ts_ms"]),
                    "exit_ts": int(x.iloc[ej]["ts_ms"]),
                    "gross_bps": gross,
                    "cost_bps": cost,
                    "net_bps": net,
                    "reason": reason,
                }
            )
            i = max(i + 1, ej + 1)

    trades = sorted(trades, key=lambda t: (t["exit_ts"], t["symbol"]))
    cut = int(len(trades) * 0.6)
    return {
        "timeframe": "30m" if tf == 1_800_000 else "1h",
        "metrics": metrics(trades),
        "train60": metrics(trades[:cut]),
        "holdout40": metrics(trades[cut:]),
        "trades": trades,
    }


def main() -> int:
    auth = v2.read_json(v2.COST_PATH)
    costs = {
        s: float(
            v2.cost_ev.fetch_execution_snapshot(s, auth)["pretrade_verified_cost_bps"]
        )
        for s in SYMS
    }
    rows = [replay(tf, costs) for tf in (1_800_000, 3_600_000)]
    for r in rows:
        m = r["metrics"]
        h = r["holdout40"]
        print(
            "AVWAP_V10="
            + json.dumps(
                {
                    "tf": r["timeframe"],
                    "T": m["T"],
                    "WR": m["WR"],
                    "NetExp": m["Exp_bps_T"],
                    "PF": m["PF"],
                    "HoldT": h["T"],
                    "HoldNetExp": h["Exp_bps_T"],
                    "HoldPF": h["PF"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    out = {
        "schema": "zel.a1.benchmark_web.avwap.v10",
        "source_id": "SHANNON_AVWAP",
        "state": "DEV_REPLAY_COMPLETE",
        "research_only": True,
        "live": "BLOCKED",
        "rows": rows,
    }
    Path("/home/z/z/runtime/benchmark_web_avwap_v10.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
