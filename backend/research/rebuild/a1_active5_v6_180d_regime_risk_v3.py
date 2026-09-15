from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

ledger_mod: Any = importlib.import_module(
    "backend.research.rebuild.a1_active5_v6_180d_ledger_v2"
)
v6 = ledger_mod.v6
LEDGER = Path("/home/z/z/runtime/active5_v6_180d_ledger_v2.json")
OUT = Path("/home/z/z/runtime/active5_v6_180d_regime_risk_v3.json")
SYMS = tuple(v6.v5.v2.SYMS6)


def market_features() -> dict[int, dict[str, float]]:
    bars = v6.v5.local_1h_bars()
    per: dict[str, dict[int, tuple[float, float, float]]] = {}
    for sym in SYMS:
        xs = bars[sym]
        closes = [float(b["close"]) for b in xs]
        ema50 = v6.v5.pk.ema(closes, 50)
        vals: dict[int, tuple[float, float, float]] = {}
        for i in range(50, len(xs)):
            r24 = closes[i] / closes[i - 24] - 1.0 if i >= 24 else 0.0
            direction = (
                1.0
                if closes[i] > ema50[i] and ema50[i] > ema50[i - 1]
                else (-1.0 if closes[i] < ema50[i] and ema50[i] < ema50[i - 1] else 0.0)
            )
            vals[int(xs[i]["ts_ms"])] = (r24, direction, closes[i])
        per[sym] = vals
    common = sorted(set.intersection(*(set(per[s]) for s in SYMS)))
    out: dict[int, dict[str, float]] = {}
    for ts in common:
        r24 = np.array([per[s][ts][0] for s in SYMS], dtype=float)
        dirs = np.array([per[s][ts][1] for s in SYMS], dtype=float)
        out[ts] = {
            "dispersion24": float(np.std(r24)),
            "mean24": float(np.mean(r24)),
            "mean_abs24": float(np.mean(np.abs(r24))),
            "breadth": float(np.sum(dirs)),
            "btc24": float(per["BTC-USDT"][ts][0]),
            "btc_dir": float(per["BTC-USDT"][ts][1]),
        }
    return out


def max_dd(values: list[float]) -> float:
    eq = peak = dd = 0.0
    for value in values:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def metrics(values: list[float]) -> dict[str, Any]:
    m = v6.rt.metrics(values)
    m["DD_bps"] = max_dd(values)
    return m


def risk_weight(
    name: str, trade: dict[str, Any], feat: dict[str, float], q: dict[str, float]
) -> float:
    side = 1.0 if trade["side"] == "long" else -1.0
    align = side * feat["breadth"]
    if name == "BASE":
        return 1.0
    if name == "DISP_Q50_HALF":
        return 0.5 if feat["dispersion24"] >= q["q50"] else 1.0
    if name == "DISP_Q67_HALF":
        return 0.5 if feat["dispersion24"] >= q["q67"] else 1.0
    if name == "DISP_Q75_HALF":
        return 0.5 if feat["dispersion24"] >= q["q75"] else 1.0
    if name == "LOW_DISP_Q25_HALF":
        return 0.5 if feat["dispersion24"] <= q["q25"] else 1.0
    if name == "OPP_BREADTH_HALF":
        return 0.5 if align <= -2.0 else 1.0
    if name == "NONALIGN_BREADTH_HALF":
        return 0.5 if align <= 0.0 else 1.0
    if name == "TRENDMA_HALF":
        return 0.5 if trade["strategy_id"] == "trend_ma_macd" else 1.0
    if name == "TRENDMA_QUARTER":
        return 0.25 if trade["strategy_id"] == "trend_ma_macd" else 1.0
    if name == "DISP_Q67_TRENDMA_HALF":
        weight = 0.5 if feat["dispersion24"] >= q["q67"] else 1.0
        if trade["strategy_id"] == "trend_ma_macd":
            weight *= 0.5
        return weight
    if name == "NONALIGN_TRENDMA_HALF":
        weight = 0.5 if align <= 0.0 else 1.0
        if trade["strategy_id"] == "trend_ma_macd":
            weight *= 0.5
        return weight
    raise KeyError(name)


