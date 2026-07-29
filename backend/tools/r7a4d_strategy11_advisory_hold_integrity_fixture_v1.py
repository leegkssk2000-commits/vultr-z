from __future__ import annotations

import json
import tempfile
from pathlib import Path

from backend.research import strategy11_pre_shadow_path_optimize_planner_v1_2 as planner
from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1 as core
from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1_1 as quota
from backend.tools import r7a4d_strategy11_path_candidate_state_v1 as path_state
from backend.tools import r7a4d_strategy11_path_search_ledger_update_v1 as ledger_update

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def decision(token: str, candidate: str) -> dict:
    return {
        "schema_version": "strategy11.ai_review_decision_gate.v3",
        "status": "HOLD_AI_REVIEW_DECISION_GATE",
        "blocker_codes": [f"groq:{token}:OVERFILTER_ZERO_TRADES"],
        "wait_codes": [],
        "candidate_id": candidate,
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ai = root / "ai"
        out = root / "out"
        write(ai / "s__A.json", decision("ADVISORY_HOLD", "A"))
        write(ai / "s__B.json", decision("SEMANTIC_REJECT", "B"))
        manifest = {
  "state": "PASS_GENERATION7_AI_REVIEW_COMPLETE",
  "next": "WAIT_NEW_EVIDENCE",
  "all_candidates_final": True,
  "ready_to_replay": False,
  "wait_quota": [],
  "semantic_rejected": [
      {"strategy_id": "s", "candidate_id": "A", "file": "s__A.json", "state": "SEMANTIC_REJECT"},
      {"strategy_id": "s", "candidate_id": "B", "file": "s__B.json", "state": "SEMANTIC_REJECT"},
  ],
  "strategy_states": [{
      "strategy_id": "s",
      "state": "WAIT_NEW_EVIDENCE",
      "accepted_candidate_ids": [],
      "semantic_rejected_candidate_ids": ["A", "B"],
      "wait_quota_candidate_ids": [],
  }],
  **SAFETY,
        }
        write(out / "accepted_plan.json", {"state": "WAIT_NEW_EVIDENCE", **SAFETY})
        write(out / "search_ledger.json", {
  "strategy_states": manifest["strategy_states"],
  "rows": [{"strategy_id": "s", "rejection_reason": "A:AI_SEMANTIC_REJECT;B:AI_SEMANTIC_REJECT"}],
  **SAFETY,
        })
        reservation = {
  "quota_epoch_date": "2026-07-30",
  "quota_epoch_candidates_used": 0,
  "quota_epoch_candidates_remaining": 10,
  "quota_epoch_selected_files": [],
  "reservation_sha": "fixture-reservation",
  "provider_retry_attempts": {},
  "provider_retry_attempt_limit": 3,
        }
        rewritten = quota.rewrite_outputs(manifest, out, ai, reservation)
        assert rewritten["advisory_hold_count"] == 1
        assert rewritten["semantic_reject_count"] == 1
        assert rewritten["advisory_held"][0]["state"] == "ADVISORY_HOLD"
        manifest_state = rewritten["strategy_states"][0]
        assert manifest_state["advisory_held_candidate_ids"] == ["A"]
        assert manifest_state["semantic_rejected_candidate_ids"] == ["B"]

        prepared = {
  "state": "PASS_PATH_CANDIDATES_PREPARED",
  "executable_count": 1,
  "unsupported_count": 0,
  "executable": [{
      "strategy_id": "s", "candidate_id": "A", "axis": "TIME_STOP",
      "basis_variant_id": "CONTROL", "candidate_sha": "candidate-a",
      "kind": "EXIT", "changes": {"time_stop_bars": 12}, **SAFETY,
  }],
  "unsupported": [],
  **SAFETY,
        }
        path_out = root / "path-review"
        replay_plan = path_state.filter_reviews(prepared, ai, path_out)
        assert replay_plan["state"] == "WAIT_PATH_ALL_SEMANTIC_REJECT_OR_FAMILY_BINDING"
        assert replay_plan["blocker_count"] == 0
        assert replay_plan["advisory_hold_count"] == 1
        assert replay_plan["semantic_reject_count"] == 0

        ledger = {"rows": [{"strategy_id": "s"}], **SAFETY}
        updated = ledger_update.update_ledger(ledger, replay_plan)
        assert updated["rows"][0]["ai_advisory_held_candidate_ids"] == ["A"]
        assert updated["path_ai_advisory_held_candidates"][0]["candidate_id"] == "A"

        fingerprint = {"fingerprint": "TIME_EXPOSURE", "support_sha": "support"}
        basis = {"bundle_sha": "bundle", "source_sha": "source"}
        policy = {
  "max_axis_generations_per_data_epoch": 2,
  "candidate_catalog": {"TIME_EXPOSURE": [{
      "candidate_id": "A", "axis": "TIME_STOP", "parameters": {"time_stop_bars": 12}, "why": "fixture"
  }]},
        }
        candidate = planner.select_candidate(
  fingerprint,
  strategy_id="s",
  basis_variant_id="CONTROL",
  basis_bundle=basis,
  ledger_row={"ai_advisory_held_candidate_ids": ["A"], "remaining_axes": ["TIME_STOP"]},
  policy=policy,
        )
        assert candidate is None

        groq = Path('scripts/strategy11_groq_redteam_v1_2.py').read_text(encoding='utf-8')
        assert 'kwargs["response_format"] = {"type": "json_object"}' in groq
        assert 'Fixture compatibility marker' not in groq
        workflow = Path('.github/workflows/r7a4d-strategy11-generation7-quota-state-machine-v1.yml').read_text(encoding='utf-8')
        assert "steps.restore.outputs.complete != 'true'" in workflow

    print('PASS_STRATEGY11_ADVISORY_HOLD_INTEGRITY_FIXTURE')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
