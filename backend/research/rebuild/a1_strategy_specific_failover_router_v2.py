from __future__ import annotations

import importlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v1: Any = importlib.import_module(
    "backend.research.rebuild.a1_causal_strategy_failover_router_v1"
)
sp: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic7_improvement_sprint_v1"
)

ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "strategy_specific_failover_router_v2.json"
REPO_OUT = Path(__file__).with_name("strategy_specific_failover_router_v2_results.json")


def ema(values: pd.Series, span: int) -> pd.Series:
    return values.ewm(span=span, adjust=False).mean()


def rider_trend_alignment(
    rows: list[dict[str, Any]], bars: dict[str, list[dict[str, Any]]]
) -> dict[tuple[int, str], bool]:
    frames: dict[str, pd.DataFrame] = {}
    for symbol, raw in bars.items():
        df = pd.DataFrame(raw).sort_values("ts_ms").reset_index(drop=True)
        close = df["close"].astype(float)
        df["ema21"] = ema(close, 21)
        df["ema55"] = ema(close, 55)
        frames[symbol] = df.set_index("ts_ms")
    out: dict[tuple[int, str], bool] = {}
    for row in rows:
        symbol = str(row["symbol"])
        ts = int(row["signal_ts"])
        frame = frames[symbol]
        idx = frame.index[frame.index <= ts]
        if len(idx) == 0:
            raise RuntimeError(f"NO_RIDER_SYMBOL_CONTEXT:{symbol}:{ts}")
        f = frame.loc[int(idx[-1])]
        side = 1.0 if str(row.get("side")) == "long" else -1.0
        out[(ts, symbol)] = side * (float(f["ema21"]) - float(f["ema55"])) > 0
    return out


def feature_vol_delta3(feat: pd.DataFrame) -> dict[int, float]:
    x = feat.sort_values("ts_ms").reset_index(drop=True).copy()
    x["vol_d3"] = x["vol_ratio"] - x["vol_ratio"].shift(3)
    return {
        int(row.ts_ms): float(row.vol_d3)
        for row in x.itertuples()
        if np.isfinite(float(row.vol_d3))
    }


def nearest_feature_value(mapping: dict[int, float], ts: int) -> float:
    keys = np.array(sorted(mapping), dtype=np.int64)
    pos = int(np.searchsorted(keys, ts, side="right") - 1)
    if pos < 0:
        raise RuntimeError(f"NO_FEATURE_VOL_DELTA:{ts}")
    return float(mapping[int(keys[pos])])


def simple(rows: list[dict[str, Any]], key: str = "adjusted_bps") -> dict[str, Any]:
    vals = [float(x[key]) for x in rows]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    return {
        "T": len(vals),
        "Net_bps": sum(vals),
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": sum(wins) / sum(losses) if losses else None,
    }


