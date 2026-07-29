from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from backend.research import strategy11_ml_light_observer_v1 as core

INPUT_SCHEMA = core.INPUT_SCHEMA
OUTPUT_SCHEMA = "strategy11.ml_light_observer_optimized.output.v1"
MODEL_SCHEMA = "strategy11.ml_light_calibrated_logistic_model.v1"
OBSERVER_TYPE = core.OBSERVER_TYPE
CAPABILITIES = core.CAPABILITIES
SAFETY = core.SAFETY
MLLightObserverError = core.MLLightObserverError


def _logits(features: list[list[float]], weights: list[float], intercept: float) -> list[float]:
    return [intercept + sum(weight * value for weight, value in zip(weights, row)) for row in features]


def _split_fit_calibration(
    train: list[dict[str, Any]], calibration_fraction: float = 0.20, minimum_calibration: int = 40
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calibration_count = max(minimum_calibration, int(round(len(train) * calibration_fraction)))
    if calibration_count >= len(train) // 2:
        core._fail("CALIBRATION_HOLDOUT_TOO_LARGE")
    fit_rows = train[:-calibration_count]
    calibration_rows = train[-calibration_count:]
    if len({row["label"] for row in fit_rows}) != 2:
        core._fail("FIT_SPLIT_SINGLE_CLASS")
    if len({row["label"] for row in calibration_rows}) != 2:
        core._fail("CALIBRATION_SPLIT_SINGLE_CLASS")
    if {row["event_id"] for row in fit_rows} & {row["event_id"] for row in calibration_rows}:
        core._fail("FIT_CALIBRATION_LEAKAGE")
    return fit_rows, calibration_rows


def _fit_platt(
    logits: list[float], labels: list[int], *, max_iter: int = 500, learning_rate: float = 0.05,
    regularization_l2: float = 0.001
) -> tuple[float, float]:
    if len(logits) != len(labels) or not logits:
        core._fail("PLATT_INPUT_INVALID")
    if len(set(labels)) != 2:
        core._fail("PLATT_SINGLE_CLASS")
    scale = 1.0
    offset = 0.0
    for _ in range(max_iter):
        grad_scale = 0.0
        grad_offset = 0.0
        for logit, label in zip(logits, labels):
            probability = core._sigmoid(scale * logit + offset)
            error = probability - label
            grad_scale += error * logit
            grad_offset += error
        inv_n = 1.0 / len(logits)
        grad_scale = grad_scale * inv_n + regularization_l2 * (scale - 1.0)
        grad_offset *= inv_n
        scale = max(0.05, min(10.0, scale - learning_rate * grad_scale))
        offset = max(-10.0, min(10.0, offset - learning_rate * grad_offset))
    return scale, offset


def _apply_platt(logits: list[float], scale: float, offset: float) -> list[float]:
    return [core._sigmoid(scale * value + offset) for value in logits]


def observe(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != INPUT_SCHEMA:
        core._fail("INPUT_SCHEMA_MISMATCH")
    config = core.MLLightConfig.from_mapping(payload.get("config", {}))
    rows = core._normalize_rows(payload.get("rows", []), config)
    train, evaluation = core._split(rows, config)
    fit_rows, calibration_rows = _split_fit_calibration(train)

    means, stds = core._fit_standardization(fit_rows, len(config.feature_order))
    fit_x = core._transform(fit_rows, means, stds)
    calibration_x = core._transform(calibration_rows, means, stds)
    evaluation_x = core._transform(evaluation, means, stds)
    fit_y = [row["label"] for row in fit_rows]
    calibration_y = [row["label"] for row in calibration_rows]
    evaluation_y = [row["label"] for row in evaluation]

    weights, intercept = core.fit(fit_x, fit_y, config)
    calibration_logits = _logits(calibration_x, weights, intercept)
    platt_scale, platt_offset = _fit_platt(calibration_logits, calibration_y)
    evaluation_logits = _logits(evaluation_x, weights, intercept)
    probabilities = _apply_platt(evaluation_logits, platt_scale, platt_offset)

    brier_score = core._brier_score(evaluation_y, probabilities)
    ece_score = core._ece_score(evaluation_y, probabilities, config.calibration_bins)
    auc_score = core._auc(evaluation_y, probabilities)
    drift_psi = core._drift_psi(fit_x, evaluation_x)
    config_sha = core.canonical_sha({**config.__dict__, "calibration_method": "PLATT_TRAIN_HOLDOUT_20PCT"})
    training_data_sha = core.canonical_sha([
        {key: row[key] for key in ("event_id", "event_ts", "features", "label", "source_sha", "feature_lineage_sha")}
        for row in train
    ])
    model = {
        "schema_version": MODEL_SCHEMA,
        "feature_order": list(config.feature_order),
        "standardization": {"means": means, "stds": stds, "fit_scope": "FIT_SPLIT_ONLY"},
        "weights": weights,
        "intercept": intercept,
        "regularization_l2": config.regularization_l2,
        "max_iter": config.max_iter,
        "seed": config.seed,
        "calibration": {
            "method": "PLATT_SCALING",
            "fit_scope": "TRAINING_HOLDOUT_ONLY",
            "calibration_fraction": 0.20,
            "sample_count": len(calibration_rows),
            "scale": platt_scale,
            "offset": platt_offset,
            "max_iter": 500,
            "learning_rate": 0.05,
            "regularization_l2": 0.001
        },
    }
    model_sha = core.canonical_sha(model)
    blockers: list[str] = []
    if brier_score > config.brier_limit:
        blockers.append("BRIER_CALIBRATION_LIMIT")
    if ece_score > config.ece_limit:
        blockers.append("ECE_CALIBRATION_LIMIT")
    if drift_psi > config.drift_psi_limit:
        blockers.append("FEATURE_DRIFT_PSI_LIMIT")

    result = {
        "schema_version": OUTPUT_SCHEMA,
        "observer_type": OBSERVER_TYPE,
        "state": "PASS_ML_LIGHT_OBSERVATION" if not blockers else "HOLD_ML_LIGHT_OBSERVATION",
        "source_sha": core.canonical_sha([row["source_sha"] for row in rows]),
        "model_sha": model_sha,
        "config_sha": config_sha,
        "training_data_sha": training_data_sha,
        "feature_lineage_sha": core.canonical_sha([row["feature_lineage_sha"] for row in rows]),
        "output_schema_sha": core.canonical_sha({"schema_version": OUTPUT_SCHEMA, "capabilities": CAPABILITIES}),
        "training_cutoff_ts": config.training_cutoff_ts,
        "evaluation_start_ts": config.evaluation_start_ts,
        "training_sample_count": len(train),
        "fit_sample_count": len(fit_rows),
        "calibration_sample_count": len(calibration_rows),
        "evaluation_sample_count": len(evaluation),
        "class_balance": {
            "fit_positive": sum(fit_y),
            "fit_negative": len(fit_y) - sum(fit_y),
            "calibration_positive": sum(calibration_y),
            "calibration_negative": len(calibration_y) - sum(calibration_y),
            "evaluation_positive": sum(evaluation_y),
            "evaluation_negative": len(evaluation_y) - sum(evaluation_y),
        },
        "calibration": {
            "method": "PLATT_SCALING",
            "fit_scope": "TRAINING_HOLDOUT_ONLY",
            "evaluation_used_for_fit": False,
            "brier_score": brier_score,
            "ece_score": ece_score,
            "bins": config.calibration_bins,
        },
        "discrimination": {"auc_score": auc_score},
        "drift": {"max_feature_psi": drift_psi, "limit": config.drift_psi_limit},
        "leakage_check_pass": True,
        "rollback_plan": "DISCARD_CALIBRATED_MODEL_ARTIFACT_AND_OBSERVATIONS",
        "deterministic_optimizer": True,
        "model": model,
        "evaluation_scores": [
            {"event_id": row["event_id"], "score": score, "label": row["label"]}
            for row, score in zip(evaluation, probabilities)
        ],
        "blocker_codes": blockers,
        "capabilities": list(CAPABILITIES),
        "requested_action": "hold" if blockers else "observer_burnin_only",
        **copy.deepcopy(SAFETY),
    }
    result["observer_manifest_sha"] = core.canonical_sha(result)
    return result
