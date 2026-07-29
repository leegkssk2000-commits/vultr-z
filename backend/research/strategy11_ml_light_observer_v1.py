from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

INPUT_SCHEMA = "strategy11.ml_light_observer.input.v1"
OUTPUT_SCHEMA = "strategy11.ml_light_observer.output.v1"
MODEL_SCHEMA = "strategy11.ml_light_logistic_model.v1"
OBSERVER_TYPE = "ML_LIGHT"
CAPABILITIES = ("READ_EVIDENCE", "EMIT_OBSERVATION", "EMIT_CALIBRATION", "REQUEST_HOLD")
SAFETY = {
    "observer_only": True,
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "advisory_enabled": False,
}


class MLLightObserverError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise MLLightObserverError(f"{code}:{detail}" if detail else code)


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        _fail("TIMESTAMP_REQUIRED", name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLLightObserverError(f"TIMESTAMP_INVALID:{name}") from exc
    if parsed.tzinfo is None:
        _fail("TIMESTAMP_TIMEZONE_REQUIRED", name)
    return parsed


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    return result


def _sigmoid(value: float) -> float:
    bounded = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-bounded))


@dataclass(frozen=True)
class MLLightConfig:
    feature_order: tuple[str, ...]
    training_cutoff_ts: str
    evaluation_start_ts: str
    max_iter: int = 300
    learning_rate: float = 0.05
    regularization_l2: float = 0.02
    seed: int = 17
    min_train_samples: int = 200
    min_evaluation_samples: int = 100
    calibration_bins: int = 10
    brier_limit: float = 0.25
    ece_limit: float = 0.12
    drift_psi_limit: float = 0.25

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MLLightConfig":
        features = value.get("feature_order")
        if not isinstance(features, list) or not features or len(features) > 32:
            _fail("FEATURE_ORDER_INVALID")
        feature_order = tuple(str(item).strip() for item in features)
        if any(not item for item in feature_order) or len(set(feature_order)) != len(feature_order):
            _fail("FEATURE_ORDER_DUPLICATE_OR_EMPTY")
        training_cutoff = _timestamp(value.get("training_cutoff_ts"), "training_cutoff_ts")
        evaluation_start = _timestamp(value.get("evaluation_start_ts"), "evaluation_start_ts")
        if training_cutoff >= evaluation_start:
            _fail("TRAINING_EVALUATION_LEAKAGE")
        max_iter = int(value.get("max_iter", 300))
        if not 20 <= max_iter <= 1000:
            _fail("MAX_ITER_OUT_OF_BOUNDS")
        learning_rate = _number(value.get("learning_rate", 0.05), "learning_rate")
        regularization = _number(value.get("regularization_l2", 0.02), "regularization_l2")
        if not 0.0001 <= learning_rate <= 0.2 or not 0.0 < regularization <= 1.0:
            _fail("OPTIMIZER_BOUNDS_INVALID")
        bins = int(value.get("calibration_bins", 10))
        if not 5 <= bins <= 20:
            _fail("CALIBRATION_BINS_INVALID")
        return cls(
            feature_order=feature_order,
            training_cutoff_ts=value["training_cutoff_ts"],
            evaluation_start_ts=value["evaluation_start_ts"],
            max_iter=max_iter,
            learning_rate=learning_rate,
            regularization_l2=regularization,
            seed=int(value.get("seed", 17)),
            min_train_samples=int(value.get("min_train_samples", 200)),
            min_evaluation_samples=int(value.get("min_evaluation_samples", 100)),
            calibration_bins=bins,
            brier_limit=_number(value.get("brier_limit", 0.25), "brier_limit"),
            ece_limit=_number(value.get("ece_limit", 0.12), "ece_limit"),
            drift_psi_limit=_number(value.get("drift_psi_limit", 0.25), "drift_psi_limit"),
        )


