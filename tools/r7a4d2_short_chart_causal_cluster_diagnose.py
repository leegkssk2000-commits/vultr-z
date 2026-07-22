#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
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
BASELINE_CLUSTER_FEATURES = [
    "ema20_gap_pct",
    "ret_60_pct",
    "body_to_range",
    "atr_14_pct",
    "efficiency_20",
    "distance_prev_high20_pct",
]


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


def rounded(value: Any, digits: int = 10) -> float:
    return round(finite(value), digits)


def robust_scale(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    median = np.median(matrix, axis=0)
    q25 = np.percentile(matrix, 25, axis=0)
    q75 = np.percentile(matrix, 75, axis=0)
    scale = q75 - q25
    std = np.std(matrix, axis=0)
    scale = np.where(scale > 1e-12, scale, np.where(std > 1e-12, std, 1.0))
    return (matrix - median) / scale, median, scale


def assign_clusters(matrix: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    distances = np.sum((matrix[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
    return np.argmin(distances, axis=1)


def fit_kmeans(matrix: np.ndarray, candidate_ids: list[str], k: int) -> dict[str, Any]:
    if len(matrix) < k or k < 2:
        raise ValueError("KMEANS_SHAPE_INVALID")
    best: dict[str, Any] | None = None
    ordered_starts = sorted(range(len(candidate_ids)), key=lambda index: candidate_ids[index])
    for first_index in ordered_starts:
        chosen = [first_index]
        while len(chosen) < k:
            distances = []
            for index in range(len(matrix)):
                nearest = min(float(np.sum((matrix[index] - matrix[chosen_index]) ** 2)) for chosen_index in chosen)
                distances.append((nearest, candidate_ids[index], index))
            _, _, next_index = max(distances, key=lambda row: (row[0], row[1]))
            if next_index in chosen:
                break
            chosen.append(next_index)
        if len(chosen) != k:
            continue
        centroids = matrix[chosen].copy()
        labels = np.zeros(len(matrix), dtype=int)
        for _ in range(100):
            next_labels = assign_clusters(matrix, centroids)
            if any(int(np.sum(next_labels == cluster)) == 0 for cluster in range(k)):
                break
            next_centroids = np.vstack([matrix[next_labels == cluster].mean(axis=0) for cluster in range(k)])
            converged = np.array_equal(labels, next_labels) and np.allclose(centroids, next_centroids, atol=1e-12)
            labels = next_labels
            centroids = next_centroids
            if converged:
                break
        if any(int(np.sum(labels == cluster)) == 0 for cluster in range(k)):
            continue
        inertia = float(sum(np.sum((matrix[index] - centroids[int(labels[index])]) ** 2) for index in range(len(matrix))))
        signature = tuple(int(value) for value in labels.tolist())
        candidate = {"labels": labels, "centroids": centroids, "inertia": inertia, "signature": signature}
        if best is None or (inertia, signature) < (float(best["inertia"]), tuple(best["signature"])):
            best = candidate
    if best is None:
        raise RuntimeError("KMEANS_FIT_FAILED")
    return best


def silhouette_score(matrix: np.ndarray, labels: np.ndarray) -> float:
    values: list[float] = []
    unique = sorted(set(int(value) for value in labels.tolist()))
    for index in range(len(matrix)):
        own = int(labels[index])
        same = [other for other in range(len(matrix)) if other != index and int(labels[other]) == own]
        a = statistics.fmean(float(np.linalg.norm(matrix[index] - matrix[other])) for other in same) if same else 0.0
        other_means: list[float] = []
        for cluster in unique:
            if cluster == own:
                continue
            members = [other for other in range(len(matrix)) if int(labels[other]) == cluster]
            if members:
                other_means.append(statistics.fmean(float(np.linalg.norm(matrix[index] - matrix[other])) for other in members))
        b = min(other_means) if other_means else 0.0
        denominator = max(a, b)
        values.append((b - a) / denominator if denominator > 1e-12 else 0.0)
    return statistics.fmean(values) if values else 0.0


def source_net(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        totals[str(row.get("source_path") or "")] += finite(row.get("outcome", {}).get("net_per_axis_cell_pct"))
    return {key: rounded(value) for key, value in sorted(totals.items())}


def evaluate_cluster(rows: list[dict[str, Any]], cluster_id: int) -> dict[str, Any]:
    robust_count = sum(1 for row in rows if bool(row.get("outcome", {}).get("robust")))
    salvage_count = sum(1 for row in rows if bool(row.get("outcome", {}).get("salvage_positive")))
    negative_count = sum(1 for row in rows if bool(row.get("outcome", {}).get("negative")))
    net = sum(finite(row.get("outcome", {}).get("net_per_axis_cell_pct")) for row in rows)
    expectancy = statistics.fmean(finite(row.get("outcome", {}).get("expectancy_r")) for row in rows) if rows else 0.0
    by_source = source_net(rows)
    precision = robust_count / len(rows) if rows else 0.0
    if (
        len(rows) >= 3
        and len(by_source) >= 2
        and precision >= 0.75
        and negative_count == 0
        and net > 0
        and min(by_source.values(), default=0.0) > 0
    ):
        classification = "S_CORE_CLUSTER_CANDIDATE"
    elif net <= 0 or negative_count >= max(1, math.ceil(len(rows) / 2)):
        classification = "FAILURE_CLUSTER"
    else:
        classification = "MIXED_POSITIVE_CLUSTER"
    return {
        "cluster_id": cluster_id,
        "classification": classification,
        "candidate_count": len(rows),
        "candidate_ids": [str(row.get("candidate_id") or "") for row in rows],
        "symbols": sorted({str(row.get("symbol") or "") for row in rows}),
        "unique_source_count": len(by_source),
        "robust_count": robust_count,
        "salvage_positive_count": salvage_count,
        "negative_count": negative_count,
        "robust_precision": rounded(precision),
        "net_per_axis_cell_sum_pct": rounded(net),
        "mean_expectancy_r": rounded(expectancy),
        "source_net_per_axis_cell_pct": by_source,
        "worst_source_net_per_axis_cell_pct": rounded(min(by_source.values(), default=0.0)),
    }


def select_cluster_count(matrix: np.ndarray, candidate_ids: list[str]) -> dict[str, Any]:
    fits: list[dict[str, Any]] = []
    for k in (2, 3):
        fit = fit_kmeans(matrix, candidate_ids, k)
        sizes = Counter(int(value) for value in fit["labels"].tolist())
        if min(sizes.values()) < 2:
            continue
        fits.append({**fit, "k": k, "silhouette": silhouette_score(matrix, fit["labels"])})
    if not fits:
        fit = fit_kmeans(matrix, candidate_ids, 2)
        return {**fit, "k": 2, "silhouette": silhouette_score(matrix, fit["labels"])}
    fits.sort(key=lambda row: (-float(row["silhouette"]), int(row["k"]), float(row["inertia"])))
    return fits[0]


def baseline_cluster_diagnosis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row.get("candidate_id") or ""))
    matrix = np.asarray(
        [[finite(row.get("features", {}).get(feature)) for feature in BASELINE_CLUSTER_FEATURES] for row in ordered],
        dtype=float,
    )
    scaled, median, scale = robust_scale(matrix)
    fit = select_cluster_count(scaled, [str(row["candidate_id"]) for row in ordered])
    labels = fit["labels"]
    clusters: list[dict[str, Any]] = []
    for cluster_id in sorted(set(int(value) for value in labels.tolist())):
        members = [row for index, row in enumerate(ordered) if int(labels[index]) == cluster_id]
        result = evaluate_cluster(members, cluster_id)
        centroid_scaled = np.asarray(fit["centroids"][cluster_id], dtype=float)
        centroid_raw = centroid_scaled * scale + median
        result["centroid"] = {
            feature: rounded(centroid_raw[index]) for index, feature in enumerate(BASELINE_CLUSTER_FEATURES)
        }
        clusters.append(result)
    clusters.sort(
        key=lambda row: (
            row["classification"] != "S_CORE_CLUSTER_CANDIDATE",
            -finite(row["robust_precision"]),
            -finite(row["net_per_axis_cell_sum_pct"]),
            int(row["cluster_id"]),
        )
    )
    return {
        "feature_names": BASELINE_CLUSTER_FEATURES,
        "selected_k": int(fit["k"]),
        "silhouette": rounded(fit["silhouette"]),
        "inertia": rounded(fit["inertia"]),
        "clusters": clusters,
    }


def training_cluster_score(cluster: dict[str, Any]) -> tuple[float, float, float, int]:
    return (
        1.0 if cluster["classification"] == "S_CORE_CLUSTER_CANDIDATE" else 0.0,
        finite(cluster["robust_precision"]),
        finite(cluster["net_per_axis_cell_sum_pct"]),
        int(cluster["candidate_count"]),
    )


def baseline_cluster_loso(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    sources = sorted({str(row.get("source_path") or "") for row in rows})
    folds: list[dict[str, Any]] = []
    selected_oos: list[dict[str, Any]] = []
    for held_out in sources:
        train = sorted([row for row in rows if str(row.get("source_path") or "") != held_out], key=lambda row: str(row["candidate_id"]))
        test = sorted([row for row in rows if str(row.get("source_path") or "") == held_out], key=lambda row: str(row["candidate_id"]))
        train_matrix = np.asarray(
            [[finite(row["features"].get(feature)) for feature in BASELINE_CLUSTER_FEATURES] for row in train], dtype=float
        )
        scaled_train, median, scale = robust_scale(train_matrix)
        fold_k = min(k, max(2, len(train) // 3))
        fit = fit_kmeans(scaled_train, [str(row["candidate_id"]) for row in train], fold_k)
        labels = fit["labels"]
        train_clusters: list[dict[str, Any]] = []
        for cluster_id in sorted(set(int(value) for value in labels.tolist())):
            members = [row for index, row in enumerate(train) if int(labels[index]) == cluster_id]
            train_clusters.append(evaluate_cluster(members, cluster_id))
        selected_cluster = max(train_clusters, key=training_cluster_score)
        test_matrix = np.asarray(
            [[finite(row["features"].get(feature)) for feature in BASELINE_CLUSTER_FEATURES] for row in test], dtype=float
        )
        scaled_test = (test_matrix - median) / scale
        test_labels = assign_clusters(scaled_test, fit["centroids"])
        selected = [row for index, row in enumerate(test) if int(test_labels[index]) == int(selected_cluster["cluster_id"])]
        selected_oos.extend(selected)
        fold_net = sum(finite(row["outcome"].get("net_per_axis_cell_pct")) for row in selected)
        folds.append({
            "held_out_source": held_out,
            "train_count": len(train),
            "test_count": len(test),
            "selected_train_cluster": selected_cluster,
            "selected_test_count": len(selected),
            "selected_test_candidate_ids": [str(row["candidate_id"]) for row in selected],
            "selected_test_robust_count": sum(1 for row in selected if bool(row["outcome"].get("robust"))),
            "selected_test_net_per_axis_cell_pct": rounded(fold_net),
        })
    selected_by_id = {str(row["candidate_id"]): row for row in selected_oos}
    selected_unique = list(selected_by_id.values())
    robust = sum(1 for row in selected_unique if bool(row["outcome"].get("robust")))
    negative = sum(1 for row in selected_unique if bool(row["outcome"].get("negative")))
    net = sum(finite(row["outcome"].get("net_per_axis_cell_pct")) for row in selected_unique)
    positive_source_folds = sum(1 for fold in folds if int(fold["selected_test_count"]) > 0 and finite(fold["selected_test_net_per_axis_cell_pct"]) > 0)
    return {
        "source_fold_count": len(folds),
        "folds": folds,
        "oos_selected_candidate_count": len(selected_unique),
        "oos_selected_candidate_ids": sorted(selected_by_id),
        "oos_robust_count": robust,
        "oos_negative_count": negative,
        "oos_robust_precision": rounded(robust / len(selected_unique) if selected_unique else 0.0),
        "oos_net_per_axis_cell_sum_pct": rounded(net),
        "positive_selected_source_fold_count": positive_source_folds,
    }


def baseline_symbol_diagnosis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_symbol[str(row.get("symbol") or "UNKNOWN")].append(row)
    for symbol, members in sorted(by_symbol.items()):
        output.append({
            "symbol": symbol,
            "candidate_count": len(members),
            "robust_count": sum(1 for row in members if bool(row["outcome"].get("robust"))),
            "negative_count": sum(1 for row in members if bool(row["outcome"].get("negative"))),
            "net_per_axis_cell_sum_pct": rounded(sum(finite(row["outcome"].get("net_per_axis_cell_pct")) for row in members)),
            "mean_expectancy_r": rounded(statistics.fmean(finite(row["outcome"].get("expectancy_r")) for row in members)),
            "candidate_ids": [str(row["candidate_id"]) for row in members],
        })
    return output


def geometry_relation(fill: float, raw_stop: float, raw_tp: float) -> str:
    if raw_tp <= 0 or raw_stop <= 0:
        return "NON_POSITIVE_RAW_GEOMETRY"
    if fill <= raw_tp:
        return "FILL_AT_OR_BELOW_RAW_TP"
    if fill >= raw_stop:
        return "FILL_AT_OR_ABOVE_RAW_STOP"
    return "RAW_GEOMETRY_VALID"


def rebased_geometry(fill: float, signal_entry: float, raw_stop: float) -> dict[str, Any]:
    raw_fraction = (raw_stop - signal_entry) / max(signal_entry, 1e-12)
    denominator = 1.0 - 0.75 * raw_fraction
    if raw_fraction <= 0 or denominator <= 0:
        return {"geometry_ok": False, "raw_r_fraction": rounded(raw_fraction), "stop": 0.0, "tp": 0.0}
    stop = fill / denominator
    tp = fill / (1.0 + 2.5 * raw_fraction)
    return {
        "geometry_ok": bool(0 < tp < fill < stop),
        "raw_r_fraction": rounded(raw_fraction),
        "stop": rounded(stop),
        "tp": rounded(tp),
    }


def scalp_geometry_diagnosis(
    root: Path,
    runner: Any,
    candidates: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    strategy_path = root / "backend/strategies/scalp_snap.py"
    module = load_module(strategy_path, "r7a4d2_scalp_geometry_source")
    costs = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]
    perturbations = [row for row in contract.get("perturbations", []) if isinstance(row, dict)]
    frame_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    parity_failures: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda row: str(row["candidate_id"])):
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
            sample = frame.iloc[start - 320:stop].copy().reset_index(drop=True)
            bar_index = int(candidate["bar_index"])
            history = sample.iloc[: bar_index + 1].copy().reset_index(drop=True)
            raw_signal = module.strategy(history, state=None, risk_action="hold", config=module.ScalpSnapConfig())
            if str(raw_signal.get("side") or "") != "short" or str(raw_signal.get("action") or "") != "enter":
                raise ValueError(f"SCALP_TARGET_SIGNAL_NOT_REPRODUCED:{raw_signal.get('side')}:{raw_signal.get('action')}")
            signal_entry = finite(raw_signal.get("entry"))
            raw_stop = finite(raw_signal.get("sl"))
            raw_tp = finite(raw_signal.get("tp"))
            axis_rows: list[dict[str, Any]] = []
            for cost in sorted(costs, key=lambda row: str(row.get("id") or "")):
                for perturbation in sorted(perturbations, key=lambda row: str(row.get("id") or "")):
                    delay = 1 + int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_entry_delay_bars") or 0)
                    fill_index = bar_index + delay
                    if fill_index >= len(sample):
                        relation = "FILL_OUTSIDE_SEGMENT"
                        fill = 0.0
                        rebased = {"geometry_ok": False, "raw_r_fraction": 0.0, "stop": 0.0, "tp": 0.0}
                    else:
                        slip_rate = finite(cost.get("slippage_bps_per_side")) / 10000.0
                        fill = finite(sample.iloc[fill_index]["open"]) * (1.0 - slip_rate)
                        relation = geometry_relation(fill, raw_stop, raw_tp)
                        rebased = rebased_geometry(fill, signal_entry, raw_stop)
                    axis_rows.append({
                        "cost_profile": str(cost.get("id") or ""),
                        "perturbation": str(perturbation.get("id") or ""),
                        "entry_delay_bars": delay,
                        "fill_index": fill_index,
                        "fill": rounded(fill),
                        "raw_geometry_relation": relation,
                        "rebased": rebased,
                    })
            computed_invalid = sum(1 for row in axis_rows if row["raw_geometry_relation"] != "RAW_GEOMETRY_VALID")
            proof_result = results_by_id[candidate_id]
            status = proof_result.get("status_histogram") if isinstance(proof_result.get("status_histogram"), dict) else {}
            proof_invalid = int(status.get("INVALID_GEOMETRY") or 0)
            if computed_invalid != proof_invalid:
                parity_failures.append({
                    "candidate_id": candidate_id,
                    "computed_invalid": computed_invalid,
                    "proof_invalid": proof_invalid,
                })
            outcome = {
                "net_pnl_sum_pct": rounded(proof_result.get("metrics", {}).get("net_pnl_sum_pct")),
                "expectancy_r": rounded(proof_result.get("metrics", {}).get("expectancy_r")),
                "salvage_positive": finite(proof_result.get("metrics", {}).get("net_pnl_sum_pct")) > 0
                and finite(proof_result.get("metrics", {}).get("expectancy_r")) > 0,
                "negative": finite(proof_result.get("metrics", {}).get("net_pnl_sum_pct")) <= 0
                or finite(proof_result.get("metrics", {}).get("expectancy_r")) <= 0,
            }
            all_rebased_valid = all(bool(row["rebased"].get("geometry_ok")) for row in axis_rows)
            if computed_invalid > 0 and outcome["salvage_positive"] and all_rebased_valid:
                classification = "SALVAGE_POSITIVE_FILL_REBASE_TESTABLE"
            elif computed_invalid == 0 and outcome["salvage_positive"]:
                classification = "SALVAGE_POSITIVE_RAW_GEOMETRY_STABLE"
            elif computed_invalid > 0 and outcome["negative"]:
                classification = "MIXED_GEOMETRY_AND_SIGNAL_FAILURE"
            else:
                classification = "NEGATIVE_SIGNAL_WITH_VALID_GEOMETRY"
            rows.append({
                "candidate_id": candidate_id,
                "symbol": str(history.iloc[-1].get("symbol") or "UNKNOWN"),
                "signal_entry": rounded(signal_entry),
                "raw_stop": rounded(raw_stop),
                "raw_tp": rounded(raw_tp),
                "raw_r_fraction": rounded((raw_stop - signal_entry) / max(signal_entry, 1e-12)),
                "raw_signal_reason": str(raw_signal.get("why") or ""),
                "raw_signal_skill": str(raw_signal.get("skill") or ""),
                "raw_indicators": raw_signal.get("indicators") if isinstance(raw_signal.get("indicators"), dict) else {},
                "computed_invalid_geometry_count": computed_invalid,
                "proof_invalid_geometry_count": proof_invalid,
                "all_rebased_geometry_valid": all_rebased_valid,
                "classification": classification,
                "outcome": outcome,
                "axes": axis_rows,
            })
        except Exception as exc:
            failures.append({"candidate_id": candidate_id, "error": f"{type(exc).__name__}:{exc}"})
    histogram = Counter(str(row["classification"]) for row in rows)
    rebase_candidates = [
        str(row["candidate_id"]) for row in rows if row["classification"] == "SALVAGE_POSITIVE_FILL_REBASE_TESTABLE"
    ]
    stable_candidates = [
        str(row["candidate_id"]) for row in rows if row["classification"] == "SALVAGE_POSITIVE_RAW_GEOMETRY_STABLE"
    ]
    relation_histogram = Counter(
        str(axis["raw_geometry_relation"]) for row in rows for axis in row.get("axes", [])
    )
    return {
        "candidate_count": len(rows),
        "failure_count": len(failures),
        "failures": failures,
        "geometry_parity_failure_count": len(parity_failures),
        "geometry_parity_failures": parity_failures,
        "classification_histogram": dict(sorted(histogram.items())),
        "raw_geometry_relation_histogram": dict(sorted(relation_histogram.items())),
        "rebase_counterfactual_candidate_count": len(rebase_candidates),
        "rebase_counterfactual_candidate_ids": rebase_candidates,
        "raw_geometry_stable_salvage_count": len(stable_candidates),
        "raw_geometry_stable_salvage_ids": stable_candidates,
        "rebase_counterfactual_ready": bool(rebase_candidates) and not parity_failures and not failures,
        "candidates": rows,
    }


def vol_component_plan(source_text: str, all_negative: bool) -> dict[str, Any]:
    required_tokens = [
        "vol_spike",
        "atr_spike",
        "trend_stretch_pct",
        "strong_up_peak",
        "short_veto",
        "short_fade_setup",
        "short_mean_target",
        "short_scale_in",
    ]
    missing = [token for token in required_tokens if token not in source_text]
    return {
        "source_token_parity": not missing,
        "missing_source_tokens": missing,
        "permanent_strategy_regime_block": all_negative,
        "reusable_observer_only_components": [
            "volume_spike_detector",
            "atr_expansion_detector",
            "trend_stretch_measurement",
            "body_and_wick_quality_measurement",
            "directional_trend_veto",
        ],
        "blocked_entry_components": [
            "shock_recovery_short_fade_entry",
            "ema_fast_mean_target_coupling",
            "fade_scale_in_progress_logic",
            "vol_spike_fade_short_rr_profile",
        ],
        "s_grade_material_status": "RAW_COMPONENTS_ONLY_REQUIRES_INDEPENDENT_OBSERVER_VALIDATION",
        "failure_learning_connection_allowed": False,
        "automatic_repair_or_promotion_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_causal_cluster_runner")
    contract = load_json(Path(args.contract).resolve())

    forensics_path = root / "runtime/r7a4d2_short_chart_structure_forensics/chart_forensics_v1.json"
    atlas_path = root / "runtime/r7a4d2_short_chart_structure_forensics/chart_atlas_v1.json"
    stress_path = root / "runtime/r7a4d2_short_expanded_candidate_stress_168/stress168_proof_v1.json"
    plan_path = root / "runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json"
    registry_path = root / str(contract["registry_path"])
    scalp_source_path = root / "backend/strategies/scalp_snap.py"
    vol_source_path = root / "backend/strategies/vol_spike_fade.py"

    forensics = load_json(forensics_path)
    atlas = load_json(atlas_path)
    stress = load_json(stress_path)
    plan = load_json(plan_path)
    blockers: list[str] = []
    if forensics.get("state") != "PASS_SHORT_CHART_STRUCTURE_FORENSICS" or int(forensics.get("blocker_count", -1)) != 0:
        blockers.append("CHART_FORENSICS_INVALID")
    if forensics.get("next_stage") != "R7.A4D2_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE":
        blockers.append("CHART_FORENSICS_NEXT_STAGE_MISMATCH")
    if int(forensics.get("candidate_count", -1)) != EXPECTED_CANDIDATE_COUNT or int(forensics.get("feature_count", -1)) != 20:
        blockers.append("CHART_FORENSICS_SHAPE_INVALID")
    if int(forensics.get("failure_count", -1)) != 0 or int(forensics.get("protected_mutation_path_count", -1)) != 0:
        blockers.append("CHART_FORENSICS_INTEGRITY_FAILED")
    if forensics.get("gate_uses_pre_entry_chart_only") is not True or forensics.get("future_chart_context_used_for_gate") is not False:
        blockers.append("CHART_GATE_LEAKAGE_GUARD_FAILED")
    if atlas.get("candidate_count") != EXPECTED_CANDIDATE_COUNT or atlas.get("future_context_used_for_gate") is not False:
        blockers.append("CHART_ATLAS_INVALID")
    if stress.get("state") != "PASS_SHORT_EXPANDED_CANDIDATE_STRESS_168" or int(stress.get("failed_cell_count", -1)) != 0:
        blockers.append("STRESS168_INVALID")
    if plan.get("state") != "PASS_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN" or int(plan.get("blocker_count", -1)) != 0:
        blockers.append("EXPANDED_PLAN_INVALID")
    if forensics.get("vol_permanent_block_recommended") is not True:
        blockers.append("VOL_PERMANENT_BLOCK_EVIDENCE_MISSING")

    feature_rows = [row for row in forensics.get("candidate_feature_rows", []) if isinstance(row, dict)]
    candidates = [row for row in plan.get("expanded_stress_candidates", []) if isinstance(row, dict)]
    results = [row for row in stress.get("candidate_results", []) if isinstance(row, dict)]
    feature_by_id = {str(row.get("candidate_id") or ""): row for row in feature_rows}
    candidate_by_id = {str(row.get("candidate_id") or ""): row for row in candidates}
    result_by_id = {str(row.get("candidate_id") or ""): row for row in results}
    ids = set(feature_by_id)
    if len(ids) != EXPECTED_CANDIDATE_COUNT or ids != set(candidate_by_id) or ids != set(result_by_id):
        blockers.append(f"CANDIDATE_PARITY_FAILED:{len(feature_by_id)}:{len(candidate_by_id)}:{len(result_by_id)}")
    if dict(Counter(str(row.get("bucket") or "") for row in feature_rows)) != EXPECTED_BUCKET_COUNTS:
        blockers.append("FEATURE_BUCKET_PARITY_FAILED")
    if any(feature not in forensics.get("feature_names", []) for feature in BASELINE_CLUSTER_FEATURES):
        blockers.append("BASELINE_CLUSTER_FEATURE_MISSING")

    protected = [
        forensics_path,
        atlas_path,
        stress_path,
        plan_path,
        registry_path,
        scalp_source_path,
        vol_source_path,
    ]
    for candidate in candidates:
        try:
            protected.append(root / runner.safe_repo_path(str(candidate.get("source_path") or "")))
        except Exception as exc:
            blockers.append(f"CANDIDATE_SOURCE_PATH_INVALID:{type(exc).__name__}:{exc}")
    protected = list(dict.fromkeys(protected))
    before = runner.snapshot(protected)

    baseline_rows = [row for row in feature_rows if row.get("bucket") == "baseline_trend_down"]
    scalp_candidates = [row for row in candidates if row.get("bucket") == "scalp_snap_trend_up"]
    vol_rows = [row for row in feature_rows if row.get("bucket") == "vol_spike_fade_shock_recovery"]
    baseline_cluster: dict[str, Any] = {}
    baseline_loso: dict[str, Any] = {}
    scalp_geometry: dict[str, Any] = {}
    vol_components: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []

    if not blockers:
        try:
            baseline_cluster = baseline_cluster_diagnosis(baseline_rows)
            baseline_loso = baseline_cluster_loso(baseline_rows, int(baseline_cluster["selected_k"]))
        except Exception as exc:
            failures.append({"scope": "baseline_cluster", "error": f"{type(exc).__name__}:{exc}"})
        try:
            scalp_geometry = scalp_geometry_diagnosis(root, runner, scalp_candidates, result_by_id, contract)
        except Exception as exc:
            failures.append({"scope": "scalp_geometry", "error": f"{type(exc).__name__}:{exc}"})
        try:
            vol_components = vol_component_plan(
                vol_source_path.read_text(encoding="utf-8"),
                bool(vol_rows) and all(bool(row.get("outcome", {}).get("negative")) for row in vol_rows),
            )
        except Exception as exc:
            failures.append({"scope": "vol_components", "error": f"{type(exc).__name__}:{exc}"})

    if failures:
        blockers.append(f"CAUSAL_DIAGNOSE_EXECUTION_FAILED:{len(failures)}")
    if scalp_geometry and (
        int(scalp_geometry.get("failure_count", -1)) != 0
        or int(scalp_geometry.get("geometry_parity_failure_count", -1)) != 0
        or int(scalp_geometry.get("candidate_count", -1)) != 12
    ):
        blockers.append("SCALP_GEOMETRY_DIAGNOSIS_INVALID")
    if vol_components and vol_components.get("source_token_parity") is not True:
        blockers.append("VOL_COMPONENT_SOURCE_PARITY_FAILED")

    s_clusters = [row for row in baseline_cluster.get("clusters", []) if row.get("classification") == "S_CORE_CLUSTER_CANDIDATE"]
    baseline_cluster_gate_ready = bool(s_clusters) and (
        int(baseline_loso.get("oos_selected_candidate_count", 0)) >= 3
        and finite(baseline_loso.get("oos_robust_precision")) >= 0.66
        and finite(baseline_loso.get("oos_net_per_axis_cell_sum_pct")) > 0
        and int(baseline_loso.get("positive_selected_source_fold_count", 0)) >= 3
    )
    failure_clusters = [row for row in baseline_cluster.get("clusters", []) if row.get("classification") == "FAILURE_CLUSTER"]
    scalp_rebase_ready = scalp_geometry.get("rebase_counterfactual_ready") is True

    after = runner.snapshot(protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
    blockers = list(dict.fromkeys(blockers))
    state = "PASS_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE" if not blockers else "HOLD_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_INPUT"
    if blockers:
        next_stage = "R7.A4D2_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE"
    elif baseline_cluster_gate_ready or scalp_rebase_ready:
        next_stage = "R7.A4D2_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN"
    else:
        next_stage = "R7.A4D2_SHORT_CAUSAL_CLUSTER_MARKET_EXPANSION"

    repair_plan = [
        {
            "bucket": "baseline_trend_down",
            "action": "build_observer_only_cluster_gate_counterfactual" if baseline_cluster_gate_ready else "expand_cluster_across_independent_eth_sol_and_control_segments",
            "cluster_gate_ready": baseline_cluster_gate_ready,
            "s_core_cluster_count": len(s_clusters),
            "failure_cluster_count": len(failure_clusters),
            "retain_grid_strategy_quarantine": True,
            "automatic_production_promotion_allowed": False,
        },
        {
            "bucket": "scalp_snap_trend_up",
            "action": "fill_rebased_geometry_counterfactual_on_salvage_watchlist" if scalp_rebase_ready else "retain_block_and_expand_geometry_trace",
            "rebase_counterfactual_ready": scalp_rebase_ready,
            "rebase_candidate_count": int(scalp_geometry.get("rebase_counterfactual_candidate_count", 0)),
            "block_non_watchlist_candidates": True,
            "entry_threshold_relaxation_allowed": False,
        },
        {
            "bucket": "vol_spike_fade_shock_recovery",
            "action": "permanent_strategy_regime_block_and_observer_component_extraction",
            "permanent_block": True,
            "component_status": vol_components.get("s_grade_material_status"),
            "failure_learning_connection_allowed": False,
            "automatic_repair_or_promotion_allowed": False,
        },
    ]

    output_dir = root / "runtime/r7a4d2_short_chart_causal_cluster_diagnose"
    evidence = {
        "schema": "r7a4d2_short_chart_causal_cluster_diagnose_v1",
        "official_stage": "R7.A4D2_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "candidate_count": len(feature_rows),
        "gate_uses_pre_entry_chart_only": True,
        "future_outcome_used_to_fit_clusters": False,
        "future_outcome_used_to_evaluate_clusters": True,
        "baseline_cluster_gate_ready": baseline_cluster_gate_ready,
        "baseline_cluster_diagnosis": baseline_cluster,
        "baseline_cluster_leave_one_source_out": baseline_loso,
        "baseline_symbol_diagnosis": baseline_symbol_diagnosis(baseline_rows) if baseline_rows else [],
        "baseline_s_core_clusters": s_clusters,
        "baseline_failure_clusters": failure_clusters,
        "scalp_geometry_diagnosis": scalp_geometry,
        "vol_component_decomposition": vol_components,
        "repair_plan": repair_plan,
        "failure_count": len(failures),
        "failures": failures,
        "protected_mutation_path_count": len(mutation_paths),
        "protected_mutation_paths": mutation_paths,
        "strategy_mutation_allowed": False,
        "admission_expansion_allowed": False,
        "shadow_start_allowed": False,
        "failure_learning_connection_allowed": False,
        "next_stage": next_stage,
    }
    runner.atomic_json(output_dir / "causal_cluster_diagnose_v1.json", evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("CANDIDATE_COUNT=" + str(len(feature_rows)))
    print("GATE_USES_PRE_ENTRY_CHART_ONLY=true")
    print("FUTURE_OUTCOME_USED_TO_FIT_CLUSTERS=false")
    print("BASELINE_CLUSTER_SELECTED_K=" + str(baseline_cluster.get("selected_k", 0)))
    print("BASELINE_CLUSTER_SILHOUETTE=" + str(baseline_cluster.get("silhouette", 0.0)))
    print("BASELINE_S_CORE_CLUSTER_COUNT=" + str(len(s_clusters)))
    print("BASELINE_FAILURE_CLUSTER_COUNT=" + str(len(failure_clusters)))
    print("BASELINE_CLUSTER_GATE_READY=" + str(baseline_cluster_gate_ready).lower())
    print("BASELINE_CLUSTERS=" + json.dumps(baseline_cluster.get("clusters", []), ensure_ascii=False, sort_keys=True))
    print("BASELINE_CLUSTER_LOSO=" + json.dumps(baseline_loso, ensure_ascii=False, sort_keys=True))
    print("BASELINE_SYMBOL_DIAGNOSIS=" + json.dumps(evidence["baseline_symbol_diagnosis"], ensure_ascii=False, sort_keys=True))
    print("SCALP_GEOMETRY_PARITY_FAILURE_COUNT=" + str(scalp_geometry.get("geometry_parity_failure_count", 0)))
    print("SCALP_REBASE_COUNTERFACTUAL_READY=" + str(scalp_rebase_ready).lower())
    print("SCALP_REBASE_COUNTERFACTUAL_CANDIDATE_COUNT=" + str(scalp_geometry.get("rebase_counterfactual_candidate_count", 0)))
    print("SCALP_GEOMETRY_CLASSIFICATION_HISTOGRAM=" + json.dumps(scalp_geometry.get("classification_histogram", {}), sort_keys=True))
    print("SCALP_RAW_GEOMETRY_RELATION_HISTOGRAM=" + json.dumps(scalp_geometry.get("raw_geometry_relation_histogram", {}), sort_keys=True))
    print("VOL_PERMANENT_BLOCK=true")
    print("VOL_COMPONENT_DECOMPOSITION=" + json.dumps(vol_components, ensure_ascii=False, sort_keys=True))
    print("REPAIR_PLAN=" + json.dumps(repair_plan, ensure_ascii=False, sort_keys=True))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("FAILURE_COUNT=" + str(len(failures)))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output_dir / "causal_cluster_diagnose_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
