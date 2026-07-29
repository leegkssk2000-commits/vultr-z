from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from backend.tools.r7a4d_strategy11_subset_replay_aggregate_v1 import SAFETY, aggregate, canonical_sha, write_json

VERSION = "R7A4D_STRATEGY11_SUBSET_REPLAY_AGGREGATE_FIXTURE_V1"


def variant(variant_id: str, *, pass_l090: bool, net: float) -> dict[str, Any]:
    return {
        "variant_id": variant_id,
        "net_return_pct_sum": net,
        "net_profit_factor": 1.4 if net > 0 else 0.8,
        "payoff_ratio": 1.8 if net > 0 else 0.9,
        "max_drawdown_pct": 1.0,
        "parity": {"state": "PASS", "duplicate_trade_count": 0},
        "ladder_check": {"research_pass": pass_l090},
    }


def summary(strategy_id: str, *, winner: bool) -> dict[str, Any]:
    candidate_id = f"{strategy_id}_CANDIDATE"
    rows = [variant("NO_CHANGE_CONTROL", pass_l090=False, net=0.0), variant(candidate_id, pass_l090=winner, net=1.0 if winner else -0.2)]
    return {
        "schema_version": "1.0",
        "version": "R7A4D_STRATEGY11_MULTIMODAL_L090_REPLAY_V1",
        "capability_marker": "MULTIMODAL_RESCUE_L090_REPLAY",
        "state": "PASS_L090_RESEARCH_CANDIDATE" if winner else "NO_L090_CANDIDATE",
        "strategy_id": strategy_id,
        "tested_candidate_ids": [candidate_id],
        "winner": candidate_id if winner else None,
        "variants": rows,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }


def accepted_plan() -> dict[str, Any]:
    return {
        "state": "PASS_GENERATION7_QUOTA_REVIEW_COMPLETE",
        "original_strategy_count": 22,
        "strategy_count": 2,
        "candidate_count": 2,
        "rows": [
            {"strategy_id": "trend_ma_macd", "candidate_ids": ["TIME12"]},
            {"strategy_id": "bb_revert", "candidate_ids": ["TIME12"]},
        ],
        **SAFETY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    replay = args.root / "replay"
    write_json(replay / "trend_ma_macd" / "summary.json", summary("trend_ma_macd", winner=True))
    write_json(replay / "bb_revert" / "summary.json", summary("bb_revert", winner=False))
    plan = accepted_plan()
    result = aggregate(replay, plan)
    assert result["state"] == "PASS_MULTIMODAL_L090_REPLAY_COMPLETE"
    assert result["strategy_count"] == 2
    assert result["source_plan_strategy_count"] == 22
    assert result["partial_strategy_set"] is True
    assert result["unreplayed_strategies_intentionally_untouched"] is True
    assert result["l090_candidate_count"] == 1
    assert result["active_l085_queue"][0]["strategy_id"] == "trend_ma_macd"
    assert result["pending_distinct_axis_queue"][0]["strategy_id"] == "bb_revert"
    assert result["final_sha256"] == canonical_sha({key: value for key, value in result.items() if key != "final_sha256"})

    mismatch_plan = copy.deepcopy(plan)
    mismatch_plan["rows"].append({"strategy_id": "missing_strategy", "candidate_ids": ["TIME12"]})
    mismatch_error = ""
    try:
        aggregate(replay, mismatch_plan)
    except ValueError as exc:
        mismatch_error = str(exc)
    assert mismatch_error.startswith("SUBSET_AGGREGATE_STRATEGY_MISMATCH")

    summary_result = {
        "schema_version": "strategy11.subset_replay_aggregate.fixture.summary.v1",
        "version": VERSION,
        "state": "PASS_SUBSET_REPLAY_AGGREGATE_FIXTURE",
        "strategy_count": result["strategy_count"],
        "source_plan_strategy_count": result["source_plan_strategy_count"],
        "l090_candidate_count": result["l090_candidate_count"],
        "mismatch_error": mismatch_error,
        "fixture_only": True,
        **SAFETY,
    }
    summary_result["fixture_sha"] = canonical_sha(summary_result)
    write_json(args.root / "final.json", result)
    write_json(args.root / "summary.json", summary_result)
    print(summary_result["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
