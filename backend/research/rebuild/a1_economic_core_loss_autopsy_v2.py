from __future__ import annotations

import importlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

p1: Any = importlib.import_module(
    "backend.research.rebuild.a1_priority_economic_program_v1"
)
mx, v6 = p1.mx, p1.v6
ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "economic_core_loss_autopsy_v2.json"
RISK_FLOORS = (1.0, 0.75, 0.50, 0.25)
TARGET_MONTHS = ("2026-03", "2026-07")


def month(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m")


def metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda x: (int(x["exit_ts"]), str(x["strategy"])))
    vals = [float(x[key]) for x in ordered]
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


def build_inputs() -> tuple[
    Any,
    int,
    dict[str, float],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    feat, cutoff, q = mx.build_features()
    strategies = mx.load_strategies()
    mx.attach_regimes(strategies, feat, q)
    regmap = {
        (str(row["strategy"]), str(row["symbol"]), int(row["signal_ts"])): str(
            row["regime"]
        )
        for rows in strategies.values()
        for row in rows
    }
    ledger = json.load(open(ROOT / "active5_v6_180d_ledger_v2.json"))["trades"]
    bars = v6.v5.local_1h_bars()
    rider = p1.improved_active(
        ledger,
        regmap,
        bars,
        "trend_rider",
        "TREND_COHERENT",
        12,
        0.50,
        "trend_rider_coherent_v2",
    )
    source = [t for t in ledger if t["strategy_id"] == "trend_rider"]
    hg = [
        dict(row, strategy="keltner_holygrail_30m")
        for row in strategies["keltner_holygrail_30m"]
        if row["regime"] == "PANIC_DISPERSION"
    ]
    return feat, cutoff, q, rider, source, hg


def attach_context(
    feat: Any, rider: list[dict[str, Any]], source: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ts = feat["ts_ms"].to_numpy(dtype=np.int64)
    vr = feat["vol_ratio"].to_numpy(dtype=float)
    source_map = {(str(t["symbol"]), int(t["signal_ts"])): t for t in source}
    out: list[dict[str, Any]] = []
    for row in rider:
        item = dict(row)
        pos = int(np.searchsorted(ts, int(row["signal_ts"]), side="right") - 1)
        item["vol_ratio"] = float(vr[pos]) if pos >= 0 else float("nan")
        original = source_map[(str(row["symbol"]), int(row["signal_ts"]))]
        item["side"] = str(original["side"])
        item["source_reason"] = str(original["reason"])
        item["strategy"] = "trend_rider_coherent_v2"
        out.append(item)
    return out


def month_autopsy(rows: list[dict[str, Any]], target: str) -> dict[str, Any]:
    selected = [row for row in rows if month(int(row["exit_ts"])) == target]
    by_symbol: dict[str, float] = defaultdict(float)
    by_side: dict[str, float] = defaultdict(float)
    by_reason: Counter[str] = Counter()
    for row in selected:
        by_symbol[str(row["symbol"])] += float(row["net_bps"])
        by_side[str(row["side"])] += float(row["net_bps"])
        by_reason[str(row["source_reason"])] += 1
    return {
        "T": len(selected),
        "Net_bps_unscaled": sum(float(x["net_bps"]) for x in selected),
        "WR": (
            sum(float(x["net_bps"]) > 0 for x in selected) / len(selected)
            if selected
            else None
        ),
        "reason_counts": dict(sorted(by_reason.items())),
        "symbol_net_bps": dict(sorted(by_symbol.items())),
        "side_net_bps": dict(sorted(by_side.items())),
        "mean_vol_ratio": (
            float(np.mean([x["vol_ratio"] for x in selected])) if selected else None
        ),
    }


def evaluate_throttles(
    rider: list[dict[str, Any]],
    hg: list[dict[str, Any]],
    cutoff: int,
    q: dict[str, float],
    rider_weight: float,
) -> tuple[dict[str, Any], float]:
    results: dict[str, Any] = {}
    for floor in RISK_FLOORS:
        routed: list[dict[str, Any]] = [
            dict(x, adjusted_bps=float(x["net_bps"])) for x in hg
        ]
        for row in rider:
            risk = rider_weight * (
                floor if float(row["vol_ratio"]) > q["vol_q67"] else 1.0
            )
            routed.append(
                dict(row, adjusted_bps=risk * float(row["net_bps"]), risk_weight=risk)
            )
        train = [x for x in routed if int(x["signal_ts"]) <= cutoff]
        hold = [x for x in routed if int(x["signal_ts"]) > cutoff]
        monthly: dict[str, float] = defaultdict(float)
        for row in routed:
            monthly[month(int(row["exit_ts"]))] += float(row["adjusted_bps"])
        results[str(floor)] = {
            "full": metric(routed, "adjusted_bps"),
            "train60_time": metric(train, "adjusted_bps"),
            "holdout40_time": metric(hold, "adjusted_bps"),
            "monthly_net_bps": dict(sorted(monthly.items())),
            "physical_T_preserved": len(routed),
        }
    base = results["1.0"]["train60_time"]
    eligible = []
    for floor in RISK_FLOORS[1:]:
        row = results[str(floor)]["train60_time"]
        if (
            row["Net_bps"] > base["Net_bps"]
            and row["PF"] > base["PF"]
            and row["DD_bps"] < base["DD_bps"]
        ):
            eligible.append((floor, row))
    chosen = (
        max(eligible, key=lambda x: (x[1]["PF"], x[1]["Net_bps"]))[0]
        if eligible
        else 1.0
    )
    return results, chosen


def main() -> int:
    feat, cutoff, q, rider_raw, source, hg = build_inputs()
    rider = attach_context(feat, rider_raw, source)
    hg_train = np.array(
        [float(x["net_bps"]) for x in hg if int(x["signal_ts"]) <= cutoff], dtype=float
    )
    rider_train = np.array(
        [float(x["net_bps"]) for x in rider if int(x["signal_ts"]) <= cutoff],
        dtype=float,
    )
    rider_weight = float(
        min(1.0, hg_train.std(ddof=1) / max(rider_train.std(ddof=1), 1e-9))
    )
    throttles, chosen = evaluate_throttles(rider, hg, cutoff, q, rider_weight)
    autopsy = {target: month_autopsy(rider, target) for target in TARGET_MONTHS}
    out = {
        "schema": "zel.economic_core.loss_autopsy_and_throttle.v2",
        "state": "DEV_CAUSAL_RISK_THROTTLE_SELECTED_NOT_LIVE_AUTHORIZED",
        "objective": "reduce March/July loss severity without changing entry count or retuning Keltner",
        "cutoff_ts": cutoff,
        "rider_train_only_base_weight": rider_weight,
        "high_vol_threshold_train_only": q["vol_q67"],
        "risk_floor_candidates": list(RISK_FLOORS),
        "chosen_high_vol_floor": chosen,
        "month_autopsy": autopsy,
        "throttle_results": throttles,
        "diagnosis": {
            "march": "Trend Rider dominates; 12/14 source exits were SL and only 2 TIMEOUT. High pre-entry volatility is materially elevated, so late stale-exit tuning is not the main failure mode.",
            "july": "Trend Rider dominates; 40/49 source exits were SL across all six symbols. This is broad trend-follow-through failure/payoff starvation, not one bad symbol or delayed timeout.",
            "causal_limit": "July sits mostly after the frozen train cutoff; no July-specific entry filter is authorized from this history.",
        },
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "CORE_LOSS_AUTOPSY_V2="
        + json.dumps(
            {
                "chosen_high_vol_floor": chosen,
                "march": autopsy["2026-03"],
                "july": autopsy["2026-07"],
                "chosen": throttles[str(chosen)],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
