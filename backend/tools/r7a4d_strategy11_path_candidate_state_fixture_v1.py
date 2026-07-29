from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

from backend.tools.r7a4d_strategy11_generation7_quota_state_machine_v1 import stable_sha, write_json
from backend.tools.r7a4d_strategy11_path_candidate_state_v1 import prepare, filter_reviews
from backend.tools.r7a4d_strategy11_path_search_ledger_update_v1 import update_ledger

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
VERSION = "R7A4D_STRATEGY11_PATH_CANDIDATE_STATE_FIXTURE_V1_1"


def proposal(strategy_id: str, candidate_id: str, axis: str) -> dict[str, Any]:
    row = {
        "strategy_id": strategy_id,
        "basis_variant_id": "BASIS_CONTROL",
        "basis_bundle_sha": stable_sha({"bundle": strategy_id}),
        "basis_source_sha": stable_sha({"source": strategy_id}),
        "candidate_id": candidate_id,
        "axis": axis,
        "parameters": {"fixture": True},
        "why": "fixture path-derived candidate",
        "failure_fingerprint": "MFE_GIVEBACK" if axis == "MFE_TRAILING" else "ENTRY_TOO_EARLY",
        "failure_support_sha": stable_sha({"support": strategy_id}),
        "generation": 1,
        "single_axis": True,
        "replay_required": True,
        "promotion_authority": False,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    row["candidate_sha"] = stable_sha(row)
    return row


def path_plan() -> dict[str, Any]:
    plan = {
        "state": "PASS_PRE_SHADOW_PATH_OPTIMIZE_BATCH_PLAN",
        "path_index_sha": stable_sha({"path": "index"}),
        "triage_sha": stable_sha({"triage": "fixture"}),
        "candidate_count": 2,
        "rows": [
            {
                "strategy_id": "trend_ma_macd",
                "state": "PASS_PRE_SHADOW_PATH_OPTIMIZE_PLAN",
                "next_candidate_proposal": proposal("trend_ma_macd", "PATH_TRAIL_R075_ATR075", "MFE_TRAILING"),
            },
            {
                "strategy_id": "bb_revert",
                "state": "PASS_PRE_SHADOW_PATH_OPTIMIZE_PLAN",
                "next_candidate_proposal": proposal("bb_revert", "PATH_CANDLE_PULLBACK_CONFIRM_1", "CANDLE_STRUCTURE_GATE"),
            },
        ],
        **SAFETY,
    }
    plan["plan_sha"] = stable_sha(plan)
    return plan


def ai_pass() -> dict[str, Any]:
    return {
        "status": "PASS_AI_REVIEW_DECISION_GATE",
        "blocker_codes": [],
        "wait_codes": [],
        "provider_results": {},
        **SAFETY,
    }


def ledger() -> dict[str, Any]:
    return {
        "state": "PASS_FIXTURE_LEDGER",
        "duplicate_strategy_axis_data_runs": 0,
        "rows": [
            {
                "strategy_id": "trend_ma_macd",
                "axis_generation_count": {"MFE_TRAILING": 0},
                "tested_candidate_ids": [],
                "selected_candidate_ids": [],
                "remaining_axes": ["MFE_TRAILING", "PARTIAL"],
                "next_axis": "MFE_TRAILING",
            },
            {
                "strategy_id": "bb_revert",
                "axis_generation_count": {"CANDLE_STRUCTURE_GATE": 0},
                "tested_candidate_ids": [],
                "selected_candidate_ids": [],
                "remaining_axes": ["CANDLE_STRUCTURE_GATE"],
                "next_axis": "CANDLE_STRUCTURE_GATE",
            },
        ],
        **SAFETY,
    }


def write_completed_replay(root: Path) -> None:
    strategy_id = "trend_ma_macd"
    candidate_id = "PATH_TRAIL_R075_ATR075"
    strategy = {
        "state": "NO_L090_CANDIDATE",
        "strategy_id": strategy_id,
        "tested_candidate_ids": [candidate_id],
        "winner": None,
        "same_axis_generation_count": 1,
        **SAFETY,
    }
    candidate = {
        "candidate_config": {"candidate_id": candidate_id, "axis": "MFE_TRAILING"},
        "parity": {"state": "PASS", "duplicate_trade_count": 0},
        "ladder_check": {"research_pass": False},
        **SAFETY,
    }
    batch = {
        "state": "PASS_PATH_CANDIDATE_REPLAY_BATCH",
        "strategy_count": 1,
        "rows": [strategy],
        **SAFETY,
    }
    write_json(root / "batch.json", batch)
    write_json(root / strategy_id / "summary.json", strategy)
    write_json(root / strategy_id / candidate_id / "summary.json", candidate)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    prepared = prepare(path_plan(), args.root)
    assert prepared["state"] == "PASS_PATH_CANDIDATES_PREPARED"
    assert prepared["executable_count"] == 1
    assert prepared["unsupported_count"] == 1
    executable = prepared["executable"][0]
    assert executable["candidate_id"] == "PATH_TRAIL_R075_ATR075"
    assert executable["changes"] == {"trail_activate_r": 0.75, "trail_atr_mult": 0.75}
    assert prepared["unsupported"][0]["state"] == "WAIT_FAMILY_BINDING"

    ai_root = args.root / "ai"
    write_json(ai_root / "trend_ma_macd__PATH_TRAIL_R075_ATR075.json", ai_pass())
    replay_plan = filter_reviews(prepared, ai_root, args.root / "filtered")
    assert replay_plan["state"] == "PASS_PATH_AI_REVIEW_READY_TO_REPLAY"
    assert replay_plan["accepted_count"] == 1
    assert replay_plan["unsupported_count"] == 1
    assert replay_plan["rows"][0]["basis_variant_id"] == "BASIS_CONTROL"
    assert replay_plan["rows"][0]["candidate_specs"]["PATH_TRAIL_R075_ATR075"]["kind"] == "EXIT"

    completion_blocked = False
    try:
        update_ledger(ledger(), replay_plan)
    except ValueError as exc:
        completion_blocked = "PATH_REPLAY_COMPLETION_REQUIRED" in str(exc)
    assert completion_blocked is True

    replay_root = args.root / "completed-replay"
    write_completed_replay(replay_root)
    updated = update_ledger(ledger(), replay_plan, replay_root)
    trend = next(row for row in updated["rows"] if row["strategy_id"] == "trend_ma_macd")
    bb = next(row for row in updated["rows"] if row["strategy_id"] == "bb_revert")
    assert trend["axis_generation_count"]["MFE_TRAILING"] == 1
    assert trend["tested_candidate_ids"] == ["PATH_TRAIL_R075_ATR075"]
    assert trend["last_path_research_pass"] is False
    assert len(trend["last_path_replay_completion_sha"]) == 64
    assert bb["family_binding_wait_candidate_ids"] == ["PATH_CANDLE_PULLBACK_CONFIRM_1"]
    assert updated["path_epoch_count"] == 1

    rejected_prepared = copy.deepcopy(prepared)
    rejected_ai = args.root / "rejected-ai"
    write_json(rejected_ai / "trend_ma_macd__PATH_TRAIL_R075_ATR075.json", {
        "status": "HOLD_AI_REVIEW_DECISION_GATE",
        "blocker_codes": ["groq:DECISION_REJECT:OVERFIT"],
        "wait_codes": [],
        **SAFETY,
    })
    rejected_plan = filter_reviews(rejected_prepared, rejected_ai, args.root / "rejected-filtered")
    assert rejected_plan["state"] == "WAIT_PATH_ALL_SEMANTIC_REJECT_OR_FAMILY_BINDING"
    rejected_ledger = update_ledger(ledger(), rejected_plan)
    trend_rejected = next(row for row in rejected_ledger["rows"] if row["strategy_id"] == "trend_ma_macd")
    assert trend_rejected["axis_generation_count"]["MFE_TRAILING"] == 0
    assert trend_rejected["ai_rejected_candidate_ids"] == ["PATH_TRAIL_R075_ATR075"]

    summary = {
        "schema_version": "strategy11.path_candidate_state.fixture.summary.v1",
        "version": VERSION,
        "state": "PASS_PATH_CANDIDATE_STATE_FIXTURE",
        "fixture_only": True,
        "production_authority": False,
        "executable_count": prepared["executable_count"],
        "unsupported_count": prepared["unsupported_count"],
        "accepted_count": replay_plan["accepted_count"],
        "path_epoch_count": updated["path_epoch_count"],
        "completion_without_replay_blocked": completion_blocked,
        "semantic_reject_generation_consumed": False,
        **SAFETY,
    }
    summary["fixture_sha"] = stable_sha(summary)
    write_json(args.root / "summary.json", summary)
    write_json(args.root / "updated_ledger.json", updated)
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
