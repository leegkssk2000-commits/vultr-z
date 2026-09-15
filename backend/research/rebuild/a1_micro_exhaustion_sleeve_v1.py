from __future__ import annotations

import gzip
import importlib
import json
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
mx: Any = importlib.import_module(
    "backend.research.rebuild.a1_strategy_regime_alpha_matrix_v1"
)
ROOT = Path("/home/z/z/runtime")
MICRO_PATH = ROOT / "benchmark6_micro_5m_v1.jsonl.gz"
OUT = ROOT / "micro_exhaustion_sleeve_v1.json"
SYMS = ("BTC-USDT", "ETH-USDT")
HOLD_BARS = 12
CANDIDATES = {
    "DENSITY": {"move6": 0.003, "trade_imb": 0.50, "depth_delta": 0.20},
    "EDGE": {"move6": 0.004, "trade_imb": 0.40, "depth_delta": 0.20},
    "WIDE": {"move6": 0.003, "trade_imb": 0.40, "depth_delta": 0.15},
}


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [
        float(t["net_bps"]) for t in sorted(trades, key=lambda x: int(x["exit_ts"]))
    ]
    wins, losses = [x for x in vals if x > 0], [-x for x in vals if x < 0]
    eq = peak = dd = 0.0
    streak = max_streak = 0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if value < 0 else 0
        max_streak = max(max_streak, streak)
    return {
        "T": len(vals),
        "WR": len(wins) / len(vals) if vals else None,
        "Net_bps": sum(vals),
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": sum(wins) / sum(losses) if losses else None,
        "DD_bps": dd,
        "MaxLossStreak": max_streak,
    }


def load_micro() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with gzip.open(MICRO_PATH, "rt") as handle:
        for line in handle:
            rows.append(json.loads(line))
    return pd.DataFrame(rows).sort_values(["symbol", "ts_ms"]).reset_index(drop=True)


def replay_candidate(
    name: str,
    cfg: dict[str, float],
    micro: pd.DataFrame,
    base: dict[str, pd.DataFrame],
    costs: dict[str, float],
    feat: pd.DataFrame,
    q: dict[str, float],
) -> list[dict[str, Any]]:
    feature_ts = feat["ts_ms"].to_numpy(dtype=np.int64)
    regimes = [mx.regime(row, q) for _, row in feat.iterrows()]
    trades: list[dict[str, Any]] = []
    for symbol in SYMS:
        frame = (
            micro[micro["symbol"] == symbol]
            .merge(base[symbol][["ts_ms", "open", "close"]], on="ts_ms", how="inner")
            .sort_values("ts_ms")
            .reset_index(drop=True)
        )
        frame["r6"] = frame["close"] / frame["close"].shift(6) - 1.0
        i = 10
        while i < len(frame) - HOLD_BARS - 1:
            row = frame.iloc[i]
            pos = int(np.searchsorted(feature_ts, int(row["ts_ms"]), side="right") - 1)
            if pos < 0 or regimes[pos] != "TREND_COHERENT":
                i += 1
                continue
            trade_imb = row["trade_imbalance"]
            depth_delta = row["imbalance_delta"]
            if pd.isna(trade_imb) or pd.isna(depth_delta) or pd.isna(row["r6"]):
                i += 1
                continue
            move = float(row["r6"])
            side = 0
            if (
                move >= cfg["move6"]
                and float(trade_imb) >= cfg["trade_imb"]
                and float(depth_delta) <= -cfg["depth_delta"]
            ):
                side = -1
            elif (
                move <= -cfg["move6"]
                and float(trade_imb) <= -cfg["trade_imb"]
                and float(depth_delta) >= cfg["depth_delta"]
            ):
                side = 1
            if side == 0:
                i += 1
                continue
            entry = float(frame.iloc[i + 1]["open"])
            exit_px = float(frame.iloc[i + HOLD_BARS]["close"])
            gross_bps = side * (exit_px - entry) / entry * 10_000.0
            cost_bps = float(costs[symbol])
            trades.append(
                {
                    "candidate": name,
                    "symbol": symbol,
                    "signal_ts": int(row["ts_ms"]),
                    "entry_ts": int(frame.iloc[i + 1]["ts_ms"]),
                    "exit_ts": int(frame.iloc[i + HOLD_BARS]["ts_ms"]),
                    "side": "long" if side == 1 else "short",
                    "gross_bps": gross_bps,
                    "cost_bps": cost_bps,
                    "net_bps": gross_bps - cost_bps,
                    "regime": "TREND_COHERENT",
                    "move6": move,
                    "trade_imbalance": float(trade_imb),
                    "imbalance_delta": float(depth_delta),
                }
            )
            i += HOLD_BARS
    return sorted(trades, key=lambda x: (int(x["exit_ts"]), str(x["symbol"])))


