from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

from backend.research import strategy11_pre_shadow_path_optimize_planner_v1 as core

SCHEMA = "strategy11.pre_shadow_path_optimize_plan.v1.1"
VERSION = "STRATEGY11_PRE_SHADOW_PATH_OPTIMIZE_PLANNER_V1_1"


def build_plan(
    *,
    path_index: Mapping[str, Any],
    path_root: Path,
    triage: Mapping[str, Any],
    ledger: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    core.assert_safety(path_index, "path_index")
    if path_index.get("state") != "PASS_TRADE_PATH_EVIDENCE_INDEX":
        raise core.PathPlannerError("PATH_INDEX_NOT_PASS")
    if int(path_index.get("hold_bundle_count") or 0) != 0:
        raise core.PathPlannerError("PATH_INDEX_HAS_HOLD_BUNDLES")
    triage = core.validate_triage(triage)
    ledger = core.validate_ledger(ledger)
    policy = core.validate_policy(policy)
    triage_rows = {str(row["strategy_id"]): row for row in triage["rows"]}
    ledger_rows = {str(row["strategy_id"]): row for row in ledger["rows"]}
    missing = sorted(set(triage_rows) - set(ledger_rows))
    if missing:
        raise core.PathPlannerError(f"TRIAGE_STRATEGY_MISSING_FROM_LEDGER:{','.join(missing)}")
    rows = [
        core.plan_strategy(triage_rows[strategy_id], ledger_rows[strategy_id], path_root, policy)
        for strategy_id in sorted(triage_rows)
    ]
    proposals = [row["next_candidate_proposal"] for row in rows if row.get("next_candidate_proposal")]
    if len(proposals) != len({(row["strategy_id"], row["axis"], row["candidate_id"]) for row in proposals}):
        raise core.PathPlannerError("PROPOSAL_DUPLICATE")
    result = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_PRE_SHADOW_PATH_OPTIMIZE_BATCH_PLAN" if proposals else "WAIT_NEW_PATH_EVIDENCE",
        "strategy_count": len(rows),
        "ledger_strategy_count": len(ledger_rows),
        "unreplayed_ledger_strategy_count": len(set(ledger_rows) - set(triage_rows)),
        "candidate_count": len(proposals),
        "hold_strategy_count": sum(str(row["state"]).startswith("HOLD_") for row in rows),
        "wait_strategy_count": sum(str(row["state"]).startswith("WAIT_") for row in rows),
        "ready_strategy_count": sum(row["state"] == "PASS_PRE_SHADOW_PATH_OPTIMIZE_PLAN" for row in rows),
        "rows": rows,
        "path_index_sha": path_index["index_sha"],
        "triage_sha": triage["triage_sha"],
        "search_ledger_sha": core.canonical_sha(ledger),
        "policy_sha": policy["policy_sha"],
        "triage_strategy_subset_of_ledger": True,
        "unreplayed_strategies_untouched": True,
        "single_axis_per_strategy": True,
        "automatic_replay_start_allowed": False,
        "ml_light_consumed": False,
        "failure_learning_consumed": False,
        "observer_connection_stage": "AFTER_REAL_SHADOW300_AND_100C_BURNIN",
        "runtime_bridge_allowed": False,
        "paper_30d_allowed": False,
        "live_activation_allowed": False,
        "order_submission_allowed": False,
        "next": "AI_ROUTER_THEN_ISOLATED_REPLAY" if proposals else "WAIT_NEW_PATH_EVIDENCE",
        **core.SAFETY,
    }
    result["plan_sha"] = core.canonical_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path-index", type=Path, required=True)
    parser.add_argument("--path-root", type=Path, required=True)
    parser.add_argument("--triage", type=Path, required=True)
    parser.add_argument("--search-ledger", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_plan(
        path_index=core.read_json(args.path_index),
        path_root=args.path_root,
        triage=core.read_json(args.triage),
        ledger=core.read_json(args.search_ledger),
        policy=core.read_json(args.policy),
    )
    core.write_json(args.out, result)
    print(result["state"], "strategies=", result["strategy_count"], "candidates=", result["candidate_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
