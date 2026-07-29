from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.research.strategy11_failure_learning_observer_v1 import (
    FailureLearningObserverError,
    INPUT_SCHEMA as FAILURE_INPUT_SCHEMA,
    observe as observe_failure,
)
from backend.research.strategy11_ml_light_observer_v1 import (
    INPUT_SCHEMA as ML_INPUT_SCHEMA,
    MLLightObserverError,
    observe as observe_ml,
)

OUT = Path("artifacts/strategy11_ml_failure_observers_v1")
HEX = "a" * 64
LINEAGE = "b" * 64


def ml_rows() -> list[dict]:
    rows = []
    train_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    evaluation_start = datetime(2026, 8, 15, tzinfo=timezone.utc)
    for index in range(240):
        phase = index % 24
        x1 = math.sin(phase / 24 * math.tau)
        x2 = math.cos(phase / 24 * math.tau)
        x3 = ((index % 11) - 5) / 5
        x4 = (index % 7) / 10
        score = 1.4 * x1 + 0.8 * x2 - 0.6 * x3 - 0.4 * x4
        rows.append({
            "event_id": f"ml.train.{index:03d}",
            "event_ts": (train_start + timedelta(minutes=15 * index)).isoformat(),
            "features": {"momentum": x1, "trend": x2, "volatility": x3, "cost": x4},
            "label": int(score > 0),
            "source_sha": HEX,
            "feature_lineage_sha": LINEAGE,
        })
    for index in range(120):
        phase = index % 24
        x1 = math.sin(phase / 24 * math.tau)
        x2 = math.cos(phase / 24 * math.tau)
        x3 = ((index % 11) - 5) / 5
        x4 = (index % 7) / 10
        score = 1.4 * x1 + 0.8 * x2 - 0.6 * x3 - 0.4 * x4
        rows.append({
            "event_id": f"ml.eval.{index:03d}",
            "event_ts": (evaluation_start + timedelta(minutes=15 * index)).isoformat(),
            "features": {"momentum": x1, "trend": x2, "volatility": x3, "cost": x4},
            "label": int(score > 0),
            "source_sha": HEX,
            "feature_lineage_sha": LINEAGE,
        })
    return rows


def valid_ml_input() -> dict:
    return {
        "schema_version": ML_INPUT_SCHEMA,
        "config": {
            "feature_order": ["momentum", "trend", "volatility", "cost"],
            "training_cutoff_ts": "2026-07-01T23:59:59Z",
            "evaluation_start_ts": "2026-08-15T00:00:00Z",
            "max_iter": 300,
            "learning_rate": 0.05,
            "regularization_l2": 0.02,
            "seed": 17,
            "min_train_samples": 200,
            "min_evaluation_samples": 100,
            "calibration_bins": 10,
            "brier_limit": 0.25,
            "ece_limit": 0.12,
            "drift_psi_limit": 0.25
        },
        "rows": ml_rows(),
    }


def failure_rows() -> list[dict]:
    rows = []
    train_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    evaluation_start = datetime(2026, 8, 15, tzinfo=timezone.utc)
    reasons = ["NO_SIGNAL", "CONTEXT_GATE_BLOCK", "REGIME_MISMATCH", "LOSS_SHAPE", "GIVEBACK"]
    strategies = ["trend_ma_macd", "bb_revert", "break_and_continue"]
    for scope, count, start in (("train", 80, train_start), ("eval", 40, evaluation_start)):
        for index in range(count):
            reason = reasons[index % len(reasons)]
            rows.append({
                "event_id": f"failure.{scope}.{index:03d}",
                "event_ts": (start + timedelta(minutes=15 * index)).isoformat(),
                "reason_code": reason,
                "severity": 0.2 + (index % 5) * 0.1,
                "loss_r": -0.2 - (index % 4) * 0.1,
                "confidence": 0.8,
                "strategy_id": strategies[index % len(strategies)],
                "symbol": "BTCUSDT" if index % 2 == 0 else "ETHUSDT",
                "regime": "UPTREND" if index % 3 else "RANGE",
                "side": "LONG",
                "source_sha": HEX,
                "feature_lineage_sha": LINEAGE,
            })
    return rows


