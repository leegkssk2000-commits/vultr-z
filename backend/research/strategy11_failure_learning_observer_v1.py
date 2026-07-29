from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

INPUT_SCHEMA = "strategy11.failure_learning_observer.input.v1"
OUTPUT_SCHEMA = "strategy11.failure_learning_observer.output.v1"
MODEL_SCHEMA = "strategy11.failure_learning_taxonomy_model.v1"
OBSERVER_TYPE = "FAILURE_LEARNING"
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
DEFAULT_TAXONOMY = {
    "NO_SIGNAL": "ENTRY_ABSENCE",
    "BASE_TRIGGER_FALSE": "ENTRY_ABSENCE",
    "CONTEXT_GATE_BLOCK": "CONTEXT_OVERFILTER",
    "REGIME_MISMATCH": "REGIME_MISMATCH",
    "LOSS_SHAPE": "EXIT_OR_RISK_SHAPE",
    "GIVEBACK": "EXIT_OR_RISK_SHAPE",
    "COST_OVERFLOW": "EXECUTION_ECONOMICS",
    "LOW_WINDOW_BREADTH": "GENERALIZATION",
    "LINEAGE_GAP": "DATA_INTEGRITY",
    "UNKNOWN": "UNKNOWN",
}


class FailureLearningObserverError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise FailureLearningObserverError(f"{code}:{detail}" if detail else code)


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        _fail("TIMESTAMP_REQUIRED", name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FailureLearningObserverError(f"TIMESTAMP_INVALID:{name}") from exc
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


@dataclass(frozen=True)
class FailureLearningConfig:
    training_cutoff_ts: str
    evaluation_start_ts: str
    min_sample_count: int = 20
    min_group_sample_count: int = 5
    unknown_rate_limit: float = 0.05
    recurrence_drift_limit: float = 0.20
    severity_loss_cap_r: float = 2.0
    confidence_prior_alpha: float = 1.0
    confidence_prior_beta: float = 1.0
    deterministic_seed: int = 19

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FailureLearningConfig":
        training_cutoff = _timestamp(value.get("training_cutoff_ts"), "training_cutoff_ts")
        evaluation_start = _timestamp(value.get("evaluation_start_ts"), "evaluation_start_ts")
        if training_cutoff >= evaluation_start:
            _fail("TRAINING_EVALUATION_LEAKAGE")
        min_sample_count = int(value.get("min_sample_count", 20))
        min_group_sample_count = int(value.get("min_group_sample_count", 5))
        if min_sample_count < 20 or min_group_sample_count < 3:
            _fail("SAMPLE_COUNT_POLICY_TOO_LOW")
        unknown_limit = _number(value.get("unknown_rate_limit", 0.05), "unknown_rate_limit")
        drift_limit = _number(value.get("recurrence_drift_limit", 0.20), "recurrence_drift_limit")
        if not 0.0 <= unknown_limit <= 0.25 or not 0.0 <= drift_limit <= 1.0:
            _fail("RATE_LIMIT_INVALID")
        return cls(
            training_cutoff_ts=value["training_cutoff_ts"],
            evaluation_start_ts=value["evaluation_start_ts"],
            min_sample_count=min_sample_count,
            min_group_sample_count=min_group_sample_count,
            unknown_rate_limit=unknown_limit,
            recurrence_drift_limit=drift_limit,
            severity_loss_cap_r=_number(value.get("severity_loss_cap_r", 2.0), "severity_loss_cap_r"),
            confidence_prior_alpha=_number(value.get("confidence_prior_alpha", 1.0), "confidence_prior_alpha"),
            confidence_prior_beta=_number(value.get("confidence_prior_beta", 1.0), "confidence_prior_beta"),
            deterministic_seed=int(value.get("deterministic_seed", 19)),
        )


def _normalize_rows(rows: Sequence[Mapping[str, Any]], taxonomy: Mapping[str, str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    required_dimensions = ("strategy_id", "symbol", "regime", "side")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _fail("ROW_OBJECT_REQUIRED", str(index))
        reason_code = str(row.get("reason_code", "UNKNOWN")).upper().strip() or "UNKNOWN"
        category = taxonomy.get(reason_code, "UNKNOWN")
        source_sha = str(row.get("source_sha", ""))
        feature_lineage_sha = str(row.get("feature_lineage_sha", ""))
        if len(source_sha) != 64 or len(feature_lineage_sha) != 64:
            _fail("SOURCE_OR_FEATURE_LINEAGE_SHA_INVALID", str(index))
        dimensions = {key: str(row.get(key, "UNKNOWN")).upper().strip() or "UNKNOWN" for key in required_dimensions}
        normalized.append({
            "event_id": str(row.get("event_id", "")),
            "event_ts": str(row.get("event_ts", "")),
            "parsed_ts": _timestamp(row.get("event_ts"), f"rows[{index}].event_ts"),
            "reason_code": reason_code,
            "category": category,
            "severity": _number(row.get("severity", 0.0), f"rows[{index}].severity"),
            "loss_r": _number(row.get("loss_r", 0.0), f"rows[{index}].loss_r"),
            "confidence": _number(row.get("confidence", 1.0), f"rows[{index}].confidence"),
            "source_sha": source_sha,
            "feature_lineage_sha": feature_lineage_sha,
            **dimensions,
        })
    if len({row["event_id"] for row in normalized}) != len(normalized):
        _fail("DUPLICATE_EVENT_ID")
    return sorted(normalized, key=lambda row: (row["parsed_ts"], row["event_id"]))


def _split(rows: list[dict[str, Any]], config: FailureLearningConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    training_cutoff = _timestamp(config.training_cutoff_ts, "training_cutoff_ts")
    evaluation_start = _timestamp(config.evaluation_start_ts, "evaluation_start_ts")
    train = [row for row in rows if row["parsed_ts"] <= training_cutoff]
    evaluation = [row for row in rows if row["parsed_ts"] >= evaluation_start]
    if len(train) < config.min_sample_count:
        _fail("TRAIN_SAMPLE_COUNT_LOW", str(len(train)))
    if len(evaluation) < config.min_sample_count:
        _fail("EVALUATION_SAMPLE_COUNT_LOW", str(len(evaluation)))
    if {row["event_id"] for row in train} & {row["event_id"] for row in evaluation}:
        _fail("TRAINING_EVALUATION_LEAKAGE")
    return train, evaluation


def fit_taxonomy(train: list[dict[str, Any]], config: FailureLearningConfig) -> dict[str, Any]:
    reason_counts = Counter(row["reason_code"] for row in train)
    category_counts = Counter(row["category"] for row in train)
    group_counts: Counter[tuple[str, str, str, str, str]] = Counter()
    severity_sum: defaultdict[tuple[str, str, str, str, str], float] = defaultdict(float)
    loss_sum: defaultdict[tuple[str, str, str, str, str], float] = defaultdict(float)
    for row in train:
        key = (row["strategy_id"], row["symbol"], row["regime"], row["side"], row["category"])
        group_counts[key] += 1
        severity_sum[key] += max(0.0, row["severity"])
        loss_sum[key] += min(config.severity_loss_cap_r, abs(min(0.0, row["loss_r"])))
    groups = []
    for key, sample_count in sorted(group_counts.items()):
        strategy_id, symbol, regime, side, category = key
        groups.append({
            "strategy_id": strategy_id,
            "symbol": symbol,
            "regime": regime,
            "side": side,
            "category": category,
            "sample_count": sample_count,
            "mean_severity": severity_sum[key] / sample_count,
            "mean_loss_r_abs": loss_sum[key] / sample_count,
            "eligible_for_hypothesis": sample_count >= config.min_group_sample_count,
        })
    return {
        "schema_version": MODEL_SCHEMA,
        "reason_code_counts": dict(sorted(reason_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "groups": groups,
        "training_sample_count": len(train),
        "deterministic_seed": config.deterministic_seed,
    }


def predict_recurrence(model: Mapping[str, Any], evaluation: list[dict[str, Any]], config: FailureLearningConfig) -> list[dict[str, Any]]:
    train_total = max(1, int(model["training_sample_count"]))
    train_categories = model["category_counts"]
    eval_counts = Counter(row["category"] for row in evaluation)
    all_categories = sorted(set(train_categories) | set(eval_counts))
    rows = []
    for category in all_categories:
        train_count = int(train_categories.get(category, 0))
        eval_count = int(eval_counts.get(category, 0))
        train_rate = train_count / train_total
        eval_rate = eval_count / len(evaluation)
        posterior = (eval_count + config.confidence_prior_alpha) / (
            len(evaluation) + config.confidence_prior_alpha + config.confidence_prior_beta
        )
        rows.append({
            "category": category,
            "training_rate": train_rate,
            "evaluation_rate": eval_rate,
            "recurrence_delta": eval_rate - train_rate,
            "confidence": posterior,
            "sample_count": eval_count,
        })
    return rows


def _group_hypotheses(model: Mapping[str, Any], evaluation: list[dict[str, Any]], config: FailureLearningConfig) -> list[dict[str, Any]]:
    eval_group_counts: Counter[tuple[str, str, str, str, str]] = Counter()
    eval_loss: defaultdict[tuple[str, str, str, str, str], float] = defaultdict(float)
    for row in evaluation:
        key = (row["strategy_id"], row["symbol"], row["regime"], row["side"], row["category"])
        eval_group_counts[key] += 1
        eval_loss[key] += min(config.severity_loss_cap_r, abs(min(0.0, row["loss_r"])))
    hypotheses = []
    for group in model["groups"]:
        key = (group["strategy_id"], group["symbol"], group["regime"], group["side"], group["category"])
        evaluation_count = eval_group_counts.get(key, 0)
        total = group["sample_count"] + evaluation_count
        if total < config.min_group_sample_count:
            continue
        confidence = (evaluation_count + config.confidence_prior_alpha) / (
            len(evaluation) + config.confidence_prior_alpha + config.confidence_prior_beta
        )
        severity_score = group["mean_severity"] + group["mean_loss_r_abs"] + (
            eval_loss.get(key, 0.0) / max(1, evaluation_count)
        )
        hypotheses.append({
            "strategy_id": group["strategy_id"],
            "symbol": group["symbol"],
            "regime": group["regime"],
            "side": group["side"],
            "category": group["category"],
            "sample_count": total,
            "training_count": group["sample_count"],
            "evaluation_count": evaluation_count,
            "severity_score": severity_score,
            "confidence": confidence,
            "hypothesis": f"OBSERVE_{group['category']}_RECURRENCE",
            "authority": "OBSERVATION_ONLY",
        })
    hypotheses.sort(key=lambda row: (-row["severity_score"], -row["sample_count"], row["strategy_id"], row["category"]))
    return hypotheses[:20]


def observe(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    config = FailureLearningConfig.from_mapping(payload.get("config", {}))
    taxonomy = dict(DEFAULT_TAXONOMY)
    supplied_taxonomy = payload.get("taxonomy", {})
    if not isinstance(supplied_taxonomy, Mapping):
        _fail("TAXONOMY_OBJECT_REQUIRED")
    for reason_code, category in supplied_taxonomy.items():
        taxonomy[str(reason_code).upper()] = str(category).upper()
    rows = _normalize_rows(payload.get("rows", []), taxonomy)
    train, evaluation = _split(rows, config)
    model = fit_taxonomy(train, config)
    recurrence = predict_recurrence(model, evaluation, config)
    hypotheses = _group_hypotheses(model, evaluation, config)
    unknown_count = sum(row["category"] == "UNKNOWN" for row in evaluation)
    unknown_rate = unknown_count / len(evaluation)
    max_recurrence_drift = max((abs(row["recurrence_delta"]) for row in recurrence), default=0.0)
    blockers: list[str] = []
    if unknown_rate > config.unknown_rate_limit:
        blockers.append("UNKNOWN_TAXONOMY_RATE_LIMIT")
    if max_recurrence_drift > config.recurrence_drift_limit:
        blockers.append("RECURRENCE_DRIFT_LIMIT")
    config_sha = canonical_sha(config.__dict__)
    training_data_sha = canonical_sha([{key: row[key] for key in (
        "event_id", "event_ts", "reason_code", "category", "severity", "loss_r", "confidence",
        "strategy_id", "symbol", "regime", "side", "source_sha", "feature_lineage_sha",
    )} for row in train])
    model_sha = canonical_sha(model)
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "observer_type": OBSERVER_TYPE,
        "state": "PASS_FAILURE_LEARNING_OBSERVATION" if not blockers else "HOLD_FAILURE_LEARNING_OBSERVATION",
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
        "taxonomy": dict(sorted(taxonomy.items())),
        "model": model,
        "recurrence": recurrence,
        "hypotheses": hypotheses,
        "calibration": {
            "confidence_prior_alpha": config.confidence_prior_alpha,
            "confidence_prior_beta": config.confidence_prior_beta,
            "unknown_rate": unknown_rate,
        },
        "drift": {"max_recurrence_delta_abs": max_recurrence_drift, "limit": config.recurrence_drift_limit},
        "leakage_check_pass": True,
        "rollback_plan": "DISCARD_TAXONOMY_MODEL_AND_OBSERVATIONS",
        "deterministic": True,
        "blocker_codes": blockers,
        "capabilities": list(CAPABILITIES),
        "requested_action": "hold" if blockers else "observer_burnin_only",
        **copy.deepcopy(SAFETY),
    }
    result["observer_manifest_sha"] = canonical_sha(result)
    return result
