#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def assert_safety(value: dict[str, Any], label: str) -> None:
    for key, expected in SAFETY.items():
        if value.get(key) != expected:
            raise ValueError(f"{label}_SAFETY_MISMATCH:{key}")


def provider_artifact(router: dict[str, Any], provider: str) -> dict[str, Any]:
    row = router.get("provider_results", {}).get(provider)
    if not isinstance(row, dict):
        raise ValueError(f"{provider.upper()}_RESULT_MISSING")
    if row.get("returncode") != 0:
        raise ValueError(f"{provider.upper()}_RETURN_CODE_NONZERO")
    artifact = row.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError(f"{provider.upper()}_ARTIFACT_MISSING")
    assert_safety(artifact, provider.upper())
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hypothesis", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        hypothesis = read_object(args.hypothesis)
        router = read_object(args.router)
        policy = read_object(args.policy)
        assert_safety(hypothesis, "HYPOTHESIS")
        assert_safety(router, "ROUTER")

        if hypothesis.get("state") != "PASS_MOMENTUM_GEN2_HYPOTHESIS_SEALED_RESEARCH_ONLY":
            raise ValueError("MOMENTUM_GEN2_HYPOTHESIS_NOT_SEALED")
        if hypothesis.get("strategy_id") != "momentum_breakout_continuation_v1":
            raise ValueError("STRATEGY_BINDING_MISMATCH")
        if hypothesis.get("changed_axes") != ["EXPECTED_MOVE_TO_COST_SATURATION"]:
            raise ValueError("MOMENTUM_GEN2_AXIS_NOT_SINGLE_OR_MISMATCHED")
        parameterization = hypothesis.get("hypothesis", {}).get("parameterization", {})
        if float(parameterization.get("effective_cap", 0.0)) != 6.0:
            raise ValueError("MOMENTUM_GEN2_CAP_MISMATCH")
        if hypothesis.get("baseline", {}).get("passing_count") != 0:
            raise ValueError("BASELINE_PASSING_COUNT_MISMATCH")

        if router.get("status") != "PASS_AI_REVIEW_ROUTER":
            raise ValueError("AI_ROUTER_NOT_PASS")
        if router.get("stage") != "PRE_REPLAY_EXTERNAL_HYPOTHESIS":
            raise ValueError("AI_ROUTER_STAGE_MISMATCH")
        if router.get("final_decision") != "ADVISORY_COMPLETE_AWAIT_DETERMINISTIC_GATES":
            raise ValueError("AI_ROUTER_FINAL_DECISION_INVALID")
        if router.get("blocker_codes") != []:
            raise ValueError("AI_ROUTER_BLOCKERS_PRESENT")

        for provider in ("gemini", "github_models"):
            skipped = router.get("provider_results", {}).get(provider, {})
            if skipped.get("status") != "SKIPPED" or skipped.get("required") is not False:
                raise ValueError(f"{provider.upper()}_PRE_W1_ROUTE_INVALID")

        groq = provider_artifact(router, "groq")
        if groq.get("status") != "PASS_GROQ_REDTEAM_CONNECTION" or groq.get("GROQ_USED") is not True:
            raise ValueError("GROQ_NOT_ACTUALLY_USED")
        if groq.get("review", {}).get("decision") != "PASS_TO_REPLAY":
            raise ValueError("GROQ_DID_NOT_PASS_TO_REPLAY")
        if groq.get("review", {}).get("single_axis") is not True:
            raise ValueError("GROQ_SINGLE_AXIS_NOT_TRUE")

        workers = provider_artifact(router, "workers_ai")
        if workers.get("status") != "PASS_WORKERS_AI_CONNECTION" or workers.get("model_called") is not True:
            raise ValueError("WORKERS_AI_NOT_ACTUALLY_USED")
        if workers.get("review", {}).get("decision") != "PASS_TO_REPLAY":
            raise ValueError("WORKERS_AI_DID_NOT_PASS_TO_REPLAY")
        if workers.get("review", {}).get("single_axis") is not True:
            raise ValueError("WORKERS_AI_SINGLE_AXIS_NOT_TRUE")
        if workers.get("review", {}).get("lineage_complete") is not True:
            raise ValueError("WORKERS_AI_LINEAGE_NOT_COMPLETE")

        routes = policy.get("stage_routes", {}).get("W1_GATE", {})
        if routes.get("workers_ai") != "REQUIRED" or routes.get("github_models") != "REQUIRED":
            raise ValueError("W1_MAJOR_GATE_ROUTE_INVALID")

        receipt = {
            "schema_version": "zel.momentum.gen2.ai_gate_receipt.v1",
            "state": "PASS_MOMENTUM_GEN2_AI_CHAIN_BOUND",
            "strategy_id": "momentum_breakout_continuation_v1",
            "generation": 2,
            "selected_axis": "EXPECTED_MOVE_TO_COST_SATURATION",
            "quality_formula": parameterization["quality_formula"],
            "effective_cap": 6.0,
            "baseline_event_study_receipt_sha256": hypothesis["baseline"]["event_study_receipt_sha256"],
            "pre_replay_providers": {
                "gemini": {"used": False, "route": "SKIPPED_NO_NEW_MULTIMODAL_EVIDENCE"},
                "groq": {"used": True, "actual_model": groq.get("actual_model"), "run_id": groq.get("run_id")},
                "workers_ai": {"used": True, "model": workers.get("model"), "model_called": True},
                "github_models": {"used": False, "route": "REQUIRED_AT_W1_RESULT_GATE"}
            },
            "lineage": {
                "hypothesis_sha256": sha_file(args.hypothesis),
                "router_sha256": sha_file(args.router),
                "policy_sha256": sha_file(args.policy),
                "groq_response_sha": groq.get("response_sha"),
                "workers_response_sha": workers.get("response_sha")
            },
            "next_gate": "MOMENTUM_GEN2_DETERMINISTIC_EVENT_STUDY_W1",
            "selection_authority": False,
            "execution_authority": "NONE",
            **SAFETY,
            "action": "route_change"
        }
        receipt["receipt_sha256"] = canonical_sha(receipt)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("PASS_MOMENTUM_GEN2_AI_CHAIN_BOUND")
        return 0
    except Exception as exc:
        hold = {
            "schema_version": "zel.momentum.gen2.ai_gate_receipt.v1",
            "state": "HOLD_MOMENTUM_GEN2_AI_CHAIN",
            "blocker_codes": [str(exc)[:1200]],
            "next_gate": "NONE_UNTIL_AI_CHAIN_PASS",
            "selection_authority": False,
            "execution_authority": "NONE",
            **SAFETY,
            "action": "block"
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(hold, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
