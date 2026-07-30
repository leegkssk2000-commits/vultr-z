from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_source_binding_contract_v1 import canonical_sha
from backend.research.strategy11_failure_learning_observer_v1 import observe as observe_failure
from backend.research.strategy11_ml_light_observer_v1 import observe as observe_ml
from backend.research.strategy11_post_shadow_observer_gate_v1 import (
    OBSERVER_SAFETY,
    PostShadowObserverGateError,
    evaluate_gate,
)
from backend.research.strategy11_shadow300_readonly_completion_v1 import complete
from backend.tools.r7a4d_strategy11_ml_failure_observers_fixture_v1 import (
    valid_failure_input,
    valid_ml_input,
)
from backend.tools.r7a4d_strategy11_shadow300_readonly_completion_fixture_v1 import (
    valid_input as valid_shadow300_input,
)


OUT = Path("artifacts/strategy11_post_shadow_observer_gate_v1")


def expect_failure(code: str, fn) -> str:
    try:
        fn()
    except PostShadowObserverGateError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def policy() -> dict:
    return {
        "policy_id": "FIXTURE_POST_SHADOW_OBSERVER_100C_POLICY_NOT_PRODUCTION_AUTHORITY",
        "required_burnin_cycles": 100,
        "first_burnin_cycle": 301,
        "min_ml_evaluation_samples": 100,
        "min_failure_evaluation_samples": 20,
        "max_ml_brier": 0.25,
        "max_ml_ece": 0.12,
        "min_ml_auc": 0.50,
        "max_ml_feature_psi": 0.25,
        "max_failure_unknown_rate": 0.05,
        "max_failure_recurrence_drift": 0.30,
        "max_hold_requested_cycles": 0,
        "error_budget_limit": 20,
        "max_error_budget_ratio": 0.20,
    }


def receipt(
    cycle: int,
    shadow: dict,
    ml: dict,
    failure: dict,
    observer_bundle_sha: str,
) -> dict:
    value = {
        "schema_version": "strategy11.post_shadow_observer_cycle.v1",
        "cycle": cycle,
        "shadow300_completion_sha": shadow["completion_sha"],
        "selected_combination_sha": shadow["selected_combination_sha"],
        "target_weights_sha": shadow["target_weights_sha"],
        "source_ledger_head_sha": canonical_sha({"kind": "source-ledger-head", "cycle": cycle}),
        "observer_input_sha": canonical_sha({"kind": "observer-input", "cycle": cycle}),
        "observer_bundle_sha": observer_bundle_sha,
        "ml_manifest_sha": ml["observer_manifest_sha"],
        "failure_manifest_sha": failure["observer_manifest_sha"],
        "state_mutation_count": 0,
        "strategy_mutation_count": 0,
        "weight_mutation_count": 0,
        "ledger_mutation_count": 0,
        "paper_live_mutation_count": 0,
        "order_attempt_count": 0,
        "hold_requested": False,
        "error_budget_used": 0,
        "authority": copy.deepcopy(OBSERVER_SAFETY),
    }
    value["receipt_sha"] = canonical_sha(value)
    return value


def reseal(value: dict) -> None:
    value.pop("receipt_sha", None)
    value["receipt_sha"] = canonical_sha(value)


