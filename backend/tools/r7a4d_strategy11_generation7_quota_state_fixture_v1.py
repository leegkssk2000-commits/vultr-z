from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1 as core
from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1_1 as adapter

SAFETY = dict(core.SAFETY)
VERSION = "R7A4D_STRATEGY11_GENERATION7_QUOTA_RUNTIME_FIXTURE_V2"


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def decision(status: str, *, blockers: list[str] | None = None, waits: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "strategy11.ai_review_decision_gate.v3",
        "status": status,
        "blocker_codes": blockers or [],
        "wait_codes": waits or [],
        "new_provider_calls": 0,
        "final_decision": "HOLD",
        **SAFETY,
    }


def fixture_plan() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan = {
        "state": "PASS_FIXTURE_PLAN",
        "prior_final_sha256": core.stable_sha({"fixture": "v2"}),
        "candidate_count": 2,
        "rows": [{
            "strategy_id": "fixture_strategy",
            "candidate_ids": ["A", "B"],
            "candidate_specs": {
                "A": {"axis": "BREAKEVEN", "parameters": {"activation_r": 0.75}},
                "B": {"axis": "TIME_STOP", "parameters": {"bars": 48}},
            },
            "failure_fingerprint": "FIXTURE",
            "selection_rationale": {"why": "fixture", "selected_axes": ["BREAKEVEN", "TIME_STOP"]},
        }],
    }
    causes = {
        "rows": [{
            "strategy_id": "fixture_strategy", "control": {"trades": 20},
            "candidates": [], "zero_trade_candidate_count": 0, "nonzero_candidate_count": 2,
        }],
        **SAFETY,
    }
    ledger = {
        "state": "PASS_SEARCH_LEDGER",
        "rows": [{
            "strategy_id": "fixture_strategy", "selected_candidate_ids": [],
            "selected_axes": [], "rejection_reason": "", "next_axis": "BREAKEVEN",
        }],
        **SAFETY,
    }
    return plan, causes, ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--groq-client", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)

    classify_root = args.root / "classify"
    rows = {
        "verified_quota": decision("WAIT_AI_QUOTA_REVIEW", waits=["groq:VERIFIED_QUOTA:HTTP 429 rate limit"]),
        "retryable_output": decision("WAIT_AI_QUOTA_REVIEW", waits=["groq:RETRYABLE_PROVIDER_OUTPUT:RESPONSE_JSON_RECOVERY_EXHAUSTED"]),
        "legacy_retryable_output": decision("WAIT_AI_QUOTA_REVIEW", waits=["groq:PROVIDER_BLOCKER:RESPONSE_JSON_RECOVERY_EXHAUSTED:RESPONSE_JSON_DECODE_FAILED"]),
        "missing_credentials": decision("WAIT_AI_QUOTA_REVIEW", waits=["groq:PROVIDER_BLOCKER:MISSING_GROQ_API_KEY"]),
        "semantic_reject": decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:SEMANTIC_REJECT:OVERFIT"]),
        "inconclusive_hold": decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:INCONCLUSIVE_HOLD:LINEAGE_INCOMPLETE"]),
    }
    classified = {}
    for name, payload in rows.items():
        path = classify_root / f"fixture__{name}.json"
        write(path, payload)
        classified[name] = adapter.strict_classify(path)
    assert classified == {
        "verified_quota": "WAIT_QUOTA",
        "retryable_output": "WAIT_PROVIDER_RETRY",
        "legacy_retryable_output": "WAIT_PROVIDER_RETRY",
        "missing_credentials": "BLOCKER",
        "semantic_reject": "SEMANTIC_REJECT",
        "inconclusive_hold": "BLOCKER",
    }

    epoch = "2026-07-29"
    prior = args.root / "prior"
    reserved = [f"fixture_strategy__R{i}.json" for i in range(10)]
    retry_files = reserved[:4]
    write(prior / "out/filter/quota_epoch_reservation.json", {
        "quota_epoch_date": epoch,
        "quota_epoch_candidates_used": 10,
        "quota_epoch_selected_files": reserved,
        "provider_retry_attempts": {name: 1 for name in retry_files},
        **SAFETY,
    })
    for name in retry_files:
        write(prior / "out/ai" / name, decision(
            "WAIT_AI_QUOTA_REVIEW",
            waits=["groq:PROVIDER_BLOCKER:RESPONSE_JSON_RECOVERY_EXHAUSTED:RESPONSE_JSON_DECODE_FAILED"],
        ))
    epoch_state = adapter.restore_epoch_state([prior], epoch)
    assert epoch_state["used"] == 10
    assert epoch_state["reserved_files"] == set(reserved)
    assert epoch_state["retryable_files"] == set(retry_files)
    assert all(epoch_state["retry_attempts"][name] == 1 for name in retry_files)

    reservation_root = args.root / "reservation"
    retry_paths = [Path(name) for name in retry_files]
    reservation = adapter.reserve_epoch_usage(
        reservation_root,
        epoch_date=epoch,
        epoch_state=epoch_state,
        new_selected=[],
        retry_selected=retry_paths,
        max_new_candidates=10,
    )
    assert reservation["quota_epoch_candidates_used"] == 10
    assert reservation["quota_epoch_candidates_remaining"] == 0
    assert reservation["quota_epoch_new_candidate_files"] == []
    assert reservation["provider_retry_files"] == retry_files
    assert all(reservation["provider_retry_attempts"][name] == 2 for name in retry_files)
    assert adapter.restore_epoch_state([reservation_root], epoch)["used"] == 10

    plan, causes, ledger = fixture_plan()
    retry_ai = args.root / "retry-state/ai"
    write(retry_ai / "fixture_strategy__A.json", decision(
        "WAIT_AI_QUOTA_REVIEW", waits=["groq:RETRYABLE_PROVIDER_OUTPUT:RESPONSE_JSON_RECOVERY_EXHAUSTED"]
    ))
    write(retry_ai / "fixture_strategy__B.json", decision(
        "WAIT_AI_QUOTA_REVIEW", waits=["groq:VERIFIED_QUOTA:HTTP 429 rate limit"]
    ))
    retry_out = args.root / "retry-state/out"
    retry_reservation = adapter.reserve_epoch_usage(
        retry_out,
        epoch_date=epoch,
        epoch_state={"used": 2, "reserved_files": {"fixture_strategy__A.json", "fixture_strategy__B.json"}, "retry_attempts": {"fixture_strategy__A.json": 1}},
        new_selected=[], retry_selected=[Path("fixture_strategy__A.json")], max_new_candidates=10,
    )
    core.classify = adapter.classify_for_core
    mixed = core.finalize(plan, causes, ledger, retry_ai, retry_out, 10)
    mixed = adapter.rewrite_outputs(mixed, retry_out, retry_ai, retry_reservation)
    assert mixed["state"] == "WAIT_GENERATION7_PROVIDER_RETRY"
    assert mixed["wait_provider_retry_count"] == 1
    assert mixed["wait_quota_count"] == 1
    assert mixed["quota_epoch_candidates_used"] == 2
    assert mixed["next"] == "RETRY_RESERVED_PROVIDER_OUTPUTS"

    reject_ai = args.root / "reject-state/ai"
    write(reject_ai / "fixture_strategy__A.json", decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:SEMANTIC_REJECT:OVERFIT"]))
    write(reject_ai / "fixture_strategy__B.json", decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["workers_ai:SEMANTIC_REJECT:POLICY"]))
    reject_out = args.root / "reject-state/out"
    core.classify = adapter.classify_for_core
    terminal = core.finalize(*fixture_plan(), reject_ai, reject_out, 10)
    assert terminal["state"] == "PASS_GENERATION7_AI_REVIEW_COMPLETE"
    assert terminal["next"] == "WAIT_NEW_EVIDENCE"

    workflow = args.workflow.read_text(encoding="utf-8")
    groq_client = args.groq_client.read_text(encoding="utf-8")
    required_workflow = [
        "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}", "gh api --paginate",
        "r7a4d_strategy11_generation7_quota_state_machine_v1_1.py",
        "if: always() && steps.restore.outcome == 'success' && steps.restore.outputs.complete != 'true'",
    ]
    assert not [value for value in required_workflow if value not in workflow]
    assert 'kwargs["response_format"] = {"type": "json_object"}' in groq_client
    assert "if json_mode:" in groq_client
    assert "BadRequestError" in groq_client
    assert "MAX_JSON_ATTEMPTS = 3" in groq_client

    summary = {
        "schema_version": "strategy11.generation7.quota_runtime.fixture.summary.v2",
        "version": VERSION,
        "state": "PASS_GENERATION7_PROVIDER_OUTPUT_RETRY_FIXTURE",
        "strict_classification": classified,
        "daily_new_candidate_budget_used": reservation["quota_epoch_candidates_used"],
        "daily_new_candidate_budget_remaining": reservation["quota_epoch_candidates_remaining"],
        "reserved_retry_candidate_count": len(retry_files),
        "reserved_retry_attempt": 2,
        "new_candidates_consumed_by_retry": 0,
        "mixed_wait_state": mixed["state"],
        "groq_json_object_mode": True,
        "all_rejected_next": terminal["next"],
        "fixture_only": True,
        **SAFETY,
    }
    summary["fixture_sha"] = core.stable_sha(summary)
    write(args.root / "summary.json", summary)
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
