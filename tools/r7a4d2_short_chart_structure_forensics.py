#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXPECTED_CANDIDATE_COUNT = 28
EXPECTED_BUCKET_COUNTS = {
    "baseline_trend_down": 12,
    "scalp_snap_trend_up": 12,
    "vol_spike_fade_shock_recovery": 4,
}
FEATURE_NAMES = [
    "ret_5_pct",
    "ret_15_pct",
    "ret_30_pct",
    "ret_60_pct",
    "slope_10_pct_per_bar",
    "slope_30_pct_per_bar",
    "efficiency_20",
    "efficiency_60",
    "rsi_14",
    "atr_14_pct",
    "atr_expansion_ratio",
    "ema20_gap_pct",
    "ema20_vs_ema50_pct",
    "range_position_20",
    "distance_prev_high20_pct",
    "distance_prev_low20_pct",
    "volume_z20",
    "body_to_range",
    "upper_wick_share",
    "lower_wick_share",
]
FORWARD_FORBIDDEN_TOKENS = ("pnl", "mfe", "mae", "exit", "future", "outcome", "profit", "loss")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def round_finite(value: Any, digits: int = 10) -> float:
    return round(finite(value), digits)


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if math.isfinite(denominator) and abs(denominator) > 1e-12 else default


def pct_change_last(values: pd.Series, bars: int) -> float:
    if len(values) <= bars:
        return 0.0
    first = finite(values.iloc[-1 - bars])
    last = finite(values.iloc[-1])
    return safe_div(last - first, first) * 100.0


def log_slope_pct_per_bar(values: pd.Series, bars: int) -> float:
    if len(values) < bars:
        return 0.0
    sample = np.asarray(values.iloc[-bars:], dtype=float)
    if np.any(sample <= 0) or not np.isfinite(sample).all():
        return 0.0
    x = np.arange(bars, dtype=float)
    slope = float(np.polyfit(x, np.log(sample), 1)[0])
    return (math.exp(slope) - 1.0) * 100.0


def efficiency_ratio(values: pd.Series, bars: int) -> float:
    if len(values) <= bars:
        return 0.0
    sample = np.asarray(values.iloc[-1 - bars:], dtype=float)
    path = float(np.abs(np.diff(sample)).sum())
    return safe_div(abs(float(sample[-1] - sample[0])), path)


