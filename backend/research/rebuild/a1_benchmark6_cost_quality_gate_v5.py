from __future__ import annotations

import argparse
from collections import Counter
import importlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
sm: Any = importlib.import_module(
    "backend.research.rebuild.benchmark25_donor_state_machine_v2"
)

SELECTED_TF = {
    "trend_ma_macd": 900_000,
    "trend_rider": 900_000,
    "supertrend_pullback": 900_000,
    "keltner_trend": 1_800_000,
    "turtle_trend": 3_600_000,
    "fvg_revert": 900_000,
}
GATES = (
    "NONE",
    "ATR_COST_4",
    "ATR_COST_6",
    "ATR_COST_8",
    "RISK_COST_3",
    "RISK_COST_4",
    "RISK_COST_5",
    "ATR4_RISK3",
    "ATR6_RISK4",
    "DONOR_A",
    "DONOR_B",
)

MIN_FULL_T = {900_000: 300, 1_800_000: 300, 3_600_000: 120}
MIN_TRAIN_T = {900_000: 100, 1_800_000: 100, 3_600_000: 60}


def tf_name(ms: int) -> str:
    return {900_000: "15m", 1_800_000: "30m", 3_600_000: "1h"}[ms]


def _safe(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def signal_features(
    sid: str,
    signal: Any,
    frame: pd.DataFrame,
    cost_bps: float,
    spec: Mapping[str, Any],
) -> dict[str, float]:
    i = int(signal.index)
    row = frame.iloc[i]
    entry = float(frame.iloc[i + 1]["open"])
    atr = max(_safe(row.get("atr"), 0.0), 1e-12)
    stop = v2.initial_stop(signal, row, entry, spec)
    risk_bps = abs(entry - stop) / entry * 10_000.0
    atr_bps = atr / entry * 10_000.0
    prev = frame.iloc[max(0, i - 1)]
    trend_sep = abs(_safe(row.get("ema21")) - _safe(row.get("ema55"))) / atr
    return {
        "atr_cost": atr_bps / max(cost_bps, 1e-9),
        "risk_cost": risk_bps / max(cost_bps, 1e-9),
        "trend_sep_atr": trend_sep,
        "rel_vol20": _safe(row.get("rel_vol20"), 0.0),
        "range_atr": (_safe(row.get("high")) - _safe(row.get("low"))) / atr,
        "prev_range_atr": (_safe(prev.get("high")) - _safe(prev.get("low"))) / atr,
        "dist21_atr": abs(_safe(row.get("close")) - _safe(row.get("ema21"))) / atr,
    }


def gate_pass(sid: str, gate: str, f: Mapping[str, float]) -> bool:
    if gate == "NONE":
        return True
    if gate == "ATR_COST_4":
        return f["atr_cost"] >= 4.0
    if gate == "ATR_COST_6":
        return f["atr_cost"] >= 6.0
    if gate == "ATR_COST_8":
        return f["atr_cost"] >= 8.0
    if gate == "RISK_COST_3":
        return f["risk_cost"] >= 3.0
    if gate == "RISK_COST_4":
        return f["risk_cost"] >= 4.0
    if gate == "RISK_COST_5":
        return f["risk_cost"] >= 5.0
    if gate == "ATR4_RISK3":
        return f["atr_cost"] >= 4.0 and f["risk_cost"] >= 3.0
    if gate == "ATR6_RISK4":
        return f["atr_cost"] >= 6.0 and f["risk_cost"] >= 4.0
    if sid in {"trend_ma_macd", "trend_rider", "supertrend_pullback", "keltner_trend"}:
        if gate == "DONOR_A":
            return f["atr_cost"] >= 4.0 and f["trend_sep_atr"] >= 0.60
        if gate == "DONOR_B":
            return (
                f["risk_cost"] >= 3.0
                and f["trend_sep_atr"] >= 0.80
                and f["rel_vol20"] >= 0.90
            )
    if sid == "turtle_trend":
        if gate == "DONOR_A":
            return (
                f["atr_cost"] >= 4.0 and f["range_atr"] >= 1.0 and f["rel_vol20"] >= 1.0
            )
        if gate == "DONOR_B":
            return f["risk_cost"] >= 4.0 and f["rel_vol20"] >= 1.20
    if sid == "fvg_revert":
        if gate == "DONOR_A":
            return f["atr_cost"] >= 4.0 and f["prev_range_atr"] >= 1.30
        if gate == "DONOR_B":
            return f["risk_cost"] >= 3.0 and f["prev_range_atr"] >= 1.60
    return False


def fixed_split_metrics(
    trades: list[dict[str, Any]], boundary_ts: int
) -> dict[str, dict[str, Any]]:
    train = [t for t in trades if int(t["exit_ts"]) <= boundary_ts]
    hold = [t for t in trades if int(t["exit_ts"]) > boundary_ts]
    return {"train60_fixed": v2.metrics(train), "holdout40_fixed": v2.metrics(hold)}


def base_samples(
    sid: str,
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    spec: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    samples: list[dict[str, Any]] = []
    symbols = ("BTC-USDT", "ETH-USDT") if spec["microstructure_required"] else v2.SYMS6
    for sym in symbols:
        x = frames[sym]
        state = sm.MachineState()
        i = 101
        while i < len(x) - 1:
            sig = sm.step_machine(sid, state, x, i, spec)
            if sig is None:
                i += 1
                continue
            feat = signal_features(sid, sig, x, float(costs[sym]), spec)
            trade, exit_j = v2.simulate_trade(sid, sig, x, float(costs[sym]), spec)
            if trade is not None:
                trade["symbol"] = sym
                samples.append({"trade": trade, "features": feat})
            state.reset()
            i = max(i + 1, exit_j + 1)
    ordered = sorted(
        samples,
        key=lambda z: (int(z["trade"]["exit_ts"]), str(z["trade"]["symbol"])),
    )
    if not ordered:
        return [], 0
    cut = max(1, int(len(ordered) * 0.60))
    boundary = int(ordered[min(cut - 1, len(ordered) - 1)]["trade"]["exit_ts"])
    return ordered, boundary


def train_gate_table(
    sid: str, samples: list[dict[str, Any]], boundary_ts: int, tf: int
) -> list[dict[str, Any]]:
    base_train = [z for z in samples if int(z["trade"]["exit_ts"]) <= boundary_ts]
    rows = []
    for gate in GATES:
        chosen = [z["trade"] for z in base_train if gate_pass(sid, gate, z["features"])]
        m = v2.metrics(chosen)
        retention = len(chosen) / max(1, len(base_train))
        eligible = bool(
            len(chosen) >= MIN_TRAIN_T[tf]
            and retention >= 0.25
            and m.get("GrossExp_bps_T") is not None
        )
        rows.append(
            {
                "gate": gate,
                "eligible": eligible,
                "retention": retention,
                "metrics": m,
            }
        )
    return rows


def choose_gate(rows: list[dict[str, Any]]) -> tuple[str, str]:
    eligible = [r for r in rows if r["eligible"]]
    if not eligible:
        return "NONE", "NO_ELIGIBLE_GATE"
    target = [
        r for r in eligible if float(r["metrics"]["GrossExp_bps_T"] or -1e9) >= 25.0
    ]
    pool = target if target else eligible
    best = max(
        pool,
        key=lambda r: (
            float(r["metrics"]["GrossExp_bps_T"] or -1e9),
            float(r["retention"]),
        ),
    )
    return str(best["gate"]), (
        "TRAIN_GROSS_25_PASS" if target else "BEST_TRAIN_GROSS_BELOW_25"
    )


def exact_gated_replay(
    sid: str,
    gate: str,
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    spec: Mapping[str, Any],
    boundary_ts: int,
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    rejected = 0
    admitted = 0
    symbols = ("BTC-USDT", "ETH-USDT") if spec["microstructure_required"] else v2.SYMS6
    for sym in symbols:
        x = frames[sym]
        state = sm.MachineState()
        i = 101
        while i < len(x) - 1:
            sig = sm.step_machine(sid, state, x, i, spec)
            if sig is None:
                i += 1
                continue
            feat = signal_features(sid, sig, x, float(costs[sym]), spec)
            if not gate_pass(sid, gate, feat):
                rejected += 1
                state.reset()
                i += 1
                continue
            admitted += 1
            trade, exit_j = v2.simulate_trade(sid, sig, x, float(costs[sym]), spec)
            if trade is not None:
                trade["symbol"] = sym
                trade["quality_features"] = feat
                trades.append(trade)
            state.reset()
            i = max(i + 1, exit_j + 1)
    full = v2.metrics(trades)
    split = fixed_split_metrics(trades, boundary_ts)
    hold = split["holdout40_fixed"]
    min_t = MIN_FULL_T[int(spec["timeframe_ms"])]
    gross_pass = bool(
        (full.get("GrossExp_bps_T") or -1e9) >= 25.0
        and (hold.get("GrossExp_bps_T") or -1e9) >= 25.0
        and int(full.get("T") or 0) >= min_t
    )
    economic_pass = bool(
        (full.get("Net_bps") or 0) > 0
        and (full.get("PF") or 0) > 1
        and (hold.get("Net_bps") or 0) > 0
        and (hold.get("PF") or 0) > 1
        and int(full.get("T") or 0) >= min_t
    )
    return {
        "gate": gate,
        "admitted": admitted,
        "rejected": rejected,
        "metrics": full,
        **split,
        "gross_25_holdout_pass": gross_pass,
        "economic_pass": economic_pass,
        "exit_reasons": dict(Counter(t["reason"] for t in trades)),
        "trades": trades,
    }


def build_frames_for_tf(
    all_spec: Mapping[str, Any], sid: str, tf: int
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    spec_copy = json.loads(json.dumps(all_spec))
    child = spec_copy["children"][sid]
    child["timeframe_ms"] = tf
    child["timeframe"] = tf_name(tf)
    child["child_id"] = f"{sid}__cost_quality_v5__{tf_name(tf)}"
    spec_copy["children"] = {sid: child}
    frames_by_tf, _ = v2.prepare_frames(spec_copy)
    return frames_by_tf[tf], child


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-id", choices=tuple(SELECTED_TF))
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    sm.validate_coverage()
    all_spec = sm.load_spec()
    authority = v2.read_json(v2.COST_PATH)
    snap_cache: dict[str, dict[str, Any]] = {}

    def cost(sym: str) -> float:
        if sym not in snap_cache:
            snap_cache[sym] = v2.cost_ev.fetch_execution_snapshot(sym, authority)
        return float(snap_cache[sym]["pretrade_verified_cost_bps"])

    costs = {s: cost(s) for s in v2.SYMS6}
    ids = [args.strategy_id] if args.strategy_id else list(SELECTED_TF)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for sid in ids:
        tf = SELECTED_TF[sid]
        frames, spec = build_frames_for_tf(all_spec, sid, tf)
        samples, boundary = base_samples(sid, frames, costs, spec)
        table = train_gate_table(sid, samples, boundary, tf)
        chosen, selection_state = choose_gate(table)
        exact = exact_gated_replay(sid, chosen, frames, costs, spec, boundary)
        report = {
            "schema": "zel.a1.benchmark6.cost_quality_gate.v5",
            "strategy_id": sid,
            "timeframe": tf_name(tf),
            "timeframe_ms": tf,
            "selection_boundary_ts": boundary,
            "selection_state": selection_state,
            "chosen_gate": chosen,
            "train_gate_table": table,
            "exact": exact,
            "parameter_sweep": "PREDECLARED_CAUSAL_GATES_ONLY",
            "research_only": True,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }
        out = args.out_dir / f"{sid}.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        reports.append(report)
        compact = {
            "strategy_id": sid,
            "timeframe": tf_name(tf),
            "chosen_gate": chosen,
            "selection_state": selection_state,
            "T": exact["metrics"].get("T"),
            "WR": exact["metrics"].get("WR"),
            "GrossExp_bps_T": exact["metrics"].get("GrossExp_bps_T"),
            "NetExp_bps_T": exact["metrics"].get("Exp_bps_T"),
            "PF": exact["metrics"].get("PF"),
            "HoldGrossExp_bps_T": exact["holdout40_fixed"].get("GrossExp_bps_T"),
            "HoldNetExp_bps_T": exact["holdout40_fixed"].get("Exp_bps_T"),
            "HoldPF": exact["holdout40_fixed"].get("PF"),
            "gross_25_holdout_pass": exact["gross_25_holdout_pass"],
            "economic_pass": exact["economic_pass"],
        }
        print("QUALITY_V5_ROW=" + json.dumps(compact, sort_keys=True), flush=True)
    summary = {
        "schema": "zel.a1.benchmark6.cost_quality_gate.summary.v5",
        "research_only": True,
        "strategies": [
            {
                "strategy_id": r["strategy_id"],
                "timeframe": r["timeframe"],
                "chosen_gate": r["chosen_gate"],
                "selection_state": r["selection_state"],
                "metrics": r["exact"]["metrics"],
                "holdout40_fixed": r["exact"]["holdout40_fixed"],
                "gross_25_holdout_pass": r["exact"]["gross_25_holdout_pass"],
                "economic_pass": r["exact"]["economic_pass"],
            }
            for r in reports
        ],
    }
    (args.out_dir / "REPORT.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