CANDIDATES = (
    "BASE",
    "DISP_Q50_HALF",
    "DISP_Q67_HALF",
    "DISP_Q75_HALF",
    "LOW_DISP_Q25_HALF",
    "OPP_BREADTH_HALF",
    "NONALIGN_BREADTH_HALF",
    "TRENDMA_HALF",
    "TRENDMA_QUARTER",
    "DISP_Q67_TRENDMA_HALF",
    "NONALIGN_TRENDMA_HALF",
)


def main() -> int:
    ledger = json.loads(LEDGER.read_text())
    trades = ledger["trades"]
    feats = market_features()
    enriched = []
    for trade in trades:
        feat = feats.get(int(trade["signal_ts"]))
        if feat is not None:
            enriched.append((trade, feat))
    cut = int(len(enriched) * 0.60)
    train = enriched[:cut]
    hold = enriched[cut:]
    train_disp = np.array([f["dispersion24"] for _, f in train], dtype=float)
    q = {
        "q25": float(np.quantile(train_disp, 0.25)),
        "q50": float(np.quantile(train_disp, 0.50)),
        "q67": float(np.quantile(train_disp, 0.67)),
        "q75": float(np.quantile(train_disp, 0.75)),
    }
    rows: list[dict[str, Any]] = []
    base_train: dict[str, Any] | None = None
    for name in CANDIDATES:
        train_vals: list[float] = []
        hold_vals: list[float] = []
        weights: list[float] = []
        for trade, feat in train:
            w = risk_weight(name, trade, feat, q)
            train_vals.append(float(trade["v6_net_bps"]) * w)
            weights.append(w)
        for trade, feat in hold:
            w = risk_weight(name, trade, feat, q)
            hold_vals.append(float(trade["v6_net_bps"]) * w)
            weights.append(w)
        mt, mh = metrics(train_vals), metrics(hold_vals)
        avg_weight = float(np.mean(weights)) if weights else 0.0
        if name == "BASE":
            base_train = mt
        rows.append(
            {
                "name": name,
                "avg_weight": avg_weight,
                "train60": mt,
                "holdout40": mh,
            }
        )
    if base_train is None:
        raise RuntimeError("BASE_TRAIN_MISSING")
    eligible: list[dict[str, Any]] = [
        row
        for row in rows
        if row["name"] != "BASE"
        and row["avg_weight"] >= 0.65
        and float(row["train60"]["Net_bps"]) > float(base_train["Net_bps"])
        and float(row["train60"]["PF"] or 0.0) > float(base_train["PF"] or 0.0)
        and float(row["train60"]["DD_bps"]) < float(base_train["DD_bps"])
    ]
    chosen = (
        max(
            eligible,
            key=lambda row: (
                float(row["train60"]["Net_bps"]),
                float(row["train60"]["PF"] or 0.0),
                -float(row["train60"]["DD_bps"]),
            ),
        )["name"]
        if eligible
        else "BASE"
    )
    out = {
        "schema": "zel.a1.active5.v6_180d_regime_risk.v3",
        "state": "DEV_TRAIN_ONLY_RISK_SELECTION_COMPLETE",
        "feature_thresholds_train_only": q,
        "candidate_set": list(CANDIDATES),
        "selection_rule": "train60 only; preserve all T; avg risk multiplier >=0.65; improve train Net/PF/DD vs BASE",
        "chosen": chosen,
        "rows": rows,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print("ACTIVE5_REGIME_V3_CHOSEN", chosen, flush=True)
    for row in rows:
        print(
            "ACTIVE5_REGIME_V3_ROW="
            + json.dumps(
                {
                    "name": row["name"],
                    "avg_weight": row["avg_weight"],
                    "train": row["train60"],
                    "hold": row["holdout40"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
