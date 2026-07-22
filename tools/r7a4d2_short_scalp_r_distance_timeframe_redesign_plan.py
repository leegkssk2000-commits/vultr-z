#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any


SHORT_TARGET_STRATEGY_UNIVERSE_COUNT = 12
ACTIVE_REPAIR_STRATEGY_COUNT = 3
REDESIGN_STRATEGY_COUNT = 1
ARCHITECTURE_CANDIDATE_TARGET = 12
ARCHITECTURE_COUNT = 3
TARGET_CANDIDATE_COUNT = ARCHITECTURE_CANDIDATE_TARGET * ARCHITECTURE_COUNT
COST_AXIS_COUNT = 3
PERTURBATION_AXIS_COUNT = 2
TARGET_EXECUTION_CELL_COUNT = TARGET_CANDIDATE_COUNT * COST_AXIS_COUNT * PERTURBATION_AXIS_COUNT
ROBUST_FRICTION_CAP_R = 0.25
CONDITIONAL_FRICTION_CAP_R = 0.33
ABSOLUTE_FRICTION_CAP_R = 0.75


ARCHITECTURES = [
    {
        "architecture_id": "TF5_STRUCTURE_TF5_TRIGGER",
        "structure_timeframe": "5m",
        "trigger_timeframe": "5m",
        "candidate_target": ARCHITECTURE_CANDIDATE_TARGET,
        "discovery_target": 6,
        "validation_target": 6,
    },
    {
        "architecture_id": "TF15_STRUCTURE_TF15_TRIGGER",
        "structure_timeframe": "15m",
        "trigger_timeframe": "15m",
        "candidate_target": ARCHITECTURE_CANDIDATE_TARGET,
        "discovery_target": 6,
        "validation_target": 6,
    },
    {
        "architecture_id": "TF15_STRUCTURE_TF5_TRIGGER",
        "structure_timeframe": "15m",
        "trigger_timeframe": "5m",
        "candidate_target": ARCHITECTURE_CANDIDATE_TARGET,
        "discovery_target": 6,
        "validation_target": 6,
    },
]


TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def rounded(value: Any, digits: int = 10) -> float:
    return round(finite(value), digits)


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def required_raw_distance_pct(fee_bps_per_side: float, slippage_bps_per_side: float, friction_cap_r: float) -> float:
    if friction_cap_r <= 0:
        raise ValueError("FRICTION_CAP_R_INVALID")
    roundtrip_friction_pct = 2.0 * (fee_bps_per_side + slippage_bps_per_side) / 100.0
    return roundtrip_friction_pct / friction_cap_r


