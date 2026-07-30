from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.research.strategy11_failure_learning_observer_v1 import observe as observe_failure
from backend.research.strategy11_ml_light_observer_optimized_v1 import observe as observe_ml
from backend.research.strategy11_post_shadow_observer_gate_v1 import (
    OBSERVER_SAFETY,
    evaluate_gate,
    ledger_genesis,
    load_trusted_policy,
    trusted_policy_sha,
)
from backend.research.strategy11_shadow20_readonly_canary_v1 import evaluate as evaluate_shadow20
from backend.research.strategy11_shadow200_readonly_accumulator_v1 import (
    INPUT_SCHEMA as SHADOW200_INPUT_SCHEMA,
    accumulate,
)
from backend.research.strategy11_shadow300_readonly_completion_v1 import (
    INPUT_SCHEMA as SHADOW300_INPUT_SCHEMA,
    complete,
)
from backend.research.strategy11_synthesis_classifier_adapter_v1 import adapt_and_classify
from backend.research.strategy11_synthesis_portfolio_integration_v1 import integrate
from backend.research.strategy11_synthesis_sealer_v1 import seal_synthesis
from backend.tools import r7a4d_strategy11_shadow20_readonly_canary_fixture_v1 as shadow20_fixture
from backend.tools import r7a4d_strategy11_shadow200_readonly_accumulator_fixture_v1 as shadow200_fixture
from backend.tools import r7a4d_strategy11_shadow300_readonly_completion_fixture_v1 as shadow300_fixture
from backend.tools import r7a4d_strategy11_synthesis_classifier_adapter_fixture_v1 as adapter_fixture
from backend.tools import r7a4d_strategy11_synthesis_portfolio_integration_fixture_v1_1 as portfolio_fixture
from backend.tools import r7a4d_strategy11_synthesis_sealer_fixture_v1 as sealer_fixture
from backend.tools.r7a4d_strategy11_ml_failure_observers_fixture_v1 import valid_failure_input, valid_ml_input
from backend.tools.r7a4d_strategy11_post_shadow_observer_gate_secure_fixture_v1 import receipt as observer_receipt

OUT = Path("artifacts/strategy11_organic_e2e_receipt_v1")
AUTHORITY = {**SAFETY, "runtime_bound": False}


class OrganicChainError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise OrganicChainError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower()):
        _fail("SHA256_REQUIRED", name)
    return value.lower()


def _stage_receipt(stage: str, state: str, artifact_sha: str, parent_artifact_sha: str | None, previous_receipt_sha: str) -> dict[str, Any]:
    value = {
        "schema_version": "strategy11.organic_stage_receipt.v1",
        "stage": stage,
        "state": state,
        "artifact_sha": _sha(artifact_sha, f"{stage}.artifact_sha"),
        "parent_artifact_sha": _sha(parent_artifact_sha, f"{stage}.parent_artifact_sha") if parent_artifact_sha else None,
        "previous_receipt_sha": _sha(previous_receipt_sha, f"{stage}.previous_receipt_sha"),
        "authority": copy.deepcopy(AUTHORITY),
    }
    value["receipt_sha"] = canonical_sha(value)
    return value


def validate_receipt_chain(receipts: list[Mapping[str, Any]]) -> str:
    previous = canonical_sha({"kind": "STRATEGY11_ORGANIC_RECEIPT_GENESIS"})
    parent_artifact: str | None = None
    for index, raw in enumerate(receipts):
        row = _mapping(raw, f"receipts[{index}]")
        supplied = _sha(row.get("receipt_sha"), f"receipts[{index}].receipt_sha")
        computed = canonical_sha({key: child for key, child in row.items() if key != "receipt_sha"})
        if supplied != computed:
            _fail("ORGANIC_RECEIPT_SHA_MISMATCH", str(index))
        if row.get("previous_receipt_sha") != previous:
            _fail("ORGANIC_RECEIPT_PREVIOUS_SHA_MISMATCH", str(index))
        if index > 0 and row.get("parent_artifact_sha") != parent_artifact:
            _fail("ORGANIC_RECEIPT_PARENT_ARTIFACT_MISMATCH", str(index))
        previous = supplied
        parent_artifact = _sha(row.get("artifact_sha"), f"receipts[{index}].artifact_sha")
    return previous


