#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOL = 1e-9
EXPECTED_CELL_COUNT = 168
EXPECTED_CANDIDATE_COUNT = 28
EXPECTED_BUCKET_COUNTS = {
    "baseline_trend_down": 12,
    "scalp_snap_trend_up": 12,
    "vol_spike_fade_shock_recovery": 4,
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


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def positive_pf(value: Any, threshold: float) -> bool:
    return value == "Infinity" or (isinstance(value, (int, float)) and float(value) > threshold)


def trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net = [finite(row.get("net_pnl_pct")) for row in trades]
    gross = [finite(row.get("gross_pnl_pct")) for row in trades]
    pnl_r = [finite(row.get("pnl_r")) for row in trades]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf: float | str = gross_profit / gross_loss if gross_loss > 0 else ("Infinity" if gross_profit > 0 else 0.0)
    avg_win = statistics.fmean(wins) if wins else 0.0
    avg_loss = statistics.fmean(losses) if losses else 0.0
    payoff: float | str = avg_win / abs(avg_loss) if avg_loss < 0 else ("Infinity" if avg_win > 0 else 0.0)
    return {
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": len(trades) - len(wins) - len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 10) if trades else 0.0,
        "net_pnl_sum_pct": round(sum(net), 10),
        "gross_pnl_sum_pct": round(sum(gross), 10),
        "cost_sum_pct": round(sum(finite(row.get("cost_pct")) for row in trades), 10),
        "profit_factor": round(pf, 10) if isinstance(pf, float) and math.isfinite(pf) else pf,
        "payoff_ratio": round(payoff, 10) if isinstance(payoff, float) and math.isfinite(payoff) else payoff,
        "expectancy_r": round(statistics.fmean(pnl_r), 10) if pnl_r else 0.0,
        "median_r": round(statistics.median(pnl_r), 10) if pnl_r else 0.0,
        "mean_mfe_pct": round(statistics.fmean(finite(row.get("mfe_pct")) for row in trades), 10) if trades else 0.0,
        "mean_mae_pct": round(statistics.fmean(finite(row.get("mae_pct")) for row in trades), 10) if trades else 0.0,
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in trades).items())),
    }