def rsi(values: pd.Series, period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    delta = values.diff().iloc[-period:]
    gains = float(delta.clip(lower=0).mean())
    losses = float((-delta.clip(upper=0)).mean())
    if losses <= 1e-12:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def chart_features(sample: pd.DataFrame, bar_index: int) -> dict[str, float]:
    if bar_index < 100 or bar_index >= len(sample):
        raise ValueError(f"CHART_FEATURE_BAR_INDEX_INVALID:{bar_index}:{len(sample)}")
    history = sample.iloc[: bar_index + 1].copy().reset_index(drop=True)
    required = ["open", "high", "low", "close", "volume"]
    if any(column not in history.columns for column in required):
        raise ValueError("CHART_FEATURE_COLUMNS_MISSING")
    for column in required:
        history[column] = pd.to_numeric(history[column], errors="coerce")
    if history[required].tail(100).isna().any().any():
        raise ValueError("CHART_FEATURE_NON_NUMERIC_TAIL")

    close = history["close"].astype(float)
    high = history["high"].astype(float)
    low = history["low"].astype(float)
    open_ = history["open"].astype(float)
    volume = history["volume"].astype(float)
    last_close = max(finite(close.iloc[-1]), 1e-12)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    tr = true_range(history)
    atr14 = float(tr.iloc[-14:].mean())
    atr50 = float(tr.iloc[-50:].mean())
    rolling_high = float(high.iloc[-21:-1].max())
    rolling_low = float(low.iloc[-21:-1].min())
    range_low = float(low.iloc[-20:].min())
    range_high = float(high.iloc[-20:].max())
    range_span = range_high - range_low
    volume_window = volume.iloc[-20:]
    volume_std = float(volume_window.std(ddof=0))
    bar_range = max(float(high.iloc[-1] - low.iloc[-1]), 1e-12)
    body = float(close.iloc[-1] - open_.iloc[-1])
    upper_wick = float(high.iloc[-1] - max(open_.iloc[-1], close.iloc[-1]))
    lower_wick = float(min(open_.iloc[-1], close.iloc[-1]) - low.iloc[-1])

    features = {
        "ret_5_pct": pct_change_last(close, 5),
        "ret_15_pct": pct_change_last(close, 15),
        "ret_30_pct": pct_change_last(close, 30),
        "ret_60_pct": pct_change_last(close, 60),
        "slope_10_pct_per_bar": log_slope_pct_per_bar(close, 10),
        "slope_30_pct_per_bar": log_slope_pct_per_bar(close, 30),
        "efficiency_20": efficiency_ratio(close, 20),
        "efficiency_60": efficiency_ratio(close, 60),
        "rsi_14": rsi(close, 14),
        "atr_14_pct": safe_div(atr14, last_close) * 100.0,
        "atr_expansion_ratio": safe_div(atr14, atr50, 1.0),
        "ema20_gap_pct": safe_div(last_close - float(ema20.iloc[-1]), float(ema20.iloc[-1])) * 100.0,
        "ema20_vs_ema50_pct": safe_div(float(ema20.iloc[-1] - ema50.iloc[-1]), float(ema50.iloc[-1])) * 100.0,
        "range_position_20": safe_div(last_close - range_low, range_span, 0.5),
        "distance_prev_high20_pct": safe_div(last_close - rolling_high, rolling_high) * 100.0,
        "distance_prev_low20_pct": safe_div(last_close - rolling_low, rolling_low) * 100.0,
        "volume_z20": safe_div(float(volume.iloc[-1] - volume_window.mean()), volume_std),
        "body_to_range": safe_div(body, bar_range),
        "upper_wick_share": safe_div(upper_wick, bar_range),
        "lower_wick_share": safe_div(lower_wick, bar_range),
    }
    rounded = {name: round_finite(features[name]) for name in FEATURE_NAMES}
    if any(not math.isfinite(value) for value in rounded.values()):
        raise ValueError("CHART_FEATURE_NON_FINITE")
    return rounded


def source_symbol(candidate: dict[str, Any], sample: pd.DataFrame) -> str:
    if "symbol" in sample.columns:
        values = [str(value) for value in sample["symbol"].dropna().tail(1).tolist() if str(value)]
        if values:
            return values[0].upper()
    match = re.search(r"(?:^|_)([A-Z0-9]+USDT)(?:_|\.)", Path(str(candidate.get("source_path") or "")).name.upper())
    return match.group(1) if match else "UNKNOWN"


def positive_pf(value: Any, threshold: float = 1.25) -> bool:
    return value == "Infinity" or (isinstance(value, (int, float)) and finite(value) > threshold)


def candidate_outcome(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    status = result.get("status_histogram") if isinstance(result.get("status_histogram"), dict) else {}
    cost_axis = result.get("cost_profile_net_pct") if isinstance(result.get("cost_profile_net_pct"), dict) else {}
    perturb_axis = result.get("perturbation_net_pct") if isinstance(result.get("perturbation_net_pct"), dict) else {}
    closed = int(result.get("closed_trade_cell_count") or 0)
    reproduced = int(result.get("target_reproduction_count") or 0)
    invalid = int(status.get("INVALID_GEOMETRY") or 0)
    net_sum = finite(metrics.get("net_pnl_sum_pct"))
    expectancy = finite(metrics.get("expectancy_r"))
    worst_cost = min((finite(value) for value in cost_axis.values()), default=0.0)
    worst_perturbation = min((finite(value) for value in perturb_axis.values()), default=0.0)
    robust = (
        closed == 6
        and reproduced == 6
        and invalid == 0
        and net_sum > 0
        and expectancy > 0.15
        and positive_pf(metrics.get("profit_factor"), 1.25)
        and worst_cost > 0
        and worst_perturbation > 0
    )
    salvage = reproduced == 6 and net_sum > 0 and expectancy > 0
    return {
        "closed_trade_cell_count": closed,
        "target_reproduction_count": reproduced,
        "invalid_geometry_count": invalid,
        "net_pnl_sum_pct": round_finite(net_sum),
        "net_per_axis_cell_pct": round_finite(net_sum / 6.0),
        "expectancy_r": round_finite(expectancy),
        "profit_factor": metrics.get("profit_factor", 0.0),
        "win_rate_pct": round_finite(metrics.get("win_rate_pct")),
        "mean_mfe_pct": round_finite(metrics.get("mean_mfe_pct")),
        "mean_mae_pct": round_finite(metrics.get("mean_mae_pct")),
        "worst_cost_axis_net_pct": round_finite(worst_cost),
        "worst_perturbation_axis_net_pct": round_finite(worst_perturbation),
        "robust": robust,
        "salvage_positive": salvage,
        "negative": net_sum <= 0 or expectancy <= 0,
    }


def atlas_points(sample: pd.DataFrame, bar_index: int, before: int = 60, after: int = 20) -> list[dict[str, Any]]:
    start = max(0, bar_index - before)
    stop = min(len(sample), bar_index + after + 1)
    window = sample.iloc[start:stop].copy().reset_index(drop=False)
    entry_close = max(finite(sample.iloc[bar_index]["close"]), 1e-12)
    close_series = pd.to_numeric(sample["close"], errors="coerce").astype(float)
    ema20 = close_series.ewm(span=20, adjust=False).mean()
    ema50 = close_series.ewm(span=50, adjust=False).mean()
    pre_volume = pd.to_numeric(sample.iloc[max(0, bar_index - 20): bar_index + 1]["volume"], errors="coerce")
    volume_scale = max(finite(pre_volume.median(), 1.0), 1e-12)
    output: list[dict[str, Any]] = []
    for _, row in window.iterrows():
        original_index = int(row["index"])
        output.append({
            "offset": original_index - bar_index,
            "open_index": round_finite(finite(row["open"]) / entry_close * 100.0, 6),
            "high_index": round_finite(finite(row["high"]) / entry_close * 100.0, 6),
            "low_index": round_finite(finite(row["low"]) / entry_close * 100.0, 6),
            "close_index": round_finite(finite(row["close"]) / entry_close * 100.0, 6),
            "ema20_index": round_finite(finite(ema20.iloc[original_index]) / entry_close * 100.0, 6),
            "ema50_index": round_finite(finite(ema50.iloc[original_index]) / entry_close * 100.0, 6),
            "volume_relative": round_finite(finite(row["volume"]) / volume_scale, 6),
            "is_target_bar": original_index == bar_index,
        })
    return output


def condition_signature(condition: dict[str, Any]) -> tuple[str, str]:
    return str(condition["feature"]), str(condition["op"])


def rule_signature(rule: dict[str, Any] | None) -> str:
    if not rule:
        return "NONE"
    return "&".join(f"{feature}{op}" for feature, op in sorted(condition_signature(row) for row in rule["conditions"]))


def apply_condition(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    value = finite(row["features"].get(condition["feature"]))
    threshold = finite(condition["threshold"])
    return value >= threshold if condition["op"] == ">=" else value <= threshold


def apply_rule(row: dict[str, Any], rule: dict[str, Any]) -> bool:
    return all(apply_condition(row, condition) for condition in rule["conditions"])


def threshold_conditions(rows: list[dict[str, Any]], features: list[str]) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []
    for feature in features:
        values = sorted({finite(row["features"].get(feature)) for row in rows})
        if len(values) < 2:
            continue
        midpoints = [(left + right) / 2.0 for left, right in zip(values, values[1:]) if right > left]
        if len(midpoints) > 16:
            indices = np.linspace(0, len(midpoints) - 1, 16).round().astype(int)
            midpoints = [midpoints[index] for index in sorted(set(indices.tolist()))]
        for threshold in midpoints:
            conditions.append({"feature": feature, "op": ">=", "threshold": round_finite(threshold)})
            conditions.append({"feature": feature, "op": "<=", "threshold": round_finite(threshold)})
    return conditions


def evaluate_rule(
    rows: list[dict[str, Any]],
    rule: dict[str, Any],
    min_support: int,
    min_sources: int,
) -> dict[str, Any] | None:
    selected = [row for row in rows if apply_rule(row, rule)]
    if len(selected) < min_support:
        return None
    sources = sorted({str(row["source_path"]) for row in selected})
    if len(sources) < min_sources:
        return None
    robust_total = sum(1 for row in rows if bool(row["outcome"]["robust"]))
    robust_selected = sum(1 for row in selected if bool(row["outcome"]["robust"]))
    negative_selected = sum(1 for row in selected if bool(row["outcome"]["negative"]))
    net_sum = sum(finite(row["outcome"]["net_per_axis_cell_pct"]) for row in selected)
    expectancy = statistics.fmean(finite(row["outcome"]["expectancy_r"]) for row in selected)
    source_net: dict[str, float] = defaultdict(float)
    for row in selected:
        source_net[str(row["source_path"])] += finite(row["outcome"]["net_per_axis_cell_pct"])
    precision = robust_selected / len(selected)
    recall = robust_selected / robust_total if robust_total else 0.0
    worst_source_net = min(source_net.values()) if source_net else 0.0
    score = (
        precision * 5.0
        + recall * 2.0
        + max(min(net_sum, 2.0), -2.0) * 0.5
        + max(min(expectancy, 3.0), -3.0) * 0.15
        - negative_selected * 0.7
        - (len(rule["conditions"]) - 1) * 0.35
    )
    return {
        "selected_count": len(selected),
        "selected_candidate_ids": [str(row["candidate_id"]) for row in selected],
        "unique_source_count": len(sources),
        "robust_selected_count": robust_selected,
        "negative_selected_count": negative_selected,
        "robust_precision": round_finite(precision),
        "robust_recall": round_finite(recall),
        "net_per_axis_cell_sum_pct": round_finite(net_sum),
        "mean_expectancy_r": round_finite(expectancy),
        "worst_source_net_per_axis_cell_pct": round_finite(worst_source_net),
        "source_net_per_axis_cell_pct": {key: round_finite(value) for key, value in sorted(source_net.items())},
        "score": round_finite(score),
    }


def search_best_rule(
    rows: list[dict[str, Any]],
    features: list[str],
    min_support: int,
    min_sources: int,
) -> dict[str, Any] | None:
    conditions = threshold_conditions(rows, features)
    singles: list[dict[str, Any]] = []
    for condition in conditions:
        rule = {"conditions": [condition]}
        metrics = evaluate_rule(rows, rule, min_support, min_sources)
        if metrics is not None:
            singles.append({**rule, "metrics": metrics})
    singles.sort(key=lambda row: (-finite(row["metrics"]["score"]), rule_signature(row)))
    candidates = singles[:]
    top_conditions = [row["conditions"][0] for row in singles[:16]]
    for left_index, left in enumerate(top_conditions):
        for right in top_conditions[left_index + 1:]:
            if left["feature"] == right["feature"]:
                continue
            rule = {"conditions": [left, right]}
            metrics = evaluate_rule(rows, rule, min_support, min_sources)
            if metrics is not None:
                candidates.append({**rule, "metrics": metrics})
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            -finite(row["metrics"]["score"]),
            len(row["conditions"]),
            rule_signature(row),
        )
    )
    return candidates[0]


def leave_one_source_out(rows: list[dict[str, Any]], features: list[str]) -> dict[str, Any]:
    sources = sorted({str(row["source_path"]) for row in rows})
    fold_rows: list[dict[str, Any]] = []
    selected_oos: list[dict[str, Any]] = []
    signature_histogram: Counter[str] = Counter()
    for held_out in sources:
        train = [row for row in rows if str(row["source_path"]) != held_out]
        test = [row for row in rows if str(row["source_path"]) == held_out]
        min_support = max(2, min(5, math.ceil(len(train) * 0.4)))
        rule = search_best_rule(train, features, min_support=min_support, min_sources=min(2, len({row["source_path"] for row in train})))
        signature = rule_signature(rule)
        signature_histogram[signature] += 1
        selected = [row for row in test if rule is not None and apply_rule(row, rule)]
        selected_oos.extend(selected)
        fold_rows.append({
            "held_out_source": held_out,
            "train_count": len(train),
            "test_count": len(test),
            "rule_signature": signature,
            "rule": rule,
            "selected_test_count": len(selected),
            "selected_test_candidate_ids": [str(row["candidate_id"]) for row in selected],
            "selected_test_net_per_axis_cell_pct": round_finite(sum(finite(row["outcome"]["net_per_axis_cell_pct"]) for row in selected)),
            "selected_test_robust_count": sum(1 for row in selected if bool(row["outcome"]["robust"])),
        })
    selected_ids = {str(row["candidate_id"]) for row in selected_oos}
    selected_unique = [row for row in rows if str(row["candidate_id"]) in selected_ids]
    robust_count = sum(1 for row in selected_unique if bool(row["outcome"]["robust"]))
    net_sum = sum(finite(row["outcome"]["net_per_axis_cell_pct"]) for row in selected_unique)
    dominant_signature, dominant_count = signature_histogram.most_common(1)[0] if signature_histogram else ("NONE", 0)
    return {
        "source_fold_count": len(sources),
        "folds": fold_rows,
        "signature_histogram": dict(sorted(signature_histogram.items())),
        "dominant_rule_signature": dominant_signature,
        "dominant_signature_share": round_finite(dominant_count / len(sources) if sources else 0.0),
        "oos_selected_candidate_count": len(selected_unique),
        "oos_selected_candidate_ids": [str(row["candidate_id"]) for row in selected_unique],
        "oos_robust_count": robust_count,
        "oos_robust_precision": round_finite(robust_count / len(selected_unique) if selected_unique else 0.0),
        "oos_net_per_axis_cell_sum_pct": round_finite(net_sum),
    }


def feature_separation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    robust = [row for row in rows if bool(row["outcome"]["robust"])]
    failed = [row for row in rows if not bool(row["outcome"]["robust"])]
    output: list[dict[str, Any]] = []
    if not robust or not failed:
        return output
    for feature in FEATURE_NAMES:
        robust_values = [finite(row["features"][feature]) for row in robust]
        failed_values = [finite(row["features"][feature]) for row in failed]
        all_values = robust_values + failed_values
        scale = statistics.pstdev(all_values) if len(all_values) > 1 else 0.0
        delta = statistics.median(robust_values) - statistics.median(failed_values)
        output.append({
            "feature": feature,
            "robust_median": round_finite(statistics.median(robust_values)),
            "failed_median": round_finite(statistics.median(failed_values)),
            "median_delta": round_finite(delta),
            "standardized_median_delta": round_finite(safe_div(delta, scale)),
        })
    output.sort(key=lambda row: (-abs(finite(row["standardized_median_delta"])), row["feature"]))
    return output


def chart_gate_ready(rule: dict[str, Any] | None, loso: dict[str, Any]) -> bool:
    if rule is None:
        return False
    metrics = rule["metrics"]
    return (
        int(metrics["selected_count"]) >= 6
        and int(metrics["unique_source_count"]) >= 3
        and finite(metrics["robust_precision"]) >= 0.75
        and finite(metrics["robust_recall"]) >= 0.70
        and int(metrics["negative_selected_count"]) <= 1
        and finite(metrics["net_per_axis_cell_sum_pct"]) > 0
        and finite(metrics["worst_source_net_per_axis_cell_pct"]) > 0
        and int(loso["oos_selected_candidate_count"]) >= 3
        and finite(loso["oos_robust_precision"]) >= 0.66
        and finite(loso["oos_net_per_axis_cell_sum_pct"]) > 0
        and finite(loso["dominant_signature_share"]) >= 0.50
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_chart_forensics_runner")

    proof_path = root / "runtime/r7a4d2_short_expanded_candidate_stress_168/stress168_proof_v1.json"
    plan_path = root / "runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json"
    proof = load_json(proof_path)
    plan = load_json(plan_path)
    blockers: list[str] = []
    if proof.get("state") != "PASS_SHORT_EXPANDED_CANDIDATE_STRESS_168" or int(proof.get("blocker_count", -1)) != 0:
        blockers.append("STRESS168_PROOF_INVALID")
    if int(proof.get("completed_cell_count", -1)) != 168 or int(proof.get("failed_cell_count", -1)) != 0:
        blockers.append("STRESS168_CELL_PARITY_FAILED")
    if int(proof.get("baseline_target_parity_failure_count", -1)) != 0:
        blockers.append("STRESS168_TARGET_PARITY_FAILED")
    if proof.get("source_registry_parity") is not True or int(proof.get("mutation_path_count", -1)) != 0:
        blockers.append("STRESS168_INTEGRITY_FAILED")
    if plan.get("state") != "PASS_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN" or int(plan.get("blocker_count", -1)) != 0:
        blockers.append("EXPANDED_PLAN_INVALID")
    if any(any(token in feature.lower() for token in FORWARD_FORBIDDEN_TOKENS) for feature in FEATURE_NAMES):
        blockers.append("FORWARD_FEATURE_NAME_DETECTED")

    candidates = [row for row in plan.get("expanded_stress_candidates", []) if isinstance(row, dict)]
    results = [row for row in proof.get("candidate_results", []) if isinstance(row, dict)]
    result_by_id = {str(row.get("candidate_id") or ""): row for row in results}
    candidate_ids = [str(row.get("candidate_id") or "") for row in candidates]
    if len(candidates) != EXPECTED_CANDIDATE_COUNT or len(set(candidate_ids)) != EXPECTED_CANDIDATE_COUNT:
        blockers.append(f"CANDIDATE_SET_INVALID:{len(candidates)}:{len(set(candidate_ids))}")
    if len(results) != EXPECTED_CANDIDATE_COUNT or set(result_by_id) != set(candidate_ids):
        blockers.append(f"CANDIDATE_RESULT_PARITY_FAILED:{len(results)}:{len(result_by_id)}")
    if dict(Counter(str(row.get("bucket") or "") for row in candidates)) != EXPECTED_BUCKET_COUNTS:
        blockers.append("CANDIDATE_BUCKET_PARITY_FAILED")

    market_paths: list[Path] = []
    for candidate in candidates:
        try:
            market_paths.append(root / runner.safe_repo_path(str(candidate.get("source_path") or "")))
        except Exception as exc:
            blockers.append(f"CANDIDATE_SOURCE_PATH_INVALID:{type(exc).__name__}:{exc}")
    protected = [proof_path, plan_path] + market_paths
    before = runner.snapshot(protected)

    rows: list[dict[str, Any]] = []
    atlas: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    frame_cache: dict[str, pd.DataFrame] = {}
    if not blockers:
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            try:
                source_path = runner.safe_repo_path(str(candidate["source_path"]))
                market_path = root / source_path
                if runner.sha256_file(market_path) != str(candidate.get("source_sha256") or ""):
                    raise ValueError("CANDIDATE_SOURCE_SHA_MISMATCH")
                frame = frame_cache.get(source_path)
                if frame is None:
                    frame = runner.load_market_frame(market_path)
                    frame_cache[source_path] = frame
                start = int(candidate["start_row"])
                stop = int(candidate["end_row_exclusive"])
                sample_start = start - 320
                if sample_start < 0 or stop > len(frame):
                    raise ValueError(f"CANDIDATE_SAMPLE_BOUNDS_INVALID:{sample_start}:{stop}:{len(frame)}")
                sample = frame.iloc[sample_start:stop].copy().reset_index(drop=True)
                if len(sample) != 640:
                    raise ValueError(f"CANDIDATE_SAMPLE_LENGTH_INVALID:{len(sample)}")
                bar_index = int(candidate["bar_index"])
                features = chart_features(sample, bar_index)
                outcome = candidate_outcome(result_by_id[candidate_id])
                row = {
                    "candidate_id": candidate_id,
                    "bucket": str(candidate["bucket"]),
                    "strategy_id": str(candidate["strategy_id"]),
                    "regime": str(candidate["regime"]),
                    "segment_id": str(candidate["segment_id"]),
                    "source_path": source_path,
                    "symbol": source_symbol(candidate, sample),
                    "bar_index": bar_index,
                    "features": features,
                    "outcome": outcome,
                }
                rows.append(row)
                atlas.append({
                    "candidate_id": candidate_id,
                    "bucket": row["bucket"],
                    "strategy_id": row["strategy_id"],
                    "regime": row["regime"],
                    "symbol": row["symbol"],
                    "source_path": source_path,
                    "gate_feature_window": "bars_at_or_before_target_only",
                    "visual_context_future_bars": 20,
                    "future_bars_used_for_gate": False,
                    "outcome": outcome,
                    "points": atlas_points(sample, bar_index),
                })
            except Exception as exc:
                failures.append({"candidate_id": candidate_id, "error": f"{type(exc).__name__}:{exc}"})

    if len(rows) != EXPECTED_CANDIDATE_COUNT or failures:
        blockers.append(f"CHART_FORENSIC_EXTRACTION_FAILED:{len(rows)}:{len(failures)}")
    after = runner.snapshot(protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")

    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_bucket[str(row["bucket"])].append(row)

    bucket_forensics: list[dict[str, Any]] = []
    baseline_rule: dict[str, Any] | None = None
    baseline_loso: dict[str, Any] = {}
    baseline_ready = False
    for bucket in EXPECTED_BUCKET_COUNTS:
        bucket_rows = by_bucket.get(bucket, [])
        separation = feature_separation(bucket_rows)
        min_support = 6 if bucket != "vol_spike_fade_shock_recovery" else 2
        min_sources = 3 if bucket == "baseline_trend_down" else 2
        best_rule = search_best_rule(bucket_rows, FEATURE_NAMES, min_support=min_support, min_sources=min_sources) if bucket_rows else None
        loso = leave_one_source_out(bucket_rows, FEATURE_NAMES) if len({row["source_path"] for row in bucket_rows}) >= 2 else {}
        robust_ids = [row["candidate_id"] for row in bucket_rows if bool(row["outcome"]["robust"])]
        salvage_ids = [row["candidate_id"] for row in bucket_rows if bool(row["outcome"]["salvage_positive"])]
        negative_ids = [row["candidate_id"] for row in bucket_rows if bool(row["outcome"]["negative"])]
        if bucket == "baseline_trend_down":
            baseline_rule = best_rule
            baseline_loso = loso
            baseline_ready = chart_gate_ready(best_rule, loso)
        bucket_forensics.append({
            "bucket": bucket,
            "candidate_count": len(bucket_rows),
            "unique_source_count": len({row["source_path"] for row in bucket_rows}),
            "robust_candidate_count": len(robust_ids),
            "robust_candidate_ids": robust_ids,
            "salvage_positive_candidate_count": len(salvage_ids),
            "salvage_positive_candidate_ids": salvage_ids,
            "negative_candidate_count": len(negative_ids),
            "negative_candidate_ids": negative_ids,
            "top_feature_separation": separation[:8],
            "best_simple_chart_rule": best_rule,
            "leave_one_source_out": loso,
        })

    scalp_rows = by_bucket.get("scalp_snap_trend_up", [])
    vol_rows = by_bucket.get("vol_spike_fade_shock_recovery", [])
    scalp_salvage = [row["candidate_id"] for row in scalp_rows if bool(row["outcome"]["salvage_positive"])]
    scalp_geometry_failures = [row["candidate_id"] for row in scalp_rows if int(row["outcome"]["invalid_geometry_count"]) > 0]
    vol_all_negative = bool(vol_rows) and all(bool(row["outcome"]["negative"]) for row in vol_rows)

    repair_plan = [
        {
            "bucket": "baseline_trend_down",
            "action": "observer_chart_gate_counterfactual" if baseline_ready else "candidate_specific_chart_causal_cluster_diagnose",
            "chart_gate_ready": baseline_ready,
            "retain_grid_strategy_quarantine": True,
            "automatic_production_promotion_allowed": False,
        },
        {
            "bucket": "scalp_snap_trend_up",
            "action": "geometry_trace_then_chart_cluster_counterfactual",
            "salvage_watchlist_candidate_ids": scalp_salvage,
            "invalid_geometry_candidate_ids": scalp_geometry_failures,
            "block_all_other_candidates": True,
        },
        {
            "bucket": "vol_spike_fade_shock_recovery",
            "action": "permanent_strategy_regime_block_and_component_decomposition" if vol_all_negative else "retain_diagnostic_only",
            "all_observed_candidates_negative": vol_all_negative,
            "automatic_repair_or_promotion_allowed": False,
        },
    ]

    blockers = list(dict.fromkeys(blockers))
    state = "PASS_SHORT_CHART_STRUCTURE_FORENSICS" if not blockers else "HOLD_SHORT_CHART_STRUCTURE_FORENSICS_INPUT"
    if blockers:
        next_stage = "R7.A4D2_SHORT_CHART_STRUCTURE_FORENSICS"
    elif baseline_ready:
        next_stage = "R7.A4D2_SHORT_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN"
    else:
        next_stage = "R7.A4D2_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE"

    output_dir = root / "runtime/r7a4d2_short_chart_structure_forensics"
    evidence = {
        "schema": "r7a4d2_short_chart_structure_forensics_v1",
        "official_stage": "R7.A4D2_SHORT_CHART_STRUCTURE_FORENSICS",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "candidate_count": len(rows),
        "feature_count": len(FEATURE_NAMES),
        "feature_names": FEATURE_NAMES,
        "gate_uses_pre_entry_chart_only": True,
        "future_chart_context_used_for_gate": False,
        "axis_repeats_create_independent_samples": False,
        "baseline_chart_gate_ready": baseline_ready,
        "baseline_best_simple_chart_rule": baseline_rule,
        "baseline_leave_one_source_out": baseline_loso,
        "scalp_salvage_candidate_count": len(scalp_salvage),
        "scalp_salvage_candidate_ids": scalp_salvage,
        "scalp_invalid_geometry_candidate_count": len(scalp_geometry_failures),
        "vol_permanent_block_recommended": vol_all_negative,
        "bucket_forensics": bucket_forensics,
        "repair_plan": repair_plan,
        "candidate_feature_rows": rows,
        "failure_count": len(failures),
        "failures": failures,
        "protected_mutation_path_count": len(mutation_paths),
        "protected_mutation_paths": mutation_paths,
        "source_registry_parity": proof.get("source_registry_parity") is True,
        "next_stage": next_stage,
    }
    atlas_evidence = {
        "schema": "r7a4d2_short_candidate_chart_atlas_v1",
        "official_stage": "R7.A4D2_SHORT_CHART_STRUCTURE_FORENSICS",
        "candidate_count": len(atlas),
        "normalization": "target_bar_close_equals_100",
        "gate_feature_window": "target_bar_and_prior_only",
        "visual_context_future_bars": 20,
        "future_context_used_for_gate": False,
        "charts": atlas,
    }
    runner.atomic_json(output_dir / "chart_forensics_v1.json", evidence)
    runner.atomic_json(output_dir / "chart_atlas_v1.json", atlas_evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("CANDIDATE_COUNT=" + str(len(rows)))
    print("FEATURE_COUNT=" + str(len(FEATURE_NAMES)))
    print("GATE_USES_PRE_ENTRY_CHART_ONLY=true")
    print("FUTURE_CHART_CONTEXT_USED_FOR_GATE=false")
    print("BASELINE_CHART_GATE_READY=" + str(baseline_ready).lower())
    print("BASELINE_BEST_SIMPLE_CHART_RULE=" + json.dumps(baseline_rule, ensure_ascii=False, sort_keys=True))
    print("BASELINE_LEAVE_ONE_SOURCE_OUT=" + json.dumps(baseline_loso, ensure_ascii=False, sort_keys=True))
    print("SCALP_SALVAGE_CANDIDATE_COUNT=" + str(len(scalp_salvage)))
    print("SCALP_SALVAGE_CANDIDATE_IDS=" + json.dumps(scalp_salvage, ensure_ascii=False))
    print("SCALP_INVALID_GEOMETRY_CANDIDATE_COUNT=" + str(len(scalp_geometry_failures)))
    print("VOL_PERMANENT_BLOCK_RECOMMENDED=" + str(vol_all_negative).lower())
    print("BUCKET_FORENSICS=" + json.dumps(bucket_forensics, ensure_ascii=False, sort_keys=True))
    print("REPAIR_PLAN=" + json.dumps(repair_plan, ensure_ascii=False, sort_keys=True))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("FAILURE_COUNT=" + str(len(failures)))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("FORENSICS_JSON=" + str(output_dir / "chart_forensics_v1.json"))
    print("CHART_ATLAS_JSON=" + str(output_dir / "chart_atlas_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
