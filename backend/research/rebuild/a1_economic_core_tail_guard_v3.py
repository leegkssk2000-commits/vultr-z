from __future__ import annotations

import importlib
import json
import math
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

p1: Any = importlib.import_module(
    "backend.research.rebuild.a1_priority_economic_program_v1"
)
a2: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic_core_loss_autopsy_v2"
)

ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "economic_core_tail_guard_v3.json"
LOAD_FLOORS = (0.75, 0.50, 0.25)
TRAIN_NET_RETENTION = 0.98


def month(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m")


def attach_load24(rows: list[dict[str, Any]]) -> None:
    signals = sorted(int(row["signal_ts"]) for row in rows)
    for row in rows:
        ts = int(row["signal_ts"])
        left = bisect_left(signals, ts - 24 * 3_600_000)
        right = bisect_left(signals, ts)
        row["prior_signal_load24"] = right - left


def rider_weight(
    hg: list[dict[str, Any]], rider: list[dict[str, Any]], cutoff: int
) -> float:
    h = np.array([float(x["net_bps"]) for x in hg if int(x["signal_ts"]) <= cutoff])
    r = np.array([float(x["net_bps"]) for x in rider if int(x["signal_ts"]) <= cutoff])
    return float(min(1.0, h.std(ddof=1) / max(r.std(ddof=1), 1e-9)))


def monthly(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for row in rows:
        out[month(int(row["exit_ts"]))] += float(row[key])
    return dict(sorted(out.items()))


def evaluate(
    rider: list[dict[str, Any]],
    hg: list[dict[str, Any]],
    cutoff: int,
    base_weight: float,
    vol_q67: float,
    vol_q85: float,
    load_threshold: int,
    load_floor: float | None,
    extreme_off: bool,
) -> dict[str, Any]:
    rows = [dict(x, adjusted_bps=float(x["net_bps"])) for x in hg]
    for row in rider:
        vol_factor = 1.0
        if extreme_off and float(row["vol_ratio"]) > vol_q85:
            vol_factor = 0.0
        elif float(row["vol_ratio"]) > vol_q67:
            vol_factor = 0.25
        load_factor = 1.0
        if load_floor is not None and int(row["prior_signal_load24"]) >= load_threshold:
            load_factor = load_floor
        risk = base_weight * vol_factor * load_factor
        rows.append(
            dict(row, adjusted_bps=risk * float(row["net_bps"]), risk_weight=risk)
        )
    rows.sort(key=lambda x: (int(x["exit_ts"]), str(x["strategy"])))
    train = [x for x in rows if int(x["signal_ts"]) <= cutoff]
    hold = [x for x in rows if int(x["signal_ts"]) > cutoff]
    return {
        "full": a2.metric(rows, "adjusted_bps"),
        "train60_time": a2.metric(train, "adjusted_bps"),
        "holdout40_time": a2.metric(hold, "adjusted_bps"),
        "monthly_net_bps": monthly(rows, "adjusted_bps"),
        "train_monthly_net_bps": monthly(train, "adjusted_bps"),
        "physical_T_preserved": len(rows),
    }


def attach_broad24(rows: list[dict[str, Any]]) -> None:
    bars = p1.v6.v5.local_1h_bars()
    syms = list(p1.v6.v5.v2.SYMS6)
    by_symbol: dict[str, dict[int, float]] = {}
    for symbol in syms:
        b = bars[symbol]
        closes = np.array([float(x["close"]) for x in b], dtype=float)
        times = [int(x["ts_ms"]) for x in b]
        by_symbol[symbol] = {
            times[i]: float(closes[i] / closes[i - 24] - 1.0) for i in range(24, len(b))
        }
    for row in rows:
        ts = int(row["signal_ts"])
        values = [by_symbol[symbol].get(ts, float("nan")) for symbol in syms]
        side = 1.0 if str(row["side"]) == "long" else -1.0
        row["broad24_side_aligned"] = side * float(np.nanmedian(values))


def aggressive_diagnostic(
    selected: dict[str, Any],
    rider: list[dict[str, Any]],
    hg: list[dict[str, Any]],
    cutoff: int,
    base_weight: float,
    vol_q67: float,
    vol_q85: float,
    load_threshold: int,
) -> dict[str, Any]:
    attach_broad24(rider)
    rows: dict[str, Any] = {}
    for floor in (0.50, 0.25):
        routed = [dict(x, adjusted_bps=float(x["net_bps"])) for x in hg]
        for row in rider:
            vol_factor = (
                0.0
                if float(row["vol_ratio"]) > vol_q85
                else (0.25 if float(row["vol_ratio"]) > vol_q67 else 1.0)
            )
            load_factor = (
                0.50 if int(row["prior_signal_load24"]) >= load_threshold else 1.0
            )
            broad_factor = floor if float(row["broad24_side_aligned"]) <= 0 else 1.0
            risk = base_weight * vol_factor * load_factor * broad_factor
            routed.append(dict(row, adjusted_bps=risk * float(row["net_bps"])))
        train = [x for x in routed if int(x["signal_ts"]) <= cutoff]
        hold = [x for x in routed if int(x["signal_ts"]) > cutoff]
        rows[str(floor)] = {
            "full": a2.metric(routed, "adjusted_bps"),
            "train60_time": a2.metric(train, "adjusted_bps"),
            "holdout40_time": a2.metric(hold, "adjusted_bps"),
            "monthly_net_bps": monthly(routed, "adjusted_bps"),
        }
    return {
        "authority": "DIAGNOSTIC_ONLY_HOLDOUT_ALREADY_INSPECTED",
        "rule": "additional rider risk reduction when six-symbol median 24h return opposes trade side",
        "rows": rows,
        "selected_core_reference": selected,
    }


def main() -> int:
    feat, cutoff, q, rider_raw, source, hg = a2.build_inputs()
    rider = a2.attach_context(feat, rider_raw, source)
    attach_load24(rider)
    weight = rider_weight(hg, rider, cutoff)
    train_feat = feat[feat.ts_ms <= cutoff]
    vol_q85 = float(train_feat.vol_ratio.quantile(0.85))
    load_q85 = int(
        math.ceil(
            float(
                np.quantile(
                    [
                        x["prior_signal_load24"]
                        for x in rider
                        if int(x["signal_ts"]) <= cutoff
                    ],
                    0.85,
                )
            )
        )
    )

    candidates: dict[str, Any] = {}
    candidates["V2_BASE"] = evaluate(
        rider, hg, cutoff, weight, q["vol_q67"], vol_q85, load_q85, None, False
    )
    candidates["EXTREME_VOL_OFF"] = evaluate(
        rider, hg, cutoff, weight, q["vol_q67"], vol_q85, load_q85, None, True
    )
    for floor in LOAD_FLOORS:
        candidates[f"EXTREME_VOL_OFF_LOAD_{floor:.2f}"] = evaluate(
            rider, hg, cutoff, weight, q["vol_q67"], vol_q85, load_q85, floor, True
        )

    base = candidates["V2_BASE"]["train60_time"]
    eligible: list[tuple[str, dict[str, Any], float]] = []
    for name, row in candidates.items():
        if name == "V2_BASE":
            continue
        train = row["train60_time"]
        train_months = row["train_monthly_net_bps"]
        worst_month = min(train_months.values()) if train_months else float("-inf")
        if (
            float(train["Net_bps"]) >= TRAIN_NET_RETENTION * float(base["Net_bps"])
            and float(train["PF"] or 0.0) >= float(base["PF"] or 0.0)
            and float(train["DD_bps"]) <= float(base["DD_bps"])
        ):
            eligible.append((name, row, worst_month))

    chosen_name = (
        max(
            eligible,
            key=lambda item: (
                item[2],
                float(item[1]["train60_time"]["PF"] or 0.0),
                float(item[1]["train60_time"]["Net_bps"]),
            ),
        )[0]
        if eligible
        else "V2_BASE"
    )
    chosen = candidates[chosen_name]
    aggressive = aggressive_diagnostic(
        chosen,
        rider,
        hg,
        cutoff,
        weight,
        q["vol_q67"],
        vol_q85,
        load_q85,
    )
    v1 = json.load(open(ROOT / "priority_economic_program_v1.json"))
    v2r = json.load(open(ROOT / "economic_core_loss_autopsy_v2.json"))
    out = {
        "schema": "zel.economic_core.tail_guard.v3",
        "state": "DEV_TRAIN_SELECTED_TAIL_GUARD_NOT_LIVE_AUTHORIZED",
        "objective": "reduce weak-month losses while preserving physical T and at least 98% of V2 train net",
        "cutoff_ts": cutoff,
        "base_rider_weight_train_only": weight,
        "vol_q67_train_only": q["vol_q67"],
        "vol_q85_train_only": vol_q85,
        "signal_load24_q85_train_only": load_q85,
        "selection_rule": "train only: >=98% V2 train net, PF no worse, DD no worse; then maximize worst train month",
        "candidate_set": candidates,
        "chosen": chosen_name,
        "chosen_metrics": chosen,
        "progression": {
            "v1_months": v1["portfolios"]["core_train_vol_scaled"]["months"],
            "v2_months": v2r["throttle_results"][str(v2r["chosen_high_vol_floor"])][
                "monthly_net_bps"
            ],
            "v3_months": chosen["monthly_net_bps"],
        },
        "aggressive_holdout_informed_diagnostic": aggressive,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "fresh_forward_required": True,
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "ECONOMIC_CORE_TAIL_V3="
        + json.dumps(
            {
                "chosen": chosen_name,
                "full": chosen["full"],
                "train": chosen["train60_time"],
                "hold": chosen["holdout40_time"],
                "months": chosen["monthly_net_bps"],
                "load_q85": load_q85,
                "vol_q85": vol_q85,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
