from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.research.strategy11_failure_learning_observer_v1 import (
    FailureLearningObserverError,
    observe as observe_failure,
)
from backend.research.strategy11_ml_light_observer_optimized_v1 import (
    MLLightObserverError,
    observe as observe_ml,
)
from backend.tools.r7a4d_strategy11_ml_failure_observers_fixture_v1 import (
    valid_failure_input,
    valid_ml_input,
)

OUT = Path("artifacts/strategy11_ml_failure_observers_v1")


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
    assert ml["calibration"]["method"] == "PLATT_SCALING"
    assert ml["calibration"]["fit_scope"] == "TRAINING_HOLDOUT_ONLY"
    assert ml["calibration"]["evaluation_used_for_fit"] is False
    assert ml["fit_sample_count"] + ml["calibration_sample_count"] == ml["training_sample_count"]
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

    single_class_calibration = valid_ml_input()
    train_rows = [row for row in single_class_calibration["rows"] if row["event_id"].startswith("ml.train")]
    for row in train_rows[-48:]:
        row["label"] = 1
    calibration_class = expect_error(
        "ml_calibration_single_class", observe_ml, single_class_calibration, MLLightObserverError, "CALIBRATION_SPLIT_SINGLE_CLASS"
    )

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
    negatives = [ml_leakage, ml_low, calibration_class, failure_leakage, {"case": "unknown_taxonomy", "status": unknown["state"]}]
    (OUT / "negative_fixtures.json").write_text(json.dumps(negatives, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "state": "PASS_ML_FAILURE_OBSERVER_IMPLEMENTATIONS",
        "ml_state": ml["state"],
        "failure_state": failure["state"],
        "ml_calibration_method": ml["calibration"]["method"],
        "ml_fit_samples": ml["fit_sample_count"],
        "ml_calibration_samples": ml["calibration_sample_count"],
        "ml_evaluation_samples": ml["evaluation_sample_count"],
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
