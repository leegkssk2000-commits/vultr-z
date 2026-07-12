from __future__ import annotations

import html
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ROOT = Path("/home/z/z")
LEDGER_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_all_signal_ledger_latest.json"
ATTRIBUTION_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_drift_attribution_latest.json"
MFE_DIAGNOSTIC_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_mfe_ladder_diagnostic_latest.json"
BOCPD_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_bocpd_observer_latest.json"
DIAGNOSTIC_DECISION_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_diagnostic_decision_latest.json"

SCREEN_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_mfe_stable_feature_screen_latest.json"
PILOT_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_side_pilot_latest.json"
TRANSITION_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_transition_giveback_latest.json"
DECISION_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_pilot_decision_latest.json"
TRIAL_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_trial_registration_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_v3_mfe_pilot_transition_latest.html"

WINDOWS = ("prior_holdout_90d", "second_holdout_90d")
SIDES = ("long", "short")
SCREEN_TARGET_R = 1.5
PILOT_TARGET_R = 1.0
SENSITIVITY_TARGET_R = 0.5
FINAL_TARGET_R = 2.0
MAX_FEATURES_PER_SIDE = 2
CORRELATION_CAP = 0.75
RIDGE_L2 = 2.0
TOP_RETENTION_PCT = 50.0
MIN_TRAIN_CLASS = 10
MIN_TEST_CLASS = 5

NUMERIC_FEATURES = (
    "ema_distance_atr",
    "ema_slope_atr",
    "adx",
    "candle_body_atr",
    "close_location",
    "volume_ratio",
    "macd_signal_spread_atr",
    "macd_signal_spread_prev_atr",
    "chop_score",
    "return_4h",
    "return_24h",
    "realized_vol_24h",
    "range_atr_6h",
    "volume_z_24h",
    "ema50_slope_atr_6h",
    "ema200_slope_atr_6h",
    "atr_percentile_120h",
)

RESEARCH_CONTRACT = {
    "intermediate_target": "Use MFE>=1.5R for cross-window feature discovery because it is the highest represented intermediate endpoint, while preserving 2R as the final economic objective.",
    "pilot_target": "Use MFE>=1.0R for side-separated diagnostic pilots because the prior diagnostic explicitly marked 1.0R as side-pilot-ready and did not mark 1.5R side-pilot-ready.",
    "validation": "Primary transport is prior-90d train to second-90d test. Reverse transport is stability diagnostics only, never causal evidence.",
    "selection": "Feature count, ridge penalty, top-half retention and metrics are pre-registered before fitting; no threshold or hyperparameter search is allowed.",
    "economics": "Prediction quality is insufficient without positive cost-adjusted R and improved 2R conversion in the held-out chronological window.",
    "safety": "All outputs are observer-only. No strategy, registry, paper, live, order or execution mutation is permitted.",
}


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(errors="ignore"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"INVALID_JSON_OBJECT:{path}")
    return payload


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def feature_value(event: Dict[str, Any], feature: str) -> Optional[float]:
    features = event.get("features", {})
    if not isinstance(features, dict):
        return None
    return safe_float(features.get(feature))


def target_value(event: Dict[str, Any], threshold_r: float) -> int:
    return 1 if float(event.get("mfe_R", 0.0)) >= threshold_r else 0


def rank_auc(labels: Sequence[int], scores: Sequence[float]) -> Optional[float]:
    positive = [score for label, score in zip(labels, scores) if int(label) == 1]
    negative = [score for label, score in zip(labels, scores) if int(label) == 0]
    if not positive or not negative:
        return None
    wins = 0.0
    total = len(positive) * len(negative)
    for left in positive:
        for right in negative:
            if left > right:
                wins += 1.0
            elif left == right:
                wins += 0.5
    return float(wins / total)


def pearson(values_left: Sequence[float], values_right: Sequence[float]) -> Optional[float]:
    if len(values_left) != len(values_right) or len(values_left) < 3:
        return None
    left = np.asarray(values_left, dtype=float)
    right = np.asarray(values_right, dtype=float)
    if float(np.std(left)) <= 1e-12 or float(np.std(right)) <= 1e-12:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def drift_map(attribution: Dict[str, Any], scope: str) -> Dict[str, float]:
    numeric = attribution.get("numeric_feature_attribution", {})
    rows = numeric.get(scope, []) if isinstance(numeric, dict) else []
    output: Dict[str, float] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("feature"):
                output[str(row["feature"])] = float(row.get("drift_score", 0.0))
    return output