def build_synthesis_chain() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    sealer_input = sealer_fixture.fixture_input()
    sealer_result = seal_synthesis(sealer_input)
    if sealer_result.get("state") != "PASS_SYNTHESIS_NEW_SEALED_WAIT_CLASSIFIER":
        _fail("SEALER_NOT_PASS", str(sealer_result.get("state")))

    adapter_input = adapter_fixture.fixture_input()
    adapter_input["sealer_input"] = copy.deepcopy(sealer_input)
    adapter_input["sealer_result"] = copy.deepcopy(sealer_result)
    adapter_result = adapt_and_classify(adapter_input)
    if adapter_result.get("state") != "PASS_SYNTHESIS_CLASSIFIER_ADAPTER":
        _fail("ADAPTER_NOT_PASS", str(adapter_result.get("state")))
    if adapter_result.get("synthesis_seal_sha") != sealer_result["synthesis_seal"]["seal_sha"]:
        _fail("SEALER_ADAPTER_SHA_MISMATCH")

    synthesis_package = portfolio_fixture.package(
        adapter_result["proposal"],
        adapter_result["classification"],
        adapter_result["source_ledger"],
        portfolio_fixture.sealed_material(
            adapter_result["strategy_id"],
            adapter_result["proposal"],
            adapter_result["classification"],
            net=4.2,
            confidence=0.82,
            uncertainty=0.18,
            dd=2.4,
            joint=3.5,
            cost=0.09,
            capacity=0.90,
            incumbent=0.50,
        ),
    )
    core_package = portfolio_fixture.core_package()
    portfolio_input = {
        "schema_version": "strategy11.synthesis_portfolio_integration.input.v1",
        "candidate_packages": [synthesis_package, core_package],
        "correlation_policy": portfolio_fixture.correlation_policy(),
        "governor_policy": portfolio_fixture.governor_policy(),
        "authority": dict(SAFETY),
    }
    portfolio_result = integrate(portfolio_input)
    if portfolio_result.get("state") != "PASS_SYNTHESIS_PORTFOLIO_INTEGRATION":
        _fail("PORTFOLIO_NOT_PASS", str(portfolio_result.get("state")))
    if adapter_result["strategy_id"] not in portfolio_result.get("selected_synthesis_members", []):
        _fail("PORTFOLIO_SELECTED_SYNTHESIS_MISSING")
    return sealer_result, adapter_result, portfolio_result, core_package


def _shared_lineage(adapter_result: Mapping[str, Any]) -> dict[str, Any]:
    proposal = _mapping(adapter_result.get("proposal"), "adapter_result.proposal")
    lineage = _mapping(proposal.get("lineage"), "adapter_result.proposal.lineage")
    evidence = _mapping(adapter_result.get("classifier_evidence"), "adapter_result.classifier_evidence")
    return {
        "source_w1_run_id": str(lineage["run_id"]),
        "source_w1_manifest_sha": _sha(lineage["source_manifest_sha"], "lineage.source_manifest_sha"),
        "data_sha": _sha(lineage["data_sha"], "lineage.data_sha"),
        "window_sha": _sha(lineage["window_sha"], "lineage.window_sha"),
        "evidence_manifest_sha": _sha(evidence["evidence_manifest_sha"], "evidence.evidence_manifest_sha"),
    }


