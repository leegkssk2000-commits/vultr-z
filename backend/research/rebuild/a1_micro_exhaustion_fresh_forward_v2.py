from __future__ import annotations

import importlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

micro: Any = importlib.import_module(
    "backend.research.rebuild.a1_micro_exhaustion_sleeve_v1"
)
ev: Any = importlib.import_module(
    "backend.research.rebuild.a1_exact25_generic_evaluator_three_lane_v1"
)
mx, v2 = micro.mx, micro.v2
ROOT = Path("/home/z/z/runtime")
RAW = Path("/home/z/z/ledger/production_bingx_ws_microstructure_v2.jsonl")
OUT = ROOT / "micro_exhaustion_fresh_forward_v2.json"
EDGE = {"move6": 0.004, "trade_imb": 0.40, "depth_delta": 0.20}


def fresh_raw_rows(freeze_ts: int) -> list[dict[str, Any]]:
    last = json.loads(subprocess.check_output(["tail", "-n", "1", str(RAW)], text=True))
    latest = int(last["bucket_start_ms"])
    expected = max(1000, math.ceil((latest - freeze_ts) / 5000.0) * 2)
    line_count = int(expected * 1.5 + 5000)
    text = subprocess.check_output(["tail", "-n", str(line_count), str(RAW)], text=True)
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [
        row
        for row in rows
        if int(row["bucket_start_ms"]) // 300_000 * 300_000 >= freeze_ts - 1_800_000
    ]