def fixture_input() -> dict:
    shadow = complete(valid_shadow300_input())
    assert shadow["state"] == "PASS_SHADOW300_READ_ONLY_COMPLETION"
    ml = observe_ml(valid_ml_input())
    assert ml["state"] == "PASS_ML_LIGHT_OBSERVATION"
    failure = observe_failure(valid_failure_input())
    assert failure["state"] == "PASS_FAILURE_LEARNING_OBSERVATION"
    observer_bundle_sha = canonical_sha(
        {
            "shadow300_completion_sha": shadow["completion_sha"],
            "ml_manifest_sha": ml["observer_manifest_sha"],
            "failure_manifest_sha": failure["observer_manifest_sha"],
        }
    )
    cycles = [receipt(cycle, shadow, ml, failure, observer_bundle_sha) for cycle in range(301, 401)]
    return {
        "schema_version": "strategy11.post_shadow_observer_gate.input.v1",
        "shadow300": shadow,
        "ml_observation": ml,
        "failure_observation": failure,
        "burnin_cycles": cycles,
        "policy": policy(),
        "authority": copy.deepcopy(OBSERVER_SAFETY),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    payload = fixture_input()
    passed = evaluate_gate(payload)
    assert passed["state"] == "PASS_POST_SHADOW_OBSERVER_100C_GATE"
    assert passed["burnin_cycle_count"] == 100
    assert passed["burnin_start_cycle"] == 301
    assert passed["burnin_end_cycle"] == 400
    assert passed["ml_failure_readonly_bridge_allowed"] is True
    assert passed["paper_30d_allowed"] is True
    assert passed["automatic_paper_start"] is False
    assert passed["strategy_write_allowed"] is False
    assert passed["weight_write_allowed"] is False
    assert passed["ledger_write_allowed"] is False
    assert passed["live_order_allowed"] is False
    assert passed["next"] == "30D_PAPER_CANARY_MANUAL_START"
    for key, expected in OBSERVER_SAFETY.items():
        assert passed[key] == expected

    incomplete_payload = fixture_input()
    incomplete_payload["burnin_cycles"] = incomplete_payload["burnin_cycles"][:-1]
    incomplete = evaluate_gate(incomplete_payload)
    assert incomplete["state"] == "HOLD_POST_SHADOW_OBSERVER_100C"
    assert incomplete["burnin_cycle_count"] == 99
    assert incomplete["paper_30d_allowed"] is False
    assert "BURNIN_CYCLE_COUNT_NOT_100" in incomplete["blocker_codes"]

    gap_payload = fixture_input()
    del gap_payload["burnin_cycles"][49]
    expect_failure("BURNIN_CYCLE_GAP_OR_REORDER", lambda: evaluate_gate(gap_payload))

    mutation_payload = fixture_input()
    mutation_payload["burnin_cycles"][10]["strategy_mutation_count"] = 1
    reseal(mutation_payload["burnin_cycles"][10])
    blocked = evaluate_gate(mutation_payload)
    assert blocked["state"] == "BLOCK_POST_SHADOW_OBSERVER_MUTATION"
    assert blocked["paper_30d_allowed"] is False
    assert "STRATEGY_MUTATION_COUNT" in blocked["blocker_codes"]

    metric_payload = fixture_input()
    actual_brier = metric_payload["ml_observation"]["calibration"]["brier_score"]
    assert actual_brier > 0.0
    metric_payload["policy"]["max_ml_brier"] = max(0.0, actual_brier / 2.0)
    metric_hold = evaluate_gate(metric_payload)
    assert metric_hold["state"] == "HOLD_POST_SHADOW_OBSERVER_100C"
    assert metric_hold["paper_30d_allowed"] is False
    assert "ML_BRIER_BREACH" in metric_hold["blocker_codes"]

    observer_tamper = fixture_input()
    observer_tamper["ml_observation"]["calibration"]["brier_score"] = 0.999
    expect_failure("OBSERVER_MANIFEST_SHA_MISMATCH", lambda: evaluate_gate(observer_tamper))

    receipt_binding = fixture_input()
    receipt_binding["burnin_cycles"][0]["ml_manifest_sha"] = "f" * 64
    reseal(receipt_binding["burnin_cycles"][0])
    expect_failure("BURNIN_ML_MANIFEST_MISMATCH", lambda: evaluate_gate(receipt_binding))

    (OUT / "input.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "pass.json").write_text(json.dumps(passed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold_incomplete.json").write_text(json.dumps(incomplete, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "block_mutation.json").write_text(json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold_metric.json").write_text(json.dumps(metric_hold, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "state": "PASS_POST_SHADOW_OBSERVER_GATE_FIXTURE",
        "gate_sha": passed["gate_sha"],
        "burnin_cycle_count": passed["burnin_cycle_count"],
        "paper_30d_allowed_fixture": passed["paper_30d_allowed"],
        "automatic_paper_start": passed["automatic_paper_start"],
        "fixture_only": True,
        "production_authority": False,
        **OBSERVER_SAFETY,
    }
    (OUT / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