def feature_window_target_report(
    events: Sequence[Dict[str, Any]], feature: str, threshold_r: float
) -> Dict[str, Any]:
    values: List[float] = []
    labels: List[int] = []
    for event in events:
        value = feature_value(event, feature)
        if value is None:
            continue
        values.append(value)
        labels.append(target_value(event, threshold_r))
    auc = rank_auc(labels, values)
    positive = [value for value, label in zip(values, labels) if label == 1]
    negative = [value for value, label in zip(values, labels) if label == 0]
    oriented = None if auc is None else float((auc - 0.5) * 2.0)
    return {
        "events": len(events),
        "observed": len(values),
        "coverage_pct": float(len(values) / len(events) * 100.0) if events else 0.0,
        "positive": len(positive),
        "negative": len(negative),
        "positive_mean": float(statistics.fmean(positive)) if positive else None,
        "negative_mean": float(statistics.fmean(negative)) if negative else None,
        "auc": auc,
        "oriented_strength": oriented,
    }


def screen_features(
    events: Sequence[Dict[str, Any]],
    attribution: Dict[str, Any],
    *,
    threshold_r: float,
    side: Optional[str],
) -> List[Dict[str, Any]]:
    scope = side if side in SIDES else "all"
    scope_events = [event for event in events if side is None or str(event.get("side")) == side]
    drift = drift_map(attribution, scope)
    reports: List[Dict[str, Any]] = []
    for feature in NUMERIC_FEATURES:
        windows = {
            window: feature_window_target_report(
                [event for event in scope_events if str(event.get("window")) == window],
                feature,
                threshold_r,
            )
            for window in WINDOWS
        }
        first = safe_float(windows[WINDOWS[0]]["oriented_strength"])
        second = safe_float(windows[WINDOWS[1]]["oriented_strength"])
        min_class = min(
            windows[WINDOWS[0]]["positive"],
            windows[WINDOWS[0]]["negative"],
            windows[WINDOWS[1]]["positive"],
            windows[WINDOWS[1]]["negative"],
        )
        min_coverage = min(
            float(windows[WINDOWS[0]]["coverage_pct"]),
            float(windows[WINDOWS[1]]["coverage_pct"]),
        )
        sign_consistent = bool(
            first is not None
            and second is not None
            and abs(first) > 1e-12
            and abs(second) > 1e-12
            and (first > 0) == (second > 0)
        )
        minimum_strength = min(abs(first), abs(second)) if first is not None and second is not None else 0.0
        drift_score = float(drift.get(feature, 0.0))
        stable_score = float(
            minimum_strength
            * math.sqrt(max(min_class, 0) / 10.0)
            * (min_coverage / 100.0)
            / (1.0 + drift_score)
        )
        stable_candidate = bool(
            sign_consistent
            and min_class >= 5
            and min_coverage >= 80.0
            and minimum_strength >= 0.10
        )
        reports.append(
            {
                "feature": feature,
                "scope": scope,
                "target_R": threshold_r,
                "windows": windows,
                "sign_consistent": sign_consistent,
                "minimum_class_per_window": min_class,
                "minimum_coverage_pct": min_coverage,
                "minimum_oriented_strength": minimum_strength,
                "drift_score": drift_score,
                "stable_score": stable_score,
                "stable_candidate": stable_candidate,
                "direction": (
                    "higher_values_favor_target"
                    if sign_consistent and first is not None and first > 0
                    else (
                        "lower_values_favor_target"
                        if sign_consistent and first is not None
                        else "direction_not_stable"
                    )
                ),
            }
        )
    reports.sort(
        key=lambda row: (
            bool(row["stable_candidate"]),
            float(row["stable_score"]),
            float(row["minimum_oriented_strength"]),
        ),
        reverse=True,
    )
    return reports


def paired_feature_values(
    events: Sequence[Dict[str, Any]], left: str, right: str
) -> Tuple[List[float], List[float]]:
    values_left: List[float] = []
    values_right: List[float] = []
    for event in events:
        left_value = feature_value(event, left)
        right_value = feature_value(event, right)
        if left_value is None or right_value is None:
            continue
        values_left.append(left_value)
        values_right.append(right_value)
    return values_left, values_right