def _normalize_rows(rows: Sequence[Mapping[str, Any]], config: MLLightConfig) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _fail("ROW_OBJECT_REQUIRED", str(index))
        features = row.get("features")
        if not isinstance(features, Mapping):
            _fail("FEATURE_OBJECT_REQUIRED", str(index))
        if set(features) != set(config.feature_order):
            _fail("FEATURE_LINEAGE_KEY_MISMATCH", str(index))
        label = row.get("label")
        if label not in (0, 1):
            _fail("BINARY_LABEL_REQUIRED", str(index))
        source_sha = str(row.get("source_sha", ""))
        feature_lineage_sha = str(row.get("feature_lineage_sha", ""))
        if len(source_sha) != 64 or len(feature_lineage_sha) != 64:
            _fail("SOURCE_OR_FEATURE_LINEAGE_SHA_INVALID", str(index))
        normalized.append({
            "event_id": str(row.get("event_id", "")),
            "event_ts": str(row.get("event_ts", "")),
            "parsed_ts": _timestamp(row.get("event_ts"), f"rows[{index}].event_ts"),
            "features": [_number(features[key], f"rows[{index}].features.{key}") for key in config.feature_order],
            "label": int(label),
            "source_sha": source_sha,
            "feature_lineage_sha": feature_lineage_sha,
        })
    if len({row["event_id"] for row in normalized}) != len(normalized):
        _fail("DUPLICATE_EVENT_ID")
    return sorted(normalized, key=lambda row: (row["parsed_ts"], row["event_id"]))


def _split(rows: list[dict[str, Any]], config: MLLightConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    training_cutoff = _timestamp(config.training_cutoff_ts, "training_cutoff_ts")
    evaluation_start = _timestamp(config.evaluation_start_ts, "evaluation_start_ts")
    train = [row for row in rows if row["parsed_ts"] <= training_cutoff]
    evaluation = [row for row in rows if row["parsed_ts"] >= evaluation_start]
    if len(train) < config.min_train_samples:
        _fail("TRAIN_SAMPLE_COUNT_LOW", str(len(train)))
    if len(evaluation) < config.min_evaluation_samples:
        _fail("EVALUATION_SAMPLE_COUNT_LOW", str(len(evaluation)))
    if {row["event_id"] for row in train} & {row["event_id"] for row in evaluation}:
        _fail("TRAINING_EVALUATION_LEAKAGE")
    if len({row["label"] for row in train}) != 2:
        _fail("CLASS_BALANCE_TRAIN_SINGLE_CLASS")
    if len({row["label"] for row in evaluation}) != 2:
        _fail("CLASS_BALANCE_EVALUATION_SINGLE_CLASS")
    return train, evaluation


def _fit_standardization(train: list[dict[str, Any]], width: int) -> tuple[list[float], list[float]]:
    means = [sum(row["features"][j] for row in train) / len(train) for j in range(width)]
    stds: list[float] = []
    for j in range(width):
        variance = sum((row["features"][j] - means[j]) ** 2 for row in train) / max(1, len(train) - 1)
        stds.append(max(math.sqrt(variance), 1e-9))
    return means, stds


def _transform(rows: list[dict[str, Any]], means: list[float], stds: list[float]) -> list[list[float]]:
    return [[(value - means[j]) / stds[j] for j, value in enumerate(row["features"])] for row in rows]


def fit(train_x: list[list[float]], train_y: list[int], config: MLLightConfig) -> tuple[list[float], float]:
    width = len(config.feature_order)
    weights = [0.0] * width
    intercept = 0.0
    positives = sum(train_y)
    negatives = len(train_y) - positives
    class_balance = {
        1: len(train_y) / max(1.0, 2.0 * positives),
        0: len(train_y) / max(1.0, 2.0 * negatives),
    }
    for _ in range(config.max_iter):
        grad_w = [0.0] * width
        grad_b = 0.0
        for features, label in zip(train_x, train_y):
            probability = _sigmoid(intercept + sum(weight * value for weight, value in zip(weights, features)))
            error = (probability - label) * class_balance[label]
            for j, value in enumerate(features):
                grad_w[j] += error * value
            grad_b += error
        scale = 1.0 / len(train_x)
        for j in range(width):
            regularization = config.regularization_l2 * weights[j]
            weights[j] -= config.learning_rate * (grad_w[j] * scale + regularization)
        intercept -= config.learning_rate * grad_b * scale
    return weights, intercept


def predict_score(features: list[list[float]], weights: list[float], intercept: float) -> list[float]:
    return [_sigmoid(intercept + sum(weight * value for weight, value in zip(weights, row))) for row in features]


def _brier_score(labels: list[int], probabilities: list[float]) -> float:
    return sum((probability - label) ** 2 for label, probability in zip(labels, probabilities)) / len(labels)


def _ece_score(labels: list[int], probabilities: list[float], bins: int) -> float:
    total = len(labels)
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [(label, probability) for label, probability in zip(labels, probabilities) if low <= probability < high or (index == bins - 1 and probability == 1.0)]
        if not members:
            continue
        accuracy = sum(label for label, _ in members) / len(members)
        confidence = sum(probability for _, probability in members) / len(members)
        error += len(members) / total * abs(accuracy - confidence)
    return error


def _auc(labels: list[int], probabilities: list[float]) -> float:
    positives = [p for y, p in zip(labels, probabilities) if y == 1]
    negatives = [p for y, p in zip(labels, probabilities) if y == 0]
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives)
    return wins / max(1, len(positives) * len(negatives))