def axis_net(cells: list[dict[str, Any]], axis: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in cells:
        totals[str(row.get(axis) or "")] += finite(row.get("net_pnl_pct"))
    return {key: round(value, 10) for key, value in sorted(totals.items())}


def candidate_axis_summary(candidates: list[dict[str, Any]], cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        rows = [row for row in cells if row.get("candidate_id") == candidate_id]
        trades = [row["trade"] for row in rows if isinstance(row.get("trade"), dict)]
        output.append({
            "candidate_id": candidate_id,
            "bucket": str(candidate.get("bucket") or ""),
            "strategy_id": str(candidate.get("strategy_id") or ""),
            "regime": str(candidate.get("regime") or ""),
            "segment_id": str(candidate.get("segment_id") or ""),
            "source_path": str(candidate.get("source_path") or ""),
            "bar_index": int(candidate.get("bar_index", -1)),
            "cell_count": len(rows),
            "target_reproduction_count": sum(1 for row in rows if int(row.get("target_match_count") or 0) == 1),
            "closed_trade_cell_count": sum(1 for row in rows if row.get("status") == "CLOSED_TRADE"),
            "status_histogram": dict(sorted(Counter(str(row.get("status") or "") for row in rows).items())),
            "metrics": trade_metrics(trades),
            "cost_profile_net_pct": axis_net(rows, "cost_profile"),
            "perturbation_net_pct": axis_net(rows, "perturbation"),
        })
    return output


def classify_failure(metrics: dict[str, Any], reproduced: int, closed: int, expected: int, invalid: int) -> str:
    if reproduced < expected:
        return "SIGNAL_NOT_ROBUST_ACROSS_AXES"
    if invalid > 0:
        return "INVALID_GEOMETRY_PRESENT"
    if closed < expected:
        return "FILL_OR_CLOSE_WINDOW_NOT_ROBUST"
    if finite(metrics.get("gross_pnl_sum_pct")) > 0 and finite(metrics.get("net_pnl_sum_pct")) <= 0:
        return "GROSS_EDGE_ERASED_BY_COST"
    if finite(metrics.get("expectancy_r")) <= 0:
        return "NEGATIVE_SIGNAL_QUALITY"
    return "AXIS_FRAGILE"


def evaluate_bucket(bucket: str, candidates: list[dict[str, Any]], cells: list[dict[str, Any]], gate: dict[str, Any]) -> dict[str, Any]:
    trades = [row["trade"] for row in cells if isinstance(row.get("trade"), dict)]
    metrics = trade_metrics(trades)
    expected_cells = len(candidates) * 6
    reproduced = sum(1 for row in cells if int(row.get("target_match_count") or 0) == 1)
    closed = sum(1 for row in cells if row.get("status") == "CLOSED_TRADE")
    invalid = sum(int(row.get("invalid_geometry_count") or 0) for row in cells)
    cost_net = axis_net(cells, "cost_profile")
    perturb_net = axis_net(cells, "perturbation")
    unique_segments = len({str(row.get("segment_id") or "") for row in candidates})
    unique_sources = len({str(row.get("source_path") or "") for row in candidates})
    candidate_counts_by_segment = Counter(str(row.get("segment_id") or "") for row in candidates)
    max_segment_count = max(candidate_counts_by_segment.values()) if candidate_counts_by_segment else 0

    common_pass = (
        len(cells) == expected_cells
        and reproduced == expected_cells
        and closed == expected_cells
        and invalid == 0
        and positive_pf(metrics.get("profit_factor"), float(gate["profit_factor_min_exclusive"]))
        and finite(metrics.get("expectancy_r")) > float(gate["expectancy_r_min_exclusive"])
        and bool(cost_net) and min(cost_net.values()) > 0
        and bool(perturb_net) and min(perturb_net.values()) > 0
    )
    if bucket == "baseline_trend_down":
        diversity_pass = len(candidates) == 12 and unique_segments == 12 and unique_sources >= 3
        promotable = False
        classification = (
            "STRESS_ROBUST_GRID_STRATEGY_QUARANTINED"
            if common_pass and diversity_pass
            else classify_failure(metrics, reproduced, closed, expected_cells, invalid)
        )
        quarantined = True
    elif bucket == "scalp_snap_trend_up":
        diversity_pass = len(candidates) == 12 and unique_segments >= 10 and max_segment_count <= 2
        promotable = common_pass and diversity_pass
        classification = (
            "STRESS_ROBUST_PROMOTION_CANDIDATE"
            if promotable
            else classify_failure(metrics, reproduced, closed, expected_cells, invalid)
        )
        quarantined = False
    else:
        diversity_pass = len(candidates) == 4 and unique_segments == 4
        promotable = False
        if common_pass and diversity_pass:
            classification = "DIAGNOSTIC_POSITIVE_UNDER_SAMPLED"
        else:
            classification = classify_failure(metrics, reproduced, closed, expected_cells, invalid)
        quarantined = False

    return {
        "bucket": bucket,
        "candidate_count": len(candidates),
        "stress_cell_count": len(cells),
        "expected_stress_cell_count": expected_cells,
        "target_reproduction_cell_count": reproduced,
        "closed_trade_cell_count": closed,
        "signal_or_execution_missing_cell_count": expected_cells - closed,
        "invalid_geometry_count": invalid,
        "unique_segment_count": unique_segments,
        "unique_source_count": unique_sources,
        "candidate_count_by_segment": dict(sorted(candidate_counts_by_segment.items())),
        "max_segment_count": max_segment_count,
        "axis_repeats_create_independent_samples": False,
        "metrics": metrics,
        "cost_profile_net_pct": cost_net,
        "perturbation_net_pct": perturb_net,
        "common_stress_gate_pass": common_pass,
        "diversity_gate_pass": diversity_pass,
        "promotable": promotable,
        "quarantined": quarantined,
        "classification": classification,
    }


def build_repair_queue(bucket_results: list[dict[str, Any]], candidate_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    for row in bucket_results:
        bucket = str(row.get("bucket") or "")
        classification = str(row.get("classification") or "")
        actions: list[str] = []
        if classification == "STRESS_ROBUST_GRID_STRATEGY_QUARANTINED":
            actions = [
                "retain_grid_strategy_quarantine",
                "run_grid_trend_down_dedup_cooldown_counterfactual",
                "require_quarantine_release_review",
            ]
        elif classification == "STRESS_ROBUST_PROMOTION_CANDIDATE":
            actions = ["build_read_only_strategy_regime_allowlist_candidate", "run_selective_counterfactual_600"]
        elif classification == "DIAGNOSTIC_POSITIVE_UNDER_SAMPLED":
            actions = ["expand_vol_shock_unique_candidates_to_12", "retain_non_promotable_status"]
        elif classification == "SIGNAL_NOT_ROBUST_ACROSS_AXES":
            actions = ["inspect_signal_context_drift", "retain_block"]
        elif classification == "INVALID_GEOMETRY_PRESENT":
            actions = ["inspect_sl_tp_geometry_at_target_bar", "block_invalid_candidates"]
        elif classification == "FILL_OR_CLOSE_WINDOW_NOT_ROBUST":
            actions = ["separate_pending_out_of_window_from_no_close", "repair_latency_fill_window_without_threshold_relaxation"]
        elif classification == "GROSS_EDGE_ERASED_BY_COST":
            actions = ["raise_admission_edge_floor", "retain_block_until_worst_cost_axis_positive"]
        elif classification == "NEGATIVE_SIGNAL_QUALITY":
            actions = ["inspect_entry_context_and_regime_binding", "test_cooldown_and_duplicate_suppression"]
        else:
            actions = ["split_cost_vs_timing_causality", "reject_fragile_axes"]
        repairs.append({"bucket": bucket, "classification": classification, "actions": actions})

    failing_candidates = [
        {
            "candidate_id": row["candidate_id"],
            "bucket": row["bucket"],
            "status_histogram": row["status_histogram"],
            "net_pnl_sum_pct": row["metrics"]["net_pnl_sum_pct"],
            "expectancy_r": row["metrics"]["expectancy_r"],
        }
        for row in candidate_results
        if row.get("closed_trade_cell_count") != 6 or finite(row.get("metrics", {}).get("expectancy_r")) <= 0
    ]
    if failing_candidates:
        repairs.append({
            "bucket": "CANDIDATE_LEVEL",
            "classification": "FAILING_CANDIDATE_SET",
            "candidate_count": len(failing_candidates),
            "candidates": failing_candidates,
        })
    return repairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_short_expanded_stress_runner")
    contract = load_json(Path(args.contract).resolve())
    contract["indicator_preroll_bars"] = 320

    plan_path = root / "runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json"
    expansion_path = root / "runtime/r7a4d2_market_segment_expansion_for_short_candidates/market_segment_expansion_v1.json"
    stress66_path = root / "runtime/r7a4d2_short_admission_candidate_stress_66/stress66_proof_v1.json"
    allowlist_path = root / "runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json"
    short_plan_path = root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json"

    plan = load_json(plan_path)
    expansion = load_json(expansion_path)
    stress66 = load_json(stress66_path)
    allowlist = load_json(allowlist_path)
    short_plan = load_json(short_plan_path)
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    if plan.get("state") != "PASS_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN" or int(plan.get("blocker_count", -1)) != 0:
        blockers.append("EXPANDED_STRESS_PLAN_INVALID")
    if int(plan.get("expanded_candidate_count", -1)) != EXPECTED_CANDIDATE_COUNT:
        blockers.append("EXPANDED_CANDIDATE_COUNT_INVALID")
    if int(plan.get("expanded_stress_execution_target_count", -1)) != EXPECTED_CELL_COUNT:
        blockers.append("EXPANDED_CELL_TARGET_INVALID")
    if expansion.get("state") != "PASS_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES" or int(expansion.get("blocker_count", -1)) != 0:
        blockers.append("MARKET_EXPANSION_INVALID")
    if stress66.get("state") != "PASS_SHORT_ADMISSION_CANDIDATE_STRESS_66" or int(stress66.get("baseline_parity_failure_count", -1)) != 0:
        blockers.append("PRIOR_STRESS66_INVALID")
    if allowlist.get("state") != "PASS_SHORT_ADMISSION_ALLOWLIST_PLAN" or len(allowlist.get("negative_pair_blocks", [])) != 14:
        blockers.append("ALLOWLIST_OR_NEGATIVE_BLOCK_SET_INVALID")
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_EXECUTION_PLAN_INVALID")

    candidates = [row for row in plan.get("expanded_stress_candidates", []) if isinstance(row, dict)]
    candidate_ids = [str(row.get("candidate_id") or "") for row in candidates]
    candidate_keys = [
        (
            str(row.get("bucket") or ""),
            str(row.get("scenario_id") or ""),
            str(row.get("strategy_id") or ""),
            int(row.get("bar_index", -1)),
        )
        for row in candidates
    ]
    if len(candidates) != EXPECTED_CANDIDATE_COUNT or len(set(candidate_ids)) != EXPECTED_CANDIDATE_COUNT or len(set(candidate_keys)) != EXPECTED_CANDIDATE_COUNT:
        blockers.append(f"EXPANDED_CANDIDATE_SET_INVALID:{len(candidates)}:{len(set(candidate_ids))}:{len(set(candidate_keys))}")
    if canonical_hash(candidates) != str(plan.get("candidate_manifest_sha256") or ""):
        blockers.append("CANDIDATE_MANIFEST_HASH_MISMATCH")
    observed_bucket_counts = Counter(str(row.get("bucket") or "") for row in candidates)
    if dict(observed_bucket_counts) != EXPECTED_BUCKET_COUNTS:
        blockers.append(f"EXPANDED_BUCKET_COUNT_INVALID:{dict(observed_bucket_counts)}")

    entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
    target_ids = sorted(str(item) for item in short_plan.get("short_target_strategy_ids", []))
    used_strategy_ids = sorted({str(row.get("strategy_id") or "") for row in candidates})
    costs = {str(row.get("id") or ""): row for row in contract.get("cost_profiles", []) if isinstance(row, dict)}
    perturbations = {str(row.get("id") or ""): row for row in contract.get("perturbations", []) if isinstance(row, dict)}
    if len(entries) != 25 or len(target_ids) != 12 or len(costs) != 3 or len(perturbations) != 2:
        blockers.append(f"MATRIX_SHAPE_INVALID:{len(entries)}:{len(target_ids)}:{len(costs)}:{len(perturbations)}")
    if not set(used_strategy_ids).issubset(set(target_ids)):
        blockers.append(f"USED_STRATEGY_NOT_SHORT_TARGET:{used_strategy_ids}")

    canonical_paths = [registry_path, root / "backend/strategy25/canonical_strategy25_config_v1.json"]
    bindings: dict[str, tuple[type[Any], str]] = {}
    source_registry_parity = True
    sys.path.insert(0, str(root))
    try:
        for strategy_id, entry in sorted(entries.items()):
            engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
            repo_path = runner.safe_repo_path(str(engine.get("implementation_path") or ""))
            source_path = root / repo_path
            canonical_paths.append(source_path)
            if runner.sha256_file(source_path) != str(engine.get("source_sha256") or ""):
                source_registry_parity = False
                blockers.append(f"SOURCE_REGISTRY_SHA_MISMATCH:{strategy_id}")
                continue
            if strategy_id in used_strategy_ids:
                module = runner.load_module(root, repo_path, strategy_id + "_expanded_stress168")
                bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        sys.path.remove(str(root))

    protected = [plan_path, expansion_path, stress66_path, allowlist_path, short_plan_path]
    before = runner.snapshot(canonical_paths + protected)
    side_effect_attempts: list[str] = []
    failures: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    frame_cache: dict[str, Any] = {}
    sample_cache: dict[tuple[str, int, int], Any] = {}

    base_contract = dict(contract)
    base_contract.update({
        "short_execution_enabled": True,
        "short_target_strategy_ids": target_ids,
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
        "short_observer_target_enabled": True,
    })

    if not blockers:
        sys.path.insert(0, str(root))
        try:
            with runner.side_effect_guard(side_effect_attempts):
                progress = 0
                for candidate in candidates:
                    candidate_id = str(candidate["candidate_id"])
                    strategy_id = str(candidate["strategy_id"])
                    source_path = runner.safe_repo_path(str(candidate["source_path"]))
                    market_path = root / source_path
                    actual_sha = runner.sha256_file(market_path)
                    if actual_sha != str(candidate.get("source_sha256") or ""):
                        failures.append({"candidate_id": candidate_id, "error": "CANDIDATE_SOURCE_SHA_MISMATCH"})
                        continue
                    frame = frame_cache.get(source_path)
                    if frame is None:
                        frame = runner.load_market_frame(market_path)
                        frame_cache[source_path] = frame
                    start = int(candidate["start_row"])
                    stop = int(candidate["end_row_exclusive"])
                    sample_key = (source_path, start, stop)
                    sample = sample_cache.get(sample_key)
                    if sample is None:
                        sample = runner.select_segment_with_preroll(frame, start, stop, 320, 320)
                        sample_cache[sample_key] = sample
                    owner, method_name = bindings[strategy_id]
                    for cost_id, cost in sorted(costs.items()):
                        for perturbation_id, perturbation in sorted(perturbations.items()):
                            scenario_id = digest_text(f"expanded-stress168:{candidate_id}:{cost_id}:{perturbation_id}")[:24]
                            scenario = {
                                "scenario_id": scenario_id,
                                "strategy_id": strategy_id,
                                "segment_id": str(candidate["segment_id"]),
                                "regime": str(candidate["regime"]),
                                "fold": -2,
                                "cost_profile": cost_id,
                                "perturbation": perturbation_id,
                            }
                            stress_contract = dict(base_contract)
                            stress_contract.update({
                                "short_observer_target_scenario_id": scenario_id,
                                "short_observer_target_strategy_id": strategy_id,
                                "short_observer_target_bar_index": int(candidate["bar_index"]),
                            })
                            try:
                                result = runner.simulate_scenario(
                                    scenario,
                                    sample,
                                    owner,
                                    method_name,
                                    cost,
                                    perturbation,
                                    stress_contract,
                                )
                                trades = [row for row in result.get("short_trade_detail", []) if isinstance(row, dict)]
                                match_count = int(result.get("short_observer_target_match_count") or 0)
                                invalid = int(result.get("short_invalid_geometry_count") or 0)
                                if match_count > 1 or len(trades) > 1:
                                    raise ValueError(f"TARGET_MULTIPLICITY_INVALID:{match_count}:{len(trades)}")
                                if trades:
                                    status = "CLOSED_TRADE"
                                elif match_count == 0:
                                    status = "SIGNAL_NOT_REPRODUCED"
                                elif invalid:
                                    status = "INVALID_GEOMETRY"
                                else:
                                    status = "NO_CLOSED_TRADE"
                                trade = trades[0] if trades else None
                                cells.append({
                                    "candidate_id": candidate_id,
                                    "bucket": str(candidate["bucket"]),
                                    "strategy_id": strategy_id,
                                    "regime": str(candidate["regime"]),
                                    "segment_id": str(candidate["segment_id"]),
                                    "source_path": source_path,
                                    "bar_index": int(candidate["bar_index"]),
                                    "scenario_id": scenario_id,
                                    "cost_profile": cost_id,
                                    "perturbation": perturbation_id,
                                    "status": status,
                                    "target_match_count": match_count,
                                    "invalid_geometry_count": invalid,
                                    "net_pnl_pct": finite(trade.get("net_pnl_pct")) if trade else 0.0,
                                    "gross_pnl_pct": finite(trade.get("gross_pnl_pct")) if trade else 0.0,
                                    "cost_pct": finite(trade.get("cost_pct")) if trade else 0.0,
                                    "pnl_r": finite(trade.get("pnl_r")) if trade else 0.0,
                                    "exit_reason": str(trade.get("exit_reason") or "") if trade else "",
                                    "trade": trade,
                                })
                            except Exception as exc:
                                failures.append({
                                    "candidate_id": candidate_id,
                                    "cost_profile": cost_id,
                                    "perturbation": perturbation_id,
                                    "error": f"{type(exc).__name__}:{exc}",
                                })
                            progress += 1
                            if progress % 14 == 0:
                                print(f"A4D2_EXPANDED_STRESS_PROGRESS={progress}/168 FAILED={len(failures)}")
        except Exception as exc:
            blockers.append(f"EXPANDED_STRESS_REPLAY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            sys.path.remove(str(root))

    after = runner.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if len(cells) != EXPECTED_CELL_COUNT or failures:
        blockers.append(f"EXPANDED_STRESS_CELL_RESULT_INVALID:{len(cells)}:{len(failures)}")
    if mutation_paths:
        blockers.append("CANONICAL_OR_PROOF_MUTATION_DETECTED")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPT:{len(side_effect_attempts)}")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    baseline_parity_failures: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        baseline = next((
            row for row in cells
            if row.get("candidate_id") == candidate_id
            and row.get("cost_profile") == "cost_profile_0"
            and row.get("perturbation") == "perturbation_0"
        ), None)
        if not isinstance(baseline, dict):
            baseline_parity_failures.append({"candidate_id": candidate_id, "reason": "BASELINE_CELL_MISSING"})
        elif int(baseline.get("target_match_count") or 0) != 1:
            baseline_parity_failures.append({
                "candidate_id": candidate_id,
                "reason": "DISCOVERED_TARGET_NOT_REPRODUCED",
                "target_match_count": int(baseline.get("target_match_count") or 0),
                "status": baseline.get("status"),
            })
    if baseline_parity_failures:
        blockers.append(f"BASELINE_TARGET_PARITY_FAILURE:{len(baseline_parity_failures)}")

    grouped_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_cells: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        grouped_candidates[str(row["bucket"])].append(row)
    for row in cells:
        grouped_cells[str(row["bucket"])].append(row)
    common_gate = plan.get("promotion_gates", {}).get("common", {}) if isinstance(plan.get("promotion_gates"), dict) else {}
    bucket_results = [
        evaluate_bucket(bucket, grouped_candidates[bucket], grouped_cells.get(bucket, []), common_gate)
        for bucket in sorted(grouped_candidates)
    ]
    candidate_results = candidate_axis_summary(candidates, cells)
    repairs = build_repair_queue(bucket_results, candidate_results)

    robust_buckets = [row["bucket"] for row in bucket_results if row.get("common_stress_gate_pass")]
    promotable_buckets = [row["bucket"] for row in bucket_results if row.get("promotable")]
    quarantined_robust_buckets = [
        row["bucket"] for row in bucket_results
        if row.get("classification") == "STRESS_ROBUST_GRID_STRATEGY_QUARANTINED"
    ]
    diagnostic_positive_buckets = [
        row["bucket"] for row in bucket_results
        if row.get("classification") == "DIAGNOSTIC_POSITIVE_UNDER_SAMPLED"
    ]

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        state = "HOLD_SHORT_EXPANDED_CANDIDATE_STRESS_INPUT"
        next_stage = "R7.A4D2_SHORT_EXPANDED_CANDIDATE_STRESS_168"
    else:
        state = "PASS_SHORT_EXPANDED_CANDIDATE_STRESS_168"
        next_stage = "R7.A4D2_SHORT_EXPANDED_CANDIDATE_REPAIR_CLOSURE"

    evidence = {
        "schema": "r7a4d2_short_expanded_candidate_stress_168_v1",
        "official_stage": "R7.A4D2_SHORT_EXPANDED_CANDIDATE_STRESS_168",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "targeted_candidate_count": EXPECTED_CANDIDATE_COUNT,
        "targeted_cell_count": EXPECTED_CELL_COUNT,
        "completed_cell_count": len(cells),
        "failed_cell_count": len(failures),
        "baseline_target_parity_failure_count": len(baseline_parity_failures),
        "baseline_target_parity_failures": baseline_parity_failures,
        "source_registry_parity": source_registry_parity,
        "mutation_path_count": len(mutation_paths),
        "side_effect_attempt_count": len(side_effect_attempts),
        "axis_repeats_create_independent_samples": False,
        "negative_pair_block_count": len(allowlist.get("negative_pair_blocks", [])),
        "grid_rebalance_strategy_quarantined": True,
        "robust_buckets": robust_buckets,
        "promotable_buckets": promotable_buckets,
        "quarantined_robust_buckets": quarantined_robust_buckets,
        "diagnostic_positive_buckets": diagnostic_positive_buckets,
        "bucket_results": bucket_results,
        "candidate_results": candidate_results,
        "repair_queue": repairs,
        "cells": cells,
        "failures": failures,
        "next_stage": next_stage,
    }
    output_dir = root / "runtime/r7a4d2_short_expanded_candidate_stress_168"
    runner.atomic_json(output_dir / "stress168_proof_v1.json", evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("TARGETED_CANDIDATE_COUNT=28")
    print("TARGETED_CELL_COUNT=168")
    print("COMPLETED_CELL_COUNT=" + str(len(cells)))
    print("FAILED_CELL_COUNT=" + str(len(failures)))
    print("BASELINE_TARGET_PARITY_FAILURE_COUNT=" + str(len(baseline_parity_failures)))
    print("NEGATIVE_PAIR_BLOCK_COUNT=" + str(len(allowlist.get("negative_pair_blocks", []))))
    print("AXIS_REPEATS_CREATE_INDEPENDENT_SAMPLES=false")
    print("GRID_REBALANCE_STRATEGY_QUARANTINED=true")
    print("ROBUST_BUCKETS=" + json.dumps(robust_buckets, ensure_ascii=False))
    print("PROMOTABLE_BUCKETS=" + json.dumps(promotable_buckets, ensure_ascii=False))
    print("QUARANTINED_ROBUST_BUCKETS=" + json.dumps(quarantined_robust_buckets, ensure_ascii=False))
    print("DIAGNOSTIC_POSITIVE_BUCKETS=" + json.dumps(diagnostic_positive_buckets, ensure_ascii=False))
    print("BUCKET_RESULTS=" + json.dumps(bucket_results, ensure_ascii=False, sort_keys=True))
    print("CANDIDATE_RESULTS=" + json.dumps(candidate_results, ensure_ascii=False, sort_keys=True))
    print("REPAIR_QUEUE=" + json.dumps(repairs, ensure_ascii=False, sort_keys=True))
    print("SOURCE_REGISTRY_PARITY=" + str(source_registry_parity).lower())
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("PROOF_JSON=" + str(output_dir / "stress168_proof_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