def select_nonredundant_features(
    reports: Sequence[Dict[str, Any]],
    events: Sequence[Dict[str, Any]],
    *,
    maximum: int = MAX_FEATURES_PER_SIDE,
) -> Dict[str, Any]:
    selected: List[str] = []
    rejected: List[Dict[str, Any]] = []
    for report in reports:
        if not bool(report.get("stable_candidate")):
            continue
        feature = str(report["feature"])
        redundant_with = None
        correlation = None
        for existing in selected:
            left, right = paired_feature_values(events, feature, existing)
            corr = pearson(left, right)
            if corr is not None and abs(corr) > CORRELATION_CAP:
                redundant_with = existing
                correlation = corr
                break
        if redundant_with is not None:
            rejected.append(
                {
                    "feature": feature,
                    "reason": "correlation_cap",
                    "redundant_with": redundant_with,
                    "correlation": correlation,
                }
            )
            continue
        selected.append(feature)
        if len(selected) >= maximum:
            break
    return {
        "selected": selected,
        "rejected_redundant": rejected,
        "maximum": maximum,
        "correlation_cap": CORRELATION_CAP,
    }


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def fit_ridge_logistic(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    l2: float = RIDGE_L2,
    maximum_iterations: int = 100,
) -> np.ndarray:
    if matrix.ndim != 2 or labels.ndim != 1 or matrix.shape[0] != labels.shape[0]:
        raise ValueError("INVALID_LOGISTIC_SHAPES")
    beta = np.zeros(matrix.shape[1], dtype=float)
    penalty = np.eye(matrix.shape[1], dtype=float) * float(l2)
    penalty[0, 0] = 0.0
    for _ in range(maximum_iterations):
        probabilities = sigmoid(matrix @ beta)
        weights = np.clip(probabilities * (1.0 - probabilities), 1e-6, None)
        gradient = matrix.T @ (probabilities - labels) + penalty @ beta
        hessian = matrix.T @ (matrix * weights[:, None]) + penalty
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(hessian) @ gradient
        beta_next = beta - step
        if float(np.linalg.norm(beta_next - beta)) < 1e-7:
            beta = beta_next
            break
        beta = beta_next
    return beta


