#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOL = 1e-9


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


def close_num(left: Any, right: Any, tolerance: float = TOL) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


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


def positive_pf(value: Any, threshold: float) -> bool:
    return value == "Infinity" or (isinstance(value, (int, float)) and float(value) > threshold)


def evaluate_bucket(bucket: str, candidates: list[dict[str, Any]], cells: list[dict[str, Any]], gate: dict[str, Any]) -> dict[str, Any]:
    trades = [row["trade"] for row in cells if isinstance(row.get("trade"), dict)]
    metrics = trade_metrics(trades)
    cost_net = axis_net(cells, "cost_profile")
    perturb_net = axis_net(cells, "perturbation")
    expected_cells = len(candidates) * 6
    reproduced = sum(1 for row in cells if row.get("status") == "CLOSED_TRADE")
    unique_segments = len({str(row.get("segment_id") or "") for row in candidates})
    unique_signal_locations = len({(str(row.get("segment_id") or ""), int(row.get("bar_index", -1))) for row in candidates})
    candidate_counts_by_segment = Counter(str(row.get("segment_id") or "") for row in candidates)
    max_segment_share = (
        max(candidate_counts_by_segment.values()) / len(candidates) if candidates and candidate_counts_by_segment else 0.0
    )
    common_pass = (
        len(cells) == expected_cells
        and reproduced == expected_cells
        and positive_pf(metrics.get("profit_factor"), float(gate["profit_factor_min_exclusive"]))
        and finite(metrics.get("expectancy_r")) > float(gate["expectancy_r_min_exclusive"])
        and bool(cost_net) and min(cost_net.values()) > 0
        and bool(perturb_net) and min(perturb_net.values()) > 0
    )
    independent_sample_pass = True
    if bucket == "grid_rebalance_range":
        # Stress repeats do not create new independent observations.
        independent_sample_pass = len(candidates) >= 8 and unique_signal_locations == len(candidates)
    else:
        independent_sample_pass = unique_segments >= 3 and len(candidates) >= 12
    promotable = common_pass and independent_sample_pass and bucket != "grid_rebalance_range"
    if bucket == "grid_rebalance_range" and common_pass:
        classification = "STRESS_ROBUST_QUARANTINED_REQUIRES_RELEASE_REVIEW"
    elif common_pass and not independent_sample_pass:
        classification = "STRESS_ROBUST_UNDER_SAMPLED"
    elif common_pass:
        classification = "STRESS_ROBUST_PROMOTION_CANDIDATE"
    elif reproduced < expected_cells:
        classification = "SIGNAL_OR_EXECUTION_NOT_ROBUST_ACROSS_AXES"
    elif finite(metrics.get("gross_pnl_sum_pct")) > 0 and finite(metrics.get("net_pnl_sum_pct")) <= 0:
        classification = "GROSS_EDGE_ERASED_BY_COST"
    elif finite(metrics.get("expectancy_r")) <= 0:
        classification = "NEGATIVE_SIGNAL_QUALITY"
    else:
        classification = "AXIS_FRAGILE"
    return {
        "bucket": bucket,
        "candidate_count": len(candidates),
        "stress_cell_count": len(cells),
        "expected_stress_cell_count": expected_cells,
        "closed_trade_cell_count": reproduced,
        "signal_or_execution_missing_cell_count": expected_cells - reproduced,
        "unique_segment_count": unique_segments,
        "unique_signal_location_count": unique_signal_locations,
        "candidate_count_by_segment": dict(sorted(candidate_counts_by_segment.items())),
        "max_segment_share": round(max_segment_share, 10),
        "axis_repeats_create_independent_samples": False,
        "metrics": metrics,
        "cost_profile_net_pct": cost_net,
        "perturbation_net_pct": perturb_net,
        "common_stress_gate_pass": common_pass,
        "independent_sample_gate_pass": independent_sample_pass,
        "promotable": promotable,
        "quarantined": bucket == "grid_rebalance_range",
        "classification": classification,
    }