def aggregate_5m(rows: list[dict[str, Any]]) -> pd.DataFrame:
    buckets: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (str(row["symbol"]), int(row["bucket_start_ms"]) // 300_000 * 300_000)
        buckets[key].append(row)
    out: list[dict[str, Any]] = []
    for (symbol, ts), bucket in sorted(buckets.items()):
        bucket.sort(key=lambda row: int(row["bucket_start_ms"]))
        first, last = bucket[0], bucket[-1]
        buy = sum(float(row.get("aggressive_buy_qty") or 0.0) for row in bucket)
        sell = sum(float(row.get("aggressive_sell_qty") or 0.0) for row in bucket)
        out.append(
            {
                "symbol": symbol,
                "ts_ms": ts,
                "trade_imbalance": (
                    (buy - sell) / (buy + sell) if buy + sell > 0 else np.nan
                ),
                "imbalance_delta": float(last.get("imbalance_top20_last") or 0.0)
                - float(first.get("imbalance_top20_first") or 0.0),
                "rows": len(bucket),
            }
        )
    return pd.DataFrame(out)


def fresh_regime() -> tuple[np.ndarray, list[str]]:
    matrix = json.load(open(ROOT / "strategy_regime_alpha_matrix_v1.json"))
    q = matrix["regime_thresholds_train_only"]
    syms = v2.SYMS6
    frames: dict[str, pd.DataFrame] = {}
    for symbol in syms:
        x = pd.DataFrame(ev.fetch_bars(symbol, "1h", 1000)).sort_values("ts_ms")
        x["e21"] = x["close"].ewm(span=21, adjust=False).mean()
        x["e55"] = x["close"].ewm(span=55, adjust=False).mean()
        x["r24"] = x["close"] / x["close"].shift(24) - 1.0
        x["dir"] = np.sign(x["e21"] - x["e55"])
        x["atr"] = mx.atr(x)
        x["vr"] = x["atr"] / x["atr"].rolling(72, min_periods=36).median()
        frames[symbol] = x.set_index("ts_ms")
    common = sorted(
        set.intersection(*(set(x.index.astype(int)) for x in frames.values()))
    )
    rows: list[dict[str, float | int]] = []
    for ts in common:
        r24 = np.array([float(frames[s].loc[ts, "r24"]) for s in syms])
        dirs = np.array([float(frames[s].loc[ts, "dir"]) for s in syms])
        vr = np.array([float(frames[s].loc[ts, "vr"]) for s in syms])
        if not (
            np.isfinite(r24).all() and np.isfinite(dirs).all() and np.isfinite(vr).all()
        ):
            continue
        rows.append(
            {
                "ts_ms": int(ts),
                "dispersion24": float(np.std(r24)),
                "mean_abs24": float(np.mean(np.abs(r24))),
                "breadth": float(np.sum(dirs)),
                "vol_ratio": float(np.median(vr)),
            }
        )
    feat = pd.DataFrame(rows)
    return feat["ts_ms"].to_numpy(dtype=np.int64), [
        mx.regime(row, q) for _, row in feat.iterrows()
    ]


def replay_fresh(freeze_ts: int, micro5: pd.DataFrame) -> list[dict[str, Any]]:
    feature_ts, regimes = fresh_regime()
    authority = v2.read_json(v2.COST_PATH)
    costs = {
        symbol: float(
            v2.cost_ev.fetch_execution_snapshot(symbol, authority)[
                "pretrade_verified_cost_bps"
            ]
        )
        for symbol in micro.SYMS
    }
    bars = {
        symbol: pd.DataFrame(ev.fetch_bars(symbol, "5m", 1000)).sort_values("ts_ms")
        for symbol in micro.SYMS
    }
    trades: list[dict[str, Any]] = []
    for symbol in micro.SYMS:
        frame = (
            micro5[micro5["symbol"] == symbol]
            .merge(bars[symbol][["ts_ms", "open", "close"]], on="ts_ms", how="inner")
            .sort_values("ts_ms")
            .reset_index(drop=True)
        )
        frame["r6"] = frame["close"] / frame["close"].shift(6) - 1.0
        i = 10
        while i < len(frame) - micro.HOLD_BARS - 1:
            row = frame.iloc[i]
            signal_ts = int(row["ts_ms"])
            if signal_ts <= freeze_ts:
                i += 1
                continue
            pos = int(np.searchsorted(feature_ts, signal_ts, side="right") - 1)
            if pos < 0 or regimes[pos] != "TREND_COHERENT":
                i += 1
                continue
            if (
                pd.isna(row["trade_imbalance"])
                or pd.isna(row["imbalance_delta"])
                or pd.isna(row["r6"])
            ):
                i += 1
                continue
            move = float(row["r6"])
            side = 0
            if (
                move >= EDGE["move6"]
                and float(row["trade_imbalance"]) >= EDGE["trade_imb"]
                and float(row["imbalance_delta"]) <= -EDGE["depth_delta"]
            ):
                side = -1
            elif (
                move <= -EDGE["move6"]
                and float(row["trade_imbalance"]) <= -EDGE["trade_imb"]
                and float(row["imbalance_delta"]) >= EDGE["depth_delta"]
            ):
                side = 1
            if side == 0:
                i += 1
                continue
            entry = float(frame.iloc[i + 1]["open"])
            exit_px = float(frame.iloc[i + micro.HOLD_BARS]["close"])
            gross = side * (exit_px - entry) / entry * 10_000.0
            cost = float(costs[symbol])
            trades.append(
                {
                    "symbol": symbol,
                    "signal_ts": signal_ts,
                    "entry_ts": int(frame.iloc[i + 1]["ts_ms"]),
                    "exit_ts": int(frame.iloc[i + micro.HOLD_BARS]["ts_ms"]),
                    "side": "long" if side == 1 else "short",
                    "gross_bps": gross,
                    "cost_bps": cost,
                    "net_bps": gross - cost,
                    "move6": move,
                    "trade_imbalance": float(row["trade_imbalance"]),
                    "imbalance_delta": float(row["imbalance_delta"]),
                }
            )
            i += micro.HOLD_BARS
    return sorted(trades, key=lambda x: (int(x["exit_ts"]), str(x["symbol"])))


def main() -> int:
    dev = json.load(open(ROOT / "micro_exhaustion_sleeve_v1.json"))
    freeze_ts = int(dev["fresh_forward_after_ts"])
    raw = fresh_raw_rows(freeze_ts)
    micro5 = aggregate_5m(raw)
    trades = replay_fresh(freeze_ts, micro5)
    latest_ts = int(micro5["ts_ms"].max()) if len(micro5) else freeze_ts
    out = {
        "schema": "zel.microstructure.exhaustion_fresh_forward.v2",
        "state": "FROZEN_EDGE_FRESH_FORWARD_OBSERVATION",
        "frozen_candidate": "EDGE",
        "frozen_config": EDGE,
        "freeze_ts": freeze_ts,
        "latest_observed_5m_ts": latest_ts,
        "fresh_hours": max(0.0, (latest_ts - freeze_ts) / 3_600_000.0),
        "raw_5s_rows_used": len(raw),
        "aggregated_5m_rows": len(micro5),
        "fresh_metrics": micro.metrics(trades),
        "fresh_trades": trades,
        "decision": (
            "NO_NEW_SIGNAL_YET"
            if not trades
            else "ACCUMULATE_MORE_FRESH_TRADES_NO_RETUNE"
        ),
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "MICRO_FRESH_V2="
        + json.dumps(
            {k: out[k] for k in ("fresh_hours", "fresh_metrics", "decision")},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