def _build_shadow20_input(
    adapter_result: Mapping[str, Any],
    portfolio_result: Mapping[str, Any],
    core_package: Mapping[str, Any],
) -> dict[str, Any]:
    selected = list(portfolio_result["selected_members"])
    weights = dict(portfolio_result["governor_result"]["target_risk_weights"])
    combination_sha = _sha(portfolio_result["candidate_set_sha"], "portfolio.candidate_set_sha")
    lineage = _shared_lineage(adapter_result)
    synthesis_id = str(adapter_result["strategy_id"])
    core_proposal = _mapping(core_package.get("proposal"), "core_package.proposal")
    core_classification = _mapping(core_package.get("classification"), "core_package.classification")
    preflight = {
        "schema_version": "strategy11.source_bound_multicandidate_orchestrator.output.v1",
        "state": "PASS_SOURCE_BOUND_MULTICANDIDATE_PREFLIGHT",
        "candidate_count": 2,
        "eligible_candidate_count": 2,
        "classifications": {synthesis_id: "SYNTHESIS", str(core_proposal["strategy_id"]): "CORE"},
        "selected_combination": selected,
        "selected_combination_sha": combination_sha,
        "target_risk_weights": weights,
        "shared_lineage": lineage,
        "stage_shas": {
            "proposal": {
                synthesis_id: adapter_result["proposal"]["proposal_sha"],
                str(core_proposal["strategy_id"]): core_proposal["proposal_sha"],
            },
            "classification": {
                synthesis_id: adapter_result["classification"]["classification_sha"],
                str(core_proposal["strategy_id"]): core_classification["classification_sha"],
            },
            "correlation": portfolio_result["correlation_analysis_sha"],
            "governor": canonical_sha(portfolio_result["governor_result"]),
            "attribution_history": adapter_result["attribution_sha"],
            "role_boundary": canonical_sha({"fixture": "ROLE_BOUNDARY_PASS", "selected": selected}),
            "model_risk": {
                member: canonical_sha({"fixture": "MODEL_RISK_PASS", "member": member}) for member in selected
            },
        },
        "source_history_verified": True,
        "append_only_evidence": True,
        "validated_role_message_count": 8,
        "model_risk_states": ["PASS_MODEL_RISK_GOVERNANCE"] * len(selected),
        "shadow_20c_ready": True,
        "shadow_canary_scope": "READ_ONLY_ORGANIC_E2E_FIXTURE_ONLY",
        "automatic_shadow_start": False,
        "runtime_bound": False,
        **SAFETY,
    }
    preflight["orchestrator_sha"] = canonical_sha(preflight)

    cycles = shadow20_fixture.make_cycles()
    weight_items = list(weights.items())
    if len(weight_items) != 2:
        _fail("ORGANIC_FIXTURE_REQUIRES_TWO_WEIGHTS", str(len(weight_items)))
    for cycle in cycles:
        cycle["source_w1_manifest_sha"] = lineage["source_w1_manifest_sha"]
        cycle["data_sha"] = lineage["data_sha"]
        cycle["window_sha"] = lineage["window_sha"]
        cycle["evidence_manifest_sha"] = lineage["evidence_manifest_sha"]
        cycle["selected_combination_sha"] = combination_sha
        cycle["target_weights"] = copy.deepcopy(weights)
        cycle["observed_weights"] = copy.deepcopy(weights)
        first_id, first_weight = weight_items[0]
        second_id, _ = weight_items[1]
        first_pnl = round(float(cycle["net_pnl_r"]) * float(first_weight), 10)
        cycle["material_net_pnl_r"] = {
            first_id: first_pnl,
            second_id: round(float(cycle["net_pnl_r"]) - first_pnl, 10),
        }
        cycle.pop("cycle_sha", None)
        cycle["cycle_sha"] = canonical_sha(cycle)

    document = {"cycles": cycles}
    return {
        "schema_version": shadow20_fixture.INPUT_SCHEMA,
        "preflight": preflight,
        "cycle_source": shadow20_fixture.source(
            "SHADOW_READ_ONLY_CYCLE_LEDGER",
            "fixture-organic-shadow20-cycle-ledger",
            "fixture-organic-shadow20",
            document,
        ),
        "policy_source": shadow20_fixture.source(
            "FIXTURE_POLICY",
            "fixture-organic-shadow20-policy",
            "fixture-organic-policy",
            copy.deepcopy(shadow20_fixture.POLICY),
        ),
        "authority": copy.deepcopy(shadow20_fixture.AUTHORITY),
    }


def validate_portfolio_shadow20_handoff(portfolio_result: Mapping[str, Any], shadow20_input: Mapping[str, Any]) -> None:
    preflight = _mapping(shadow20_input.get("preflight"), "shadow20_input.preflight")
    if preflight.get("selected_combination_sha") != portfolio_result.get("candidate_set_sha"):
        _fail("PORTFOLIO_SHADOW20_COMBINATION_SHA_MISMATCH")
    if preflight.get("target_risk_weights") != portfolio_result.get("governor_result", {}).get("target_risk_weights"):
        _fail("PORTFOLIO_SHADOW20_TARGET_WEIGHTS_MISMATCH")
    if set(preflight.get("selected_combination", [])) != set(portfolio_result.get("selected_members", [])):
        _fail("PORTFOLIO_SHADOW20_MEMBERS_MISMATCH")