def repair_queue(bucket_rows: list[dict[str, Any]], cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    by_bucket = {str(row.get("bucket") or ""): row for row in bucket_rows}
    for bucket, row in sorted(by_bucket.items()):
        classification = str(row.get("classification") or "")
        actions: list[str] = []
        if classification == "SIGNAL_OR_EXECUTION_NOT_ROBUST_ACROSS_AXES":
            actions = ["separate_signal_disappearance_from_pending_out_of_window", "inspect_latency_and_fill_sensitivity"]
        elif classification == "GROSS_EDGE_ERASED_BY_COST":
            actions = ["raise_admission_edge_floor_without_threshold_relaxation", "retain_block_until_cost_positive"]
        elif classification == "NEGATIVE_SIGNAL_QUALITY":
            actions = ["inspect_entry_context_and_regime_binding", "test_cooldown_and_duplicate_suppression"]
        elif classification == "AXIS_FRAGILE":
            actions = ["split_cost_vs_timing_causality", "reject_fragile_axes"]
        elif classification == "STRESS_ROBUST_UNDER_SAMPLED":
            actions = ["expand_unique_market_segments", "do_not_promote_from_axis_repeats"]
        elif classification == "STRESS_ROBUST_QUARANTINED_REQUIRES_RELEASE_REVIEW":
            actions = ["retain_grid_quarantine", "run_grid_range_dedup_and_cooldown_counterfactual"]
        if actions:
            repairs.append({"bucket": bucket, "classification": classification, "actions": actions})
    missing = Counter(str(row.get("status") or "") for row in cells if row.get("status") != "CLOSED_TRADE")
    if missing:
        repairs.append({"bucket": "GLOBAL", "classification": "CELL_FAILURE_HISTOGRAM", "histogram": dict(sorted(missing.items()))})
    return repairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_short_stress_runner")
    contract = load_json(Path(args.contract).resolve())
    contract["indicator_preroll_bars"] = 320

    plan = load_json(root / "runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json")
    closure = load_json(root / "runtime/r7a4d2_short_signal_frequency_admission_closure/admission_closure_v1.json")
    coverage = load_json(root / "runtime/r7a4d2_no_trigger_market_coverage_diagnose/coverage_diagnose_v1.json")
    short_plan = load_json(root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json")
    manifest = load_json(root / str(contract["selected_manifest_path"]))
    scenario_plan = load_json(root / str(contract["scenario_plan_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    if plan.get("state") != "PASS_SHORT_ADMISSION_ALLOWLIST_PLAN" or int(plan.get("blocker_count", -1)) != 0:
        blockers.append("ALLOWLIST_PLAN_INVALID")
    if int(plan.get("stress_candidate_count", -1)) != 11 or int(plan.get("stress_execution_target_count", -1)) != 66:
        blockers.append("STRESS_PLAN_SHAPE_INVALID")
    if closure.get("state") != "PASS_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE":
        blockers.append("ADMISSION_CLOSURE_INVALID")
    if coverage.get("state") != "PASS_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE":
        blockers.append("COVERAGE_DIAGNOSE_INVALID")

    candidates = [row for row in plan.get("stress_candidates", []) if isinstance(row, dict)]
    candidate_keys = [(str(row.get("scenario_id") or ""), str(row.get("strategy_id") or ""), int(row.get("bar_index", -1))) for row in candidates]
    if len(candidates) != 11 or len(set(candidate_keys)) != 11:
        blockers.append(f"CANDIDATE_SET_INVALID:{len(candidates)}:{len(set(candidate_keys))}")

    entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
    segments = {str(row.get("segment_id") or ""): row for row in manifest.get("selected_segments", []) if isinstance(row, dict)}
    scenarios = [row for row in scenario_plan.get("scenarios", []) if isinstance(row, dict)]
    scenario_index = {
        (
            str(row.get("strategy_id") or ""), str(row.get("segment_id") or ""),
            str(row.get("cost_profile") or ""), str(row.get("perturbation") or ""),
        ): row
        for row in scenarios
    }
    costs = {str(row.get("id") or ""): row for row in contract.get("cost_profiles", []) if isinstance(row, dict)}
    perturbations = {str(row.get("id") or ""): row for row in contract.get("perturbations", []) if isinstance(row, dict)}
    target_ids = sorted(str(item) for item in short_plan.get("short_target_strategy_ids", []))
    if len(entries) != 25 or len(segments) != 24 or len(costs) != 3 or len(perturbations) != 2 or len(target_ids) != 12:
        blockers.append(f"MATRIX_SHAPE_INVALID:{len(entries)}:{len(segments)}:{len(costs)}:{len(perturbations)}:{len(target_ids)}")

    closure_observations = {
        str(row.get("candidate_id") or ""): row
        for row in closure.get("candidate_observations", []) if isinstance(row, dict)
    }
    coverage_trace = {
        ":".join((str(row.get("scenario_id") or ""), str(row.get("strategy_id") or ""), str(int(row.get("bar_index", -1))))): row
        for row in coverage.get("candidate_trace", []) if isinstance(row, dict)
    }

    canonical_paths = [registry_path, root / "backend/strategy25/canonical_strategy25_config_v1.json"]
    bindings: dict[str, tuple[type[Any], str]] = {}
    source_registry_parity = True
    sys.path.insert(0, str(root))
    try:
        for strategy_id in sorted(entries):
            engine = entries[strategy_id].get("canonical_engine") if isinstance(entries[strategy_id].get("canonical_engine"), dict) else {}
            repo_path = runner.safe_repo_path(str(engine.get("implementation_path") or ""))
            source_path = root / repo_path
            canonical_paths.append(source_path)
            if runner.sha256_file(source_path) != str(engine.get("source_sha256") or ""):
                source_registry_parity = False
                blockers.append(f"SOURCE_REGISTRY_SHA_MISMATCH:{strategy_id}")
                continue
            module = runner.load_module(root, repo_path, strategy_id + "_stress66")
            bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        sys.path.remove(str(root))

    protected = [
        root / "runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json",
        root / "runtime/r7a4d2_short_signal_frequency_admission_closure/admission_closure_v1.json",
        root / "runtime/r7a4d2_short_rr_sidecar_counterfactual/counterfactual_proof_v1.json",
    ]
    before = runner.snapshot(canonical_paths + protected)
    side_effect_attempts: list[str] = []
    failures: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    frame_cache: dict[str, Any] = {}
    sample_cache: dict[str, Any] = {}

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
                    strategy_id = str(candidate["strategy_id"])
                    segment_id = str(candidate["segment_id"])
                    segment = segments.get(segment_id)
                    if not isinstance(segment, dict):
                        failures.append({"candidate_id": candidate.get("candidate_id"), "error": "SEGMENT_MISSING"})
                        continue
                    sample = sample_cache.get(segment_id)
                    if sample is None:
                        market_path = root / runner.safe_repo_path(str(segment["source_path"]))
                        if runner.sha256_file(market_path) != segment.get("source_sha256"):
                            failures.append({"candidate_id": candidate.get("candidate_id"), "error": "SEGMENT_SOURCE_SHA_MISMATCH"})
                            continue
                        frame = frame_cache.get(str(market_path))
                        if frame is None:
                            frame = runner.load_market_frame(market_path)
                            frame_cache[str(market_path)] = frame
                        sample = runner.select_segment_with_preroll(
                            frame, int(segment["start_row"]), int(segment["end_row_exclusive"]),
                            int(contract["segment_bars"]), 320,
                        )
                        sample_cache[segment_id] = sample
                    owner, method_name = bindings[strategy_id]
                    for cost_id, cost in sorted(costs.items()):
                        for perturbation_id, perturbation in sorted(perturbations.items()):
                            scenario = scenario_index.get((strategy_id, segment_id, cost_id, perturbation_id))
                            if not isinstance(scenario, dict):
                                failures.append({"candidate_id": candidate.get("candidate_id"), "cost": cost_id, "perturbation": perturbation_id, "error": "SCENARIO_MISSING"})
                                continue
                            stress_contract = dict(base_contract)
                            stress_contract.update({
                                "short_observer_target_scenario_id": str(scenario["scenario_id"]),
                                "short_observer_target_strategy_id": strategy_id,
                                "short_observer_target_bar_index": int(candidate["bar_index"]),
                            })
                            try:
                                result = runner.simulate_scenario(scenario, sample, owner, method_name, cost, perturbation, stress_contract)
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
                                    "candidate_id": str(candidate["candidate_id"]),
                                    "bucket": str(candidate["bucket"]),
                                    "strategy_id": strategy_id,
                                    "segment_id": segment_id,
                                    "regime": str(candidate["regime"]),
                                    "bar_index": int(candidate["bar_index"]),
                                    "scenario_id": str(scenario["scenario_id"]),
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
                                    "candidate_id": candidate.get("candidate_id"), "cost": cost_id,
                                    "perturbation": perturbation_id, "error": f"{type(exc).__name__}:{exc}",
                                })
                            progress += 1
                            if progress % 11 == 0:
                                print(f"A4D2_STRESS66_PROGRESS={progress}/66 FAILED={len(failures)}")
        except Exception as exc:
            blockers.append(f"STRESS_REPLAY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            sys.path.remove(str(root))

    after = runner.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if len(cells) != 66 or failures:
        blockers.append(f"STRESS_CELL_RESULT_INVALID:{len(cells)}:{len(failures)}")
    if mutation_paths:
        blockers.append("CANONICAL_OR_PROOF_MUTATION_DETECTED")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPT:{len(side_effect_attempts)}")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    # Baseline parity: cost0/perturb0 must reproduce the prior isolated observer trade.
    baseline_parity_failures: list[dict[str, Any]] = []
    for candidate in candidates:
        baseline_cell = next((row for row in cells if row["candidate_id"] == candidate["candidate_id"] and row["cost_profile"] == "cost_profile_0" and row["perturbation"] == "perturbation_0"), None)
        prior_container = closure_observations.get(str(candidate["candidate_id"])) if candidate.get("source") == "closure_observer" else coverage_trace.get(str(candidate["candidate_id"]))
        prior_trade = prior_container.get("trade") if isinstance(prior_container, dict) and isinstance(prior_container.get("trade"), dict) else None
        if not isinstance(baseline_cell, dict):
            baseline_parity_failures.append({"candidate_id": candidate["candidate_id"], "reason": "BASELINE_CELL_MISSING"})
            continue
        # Coverage admitted trace has no trade payload; its parity is checked by one closed trade only.
        if prior_trade is None:
            if baseline_cell.get("status") != "CLOSED_TRADE":
                baseline_parity_failures.append({"candidate_id": candidate["candidate_id"], "reason": "BASELINE_TRADE_NOT_REPRODUCED"})
        else:
            fields = ("net_pnl_pct", "gross_pnl_pct", "cost_pct", "pnl_r", "entry_index", "exit_index", "exit_reason")
            diffs = []
            current_trade = baseline_cell.get("trade") if isinstance(baseline_cell.get("trade"), dict) else {}
            for field in fields:
                left, right = prior_trade.get(field), current_trade.get(field)
                equal = close_num(left, right) if isinstance(left, (int, float)) and isinstance(right, (int, float)) else left == right
                if not equal:
                    diffs.append({"field": field, "prior": left, "current": right})
            if diffs:
                baseline_parity_failures.append({"candidate_id": candidate["candidate_id"], "reason": "BASELINE_TRADE_DIFF", "diffs": diffs})
    if baseline_parity_failures:
        blockers.append(f"BASELINE_PARITY_FAILURE:{len(baseline_parity_failures)}")

    grouped_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_cells: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        grouped_candidates[str(row["bucket"])].append(row)
    for row in cells:
        grouped_cells[str(row["bucket"])].append(row)
    gate = plan.get("promotion_gates", {}).get("common", {}) if isinstance(plan.get("promotion_gates"), dict) else {}
    bucket_rows = [evaluate_bucket(bucket, grouped_candidates[bucket], grouped_cells.get(bucket, []), gate) for bucket in sorted(grouped_candidates)]
    repairs = repair_queue(bucket_rows, cells)

    robust_buckets = [row["bucket"] for row in bucket_rows if row.get("common_stress_gate_pass")]
    promotable_buckets = [row["bucket"] for row in bucket_rows if row.get("promotable")]
    under_sampled_robust = [row["bucket"] for row in bucket_rows if row.get("classification") == "STRESS_ROBUST_UNDER_SAMPLED"]
    grid_robust = any(row.get("bucket") == "grid_rebalance_range" and row.get("common_stress_gate_pass") for row in bucket_rows)

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        state = "HOLD_SHORT_ADMISSION_CANDIDATE_STRESS_INPUT"
        next_stage = "R7.A4D2_SHORT_ADMISSION_CANDIDATE_STRESS_66"
    else:
        state = "PASS_SHORT_ADMISSION_CANDIDATE_STRESS_66"
        if promotable_buckets:
            next_stage = "R7.A4D2_SHORT_ADMISSION_ALLOWLIST_COUNTERFACTUAL_600"
        elif under_sampled_robust or grid_robust:
            next_stage = "R7.A4D2_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES"
        else:
            next_stage = "R7.A4D2_SHORT_CANDIDATE_REPAIR_PLAN"

    evidence = {
        "schema": "r7a4d2_short_admission_candidate_stress_66_v1",
        "official_stage": "R7.A4D2_SHORT_ADMISSION_CANDIDATE_STRESS_66",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "targeted_cell_count": 66,
        "completed_cell_count": len(cells),
        "failed_cell_count": len(failures),
        "baseline_parity_failure_count": len(baseline_parity_failures),
        "baseline_parity_failures": baseline_parity_failures,
        "source_registry_parity": source_registry_parity,
        "mutation_path_count": len(mutation_paths),
        "side_effect_attempt_count": len(side_effect_attempts),
        "axis_repeats_create_independent_samples": False,
        "negative_pair_block_count": len(plan.get("negative_pair_blocks", [])),
        "grid_rebalance_quarantined": True,
        "robust_buckets": robust_buckets,
        "promotable_buckets": promotable_buckets,
        "under_sampled_robust_buckets": under_sampled_robust,
        "bucket_results": bucket_rows,
        "repair_queue": repairs,
        "cells": cells,
        "failures": failures[:20],
        "next_stage": next_stage,
    }
    output_dir = root / "runtime/r7a4d2_short_admission_candidate_stress_66"
    runner.atomic_json(output_dir / "stress66_proof_v1.json", evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("TARGETED_CELL_COUNT=66")
    print("COMPLETED_CELL_COUNT=" + str(len(cells)))
    print("FAILED_CELL_COUNT=" + str(len(failures)))
    print("BASELINE_PARITY_FAILURE_COUNT=" + str(len(baseline_parity_failures)))
    print("NEGATIVE_PAIR_BLOCK_COUNT=" + str(len(plan.get("negative_pair_blocks", []))))
    print("AXIS_REPEATS_CREATE_INDEPENDENT_SAMPLES=false")
    print("GRID_REBALANCE_QUARANTINED=true")
    print("ROBUST_BUCKETS=" + json.dumps(robust_buckets, ensure_ascii=False))
    print("PROMOTABLE_BUCKETS=" + json.dumps(promotable_buckets, ensure_ascii=False))
    print("UNDER_SAMPLED_ROBUST_BUCKETS=" + json.dumps(under_sampled_robust, ensure_ascii=False))
    print("BUCKET_RESULTS=" + json.dumps(bucket_rows, ensure_ascii=False, sort_keys=True))
    print("REPAIR_QUEUE=" + json.dumps(repairs, ensure_ascii=False, sort_keys=True))
    print("SOURCE_REGISTRY_PARITY=" + str(source_registry_parity).lower())
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("PROOF_JSON=" + str(output_dir / "stress66_proof_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
