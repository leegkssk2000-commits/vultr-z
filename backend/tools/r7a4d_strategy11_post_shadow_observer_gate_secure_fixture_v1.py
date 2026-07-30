from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_source_binding_contract_v1 import canonical_sha
from backend.research.strategy11_failure_learning_observer_v1 import observe as observe_failure
from backend.research.strategy11_ml_light_observer_optimized_v1 import observe as observe_ml
from backend.research.strategy11_post_shadow_observer_gate_v1 import (
    CYCLE_SCHEMA,
    OBSERVER_SAFETY,
    PostShadowObserverGateError,
    evaluate_gate,
    expected_ledger_head,
    ledger_genesis,
    load_trusted_policy,
    trusted_policy_sha,
)
from backend.research.strategy11_shadow300_readonly_completion_v1 import complete
from backend.tools.r7a4d_strategy11_ml_failure_observers_fixture_v1 import valid_failure_input, valid_ml_input
from backend.tools.r7a4d_strategy11_shadow300_readonly_completion_fixture_v1 import valid_input as valid_shadow300_input

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


def receipt(
    cycle: int,
    previous_head: str,
    shadow: dict,
    ml: dict,
    failure: dict,
    observer_bundle_sha: str,
) -> dict:
    observer_input_sha = canonical_sha({"kind": "observer-input", "cycle": cycle})
    source_head = expected_ledger_head(previous_head, cycle, observer_input_sha)
    value = {
        "schema_version": CYCLE_SCHEMA,
        "cycle": cycle,
        "previous_source_ledger_head_sha": previous_head,
        "source_ledger_head_sha": source_head,
        "observer_input_sha": observer_input_sha,
        "shadow300_completion_sha": shadow["completion_sha"],
        "selected_combination_sha": shadow["selected_combination_sha"],
        "target_weights_sha": shadow["target_weights_sha"],
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
    ml = observe_ml(valid_ml_input())
    failure = observe_failure(valid_failure_input())
    assert shadow["state"] == "PASS_SHADOW300_READ_ONLY_COMPLETION"
    assert ml["state"] == "PASS_ML_LIGHT_OBSERVATION", ml["blocker_codes"]
    assert failure["state"] == "PASS_FAILURE_LEARNING_OBSERVATION", failure["blocker_codes"]
    policy = load_trusted_policy()
    policy_sha = trusted_policy_sha()
    observer_bundle_sha = canonical_sha(
        {
            "shadow300_completion_sha": shadow["completion_sha"],
            "ml_manifest_sha": ml["observer_manifest_sha"],
            "failure_manifest_sha": failure["observer_manifest_sha"],
            "policy_sha": policy_sha,
        }
    )
    previous_head = ledger_genesis(shadow["completion_sha"])
    cycles: list[dict] = []
    for cycle in range(301, 401):
        row = receipt(cycle, previous_head, shadow, ml, failure, observer_bundle_sha)
        cycles.append(row)
        previous_head = row["source_ledger_head_sha"]
    return {
        "schema_version": "strategy11.post_shadow_observer_gate.input.v1",
        "shadow300": shadow,
        "ml_observation": ml,
        "failure_observation": failure,
        "burnin_cycles": cycles,
        "policy": policy,
        "policy_sha": policy_sha,
        "authority": copy.deepcopy(OBSERVER_SAFETY),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = fixture_input()
    passed = evaluate_gate(payload)
    assert passed["state"] == "PASS_POST_SHADOW_OBSERVER_100C_STRUCTURAL_GATE"
    assert passed["trusted_policy_sha"] == payload["policy_sha"]
    assert passed["policy_class"] == "FIXTURE_ONLY"
    assert passed["production_threshold_authority"] is False
    assert passed["burnin_cycle_count"] == 100
    assert passed["burnin_start_cycle"] == 301
    assert passed["burnin_end_cycle"] == 400
    assert passed["ledger_chain_verified"] is True
    assert passed["ledger_final_head_sha"] == payload["burnin_cycles"][-1]["source_ledger_head_sha"]
    assert passed["paper_30d_structural_gate_pass"] is True
    assert passed["paper_30d_allowed"] is False
    assert passed["automatic_paper_start"] is False
    assert passed["next"] == "WAIT_PRODUCTION_POLICY_AND_REAL_100C"
    for key, expected in OBSERVER_SAFETY.items():
        assert passed[key] == expected

    incomplete_payload = fixture_input()
    incomplete_payload["burnin_cycles"] = incomplete_payload["burnin_cycles"][:-1]
    incomplete = evaluate_gate(incomplete_payload)
    assert incomplete["state"] == "HOLD_POST_SHADOW_OBSERVER_100C"
    assert "BURNIN_CYCLE_COUNT_NOT_100" in incomplete["blocker_codes"]
    assert incomplete["paper_30d_structural_gate_pass"] is False

    policy_tamper = fixture_input()
    policy_tamper["policy"]["max_ml_ece"] = 1.0
    policy_tamper["policy_sha"] = canonical_sha(policy_tamper["policy"])
    expect_failure("TRUSTED_POLICY_BINDING_MISMATCH", lambda: evaluate_gate(policy_tamper))

    chain_tamper = fixture_input()
    chain_tamper["burnin_cycles"][50]["previous_source_ledger_head_sha"] = "f" * 64
    chain_tamper["burnin_cycles"][50]["source_ledger_head_sha"] = expected_ledger_head(
        "f" * 64,
        chain_tamper["burnin_cycles"][50]["cycle"],
        chain_tamper["burnin_cycles"][50]["observer_input_sha"],
    )
    reseal(chain_tamper["burnin_cycles"][50])
    expect_failure("BURNIN_PREVIOUS_LEDGER_HEAD_MISMATCH", lambda: evaluate_gate(chain_tamper))

    head_tamper = fixture_input()
    head_tamper["burnin_cycles"][5]["source_ledger_head_sha"] = "e" * 64
    reseal(head_tamper["burnin_cycles"][5])
    expect_failure("BURNIN_LEDGER_HEAD_CHAIN_MISMATCH", lambda: evaluate_gate(head_tamper))

    mutation_payload = fixture_input()
    mutation_payload["burnin_cycles"][10]["strategy_mutation_count"] = 1
    reseal(mutation_payload["burnin_cycles"][10])
    blocked = evaluate_gate(mutation_payload)
    assert blocked["state"] == "BLOCK_POST_SHADOW_OBSERVER_MUTATION"
    assert "STRATEGY_MUTATION_COUNT" in blocked["blocker_codes"]
    assert blocked["paper_30d_allowed"] is False

    observer_tamper = fixture_input()
    observer_tamper["ml_observation"]["calibration"]["brier_score"] = 0.999
    expect_failure("OBSERVER_MANIFEST_SHA_MISMATCH", lambda: evaluate_gate(observer_tamper))

    (OUT / "input.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "pass_structural.json").write_text(json.dumps(passed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold_incomplete.json").write_text(json.dumps(incomplete, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "block_mutation.json").write_text(json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "state": "PASS_POST_SHADOW_OBSERVER_GATE_HARDENED_FIXTURE",
        "gate_sha": passed["gate_sha"],
        "trusted_policy_sha": passed["trusted_policy_sha"],
        "ledger_chain_verified": passed["ledger_chain_verified"],
        "paper_30d_structural_gate_pass": True,
        "paper_30d_allowed": False,
        "fixture_only": True,
        "production_authority": False,
        **OBSERVER_SAFETY,
    }
    (OUT / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
