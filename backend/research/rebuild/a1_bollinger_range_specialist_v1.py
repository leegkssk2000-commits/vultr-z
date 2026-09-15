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
rm: Any = importlib.import_module(
    "backend.research.rebuild.a1_strategy_regime_alpha_matrix_v1"
)

OUT = Path("/home/z/z/runtime/bollinger_range_specialist_v1.json")
SYMS = v2.SYMS6
VARIANTS = ("MID_ALL", "HALF_MID_OPPOSITE")
TF_MS = (1_800_000, 3_600_000)
ALLOWED_REGIMES = {"RANGE_MIXED", "COMPRESSION"}


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    flow = tp * df["volume"]
    pos = flow.where(tp.diff() > 0, 0.0).rolling(n).sum()
    neg = flow.where(tp.diff() < 0, 0.0).rolling(n).sum()
    ratio = pos / neg.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + ratio)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    x = v2.util.enrich(df).copy()
    x["mid"] = x["close"].rolling(20).mean()
    sd = x["close"].rolling(20).std(ddof=0)
    x["upper"] = x["mid"] + 2.0 * sd
    x["lower"] = x["mid"] - 2.0 * sd
    x["mfi14"] = mfi(x, 14)
    return x


def attach_regime(
    frame: pd.DataFrame, feat: pd.DataFrame, q: dict[str, float]
) -> pd.DataFrame:
    tsarr = feat["ts_ms"].to_numpy(dtype=np.int64)
    regs = [rm.regime(r, q) for _, r in feat.iterrows()]
    out = frame.copy()
    labels = []
    for ts in out["ts_ms"].astype(int):
        pos = int(np.searchsorted(tsarr, ts, side="right") - 1)
        labels.append(regs[pos] if pos >= 0 else "NO_CONTEXT")
    out["regime"] = labels
    return out


def simulate(
    x: pd.DataFrame,
    i: int,
    side: int,
    excursion: float,
    cost_bps: float,
    variant: str,
) -> tuple[dict[str, Any] | None, int]:
    if i + 1 >= len(x):
        return None, i
    entry = float(x.iloc[i + 1]["open"])
    atr = max(float(x.iloc[i]["atr"]), 1e-12)
    stop = excursion - side * 0.50 * atr
    if (side == 1 and stop >= entry) or (side == -1 and stop <= entry):
        stop = entry - side * 1.5 * atr
    mid = float(x.iloc[i]["mid"])
    opp = float(x.iloc[i]["upper"] if side == 1 else x.iloc[i]["lower"])
    last = min(len(x) - 1, i + 1 + 16)
    rem = 1.0
    parts: list[float] = []
    mid_done = False
    final = float(x.iloc[last]["close"])
    exit_j = last
    reason = "TIMEOUT"
    for j in range(i + 1, last + 1):
        row = x.iloc[j]
        low, high = float(row["low"]), float(row["high"])
        if (side == 1 and low <= stop) or (side == -1 and high >= stop):
            final = stop
            exit_j = j
            reason = "STOP"
            break
        hit_mid = (side == 1 and high >= mid) or (side == -1 and low <= mid)
        if hit_mid and not mid_done:
            if variant == "MID_ALL":
                final = mid
                exit_j = j
                reason = "MID_TARGET"
                break
            parts.append(0.50 * side * (mid - entry) / entry * 10_000.0)
            rem = 0.50
            mid_done = True
            continue
        if mid_done:
            hit_opp = (side == 1 and high >= opp) or (side == -1 and low <= opp)
            if hit_opp:
                final = opp
                exit_j = j
                reason = "OPPOSITE_BAND"
                break
    parts.append(rem * side * (final - entry) / entry * 10_000.0)
    gross = sum(parts)
    return {
        "signal_ts": int(x.iloc[i]["ts_ms"]),
        "entry_ts": int(x.iloc[i + 1]["ts_ms"]),
        "exit_ts": int(x.iloc[exit_j]["ts_ms"]),
        "side": "long" if side == 1 else "short",
        "gross_bps": gross,
        "cost_bps": cost_bps,
        "net_bps": gross - cost_bps,
        "reason": reason,
        "regime": str(x.iloc[i]["regime"]),
    }, exit_j