def prepare_design(
    train_events: Sequence[Dict[str, Any]],
    test_events: Sequence[Dict[str, Any]],
    features: Sequence[str],
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    if not features:
        raise ValueError("NO_FEATURES")
    train_columns: List[List[float]] = []
    test_columns: List[List[float]] = []
    transforms: Dict[str, Any] = {}
    for feature in features:
        train_raw = [feature_value(event, feature) for event in train_events]
        observed = [value for value in train_raw if value is not None]
        if not observed:
            raise ValueError(f"FEATURE_ALL_MISSING:{feature}")
        median = float(statistics.median(observed))
        train_filled = [median if value is None else float(value) for value in train_raw]
        test_raw = [feature_value(event, feature) for event in test_events]
        test_filled = [median if value is None else float(value) for value in test_raw]
        mean = float(statistics.fmean(train_filled))
        std = float(statistics.pstdev(train_filled)) if len(train_filled) > 1 else 1.0
        std = std if std > 1e-9 else 1.0
        train_columns.append([(value - mean) / std for value in train_filled])
        test_columns.append([(value - mean) / std for value in test_filled])
        transforms[feature] = {"median": median, "mean": mean, "std": std}
    train_core = np.asarray(train_columns, dtype=float).T
    test_core = np.asarray(test_columns, dtype=float).T
    train_matrix = np.column_stack([np.ones(len(train_events)), train_core])
    test_matrix = np.column_stack([np.ones(len(test_events)), test_core])
    return train_matrix, test_matrix, transforms


def log_loss(labels: Sequence[int], probabilities: Sequence[float]) -> float:
    if not labels:
        return 0.0
    total = 0.0
    for label, probability in zip(labels, probabilities):
        p = min(max(float(probability), 1e-9), 1.0 - 1e-9)
        total += -(int(label) * math.log(p) + (1 - int(label)) * math.log(1.0 - p))
    return float(total / len(labels))


def brier_score(labels: Sequence[int], probabilities: Sequence[float]) -> float:
    if not labels:
        return 0.0
    return float(statistics.fmean((int(label) - float(probability)) ** 2 for label, probability in zip(labels, probabilities)))


def profit_factor(values: Sequence[float]) -> float:
    positive = float(sum(value for value in values if value > 0))
    negative = abs(float(sum(value for value in values if value < 0)))
    if negative <= 0:
        return 999.0 if positive > 0 else 0.0
    return float(positive / negative)


def economic_metrics(events: Sequence[Dict[str, Any]], threshold_r: float) -> Dict[str, Any]:
    net_values = [float(event.get("net_R_0.15", 0.0)) for event in events]
    target_count = sum(target_value(event, threshold_r) for event in events)
    tp2r_count = sum(target_value(event, FINAL_TARGET_R) for event in events)
    return {
        "events": len(events),
        "target_positive": target_count,
        "target_rate_pct": float(target_count / len(events) * 100.0) if events else 0.0,
        "tp2r_positive": tp2r_count,
        "tp2r_rate_pct": float(tp2r_count / len(events) * 100.0) if events else 0.0,
        "net_sum_R": float(sum(net_values)),
        "avg_net_R": float(statistics.fmean(net_values)) if net_values else 0.0,
        "profit_factor_R": profit_factor(net_values),
        "positive_rate_pct": float(sum(value > 0 for value in net_values) / len(net_values) * 100.0) if net_values else 0.0,
    }


def calibration_bins(labels: Sequence[int], probabilities: Sequence[float], bins: int = 4) -> List[Dict[str, Any]]:
    rows = sorted(zip(probabilities, labels), key=lambda row: float(row[0]))
    if not rows:
        return []
    output: List[Dict[str, Any]] = []
    for index in range(bins):
        start = int(math.floor(index * len(rows) / bins))
        end = int(math.floor((index + 1) * len(rows) / bins))
        chunk = rows[start:end]
        if not chunk:
            continue
        output.append(
            {
                "bin": index + 1,
                "events": len(chunk),
                "mean_probability": float(statistics.fmean(float(row[0]) for row in chunk)),
                "observed_rate": float(statistics.fmean(int(row[1]) for row in chunk)),
            }
        )
    return output


def transport_fit(
    events: Sequence[Dict[str, Any]],
    *,
    side: str,
    features: Sequence[str],
    threshold_r: float,
    train_window: str,
    test_window: str,
) -> Dict[str, Any]:
    train_events = [
        event for event in events
        if str(event.get("side")) == side and str(event.get("window")) == train_window
    ]
    test_events = [
        event for event in events
        if str(event.get("side")) == side and str(event.get("window")) == test_window
    ]
    train_labels = [target_value(event, threshold_r) for event in train_events]
    test_labels = [target_value(event, threshold_r) for event in test_events]
    readiness = {
        "train_positive": sum(train_labels),
        "train_negative": len(train_labels) - sum(train_labels),
        "test_positive": sum(test_labels),
        "test_negative": len(test_labels) - sum(test_labels),
        "features": len(features),
    }
    evaluable = bool(
        features
        and readiness["train_positive"] >= MIN_TRAIN_CLASS
        and readiness["train_negative"] >= MIN_TRAIN_CLASS
        and readiness["test_positive"] >= MIN_TEST_CLASS
        and readiness["test_negative"] >= MIN_TEST_CLASS
    )
    if not evaluable:
        return {
            "side": side,
            "train_window": train_window,
            "test_window": test_window,
            "target_R": threshold_r,
            "features": list(features),
            "evaluable": False,
            "readiness": readiness,
            "reason": "class_or_feature_gate_not_met",
        }

    train_matrix, test_matrix, transforms = prepare_design(train_events, test_events, features)
    beta = fit_ridge_logistic(train_matrix, np.asarray(train_labels, dtype=float), l2=RIDGE_L2)
    probabilities = sigmoid(test_matrix @ beta)
    base_rate = float(statistics.fmean(test_labels)) if test_labels else 0.0
    baseline_brier = float(statistics.fmean((label - base_rate) ** 2 for label in test_labels)) if test_labels else 0.0
    auc = rank_auc(test_labels, [float(value) for value in probabilities])
    order = sorted(range(len(test_events)), key=lambda index: float(probabilities[index]), reverse=True)
    selected_count = max(1, int(math.ceil(len(test_events) * TOP_RETENTION_PCT / 100.0)))
    selected_indices = set(order[:selected_count])
    selected_events = [event for index, event in enumerate(test_events) if index in selected_indices]
    all_metrics = economic_metrics(test_events, threshold_r)
    selected_metrics = economic_metrics(selected_events, threshold_r)
    target_lift = (
        float(selected_metrics["target_rate_pct"] / all_metrics["target_rate_pct"])
        if float(all_metrics["target_rate_pct"]) > 0
        else None
    )
    tp2r_lift = (
        float(selected_metrics["tp2r_rate_pct"] / all_metrics["tp2r_rate_pct"])
        if float(all_metrics["tp2r_rate_pct"]) > 0
        else None
    )
    brier = brier_score(test_labels, probabilities)
    skill = float(1.0 - brier / baseline_brier) if baseline_brier > 0 else None
    diagnostic_pass = bool(
        auc is not None
        and auc >= 0.55
        and skill is not None
        and skill > 0.0
        and target_lift is not None
        and target_lift >= 1.10
        and float(selected_metrics["avg_net_R"]) > float(all_metrics["avg_net_R"])
    )
    return {
        "side": side,
        "train_window": train_window,
        "test_window": test_window,
        "target_R": threshold_r,
        "features": list(features),
        "evaluable": True,
        "readiness": readiness,
        "ridge_l2": RIDGE_L2,
        "coefficients": {
            "intercept": float(beta[0]),
            **{feature: float(beta[index + 1]) for index, feature in enumerate(features)},
        },
        "transforms": transforms,
        "predictive": {
            "auc": auc,
            "brier": brier,
            "baseline_brier": baseline_brier,
            "brier_skill": skill,
            "log_loss": log_loss(test_labels, probabilities),
            "calibration_bins": calibration_bins(test_labels, probabilities),
        },
        "economics": {
            "all": all_metrics,
            "top_half": selected_metrics,
            "retention_pct": float(len(selected_events) / len(test_events) * 100.0) if test_events else 0.0,
            "target_lift": target_lift,
            "tp2r_lift": tp2r_lift,
        },
        "diagnostic_pass": diagnostic_pass,
        "promotion_allowed": False,
    }


def transition_scope(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    thresholds = (0.5, 1.0, 1.5, 2.0)
    counts = {str(threshold): sum(target_value(event, threshold) for event in events) for threshold in thresholds}

    def conditional(numerator: float, denominator: float) -> Optional[float]:
        return float(numerator / denominator) if denominator > 0 else None

    reached_1r = [event for event in events if target_value(event, 1.0)]
    reached_15r = [event for event in events if target_value(event, 1.5)]
    reached_2r = [event for event in events if target_value(event, 2.0)]
    one_r_nonpositive = [event for event in reached_1r if float(event.get("net_R_0.15", 0.0)) <= 0.0]
    one_r_timeout_nonpositive = [event for event in one_r_nonpositive if str(event.get("label")) == "TIMEOUT"]
    fast_1r = [event for event in reached_1r if int(event.get("minutes_to_mfe", 999999)) <= 60]
    fast_1r_nonpositive = [event for event in fast_1r if float(event.get("net_R_0.15", 0.0)) <= 0.0]
    return {
        "events": len(events),
        "threshold_counts": counts,
        "conditional_probability": {
            "p_1.0_given_0.5": conditional(counts["1.0"], counts["0.5"]),
            "p_1.5_given_1.0": conditional(counts["1.5"], counts["1.0"]),
            "p_2.0_given_1.5": conditional(counts["2.0"], counts["1.5"]),
            "p_2.0_given_1.0": conditional(counts["2.0"], counts["1.0"]),
        },
        "giveback": {
            "reached_1R": len(reached_1r),
            "finished_nonpositive_after_1R": len(one_r_nonpositive),
            "finished_nonpositive_after_1R_pct": conditional(len(one_r_nonpositive) * 100.0, len(reached_1r)),
            "timeout_nonpositive_after_1R": len(one_r_timeout_nonpositive),
            "fast_1R_within_60m": len(fast_1r),
            "fast_1R_then_nonpositive": len(fast_1r_nonpositive),
            "fast_1R_then_nonpositive_pct": conditional(len(fast_1r_nonpositive) * 100.0, len(fast_1r)),
            "mean_net_R_after_1R": float(statistics.fmean(float(event.get("net_R_0.15", 0.0)) for event in reached_1r)) if reached_1r else None,
            "mean_net_R_after_1.5R": float(statistics.fmean(float(event.get("net_R_0.15", 0.0)) for event in reached_15r)) if reached_15r else None,
            "mean_net_R_after_2R": float(statistics.fmean(float(event.get("net_R_0.15", 0.0)) for event in reached_2r)) if reached_2r else None,
        },
        "economics": economic_metrics(events, PILOT_TARGET_R),
    }


def transition_report(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    scopes: Dict[str, List[Dict[str, Any]]] = {"all": list(events)}
    for window in WINDOWS:
        scopes[f"window:{window}"] = [event for event in events if str(event.get("window")) == window]
    for side in SIDES:
        scopes[f"side:{side}"] = [event for event in events if str(event.get("side")) == side]
    for window in WINDOWS:
        for side in SIDES:
            scopes[f"window_side:{window}|{side}"] = [
                event for event in events
                if str(event.get("window")) == window and str(event.get("side")) == side
            ]
    month_scopes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        stamp = int(event.get("signal_ts", 0))
        month = pd.to_datetime(stamp, unit="ms", utc=True).strftime("%Y-%m")
        month_scopes[month].append(event)
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_TRANSITION_GIVEBACK",
        "scopes": {scope: transition_scope(rows) for scope, rows in scopes.items()},
        "month_blocks": {
            month: transition_scope(rows)
            for month, rows in sorted(month_scopes.items())
        },
        "rule": "MFE transition and post-entry giveback are diagnostic. Post-entry variables cannot become entry features.",
    }


def bocpd_cross_check(
    events: Sequence[Dict[str, Any]], bocpd: Dict[str, Any], transition: Dict[str, Any]
) -> Dict[str, Any]:
    top = bocpd.get("top_change_points", [])
    if not isinstance(top, list):
        top = []
    contexts: List[Dict[str, Any]] = []
    for row in top[:15]:
        if not isinstance(row, dict):
            continue
        stamp = int(row.get("signal_ts", 0))
        contexts.append(
            {
                "event_id": row.get("event_id"),
                "signal_utc": row.get("signal_utc"),
                "month": pd.to_datetime(stamp, unit="ms", utc=True).strftime("%Y-%m"),
                "window": row.get("window"),
                "side": row.get("side"),
                "symbol": row.get("symbol"),
                "cp_probability": row.get("cp_probability"),
            }
        )
    month_rows = transition.get("month_blocks", {})
    worst_months = sorted(
        (
            {
                "month": month,
                "avg_net_R": float(report.get("economics", {}).get("avg_net_R", 0.0)),
                "p_1.5_given_1.0": report.get("conditional_probability", {}).get("p_1.5_given_1.0"),
                "p_2.0_given_1.5": report.get("conditional_probability", {}).get("p_2.0_given_1.5"),
            }
            for month, report in month_rows.items()
        ),
        key=lambda row: float(row["avg_net_R"]),
    )
    cp_months = Counter(str(row["month"]) for row in contexts)
    return {
        "top_change_contexts": contexts,
        "change_point_month_frequency": dict(sorted(cp_months.items())),
        "worst_months": worst_months[:3],
        "top_cp_overlaps_worst_month": any(
            row["month"] in {month["month"] for month in worst_months[:3]}
            for row in contexts
        ),
        "second_window_boundary": bocpd.get("second_window_boundary"),
        "observer_only": True,
    }


def build_feature_screen(
    events: Sequence[Dict[str, Any]], attribution: Dict[str, Any]
) -> Dict[str, Any]:
    screen_15 = {
        scope: screen_features(
            events,
            attribution,
            threshold_r=SCREEN_TARGET_R,
            side=None if scope == "all" else scope,
        )
        for scope in ("all", "long", "short")
    }
    pilot_10 = {
        side: screen_features(
            events,
            attribution,
            threshold_r=PILOT_TARGET_R,
            side=side,
        )
        for side in SIDES
    }
    selected = {
        side: select_nonredundant_features(
            pilot_10[side],
            [event for event in events if str(event.get("side")) == side],
        )
        for side in SIDES
    }
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_MFE_STABLE_FEATURE_SCREEN",
        "screen_target_R": SCREEN_TARGET_R,
        "pilot_target_R": PILOT_TARGET_R,
        "screen_1.5R": screen_15,
        "pilot_screen_1.0R": pilot_10,
        "selected_pilot_features": selected,
        "rules": {
            "feature_cap_per_side": MAX_FEATURES_PER_SIDE,
            "correlation_cap": CORRELATION_CAP,
            "minimum_class_per_window": 5,
            "minimum_coverage_pct": 80.0,
            "minimum_oriented_strength": 0.10,
            "post_entry_features_forbidden": True,
        },
    }


def build_pilots(
    events: Sequence[Dict[str, Any]], feature_screen: Dict[str, Any]
) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for side in SIDES:
        features = feature_screen["selected_pilot_features"][side]["selected"]
        primary = transport_fit(
            events,
            side=side,
            features=features,
            threshold_r=PILOT_TARGET_R,
            train_window=WINDOWS[0],
            test_window=WINDOWS[1],
        )
        reverse = transport_fit(
            events,
            side=side,
            features=features,
            threshold_r=PILOT_TARGET_R,
            train_window=WINDOWS[1],
            test_window=WINDOWS[0],
        )
        sensitivity = transport_fit(
            events,
            side=side,
            features=features,
            threshold_r=SENSITIVITY_TARGET_R,
            train_window=WINDOWS[0],
            test_window=WINDOWS[1],
        )
        stable_transport = bool(
            primary.get("diagnostic_pass")
            and reverse.get("evaluable")
            and safe_float(reverse.get("predictive", {}).get("auc")) is not None
            and float(reverse["predictive"]["auc"]) >= 0.50
        )
        results[side] = {
            "features": features,
            "primary_prior_to_second": primary,
            "reverse_second_to_prior_diagnostic_only": reverse,
            "sensitivity_0.5R_primary": sensitivity,
            "stable_transport": stable_transport,
            "promotion_allowed": False,
        }
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_SIDE_PILOT",
        "target_R": PILOT_TARGET_R,
        "model": "fixed_ridge_logistic",
        "ridge_l2": RIDGE_L2,
        "primary_transport": f"{WINDOWS[0]}_to_{WINDOWS[1]}",
        "results": results,
        "promotion_allowed": False,
    }


