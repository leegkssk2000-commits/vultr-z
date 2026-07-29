from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Mapping

from backend.tools.r7a4d_strategy11_generation7_quota_state_machine_v1 import read_json, stable_sha, write_json

VERSION = "R7A4D_STRATEGY11_PATH_SEARCH_LEDGER_UPDATE_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def assert_safety(value: Mapping[str, Any], name: str) -> None:
    for key, expected in SAFETY.items():
        if value.get(key) != expected:
            raise ValueError(f"SAFETY_MISMATCH:{name}:{key}")


def append_unique(row: dict[str, Any], key: str, value: str) -> None:
    values = [str(item) for item in row.get(key) or []]
    if value not in values:
        values.append(value)
    row[key] = sorted(values)


def update_ledger(ledger_value: Mapping[str, Any], replay_plan: Mapping[str, Any]) -> dict[str, Any]:
    assert_safety(ledger_value, "ledger")
    assert_safety(replay_plan, "replay_plan")
    ledger = copy.deepcopy(dict(ledger_value))
    rows = ledger.get("rows")
    if not isinstance(rows, list):
        raise ValueError("LEDGER_ROWS_REQUIRED")
    by_strategy = {str(row.get("strategy_id")): row for row in rows if isinstance(row, dict)}
    if len(by_strategy) != len(rows):
        raise ValueError("LEDGER_STRATEGY_DUPLICATE_OR_INVALID")

    consumed = []
    rejected = []
    family_wait = []
    for review in replay_plan.get("accepted") or []:
        strategy_id = str(review.get("strategy_id") or "")
        candidate_id = str(review.get("candidate_id") or "")
        axis = str(review.get("axis") or "").upper()
        if strategy_id not in by_strategy or not candidate_id or not axis:
            raise ValueError(f"ACCEPTED_REVIEW_IDENTITY_INVALID:{strategy_id}:{candidate_id}:{axis}")
        row = by_strategy[strategy_id]
        append_unique(row, "tested_candidate_ids", candidate_id)
        generation = dict(row.get("axis_generation_count") or {})
        generation[axis] = int(generation.get(axis) or 0) + 1
        if generation[axis] > 2:
            raise ValueError(f"AXIS_GENERATION_LIMIT_BREACH:{strategy_id}:{axis}:{generation[axis]}")
        row["axis_generation_count"] = generation
        row["last_path_candidate_id"] = candidate_id
        row["last_path_axis"] = axis
        row["last_path_review_sha"] = review.get("review_sha")
        consumed.append({"strategy_id": strategy_id, "candidate_id": candidate_id, "axis": axis, "generation": generation[axis]})

    for review in replay_plan.get("semantic_rejected") or []:
        strategy_id = str(review.get("strategy_id") or "")
        candidate_id = str(review.get("candidate_id") or "")
        if strategy_id not in by_strategy or not candidate_id:
            raise ValueError(f"REJECTED_REVIEW_IDENTITY_INVALID:{strategy_id}:{candidate_id}")
        append_unique(by_strategy[strategy_id], "ai_rejected_candidate_ids", candidate_id)
        rejected.append({"strategy_id": strategy_id, "candidate_id": candidate_id, "review_sha": review.get("review_sha")})

    for review in replay_plan.get("unsupported") or []:
        strategy_id = str(review.get("strategy_id") or "")
        candidate_id = str(review.get("candidate_id") or "")
        if strategy_id not in by_strategy or not candidate_id:
            raise ValueError(f"UNSUPPORTED_REVIEW_IDENTITY_INVALID:{strategy_id}:{candidate_id}")
        append_unique(by_strategy[strategy_id], "family_binding_wait_candidate_ids", candidate_id)
        family_wait.append({"strategy_id": strategy_id, "candidate_id": candidate_id, "reason": review.get("reason")})

    ledger["path_consumed_candidates"] = consumed
    ledger["path_ai_rejected_candidates"] = rejected
    ledger["path_family_binding_wait_candidates"] = family_wait
    ledger["path_state_machine_version"] = VERSION
    ledger["path_epoch_count"] = int(ledger.get("path_epoch_count") or 0) + (1 if consumed else 0)
    ledger.update(SAFETY)
    ledger["path_ledger_sha"] = stable_sha({key: value for key, value in ledger.items() if key != "path_ledger_sha"})
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--replay-plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = update_ledger(read_json(args.ledger), read_json(args.replay_plan))
    write_json(args.out, result)
    print("PASS_PATH_SEARCH_LEDGER_UPDATE", "epoch=", result["path_epoch_count"], "consumed=", len(result["path_consumed_candidates"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
