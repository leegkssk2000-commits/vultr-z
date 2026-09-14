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
ev: Any = importlib.import_module(
    "backend.research.rebuild.a1_exact25_generic_evaluator_three_lane_v1"
)
SYMS = v2.SYMS6


def rsi2(s: pd.Series) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + g / loss.replace(0, np.nan))


def daily_regime(sym: str) -> pd.DataFrame:
    rows = ev.fetch_bars(sym, "1d", 1000)
    x = pd.DataFrame(rows).sort_values("ts_ms")
    x["ma200"] = x["close"].rolling(200).mean()
    return x[["ts_ms", "close", "ma200"]]


def replay(tf: int, costs: dict[str, float]) -> dict[str, Any]:
    base = util.load_5m()
    tr = []
    for sym in SYMS:
        x = util.enrich(util.resample_frame(base[sym], tf // 300_000))
        x["rsi2"] = rsi2(x["close"])
        x["ma5"] = x["close"].rolling(5).mean()
        d = daily_regime(sym)
        daily_ts = d["ts_ms"].astype(int).to_numpy()
        ma = d["ma200"].to_numpy(float)
        dc = d["close"].to_numpy(float)
        i = 210
        while i < len(x) - 2:
            ts = int(x.iloc[i]["ts_ms"])
            pos = np.searchsorted(daily_ts, ts, side="right") - 1
            if pos < 199 or not np.isfinite(ma[pos]):
                i += 1
                continue
            r = x.iloc[i]
            side = 0
            if dc[pos] > ma[pos] and float(r["rsi2"]) < 5:
                side = 1
            elif dc[pos] < ma[pos] and float(r["rsi2"]) > 95:
                side = -1
            if not side:
                i += 1
                continue
            entry = float(x.iloc[i + 1]["open"])
            a = max(float(r["atr"]), 1e-12)
            stop = entry - side * 2.0 * a
            last = min(len(x) - 1, i + 1 + 20)
            final = float(x.iloc[last]["close"])
            ej = last
            reason = "TIMEOUT"
            for j in range(i + 1, last + 1):
                q = x.iloc[j]
                lo = float(q["low"])
                hi = float(q["high"])
                close = float(q["close"])
                m5 = float(q["ma5"])
                if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
                    final = stop
                    ej = j
                    reason = "DISASTER_STOP"
                    break
                if (side == 1 and close > m5) or (side == -1 and close < m5):
                    final = close
                    ej = j
                    reason = "MA5_EXIT"
                    break
            gross = side * (final - entry) / entry * 10000
            cost = float(costs[sym])
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
    tr = sorted(tr, key=lambda z: (z["exit_ts"], z["symbol"]))
    cut = int(len(tr) * 0.6)
    return {
        "timeframe": "30m" if tf == 1800000 else "1h",
        "metrics": v2.metrics(tr),
        "train60": v2.metrics(tr[:cut]),
        "holdout40": v2.metrics(tr[cut:]),
        "trades": tr,
    }


def main() -> int:
    auth = v2.read_json(v2.COST_PATH)
    costs = {
        s: float(
            v2.cost_ev.fetch_execution_snapshot(s, auth)["pretrade_verified_cost_bps"]
        )
        for s in SYMS
    }
    rows = [replay(tf, costs) for tf in (1800000, 3600000)]
    for r in rows:
        m = r["metrics"]
        h = r["holdout40"]
        print(
            "CONNORS_V11="
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
    Path("/home/z/z/runtime/benchmark_web_connors_rsi2_v11.json").write_text(
        json.dumps(
            {
                "schema": "zel.a1.benchmark_web.connors_rsi2.v11",
                "source_id": "CONNORS_RSI2_PUBLIC",
                "translation_note": "200-day regime from real daily BingX bars; RSI2/MA5 on 30m or 1h execution; 2ATR disaster stop is implementation risk control, not claimed donor parameter",
                "rows": rows,
                "research_only": True,
                "live": "BLOCKED",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
