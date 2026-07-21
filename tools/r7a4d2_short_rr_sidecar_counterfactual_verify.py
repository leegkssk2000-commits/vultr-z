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


TOL = 1e-10


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


def close_enough(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= TOL
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(close_enough(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(close_enough(a, b) for a, b in zip(left, right))
    return left == right


def long_projection(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in row.items() if not str(key).startswith("short_")}
    samples = []
    for trade in result.get("trade_sample", []) if isinstance(result.get("trade_sample"), list) else []:
        if isinstance(trade, dict) and str(trade.get("side") or "long") != "short":
            samples.append({key: value for key, value in trade.items() if key != "side"})
    if "trade_sample" in result:
        result["trade_sample"] = samples
    return result


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net = [finite(row.get("net_pnl_pct")) for row in trades]
    gross = [finite(row.get("gross_pnl_pct")) for row in trades]
    pnl_r = [finite(row.get("pnl_r")) for row in trades]
    gross_r = [
        finite(row.get("gross_pnl_pct")) / max(finite(row.get("risk_capital_pct")), 1e-12)
        for row in trades
    ]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf: float | str = gross_profit / gross_loss if gross_loss > 0 else ("Infinity" if gross_profit > 0 else 0.0)
    average_win = statistics.fmean(wins) if wins else 0.0
    average_loss = statistics.fmean(losses) if losses else 0.0
    payoff = average_win / abs(average_loss) if average_loss < 0 else (math.inf if average_win > 0 else 0.0)
    return {
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 10) if trades else 0.0,
        "net_pnl_sum_pct": round(sum(net), 10),
        "gross_pnl_sum_pct": round(sum(gross), 10),
        "cost_sum_pct": round(sum(finite(row.get("cost_pct")) for row in trades), 10),
        "profit_factor": round(pf, 10) if isinstance(pf, float) and math.isfinite(pf) else pf,
        "payoff_ratio": round(payoff, 10) if math.isfinite(payoff) else "Infinity",
        "expectancy_r": round(statistics.fmean(pnl_r), 10) if pnl_r else 0.0,
        "gross_expectancy_r": round(statistics.fmean(gross_r), 10) if gross_r else 0.0,
        "minimum_gross_r": round(min(gross_r), 10) if gross_r else 0.0,
        "maximum_gross_r": round(max(gross_r), 10) if gross_r else 0.0,
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in trades).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_rr_counterfactual_runner")
    contract = load_json(Path(args.contract).resolve())
    contract["indicator_preroll_bars"] = 320

    rr_plan = load_json(root / "runtime/r7a4d2_short_rr_policy_plan/short_rr_policy_plan_v1.json")
    short_plan = load_json(root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json")
    entry_proof = load_json(root / "runtime/r7a4d2_entry_chain_minimal_patch_verify/entry_chain_patch_proof_v1.json")
    manifest = load_json(root / str(contract["selected_manifest_path"]))
    scenario_plan = load_json(root / str(contract["scenario_plan_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    if rr_plan.get("state") != "PASS_SHORT_RR_POLICY_PLAN" or int(rr_plan.get("blocker_count", -1)) != 0:
        blockers.append("RR_POLICY_PLAN_INVALID")
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_PLAN_INVALID")
    if entry_proof.get("state") != "PASS_ENTRY_CHAIN_MINIMAL_PATCH":
        blockers.append("ENTRY_PROOF_INVALID")

    entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    scenarios = [row for row in scenario_plan.get("scenarios", []) if isinstance(row, dict)]
    scenario_index = {
        (str(row.get("strategy_id") or ""), str(row.get("segment_id") or ""), str(row.get("cost_profile") or ""), str(row.get("perturbation") or "")): row
        for row in scenarios
    }
    if len(entries) != 25 or len(segments) != 24:
        blockers.append(f"MATRIX_SHAPE_INVALID:{len(entries)}:{len(segments)}")

    costs = {str(row["id"]): row for row in contract.get("cost_profiles", []) if isinstance(row, dict)}
    perturbations = {str(row["id"]): row for row in contract.get("perturbations", []) if isinstance(row, dict)}
    if "cost_profile_0" not in costs or "perturbation_0" not in perturbations:
        blockers.append("BASELINE_AXIS_MISSING")

    target_ids = sorted(str(item) for item in short_plan.get("short_target_strategy_ids", []))
    if len(target_ids) != 12:
        blockers.append(f"SHORT_TARGET_COUNT_INVALID:{len(target_ids)}")

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
            module = runner.load_module(root, repo_path, strategy_id + "_rr_cf")
            bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        sys.path.remove(str(root))

    protected_evidence = [
        root / "runtime/r7a4d2_short_execution_harness_verify/short_execution_harness_proof_v1.json",
        root / "runtime/r7a4d2_short_harness_mismatch_performance/diagnose_v1.json",
    ]
    before = runner.snapshot(canonical_paths + protected_evidence)
    policy_results: list[dict[str, Any]] = []
    long_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    side_effect_attempts: list[str] = []
    frame_cache: dict[str, Any] = {}

    contract_policy = dict(contract)
    contract_policy.update({
        "short_execution_enabled": True,
        "short_target_strategy_ids": target_ids,
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
    })
    contract_long = dict(contract_policy)
    contract_long["short_execution_enabled"] = False

    if not blockers:
        sys.path.insert(0, str(root))
        try:
            with runner.side_effect_guard(side_effect_attempts):
                progress = 0
                for segment in segments:
                    segment_id = str(segment["segment_id"])
                    market_path = root / runner.safe_repo_path(str(segment["source_path"]))
                    if runner.sha256_file(market_path) != segment.get("source_sha256"):
                        raise ValueError(f"SEGMENT_SOURCE_SHA_MISMATCH:{segment_id}")
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
                    for strategy_id in sorted(entries):
                        scenario = scenario_index.get((strategy_id, segment_id, "cost_profile_0", "perturbation_0"))
                        if not isinstance(scenario, dict):
                            raise ValueError(f"SCENARIO_MISSING:{strategy_id}:{segment_id}")
                        owner, method_name = bindings[strategy_id]
                        try:
                            long_results.append(runner.simulate_scenario(
                                scenario, sample, owner, method_name, costs["cost_profile_0"], perturbations["perturbation_0"], contract_long
                            ))
                            policy_results.append(runner.simulate_scenario(
                                scenario, sample, owner, method_name, costs["cost_profile_0"], perturbations["perturbation_0"], contract_policy
                            ))
                        except Exception as exc:
                            failures.append({"scenario_id": scenario.get("scenario_id"), "strategy_id": strategy_id, "error": f"{type(exc).__name__}:{exc}"})
                        progress += 1
                        if progress % 50 == 0:
                            print(f"A4D2_RR_PROGRESS={progress}/600 FAILED={len(failures)}")
        except Exception as exc:
            blockers.append(f"COUNTERFACTUAL_REPLAY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            sys.path.remove(str(root))

    after = runner.snapshot(canonical_paths + protected_evidence)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if len(policy_results) != 600 or len(long_results) != 600 or failures:
        blockers.append(f"COUNTERFACTUAL_RESULT_INVALID:{len(policy_results)}:{len(long_results)}:{len(failures)}")
    if mutation_paths:
        blockers.append("RAW_OR_CANONICAL_MUTATION_DETECTED")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPT:{len(side_effect_attempts)}")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    prior_index = {str(row.get("scenario_id") or ""): row for row in entry_proof.get("results", []) if isinstance(row, dict)}
    long_index = {str(row.get("scenario_id") or ""): row for row in long_results}
    long_mismatches = []
    for scenario_id, prior in prior_index.items():
        current = long_index.get(scenario_id)
        if not isinstance(current, dict) or not close_enough(long_projection(prior), long_projection(current)):
            long_mismatches.append(scenario_id)
    if long_mismatches:
        blockers.append(f"LONG_REGRESSION_MISMATCH:{len(long_mismatches)}")

    short_trades = [trade for row in policy_results for trade in row.get("short_trade_detail", []) if isinstance(trade, dict)]
    short_metrics = metrics(short_trades)
    policy_net = sum(finite(row.get("net_return_pct")) for row in policy_results)
    long_net = sum(finite(row.get("net_return_pct")) for row in long_results)
    incremental_net = policy_net - long_net
    by_regime: dict[str, dict[str, Any]] = defaultdict(lambda: {"scenario_count": 0, "short_trade_count": 0, "incremental_net_pct": 0.0})
    long_by_id = {str(row.get("scenario_id") or ""): row for row in long_results}
    for row in policy_results:
        regime = str(row.get("regime") or "")
        base = long_by_id.get(str(row.get("scenario_id") or ""), {})
        by_regime[regime]["scenario_count"] += 1
        by_regime[regime]["short_trade_count"] += int(row.get("short_closed_trade_count") or 0)
        by_regime[regime]["incremental_net_pct"] += finite(row.get("net_return_pct")) - finite(base.get("net_return_pct"))
    for value in by_regime.values():
        value["incremental_net_pct"] = round(float(value["incremental_net_pct"]), 10)

    trend_up_short = int(by_regime.get("trend_up", {}).get("short_trade_count", 0))
    shock_short = int(by_regime.get("shock_recovery", {}).get("short_trade_count", 0))
    range_short = int(by_regime.get("range", {}).get("short_trade_count", 0))
    invalid_geometry = sum(int(row.get("short_invalid_geometry_count") or 0) for row in policy_results)
    orphan_add = sum(int(row.get("short_orphan_add_block_count") or 0) for row in policy_results)
    candidates = sum(int(row.get("short_policy_candidate_count") or 0) for row in policy_results)
    admitted = sum(int(row.get("short_policy_admitted_action_count") or 0) for row in policy_results)
    regime_blocks = sum(int(row.get("short_policy_regime_block_count") or 0) for row in policy_results)
    add_suppressed = sum(int(row.get("short_policy_add_suppressed_count") or 0) for row in policy_results)
    reduce_suppressed = sum(int(row.get("short_policy_reduce_suppressed_count") or 0) for row in policy_results)

    performance_flags: list[str] = []
    if not short_trades:
        performance_flags.append("POLICY_SHORT_TRADE_ZERO")
    pf = short_metrics.get("profit_factor")
    if isinstance(pf, (int, float)) and float(pf) <= 1.0:
        performance_flags.append("POLICY_PROFIT_FACTOR_NOT_ABOVE_ONE")
    if finite(short_metrics.get("expectancy_r")) <= 0:
        performance_flags.append("POLICY_EXPECTANCY_R_NOT_POSITIVE")
    if incremental_net <= 0:
        performance_flags.append("POLICY_INCREMENTAL_NET_NOT_POSITIVE")
    if trend_up_short or shock_short or range_short:
        blockers.append(f"BLOCKED_REGIME_SHORT_EXECUTED:{trend_up_short}:{shock_short}:{range_short}")
    if invalid_geometry or orphan_add:
        blockers.append(f"POLICY_GEOMETRY_OR_LINEAGE_INVALID:{invalid_geometry}:{orphan_add}")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        state = "HOLD_SHORT_RR_COUNTERFACTUAL_INPUT"
        next_stage = "R7.A4D2_SHORT_RR_SIDECAR_COUNTERFACTUAL_600"
    elif performance_flags:
        state = "HOLD_SHORT_RR_PERFORMANCE_ROOT_CAUSE"
        next_stage = "R7.A4D2_SHORT_ADMISSION_SIGNAL_QUALITY_CLOSURE"
    else:
        state = "PASS_SHORT_RR_SIDECAR_COUNTERFACTUAL_600"
        next_stage = "R7.A4D2_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE"

    evidence = {
        "schema": "r7a4d2_short_rr_sidecar_counterfactual_v1",
        "official_stage": "R7.A4D2_SHORT_RR_SIDECAR_COUNTERFACTUAL_600",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "performance_flags": performance_flags,
        "targeted_scenario_count": 600,
        "completed_policy_scenario_count": len(policy_results),
        "completed_long_scenario_count": len(long_results),
        "failed_scenario_count": len(failures),
        "long_regression_mismatch_count": len(long_mismatches),
        "raw_and_canonical_mutation_count": len(mutation_paths),
        "source_registry_parity": source_registry_parity,
        "side_effect_attempts": side_effect_attempts,
        "policy_loss_cap_r": 0.75,
        "policy_full_tp_r": 2.5,
        "minimum_gross_payoff_ratio": round(2.5 / 0.75, 12),
        "short_policy_candidate_count": candidates,
        "short_policy_admitted_action_count": admitted,
        "short_policy_regime_block_count": regime_blocks,
        "short_policy_add_suppressed_count": add_suppressed,
        "short_policy_reduce_suppressed_count": reduce_suppressed,
        "short_invalid_geometry_count": invalid_geometry,
        "short_orphan_add_block_count": orphan_add,
        "policy_net_return_sum_pct": round(policy_net, 10),
        "long_baseline_net_return_sum_pct": round(long_net, 10),
        "policy_incremental_net_return_pct": round(incremental_net, 10),
        "short_trade_metrics": short_metrics,
        "regime_summary": dict(sorted(by_regime.items())),
        "failures": failures[:20],
        "next_stage": next_stage,
    }
    output_dir = root / "runtime/r7a4d2_short_rr_sidecar_counterfactual"
    runner.atomic_json(output_dir / "counterfactual_proof_v1.json", evidence)
    runner.atomic_jsonl(output_dir / "policy_results_600_v1.jsonl", policy_results)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("TARGETED_SCENARIO_COUNT=600")
    print("COMPLETED_POLICY_SCENARIO_COUNT=" + str(len(policy_results)))
    print("COMPLETED_LONG_SCENARIO_COUNT=" + str(len(long_results)))
    print("FAILED_SCENARIO_COUNT=" + str(len(failures)))
    print("LONG_REGRESSION_MISMATCH_COUNT=" + str(len(long_mismatches)))
    print("RAW_AND_CANONICAL_MUTATION_COUNT=" + str(len(mutation_paths)))
    print("SHORT_POLICY_CANDIDATE_COUNT=" + str(candidates))
    print("SHORT_POLICY_ADMITTED_ACTION_COUNT=" + str(admitted))
    print("SHORT_POLICY_REGIME_BLOCK_COUNT=" + str(regime_blocks))
    print("SHORT_POLICY_ADD_SUPPRESSED_COUNT=" + str(add_suppressed))
    print("SHORT_POLICY_REDUCE_SUPPRESSED_COUNT=" + str(reduce_suppressed))
    print("SHORT_CLOSED_TRADE_COUNT=" + str(len(short_trades)))
    print("POLICY_INCREMENTAL_NET_RETURN_PCT=" + str(round(incremental_net, 10)))
    print("SHORT_TRADE_METRICS=" + json.dumps(short_metrics, ensure_ascii=False, sort_keys=True))
    print("REGIME_SUMMARY=" + json.dumps(dict(sorted(by_regime.items())), ensure_ascii=False, sort_keys=True))
    print("PERFORMANCE_FLAGS=" + json.dumps(performance_flags, ensure_ascii=False))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("PROOF_JSON=" + str(output_dir / "counterfactual_proof_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if state.startswith("PASS_") else "2"))
    return 0 if state.startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
