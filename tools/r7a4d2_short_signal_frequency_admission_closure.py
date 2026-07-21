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


def profit_factor(trades: list[dict[str, Any]]) -> float | str:
    wins = sum(max(finite(row.get("net_pnl_pct")), 0.0) for row in trades)
    losses = abs(sum(min(finite(row.get("net_pnl_pct")), 0.0) for row in trades))
    if losses > 0:
        return wins / losses
    return "Infinity" if wins > 0 else 0.0


def group_metrics(candidates: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    net = [finite(row.get("net_pnl_pct")) for row in trades]
    gross = [finite(row.get("gross_pnl_pct")) for row in trades]
    pnl_r = [finite(row.get("pnl_r")) for row in trades]
    gross_r = [
        finite(row.get("gross_pnl_pct")) / max(finite(row.get("risk_capital_pct")), 1e-12)
        for row in trades
    ]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    flats = [value for value in net if value == 0]
    average_win = statistics.fmean(wins) if wins else 0.0
    average_loss = statistics.fmean(losses) if losses else 0.0
    payoff: float | str
    if average_loss < 0:
        payoff = average_win / abs(average_loss)
    else:
        payoff = "Infinity" if average_win > 0 else 0.0
    pf = profit_factor(trades)
    net_sum = sum(net)
    expectancy = statistics.fmean(pnl_r) if pnl_r else 0.0
    positive = (
        bool(trades)
        and net_sum > 0
        and expectancy > 0
        and (pf == "Infinity" or (isinstance(pf, float) and pf > 1.0))
    )
    if not trades:
        classification = "NO_CLOSED_TRADE"
    elif positive and len(trades) == 1:
        classification = "POSITIVE_SINGLE_TRADE_CANDIDATE"
    elif positive:
        classification = "POSITIVE_MULTI_TRADE_CANDIDATE"
    elif net_sum < 0 or expectancy < 0:
        classification = "NEGATIVE_OBSERVER_RESULT"
    else:
        classification = "ZERO_OR_MIXED_OBSERVER_RESULT"
    return {
        "candidate_count": len(candidates),
        "closed_trade_count": len(trades),
        "no_closed_trade_count": len(candidates) - len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": len(flats),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 10) if trades else 0.0,
        "net_pnl_sum_pct": round(net_sum, 10),
        "gross_pnl_sum_pct": round(sum(gross), 10),
        "cost_sum_pct": round(sum(finite(row.get("cost_pct")) for row in trades), 10),
        "profit_factor": round(pf, 10) if isinstance(pf, float) and math.isfinite(pf) else pf,
        "payoff_ratio": round(payoff, 10) if isinstance(payoff, float) and math.isfinite(payoff) else payoff,
        "expectancy_r": round(expectancy, 10),
        "gross_expectancy_r": round(statistics.fmean(gross_r), 10) if gross_r else 0.0,
        "mean_mfe_pct": round(statistics.fmean([finite(row.get("mfe_pct")) for row in trades]), 10) if trades else 0.0,
        "mean_mae_pct": round(statistics.fmean([finite(row.get("mae_pct")) for row in trades]), 10) if trades else 0.0,
        "median_mfe_pct": round(statistics.median([finite(row.get("mfe_pct")) for row in trades]), 10) if trades else 0.0,
        "median_mae_pct": round(statistics.median([finite(row.get("mae_pct")) for row in trades]), 10) if trades else 0.0,
        "minimum_gross_r": round(min(gross_r), 10) if gross_r else 0.0,
        "maximum_gross_r": round(max(gross_r), 10) if gross_r else 0.0,
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in trades).items())),
        "classification": classification,
        "allowlist_candidate": positive,
    }


