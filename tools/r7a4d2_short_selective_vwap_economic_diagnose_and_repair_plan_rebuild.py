#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

VERIFIED_DIR = Path("runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair")
REBASELINE_DIR = Path("runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution")
PLAN_DIR = Path("runtime/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan")
OUTPUT_DIR = Path("runtime/r7a4d2_short_selective_vwap_economic_diagnose_and_repair_plan_rebuild")

EXPECTED_LANES = {
    "strategy:vwap_revert:1m": "1m",
    "strategy:vwap_revert:5m": "5m",
    "strategy:vwap_revert:15m": "15m",
}
EXPECTED_ARM_COUNT = 9
EXPECTED_STRESS_CELL_COUNT = 54


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            rows.append(value)
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def first_number(row: dict[str, Any], names: Iterable[str]) -> float | None:
    for name in names:
        number = finite_number(row.get(name))
        if number is not None:
            return number
    return None


def numeric_values(rows: Iterable[dict[str, Any]], names: Iterable[str]) -> list[float]:
    values: list[float] = []
    for row in rows:
        number = first_number(row, names)
        if number is not None:
            values.append(number)
    return values


def median_or_none(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 10) if values else None


def quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 10)
    position = (len(ordered) - 1) * fraction
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return round(ordered[low], 10)
    weight = position - low
    return round(ordered[low] * (1.0 - weight) + ordered[high] * weight, 10)


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def signal_key(row: dict[str, Any]) -> tuple[str, int, float]:
    return (
        str(row.get("segment_id") or ""),
        int(row.get("signal_bar_index") or -1),
        float(row.get("entry_timestamp") or row.get("signal_timestamp") or 0.0),
    )


def severe_positive(row: dict[str, Any]) -> bool | None:
    explicit = row.get("severe_net_available_r_positive")
    if isinstance(explicit, bool):
        return explicit
    net_r = first_number(row, ("severe_net_available_r", "net_available_r", "net_r"))
    if net_r is not None:
        return net_r > 0.0
    return None


def lane_role(signal_count: int, severe_positive_rate: float) -> str:
    if signal_count >= 30 and severe_positive_rate >= 40.0:
        return "PRIMARY_EXECUTION_CANDIDATE"
    if signal_count >= 24 and severe_positive_rate >= 30.0:
        return "CONTEXT_OR_FALLBACK_CANDIDATE"
    return "TRIGGER_ONLY_OR_REJECT"


def regime_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("regime") or "unknown")].append(row)
    result: dict[str, Any] = {}
    for regime, group in sorted(grouped.items()):
        outcomes = [value for value in (severe_positive(row) for row in group) if value is not None]
        result[regime] = {
            "geometry_row_count": len(group),
            "signal_count": len({signal_key(row) for row in group}),
            "severe_positive_rate_pct": round(100.0 * sum(outcomes) / len(outcomes), 6) if outcomes else None,
        }
    return result


def pick_allowed_regimes(stats: dict[str, Any]) -> list[str]:
    ranked: list[tuple[float, int, str]] = []
    for regime, row in stats.items():
        rate = finite_number(row.get("severe_positive_rate_pct"))
        signals = int(row.get("signal_count") or 0)
        if rate is not None:
            ranked.append((rate, signals, regime))
    ranked.sort(reverse=True)
    selected = [regime for rate, signals, regime in ranked if rate >= 35.0 and signals >= 4][:2]
    return selected or [name for name in ("range", "shock_recovery") if name in stats]


