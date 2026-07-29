from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.research.strategy11_observer_only_gate_v1 import (
    INPUT_SCHEMA,
    ObserverOnlyGateError,
    evaluate,
)
from backend.research.strategy11_shadow300_readonly_completion_v1 import complete
from backend.tools.r7a4d_strategy11_shadow300_readonly_completion_fixture_v1 import valid_input as valid_shadow300_input

OUT = Path("artifacts/strategy11_observer_only_gate_v1")
AUTHORITY = {**SAFETY, "runtime_bound": False}


def shadow300() -> dict:
    result = complete(valid_shadow300_input())
    assert result["state"] == "PASS_SHADOW300_READ_ONLY_COMPLETION"
    return result


def observer(observer_type: str, suffix: str) -> dict:
    return {
        "observer_id": f"{observer_type.lower()}.observer.v1",
        "observer_type": observer_type,
        "source_sha": ("1" if suffix == "ml" else "2") * 64,
        "model_sha": ("3" if suffix == "ml" else "4") * 64,
        "config_sha": ("5" if suffix == "ml" else "6") * 64,
        "training_data_sha": ("7" if suffix == "ml" else "8") * 64,
        "feature_lineage_sha": ("9" if suffix == "ml" else "a") * 64,
        "output_schema_sha": ("b" if suffix == "ml" else "c") * 64,
        "training_cutoff_ts": "2026-07-01T00:00:00Z",
        "evaluation_start_ts": "2026-08-15T00:00:00Z",
        "calibration_sample_count": 240,
        "leakage_check_pass": True,
        "drift_baseline_pass": True,
        "calibration_baseline_pass": True,
        "attribution_plan_pass": True,
        "rollback_plan_pass": True,
        "offline_fixture_pass": True,
        "reads_existing_sealed": False,
        "advisory_enabled": False,
        "runtime_bound": False,
        "capabilities": ["READ_EVIDENCE", "EMIT_OBSERVATION", "EMIT_CALIBRATION", "REQUEST_HOLD"],
        "authority": copy.deepcopy(AUTHORITY),
    }


def valid_input() -> dict:
    return {
        "schema_version": INPUT_SCHEMA,
        "shadow300": shadow300(),
        "observers": [observer("ML_LIGHT", "ml"), observer("FAILURE_LEARNING", "failure")],
        "policy": {
            "policy_id": "FIXTURE_OBSERVER_ONLY_POLICY_NOT_PRODUCTION_AUTHORITY",
            "min_calibration_samples": 200,
            "required_observer_burnin_cycles": 100,
        },
        "authority": copy.deepcopy(AUTHORITY),
    }


def expect_error(name: str, payload: dict, code: str) -> dict:
    try:
        evaluate(payload)
    except ObserverOnlyGateError as exc:
        assert code in str(exc), (name, code, str(exc))
        return {"case": name, "status": "PASS_REJECTED", "expected_code": code, "error": str(exc)}
    raise AssertionError(f"{name}: expected {code}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    passed = evaluate(valid_input())
    assert passed["state"] == "PASS_OBSERVER_ONLY_GATE"
    assert passed["observer_count"] == 2
    assert passed["observer_burnin_allowed"] is True
    assert passed["observer_advisory_allowed"] is False
    assert passed["strategy_input_allowed"] is False
    assert passed["portfolio_weight_input_allowed"] is False
    assert passed["paper_30d_allowed"] is False

    incomplete_payload = valid_input()
    incomplete_payload["observers"] = incomplete_payload["observers"][:1]
    incomplete = evaluate(incomplete_payload)
    assert incomplete["state"] == "HOLD_OBSERVER_ONLY_GATE_INCOMPLETE"

    advisory_payload = valid_input()
    advisory_payload["observers"][0]["advisory_enabled"] = True
    advisory = expect_error("premature_advisory", advisory_payload, "OBSERVER_ADVISORY_PREMATURE")

    leakage_payload = valid_input()
    leakage_payload["observers"][1]["training_cutoff_ts"] = "2026-09-01T00:00:00Z"
    leakage = expect_error("training_leakage", leakage_payload, "TRAINING_EVALUATION_LEAKAGE")

    capability_payload = valid_input()
    capability_payload["observers"][0]["capabilities"].append("WRITE_WEIGHT")
    capability = expect_error("forbidden_capability", capability_payload, "OBSERVER_FORBIDDEN_CAPABILITY")

    sealed_payload = valid_input()
    sealed_payload["observers"][1]["reads_existing_sealed"] = True
    sealed = expect_error("existing_sealed_read", sealed_payload, "EXISTING_SEALED_READ_FORBIDDEN")

    shadow_payload = valid_input()
    shadow_payload["shadow300"]["selected_combination_sha"] = "f" * 64
    shadow = expect_error("shadow300_tamper", shadow_payload, "SHADOW300_SHA_MISMATCH")

    (OUT / "pass.json").write_text(json.dumps(passed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold_incomplete.json").write_text(json.dumps(incomplete, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    negatives = [advisory, leakage, capability, sealed, shadow]
    (OUT / "negative_fixtures.json").write_text(json.dumps(negatives, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "state": "PASS_OBSERVER_ONLY_GATE_FIXTURES",
        "pass_state": passed["state"],
        "hold_state": incomplete["state"],
        "observer_count": passed["observer_count"],
        "negative_fixture_count": len(negatives),
        "observer_burnin_allowed_fixture": True,
        "observer_advisory_allowed": False,
        "strategy_input_allowed": False,
        "portfolio_weight_input_allowed": False,
        "paper_30d_allowed": False,
        "automatic_activation": False,
        "runtime_bound": False,
        "production_threshold_authority": False,
        "next": "OBSERVER_ONLY_BURNIN_THEN_30D_PAPER_CANARY_GATE",
        **SAFETY,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
