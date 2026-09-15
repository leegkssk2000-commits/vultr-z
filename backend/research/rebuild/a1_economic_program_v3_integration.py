from __future__ import annotations

import importlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

core: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic_core_tail_guard_v3"
)
mr: Any = importlib.import_module(
    "backend.research.rebuild.a1_cross_sectional_mean_reversion_v1"
)
a2, p1 = core.a2, core.p1
ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "economic_program_v3_integration.json"


def month(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m")


def build_core_rows() -> tuple[list[dict[str, Any]], int]:
    feat, cutoff, q, rider_raw, source, hg = a2.build_inputs()
    rider = a2.attach_context(feat, rider_raw, source)
    core.attach_load24(rider)
    weight = core.rider_weight(hg, rider, cutoff)
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
    rows = [
        dict(x, strategy="keltner_holygrail_30m", adjusted_bps=float(x["net_bps"]))
        for x in hg
    ]
    for row in rider:
        vol_factor = (
            0.0
            if float(row["vol_ratio"]) > vol_q85
            else (0.25 if float(row["vol_ratio"]) > q["vol_q67"] else 1.0)
        )
        load_factor = 0.50 if int(row["prior_signal_load24"]) >= load_q85 else 1.0
        risk = weight * vol_factor * load_factor
        rows.append(
            dict(
                row,
                strategy="trend_rider_coherent_v3",
                adjusted_bps=risk * float(row["net_bps"]),
            )
        )
    return rows, cutoff


def monthly(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for row in rows:
        out[month(int(row["exit_ts"]))] += float(row[key])
    return dict(sorted(out.items()))


def main() -> int:
    core_rows, cutoff = build_core_rows()
    mr_trades, mr_cutoff, _ = mr.replay()
    if mr_cutoff != cutoff:
        raise RuntimeError(f"CUTOFF_MISMATCH:{cutoff}:{mr_cutoff}")
    mr_rows = [
        {
            "strategy": "cross_sectional_mean_reversion_v1",
            "signal_ts": int(t["signal_ts"]),
            "exit_ts": int(t["exit_ts"]),
            "adjusted_bps": float(t["net_bps"]),
        }
        for t in mr_trades
    ]
    combined = sorted(
        [*core_rows, *mr_rows],
        key=lambda x: (int(x["exit_ts"]), str(x["strategy"])),
    )
    train = [x for x in combined if int(x["signal_ts"]) <= cutoff]
    hold = [x for x in combined if int(x["signal_ts"]) > cutoff]
    core_v3 = json.load(open(ROOT / "economic_core_tail_guard_v3.json"))
    mr_v1 = json.load(open(ROOT / "cross_sectional_mean_reversion_v1.json"))
    micro_dev = json.load(open(ROOT / "micro_exhaustion_sleeve_v1.json"))
    micro_fresh = json.load(open(ROOT / "micro_exhaustion_fresh_forward_v2.json"))
    old_core = json.load(open(ROOT / "priority_economic_program_v1.json"))
    core_t_day = float(old_core["portfolios"]["core_train_vol_scaled"]["T_per_day"])
    mr_t_day = float(mr_v1["T_per_day"])
    micro_edge = micro_dev["candidates"]["EDGE"]
    out: dict[str, Any] = {
        "schema": "zel.economic_program.v3.integration",
        "state": "DEV_ECONOMIC_PROGRAM_NOT_LIVE_AUTHORIZED",
        "core_v3": {
            "chosen": core_v3["chosen"],
            "metrics": core_v3["chosen_metrics"],
            "T_per_day": core_t_day,
        },
        "mean_reversion_v1": {
            "metrics": mr_v1["economics"],
            "T_per_day": mr_t_day,
            "status": mr_v1["state"],
        },
        "combined_core_plus_mean_reversion": {
            "full": a2.metric(combined, "adjusted_bps"),
            "train60_time": a2.metric(train, "adjusted_bps"),
            "holdout40_time": a2.metric(hold, "adjusted_bps"),
            "months": monthly(combined, "adjusted_bps"),
            "nominal_T_per_day": core_t_day + mr_t_day,
        },
        "micro_edge": {
            "development_metrics": {
                key: micro_edge[key]
                for key in ("full", "train60_time", "holdout40_time", "T_per_day")
            },
            "fresh_forward": {
                "fresh_hours": micro_fresh["fresh_hours"],
                "fresh_metrics": micro_fresh["fresh_metrics"],
                "decision": micro_fresh["decision"],
            },
            "status": "DEV_ONLY_FRESH_FORWARD_ACCUMULATION",
        },
        "nominal_frequency_if_micro_edge_survives": core_t_day
        + mr_t_day
        + float(micro_edge["T_per_day"]),
        "authority": {
            "selection": False,
            "promotion": False,
            "execution": "NONE",
            "order": "BLOCKED",
            "live": "BLOCKED",
        },
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "ECONOMIC_PROGRAM_V3="
        + json.dumps(
            {
                "combined": out["combined_core_plus_mean_reversion"]["full"],
                "months": out["combined_core_plus_mean_reversion"]["months"],
                "T_day": out["combined_core_plus_mean_reversion"]["nominal_T_per_day"],
                "T_day_if_micro": out["nominal_frequency_if_micro_edge_survives"],
                "micro_fresh": out["micro_edge"]["fresh_forward"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
