from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

PROJECTION = Path(
    "/home/z/z/runtime/exact25_edge_v1/six_layer_observer_suite/outcome_contract_projection_v1.jsonl"
)
OUT = Path(__file__).with_name("material_upgrade_program_v3_results.json")
HOST_LINEAGES = {
    "keltner_trend",
    "trend_rider",
    "break_and_continue",
    "supertrend_pullback",
    "squeeze_break",
}
ALL25 = [
    "alpha_combo",
    "anchor_vwap_trend",
    "bb_revert",
    "break_and_continue",
    "ema_ribbon_scalp",
    "fvg_revert",
    "grid_rebalance",
    "keltner_trend",
    "liquidity_sweep",
    "mfi_rsi_div",
    "obv_trend",
    "pivot_reversal",
    "range_fade",
    "rbreaker_like",
    "rsi_swing_fail",
    "scalp_snap",
    "session_bias",
    "squeeze_break",
    "sr_levels",
    "supertrend_pullback",
    "trend_ma_macd",
    "trend_rider",
    "turtle_trend",
    "vol_spike_fade",
    "vwap_revert",
]
ROLE = {
    "alpha_combo": "entry_quality_material",
    "anchor_vwap_trend": "entry_quality_material",
    "bb_revert": "exit_or_risk_material",
    "ema_ribbon_scalp": "entry_quality_material",
    "fvg_revert": "context_filter_or_veto_material",
    "grid_rebalance": "exit_or_risk_material",
    "liquidity_sweep": "context_filter_or_veto_material",
    "mfi_rsi_div": "exit_or_risk_material",
    "obv_trend": "context_filter_or_veto_material",
    "pivot_reversal": "context_filter_or_veto_material",
    "range_fade": "exit_or_risk_material",
    "rbreaker_like": "entry_quality_material",
    "rsi_swing_fail": "exit_or_risk_material",
    "scalp_snap": "entry_quality_material",
    "session_bias": "exit_or_risk_material",
    "sr_levels": "context_filter_or_veto_material",
    "trend_ma_macd": "entry_quality_material",
    "turtle_trend": "entry_quality_material",
    "vol_spike_fade": "exit_or_risk_material",
    "vwap_revert": "context_filter_or_veto_material",
}
TARGETS = {
    "entry_quality_material": [
        "KELTNER_HG",
        "TREND_RIDER",
        "BREAK",
        "SUPERTREND",
        "SQUEEZE",
    ],
    "context_filter_or_veto_material": [
        "TREND_RIDER",
        "BREAK",
        "SUPERTREND",
        "MR",
        "MICRO",
    ],
    "exit_or_risk_material": [
        "KELTNER_HG",
        "TREND_RIDER",
        "SUPERTREND",
        "SQUEEZE",
        "MR",
    ],
}
EXECUTION_HOLD = {"liquidity_sweep", "scalp_snap"}


def grade(row: dict[str, Any] | None, strategy: str) -> tuple[str, str]:
    if row is None:
        return "HOLD", "SOURCE_OR_SAMPLE_COMPLETION"
    if strategy in EXECUTION_HOLD:
        return "HOLD", "REAL_L2_PASSIVE_EXECUTION_FIDELITY"
    t = int(row["T"])
    exp = float(row["ExpR"])
    mfe = float(row["MFE"])
    if t < 12:
        return "C", "STRUCTURAL_EVENT_DENSITY_REDESIGN"
    if exp > 0:
        return "B", "CAUSAL_CONTROL_HARDENING"
    if exp > -0.10 or (mfe >= 1.20 and exp > -0.25):
        return "C", "ONE_AXIS_PAYOFF_OR_ENTRY_REPAIR"
    return "D", "MARGINAL_ABLATION_ONLY"


def main() -> int:
    df = pd.DataFrame(
        json.loads(line) for line in PROJECTION.read_text().splitlines() if line.strip()
    )
    stats: dict[str, Any] = {}
    for sid, grp in df.groupby("strategy_id"):
        vals = grp["realized_R"].astype(float)
        stats[str(sid)] = {
            "T": int(len(grp)),
            "WR": float((vals > 0).mean()),
            "NetR": float(vals.sum()),
            "ExpR": float(vals.mean()),
            "MFE": float(grp["MFE_R"].astype(float).mean()),
            "MAE": float(grp["MAE_R"].astype(float).mean()),
            "MedianHoldMin": float(grp["time_exposure_min"].astype(float).median()),
        }
    materials = []
    for sid in ALL25:
        if sid in HOST_LINEAGES:
            continue
        row = stats.get(sid)
        g, axis = grade(row, sid)
        role = ROLE[sid]
        materials.append(
            {
                "strategy_id": sid,
                "fresh_shadow": row,
                "material_grade": g,
                "role": role,
                "upgrade_axis": axis,
                "target_hosts": TARGETS[role],
                "max_upgrade_rounds": 3,
            }
        )
    grades = {
        grade_name: [
            x["strategy_id"] for x in materials if x["material_grade"] == grade_name
        ]
        for grade_name in ("A", "B", "C", "D", "HOLD")
    }
    out = {
        "schema": "zel.material_upgrade_program.v3",
        "state": "DEV_MATERIAL_GRADE_REFRESH_COMPLETE",
        "source": str(PROJECTION),
        "source_rows": int(len(df)),
        "source_strategy_count": int(df.strategy_id.nunique()),
        "host_lineages_excluded": sorted(HOST_LINEAGES),
        "material_count": len(materials),
        "grades": grades,
        "materials": materials,
        "fusion_pipeline": [
            "HOLD -> source/execution completion only",
            "D -> veto/exit sidecar marginal ablation only; cannot generate host entries",
            "C -> max 3 one-axis standalone grade-up rounds; no threshold loosening",
            "B/A -> may touch a host one axis at a time",
            "B+A or B+B composite -> require behavior cosine <0.85 and positive marginal Net/PF/DD ablation",
            "composite B -> A only after independent fresh evidence; then eligible for second-stage host fusion",
        ],
        "cxc_policy": "HEAVY_CxC_DISABLED_AFTER_PRIOR_8_PAIR_FUTILITY; reopen only after one parent is upgraded to B/A or a new independently positive standalone appears",
        "host_touch_gate": {
            "minimum_grade": "B",
            "required": [
                "cost-adjusted Net>0",
                "PF>1",
                "T>=12",
                "DD better than worse parent",
                "one changed axis",
                "fresh forward required",
            ],
        },
        "priority_grade_up": [
            "turtle_trend -> breakout persistence material for BREAK/KELTNER",
            "trend_ma_macd -> trend-quality state material, not standalone host",
            "rsi_swing_fail -> loss-tail/failed-swing veto material",
            "rbreaker_like -> breakout/reversal entry material",
            "liquidity_sweep/scalp_snap -> real L2 execution completion before grading",
        ],
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "MATERIAL_V3=" + json.dumps({"grades": grades, "rows": len(df)}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