def replay_symbol(
    sym: str,
    frame: pd.DataFrame,
    cost_bps: float,
    variant: str,
) -> list[dict[str, Any]]:
    x = enrich(frame)
    out: list[dict[str, Any]] = []
    armed_side = 0
    extreme = 0.0
    armed_at = -1
    i = 60
    while i < len(x) - 2:
        row, prev = x.iloc[i], x.iloc[i - 1]
        if not np.isfinite(
            [row["mid"], row["upper"], row["lower"], row["mfi14"], row["atr"]]
        ).all():
            i += 1
            continue
        if armed_side == 0:
            if float(row["close"]) < float(row["lower"]):
                armed_side = 1
                extreme = float(row["low"])
                armed_at = i
            elif float(row["close"]) > float(row["upper"]):
                armed_side = -1
                extreme = float(row["high"])
                armed_at = i
            i += 1
            continue
        if i - armed_at > 6:
            armed_side = 0
            i += 1
            continue
        extreme = (
            min(extreme, float(row["low"]))
            if armed_side == 1
            else max(extreme, float(row["high"]))
        )
        inside = (
            float(row["close"]) >= float(row["lower"])
            if armed_side == 1
            else float(row["close"]) <= float(row["upper"])
        )
        mfi_turn = (
            float(row["mfi14"]) <= 35.0 and float(row["mfi14"]) > float(prev["mfi14"])
            if armed_side == 1
            else float(row["mfi14"]) >= 65.0
            and float(row["mfi14"]) < float(prev["mfi14"])
        )
        if inside and mfi_turn and str(row["regime"]) in ALLOWED_REGIMES:
            trade, exit_j = simulate(x, i, armed_side, extreme, cost_bps, variant)
            if trade is not None:
                trade["symbol"] = sym
                out.append(trade)
            armed_side = 0
            i = max(i + 1, exit_j + 1)
            continue
        i += 1
    return out


def split_time(trades: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    train = [t for t in trades if int(t["signal_ts"]) <= cutoff]
    hold = [t for t in trades if int(t["signal_ts"]) > cutoff]
    return {"train60_time": v2.metrics(train), "holdout40_time": v2.metrics(hold)}


def main() -> int:
    feat, cutoff, q = rm.build_features()
    base = v2.util.load_5m()
    authority = v2.read_json(v2.COST_PATH)
    costs = {
        sym: float(
            v2.cost_ev.fetch_execution_snapshot(sym, authority)[
                "pretrade_verified_cost_bps"
            ]
        )
        for sym in SYMS
    }
    rows = []
    for tf in TF_MS:
        frames = {
            sym: attach_regime(v2.util.resample_frame(df, tf // 300_000), feat, q)
            for sym, df in base.items()
        }
        for variant in VARIANTS:
            trades: list[dict[str, Any]] = []
            for sym in SYMS:
                trades.extend(replay_symbol(sym, frames[sym], costs[sym], variant))
            trades.sort(key=lambda t: (int(t["exit_ts"]), str(t["symbol"])))
            row = {
                "timeframe": "30m" if tf == 1_800_000 else "1h",
                "variant": variant,
                "metrics": v2.metrics(trades),
                **split_time(trades, cutoff),
                "trades": trades,
            }
            rows.append(row)
            print(
                "BOLL_RANGE="
                + json.dumps(
                    {
                        "tf": row["timeframe"],
                        "variant": variant,
                        "T": row["metrics"]["T"],
                        "WR": row["metrics"]["WR"],
                        "NetExp": row["metrics"]["Exp_bps_T"],
                        "PF": row["metrics"]["PF"],
                        "HoldT": row["holdout40_time"]["T"],
                        "HoldNetExp": row["holdout40_time"]["Exp_bps_T"],
                        "HoldPF": row["holdout40_time"]["PF"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    out = {
        "schema": "zel.bollinger_range_specialist.v1",
        "state": "DEV_REPLAY_COMPLETE",
        "source_receipt": "backend/research/rebuild/bollinger_range_source_receipt_v1.json",
        "claim_level": "MECHANISM_ONLY_NOT_LITERAL_PROPRIETARY_SYSTEM",
        "allowed_regimes": sorted(ALLOWED_REGIMES),
        "rows": rows,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
