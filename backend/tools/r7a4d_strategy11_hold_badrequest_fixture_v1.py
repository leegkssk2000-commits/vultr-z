from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1 as core
from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1_1 as adapter

SAFETY = dict(core.SAFETY)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--groq-client", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)

    classify = args.root / "classify"
    cases = {
        "advisory_hold": decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:ADVISORY_HOLD:OVERFILTER_ZERO_TRADES"]),
        "badrequest_retry": decision("WAIT_AI_QUOTA_REVIEW", waits=["groq:PROVIDER_BLOCKER:BadRequestError"]),
        "semantic_reject": decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:SEMANTIC_REJECT:ZERO_TRADES"]),
        "inconclusive_hold": decision("HOLD_AI_REVIEW_DECISION_GATE", blockers=["groq:INCONCLUSIVE_HOLD:INSUFFICIENT_EVIDENCE"]),
    }
    states = {}
    for name, payload in cases.items():
        path = classify / f"fixture__{name}.json"
        write(path, payload)
        states[name] = adapter.strict_classify(path)
    assert states == {
        "advisory_hold": "ADVISORY_HOLD",
        "badrequest_retry": "WAIT_PROVIDER_RETRY",
        "semantic_reject": "SEMANTIC_REJECT",
        "inconclusive_hold": "BLOCKER",
    }

    plan = {
        "prior_final_sha256": core.stable_sha({"fixture": "hold"}),
        "candidate_count": 2,
        "rows": [{
            "strategy_id": "fixture_strategy",
            "candidate_ids": ["HOLD", "REJECT"],
            "candidate_specs": {
                "HOLD": {"axis": "MOMENTUM_GATE"},
                "REJECT": {"axis": "TIME_STOP"},
            },
            "failure_fingerprint": "FIXTURE",
            "selection_rationale": {"why": "fixture"},
        }],
    }
    causes = {
        "rows": [{
            "strategy_id": "fixture_strategy", "control": {"trades": 7},
            "candidates": [], "zero_trade_candidate_count": 1, "nonzero_candidate_count": 1,
        }],
        **SAFETY,
    }
    ledger = {
        "rows": [{
            "strategy_id": "fixture_strategy", "selected_candidate_ids": [],
            "selected_axes": [], "rejection_reason": "", "next_axis": "MOMENTUM_GATE",
        }],
        **SAFETY,
    }
    ai_root = args.root / "state/ai"
    write(ai_root / "fixture_strategy__HOLD.json", cases["advisory_hold"])
    write(ai_root / "fixture_strategy__REJECT.json", cases["semantic_reject"])
    out = args.root / "state/out"
    reservation = adapter.reserve_epoch_usage(
        out,
        epoch_date="2026-07-29",
        epoch_state={"used": 2, "reserved_files": {"fixture_strategy__HOLD.json", "fixture_strategy__REJECT.json"}, "retry_attempts": {}},
        new_selected=[], retry_selected=[], max_new_candidates=10,
    )
    core.classify = adapter.classify_for_core
    manifest = core.finalize(plan, causes, ledger, ai_root, out, 10)
    manifest = adapter.rewrite_outputs(manifest, out, ai_root, reservation)
    assert manifest["state"] == "PASS_GENERATION7_AI_REVIEW_COMPLETE"
    assert manifest["semantic_reject_count"] == 1
    assert manifest["advisory_hold_count"] == 1
    assert manifest["all_candidates_final"] is True
    assert manifest["ready_to_replay"] is False
    assert manifest["next"] == "WAIT_NEW_EVIDENCE"
    assert manifest["advisory_held"][0]["candidate_id"] == "HOLD"
    assert manifest["semantic_rejected"][0]["candidate_id"] == "REJECT"

    groq = args.groq_client.read_text(encoding="utf-8")
    assert 'kwargs["response_format"] = {"type": "json_object"}' in groq
    assert 'type(exc).__name__ == "BadRequestError"' in groq
    assert "json_mode = False" in groq
    assert "MAX_JSON_ATTEMPTS = 3" in groq

    summary = {
        "schema_version": "strategy11.hold_badrequest.fixture.v1",
        "state": "PASS_GENERATION7_HOLD_BADREQUEST_CLOSURE_FIXTURE",
        "classification": states,
        "advisory_hold_count": manifest["advisory_hold_count"],
        "semantic_reject_count": manifest["semantic_reject_count"],
        "terminal_next": manifest["next"],
        "badrequest_json_mode_fallback": True,
        "new_candidate_budget_consumed": 0,
        "fixture_only": True,
        **SAFETY,
    }
    summary["fixture_sha"] = core.stable_sha(summary)
    write(args.root / "summary.json", summary)
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
