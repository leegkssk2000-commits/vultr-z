from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
sm: Any = importlib.import_module(
    "backend.research.rebuild.benchmark25_donor_state_machine_v2"
)

TF = 1_800_000


def linreg_endpoint(values: np.ndarray) -> float:
    if len(values) < 20 or np.isnan(values).any():
        return np.nan
    x = np.arange(len(values), dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    return float(intercept + slope * x[-1])


def enrich_squeeze(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    close = x["close"]
    mean20 = close.rolling(20).mean()
    sd20 = close.rolling(20).std(ddof=0)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema34 = close.ewm(span=34, adjust=False).mean()
    ema8 = close.ewm(span=8, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    atr20 = v2.util.wilder_atr(x, 20)
    bb_u, bb_l = mean20 + 2.0 * sd20, mean20 - 2.0 * sd20
    kc_u, kc_l = ema20 + 1.5 * atr20, ema20 - 1.5 * atr20
    x["squeeze_on"] = (bb_u < kc_u) & (bb_l > kc_l)
    hh = x["high"].rolling(20).max()
    ll = x["low"].rolling(20).min()
    delta = close - (((hh + ll) / 2.0 + mean20) / 2.0)
    x["momentum"] = delta.rolling(20).apply(linreg_endpoint, raw=True)
    x["ema8_s"] = ema8
    x["ema21_s"] = ema21
    x["ema34_s"] = ema34
    x["atr20_s"] = atr20
    return x


def cost_scale(row: pd.Series, entry: float, cost_bps: float) -> float:
    return float(row["atr20_s"]) / max(entry, 1e-12) * 10_000.0 / max(cost_bps, 1e-9)


def signal_at(
    i: int, x: pd.DataFrame, cost_bps: float, gate: str
) -> tuple[str, tuple[str, ...]] | None:
    if i < 2 or i + 1 >= len(x):
        return None
    row, prev = x.iloc[i], x.iloc[i - 1]
    fired = bool(prev["squeeze_on"]) and not bool(row["squeeze_on"])
    if not fired or not np.isfinite(float(row["momentum"])):
        return None
    mom, pmom = float(row["momentum"]), float(prev["momentum"])
    long_ok = (
        mom > 0
        and mom > pmom
        and float(row["close"]) > float(row["ema34_s"])
        and float(row["ema8_s"]) > float(row["ema21_s"]) > float(row["ema34_s"])
    )
    short_ok = (
        mom < 0
        and mom < pmom
        and float(row["close"]) < float(row["ema34_s"])
        and float(row["ema8_s"]) < float(row["ema21_s"]) < float(row["ema34_s"])
    )
    side = "long" if long_ok else ("short" if short_ok else "flat")
    if side == "flat":
        return None
    entry = float(x.iloc[i + 1]["open"])
    if gate == "COST4" and cost_scale(row, entry, cost_bps) < 4.0:
        return None
    return side, (
        "BB_INSIDE_KC_20_2_1P5",
        "FIRST_FIRE",
        "MOMENTUM_SIGN_AND_ACCEL",
        "PRICE_VS_34MA",
        "STACKED_MA_INTRADAY_TRANSLATION",
        "ATR_COST4" if gate == "COST4" else "NO_COST_GATE",
    )


def simulate(
    i: int, side_name: str, x: pd.DataFrame, cost_bps: float
) -> tuple[dict[str, Any], int]:
    side = 1 if side_name == "long" else -1
    row = x.iloc[i]
    entry = float(x.iloc[i + 1]["open"])
    atr = max(float(row["atr20_s"]), 1e-12)
    band_ref = float(row["ema21_s"]) - side * 2.0 * atr
    fallback = entry - side * 2.0 * atr
    stop = band_ref
    if (side == 1 and stop >= entry) or (side == -1 and stop <= entry):
        stop = fallback
    last = min(len(x) - 1, i + 1 + 10)
    exit_px = float(x.iloc[last]["close"])
    exit_j = last
    reason = "MOMENTUM_10BAR_EXIT"
    weaken = 0
    for j in range(i + 1, last + 1):
        bar = x.iloc[j]
        lo, hi = float(bar["low"]), float(bar["high"])
        if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
            exit_px, exit_j, reason = stop, j, "2ATR_STOP"
            break
        mom = float(bar["momentum"])
        pmom = float(x.iloc[j - 1]["momentum"])
        bad = (mom > 0 and mom < pmom) if side == 1 else (mom < 0 and mom > pmom)
        weaken = weaken + 1 if bad else 0
        if weaken >= 2:
            exit_px, exit_j, reason = float(bar["close"]), j, "TWO_WEAK_MOMENTUM_BARS"
            break
    gross = side * (exit_px - entry) / entry * 10_000.0
    return {
        "side": side_name,
        "signal_ts": int(row["ts_ms"]),
        "entry_ts": int(x.iloc[i + 1]["ts_ms"]),
        "exit_ts": int(x.iloc[exit_j]["ts_ms"]),
        "entry": entry,
        "exit": exit_px,
        "reason": reason,
        "gross_bps": gross,
        "cost_bps": cost_bps,
        "net_bps": gross - cost_bps,
    }, exit_j


def replay(
    gate: str, frames: Mapping[str, pd.DataFrame], costs: Mapping[str, float]
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    for sym in v2.SYMS6:
        x = enrich_squeeze(frames[sym])
        i = 80
        while i < len(x) - 1:
            sig = signal_at(i, x, float(costs[sym]), gate)
            if sig is None:
                i += 1
                continue
            side, trace = sig
            trade, exit_j = simulate(i, side, x, float(costs[sym]))
            trade["symbol"] = sym
            trade["event_trace"] = list(trace)
            trades.append(trade)
            i = max(i + 1, exit_j + 1)
    full = v2.metrics(trades)
    split = v2.split_metrics(trades)
    return {
        "gate": gate,
        "metrics": full,
        "split": split,
        "exit_reasons": dict(
            __import__("collections").Counter(t["reason"] for t in trades)
        ),
        "trades": trades,
    }


def main() -> int:
    all_spec = sm.load_spec()
    spec_all = json.loads(json.dumps(all_spec))
    child = spec_all["children"]["squeeze_break"]
    child["timeframe_ms"] = TF
    child["timeframe"] = "30m"
    spec_all["children"] = {"squeeze_break": child}
    frames_by_tf, _ = v2.prepare_frames(spec_all)
    authority = v2.read_json(v2.COST_PATH)
    costs: dict[str, float] = {}
    for sym in v2.SYMS6:
        snap = v2.cost_ev.fetch_execution_snapshot(sym, authority)
        costs[sym] = float(snap["pretrade_verified_cost_bps"])
    rows = [replay(gate, frames_by_tf[TF], costs) for gate in ("NATIVE", "COST4")]
    for r in rows:
        m, h = r["metrics"], r["split"]["holdout40"]
        print(
            "SQUEEZE_V7="
            + json.dumps(
                {
                    "gate": r["gate"],
                    "T": m["T"],
                    "WR": m["WR"],
                    "GrossExp_bps_T": m["GrossExp_bps_T"],
                    "NetExp_bps_T": m["Exp_bps_T"],
                    "PF": m["PF"],
                    "HoldT": h["T"],
                    "HoldGrossExp_bps_T": h["GrossExp_bps_T"],
                    "HoldNetExp_bps_T": h["Exp_bps_T"],
                    "HoldPF": h["PF"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    out = {
        "schema": "zel.a1.benchmark_web.squeeze.v7",
        "state": "DEV_REPLAY_COMPLETE",
        "sources": ["CARTER_TTM", "CARTER_PLAN", "THINKORSWIM_TTM_DOC"],
        "timeframe": "30m",
        "parameter_tuning": False,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "variants": rows,
    }
    path = Path("/home/z/z/runtime/benchmark_web_squeeze_v7.json")
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