def normalize_timeframe(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace(" ", "")
    aliases = {
        "1": "1m", "1m": "1m", "1min": "1m", "1minute": "1m",
        "3": "3m", "3m": "3m", "3min": "3m",
        "5": "5m", "5m": "5m", "5min": "5m", "5minute": "5m",
        "15": "15m", "15m": "15m", "15min": "15m", "15minute": "15m",
        "30": "30m", "30m": "30m", "30min": "30m",
        "60": "1h", "1h": "1h", "60m": "1h", "1hour": "1h",
    }
    return aliases.get(text)


def infer_timeframe(frame: Any) -> str | None:
    for name in ("timeframe", "interval", "tf"):
        if name in frame.columns and not frame[name].dropna().empty:
            normalized = normalize_timeframe(frame[name].dropna().iloc[0])
            if normalized:
                return normalized
    if "__timestamp" not in frame.columns or len(frame) < 3:
        return None
    values = frame["__timestamp"].dropna().sort_values()
    if len(values) < 3:
        return None
    deltas = values.diff().dropna().dt.total_seconds()
    positive = [float(value) for value in deltas if finite(value) > 0]
    if not positive:
        return None
    median_seconds = statistics.median(positive)
    return min(TIMEFRAME_SECONDS, key=lambda key: abs(TIMEFRAME_SECONDS[key] - median_seconds))


def infer_symbol(frame: Any, source_path: str) -> str | None:
    for name in ("symbol", "ticker", "market", "instrument"):
        if name in frame.columns and not frame[name].dropna().empty:
            return str(frame[name].dropna().iloc[0]).upper()
    match = re.search(r"(?<![A-Z0-9])([A-Z]{2,12}(?:USDT|USD|BTC|ETH))(?![A-Z0-9])", source_path.upper())
    return match.group(1) if match else None


def inspect_market_sources(root: Path, runner: Any, market_entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for entry in market_entries:
        repo_path = str(entry.get("path") or "")
        try:
            repo_path = runner.safe_repo_path(repo_path)
            path = root / repo_path
            actual_sha = runner.sha256_file(path)
            expected_sha = str(entry.get("sha256") or "")
            if actual_sha is None or actual_sha != expected_sha:
                raise ValueError("FROZEN_SHA_MISMATCH")
            frame = runner.load_market_frame(path)
            if len(frame) < 640:
                raise ValueError(f"INSUFFICIENT_ROWS:{len(frame)}")
            timeframe = infer_timeframe(frame)
            if timeframe is None:
                raise ValueError("TIMEFRAME_UNRESOLVED")
            symbol = infer_symbol(frame, repo_path)
            timestamp_ready = "__timestamp" in frame.columns and not frame["__timestamp"].dropna().empty
            derivable: list[str] = []
            seconds = TIMEFRAME_SECONDS.get(timeframe)
            if seconds is not None and timestamp_ready:
                for target in ("5m", "15m"):
                    if TIMEFRAME_SECONDS[target] >= seconds and TIMEFRAME_SECONDS[target] % seconds == 0:
                        derivable.append(target)
            inventory.append({
                "source_path": repo_path,
                "source_sha256": actual_sha,
                "row_count": int(len(frame)),
                "symbol": symbol,
                "native_timeframe": timeframe,
                "timestamp_ready": bool(timestamp_ready),
                "derivable_timeframes": sorted(set(derivable)),
            })
        except Exception as exc:
            rejected.append({"path": repo_path, "reason": f"{type(exc).__name__}:{exc}"})
    inventory.sort(key=lambda row: (str(row.get("symbol") or ""), str(row.get("source_path") or "")))
    rejected.sort(key=lambda row: str(row.get("path") or ""))
    return inventory, rejected


def build_plan(
    feasibility: dict[str, Any],
    frozen_manifest: dict[str, Any],
    a4c_contract: dict[str, Any],
    a4d_contract: dict[str, Any],
    source_inventory: list[dict[str, Any]],
    rejected_sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    coverage_flags: list[str] = []

    if feasibility.get("state") != "PASS_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN":
        blockers.append("FEASIBILITY_PLAN_NOT_PASS")
    if int(feasibility.get("blocker_count", -1)) != 0:
        blockers.append("FEASIBILITY_PLAN_BLOCKED")
    if feasibility.get("next_stage") != "R7.A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN":
        blockers.append("FEASIBILITY_NEXT_STAGE_MISMATCH")
    if bool(feasibility.get("single_survivor_retest_allowed", True)):
        blockers.append("CURRENT_GEOMETRY_RETEST_UNEXPECTEDLY_ALLOWED")
    if bool(feasibility.get("current_geometry_feasible", True)):
        blockers.append("CURRENT_GEOMETRY_UNEXPECTEDLY_FEASIBLE")
    if feasibility.get("feasibility_classification") != "CURRENT_GEOMETRY_COST_R_INFEASIBLE":
        blockers.append("FEASIBILITY_CLASSIFICATION_MISMATCH")
    if int(feasibility.get("protected_mutation_path_count", -1)) != 0:
        blockers.append("FEASIBILITY_INPUT_MUTATION_DETECTED")

    survivor_id = str(feasibility.get("single_survivor_candidate_id") or "")
    if not survivor_id:
        blockers.append("DIAGNOSTIC_SURVIVOR_ID_MISSING")

    if frozen_manifest.get("state") != "PASS":
        blockers.append("FROZEN_INPUT_MANIFEST_NOT_PASS")
    category_inputs = frozen_manifest.get("category_inputs") if isinstance(frozen_manifest.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    if not market_entries:
        blockers.append("FROZEN_MARKET_SOURCE_ZERO")
    if rejected_sources:
        blockers.append(f"FROZEN_MARKET_SOURCE_REJECTED:{len(rejected_sources)}")

    if int(a4c_contract.get("expected_strategy_count", -1)) != 25:
        blockers.append("A4C_STRATEGY_UNIVERSE_INVALID")
    if int(a4d_contract.get("expected_strategy_count", -1)) != 25:
        blockers.append("A4D_STRATEGY_UNIVERSE_INVALID")

    cost_profiles = {
        str(row.get("id") or ""): row
        for row in a4d_contract.get("cost_profiles", [])
        if isinstance(row, dict) and row.get("id")
    }
    perturbations = {
        str(row.get("id") or ""): row
        for row in a4d_contract.get("perturbations", [])
        if isinstance(row, dict) and row.get("id")
    }
    if sorted(cost_profiles) != ["cost_profile_0", "cost_profile_1", "cost_profile_2"]:
        blockers.append("COST_PROFILE_CONTRACT_INVALID")
    if sorted(perturbations) != ["perturbation_0", "perturbation_1"]:
        blockers.append("PERTURBATION_CONTRACT_INVALID")

    distance_requirements: dict[str, dict[str, float]] = {}
    for cost_id, row in sorted(cost_profiles.items()):
        fee = finite(row.get("fee_bps_per_side"))
        slippage = finite(row.get("slippage_bps_per_side"))
        distance_requirements[cost_id] = {
            "fee_bps_per_side": rounded(fee),
            "slippage_bps_per_side": rounded(slippage),
            "conditional_required_raw_distance_pct": rounded(
                required_raw_distance_pct(fee, slippage, CONDITIONAL_FRICTION_CAP_R)
            ),
            "robust_required_raw_distance_pct": rounded(
                required_raw_distance_pct(fee, slippage, ROBUST_FRICTION_CAP_R)
            ),
        }

    available_timeframes = sorted({
        timeframe
        for row in source_inventory
        for timeframe in row.get("derivable_timeframes", [])
        if timeframe in {"5m", "15m"}
    })
    source_symbols = sorted({str(row.get("symbol") or "") for row in source_inventory if row.get("symbol")})
    source_paths = sorted({str(row.get("source_path") or "") for row in source_inventory if row.get("source_path")})
    if "5m" not in available_timeframes:
        coverage_flags.append("TF5_MARKET_LINEAGE_UNAVAILABLE")
    if "15m" not in available_timeframes:
        coverage_flags.append("TF15_MARKET_LINEAGE_UNAVAILABLE")
    if len(source_symbols) < 3:
        coverage_flags.append(f"SYMBOL_DIVERSITY_LT_3:{len(source_symbols)}")
    if len(source_paths) < 3:
        coverage_flags.append(f"SOURCE_DIVERSITY_LT_3:{len(source_paths)}")

    severe = distance_requirements.get("cost_profile_2", {})
    conditional_severe_distance = finite(severe.get("conditional_required_raw_distance_pct"))
    robust_severe_distance = finite(severe.get("robust_required_raw_distance_pct"))
    if conditional_severe_distance <= 0 or robust_severe_distance <= conditional_severe_distance:
        blockers.append("SEVERE_DISTANCE_REQUIREMENT_INVALID")

    architectures = []
    for row in ARCHITECTURES:
        item = dict(row)
        item.update({
            "strategy_id": "scalp_snap",
            "side": "short",
            "canonical_entry_threshold_relaxation_allowed": False,
            "candidate_signal_source": "canonical_scalp_snap_short_signal_only",
            "structure_stop_rule": "pre_entry_confirmed_swing_high_distance_only",
            "blind_stop_widening_allowed": False,
            "minimum_natural_raw_distance_pct": rounded(conditional_severe_distance),
            "robust_natural_raw_distance_pct": rounded(robust_severe_distance),
            "full_tp_r": 2.5,
            "loss_cap_r": 0.75,
            "selection_order": "chronological_then_source_symbol_round_robin",
            "future_outcome_selection_allowed": False,
        })
        architectures.append(item)

    plan_ready = not blockers and not coverage_flags
    if blockers:
        next_stage = "R7.A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN"
    elif not plan_ready:
        next_stage = "R7.A4D2_SHORT_SCALP_TIMEFRAME_MARKET_COVERAGE_CLOSURE"
    else:
        next_stage = "R7.A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36"

    plan = {
        "schema": "r7a4d2_short_scalp_r_distance_timeframe_redesign_plan_v1",
        "official_stage": "R7.A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN",
        "state": "PASS_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN" if not blockers else "HOLD_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_INPUT",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "coverage_flag_count": len(coverage_flags),
        "coverage_flags": coverage_flags,
        "plan_ready": plan_ready,
        "canonical_strategy_universe_count": 25,
        "short_target_strategy_universe_count": SHORT_TARGET_STRATEGY_UNIVERSE_COUNT,
        "active_repair_strategy_count": ACTIVE_REPAIR_STRATEGY_COUNT,
        "redesign_strategy_count": REDESIGN_STRATEGY_COUNT,
        "redesign_strategy_ids": ["scalp_snap"],
        "diagnostic_lineage_seed_candidate_id": survivor_id,
        "current_1m_scalp_execution_allowed": False,
        "current_1m_geometry_permanent_promotion_allowed": False,
        "current_geometry_classification": feasibility.get("feasibility_classification"),
        "architecture_count": ARCHITECTURE_COUNT,
        "architectures": architectures,
        "target_candidate_count": TARGET_CANDIDATE_COUNT,
        "target_execution_cell_count": TARGET_EXECUTION_CELL_COUNT,
        "cost_axis_count": COST_AXIS_COUNT,
        "perturbation_axis_count": PERTURBATION_AXIS_COUNT,
        "cost_r_pre_admission_policy": {
            "conditional_friction_cap_r": CONDITIONAL_FRICTION_CAP_R,
            "robust_friction_cap_r": ROBUST_FRICTION_CAP_R,
            "absolute_friction_cap_r": ABSOLUTE_FRICTION_CAP_R,
            "required_raw_distance_pct_by_cost_profile": distance_requirements,
            "candidate_execution_requires_severe_axis_le_0_33r": True,
            "s_edge_requires_severe_axis_le_0_25r": True,
        },
        "candidate_selection_contract": {
            "outcome_blind": True,
            "future_mfe_mae_pnl_selection_allowed": False,
            "chronological_selection": True,
            "source_symbol_round_robin": True,
            "one_candidate_per_segment_before_reuse": True,
            "discovery_validation_split_required": True,
            "source_disjoint_validation_preferred": True,
            "symbol_only_overfit_allowed": False,
        },
        "post_execution_economic_gate": {
            "profit_factor_gt": 1.25,
            "expectancy_r_gt": 0.15,
            "worst_cost_axis_net_positive": True,
            "timing_stress_net_positive": True,
            "invalid_geometry_count_eq": 0,
            "realized_gross_net_payoff_ratio_audit_required": True,
            "average_win_loss_r_audit_required": True,
            "tp_sl_segment_end_histogram_required": True,
            "mfe_capture_audit_required": True,
        },
        "market_source_inventory": source_inventory,
        "rejected_market_sources": rejected_sources,
        "market_source_count": len(source_paths),
        "market_symbol_count": len(source_symbols),
        "market_symbols": source_symbols,
        "available_derived_timeframes": available_timeframes,
        "resampling_contract": {
            "frozen_source_only": True,
            "utc_boundary_anchor": True,
            "ohlc_aggregation": "open_first_high_max_low_min_close_last",
            "volume_aggregation": "sum_when_present",
            "partial_bucket_allowed": False,
            "source_sha_lineage_required": True,
            "lookahead_allowed": False,
        },
        "baseline_market_coverage_expansion_still_required": True,
        "failure_learning_connection_allowed": False,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "production_admission_expansion_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "full_3600_reexecution_allowed": False,
        "event_replay_2880_allowed": False,
        "next_stage": next_stage,
    }
    return plan, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--a4c-contract", required=True)
    parser.add_argument("--a4d-contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner_path = Path(args.runner).resolve()
    a4c_contract_path = Path(args.a4c_contract).resolve()
    a4d_contract_path = Path(args.a4d_contract).resolve()
    feasibility_path = root / "runtime/r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan/feasibility_plan_v1.json"

    a4c_contract = load_json(a4c_contract_path)
    a4d_contract = load_json(a4d_contract_path)
    frozen_manifest_path = root / str(a4c_contract["frozen_manifest_path"])
    feasibility = load_json(feasibility_path)
    frozen_manifest = load_json(frozen_manifest_path)
    runner = load_module(runner_path, "r7a4d2_scalp_timeframe_redesign_runner")

    category_inputs = frozen_manifest.get("category_inputs") if isinstance(frozen_manifest.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]

    protected_inputs = [feasibility_path, frozen_manifest_path, a4c_contract_path, a4d_contract_path]
    before = {str(path): sha256_file(path) for path in protected_inputs}
    source_inventory, rejected_sources = inspect_market_sources(root, runner, market_entries)
    plan, blockers = build_plan(
        feasibility,
        frozen_manifest,
        a4c_contract,
        a4d_contract,
        source_inventory,
        rejected_sources,
    )
    after = {str(path): sha256_file(path) for path in protected_inputs}
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
        plan["blockers"] = list(dict.fromkeys(blockers))
        plan["blocker_count"] = len(plan["blockers"])
        plan["state"] = "HOLD_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_INPUT"
        plan["plan_ready"] = False
        plan["next_stage"] = "R7.A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN"
    plan["protected_mutation_path_count"] = len(mutation_paths)
    plan["protected_mutation_paths"] = mutation_paths

    output = root / "runtime/r7a4d2_short_scalp_r_distance_timeframe_redesign_plan/redesign_plan_v1.json"
    atomic_json(output, plan)

    severe = plan.get("cost_r_pre_admission_policy", {}).get("required_raw_distance_pct_by_cost_profile", {}).get("cost_profile_2", {})
    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=" + str(plan["blocker_count"]))
    print("COVERAGE_FLAG_COUNT=" + str(plan["coverage_flag_count"]))
    print("PLAN_READY=" + str(plan["plan_ready"]).lower())
    print("SHORT_TARGET_STRATEGY_UNIVERSE_COUNT=" + str(plan["short_target_strategy_universe_count"]))
    print("ACTIVE_REPAIR_STRATEGY_COUNT=" + str(plan["active_repair_strategy_count"]))
    print("REDESIGN_STRATEGY_COUNT=" + str(plan["redesign_strategy_count"]))
    print("CURRENT_1M_SCALP_EXECUTION_ALLOWED=" + str(plan["current_1m_scalp_execution_allowed"]).lower())
    print("ARCHITECTURE_COUNT=" + str(plan["architecture_count"]))
    print("TARGET_CANDIDATE_COUNT=" + str(plan["target_candidate_count"]))
    print("TARGET_EXECUTION_CELL_COUNT=" + str(plan["target_execution_cell_count"]))
    print("SEVERE_CONDITIONAL_REQUIRED_RAW_DISTANCE_PCT=" + str(severe.get("conditional_required_raw_distance_pct", 0.0)))
    print("SEVERE_ROBUST_REQUIRED_RAW_DISTANCE_PCT=" + str(severe.get("robust_required_raw_distance_pct", 0.0)))
    print("MARKET_SOURCE_COUNT=" + str(plan["market_source_count"]))
    print("MARKET_SYMBOL_COUNT=" + str(plan["market_symbol_count"]))
    print("AVAILABLE_DERIVED_TIMEFRAMES=" + json.dumps(plan["available_derived_timeframes"]))
    print("ARCHITECTURES=" + json.dumps(plan["architectures"], sort_keys=True))
    print("COVERAGE_FLAGS=" + json.dumps(plan["coverage_flags"], ensure_ascii=False))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("BLOCKERS=" + json.dumps(plan["blockers"], ensure_ascii=False))
    print("RC=" + ("0" if int(plan["blocker_count"]) == 0 else "2"))
    return 0 if int(plan["blocker_count"]) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