def build_lane_diagnosis(lane_id: str, rows: list[dict[str, Any]], by_lane: dict[str, Any]) -> dict[str, Any]:
    summary = by_lane.get(lane_id) if isinstance(by_lane.get(lane_id), dict) else {}
    unique_signals = {signal_key(row) for row in rows}
    signal_count = int(summary.get("semantic_eligible_signal_count") or len(unique_signals))
    severe_rate = finite_number(summary.get("severe_net_available_r_positive_rate_pct"))
    if severe_rate is None:
        outcomes = [value for value in (severe_positive(row) for row in rows) if value is not None]
        severe_rate = 100.0 * sum(outcomes) / len(outcomes) if outcomes else 0.0

    mfe = numeric_values(rows, ("full_forward_mfe_pct", "mfe_pct", "maximum_favorable_excursion_pct"))
    mae = numeric_values(rows, ("full_forward_mae_pct", "mae_pct", "maximum_adverse_excursion_pct"))
    stop_distance = numeric_values(rows, ("structural_stop_distance_pct", "stop_distance_pct"))
    friction_r = numeric_values(rows, ("severe_friction_r", "friction_r", "cost_r"))
    time_to_mfe = numeric_values(rows, ("time_to_mfe_bars", "mfe_bar_distance", "bars_to_mfe"))
    deviation = numeric_values(rows, ("entry_vwap_distance_pct", "vwap_distance_pct", "entry_deviation_pct"))
    stats = regime_stats(rows)
    role = lane_role(signal_count, float(severe_rate))

    stop_q65 = quantile(stop_distance, 0.65)
    mfe_q50 = quantile(mfe, 0.50)
    time_q75 = quantile(time_to_mfe, 0.75)
    deviation_q60 = quantile([abs(value) for value in deviation], 0.60)
    fallback_stop = max((mfe_q50 or 0.5) * 0.55, 0.25)

    return {
        "lane_id": lane_id,
        "timeframe": EXPECTED_LANES[lane_id],
        "lane_role": role,
        "geometry_row_count": len(rows),
        "signal_count": signal_count,
        "severe_positive_rate_pct": round(float(severe_rate), 6),
        "median_full_forward_mfe_pct": median_or_none(mfe),
        "median_full_forward_mae_pct": median_or_none(mae),
        "median_structural_stop_distance_pct": median_or_none(stop_distance),
        "median_severe_friction_r": median_or_none(friction_r),
        "median_time_to_mfe_bars": median_or_none(time_to_mfe),
        "regime_stats": stats,
        "recommended_allowed_regimes": pick_allowed_regimes(stats),
        "derived_parameters": {
            "minimum_entry_deviation_pct": round(clamp(deviation_q60 or fallback_stop, 0.15, 3.0), 6),
            "structural_stop_distance_pct": round(clamp(stop_q65 or fallback_stop, 0.20, 3.0), 6),
            "partial_trigger_mfe_pct": round(clamp((mfe_q50 or 0.5) * 0.45, 0.10, 1.5), 6),
            "timeout_bars": int(clamp(math.ceil(time_q75 or 6.0), 3, 24)),
        },
    }


