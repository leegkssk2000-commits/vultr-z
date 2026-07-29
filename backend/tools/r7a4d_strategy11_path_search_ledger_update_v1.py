from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Mapping

from backend.tools.r7a4d_strategy11_generation7_quota_state_machine_v1 import read_json, stable_sha, write_json

VERSION = "R7A4D_STRATEGY11_PATH_SEARCH_LEDGER_UPDATE_V1_1"
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


def replay_completions(
    replay_plan: Mapping[str, Any], replay_root: Path | None
) -> dict[tuple[str, str], dict[str, Any]]:
    accepted = list(replay_plan.get("accepted") or [])
    if not accepted:
        return {}
    if replay_plan.get("state") != "PASS_PATH_AI_REVIEW_READY_TO_REPLAY":
        raise ValueError(f"REPLAY_PLAN_NOT_READY:{replay_plan.get('state')}")
    if replay_root is None:
        raise ValueError("PATH_REPLAY_COMPLETION_REQUIRED")
    root = replay_root.resolve()
    batch_path = root / "batch.json"
    if not batch_path.exists():
        raise ValueError(f"PATH_REPLAY_BATCH_MISSING:{batch_path}")
    batch = read_json(batch_path)
    assert_safety(batch, "replay_batch")
    if batch.get("state") != "PASS_PATH_CANDIDATE_REPLAY_BATCH":
        raise ValueError(f"PATH_REPLAY_BATCH_NOT_PASS:{batch.get('state')}")

    accepted_keys: set[tuple[str, str]] = set()
    accepted_strategies: set[str] = set()
    for review in accepted:
        strategy_id = str(review.get("strategy_id") or "")
        candidate_id = str(review.get("candidate_id") or "")
        if not strategy_id or not candidate_id:
            raise ValueError(f"ACCEPTED_REVIEW_IDENTITY_INVALID:{strategy_id}:{candidate_id}")
        key = (strategy_id, candidate_id)
        if key in accepted_keys:
            raise ValueError(f"ACCEPTED_REVIEW_DUPLICATE:{strategy_id}:{candidate_id}")
        accepted_keys.add(key)
        accepted_strategies.add(strategy_id)

    batch_rows = batch.get("rows")
    if not isinstance(batch_rows, list):
        raise ValueError("PATH_REPLAY_BATCH_ROWS_REQUIRED")
    batch_strategies = {str(row.get("strategy_id") or "") for row in batch_rows if isinstance(row, Mapping)}
    if batch_strategies != accepted_strategies:
        raise ValueError(
            "PATH_REPLAY_STRATEGY_SET_MISMATCH:"
            f"accepted={sorted(accepted_strategies)}:batch={sorted(batch_strategies)}"
        )

    completions: dict[tuple[str, str], dict[str, Any]] = {}
    for strategy_id, candidate_id in sorted(accepted_keys):
        strategy_path = root / strategy_id / "summary.json"
        candidate_path = root / strategy_id / candidate_id / "summary.json"
        if not strategy_path.exists() or not candidate_path.exists():
            raise ValueError(f"PATH_REPLAY_SUMMARY_MISSING:{strategy_id}:{candidate_id}")
        strategy_summary = read_json(strategy_path)
        candidate_summary = read_json(candidate_path)
        assert_safety(strategy_summary, f"strategy_summary:{strategy_id}")
        assert_safety(candidate_summary, f"candidate_summary:{strategy_id}:{candidate_id}")
        tested = [str(value) for value in strategy_summary.get("tested_candidate_ids") or []]
        if tested != [candidate_id]:
            raise ValueError(f"PATH_REPLAY_TESTED_ID_MISMATCH:{strategy_id}:{tested}:{candidate_id}")
        if strategy_summary.get("state") not in {"PASS_L090_RESEARCH_CANDIDATE", "NO_L090_CANDIDATE"}:
            raise ValueError(f"PATH_REPLAY_OUTCOME_INVALID:{strategy_id}:{strategy_summary.get('state')}")
        config = candidate_summary.get("candidate_config")
        if not isinstance(config, Mapping) or str(config.get("candidate_id") or "") != candidate_id:
            raise ValueError(f"PATH_REPLAY_CANDIDATE_CONFIG_MISMATCH:{strategy_id}:{candidate_id}")
        parity = candidate_summary.get("parity")
        if not isinstance(parity, Mapping) or parity.get("state") != "PASS":
            raise ValueError(f"PATH_REPLAY_PARITY_NOT_PASS:{strategy_id}:{candidate_id}")
        if int(parity.get("duplicate_trade_count") or 0) != 0:
            raise ValueError(f"PATH_REPLAY_DUPLICATE_TRADES:{strategy_id}:{candidate_id}")
        ladder = candidate_summary.get("ladder_check")
        if not isinstance(ladder, Mapping) or not isinstance(ladder.get("research_pass"), bool):
            raise ValueError(f"PATH_REPLAY_LADDER_RESULT_MISSING:{strategy_id}:{candidate_id}")
        if strategy_summary.get("winner") not in {None, candidate_id}:
            raise ValueError(f"PATH_REPLAY_WINNER_MISMATCH:{strategy_id}:{candidate_id}")
        completion = {
            "strategy_id": strategy_id,
            "candidate_id": candidate_id,
            "outcome_state": strategy_summary["state"],
            "winner": strategy_summary.get("winner"),
            "research_pass": ladder["research_pass"],
            "strategy_summary_sha": stable_sha(strategy_summary),
            "candidate_summary_sha": stable_sha(candidate_summary),
            "batch_sha": stable_sha(batch),
        }
        completion["completion_sha"] = stable_sha(completion)
        completions[(strategy_id, candidate_id)] = completion
    return completions


def update_ledger(
    ledger_value: Mapping[str, Any],
    replay_plan: Mapping[str, Any],
    replay_root: Path | None = None,
) -> dict[str, Any]:
    assert_safety(ledger_value, "ledger")
    assert_safety(replay_plan, "replay_plan")
    completions = replay_completions(replay_plan, replay_root)
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
        completion = completions.get((strategy_id, candidate_id))
        if completion is None:
            raise ValueError(f"PATH_REPLAY_COMPLETION_REQUIRED:{strategy_id}:{candidate_id}")
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
        row["last_path_replay_completion_sha"] = completion["completion_sha"]
        row["last_path_replay_state"] = completion["outcome_state"]
        row["last_path_research_pass"] = completion["research_pass"]
        consumed.append({
            "strategy_id": strategy_id,
            "candidate_id": candidate_id,
            "axis": axis,
            "generation": generation[axis],
            **completion,
        })

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
    ledger["path_replay_completion_set_sha"] = stable_sha(consumed)
    ledger.update(SAFETY)
    ledger["path_ledger_sha"] = stable_sha({key: value for key, value in ledger.items() if key != "path_ledger_sha"})
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--replay-plan", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    replay_root = args.replay_root
    if replay_root is None:
        inferred = args.replay_plan.resolve().parent.parent / "replay"
        replay_root = inferred if inferred.exists() else None
    result = update_ledger(read_json(args.ledger), read_json(args.replay_plan), replay_root)
    write_json(args.out, result)
    print(
        "PASS_PATH_SEARCH_LEDGER_UPDATE",
        "epoch=", result["path_epoch_count"],
        "consumed=", len(result["path_consumed_candidates"]),
        "completion_sha=", result["path_replay_completion_set_sha"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