def build_inputs() -> tuple[
    pd.DataFrame,
    int,
    dict[str, float],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    feat, cutoff, q, strategies, ledger, bars = sp.build_inputs()
    k_lane, k_rows = sp.keltner_lane(strategies, cutoff)
    r_lane, r_rows = sp.rider_lane(strategies, ledger, bars, cutoff)
    s_lane, s_rows = sp.squeeze_lane(strategies, cutoff)
    m_lane, m_rows = sp.mean_reversion_lane(cutoff)
    del k_lane, r_lane, s_lane, m_lane
    lanes = {
        "KELTNER": k_rows,
        "RIDER": r_rows,
        "SQUEEZE": s_rows,
        "MR": m_rows,
    }
    v1.attach_state(feat, q, lanes)
    return feat, cutoff, q, lanes, ledger, bars


def train_evidence(
    gated: list[dict[str, Any]],
    cutoff: int,
    trend_align: dict[tuple[int, str], bool],
    vol_d3_map: dict[int, float],
) -> dict[str, Any]:
    rider_red = [
        x
        for x in gated
        if x["lane"] == "RIDER"
        and int(x["signal_ts"]) <= cutoff
        and float(x["state_risk"]) < 1.0
        and str(x["vol_state"]) == "MID"
        and str(x["breadth_state"]) == "B4"
    ]
    aligned = [
        x
        for x in rider_red
        if trend_align.get((int(x["signal_ts"]), str(x["symbol"])), False)
    ]
    long_aligned = [x for x in aligned if str(x.get("side")) == "long"]
    short_aligned = [x for x in aligned if str(x.get("side")) == "short"]
    long_misaligned = [
        x for x in rider_red if str(x.get("side")) == "long" and x not in aligned
    ]
    squeeze_train = [
        x for x in gated if x["lane"] == "SQUEEZE" and int(x["signal_ts"]) <= cutoff
    ]
    counts: dict[int, int] = defaultdict(int)
    for row in squeeze_train:
        counts[int(row["signal_ts"]) // 3_600_000] += 1
    trusted, guarded = [], []
    for row in squeeze_train:
        count = counts[int(row["signal_ts"]) // 3_600_000]
        vd3 = nearest_feature_value(vol_d3_map, int(row["signal_ts"]))
        if count < 2:
            continue
        if str(row["vol_state"]) == "HIGH" and vd3 > 0:
            trusted.append(row)
        else:
            guarded.append(row)
    return {
        "rider_mid_b4_red_long_trend_aligned": simple(long_aligned),
        "rider_mid_b4_red_short_trend_aligned": simple(short_aligned),
        "rider_mid_b4_red_long_trend_misaligned": simple(long_misaligned),
        "squeeze_multi_fire_trusted": simple(trusted),
        "squeeze_multi_fire_guarded": simple(guarded),
    }


def apply_strategy_specific_gate(
    base: list[dict[str, Any]],
    state_maps: dict[str, Any],
    trend_align: dict[tuple[int, str], bool],
    vol_d3_map: dict[int, float],
) -> list[dict[str, Any]]:
    gated = v1.apply_state_gate(base, state_maps)
    squeeze_counts: dict[int, int] = defaultdict(int)
    for row in gated:
        if row["lane"] == "SQUEEZE":
            squeeze_counts[int(row["signal_ts"]) // 3_600_000] += 1
    out: list[dict[str, Any]] = []
    for row in gated:
        item = dict(row)
        risk = float(row["state_risk"])
        reason = "V1_HIERARCHICAL_STATE"
        if (
            row["lane"] == "RIDER"
            and risk < 1.0
            and str(row.get("side")) == "long"
            and str(row["vol_state"]) == "MID"
            and str(row["breadth_state"]) == "B4"
        ):
            key = (int(row["signal_ts"]), str(row["symbol"]))
            if trend_align.get(key, False):
                risk = 1.0
                reason = "RIDER_MID_B4_SYMBOL_TREND_ALIGNMENT_PAYER_PRESERVE"
        if row["lane"] == "SQUEEZE":
            hour = int(row["signal_ts"]) // 3_600_000
            count = squeeze_counts[hour]
            vd3 = nearest_feature_value(vol_d3_map, int(row["signal_ts"]))
            item["squeeze_same_hour_fire_count"] = count
            item["market_vol_delta3"] = vd3
            if count >= 2 and not (str(row["vol_state"]) == "HIGH" and vd3 > 0):
                risk = min(risk, 0.25)
                reason = "SQUEEZE_MULTI_FIRE_REQUIRES_HIGH_AND_RISING_VOL"
        item["strategy_state_risk"] = risk
        item["strategy_state_reason"] = reason
        item["state_risk"] = risk
        item["routed_bps"] = risk * float(row["adjusted_bps"])
        out.append(item)
    return out


def lane_month(rows: list[dict[str, Any]], lane: str, month: str, key: str) -> float:
    return sum(
        float(x[key])
        for x in rows
        if str(x["lane"]) == lane and v1.month(int(x["exit_ts"])) == month
    )


def month_positive_sum(rows: list[dict[str, Any]], month: str, key: str) -> float:
    return sum(
        max(0.0, float(x[key])) for x in rows if v1.month(int(x["exit_ts"])) == month
    )


def strategy_reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get("strategy_state_reason") or "NONE")] += 1
    return dict(sorted(counts.items()))


def main() -> int:
    feat, cutoff, _, lanes, _, bars = build_inputs()
    state_maps = v1.build_state_maps(lanes, cutoff)
    base = sorted(
        [
            dict(x, base_bps=float(x["adjusted_bps"]))
            for rows in lanes.values()
            for x in rows
        ],
        key=lambda x: (int(x["signal_ts"]), str(x["lane"])),
    )
    v1_gated = v1.apply_state_gate(base, state_maps)
    rider_rows = [x for x in base if x["lane"] == "RIDER"]
    trend_align = rider_trend_alignment(rider_rows, bars)
    vol_d3_map = feature_vol_delta3(feat)
    evidence = train_evidence(v1_gated, cutoff, trend_align, vol_d3_map)
    rider_ok = (
        int(evidence["rider_mid_b4_red_long_trend_aligned"]["T"]) >= 4
        and float(evidence["rider_mid_b4_red_long_trend_aligned"]["Exp_bps_T"] or -1e9)
        > 0
        and float(evidence["rider_mid_b4_red_long_trend_aligned"]["PF"] or 0.0) > 1.0
        and float(evidence["rider_mid_b4_red_short_trend_aligned"]["Exp_bps_T"] or 1e9)
        < 0
        and float(
            evidence["rider_mid_b4_red_long_trend_misaligned"]["Exp_bps_T"] or 1e9
        )
        < 0
    )
    squeeze_ok = (
        int(evidence["squeeze_multi_fire_guarded"]["T"]) >= 4
        and float(evidence["squeeze_multi_fire_guarded"]["Exp_bps_T"] or 1e9) < 0
        and int(evidence["squeeze_multi_fire_trusted"]["T"]) >= 3
        and float(evidence["squeeze_multi_fire_trusted"]["Exp_bps_T"] or -1e9) > 0
    )
    if not rider_ok:
        raise RuntimeError("RIDER_TRAIN_PAYER_PRESERVE_EVIDENCE_FAILED")
    if not squeeze_ok:
        raise RuntimeError("SQUEEZE_TRAIN_MULTI_FIRE_EVIDENCE_FAILED")

    v2_gated = apply_strategy_specific_gate(base, state_maps, trend_align, vol_d3_map)
    v1_rows, v1_receipt = v1.apply_same_hour_failover(v1_gated, 1.0)
    v2_rows, v2_receipt = v1.apply_same_hour_failover(v2_gated, 1.0)
    base_summary = v1.summarize(base, cutoff, "base_bps")
    v1_summary = v1.summarize(v1_rows, cutoff, "final_bps")
    v2_summary = v1.summarize(v2_rows, cutoff, "final_bps")
    v1_train = v1_summary["train"]
    v2_train = v2_summary["train"]
    selection_checks = {
        "train_net_non_decrease_vs_v1": float(v2_train["Net_bps"])
        >= float(v1_train["Net_bps"]),
        "train_pf_non_decrease_vs_v1": float(v2_train["PF"] or 0.0)
        >= float(v1_train["PF"] or 0.0),
        "train_dd_non_increase_vs_v1": float(v2_train["DD_bps"])
        <= float(v1_train["DD_bps"]),
        "worst_train_month_non_decrease_vs_v1": float(
            v2_summary["worst_train_month_bps"]
        )
        >= float(v1_summary["worst_train_month_bps"]),
    }
    train_selected = all(selection_checks.values())
    april_diag = {
        "base_portfolio_bps": base_summary["months_full"].get("2026-04"),
        "v1_portfolio_bps": v1_summary["months_full"].get("2026-04"),
        "v2_portfolio_bps": v2_summary["months_full"].get("2026-04"),
        "base_squeeze_bps": lane_month(base, "SQUEEZE", "2026-04", "base_bps"),
        "v1_squeeze_bps": lane_month(v1_rows, "SQUEEZE", "2026-04", "final_bps"),
        "v2_squeeze_bps": lane_month(v2_rows, "SQUEEZE", "2026-04", "final_bps"),
    }
    august_diag = {
        "base_portfolio_bps": base_summary["months_full"].get("2026-08"),
        "v1_portfolio_bps": v1_summary["months_full"].get("2026-08"),
        "v2_portfolio_bps": v2_summary["months_full"].get("2026-08"),
        "base_positive_bps": month_positive_sum(base, "2026-08", "base_bps"),
        "v1_positive_bps": month_positive_sum(v1_rows, "2026-08", "final_bps"),
        "v2_positive_bps": month_positive_sum(v2_rows, "2026-08", "final_bps"),
    }
    august_diag["v2_positive_retention_vs_base"] = float(
        august_diag["v2_positive_bps"]
    ) / max(float(august_diag["base_positive_bps"]), 1e-9)
    out = {
        "schema": "zel.strategy_specific_failover_router.v2",
        "state": (
            "DEV_TRAIN_SELECTED_STRATEGY_SPECIFIC_ROUTER_NOT_LIVE"
            if train_selected
            else "HOLD_STRATEGY_SPECIFIC_ROUTER"
        ),
        "objective": "fix April Squeeze false-release state while preserving August winners using entry-time causal strategy-specific states",
        "cutoff_ts": cutoff,
        "train_only_rules": {
            "rider": "only for LONG in V1 MID-vol/B4-breadth throttled state, preserve 1.0x when trade-side EMA21-EMA55 remains aligned; train-aligned SHORT remained negative",
            "squeeze": "when >=2 long Squeeze fires occur in the same hour, allow normal risk only if market vol state is HIGH and 3h vol-ratio delta is positive; otherwise cap at 0.25x",
            "failover": "released risk may boost only another GREEN lane that already has a valid same-hour signal; no manufactured replacement trade",
        },
        "train_evidence": evidence,
        "selection_checks": selection_checks,
        "train_selected": train_selected,
        "base": base_summary,
        "router_v1_reference": {"summary": v1_summary, "failover": v1_receipt},
        "router_v2": {
            "summary": v2_summary,
            "failover": v2_receipt,
            "strategy_state_reason_counts": strategy_reason_counts(v2_gated),
        },
        "target_diagnostics": {
            "april_squeeze": april_diag,
            "august_winner_preservation": august_diag,
        },
        "holdout_note": "August and the post-cutoff interval are already-inspected diagnostic history only; they did not define thresholds or selection authority",
        "fresh_forward_required": True,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    payload = json.dumps(out, indent=2, sort_keys=True) + "\n"
    OUT.write_text(payload)
    REPO_OUT.write_text(payload)
    print(
        "STRATEGY_SPECIFIC_FAILOVER_V2="
        + json.dumps(
            {
                "state": out["state"],
                "selection_checks": selection_checks,
                "base_full": base_summary["full"],
                "v1_full": v1_summary["full"],
                "v2_full": v2_summary["full"],
                "v2_train": v2_summary["train"],
                "v2_holdout_diagnostic": v2_summary["holdout_diagnostic"],
                "april": april_diag,
                "august": august_diag,
                "failover": v2_receipt,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
