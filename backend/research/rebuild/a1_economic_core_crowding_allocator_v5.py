from __future__ import annotations

import importlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

p1: Any = importlib.import_module(
    "backend.research.rebuild.a1_priority_economic_program_v1"
)
a2: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic_core_loss_autopsy_v2"
)
v3: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic_core_tail_guard_v3"
)

ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "economic_core_crowding_allocator_v5.json"
CAPS = (2.0, 1.5, 1.0)


def decision_streak(rows: list[dict[str, Any]], key: str) -> int:
    buckets: dict[tuple[int, str], float] = defaultdict(float)
    for row in rows:
        hour = int(row["signal_ts"]) // 3_600_000
        buckets[(hour, str(row.get("side", "portfolio")))] += float(row[key])
    cur = best = 0
    for _, value in sorted(buckets.items()):
        cur = cur + 1 if value < 0 else 0
        best = max(best, cur)
    return best


def build_rows() -> tuple[list[dict[str, Any]], int, float, int, float]:
    feat, cutoff, q, rider_raw, source, hg = a2.build_inputs()
    rider = a2.attach_context(feat, rider_raw, source)
    v3.attach_load24(rider)
    weight = v3.rider_weight(hg, rider, cutoff)
    train_feat = feat[feat.ts_ms <= cutoff]
    vol_q85 = float(train_feat.vol_ratio.quantile(0.85))
    load_q85 = int(
        np.ceil(
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
    rows = [dict(x, current_risk=1.0, current_bps=float(x["net_bps"])) for x in hg]
    for row in rider:
        vol_factor = (
            0.0
            if float(row["vol_ratio"]) > vol_q85
            else (0.25 if float(row["vol_ratio"]) > q["vol_q67"] else 1.0)
        )
        load_factor = 0.50 if int(row["prior_signal_load24"]) >= load_q85 else 1.0
        risk = weight * vol_factor * load_factor
        rows.append(
            dict(row, current_risk=risk, current_bps=risk * float(row["net_bps"]))
        )
    return rows, cutoff, weight, load_q85, vol_q85


def apply_cap(rows: list[dict[str, Any]], cap: float) -> list[dict[str, Any]]:
    cohorts: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row["strategy"]) != "trend_rider_coherent_v2":
            continue
        key = (int(row["signal_ts"]) // 3_600_000, str(row.get("side", "na")))
        cohorts[key].append(row)
    scale: dict[int, float] = {}
    for xs in cohorts.values():
        total = sum(float(x["current_risk"]) for x in xs)
        factor = min(1.0, cap / total) if total > 0 else 1.0
        for x in xs:
            scale[id(x)] = factor
    out = []
    for row in rows:
        factor = scale.get(id(row), 1.0)
        item = dict(row)
        item["adjusted_bps"] = factor * float(row["current_bps"])
        item["crowding_scale"] = factor
        out.append(item)
    return out


def summarize(rows: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    train = [x for x in rows if int(x["signal_ts"]) <= cutoff]
    hold = [x for x in rows if int(x["signal_ts"]) > cutoff]
    return {
        "full": a2.metric(rows, "adjusted_bps"),
        "train": a2.metric(train, "adjusted_bps"),
        "hold": a2.metric(hold, "adjusted_bps"),
        "decision_streak_full": decision_streak(rows, "adjusted_bps"),
        "decision_streak_train": decision_streak(train, "adjusted_bps"),
        "decision_streak_hold": decision_streak(hold, "adjusted_bps"),
    }


def main() -> int:
    rows, cutoff, weight, load_q85, vol_q85 = build_rows()
    baseline = []
    for row in rows:
        item = dict(row)
        item["adjusted_bps"] = float(row["current_bps"])
        item["crowding_scale"] = 1.0
        baseline.append(item)
    candidates = {"BASE": summarize(baseline, cutoff)}
    for cap in CAPS:
        candidates[f"CAP_{cap:.1f}"] = summarize(apply_cap(rows, cap), cutoff)

    base = candidates["BASE"]["train"]
    eligible = []
    for name, row in candidates.items():
        if name == "BASE":
            continue
        tr = row["train"]
        if (
            float(tr["Net_bps"]) >= 0.98 * float(base["Net_bps"])
            and float(tr["PF"] or 0.0) >= float(base["PF"] or 0.0)
            and float(tr["DD_bps"]) <= float(base["DD_bps"])
        ):
            eligible.append((name, row))
    chosen = max(
        eligible,
        key=lambda x: (
            -int(x[1]["decision_streak_train"]),
            float(x[1]["train"]["PF"] or 0.0),
            float(x[1]["train"]["Net_bps"]),
        ),
        default=("BASE", candidates["BASE"]),
    )[0]
    out = {
        "schema": "zel.economic_core.crowding_allocator.v5",
        "state": "DEV_TRAIN_SELECTED_CROWDING_CAP_NOT_LIVE_AUTHORIZED",
        "objective": "cap same-hour same-direction Trend Rider correlated risk without altering Keltner rules",
        "cutoff_ts": cutoff,
        "base_rider_weight_train_only": weight,
        "signal_load24_q85_train_only": load_q85,
        "vol_q85_train_only": vol_q85,
        "candidates": candidates,
        "chosen": chosen,
        "selection_rule": "train only: >=98% base net, PF no worse, DD no worse; then minimize portfolio decision loss streak",
        "diagnosis": "trade-level streak overcounts correlated same-hour cross-symbol Trend Rider bets; cap aggregate sleeve risk instead of adding July-specific entry filters",
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "fresh_forward_required": True,
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "CORE_CROWDING_V5="
        + json.dumps({"chosen": chosen, "rows": candidates}, sort_keys=True),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