def build_decision(
    feature_screen: Dict[str, Any],
    pilots: Dict[str, Any],
    transition: Dict[str, Any],
    bocpd_check: Dict[str, Any],
    diagnostic_decision: Dict[str, Any],
) -> Dict[str, Any]:
    stable_15 = {
        scope: [row for row in feature_screen["screen_1.5R"][scope] if row.get("stable_candidate")]
        for scope in ("all", "long", "short")
    }
    stable_sides = [
        side for side in SIDES
        if bool(pilots["results"][side].get("stable_transport"))
    ]
    all_transition = transition["scopes"]["all"]
    p_15_to_2 = all_transition["conditional_probability"]["p_2.0_given_1.5"]
    giveback_pct = all_transition["giveback"]["finished_nonpositive_after_1R_pct"]
    next_modules: List[str] = []
    if stable_sides:
        next_modules.append("PRE_REGISTER_SCORE_OBSERVER_AND_EXIT_POLICY_DIAGNOSTIC")
    else:
        next_modules.append("SAFE_HISTORY_EXPANSION_BEFORE_MODEL_ESCALATION")
    if giveback_pct is not None and float(giveback_pct) >= 25.0:
        next_modules.append("CONDITIONAL_PROFIT_REALIZATION_POLICY_ON_1R_REACHED_EVENTS")
    if p_15_to_2 is not None and float(p_15_to_2) < 0.50:
        next_modules.append("CONTINUATION_FAILURE_ANALYSIS_1.5R_TO_2R")
    next_modules.append("BOCPD_MONTH_BLOCK_OBSERVER_VALIDATION")
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_PILOT_DECISION",
        "verdict": (
            "STABLE_SIDE_PILOT_FOUND_OBSERVER_ONLY"
            if stable_sides
            else "NO_STABLE_SIDE_PILOT_SAFE_HISTORY_REQUIRED"
        ),
        "stable_1.5R_feature_count": {scope: len(rows) for scope, rows in stable_15.items()},
        "stable_transport_sides": stable_sides,
        "p_2R_given_1.5R": p_15_to_2,
        "giveback_after_1R_pct": giveback_pct,
        "bocpd_worst_month_overlap": bocpd_check.get("top_cp_overlaps_worst_month"),
        "prior_diagnostic_contract": {
            "preferred_intermediate_label": diagnostic_decision.get("preferred_intermediate_label"),
            "side_separated_pilot_labels": diagnostic_decision.get("side_separated_pilot_labels"),
        },
        "next_modules": next_modules,
        "hard_rules": {
            "model_or_strategy_promotion_now": False,
            "final_holdout_access": False,
            "synthetic_oversampling": False,
            "feature_or_threshold_search_after_test": False,
            "production_strategy_modified": False,
        },
    }


