from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts import strategy11_ai_review_router as v1
from backend.tools.r7a4d_strategy11_generation7_quota_state_machine_v1 import build_payloads, read_json, stable_sha, write_json

SAFETY = dict(v1.SAFETY)
VERSION = "R7A4D_STRATEGY11_AI_QUOTA_RESUME_FIXTURE_V1"


def fixture_plan(root: Path) -> None:
    sha = stable_sha({"fixture": "prior-final"})
    plan = {
        "state": "PASS_FIXTURE_PLAN",
        "prior_final_sha256": sha,
        "candidate_count": 2,
        "rows": [{
            "strategy_id": "fixture_strategy",
            "candidate_ids": ["CANDIDATE_PASS", "CANDIDATE_REJECT"],
            "candidate_specs": {
                "CANDIDATE_PASS": {"axis": "MFE_TRAILING", "parameters": {"activation_r": 0.75}},
                "CANDIDATE_REJECT": {"axis": "ENTRY_CONTEXT_GATE", "parameters": {"gate": "overfilter"}},
            },
            "failure_fingerprint": "MFE_GIVEBACK",
            "selection_rationale": {"why": "fixture isolated axes"},
        }],
    }
    causes = {
        "rows": [{
            "strategy_id": "fixture_strategy",
            "control": {"trades": 20, "net": 1.0},
            "candidates": [],
            "zero_trade_candidate_count": 1,
            "nonzero_candidate_count": 1,
        }]
    }
    ledger = {
        "rows": [{
            "strategy_id": "fixture_strategy",
            "selected_candidate_ids": [],
            "selected_axes": [],
            "rejection_reason": "",
            "next_axis": "MFE_TRAILING",
        }],
        **SAFETY,
    }
    write_json(root / "plan.json", plan)
    write_json(root / "cause_analysis.json", causes)
    write_json(root / "search_ledger.json", ledger)


def provider_row(provider: str, decision: str) -> dict[str, Any]:
    review = {
        "decision": decision,
        "blocker_codes": [] if decision == "PASS_TO_REPLAY" else ["OVERFILTER_ZERO_TRADES"],
        "single_axis": True,
    }
    if provider == "workers_ai":
        review["lineage_complete"] = True
    return {
        "returncode": 0,
        "stdout_sha": stable_sha({"provider": provider, "stdout": decision}),
        "stderr_sha": stable_sha({"provider": provider, "stderr": ""}),
        "artifact": {
            "status": f"PASS_{provider.upper()}_CONNECTION",
            "provider": provider,
            "review": review,
            "run_id": "fixture-prior-run",
            "run_attempt": "1",
            **SAFETY,
        },
    }


def prior_result(payload_path: Path, policy_path: Path, groq_decision: str) -> dict[str, Any]:
    payload = read_json(payload_path)
    policy = read_json(policy_path)
    v1.validate_policy(policy)
    plan = v1.build_plan(policy, "PRE_REPLAY_EXTERNAL_HYPOTHESIS", payload)
    external = v1.build_external_payload(payload, "PRE_REPLAY_EXTERNAL_HYPOTHESIS")
    return {
        "schema_version": "strategy11.ai_review_decision_gate.v2",
        "status": "HOLD_AI_REVIEW_DECISION_GATE",
        "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
        "input_sha": v1.sha256_text(v1.canonical_json(payload)),
        "external_input_sha": v1.sha256_text(v1.canonical_json(external)),
        "policy_sha": v1.sha256_text(v1.canonical_json(policy)),
        "plan_sha": v1.sha256_text(v1.canonical_json(plan)),
        "provider_results": {
            "gemini": {"status": "SKIPPED", "required": False},
            "groq": provider_row("groq", groq_decision),
            "workers_ai": provider_row("workers_ai", "PASS_TO_REPLAY"),
            "github_models": {"status": "SKIPPED", "required": False},
        },
        "blocker_codes": [],
        "final_decision": "HOLD",
        **SAFETY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--driver", type=Path, required=True)
    args = parser.parse_args()
    plan_root = args.root / "plan"
    payload_root = args.root / "payloads"
    prior_root = args.root / "prior"
    ai_root = args.root / "ai"
    state_root = args.root / "state"
    fixture_plan(plan_root)
    build_payloads(plan_root, payload_root)
    prior_root.mkdir(parents=True, exist_ok=True)
    write_json(prior_root / "fixture_strategy__CANDIDATE_PASS.json", prior_result(
        payload_root / "fixture_strategy__CANDIDATE_PASS.json", args.policy, "PASS_TO_REPLAY"
    ))
    write_json(prior_root / "fixture_strategy__CANDIDATE_REJECT.json", prior_result(
        payload_root / "fixture_strategy__CANDIDATE_REJECT.json", args.policy, "REJECT"
    ))

    command = [
        sys.executable, str(args.driver),
        "--plan-root", str(plan_root),
        "--payload-root", str(payload_root),
        "--ai-root", str(ai_root),
        "--output-root", str(state_root),
        "--router", str(args.router),
        "--policy", str(args.policy),
        "--prior-root", str(prior_root),
        "--max-new-candidates", "1",
    ]
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"DRIVER_FAILED:{process.stdout}:{process.stderr}")

    manifest = read_json(state_root / "ai_manifest.json")
    accepted_plan = read_json(state_root / "accepted_plan.json")
    passed = read_json(ai_root / "fixture_strategy__CANDIDATE_PASS.json")
    rejected = read_json(ai_root / "fixture_strategy__CANDIDATE_REJECT.json")
    assert manifest["state"] == "PASS_GENERATION7_AI_REVIEW_COMPLETE"
    assert manifest["pass_count"] == 1
    assert manifest["semantic_reject_count"] == 1
    assert manifest["wait_quota_count"] == 0
    assert manifest["new_provider_calls"] == 0
    assert manifest["ready_to_replay"] is True
    assert accepted_plan["candidate_count"] == 1
    assert accepted_plan["rows"][0]["candidate_ids"] == ["CANDIDATE_PASS"]
    assert passed["status"] == "PASS_AI_REVIEW_DECISION_GATE"
    assert passed["provider_results"]["groq"]["reused"] is True
    assert passed["provider_results"]["workers_ai"]["reused"] is True
    assert rejected["status"] == "HOLD_AI_REVIEW_DECISION_GATE"
    assert rejected["provider_results"]["workers_ai"]["status"] == "SKIPPED_UPSTREAM_GROQ_REJECT"
    assert rejected["provider_results"]["workers_ai"]["quota_preserved"] is True

    summary = {
        "schema_version": "strategy11.ai_quota_resume.fixture.summary.v1",
        "version": VERSION,
        "state": "PASS_AI_QUOTA_RESUME_FIXTURE",
        "cached_provider_reviews_reused": 3,
        "workers_calls_avoided_by_groq_reject": 1,
        "new_provider_calls": 0,
        "accepted_candidate_id": "CANDIDATE_PASS",
        "semantic_rejected_candidate_id": "CANDIDATE_REJECT",
        "fixture_only": True,
        **SAFETY,
    }
    summary["fixture_sha"] = stable_sha(summary)
    write_json(args.root / "summary.json", summary)
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