def _segment_from_shadow20(
    shadow20_result: Mapping[str, Any],
    *,
    index: int,
    start_cycle: int,
    target_weights_sha: str,
    head_sha: str,
) -> dict[str, Any]:
    metrics = _mapping(shadow20_result.get("metrics"), "shadow20_result.metrics")
    payload = {
        "state": shadow20_result["state"],
        "shadow_200c_allowed": shadow20_result["shadow_200c_allowed"],
        "selected_combination_sha": shadow20_result["selected_combination_sha"],
        "target_weights_sha": target_weights_sha,
        "shared_lineage": copy.deepcopy(shadow20_result["shared_lineage"]),
        "metrics": {
            "total_net_r": round(float(metrics["total_net_pnl_r"]) + index * 0.001, 10),
            "total_cost_r": float(metrics["total_cost_r"]),
            "max_shadow_dd_pct": float(metrics["max_shadow_dd_pct"]),
            "max_cost_overrun_pct": float(metrics["max_cost_overrun_pct"]),
            "max_abs_weight_drift": float(metrics["max_abs_weight_drift"]),
            "max_abs_rolling_correlation": float(metrics["max_abs_rolling_correlation"]),
            "max_attribution_error_r": float(metrics["max_attribution_error_r"]),
            "stale_cycles": int(metrics["stale_cycle_count"]),
            "source_parity_failures": int(metrics["source_parity_failure_count"]),
            "display_integrity_failures": int(metrics["display_integrity_failure_count"]),
            "lineage_failures": 0,
            "chaos_e2e_failures": 0,
        },
        "runtime_bound": False,
        "real_shadow_started": False,
        **SAFETY,
    }
    return {
        "segment_id": f"organic.shadow20.segment.{start_cycle:03d}",
        "start_cycle": start_cycle,
        "end_cycle": start_cycle + 19,
        "cycle_count": 20,
        "run_id": str(910000 + start_cycle),
        "head_sha": head_sha,
        "artifact_sha": canonical_sha(
            {
                "shadow20_canary_sha": shadow20_result["canary_sha"],
                "segment_index": index,
                "start_cycle": start_cycle,
            }
        ),
        "payload": payload,
        "payload_sha": canonical_sha(payload),
    }


