from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

VERSION = "R7A4D_STRATEGY11_ALPHA_EXPECTED_R_FEASIBILITY_V1"
FEATURES = (
    "atr_pct", "adx14", "vwap_distance_atr", "roc10", "volume_z", "directional_close_long",
)
THRESHOLDS = (0.10, 0.15, 0.20)
WINDOW_ORDER = ("F1", "F2", "F3")
RIDGE_ALPHA = 10.0


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def feature_vector(trade: Mapping[str, Any]) -> list[float]:
    features = trade.get("features") if isinstance(trade.get("features"), Mapping) else {}
    row: list[float] = []
    for key in FEATURES:
        raw = features.get(key)
        if isinstance(raw, bool):
            row.append(1.0 if raw else 0.0)
        elif finite(raw):
            row.append(float(raw))
        else:
            raise ValueError(f"FEATURE_MISSING:{trade.get('trade_id')}:{key}")
    return row


def target_r(trade: Mapping[str, Any]) -> float:
    for key in ("net_reference_R", "net_loss_r"):
        value = trade.get(key)
        if finite(value):
            return float(value)
    risk = trade.get("reference_risk_pct", trade.get("risk_pct"))
    net = trade.get("net_return_pct")
    if finite(risk) and float(risk) > 0 and finite(net):
        return float(net) / float(risk)
    raise ValueError(f"TARGET_R_MISSING:{trade.get('trade_id')}")


def fit_predict(train: list[dict[str, Any]], test: list[dict[str, Any]]) -> list[float]:
    x_train = np.asarray([feature_vector(row) for row in train], dtype=float)
    y_train = np.asarray([target_r(row) for row in train], dtype=float)
    x_test = np.asarray([feature_vector(row) for row in test], dtype=float)
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std[std < 1e-9] = 1.0
    z_train = (x_train - mean) / std
    z_test = (x_test - mean) / std
    design = np.column_stack([np.ones(len(z_train)), z_train])
    test_design = np.column_stack([np.ones(len(z_test)), z_test])
    penalty = np.eye(design.shape[1]) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    return [float(value) for value in test_design @ beta]