def write_html(
    feature_screen: Dict[str, Any],
    pilots: Dict[str, Any],
    transition: Dict[str, Any],
    decision: Dict[str, Any],
) -> None:
    feature_rows: List[str] = []
    for scope in ("all", "long", "short"):
        for row in feature_screen["screen_1.5R"][scope][:8]:
            feature_rows.append(
                "<tr>"
                f"<td>{html.escape(scope)}</td>"
                f"<td>{html.escape(str(row['feature']))}</td>"
                f"<td>{row['minimum_oriented_strength']:.3f}</td>"
                f"<td>{row['drift_score']:.3f}</td>"
                f"<td>{row['stable_score']:.3f}</td>"
                f"<td>{row['stable_candidate']}</td>"
                "</tr>"
            )
    pilot_rows: List[str] = []
    for side in SIDES:
        report = pilots["results"][side]["primary_prior_to_second"]
        predictive = report.get("predictive", {})
        economics = report.get("economics", {})
        pilot_rows.append(
            "<tr>"
            f"<td>{html.escape(side)}</td>"
            f"<td>{html.escape(', '.join(pilots['results'][side]['features']))}</td>"
            f"<td>{report.get('evaluable')}</td>"
            f"<td>{predictive.get('auc')}</td>"
            f"<td>{predictive.get('brier_skill')}</td>"
            f"<td>{economics.get('target_lift')}</td>"
            f"<td>{economics.get('top_half', {}).get('avg_net_R')}</td>"
            f"<td>{report.get('diagnostic_pass')}</td>"
            "</tr>"
        )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke v3 MFE pilot transition</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%;margin-bottom:30px}td,th{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Raschke v3 stable MFE feature screen and transport pilot</h1>",
            "<h2>1.5R cross-window feature screen</h2><table><thead><tr><th>Scope</th><th>Feature</th><th>Min strength</th><th>Drift</th><th>Stable score</th><th>Candidate</th></tr></thead><tbody>",
            "".join(feature_rows),
            "</tbody></table><h2>1.0R side pilots</h2><table><thead><tr><th>Side</th><th>Features</th><th>Evaluable</th><th>AUC</th><th>Brier skill</th><th>Target lift</th><th>Top-half avg R</th><th>Pass</th></tr></thead><tbody>",
            "".join(pilot_rows),
            "</tbody></table><h2>Decision</h2><pre>",
            html.escape(json.dumps(decision, ensure_ascii=False, indent=2)),
            "</pre><h2>Transition and giveback</h2><pre>",
            html.escape(json.dumps(transition, ensure_ascii=False, indent=2)),
            "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    ledger = load_json(LEDGER_SOURCE)
    attribution = load_json(ATTRIBUTION_SOURCE)
    load_json(MFE_DIAGNOSTIC_SOURCE)
    bocpd = load_json(BOCPD_SOURCE)
    diagnostic_decision = load_json(DIAGNOSTIC_DECISION_SOURCE)
    events = ledger.get("events", [])
    if not isinstance(events, list) or not events:
        raise RuntimeError("EVENT_LEDGER_EMPTY")
    events = [event for event in events if isinstance(event, dict)]

    feature_screen = build_feature_screen(events, attribution)
    pilots = build_pilots(events, feature_screen)
    transition = transition_report(events)
    bocpd_check = bocpd_cross_check(events, bocpd, transition)
    transition["bocpd_cross_check"] = bocpd_check
    decision = build_decision(
        feature_screen,
        pilots,
        transition,
        bocpd_check,
        diagnostic_decision,
    )
    trial = {
        "status": "PASS_Q4R3_RASCHKE_V3_TRIAL_REGISTRATION",
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "trial_id": "raschke_v3_mfe1r_side_ridge_transport_v1",
        "screen_target_R": SCREEN_TARGET_R,
        "pilot_target_R": PILOT_TARGET_R,
        "sensitivity_target_R": SENSITIVITY_TARGET_R,
        "final_business_target_R": FINAL_TARGET_R,
        "feature_cap_per_side": MAX_FEATURES_PER_SIDE,
        "correlation_cap": CORRELATION_CAP,
        "ridge_l2": RIDGE_L2,
        "retention_pct": TOP_RETENTION_PCT,
        "primary_train_window": WINDOWS[0],
        "primary_test_window": WINDOWS[1],
        "metrics": ["AUC", "Brier skill", "log loss", "target lift", "net R", "PF", "2R conversion"],
        "promotion_allowed": False,
        "research_contract": RESEARCH_CONTRACT,
    }

    feature_screen["authority"] = {
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "paper_request_written": False,
        "live_execution_allowed": False,
        "production_strategy_modified": False,
    }
    pilots["authority"] = dict(feature_screen["authority"])
    transition["authority"] = dict(feature_screen["authority"])
    decision["authority"] = dict(feature_screen["authority"])
    trial["authority"] = dict(feature_screen["authority"])

    atomic_json(SCREEN_OUT, feature_screen)
    atomic_json(PILOT_OUT, pilots)
    atomic_json(TRANSITION_OUT, transition)
    atomic_json(DECISION_OUT, decision)
    atomic_json(TRIAL_OUT, trial)
    write_html(feature_screen, pilots, transition, decision)
    print(json.dumps({
        "decision": decision,
        "selected_features": feature_screen["selected_pilot_features"],
        "pilot_summary": {
            side: {
                "features": pilots["results"][side]["features"],
                "primary": pilots["results"][side]["primary_prior_to_second"],
                "stable_transport": pilots["results"][side]["stable_transport"],
            }
            for side in SIDES
        },
        "all_transition": transition["scopes"]["all"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