def _drift_psi(train_x: list[list[float]], evaluation_x: list[list[float]]) -> float:
    # Deterministic five-bin standardization drift proxy; bins are fixed on train z-scores.
    edges = (-math.inf, -1.0, -0.25, 0.25, 1.0, math.inf)
    feature_scores: list[float] = []
    for j in range(len(train_x[0])):
        train_counts = [0] * 5
        eval_counts = [0] * 5
        for row, counts in ((row, train_counts) for row in train_x):
            value = row[j]
            counts[next(i for i in range(5) if edges[i] <= value < edges[i + 1])] += 1
        for row, counts in ((row, eval_counts) for row in evaluation_x):
            value = row[j]
            counts[next(i for i in range(5) if edges[i] <= value < edges[i + 1])] += 1
        score = 0.0
        for train_count, eval_count in zip(train_counts, eval_counts):
            p = max(train_count / len(train_x), 1e-6)
            q = max(eval_count / len(evaluation_x), 1e-6)
            score += (q - p) * math.log(q / p)
        feature_scores.append(score)
    return max(feature_scores)


def observe(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    config = MLLightConfig.from_mapping(payload.get("config", {}))
    rows = _normalize_rows(payload.get("rows", []), config)
    train, evaluation = _split(rows, config)
    means, stds = _fit_standardization(train, len(config.feature_order))
    train_x = _transform(train, means, stds)
    evaluation_x = _transform(evaluation, means, stds)
    train_y = [row["label"] for row in train]
    evaluation_y = [row["label"] for row in evaluation]
    weights, intercept = fit(train_x, train_y, config)
    probabilities = predict_score(evaluation_x, weights, intercept)
    brier_score = _brier_score(evaluation_y, probabilities)
    ece_score = _ece_score(evaluation_y, probabilities, config.calibration_bins)
    auc_score = _auc(evaluation_y, probabilities)
    drift_psi = _drift_psi(train_x, evaluation_x)
    config_sha = canonical_sha(config.__dict__)
    training_data_sha = canonical_sha([{key: row[key] for key in ("event_id", "event_ts", "features", "label", "source_sha", "feature_lineage_sha")} for row in train])
    model = {
        "schema_version": MODEL_SCHEMA,
        "feature_order": list(config.feature_order),
        "standardization": {"means": means, "stds": stds, "fit_scope": "TRAIN_ONLY"},
        "weights": weights,
        "intercept": intercept,
        "regularization_l2": config.regularization_l2,
        "max_iter": config.max_iter,
        "seed": config.seed,
    }
    model_sha = canonical_sha(model)
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
        "source_sha": canonical_sha([row["source_sha"] for row in rows]),
        "model_sha": model_sha,
        "config_sha": config_sha,
        "training_data_sha": training_data_sha,
        "feature_lineage_sha": canonical_sha([row["feature_lineage_sha"] for row in rows]),
        "output_schema_sha": canonical_sha({"schema_version": OUTPUT_SCHEMA, "capabilities": CAPABILITIES}),
        "training_cutoff_ts": config.training_cutoff_ts,
        "evaluation_start_ts": config.evaluation_start_ts,
        "training_sample_count": len(train),
        "evaluation_sample_count": len(evaluation),
        "class_balance": {
            "train_positive": sum(train_y),
            "train_negative": len(train_y) - sum(train_y),
            "evaluation_positive": sum(evaluation_y),
            "evaluation_negative": len(evaluation_y) - sum(evaluation_y),
        },
        "calibration": {"brier_score": brier_score, "ece_score": ece_score, "bins": config.calibration_bins},
        "discrimination": {"auc_score": auc_score},
        "drift": {"max_feature_psi": drift_psi, "limit": config.drift_psi_limit},
        "leakage_check_pass": True,
        "rollback_plan": "DISCARD_MODEL_ARTIFACT_AND_OBSERVATIONS",
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
    result["observer_manifest_sha"] = canonical_sha(result)
    return result