def build_shadow_chain(
    adapter_result: Mapping[str, Any],
    portfolio_result: Mapping[str, Any],
    core_package: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    shadow20_input = _build_shadow20_input(adapter_result, portfolio_result, core_package)
    validate_portfolio_shadow20_handoff(portfolio_result, shadow20_input)
    shadow20_result = evaluate_shadow20(shadow20_input)
    if shadow20_result.get("state") != "PASS_SHADOW20_READ_ONLY_CANARY":
        _fail("SHADOW20_NOT_PASS", str(shadow20_result.get("state")))

    target_weights_sha = canonical_sha(shadow20_result["target_risk_weights"])
    head_sha = canonical_sha(
        {
            "portfolio_integration_sha": portfolio_result["integration_sha"],
            "shadow20_canary_sha": shadow20_result["canary_sha"],
        }
    )
    base_segments = [
        _segment_from_shadow20(
            shadow20_result,
            index=index,
            start_cycle=index * 20 + 1,
            target_weights_sha=target_weights_sha,
            head_sha=head_sha,
        )
        for index in range(10)
    ]
    shadow200_input = {
        "schema_version": SHADOW200_INPUT_SCHEMA,
        "segments": base_segments,
        "midcheck": shadow200_fixture.midcheck(),
        "policy": shadow200_fixture.policy(),
        "authority": copy.deepcopy(AUTHORITY),
    }
    shadow200_result = accumulate(shadow200_input)
    if shadow200_result.get("state") != "PASS_SHADOW200_READ_ONLY_ACCUMULATION":
        _fail("SHADOW200_NOT_PASS", str(shadow200_result.get("state")))
    if shadow200_result.get("selected_combination_sha") != portfolio_result.get("candidate_set_sha"):
        _fail("SHADOW200_COMBINATION_SHA_MISMATCH")

    continuation = [
        _segment_from_shadow20(
            shadow20_result,
            index=10 + index,
            start_cycle=201 + index * 20,
            target_weights_sha=target_weights_sha,
            head_sha=head_sha,
        )
        for index in range(5)
    ]
    shadow300_input = {
        "schema_version": SHADOW300_INPUT_SCHEMA,
        "base_200": shadow200_result,
        "continuation_segments": continuation,
        "final_review": shadow300_fixture.final_review(),
        "policy": shadow300_fixture.policy300(),
        "authority": copy.deepcopy(AUTHORITY),
    }
    shadow300_result = complete(shadow300_input)
    if shadow300_result.get("state") != "PASS_SHADOW300_READ_ONLY_COMPLETION":
        _fail("SHADOW300_NOT_PASS", str(shadow300_result.get("state")))
    if shadow300_result.get("selected_combination_sha") != portfolio_result.get("candidate_set_sha"):
        _fail("SHADOW300_COMBINATION_SHA_MISMATCH")
    if shadow300_result.get("target_weights_sha") != target_weights_sha:
        _fail("SHADOW300_TARGET_WEIGHTS_SHA_MISMATCH")

    ml = observe_ml(valid_ml_input())
    failure = observe_failure(valid_failure_input())
    if ml.get("state") != "PASS_ML_LIGHT_OBSERVATION":
        _fail("ML_OBSERVER_NOT_PASS", ",".join(ml.get("blocker_codes", [])))
    if failure.get("state") != "PASS_FAILURE_LEARNING_OBSERVATION":
        _fail("FAILURE_OBSERVER_NOT_PASS", ",".join(failure.get("blocker_codes", [])))
    policy = load_trusted_policy()
    policy_sha = trusted_policy_sha()
    observer_bundle_sha = canonical_sha(
        {
            "shadow300_completion_sha": shadow300_result["completion_sha"],
            "ml_manifest_sha": ml["observer_manifest_sha"],
            "failure_manifest_sha": failure["observer_manifest_sha"],
            "policy_sha": policy_sha,
        }
    )
    previous_head = ledger_genesis(shadow300_result["completion_sha"])
    burnin = []
    for cycle in range(301, 401):
        row = observer_receipt(cycle, previous_head, shadow300_result, ml, failure, observer_bundle_sha)
        burnin.append(row)
        previous_head = row["source_ledger_head_sha"]
    observer_input = {
        "schema_version": "strategy11.post_shadow_observer_gate.input.v1",
        "shadow300": shadow300_result,
        "ml_observation": ml,
        "failure_observation": failure,
        "burnin_cycles": burnin,
        "policy": policy,
        "policy_sha": policy_sha,
        "authority": copy.deepcopy(OBSERVER_SAFETY),
    }
    observer_result = evaluate_gate(observer_input)
    if observer_result.get("state") != "PASS_POST_SHADOW_OBSERVER_100C_STRUCTURAL_GATE":
        _fail("OBSERVER_GATE_NOT_PASS", str(observer_result.get("state")))
    if observer_input["shadow300"]["completion_sha"] != shadow300_result["completion_sha"]:
        _fail("SHADOW300_OBSERVER_COMPLETION_SHA_MISMATCH")
    return shadow20_result, shadow200_result, shadow300_result, observer_result


def run_chain() -> dict[str, Any]:
    sealer_result, adapter_result, portfolio_result, core_package = build_synthesis_chain()
    shadow20_result, shadow200_result, shadow300_result, observer_result = build_shadow_chain(
        adapter_result,
        portfolio_result,
        core_package,
    )

    genesis = canonical_sha({"kind": "STRATEGY11_ORGANIC_RECEIPT_GENESIS"})
    receipts = []
    stage_specs = [
        (
            "SYNTHESIS_SEALER",
            sealer_result["state"],
            sealer_result["synthesis_seal"]["seal_sha"],
        ),
        ("GLOBAL_CLASSIFIER_ADAPTER", adapter_result["state"], adapter_result["adapter_sha"]),
        ("PORTFOLIO_INTEGRATION", portfolio_result["state"], portfolio_result["integration_sha"]),
        ("SHADOW20", shadow20_result["state"], shadow20_result["canary_sha"]),
        ("SHADOW200", shadow200_result["state"], shadow200_result["accumulator_sha"]),
        ("SHADOW300", shadow300_result["state"], shadow300_result["completion_sha"]),
        ("OBSERVER100C", observer_result["state"], observer_result["gate_sha"]),
    ]
    previous_receipt = genesis
    parent_artifact = None
    for stage, state, artifact_sha in stage_specs:
        row = _stage_receipt(stage, state, artifact_sha, parent_artifact, previous_receipt)
        receipts.append(row)
        previous_receipt = row["receipt_sha"]
        parent_artifact = row["artifact_sha"]
    final_receipt = validate_receipt_chain(receipts)

    result = {
        "schema_version": "strategy11.organic_e2e_receipt.output.v1",
        "state": "PASS_STRATEGY11_ORGANIC_E2E_RECEIPT",
        "stage_count": len(receipts),
        "stage_states": {row["stage"]: row["state"] for row in receipts},
        "receipts": receipts,
        "final_receipt_sha": final_receipt,
        "synthesis_seal_sha": sealer_result["synthesis_seal"]["seal_sha"],
        "classification_sha": adapter_result["classification"]["classification_sha"],
        "portfolio_integration_sha": portfolio_result["integration_sha"],
        "candidate_set_sha": portfolio_result["candidate_set_sha"],
        "target_weights_sha": shadow300_result["target_weights_sha"],
        "shadow20_canary_sha": shadow20_result["canary_sha"],
        "shadow200_accumulator_sha": shadow200_result["accumulator_sha"],
        "shadow300_completion_sha": shadow300_result["completion_sha"],
        "observer_gate_sha": observer_result["gate_sha"],
        "cycle_count_to_shadow300": shadow300_result["cycle_count"],
        "observer_burnin_cycle_count": observer_result["burnin_cycle_count"],
        "paper_30d_structural_gate_pass": observer_result["paper_30d_structural_gate_pass"],
        "paper_30d_allowed": False,
        "automatic_shadow_start": False,
        "automatic_paper_start": False,
        "real_shadow_started": False,
        "fixture_only": True,
        "production_authority": False,
        **AUTHORITY,
    }
    result["organic_e2e_sha"] = canonical_sha(result)
    return result


def expect_failure(code: str, callback) -> str:
    try:
        callback()
    except OrganicChainError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    passed = run_chain()
    assert passed["state"] == "PASS_STRATEGY11_ORGANIC_E2E_RECEIPT"
    assert passed["stage_count"] == 7
    assert passed["cycle_count_to_shadow300"] == 300
    assert passed["observer_burnin_cycle_count"] == 100
    assert passed["paper_30d_structural_gate_pass"] is True
    assert passed["paper_30d_allowed"] is False
    assert passed["automatic_shadow_start"] is False
    assert passed["automatic_paper_start"] is False
    assert passed["real_shadow_started"] is False
    assert validate_receipt_chain(passed["receipts"]) == passed["final_receipt_sha"]

    _, adapter_result, portfolio_result, core_package = build_synthesis_chain()
    broken_handoff = _build_shadow20_input(adapter_result, portfolio_result, core_package)
    broken_handoff["preflight"]["selected_combination_sha"] = "0" * 64
    handoff_error = expect_failure(
        "PORTFOLIO_SHADOW20_COMBINATION_SHA_MISMATCH",
        lambda: validate_portfolio_shadow20_handoff(portfolio_result, broken_handoff),
    )

    broken_receipts = copy.deepcopy(passed["receipts"])
    broken_receipts[3]["previous_receipt_sha"] = "f" * 64
    broken_receipts[3]["receipt_sha"] = canonical_sha(
        {key: child for key, child in broken_receipts[3].items() if key != "receipt_sha"}
    )
    receipt_error = expect_failure(
        "ORGANIC_RECEIPT_PREVIOUS_SHA_MISMATCH",
        lambda: validate_receipt_chain(broken_receipts),
    )

    (OUT / "pass.json").write_text(json.dumps(passed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    negatives = {
        "portfolio_shadow20_handoff": handoff_error,
        "receipt_chain": receipt_error,
    }
    (OUT / "negative_fixtures.json").write_text(json.dumps(negatives, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "state": "PASS_STRATEGY11_ORGANIC_E2E_FIXTURE",
        "organic_e2e_sha": passed["organic_e2e_sha"],
        "final_receipt_sha": passed["final_receipt_sha"],
        "stage_count": passed["stage_count"],
        "shadow_cycle_count": passed["cycle_count_to_shadow300"],
        "observer_cycle_count": passed["observer_burnin_cycle_count"],
        "negative_fixture_count": len(negatives),
        "paper_30d_allowed": False,
        "fixture_only": True,
        "production_authority": False,
        **AUTHORITY,
    }
    (OUT / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
