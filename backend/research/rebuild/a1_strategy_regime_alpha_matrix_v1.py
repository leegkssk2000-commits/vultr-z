from __future__ import annotations

import importlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
cr8: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_crabel_orb_v8"
)
cr12: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_crabel_regime_v12"
)
ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "strategy_regime_alpha_matrix_v1.json"
MIN_TRAIN_CELL, MIN_HOLD_CONFIRM = 20, 8
FLOOR_RISK = 0.25
SLEEVE = {
    "supertrend_pullback_active5": "TREND_PULLBACK",
    "keltner_trend_active5": "TREND_PULLBACK",
    "trend_rider_active5": "TREND_PULLBACK",
    "trend_ma_macd_active5": "TREND_PULLBACK",
    "keltner_holygrail_30m": "TREND_PULLBACK",
    "break_and_continue_active5": "BREAKOUT_EXPANSION",
    "crabel_orb_trend5_30m": "BREAKOUT_EXPANSION",
    "squeeze_native_30m": "BREAKOUT_EXPANSION",
    "connors_rsi2_30m": "MEAN_REVERSION",
    "shannon_avwap_30m": "MEAN_REVERSION",
}


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat(
        [(df["high"] - df["low"]), (df["high"] - pc).abs(), (df["low"] - pc).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def build_features() -> tuple[pd.DataFrame, int, dict[str, float]]:
    base = v2.util.load_5m()
    by = {}
    for sym, df in base.items():
        x = v2.util.resample_frame(df, 12).copy()
        x["e21"] = x["close"].ewm(span=21, adjust=False).mean()
        x["e55"] = x["close"].ewm(span=55, adjust=False).mean()
        x["r24"] = x["close"] / x["close"].shift(24) - 1
        x["dir"] = np.sign(x["e21"] - x["e55"])
        x["atr"] = atr(x)
        x["vr"] = x["atr"] / x["atr"].rolling(72, min_periods=36).median()
        by[sym] = x.set_index("ts_ms")
    common = sorted(set.intersection(*(set(x.index.astype(int)) for x in by.values())))
    rows = []
    for ts in common:
        r24 = np.array([float(by[s].loc[ts, "r24"]) for s in v2.SYMS6])
        dirs = np.array([float(by[s].loc[ts, "dir"]) for s in v2.SYMS6])
        vr = np.array([float(by[s].loc[ts, "vr"]) for s in v2.SYMS6])
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
    feat = pd.DataFrame(rows).sort_values("ts_ms").reset_index(drop=True)
    start, end = int(feat.iloc[0].ts_ms), int(feat.iloc[-1].ts_ms)
    cutoff = int(start + 0.60 * (end - start))
    train = feat[feat.ts_ms <= cutoff]
    q = {
        "disp_q67": float(train.dispersion24.quantile(0.67)),
        "meanabs_q85": float(train.mean_abs24.quantile(0.85)),
        "vol_q25": float(train.vol_ratio.quantile(0.25)),
        "vol_q67": float(train.vol_ratio.quantile(0.67)),
    }
    return feat, cutoff, q


def regime(r: pd.Series, q: dict[str, float]) -> str:
    if r.mean_abs24 >= q["meanabs_q85"] and r.dispersion24 >= q["disp_q67"]:
        return "PANIC_DISPERSION"
    if abs(r.breadth) >= 4:
        return (
            "TREND_DISPERSED" if r.dispersion24 >= q["disp_q67"] else "TREND_COHERENT"
        )
    if r.vol_ratio <= q["vol_q25"]:
        return "COMPRESSION"
    if r.vol_ratio >= q["vol_q67"]:
        return "VOL_EXPANSION_MIXED"
    return "RANGE_MIXED"


def norm(
    name: str, trades: list[dict[str, Any]], net_key: str = "net_bps"
) -> list[dict[str, Any]]:
    return [
        {
            "strategy": name,
            "sleeve": SLEEVE[name],
            "symbol": str(t["symbol"]),
            "side": str(t["side"]),
            "signal_ts": int(t["signal_ts"]),
            "exit_ts": int(t["exit_ts"]),
            "net_bps": float(t[net_key]),
        }
        for t in trades
    ]


def load_strategies() -> dict[str, list[dict[str, Any]]]:
    out = {}
    a5 = json.load(open(ROOT / "active5_v6_180d_ledger_v2.json"))
    for sid in (
        "supertrend_pullback",
        "keltner_trend",
        "break_and_continue",
        "trend_ma_macd",
        "trend_rider",
    ):
        name = f"{sid}_active5"
        out[name] = norm(
            name, [t for t in a5["trades"] if t["strategy_id"] == sid], "v6_net_bps"
        )
    hg = json.load(open(ROOT / "keltner_holygrail_streak_guard_v11.json"))
    out["keltner_holygrail_30m"] = norm("keltner_holygrail_30m", hg["trades"])
    crsrc = json.load(open(ROOT / "benchmark_web_crabel_orb_v8.json"))
    base = next(x for x in crsrc["variants"] if x["variant"] == "BASELINE")
    frames = cr8.prepare_30m()
    fmap = {s: cr12.features(s, frames[s]) for s in v2.SYMS6}
    selected = []
    for t in base["trades"]:
        f = fmap[str(t["symbol"])].get(cr12.dkey(int(t["signal_ts"])))
        if f and cr12.allow("TREND5_ALIGN", t, f):
            selected.append(t)
    out["crabel_orb_trend5_30m"] = norm("crabel_orb_trend5_30m", selected)
    conn = json.load(open(ROOT / "benchmark_web_connors_rsi2_v11.json"))
    c30 = next(x for x in conn["rows"] if x["timeframe"] == "30m")
    out["connors_rsi2_30m"] = norm("connors_rsi2_30m", c30["trades"])
    av = json.load(open(ROOT / "benchmark_web_avwap_v10.json"))
    a30 = next(x for x in av["rows"] if x["timeframe"] == "30m")
    out["shannon_avwap_30m"] = norm("shannon_avwap_30m", a30["trades"])
    sq = json.load(open(ROOT / "benchmark_web_squeeze_v7.json"))
    native = next(x for x in sq["variants"] if x["gate"] == "NATIVE")
    out["squeeze_native_30m"] = norm("squeeze_native_30m", native["trades"])
    return out


def metrics(ts: list[dict[str, Any]], key: str = "net_bps") -> dict[str, Any]:
    vals = [
        float(t[key]) for t in sorted(ts, key=lambda x: (x["exit_ts"], x["strategy"]))
    ]
    wins, losses = [v for v in vals if v > 0], [-v for v in vals if v < 0]
    eq = peak = dd = 0.0
    cur = mx = 0
    for v in vals:
        eq += v
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        cur = cur + 1 if v < 0 else 0
        mx = max(mx, cur)
    return {
        "T": len(vals),
        "WR": len(wins) / len(vals) if vals else None,
        "Net_bps": float(sum(vals)),
        "Exp_bps_T": float(sum(vals) / len(vals)) if vals else None,
        "PF": float(sum(wins) / sum(losses)) if losses else None,
        "DD_bps": float(dd),
        "MaxLossStreak": mx,
    }


def attach_regimes(
    strategies: dict[str, list[dict[str, Any]]], feat: pd.DataFrame, q: dict[str, float]
) -> None:
    tsarr = feat.ts_ms.to_numpy(dtype=np.int64)
    regs = [regime(r, q) for _, r in feat.iterrows()]
    for trades in strategies.values():
        for t in trades:
            pos = int(np.searchsorted(tsarr, int(t["signal_ts"]), side="right") - 1)
            t["regime"] = regs[pos] if pos >= 0 else "NO_CONTEXT"


def build_matrix(
    strategies: dict[str, list[dict[str, Any]]], cutoff: int
) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    matrix, eligible = {}, set()
    for name, trades in strategies.items():
        item: dict[str, Any] = {
            "sleeve": SLEEVE[name],
            "full": metrics(trades),
            "regimes": {},
        }
        for reg in sorted(set(t["regime"] for t in trades)):
            xs = [t for t in trades if t["regime"] == reg]
            tr = [t for t in xs if t["signal_ts"] <= cutoff]
            ho = [t for t in xs if t["signal_ts"] > cutoff]
            mt, mh = metrics(tr), metrics(ho)
            train_ok = bool(
                mt["T"] >= MIN_TRAIN_CELL
                and (mt["Exp_bps_T"] or -1e9) > 0
                and (mt["PF"] or 0) > 1.05
            )
            hold_ok = bool(
                mh["T"] >= MIN_HOLD_CONFIRM
                and (mh["Exp_bps_T"] or -1e9) > 0
                and (mh["PF"] or 0) > 1.0
            )
            if train_ok:
                eligible.add((name, reg))
            item["regimes"][reg] = {
                "full": metrics(xs),
                "train60_time": mt,
                "holdout40_time": mh,
                "train_selected": train_ok,
                "holdout_confirmed": hold_ok if train_ok else None,
            }
        matrix[name] = item
    return matrix, eligible


def sleeve_metrics(
    strategies: dict[str, list[dict[str, Any]]], cutoff: int
) -> dict[str, Any]:
    out = {}
    for sleeve in sorted(set(SLEEVE.values())):
        xs = [
            t for n, trades in strategies.items() if SLEEVE[n] == sleeve for t in trades
        ]
        out[sleeve] = {
            "full": metrics(xs),
            "train60_time": metrics([t for t in xs if t["signal_ts"] <= cutoff]),
            "holdout40_time": metrics([t for t in xs if t["signal_ts"] > cutoff]),
            "strategies": [n for n in strategies if SLEEVE[n] == sleeve],
        }
    return out


def router(
    strategies: dict[str, list[dict[str, Any]]],
    eligible: set[tuple[str, str]],
    cutoff: int,
) -> dict[str, Any]:
    routed, weights = [], []
    for trades in strategies.values():
        for t in trades:
            w = 1.0 if (t["strategy"], t["regime"]) in eligible else FLOOR_RISK
            z = dict(t)
            z["routed_net_bps"] = w * float(t["net_bps"])
            z["router_weight"] = w
            routed.append(z)
            weights.append(w)
    routed.sort(key=lambda x: (x["exit_ts"], x["strategy"]))
    train = [t for t in routed if t["signal_ts"] <= cutoff]
    hold = [t for t in routed if t["signal_ts"] > cutoff]
    return {
        "rule": f"1.0x train-selected strategy-regime cells, {FLOOR_RISK:.2f}x otherwise",
        "physical_T_preserved": len(routed),
        "avg_risk_weight": float(np.mean(weights)) if weights else 0.0,
        "baseline_full": metrics(routed),
        "routed_full": metrics(routed, "routed_net_bps"),
        "baseline_train": metrics(train),
        "routed_train": metrics(train, "routed_net_bps"),
        "baseline_holdout": metrics(hold),
        "routed_holdout": metrics(hold, "routed_net_bps"),
    }


def main() -> int:
    feat, cutoff, q = build_features()
    strategies = load_strategies()
    attach_regimes(strategies, feat, q)
    matrix, eligible = build_matrix(strategies, cutoff)
    selected = []
    for name, reg in sorted(eligible):
        cell = matrix[name]["regimes"][reg]
        selected.append(
            {
                "strategy": name,
                "regime": reg,
                "train": cell["train60_time"],
                "holdout": cell["holdout40_time"],
                "confirmed": cell["holdout_confirmed"],
            }
        )
    out = {
        "schema": "zel.strategy_regime_alpha_matrix.v1",
        "state": "DEV_REGIME_ALPHA_MATRIX_COMPLETE_NOT_FRESH_OOS",
        "window_note": "same inspected 180d history; thresholds and cell selection use first 60% calendar time only",
        "cutoff_ts": cutoff,
        "regime_thresholds_train_only": q,
        "regime_counts": dict(Counter(regime(r, q) for _, r in feat.iterrows())),
        "selection_contract": {
            "min_train_T": MIN_TRAIN_CELL,
            "train_net_gt": 0,
            "train_pf_gt": 1.05,
            "hold_min_T": MIN_HOLD_CONFIRM,
        },
        "strategy_matrix": matrix,
        "sleeves": sleeve_metrics(strategies, cutoff),
        "train_selected_cells": selected,
        "selected_cells": len(selected),
        "holdout_confirmed_cells": sum(1 for x in selected if x["confirmed"]),
        "router": router(strategies, eligible, cutoff),
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print("REGIME_COUNTS", json.dumps(out["regime_counts"], sort_keys=True))
    print(
        "SELECTED", out["selected_cells"], "CONFIRMED", out["holdout_confirmed_cells"]
    )
    for x in selected:
        print(
            "CELL",
            x["strategy"],
            x["regime"],
            "TR",
            x["train"]["T"],
            round(x["train"]["Exp_bps_T"], 2),
            round(x["train"]["PF"] or 0, 3),
            "HO",
            x["holdout"]["T"],
            round(x["holdout"]["Exp_bps_T"] or 0, 2),
            round(x["holdout"]["PF"] or 0, 3),
            x["confirmed"],
        )
    print("ROUTER", json.dumps(out["router"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