def repair_arms(diagnosis: dict[str, Any]) -> list[dict[str, Any]]:
    lane_id = str(diagnosis["lane_id"])
    timeframe = str(diagnosis["timeframe"])
    parameters = dict(diagnosis["derived_parameters"])
    regimes = list(diagnosis.get("recommended_allowed_regimes") or [])
    standalone_allowed = diagnosis["lane_role"] == "PRIMARY_EXECUTION_CANDIDATE"
    return [
        {
            "arm_id": f"{lane_id}:native_reclaim_entry",
            "lane_id": lane_id,
            "timeframe": timeframe,
            "axis": "ENTRY",
            "single_axis_only": True,
            "standalone_promotion_allowed": standalone_allowed,
            "design": {
                "native_signal_required": True,
                "minimum_entry_deviation_pct": parameters["minimum_entry_deviation_pct"],
                "close_back_toward_vwap_required": True,
                "bearish_reclaim_confirmation_required": True,
                "duplicate_liquidity_event_entry_blocked": True,
            },
        },
        {
            "arm_id": f"{lane_id}:regime_conditioned_reclaim",
            "lane_id": lane_id,
            "timeframe": timeframe,
            "axis": "REGIME",
            "single_axis_only": True,
            "standalone_promotion_allowed": standalone_allowed,
            "design": {
                "native_entry_unchanged": True,
                "allowed_regimes": regimes,
                "trend_up_chase_veto": True,
                "post_shock_cooldown_bars": max(2, int(parameters["timeout_bars"] // 3)),
            },
        },
        {
            "arm_id": f"{lane_id}:vwap_target_timeout_exit",
            "lane_id": lane_id,
            "timeframe": timeframe,
            "axis": "EXIT",
            "single_axis_only": True,
            "standalone_promotion_allowed": standalone_allowed,
            "design": {
                "native_entry_unchanged": True,
                "structural_stop_distance_pct": parameters["structural_stop_distance_pct"],
                "partial_trigger_mfe_pct": parameters["partial_trigger_mfe_pct"],
                "primary_exit": "VWAP_TOUCH_OR_CLOSE_CROSS",
                "timeout_bars": parameters["timeout_bars"],
                "stop_first_collision": True,
            },
        },
    ]


def self_test() -> int:
    rows = [
        {"segment_id": "a", "signal_bar_index": 1, "entry_timestamp": 1, "regime": "range", "full_forward_mfe_pct": 1.0, "full_forward_mae_pct": 0.3, "structural_stop_distance_pct": 0.4, "severe_net_available_r": 0.2},
        {"segment_id": "b", "signal_bar_index": 2, "entry_timestamp": 2, "regime": "range", "full_forward_mfe_pct": 0.8, "full_forward_mae_pct": 0.4, "structural_stop_distance_pct": 0.5, "severe_net_available_r": -0.1},
    ]
    diagnosis = build_lane_diagnosis("strategy:vwap_revert:5m", rows, {})
    arms = repair_arms(diagnosis)
    assert len(arms) == 3
    assert {row["axis"] for row in arms} == {"ENTRY", "REGIME", "EXIT"}
    assert all(row["single_axis_only"] is True for row in arms)
    print("STATE=PASS_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="SELF_TEST")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    required = {
        "verified_aggregate": root / VERIFIED_DIR / "verified_aggregate_v3.json",
        "verified_plan": root / VERIFIED_DIR / "verified_effective_execution_plan_v3.json",
        "verification_proof": root / VERIFIED_DIR / "proof_v3.json",
        "merged_geometry": root / REBASELINE_DIR / "merged_signal_geometry_v2.jsonl",
        "merged_scans": root / REBASELINE_DIR / "merged_scan_results_v2.jsonl",
        "snapshot_manifest": root / PLAN_DIR / "snapshot_manifest_v1.json",
    }
    blockers: list[str] = []
    for label, path in required.items():
        if not path.is_file():
            blockers.append(f"REQUIRED_EVIDENCE_MISSING:{label}:{path}")
    if blockers:
        print("STATE=HOLD_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    verified = load_json(required["verified_aggregate"])
    effective = load_json(required["verified_plan"])
    proof = load_json(required["verification_proof"])
    snapshot = load_json(required["snapshot_manifest"])
    scans = read_jsonl(required["merged_scans"])
    geometry = read_jsonl(required["merged_geometry"])

    if verified.get("state") != "PASS_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR":
        blockers.append("PRIOR_VERIFICATION_NOT_PASS")
    if int(verified.get("blocker_count", -1)) != 0:
        blockers.append("PRIOR_VERIFICATION_BLOCKED")
    if verified.get("preserved_geometry_content_equal") is not True:
        blockers.append("PRESERVED_GEOMETRY_NOT_EQUAL")
    if verified.get("replacement_geometry_merge_equal") is not True:
        blockers.append("REPLACEMENT_GEOMETRY_NOT_EQUAL")
    if proof.get("prior_evidence_reexecuted") is not False:
        blockers.append("PRIOR_EVIDENCE_REEXECUTION_FLAG_INVALID")

    raw_evidence = effective.get("raw_geometry_evidence") if isinstance(effective.get("raw_geometry_evidence"), dict) else {}
    if str(raw_evidence.get("scan_results_sha256") or "") != sha256_file(required["merged_scans"]):
        blockers.append("MERGED_SCAN_SHA_MISMATCH")
    if str(raw_evidence.get("signal_geometry_sha256") or "") != sha256_file(required["merged_geometry"]):
        blockers.append("MERGED_GEOMETRY_SHA_MISMATCH")

    lane_scan_ids = {str(row.get("lane_id") or "") for row in scans if str(row.get("strategy_id") or "") == "vwap_revert"}
    if lane_scan_ids != set(EXPECTED_LANES):
        blockers.append(f"VWAP_LANE_SET_INVALID:{sorted(lane_scan_ids)}")
    if any(row.get("completed") is not True for row in scans if str(row.get("lane_id") or "") in EXPECTED_LANES):
        blockers.append("VWAP_SCAN_FAILURE_PRESENT")

    snapshots = [row for row in snapshot.get("snapshots", []) if isinstance(row, dict)]
    if len(snapshots) != 1 or str(snapshots[0].get("strategy_id") or "") != "vwap_revert":
        blockers.append("VWAP_SNAPSHOT_INVALID")
    snapshot_sha = str(snapshots[0].get("snapshot_sha256") or "") if snapshots else ""
    if not snapshot_sha:
        blockers.append("VWAP_SNAPSHOT_SHA_MISSING")

    if blockers:
        unique = list(dict.fromkeys(blockers))
        print("STATE=HOLD_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_INPUT")
        print("BLOCKER_COUNT=" + str(len(unique)))
        print("BLOCKERS=" + json.dumps(unique, ensure_ascii=False))
        print("RC=2")
        return 2

    by_lane = verified.get("by_lane") if isinstance(verified.get("by_lane"), dict) else {}
    geometry_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in geometry:
        lane_id = str(row.get("lane_id") or "")
        if lane_id in EXPECTED_LANES:
            geometry_by_lane[lane_id].append(row)

    diagnosis_rows = [build_lane_diagnosis(lane_id, geometry_by_lane[lane_id], by_lane) for lane_id in sorted(EXPECTED_LANES)]
    role_rank = {"PRIMARY_EXECUTION_CANDIDATE": 3, "CONTEXT_OR_FALLBACK_CANDIDATE": 2, "TRIGGER_ONLY_OR_REJECT": 1}
    ranked = sorted(
        diagnosis_rows,
        key=lambda row: (role_rank[str(row["lane_role"])], float(row["severe_positive_rate_pct"]), int(row["signal_count"])),
        reverse=True,
    )
    primary = ranked[0]
    all_arms = [arm for row in diagnosis_rows for arm in repair_arms(row)]
    if len(all_arms) != EXPECTED_ARM_COUNT:
        blockers.append(f"REPAIR_ARM_COUNT_INVALID:{len(all_arms)}")
    if len({row["arm_id"] for row in all_arms}) != EXPECTED_ARM_COUNT:
        blockers.append("REPAIR_ARM_ID_DUPLICATE")

    primary_lane = str(primary["lane_id"])
    primary_is_promotable = str(primary["lane_role"]) == "PRIMARY_EXECUTION_CANDIDATE"
    plan = {
        "schema": "r7a4d2_short_selective_vwap_economic_diagnose_and_repair_plan_rebuild_v1",
        "official_stage": "R7.A4D2_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD",
        "state": "PASS_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD" if not blockers else "HOLD_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD",
        "target_commit": args.target_sha,
        "strategy_id": "vwap_revert",
        "snapshot_sha256": snapshot_sha,
        "affected_lane_ids": sorted(EXPECTED_LANES),
        "lane_count": len(diagnosis_rows),
        "repair_arm_count": len(all_arms),
        "stress_cell_count": EXPECTED_STRESS_CELL_COUNT,
        "cost_profile_count": 3,
        "timing_perturbation_count": 2,
        "diagnosis_rows": diagnosis_rows,
        "lane_role_histogram": dict(sorted(Counter(str(row["lane_role"]) for row in diagnosis_rows).items())),
        "selected_primary_lane_id": primary_lane,
        "selected_primary_timeframe": str(primary["timeframe"]),
        "primary_standalone_promotion_allowed": primary_is_promotable,
        "repair_arms": all_arms,
        "execution_contract": {
            "native_signal_only": True,
            "single_axis_arm_only": True,
            "future_validation_selection_allowed": False,
            "stop_first_collision_required": True,
            "overlapping_position_allowed": False,
            "strategy_mutation_allowed": False,
            "registry_mutation_allowed": False,
            "shadow_start_allowed": False,
            "paper_live_order_allowed": False,
            "survivor_gate": {
                "severe_trade_count_min": 8,
                "profit_factor_min_exclusive": 1.0,
                "expectancy_r_min_exclusive": 0.0,
                "net_pnl_pct_min_exclusive": 0.0,
                "positive_stress_cell_min": 4,
                "max_drawdown_must_not_worsen_vs_native": True,
            },
        },
        "broader_redesign_status": {
            "all_strategy_redesign_complete": False,
            "identity_clean_strategy_count_preserved": 10,
            "vwap_lineage_repaired": True,
            "remaining_strategy_family_rebuild_pending": True,
            "resume_after_vwap_selective_execution": "R7.A4D2_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_GENERATION_2",
        },
        "blocker_count": len(blockers),
        "blockers": blockers,
        "next_stage": (
            "R7.A4D2_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54"
            if not blockers
            else "R7.A4D2_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_REPAIR_PLAN_DIAGNOSE"
        ),
    }

    output = root / OUTPUT_DIR
    atomic_json(output / "economic_diagnose_v1.json", {
        "schema": "r7a4d2_short_selective_vwap_economic_diagnose_v1",
        "state": plan["state"],
        "target_commit": args.target_sha,
        "strategy_id": "vwap_revert",
        "diagnosis_rows": diagnosis_rows,
        "selected_primary_lane_id": primary_lane,
        "selected_primary_timeframe": str(primary["timeframe"]),
        "blockers": blockers,
    })
    atomic_json(output / "repair_plan_v1.json", plan)

    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("VWAP_LANE_COUNT=" + str(len(diagnosis_rows)))
    print("VWAP_REPAIR_ARM_COUNT=" + str(len(all_arms)))
    print("VWAP_STRESS_CELL_COUNT=" + str(EXPECTED_STRESS_CELL_COUNT))
    print("LANE_ROLE_HISTOGRAM=" + json.dumps(plan["lane_role_histogram"], sort_keys=True))
    print("SELECTED_PRIMARY_LANE_ID=" + primary_lane)
    print("SELECTED_PRIMARY_TIMEFRAME=" + str(primary["timeframe"]))
    print("PRIMARY_STANDALONE_PROMOTION_ALLOWED=" + str(primary_is_promotable).lower())
    print("VWAP_DIAGNOSIS_ROWS=" + json.dumps(diagnosis_rows, ensure_ascii=False, sort_keys=True))
    print("VWAP_REPAIR_ARMS=" + json.dumps(all_arms, ensure_ascii=False, sort_keys=True))
    print("ALL_STRATEGY_REDESIGN_COMPLETE=false")
    print("REMAINING_STRATEGY_FAMILY_REBUILD_PENDING=true")
    print("ECONOMIC_DIAGNOSE_JSON=" + str(output / "economic_diagnose_v1.json"))
    print("REPAIR_PLAN_JSON=" + str(output / "repair_plan_v1.json"))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
