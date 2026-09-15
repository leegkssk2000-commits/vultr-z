from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

c: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_connors_rsi2_v11"
)
v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
util: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_native_replay_v1"
)
TF = 1_800_000
STOPS = (0.75, 1.0, 1.25, 1.5, 2.0)
COSTS = {
    "BTC-USDT": 14.0,
    "ETH-USDT": 14.0,
    "SOL-USDT": 14.0,
    "XRP-USDT": 15.058813437188807,
    "LINK-USDT": 15.561366061899777,
    "DOGE-USDT": 15.363228169680506,
}


def max_loss_streak(trades: list[dict[str, Any]]) -> int:
    cur = best = 0
    for t in trades:
        if float(t["net_bps"]) <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def replay_symbol(sym: str, x, daily, stop_mult: float) -> list[dict[str, Any]]:
    x = util.enrich(util.resample_frame(x, 6))
    x["rsi2"] = c.rsi2(x["close"])
    x["ma5"] = x["close"].rolling(5).mean()
    daily_ts = daily["ts_ms"].astype(int).to_numpy()
    ma = daily["ma200"].to_numpy(float)
    dc = daily["close"].to_numpy(float)
    tr: list[dict[str, Any]] = []
    i = 210
    while i < len(x) - 2:
        ts = int(x.iloc[i]["ts_ms"])
        pos = np.searchsorted(daily_ts, ts, side="right") - 1
        if pos < 199 or not np.isfinite(ma[pos]):
            i += 1
            continue
        r = x.iloc[i]
        side = (
            1
            if dc[pos] > ma[pos] and float(r["rsi2"]) < 5
            else (-1 if dc[pos] < ma[pos] and float(r["rsi2"]) > 95 else 0)
        )
        if not side:
            i += 1
            continue
        entry = float(x.iloc[i + 1]["open"])
        atr = max(float(r["atr"]), 1e-12)
        stop = entry - side * stop_mult * atr
        last = min(len(x) - 1, i + 1 + 20)
        final = float(x.iloc[last]["close"])
        ej = last
        reason = "TIMEOUT"
        for j in range(i + 1, last + 1):
            q = x.iloc[j]
            lo, hi, close = float(q["low"]), float(q["high"]), float(q["close"])
            m5 = float(q["ma5"])
            if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
                final, ej, reason = stop, j, "DISASTER_STOP"
                break
            if (side == 1 and close > m5) or (side == -1 and close < m5):
                final, ej, reason = close, j, "MA5_EXIT"
                break
        gross = side * (final - entry) / entry * 10_000.0
        cost = COSTS[sym]
        tr.append(
            {
                "symbol": sym,
                "signal_ts": ts,
                "entry_ts": int(x.iloc[i + 1]["ts_ms"]),
                "exit_ts": int(x.iloc[ej]["ts_ms"]),
                "side": "long" if side == 1 else "short",
                "gross_bps": gross,
                "cost_bps": cost,
                "net_bps": gross - cost,
                "reason": reason,
            }
        )
        i = max(i + 1, ej + 1)
    return tr


def main() -> int:
    base = util.load_5m()
    daily = {s: c.daily_regime(s) for s in c.SYMS}
    baseline = json.load(open("/home/z/z/runtime/benchmark_web_connors_rsi2_v11.json"))
    base30 = next(r for r in baseline["rows"] if r["timeframe"] == "30m")
    ordered0 = sorted(
        base30["trades"], key=lambda z: (int(z["exit_ts"]), str(z["symbol"]))
    )
    boundary = int(ordered0[max(0, int(len(ordered0) * 0.6) - 1)]["exit_ts"])
    rows = []
    for stop_mult in STOPS:
        tr = []
        for sym in c.SYMS:
            tr.extend(replay_symbol(sym, base[sym], daily[sym], stop_mult))
        tr = sorted(tr, key=lambda z: (int(z["exit_ts"]), str(z["symbol"])))
        train = [t for t in tr if int(t["exit_ts"]) <= boundary]
        hold = [t for t in tr if int(t["exit_ts"]) > boundary]
        row = {
            "stop_atr": stop_mult,
            "full": v2.metrics(tr),
            "train60_fixed": v2.metrics(train),
            "holdout40_fixed": v2.metrics(hold),
            "max_loss_streak": max_loss_streak(tr),
            "holdout_max_loss_streak": max_loss_streak(hold),
        }
        rows.append(row)
        m, h = row["full"], row["holdout40_fixed"]
        print(
            "CONNORS_LOSS_V12="
            + json.dumps(
                {
                    "stop_atr": stop_mult,
                    "T": m["T"],
                    "WR": m["WR"],
                    "NetExp": m["Exp_bps_T"],
                    "PF": m["PF"],
                    "LS": row["max_loss_streak"],
                    "HoldT": h["T"],
                    "HoldNetExp": h["Exp_bps_T"],
                    "HoldPF": h["PF"],
                    "HoldLS": row["holdout_max_loss_streak"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    eligible = [
        r
        for r in rows
        if int(r["train60_fixed"]["T"] or 0) >= 300
        and float(r["train60_fixed"]["Exp_bps_T"] or -1e9) > 0
        and float(r["train60_fixed"]["PF"] or 0) > 1
    ]
    chosen = (
        max(
            eligible,
            key=lambda r: (
                float(r["train60_fixed"]["Exp_bps_T"]),
                -float(r["stop_atr"]),
            ),
        )
        if eligible
        else None
    )
    out = {
        "schema": "zel.a1.connors_rsi2.loss_compression.v12",
        "state": "DEV_COMPLETE",
        "source_id": "CONNORS_RSI2_PUBLIC",
        "selection_boundary_ts": boundary,
        "selection_rule": "train60_fixed only; T>=300, NetExp>0, PF>1; then inspect holdout once",
        "chosen_stop_atr": chosen["stop_atr"] if chosen else None,
        "rows": rows,
        "research_only": True,
        "live_trade_authority": "BLOCKED",
    }
    Path("/home/z/z/runtime/connors_rsi2_loss_compression_v12.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