def classify_next(group_rows: list[dict[str, Any]], closed_count: int) -> tuple[list[str], str]:
    classes: list[str] = []
    positive_non_grid = [
        row for row in group_rows
        if row.get("strategy_id") != "grid_rebalance" and bool(row.get("metrics", {}).get("allowlist_candidate"))
    ]
    negative = [row for row in group_rows if row.get("metrics", {}).get("classification") == "NEGATIVE_OBSERVER_RESULT"]
    no_trade = [row for row in group_rows if row.get("metrics", {}).get("classification") == "NO_CLOSED_TRADE"]
    if positive_non_grid:
        classes.append("POSITIVE_STRATEGY_REGIME_ALLOWLIST_CANDIDATES_FOUND")
    if negative:
        classes.append("NEGATIVE_STRATEGY_REGIME_PAIRS_FOUND")
    if no_trade:
        classes.append("OBSERVER_CANDIDATES_WITHOUT_CLOSED_TRADE")
    if any(row.get("strategy_id") == "grid_rebalance" for row in group_rows):
        classes.append("GRID_REBALANCE_QUARANTINED")
    if closed_count == 0:
        classes.append("OBSERVER_CLOSED_TRADE_ZERO")
        return classes, "R7.A4D2_SHORT_OBSERVER_EXECUTION_CLOSURE"
    if positive_non_grid:
        return classes, "R7.A4D2_SHORT_ADMISSION_ALLOWLIST_PLAN"
    return classes, "R7.A4D2_SHORT_SIGNAL_QUALITY_CLOSURE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_short_admission_observer_runner")
    contract = load_json(Path(args.contract).resolve())
    contract["indicator_preroll_bars"] = 320

    coverage = load_json(root / "runtime/r7a4d2_no_trigger_market_coverage_diagnose/coverage_diagnose_v1.json")
    rr_proof = load_json(root / "runtime/r7a4d2_short_rr_sidecar_counterfactual/counterfactual_proof_v1.json")
    short_plan = load_json(root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json")
    manifest = load_json(root / str(contract["selected_manifest_path"]))
    scenario_plan = load_json(root / str(contract["scenario_plan_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    if coverage.get("state") != "PASS_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE":
        blockers.append("COVERAGE_PROOF_NOT_PASS")
    if int(coverage.get("blocker_count", -1)) != 0:
        blockers.append("COVERAGE_PROOF_BLOCKED")
    if int(coverage.get("blocked_flat_enter_count", -1)) != 158:
        blockers.append("BLOCKED_FLAT_ENTER_COUNT_INVALID")
    if rr_proof.get("state") != "PASS_SHORT_RR_SIDECAR_COUNTERFACTUAL_600":
        blockers.append("RR_COUNTERFACTUAL_NOT_PASS")
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_PLAN_INVALID")

    raw_trace = coverage.get("candidate_trace") if isinstance(coverage.get("candidate_trace"), list) else []
    blocked_candidates = [
        row for row in raw_trace
        if isinstance(row, dict)
        and not bool(row.get("admitted"))
        and row.get("candidate_state") == "FLAT_ENTER"
        and row.get("legacy_action") == "enter"
    ]
    candidate_keys = [
        (
            str(row.get("scenario_id") or ""),
            str(row.get("strategy_id") or ""),
            int(row.get("bar_index", -1)),
        )
        for row in blocked_candidates
    ]
    if len(blocked_candidates) != 158 or len(set(candidate_keys)) != 158:
        blockers.append(f"OBSERVER_CANDIDATE_SET_INVALID:{len(blocked_candidates)}:{len(set(candidate_keys))}")

    entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
    segments = {str(row.get("segment_id") or ""): row for row in manifest.get("selected_segments", []) if isinstance(row, dict)}
    scenarios = {str(row.get("scenario_id") or ""): row for row in scenario_plan.get("scenarios", []) if isinstance(row, dict)}
    costs = {str(row["id"]): row for row in contract.get("cost_profiles", []) if isinstance(row, dict)}
    perturbations = {str(row["id"]): row for row in contract.get("perturbations", []) if isinstance(row, dict)}
    target_ids = sorted(str(item) for item in short_plan.get("short_target_strategy_ids", []))
    if len(entries) != 25 or len(segments) != 24 or len(target_ids) != 12:
        blockers.append(f"MATRIX_SHAPE_INVALID:{len(entries)}:{len(segments)}:{len(target_ids)}")
    if "cost_profile_0" not in costs or "perturbation_0" not in perturbations:
        blockers.append("BASELINE_AXIS_MISSING")

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
            module = runner.load_module(root, repo_path, strategy_id + "_admission_observer")
            bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        sys.path.remove(str(root))

    protected = [
        root / "runtime/r7a4d2_no_trigger_market_coverage_diagnose/coverage_diagnose_v1.json",
        root / "runtime/r7a4d2_short_rr_sidecar_counterfactual/counterfactual_proof_v1.json",
    ]
    before = runner.snapshot(canonical_paths + protected)
    side_effect_attempts: list[str] = []
    failures: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
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
                for index, candidate in enumerate(blocked_candidates, start=1):
                    scenario_id = str(candidate.get("scenario_id") or "")
                    strategy_id = str(candidate.get("strategy_id") or "")
                    segment_id = str(candidate.get("segment_id") or "")
                    scenario = scenarios.get(scenario_id)
                    segment = segments.get(segment_id)
                    if not isinstance(scenario, dict) or not isinstance(segment, dict):
                        failures.append({"candidate_key": candidate_keys[index - 1], "error": "SCENARIO_OR_SEGMENT_MISSING"})
                        continue
                    sample = sample_cache.get(segment_id)
                    if sample is None:
                        market_path = root / runner.safe_repo_path(str(segment["source_path"]))
                        if runner.sha256_file(market_path) != segment.get("source_sha256"):
                            failures.append({"candidate_key": candidate_keys[index - 1], "error": "SEGMENT_SOURCE_SHA_MISMATCH"})
                            continue
                        frame = frame_cache.get(str(market_path))
                        if frame is None:
                            frame = runner.load_market_frame(market_path)
                            frame_cache[str(market_path)] = frame
                        sample = runner.select_segment_with_preroll(
                            frame,
                            int(segment["start_row"]),
                            int(segment["end_row_exclusive"]),
                            int(contract["segment_bars"]),
                            320,
                        )
                        sample_cache[segment_id] = sample
                    owner, method_name = bindings[strategy_id]
                    observer_contract = dict(base_contract)
                    observer_contract.update({
                        "short_observer_target_scenario_id": scenario_id,
                        "short_observer_target_strategy_id": strategy_id,
                        "short_observer_target_bar_index": int(candidate.get("bar_index", -1)),
                    })
                    try:
                        result = runner.simulate_scenario(
                            scenario,
                            sample,
                            owner,
                            method_name,
                            costs["cost_profile_0"],
                            perturbations["perturbation_0"],
                            observer_contract,
                        )
                        trades = [row for row in result.get("short_trade_detail", []) if isinstance(row, dict)]
                        match_count = int(result.get("short_observer_target_match_count") or 0)
                        if match_count != 1 or len(trades) > 1:
                            failures.append({
                                "candidate_key": candidate_keys[index - 1],
                                "error": f"OBSERVER_TARGET_RESULT_INVALID:{match_count}:{len(trades)}",
                            })
                            continue
                        status = "CLOSED_TRADE" if trades else (
                            "INVALID_GEOMETRY"
                            if int(result.get("short_invalid_geometry_count") or 0) > 0
                            else "NO_CLOSED_TRADE"
                        )
                        observation = {
                            "candidate_id": f"{scenario_id}:{strategy_id}:{int(candidate.get('bar_index', -1))}",
                            "scenario_id": scenario_id,
                            "strategy_id": strategy_id,
                            "segment_id": segment_id,
                            "regime": str(candidate.get("regime") or ""),
                            "bar_index": int(candidate.get("bar_index", -1)),
                            "evaluation_index": int(candidate.get("evaluation_index", -1)),
                            "legacy_reason": str(candidate.get("legacy_reason") or ""),
                            "target_qty": finite(candidate.get("target_qty")),
                            "status": status,
                            "target_match_count": match_count,
                            "short_enter_signal_count": int(result.get("short_enter_signal_count") or 0),
                            "invalid_geometry_count": int(result.get("short_invalid_geometry_count") or 0),
                            "non_target_suppressed_count": int(result.get("short_observer_non_target_suppressed_count") or 0),
                            "trade": trades[0] if trades else None,
                        }
                        observations.append(observation)
                    except Exception as exc:
                        failures.append({
                            "candidate_key": candidate_keys[index - 1],
                            "error": f"{type(exc).__name__}:{exc}",
                        })
                    if index % 20 == 0:
                        print(f"A4D2_ADMISSION_OBSERVER_PROGRESS={index}/158 FAILED={len(failures)}")
        except Exception as exc:
            blockers.append(f"OBSERVER_REPLAY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            sys.path.remove(str(root))

    after = runner.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if len(observations) != 158 or failures:
        blockers.append(f"OBSERVER_RESULT_INVALID:{len(observations)}:{len(failures)}")
    if mutation_paths:
        blockers.append("CANONICAL_OR_PROOF_MUTATION_DETECTED")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPT:{len(side_effect_attempts)}")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    grouped_candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    grouped_trades: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        key = (str(row.get("strategy_id") or ""), str(row.get("regime") or ""))
        grouped_candidates[key].append(row)
        if isinstance(row.get("trade"), dict):
            grouped_trades[key].append(row["trade"])

    group_rows: list[dict[str, Any]] = []
    for key in sorted(grouped_candidates):
        strategy_id, regime = key
        result = {
            "strategy_id": strategy_id,
            "regime": regime,
            "quarantined": strategy_id == "grid_rebalance",
            "metrics": group_metrics(grouped_candidates[key], grouped_trades.get(key, [])),
        }
        if result["quarantined"]:
            result["metrics"]["allowlist_candidate"] = False
            result["metrics"]["classification"] = "GRID_REBALANCE_QUARANTINED"
        group_rows.append(result)

    closed_trades = [row["trade"] for row in observations if isinstance(row.get("trade"), dict)]
    allowlist_candidates = [
        {
            "strategy_id": row["strategy_id"],
            "regime": row["regime"],
            "closed_trade_count": row["metrics"]["closed_trade_count"],
            "net_pnl_sum_pct": row["metrics"]["net_pnl_sum_pct"],
            "profit_factor": row["metrics"]["profit_factor"],
            "expectancy_r": row["metrics"]["expectancy_r"],
            "classification": row["metrics"]["classification"],
        }
        for row in group_rows
        if bool(row["metrics"].get("allowlist_candidate")) and not bool(row.get("quarantined"))
    ]
    negative_pairs = [
        {"strategy_id": row["strategy_id"], "regime": row["regime"], "metrics": row["metrics"]}
        for row in group_rows
        if row["metrics"].get("classification") == "NEGATIVE_OBSERVER_RESULT"
    ]
    grid_rows = [row for row in group_rows if row.get("strategy_id") == "grid_rebalance"]
    root_classes, next_stage = classify_next(group_rows, len(closed_trades))

    blockers = list(dict.fromkeys(blockers))
    state = "PASS_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE" if not blockers else "HOLD_SHORT_ADMISSION_OBSERVER_INPUT"
    if blockers:
        next_stage = "R7.A4D2_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE"

    evidence = {
        "schema": "r7a4d2_short_signal_frequency_admission_closure_v1",
        "official_stage": "R7.A4D2_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "observer_candidate_count": len(blocked_candidates),
        "completed_observer_candidate_count": len(observations),
        "failed_observer_candidate_count": len(failures),
        "closed_trade_count": len(closed_trades),
        "no_closed_trade_count": len(observations) - len(closed_trades),
        "strategy_regime_pair_count": len(group_rows),
        "allowlist_candidate_pair_count": len(allowlist_candidates),
        "negative_pair_count": len(negative_pairs),
        "grid_rebalance_quarantined": True,
        "policy_loss_cap_r": 0.75,
        "policy_full_tp_r": 2.5,
        "source_registry_parity": source_registry_parity,
        "mutation_path_count": len(mutation_paths),
        "side_effect_attempt_count": len(side_effect_attempts),
        "root_cause_classifications": root_classes,
        "allowlist_candidates": allowlist_candidates,
        "negative_pairs": negative_pairs,
        "grid_rebalance_summary": grid_rows,
        "strategy_regime_metrics": group_rows,
        "candidate_observations": observations,
        "failures": failures[:20],
        "next_stage": next_stage,
    }
    output_dir = root / "runtime/r7a4d2_short_signal_frequency_admission_closure"
    runner.atomic_json(output_dir / "admission_closure_v1.json", evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("OBSERVER_CANDIDATE_COUNT=" + str(len(blocked_candidates)))
    print("COMPLETED_OBSERVER_CANDIDATE_COUNT=" + str(len(observations)))
    print("FAILED_OBSERVER_CANDIDATE_COUNT=" + str(len(failures)))
    print("OBSERVER_CLOSED_TRADE_COUNT=" + str(len(closed_trades)))
    print("OBSERVER_NO_CLOSED_TRADE_COUNT=" + str(len(observations) - len(closed_trades)))
    print("STRATEGY_REGIME_PAIR_COUNT=" + str(len(group_rows)))
    print("ALLOWLIST_CANDIDATE_PAIR_COUNT=" + str(len(allowlist_candidates)))
    print("ALLOWLIST_CANDIDATES=" + json.dumps(allowlist_candidates, ensure_ascii=False, sort_keys=True))
    print("NEGATIVE_PAIR_COUNT=" + str(len(negative_pairs)))
    print("GRID_REBALANCE_QUARANTINED=true")
    print("GRID_REBALANCE_SUMMARY=" + json.dumps(grid_rows, ensure_ascii=False, sort_keys=True))
    print("STRATEGY_REGIME_METRICS=" + json.dumps(group_rows, ensure_ascii=False, sort_keys=True))
    print("ROOT_CAUSE_CLASSIFICATIONS=" + json.dumps(root_classes, ensure_ascii=False))
    print("SOURCE_REGISTRY_PARITY=" + str(source_registry_parity).lower())
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output_dir / "admission_closure_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