def valid_failure_input() -> dict:
    return {
        "schema_version": FAILURE_INPUT_SCHEMA,
        "config": {
            "training_cutoff_ts": "2026-07-01T23:59:59Z",
            "evaluation_start_ts": "2026-08-15T00:00:00Z",
            "min_sample_count": 20,
            "min_group_sample_count": 3,
            "unknown_rate_limit": 0.05,
            "recurrence_drift_limit": 0.30,
            "severity_loss_cap_r": 2.0,
            "confidence_prior_alpha": 1.0,
            "confidence_prior_beta": 1.0,
            "deterministic_seed": 19
        },
        "taxonomy": {},
        "rows": failure_rows(),
    }


def expect_error(name: str, fn, payload: dict, error_type, code: str) -> dict:
    try:
        fn(payload)
    except error_type as exc:
        assert code in str(exc), (name, code, str(exc))
        return {"case": name, "status": "PASS_REJECTED", "expected_code": code, "error": str(exc)}
    raise AssertionError(f"{name}: expected {code}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ml = observe_ml(valid_ml_input())
    failure = observe_failure(valid_failure_input())
    assert ml["state"] == "PASS_ML_LIGHT_OBSERVATION", ml["blocker_codes"]
    assert failure["state"] == "PASS_FAILURE_LEARNING_OBSERVATION", failure["blocker_codes"]
    for result in (ml, failure):
        assert result["observer_only"] is True
        assert result["research_only"] is True
        assert result["promotion_authority"] is False
        assert result["protected_mutations"] == 0
        assert result["execution_allowed"] is False
        assert result["order_authority"] == "BLOCKED"
        assert result["runtime_bound"] is False
        assert result["advisory_enabled"] is False
        assert result["leakage_check_pass"] is True

    leakage_ml = valid_ml_input()
    leakage_ml["config"]["training_cutoff_ts"] = "2026-09-01T00:00:00Z"
    ml_leakage = expect_error("ml_time_leakage", observe_ml, leakage_ml, MLLightObserverError, "TRAINING_EVALUATION_LEAKAGE")

    low_sample_ml = valid_ml_input()
    low_sample_ml["rows"] = low_sample_ml["rows"][:50]
    ml_low = expect_error("ml_low_sample", observe_ml, low_sample_ml, MLLightObserverError, "TRAIN_SAMPLE_COUNT_LOW")

    leakage_failure = valid_failure_input()
    leakage_failure["config"]["training_cutoff_ts"] = "2026-09-01T00:00:00Z"
    failure_leakage = expect_error(
        "failure_time_leakage", observe_failure, leakage_failure, FailureLearningObserverError, "TRAINING_EVALUATION_LEAKAGE"
    )

    unknown_failure = valid_failure_input()
    for row in unknown_failure["rows"]:
        if row["event_id"].startswith("failure.eval"):
            row["reason_code"] = "UNMAPPED_NEW_REASON"
    unknown = observe_failure(unknown_failure)
    assert unknown["state"] == "HOLD_FAILURE_LEARNING_OBSERVATION"
    assert "UNKNOWN_TAXONOMY_RATE_LIMIT" in unknown["blocker_codes"]

    (OUT / "ml_light_pass.json").write_text(json.dumps(ml, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "failure_learning_pass.json").write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    negatives = [ml_leakage, ml_low, failure_leakage, {"case": "unknown_taxonomy", "status": unknown["state"]}]
    (OUT / "negative_fixtures.json").write_text(json.dumps(negatives, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "state": "PASS_ML_FAILURE_OBSERVER_IMPLEMENTATIONS",
        "ml_state": ml["state"],
        "failure_state": failure["state"],
        "ml_brier": ml["calibration"]["brier_score"],
        "ml_ece": ml["calibration"]["ece_score"],
        "ml_auc": ml["discrimination"]["auc_score"],
        "ml_drift_psi": ml["drift"]["max_feature_psi"],
        "failure_unknown_rate": failure["calibration"]["unknown_rate"],
        "failure_hypothesis_count": len(failure["hypotheses"]),
        "observer_only": True,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
        "advisory_enabled": False,
        "automatic_activation": False,
        "next": "REAL_POST_SHADOW300_SOURCE_BINDING_AND_100C_BURNIN",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
