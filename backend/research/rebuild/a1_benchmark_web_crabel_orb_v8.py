from __future__ import annotations

import importlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)

TF = 1_800_000
VARIANTS = ("BASELINE", "NR4", "NR7")


def day_key(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def prepare_30m() -> dict[str, pd.DataFrame]:
    base = v2.util.load_5m()
    return {sym: v2.util.resample_frame(df, 6) for sym, df in base.items()}


def daily_summary(
    df: pd.DataFrame,
) -> tuple[list[str], dict[str, dict[str, float | int]]]:
    rows: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(df["ts_ms"].astype(int)):
        rows[day_key(int(ts))].append(i)
    days = sorted(rows)
    out: dict[str, dict[str, float | int]] = {}
    for day in days:
        idx = rows[day]
        part = df.iloc[idx]
        out[day] = {
            "first_i": idx[0],
            "last_i": idx[-1],
            "open": float(part.iloc[0]["open"]),
            "high": float(part["high"].max()),
            "low": float(part["low"].min()),
            "close": float(part.iloc[-1]["close"]),
            "range": float(part["high"].max() - part["low"].min()),
        }
    return days, out


def narrow_filter(
    days: list[str], daily: dict[str, dict[str, float | int]], pos: int, lookback: int
) -> bool:
    if pos < lookback:
        return False
    prior = pos - 1
    window = [
        float(daily[days[j]]["range"]) for j in range(prior - lookback + 1, prior + 1)
    ]
    return window[-1] <= min(window)


def replay_symbol(
    sym: str,
    df: pd.DataFrame,
    cost_bps: float,
    variant: str,
) -> list[dict[str, Any]]:
    days, daily = daily_summary(df)
    trades: list[dict[str, Any]] = []
    for pos in range(10, len(days) - 1):
        if variant == "NR4" and not narrow_filter(days, daily, pos, 4):
            continue
        if variant == "NR7" and not narrow_filter(days, daily, pos, 7):
            continue
        prior_ranges = [float(daily[days[j]]["range"]) for j in range(pos - 10, pos)]
        stretch = 0.8 * (sum(prior_ranges) / 10.0)
        if stretch <= 0:
            continue
        day = days[pos]
        info = daily[day]
        session_open = float(info["open"])
        long_trigger = session_open + stretch
        short_trigger = session_open - stretch
        chosen_side = None
        signal_i = None
        for i in range(int(info["first_i"]), int(info["last_i"]) + 1):
            row = df.iloc[i]
            hit_long = float(row["high"]) >= long_trigger
            hit_short = float(row["low"]) <= short_trigger
            if hit_long and hit_short:
                chosen_side = None
                signal_i = None
                break
            if hit_long or hit_short:
                chosen_side = "long" if hit_long else "short"
                signal_i = i
                break
        if chosen_side is None or signal_i is None:
            continue
        next_day = daily[days[pos + 1]]
        exit_i = int(next_day["first_i"])
        entry = long_trigger if chosen_side == "long" else short_trigger
        exit_px = float(df.iloc[exit_i]["open"])
        side = 1 if chosen_side == "long" else -1
        gross = side * (exit_px - entry) / entry * 10_000.0
        trades.append(
            {
                "strategy_id": "break_and_continue",
                "child_id": f"crabel_orb_v8_{variant.lower()}",
                "symbol": sym,
                "side": chosen_side,
                "signal_ts": int(df.iloc[signal_i]["ts_ms"]),
                "entry_ts": int(df.iloc[signal_i]["ts_ms"]),
                "exit_ts": int(df.iloc[exit_i]["ts_ms"]),
                "entry": entry,
                "exit": exit_px,
                "stretch": stretch,
                "gross_bps": gross,
                "cost_bps": cost_bps,
                "net_bps": gross - cost_bps,
                "reason": "NEXT_UTC_DAY_OPEN",
            }
        )
    return trades


def main() -> int:
    frames = prepare_30m()
    authority = v2.read_json(v2.COST_PATH)
    costs: dict[str, float] = {}
    for sym in v2.SYMS6:
        snap = v2.cost_ev.fetch_execution_snapshot(sym, authority)
        costs[sym] = float(snap["pretrade_verified_cost_bps"])
    rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        trades: list[dict[str, Any]] = []
        for sym in v2.SYMS6:
            trades.extend(replay_symbol(sym, frames[sym], costs[sym], variant))
        trades = sorted(trades, key=lambda t: (int(t["exit_ts"]), str(t["symbol"])))
        full = v2.metrics(trades)
        split = v2.split_metrics(trades)
        row = {"variant": variant, "metrics": full, "split": split, "trades": trades}
        rows.append(row)
        h = split["holdout40"]
        print(
            "CRABEL_V8="
            + json.dumps(
                {
                    "variant": variant,
                    "T": full["T"],
                    "WR": full["WR"],
                    "GrossExp_bps_T": full["GrossExp_bps_T"],
                    "NetExp_bps_T": full["Exp_bps_T"],
                    "PF": full["PF"],
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
        "schema": "zel.a1.benchmark_web.crabel_orb.v8",
        "state": "DEV_REPLAY_COMPLETE",
        "source_ids": ["CRABEL_ORB_2026", "CRABEL_1_4_BNR_2026"],
        "translation": "UTC session anchor for 24/7 crypto; 30m execution; 0.8x prior-10-day average range stretch; next UTC-day open exit",
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "variants": rows,
    }
    Path("/home/z/z/runtime/benchmark_web_crabel_orb_v8.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