def main() -> int:
    micro = load_micro()
    base = v2.util.load_5m()
    feat, _, q = mx.build_features()
    authority = v2.read_json(v2.COST_PATH)
    costs = {
        symbol: float(
            v2.cost_ev.fetch_execution_snapshot(symbol, authority)[
                "pretrade_verified_cost_bps"
            ]
        )
        for symbol in SYMS
    }
    start_ts = int(micro["ts_ms"].min())
    end_ts = int(micro["ts_ms"].max())
    cutoff = start_ts + int(0.60 * (end_ts - start_ts))
    rows: dict[str, Any] = {}
    for name, cfg in CANDIDATES.items():
        trades = replay_candidate(name, cfg, micro, base, costs, feat, q)
        train = [t for t in trades if int(t["signal_ts"]) <= cutoff]
        hold = [t for t in trades if int(t["signal_ts"]) > cutoff]
        days = max((end_ts - start_ts) / 86_400_000.0, 1e-9)
        rows[name] = {
            "config": cfg,
            "full": metrics(trades),
            "train60_time": metrics(train),
            "holdout40_time": metrics(hold),
            "T_per_day": len(trades) / days,
            "trades": trades,
        }
        print(
            "MICRO_EXHAUSTION="
            + json.dumps(
                {
                    "candidate": name,
                    "T": rows[name]["full"]["T"],
                    "NetExp": rows[name]["full"]["Exp_bps_T"],
                    "PF": rows[name]["full"]["PF"],
                    "TrainT": rows[name]["train60_time"]["T"],
                    "TrainNetExp": rows[name]["train60_time"]["Exp_bps_T"],
                    "HoldT": rows[name]["holdout40_time"]["T"],
                    "HoldNetExp": rows[name]["holdout40_time"]["Exp_bps_T"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    dev_candidates = []
    for name, row in rows.items():
        tr, ho = row["train60_time"], row["holdout40_time"]
        if (
            tr["T"] >= 12
            and (tr["Exp_bps_T"] or -1e9) > 0
            and (tr["PF"] or 0) > 1.0
            and ho["T"] >= 4
            and (ho["Exp_bps_T"] or -1e9) > 0
            and (ho["PF"] or 0) > 1.0
        ):
            dev_candidates.append(name)
    out = {
        "schema": "zel.microstructure.exhaustion_sleeve.v1",
        "state": "DEV_MICRO_SLEEVE_SEARCH_COMPLETE_HISTORY_INSPECTED",
        "window": {"start_ts": start_ts, "end_ts": end_ts, "cutoff_ts": cutoff},
        "source_ids": ["ROTTER_INTERVIEW", "AZIZ_LEVEL2"],
        "execution_model": "taker-next-5m-open entry; verified round-trip cost charged; no passive/maker fill credit",
        "frozen_regime": "TREND_COHERENT",
        "hold_bars_5m": HOLD_BARS,
        "costs_bps": costs,
        "candidates": rows,
        "development_candidates": dev_candidates,
        "decision": (
            "FRESH_FORWARD_REQUIRED; no promotion because this history was inspected and sample counts are small"
            if dev_candidates
            else "NO_DEV_SURVIVOR"
        ),
        "fresh_forward_after_ts": end_ts,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "MICRO_DEV_CANDIDATES="
        + json.dumps(
            {
                name: {
                    k: rows[name][k]
                    for k in ("full", "train60_time", "holdout40_time", "T_per_day")
                }
                for name in dev_candidates
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
