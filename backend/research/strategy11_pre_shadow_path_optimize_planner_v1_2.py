from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Mapping

from backend.research import strategy11_pre_shadow_path_optimize_planner_v1 as core
from backend.research import strategy11_pre_shadow_path_optimize_planner_v1_1 as subset

SCHEMA = "strategy11.pre_shadow_path_optimize_plan.v1.2"
VERSION = "STRATEGY11_PRE_SHADOW_PATH_OPTIMIZE_PLANNER_V1_2"


def select_candidate(
    fingerprint: Mapping[str, Any],
    *,
    strategy_id: str,
    basis_variant_id: str,
    basis_bundle: Mapping[str, Any],
    ledger_row: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any] | None:
    excluded = {
        str(value)
        for key in (
            "tested_candidate_ids",
            "selected_candidate_ids",
            "ai_rejected_candidate_ids",
            "ai_advisory_held_candidate_ids",
            "family_binding_wait_candidate_ids",
        )
        for value in (ledger_row.get(key) or [])
    }
    generation = core.normalized_generation_count(ledger_row)
    remaining = {str(value).upper() for value in ledger_row.get("remaining_axes") or []}
    next_axis = str(ledger_row.get("next_axis") or "").upper()
    for catalog_row in policy["candidate_catalog"][fingerprint["fingerprint"]]:
        candidate_id = catalog_row["candidate_id"]
        axis = catalog_row["axis"]
        if candidate_id in excluded:
            continue
        if generation.get(axis, 0) >= policy["max_axis_generations_per_data_epoch"]:
            continue
        if remaining and axis not in remaining and axis != next_axis:
            continue
        proposal = {
            "strategy_id": strategy_id,
            "basis_variant_id": basis_variant_id,
            "basis_bundle_sha": basis_bundle["bundle_sha"],
            "basis_source_sha": basis_bundle["source_sha"],
            "candidate_id": candidate_id,
            "axis": axis,
            "parameters": copy.deepcopy(catalog_row["parameters"]),
            "why": catalog_row["why"],
            "failure_fingerprint": fingerprint["fingerprint"],
            "failure_support_sha": fingerprint["support_sha"],
            "generation": generation.get(axis, 0) + 1,
            "single_axis": True,
            "control_required": True,
            "independent_ab_required": True,
            "duplicate_zero_required": True,
            "observed_2x_cost_p95_funding_plus_one_required": True,
            "pareto_hard_risk_retention_required": True,
            "ai_router_stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
            "ai_router_plan_required": True,
            "ai_router_execute_required": True,
            "replay_required": True,
            "replay_started": False,
            "incumbent_retained": True,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        }
        proposal["candidate_sha"] = core.canonical_sha(proposal)
        return proposal
    return None


def build_plan(
    *,
    path_index: Mapping[str, Any],
    path_root: Path,
    triage: Mapping[str, Any],
    ledger: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    original = core.select_candidate
    core.select_candidate = select_candidate
    try:
        result = subset.build_plan(
            path_index=path_index,
            path_root=path_root,
            triage=triage,
            ledger=ledger,
            policy=policy,
        )
    finally:
        core.select_candidate = original
    result["schema_version"] = SCHEMA
    result["version"] = VERSION
    result["ai_rejected_candidates_excluded"] = True
    result["ai_advisory_held_candidates_excluded"] = True
    result["family_binding_wait_candidates_excluded"] = True
    result["plan_sha"] = core.canonical_sha({key: value for key, value in result.items() if key != "plan_sha"})
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
