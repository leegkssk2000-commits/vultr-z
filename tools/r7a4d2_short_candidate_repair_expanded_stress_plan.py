#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


COST_AXIS_COUNT = 3
PERTURBATION_AXIS_COUNT = 2
AXIS_MULTIPLIER = COST_AXIS_COUNT * PERTURBATION_AXIS_COUNT
EXPECTED_BUCKET_COUNTS = {
    "baseline_trend_down": 12,
    "grid_rebalance_range": 0,
    "scalp_snap_trend_up": 12,
    "vol_spike_fade_shock_recovery": 4,
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def bucket_rows(expansion: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("bucket") or ""): row
        for row in expansion.get("bucket_expansion_results", [])
        if isinstance(row, dict)
    }


def candidate_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        str(row.get("bucket") or ""),
        str(row.get("scenario_id") or ""),
        str(row.get("strategy_id") or ""),
        int(row.get("bar_index", -1)),
    )


def validate_candidate(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    candidate_id = str(row.get("candidate_id") or "")
    if not candidate_id:
        errors.append("CANDIDATE_ID_MISSING")
    if not bool(row.get("discovery_only")):
        errors.append("DISCOVERY_ONLY_FALSE")
    start = int(row.get("start_row", -1))
    stop = int(row.get("end_row_exclusive", -1))
    if start < 0 or stop - start != 320:
        errors.append(f"SEGMENT_GEOMETRY_INVALID:{start}:{stop}")
    bar_index = int(row.get("bar_index", -1))
    evaluation_index = int(row.get("evaluation_index", -1))
    if not (320 <= bar_index < 640):
        errors.append(f"BAR_INDEX_OUTSIDE_PREROLL_SAMPLE:{bar_index}")
    if evaluation_index != bar_index - 320:
        errors.append(f"EVALUATION_LINEAGE_INVALID:{bar_index}:{evaluation_index}")
    source_sha = str(row.get("source_sha256") or "")
    if len(source_sha) != 64:
        errors.append("SOURCE_SHA_INVALID")
    for field in ("bucket", "scenario_id", "strategy_id", "segment_id", "regime", "source_path"):
        if not str(row.get(field) or ""):
            errors.append(f"FIELD_MISSING:{field}")
    return errors


def build_plan(
    expansion: dict[str, Any],
    prior_stress: dict[str, Any],
    allowlist: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if expansion.get("state") != "PASS_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES":
        blockers.append("MARKET_SEGMENT_EXPANSION_NOT_PASS")
    if int(expansion.get("blocker_count", -1)) != 0:
        blockers.append("MARKET_SEGMENT_EXPANSION_BLOCKED")
    if not bool(expansion.get("baseline_expansion_ready")):
        blockers.append("BASELINE_EXPANSION_NOT_READY")
    if int(expansion.get("mutation_path_count", -1)) != 0:
        blockers.append("EXPANSION_MUTATION_DETECTED")
    if int(expansion.get("side_effect_attempt_count", -1)) != 0:
        blockers.append("EXPANSION_SIDE_EFFECT_DETECTED")
    if expansion.get("source_registry_parity") is not True:
        blockers.append("EXPANSION_SOURCE_REGISTRY_PARITY_FAILED")
    if prior_stress.get("state") != "PASS_SHORT_ADMISSION_CANDIDATE_STRESS_66":
        blockers.append("PRIOR_STRESS66_NOT_PASS")
    if int(prior_stress.get("baseline_parity_failure_count", -1)) != 0:
        blockers.append("PRIOR_STRESS66_BASELINE_PARITY_FAILED")
    if allowlist.get("state") != "PASS_SHORT_ADMISSION_ALLOWLIST_PLAN":
        blockers.append("ALLOWLIST_PLAN_INVALID")
    if len(allowlist.get("negative_pair_blocks", [])) != 14:
        blockers.append("NEGATIVE_PAIR_BLOCK_SET_INVALID")

    rows_by_bucket = bucket_rows(expansion)
    selected: list[dict[str, Any]] = []
    bucket_summary: list[dict[str, Any]] = []
    for bucket, expected_count in EXPECTED_BUCKET_COUNTS.items():
        row = rows_by_bucket.get(bucket, {})
        candidates = [item for item in row.get("selected_candidates", []) if isinstance(item, dict)]
        observed_count = int(row.get("selected_candidate_count", len(candidates)))
        if observed_count != expected_count or len(candidates) != expected_count:
            blockers.append(f"BUCKET_CANDIDATE_COUNT_INVALID:{bucket}:{observed_count}:{len(candidates)}:{expected_count}")
        unique_segments = len({str(item.get("segment_id") or "") for item in candidates})
        unique_sources = len({str(item.get("source_path") or "") for item in candidates})
        if unique_segments != int(row.get("selected_unique_segment_count", unique_segments)):
            blockers.append(f"BUCKET_UNIQUE_SEGMENT_PARITY_FAILED:{bucket}")
        if unique_sources != int(row.get("selected_unique_source_count", unique_sources)):
            blockers.append(f"BUCKET_UNIQUE_SOURCE_PARITY_FAILED:{bucket}")
        segment_counts = Counter(str(item.get("segment_id") or "") for item in candidates)
        max_segment_count = max(segment_counts.values()) if candidates else 0
        max_segment_share = max_segment_count / len(candidates) if candidates else 0.0
        bucket_summary.append({
            "bucket": bucket,
            "strategy_id": str(row.get("strategy_id") or ""),
            "regime": str(row.get("regime") or ""),
            "candidate_count": len(candidates),
            "unique_segment_count": unique_segments,
            "unique_source_count": unique_sources,
            "candidate_count_by_segment": dict(sorted(segment_counts.items())),
            "max_segment_count": max_segment_count,
            "max_segment_share": round(max_segment_share, 10),
        })
        for candidate in candidates:
            item = dict(candidate)
            item["repair_stage"] = "R7.A4D2_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN"
            item["production_eligible"] = False
            selected.append(item)

    expected_total = sum(EXPECTED_BUCKET_COUNTS.values())
    keys = [candidate_key(row) for row in selected]
    ids = [str(row.get("candidate_id") or "") for row in selected]
    if len(selected) != expected_total or len(set(keys)) != expected_total or len(set(ids)) != expected_total:
        blockers.append(f"EXPANDED_CANDIDATE_SET_INVALID:{len(selected)}:{len(set(keys))}:{len(set(ids))}:{expected_total}")
    for row in selected:
        errors = validate_candidate(row)
        if errors:
            blockers.append(f"CANDIDATE_LINEAGE_INVALID:{row.get('candidate_id')}:{'|'.join(errors)}")

    summary_by_bucket = {row["bucket"]: row for row in bucket_summary}
    baseline = summary_by_bucket.get("baseline_trend_down", {})
    scalp = summary_by_bucket.get("scalp_snap_trend_up", {})
    vol = summary_by_bucket.get("vol_spike_fade_shock_recovery", {})
    if int(baseline.get("unique_segment_count", 0)) != 12 or int(baseline.get("unique_source_count", 0)) < 3:
        blockers.append("BASELINE_DIVERSITY_GATE_FAILED")
    if int(scalp.get("unique_segment_count", 0)) < 10 or int(scalp.get("max_segment_count", 999)) > 2:
        blockers.append("SCALP_DIVERSITY_GATE_FAILED")
    if int(vol.get("unique_segment_count", 0)) != 4:
        blockers.append("VOL_DISCOVERY_DIVERSITY_GATE_FAILED")

    execution_target = len(selected) * AXIS_MULTIPLIER
    repair_tracks = [
        {
            "bucket": "baseline_trend_down",
            "strategy_id": "grid_rebalance",
            "candidate_count": 12,
            "mode": "expanded_economic_stress",
            "pre_stress_repairs": [
                "candidate_id_dedup_locked",
                "one_selected_signal_per_segment_locked",
                "cost_edge_floor_audit",
                "cooldown_need_observer_only",
            ],
            "promotion_posture": "STRATEGY_LEVEL_GRID_QUARANTINE_RELEASE_REVIEW_REQUIRED",
        },
        {
            "bucket": "scalp_snap_trend_up",
            "strategy_id": "scalp_snap",
            "candidate_count": 12,
            "mode": "latency_and_fill_window_causality_stress",
            "pre_stress_repairs": [
                "signal_reproduction_separated_from_fill_completion",
                "invalid_geometry_separated_from_no_close",
                "same_segment_share_capped_at_two_of_twelve",
            ],
            "promotion_posture": "ELIGIBLE_ONLY_IF_ALL_72_CELLS_REPRODUCE_AND_CLOSE",
        },
        {
            "bucket": "vol_spike_fade_shock_recovery",
            "strategy_id": "vol_spike_fade",
            "candidate_count": 4,
            "mode": "shock_phase_context_diagnostic_stress",
            "pre_stress_repairs": [
                "shock_phase_metrics_bound_to_each_candidate",
                "duplicate_candidate_suppression_locked",
                "cooldown_need_observer_only",
            ],
            "promotion_posture": "DIAGNOSTIC_ONLY_UNTIL_INDEPENDENT_CANDIDATES_GE_12",
        },
        {
            "bucket": "grid_rebalance_range",
            "strategy_id": "grid_rebalance",
            "candidate_count": 0,
            "mode": "coverage_hold",
            "pre_stress_repairs": ["retain_quarantine", "do_not_synthesize_missing_range_samples"],
            "promotion_posture": "BLOCKED_NO_COVERAGE",
        },
    ]

    common_gate = {
        "all_cells_completed": True,
        "failed_cell_count": 0,
        "invalid_geometry_count": 0,
        "source_registry_parity": True,
        "mutation_path_count": 0,
        "side_effect_attempt_count": 0,
        "profit_factor_min_exclusive": 1.25,
        "expectancy_r_min_exclusive": 0.15,
        "worst_cost_axis_net_return_positive": True,
        "worst_perturbation_axis_net_return_positive": True,
        "baseline_cost0_perturb0_candidate_reproduction_count": len(selected),
    }
    plan = {
        "schema": "r7a4d2_short_candidate_repair_expanded_stress_plan_v1",
        "official_stage": "R7.A4D2_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN",
        "state": "PASS_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN" if not blockers else "HOLD_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN_INPUT",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "policy": {
            "loss_cap_r": 0.75,
            "full_tp_r": 2.5,
            "raw_strategy_sl_tp_preserved": True,
            "production_admission_expansion_allowed": False,
            "entry_threshold_relaxation_allowed": False,
            "strategy_mutation_allowed": False,
            "grid_rebalance_strategy_quarantined": True,
            "negative_pair_block_count": 14,
        },
        "bucket_counts": EXPECTED_BUCKET_COUNTS,
        "expanded_candidate_count": len(selected),
        "cost_axis_count": COST_AXIS_COUNT,
        "perturbation_axis_count": PERTURBATION_AXIS_COUNT,
        "expanded_stress_execution_target_count": execution_target,
        "candidate_manifest_sha256": canonical_hash(selected),
        "bucket_summary": bucket_summary,
        "repair_tracks": repair_tracks,
        "expanded_stress_candidates": selected,
        "promotion_gates": {
            "common": common_gate,
            "baseline_trend_down": {
                "minimum_independent_closed_trade_count": 12,
                "minimum_unique_segment_count": 12,
                "stress_cell_count": 72,
                "automatic_production_promotion_allowed": False,
                "grid_quarantine_release_review_required": True,
            },
            "scalp_snap_trend_up": {
                "minimum_independent_closed_trade_count": 12,
                "minimum_unique_segment_count": 10,
                "stress_cell_count": 72,
                "signal_reproduction_rate_required": 1.0,
            },
            "vol_spike_fade_shock_recovery": {
                "stress_cell_count": 24,
                "promotion_allowed": False,
                "minimum_independent_candidate_count_before_promotion": 12,
            },
        },
        "next_stage": "R7.A4D2_SHORT_EXPANDED_CANDIDATE_STRESS_168" if not blockers else "R7.A4D2_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN",
    }
    return plan, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    expansion = load_json(root / "runtime/r7a4d2_market_segment_expansion_for_short_candidates/market_segment_expansion_v1.json")
    prior_stress = load_json(root / "runtime/r7a4d2_short_admission_candidate_stress_66/stress66_proof_v1.json")
    allowlist = load_json(root / "runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json")
    plan, blockers = build_plan(expansion, prior_stress, allowlist)
    output = root / "runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json"
    atomic_json(output, plan)

    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("EXPANDED_CANDIDATE_COUNT=" + str(plan["expanded_candidate_count"]))
    print("EXPANDED_BUCKET_COUNTS=" + json.dumps(plan["bucket_counts"], sort_keys=True))
    print("EXPANDED_STRESS_EXECUTION_TARGET_COUNT=" + str(plan["expanded_stress_execution_target_count"]))
    print("CANDIDATE_MANIFEST_SHA256=" + str(plan["candidate_manifest_sha256"]))
    print("GRID_REBALANCE_STRATEGY_QUARANTINED=true")
    print("PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false")
    print("REPAIR_TRACKS=" + json.dumps(plan["repair_tracks"], ensure_ascii=False, sort_keys=True))
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
