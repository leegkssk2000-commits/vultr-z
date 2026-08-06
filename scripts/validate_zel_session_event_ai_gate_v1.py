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


def assert_safety(value: dict[str, Any], label: str) -> None:
    for key, expected in SAFETY.items():
        if value.get(key) != expected:
            raise ValueError(f"{label}_SAFETY_MISMATCH:{key}")


def provider_artifact(router: dict[str, Any], provider: str) -> dict[str, Any]:
    row = router.get("provider_results", {}).get(provider)
    if not isinstance(row, dict):
        raise ValueError(f"{provider.upper()}_RESULT_MISSING")
    artifact = row.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError(f"{provider.upper()}_ARTIFACT_MISSING")
    if row.get("returncode") != 0:
        raise ValueError(f"{provider.upper()}_RETURN_CODE_NONZERO")
    assert_safety(artifact, provider.upper())
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        gemini = read_object(args.gemini)
        router = read_object(args.router)
        policy = read_object(args.policy)
        assert_safety(gemini, "GEMINI")
        assert_safety(router, "ROUTER")

        if gemini.get("status") != "PASS_GEMINI_SESSION_EVENT_HYPOTHESIS":
            raise ValueError("GEMINI_GATE_NOT_PASS")
        if gemini.get("GEMINI_USED") is not True or gemini.get("used") is not True:
            raise ValueError("GEMINI_NOT_ACTUALLY_USED")
        required_lineage = {"actual_model", "run_id", "input_sha", "prompt_sha", "response_sha"}
        if not required_lineage.issubset(gemini) or any(not gemini.get(key) for key in required_lineage):
            raise ValueError("GEMINI_LINEAGE_INCOMPLETE")
        if len(set(map(str, gemini.get("public_urls", [])))) < 4:
            raise ValueError("GEMINI_VIDEO_COUNT_LT_4")
        if len(set(map(str, gemini.get("independent_channels", [])))) < 4:
            raise ValueError("GEMINI_CHANNEL_COUNT_LT_4")
        selected = gemini.get("selected_hypothesis")
        if not isinstance(selected, dict) or not selected.get("axis"):
            raise ValueError("GEMINI_SELECTED_HYPOTHESIS_MISSING")

        if router.get("status") != "PASS_AI_REVIEW_ROUTER":
            raise ValueError("AI_ROUTER_NOT_PASS")
        if router.get("final_decision") != "ADVISORY_COMPLETE_AWAIT_DETERMINISTIC_GATES":
            raise ValueError("AI_ROUTER_FINAL_DECISION_INVALID")
        if router.get("blocker_codes") != []:
            raise ValueError("AI_ROUTER_BLOCKERS_PRESENT")

        gemini_router = router.get("provider_results", {}).get("gemini", {})
        if gemini_router.get("status") != "PASS_EXISTING_GEMINI_ARTIFACT":
            raise ValueError("ROUTER_DID_NOT_BIND_GEMINI_ARTIFACT")

        groq = provider_artifact(router, "groq")
        if groq.get("status") != "PASS_GROQ_REDTEAM_CONNECTION" or groq.get("GROQ_USED") is not True:
            raise ValueError("GROQ_NOT_ACTUALLY_USED")
        if groq.get("review", {}).get("decision") != "PASS_TO_REPLAY":
            raise ValueError("GROQ_DID_NOT_PASS_TO_REPLAY")

        workers = provider_artifact(router, "workers_ai")
        if workers.get("status") != "PASS_WORKERS_AI_CONNECTION" or workers.get("model_called") is not True:
            raise ValueError("WORKERS_AI_NOT_ACTUALLY_USED")
        if workers.get("review", {}).get("decision") != "PASS_TO_REPLAY":
            raise ValueError("WORKERS_AI_DID_NOT_PASS_TO_REPLAY")

        github_pre = router.get("provider_results", {}).get("github_models", {})
        if github_pre.get("status") != "SKIPPED" or github_pre.get("required") is not False:
            raise ValueError("GITHUB_MODELS_PRE_REPLAY_ROUTE_INVALID")
        routes = policy.get("stage_routes", {})
        for stage in ("W1_GATE", "W2_GATE", "W3_GATE"):
            if routes.get(stage, {}).get("github_models") != "REQUIRED":
                raise ValueError(f"GITHUB_MODELS_NOT_REQUIRED_AT_{stage}")
            if routes.get(stage, {}).get("workers_ai") != "REQUIRED":
                raise ValueError(f"WORKERS_AI_NOT_REQUIRED_AT_{stage}")

        receipt = {
            "schema_version": "zel.session_event.ai_gate_receipt.v1",
            "state": "PASS_SESSION_EVENT_AI_CHAIN_BOUND",
            "family": "session_event_continuation_v1",
            "selected_axis": selected["axis"],
            "pre_replay_providers": {
                "gemini": {"used": True, "actual_model": gemini["actual_model"], "run_id": gemini["run_id"]},
                "groq": {"used": True, "actual_model": groq.get("actual_model"), "run_id": groq.get("run_id")},
                "workers_ai": {"used": True, "model": workers.get("model"), "model_called": True},
                "github_models": {"used": False, "route": "HARD_REQUIRED_AT_W1_W2_W3_NOT_PRE_REPLAY"}
            },
            "lineage": {
                "gemini_sha256": sha_file(args.gemini),
                "router_sha256": sha_file(args.router),
                "policy_sha256": sha_file(args.policy),
                "gemini_input_sha": gemini["input_sha"],
                "gemini_prompt_sha": gemini["prompt_sha"],
                "gemini_response_sha": gemini["response_sha"],
                "groq_response_sha": groq.get("response_sha"),
                "workers_response_sha": workers.get("response_sha")
            },
            "next_gate": "DETERMINISTIC_SESSION_EVENT_EVENT_STUDY",
            "deterministic_replay_final_authority": True,
            "selection_authority": False,
            "execution_authority": "NONE",
            **SAFETY,
            "action": "route_change"
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"PASS_SESSION_EVENT_AI_CHAIN_BOUND axis={selected['axis']}")
        return 0
    except Exception as exc:
        hold = {
            "schema_version": "zel.session_event.ai_gate_receipt.v1",
            "state": "HOLD_SESSION_EVENT_AI_CHAIN",
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