def profit_factor(values: list[float]) -> float | None:
    wins = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    return None if losses <= 0 else wins / losses


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha-root", required=True)
    ap.add_argument("--lineage-summary", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.alpha_root).resolve()
    lineage_path = Path(args.lineage_summary).resolve()
    out = Path(args.out).resolve()
    lineage = load(lineage_path)
    if lineage.get("state") != "PASS_FEATURE_LINEAGE":
        raise RuntimeError("RAW_FEATURE_LINEAGE_NOT_PASS")

    replay_path = root / "INCUMBENT_CONTROL" / "replay-A.json"
    authority_path = root / "summary.json"
    trades = [dict(row) for row in load(replay_path).get("trades", []) if isinstance(row, Mapping)]
    by_window = {window: [row for row in trades if row.get("window_id") == window] for window in WINDOW_ORDER}
    if any(len(by_window[window]) == 0 for window in WINDOW_ORDER):
        raise RuntimeError("WINDOW_TRADE_MISSING")

    predictions: list[dict[str, Any]] = []
    train: list[dict[str, Any]] = list(by_window["F1"])
    for window in ("F2", "F3"):
        test = by_window[window]
        if len(train) < 8:
            raise RuntimeError(f"TRAIN_SAMPLE_TOO_SMALL:{window}:{len(train)}")
        predicted = fit_predict(train, test)
        for trade, expected_r in zip(test, predicted):
            predictions.append({
                "trade_id": trade.get("trade_id"),
                "window_id": window,
                "symbol": trade.get("symbol"),
                "entry_ts": trade.get("entry_ts"),
                "expected_r_oof": expected_r,
                "realized_net_reference_r": target_r(trade),
                "feature_sha256": hashlib.sha256(json.dumps(trade.get("features"), sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            })
        train.extend(test)

    control_values = [row["realized_net_reference_r"] for row in predictions]
    control_mean = sum(control_values) / len(control_values)
    control_pf = profit_factor(control_values)
    control_winners = sum(value > 0 for value in control_values)
    threshold_rows: list[dict[str, Any]] = []

    for threshold in THRESHOLDS:
        selected = [row for row in predictions if row["expected_r_oof"] >= threshold]
        rejected = [row for row in predictions if row["expected_r_oof"] < threshold]
        selected_values = [row["realized_net_reference_r"] for row in selected]
        selected_pf = profit_factor(selected_values)
        retention = len(selected) / len(predictions) * 100.0
        rejected_winners = sum(row["realized_net_reference_r"] > 0 for row in rejected)
        winner_contamination = 0.0 if control_winners == 0 else rejected_winners / control_winners * 100.0
        per_window_net = {
            window: sum(row["realized_net_reference_r"] for row in selected if row["window_id"] == window)
            for window in ("F2", "F3")
        }
        selected_mean = None if not selected_values else sum(selected_values) / len(selected_values)
        pf_nonworse = selected_pf is not None and control_pf is not None and selected_pf >= control_pf
        passes = (
            len(predictions) >= 12
            and retention >= 80.0
            and selected_mean is not None
            and selected_mean >= control_mean + 0.10
            and sum(selected_values) > 0
            and pf_nonworse
            and winner_contamination <= 20.0
            and all(value > 0 for value in per_window_net.values())
        )
        threshold_rows.append({
            "threshold_expected_r": threshold,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "trade_retention_pct": retention,
            "control_mean_r": control_mean,
            "selected_mean_r": selected_mean,
            "delta_mean_r": None if selected_mean is None else selected_mean - control_mean,
            "control_profit_factor": control_pf,
            "selected_profit_factor": selected_pf,
            "winner_contamination_pct": winner_contamination,
            "per_window_selected_net_r": per_window_net,
            "pass_to_isolated_replay": passes,
        })

    eligible = [row for row in threshold_rows if row["pass_to_isolated_replay"]]
    winner = max(eligible, key=lambda row: (row["delta_mean_r"], row["selected_profit_factor"], row["trade_retention_pct"])) if eligible else None
    blockers = [] if winner else ["NO_EXPECTED_R_THRESHOLD_PASSED_CAUSAL_FEASIBILITY"]
    state = "PASS_TO_ISOLATED_REPLAY" if winner else "RESEARCH_HOLD"
    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "strategy_id": "alpha_combo",
        "source_authority": {
            "pr": 211,
            "run_id": 30278422559,
            "artifact": "s11-alpha-cost-aware-stop-v1-30278422559-attempt-1",
            "replay_a_sha256": sha(replay_path),
            "summary_sha256": sha(authority_path),
            "raw_feature_lineage_run_id": 30312377783,
            "raw_feature_lineage_summary_sha256": sha(lineage_path),
        },
        "estimator_contract": {
            "type": "WALK_FORWARD_RIDGE",
            "ridge_alpha": RIDGE_ALPHA,
            "features": list(FEATURES),
            "training": "F1_TO_F2_THEN_F1_PLUS_F2_TO_F3",
            "test_windows": ["F2", "F3"],
            "lookahead": False,
            "parameter_tuning": False,
            "thresholds_from_gemini_hypothesis": list(THRESHOLDS),
        },
        "audit": {
            "total_authority_trades": len(trades),
            "oof_prediction_count": len(predictions),
            "control_mean_r": control_mean,
            "control_profit_factor": control_pf,
            "thresholds": threshold_rows,
            "winner": winner,
        },
        "blockers": blockers,
        "next": "CREATE_FULL_STATE_ISOLATED_ENTRY_GATE_REPLAY" if winner else "WAIT_W1_NEW_CAUSAL_EVIDENCE",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    write(out / "summary.json", result)
    write(out / "oof_predictions.json", {"rows": predictions})
    print(json.dumps({"state": state, "oof": len(predictions), "winner": None if winner is None else winner["threshold_expected_r"], "blockers": blockers}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
