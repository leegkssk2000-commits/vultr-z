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
a2: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic_core_loss_autopsy_v2"
)
v3: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic_core_tail_guard_v3"
)

ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "economic_core_streak_autopsy_v4.json"


def ym(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m")


def attach_market_context(feat: Any, rows: list[dict[str, Any]]) -> None:
    ts = feat["ts_ms"].to_numpy(dtype=np.int64)
    breadth = feat["breadth"].to_numpy(dtype=float)
    dispersion = feat["dispersion24"].to_numpy(dtype=float)
    mean_abs = feat["mean_abs24"].to_numpy(dtype=float)
    for row in rows:
        pos = int(np.searchsorted(ts, int(row["signal_ts"]), side="right") - 1)
        if pos < 0:
            continue
        row["breadth_abs"] = abs(float(breadth[pos]))
        row["dispersion24"] = float(dispersion[pos])
        row["mean_abs24"] = float(mean_abs[pos])
        side = 1.0 if str(row["side"]) == "long" else -1.0
        row["breadth_side_alignment"] = side * float(breadth[pos])


def bucket_stats(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(float(row["net_bps"]))
    return {
        name: {"T": len(vals), "Exp_bps_T": sum(vals) / len(vals), "Net_bps": sum(vals)}
        for name, vals in sorted(grouped.items())
    }


def streaks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda x: (int(x["exit_ts"]), str(x["strategy"])))
    out: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for row in ordered:
        if float(row["adjusted_bps"]) < 0:
            cur.append(row)
        else:
            if cur:
                out.append(_streak_summary(cur))
                cur = []
    if cur:
        out.append(_streak_summary(cur))
    return sorted(out, key=lambda x: (-int(x["length"]), int(x["start_ts"])))


def _streak_summary(xs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "length": len(xs),
        "net_bps": sum(float(x["adjusted_bps"]) for x in xs),
        "start_ts": min(int(x["signal_ts"]) for x in xs),
        "end_ts": max(int(x["exit_ts"]) for x in xs),
        "months": dict(Counter(ym(int(x["exit_ts"])) for x in xs)),
        "strategies": dict(Counter(str(x["strategy"]) for x in xs)),
        "symbols": dict(Counter(str(x["symbol"]) for x in xs)),
        "sides": dict(Counter(str(x.get("side", "na")) for x in xs)),
        "avg_risk_weight": float(
            np.mean([float(x.get("risk_weight", 1.0)) for x in xs])
        ),
        "rows": [
            {
                k: x.get(k)
                for k in (
                    "strategy",
                    "symbol",
                    "side",
                    "signal_ts",
                    "exit_ts",
                    "adjusted_bps",
                    "vol_ratio",
                    "prior_signal_load24",
                    "breadth_abs",
                )
            }
            for x in xs
        ],
    }


def main() -> int:
    feat, cutoff, q, rider_raw, source, hg = a2.build_inputs()
    rider = a2.attach_context(feat, rider_raw, source)
    v3.attach_load24(rider)
    attach_market_context(feat, rider)

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

    rows = [dict(x, adjusted_bps=float(x["net_bps"]), risk_weight=1.0) for x in hg]
    for row in rider:
        vol_factor = (
            0.0
            if float(row["vol_ratio"]) > vol_q85
            else (0.25 if float(row["vol_ratio"]) > q["vol_q67"] else 1.0)
        )
        load_factor = 0.50 if int(row["prior_signal_load24"]) >= load_q85 else 1.0
        risk = weight * vol_factor * load_factor
        rows.append(
            dict(row, adjusted_bps=risk * float(row["net_bps"]), risk_weight=risk)
        )

    rider_train = [x for x in rider if int(x["signal_ts"]) <= cutoff]
    rider_hold = [x for x in rider if int(x["signal_ts"]) > cutoff]
    for row in rider:
        row["breadth_bucket"] = (
            "B6" if float(row.get("breadth_abs", 0.0)) >= 6 else "B4"
        )
        row["load_bucket"] = (
            "HIGH" if int(row["prior_signal_load24"]) >= load_q85 else "NORMAL"
        )
        vr = float(row["vol_ratio"])
        row["vol_bucket"] = (
            "EXTREME" if vr > vol_q85 else ("HIGH" if vr > q["vol_q67"] else "NORMAL")
        )

    diag = {
        "train_breadth": bucket_stats(rider_train, "breadth_bucket"),
        "holdout_breadth": bucket_stats(rider_hold, "breadth_bucket"),
        "train_load": bucket_stats(rider_train, "load_bucket"),
        "holdout_load": bucket_stats(rider_hold, "load_bucket"),
        "train_vol": bucket_stats(rider_train, "vol_bucket"),
        "holdout_vol": bucket_stats(rider_hold, "vol_bucket"),
    }
    ranked = streaks(rows)
    out = {
        "schema": "zel.economic_core.streak_autopsy.v4",
        "state": "DIAGNOSTIC_COMPLETE_NO_NEW_LIVE_RULE",
        "cutoff_ts": cutoff,
        "current_core": v3.evaluate(
            rider, hg, cutoff, weight, q["vol_q67"], vol_q85, load_q85, 0.50, True
        ),
        "feature_stability": diag,
        "top_loss_streaks": ranked[:10],
        "diagnosis": {
            "max_streak_is_sign_sequence_not_risk_magnitude": True,
            "breadth_filter_rejected": "train B4 is weak but holdout relationship reverses; not stable enough for routing",
            "authorized_improvement_direction": "preserve current volatility/load throttle; seek fresh-data follow-through feature or orthogonal sleeve rather than post-hoc July gate",
        },
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "CORE_STREAK_AUTOPSY_V4="
        + json.dumps(
            {
                "current": out["current_core"]["full"],
                "train_breadth": diag["train_breadth"],
                "holdout_breadth": diag["holdout_breadth"],
                "max_streak": ranked[0] if ranked else None,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
