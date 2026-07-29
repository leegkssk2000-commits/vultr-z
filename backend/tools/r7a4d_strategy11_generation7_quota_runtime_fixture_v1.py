from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1 as core
from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1_1 as adapter

SAFETY = dict(core.SAFETY)
VERSION = "R7A4D_STRATEGY11_GENERATION7_QUOTA_RUNTIME_FIXTURE_V1"


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def decision(status: str, *, blockers: list[str] | None = None, waits: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "fixture.strategy11.ai_review_decision_gate.v3",
        "status": status,
        "blocker_codes": blockers or [],
        "wait_codes": waits or [],
        "new_provider_calls": 0,
        "final_decision": "HOLD",
        **SAFETY,
    }


def fixture_plan(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan = {
        "state": "PASS_FIXTURE_PLAN",
        "prior_final_sha256": core.stable_sha({"fixture": "all-rejected"}),
        "candidate_count": 2,
        "rows": [{
            "strategy_id": "fixture_strategy",
            "candidate_ids": ["REJECT_A", "REJECT_B"],
            "candidate_specs": {
                "REJECT_A": {"axis": "BREAKEVEN", "parameters": {"activation_r": 0.75}},
                "REJECT_B": {"axis": "TIME_STOP", "parameters": {"bars": 48}},
            },
            "failure_fingerprint": "FIXTURE",
            "selection_rationale": {"why": "fixture all semantic rejects", "selected_axes": ["BREAKEVEN", "TIME_STOP"]},
        }],
    }
    causes = {
        "rows": [{
            "strategy_id": "fixture_strategy",
            "control": {"trades": 20, "net": 0.0},
            "candidates": [],
            "zero_trade_candidate_count": 0,
            "nonzero_candidate_count": 2,
        }],
        **SAFETY,
    }
    ledger = {
        "state": "PASS_SEARCH_LEDGER",
        "rows": [{
            "strategy_id": "fixture_strategy",
            "selected_candidate_ids": [],
            "selected_axes": [],
            "rejection_reason": "",
            "next_axis": "BREAKEVEN",
        }],
        **SAFETY,
    }
    write(root / "plan.json", plan)
    write(root / "cause_analysis.json", causes)
    write(root / "search_ledger.json", ledger)
    return plan, causes, ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)

    classify_root = args.root / "classify"
    rows = {
        "verified_quota": decision("WAIT_AI_QUOTA_REVIEW", waits=["groq:VERIFIED_QUOTA:HTTP 429 rate limit"]),
        "missing_credentials": decision("WAIT_AI_QUOTA_REVIEW", waits=["groq:PROVIDER_BLOCKER:MISSING_GROQ_API_KEY"]),
        "semantic_reject": decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:SEMANTIC_REJECT:OVERFIT"]),
        "inconclusive_hold": decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:INCONCLUSIVE_HOLD:INSUFFICIENT_EVIDENCE"]),
    }
    classified = {}
    for name, payload in rows.items():
        path = classify_root / f"fixture__{name}.json"
        write(path, payload)
        classified[name] = adapter.strict_classify(path)
    assert classified == {
        "verified_quota": "WAIT_QUOTA",
        "missing_credentials": "BLOCKER",
        "semantic_reject": "SEMANTIC_REJECT",
        "inconclusive_hold": "BLOCKER",
    }
    assert adapter.is_verified_quota_failure("used up your daily free allocation") is True
    assert adapter.is_verified_quota_failure("HTTP 401 invalid token") is False

    epoch = "2026-07-29"
    prior = args.root / "prior"
    write(prior / "state" / "out" / "filter" / "ai_manifest.json", {
        "state": "WAIT_GENERATION7_AI_QUOTA",
        "quota_epoch_date": epoch,
        "quota_epoch_candidates_used": 7,
        **SAFETY,
    })
    used_before = adapter.restore_epoch_usage([prior], epoch)
    assert used_before == 7
    output_root = args.root / "budget"
    base_manifest = {
        "state": "WAIT_GENERATION7_AI_QUOTA",
        "state_sha": "old",
        "pass_count": 1,
        "semantic_reject_count": 1,
        "wait_quota_count": 2,
        **SAFETY,
    }
    write(output_root / "accepted_plan.json", {"state": "WAIT_GENERATION7_AI_QUOTA", **SAFETY})
    write(output_root / "search_ledger.json", {"state": "PASS_SEARCH_LEDGER", **SAFETY})
    selected = [Path("a.json"), Path("b.json"), Path("c.json")]
    budgeted = adapter.rewrite_manifest(
        base_manifest,
        output_root,
        epoch_date=epoch,
        used_before=used_before,
        selected=selected,
        max_new_candidates=10,
    )
    assert budgeted["quota_epoch_candidates_used"] == 10
    assert budgeted["quota_epoch_candidates_remaining"] == 0
    assert len(budgeted["state_sha"]) == 64

    plan_root = args.root / "all-rejected-plan"
    plan, causes, ledger = fixture_plan(plan_root)
    ai_root = args.root / "all-rejected-ai"
    write(ai_root / "fixture_strategy__REJECT_A.json", decision(
        "HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:SEMANTIC_REJECT:OVERFIT"]
    ))
    write(ai_root / "fixture_strategy__REJECT_B.json", decision(
        "HOLD_AI_REVIEW_DECISION_GATE", blockers=["workers_ai:SEMANTIC_REJECT:LINEAGE_POLICY_REJECT"]
    ))
    core.classify = adapter.strict_classify
    terminal_root = args.root / "all-rejected-state"
    terminal = core.finalize(plan, causes, ledger, ai_root, terminal_root, 10)
    accepted_plan = core.read_json(terminal_root / "accepted_plan.json")
    assert terminal["state"] == "PASS_GENERATION7_AI_REVIEW_COMPLETE"
    assert terminal["all_candidates_final"] is True
    assert terminal["ready_to_replay"] is False
    assert terminal["wait_quota_count"] == 0
    assert terminal["replay_strategy_count"] == 0
    assert terminal["next"] == "WAIT_NEW_EVIDENCE"
    assert accepted_plan["rows"] == []

    workflow = args.workflow.read_text(encoding="utf-8")
    required_fragments = [
        "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}",
        "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}",
        "CLOUDFLARE_WORKERS_AI_TOKEN: ${{ secrets.CLOUDFLARE_WORKERS_AI_TOKEN }}",
        "gh api --paginate",
        "r7a4d_strategy11_generation7_quota_state_machine_v1_1.py",
        "Assert terminal WAIT_NEW_EVIDENCE outcome",
        "steps.state.outputs.all_final != 'true'",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in workflow]
    assert not missing, missing

    summary = {
        "schema_version": "strategy11.generation7.quota_runtime.fixture.summary.v1",
        "version": VERSION,
        "state": "PASS_GENERATION7_QUOTA_RUNTIME_FIXTURE",
        "strict_classification": classified,
        "verified_quota_only": True,
        "daily_budget_persisted": True,
        "quota_epoch_candidates_used": budgeted["quota_epoch_candidates_used"],
        "all_rejected_next": terminal["next"],
        "credential_mapping_present": True,
        "artifact_pagination_present": True,
        "fixture_only": True,
        **SAFETY,
    }
    summary["fixture_sha"] = core.stable_sha(summary)
    write(args.root / "summary.json", summary)
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
