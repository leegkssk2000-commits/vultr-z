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

ENTRY_CHAIN_TARGETS = {
    "break_and_continue",
    "rbreaker_like",
    "squeeze_break",
    "trend_ma_macd",
    "vwap_revert",
}
ECONOMIC_FIELDS = {
    "trade_count",
    "win_count",
    "loss_count",
    "win_rate_pct",
    "net_return_pct",
    "total_cost_pct",
    "max_drawdown_pct",
    "profit_factor",
    "expectancy_r",
    "median_r",
    "mean_mfe_pct",
    "mean_mae_pct",
    "exposure_pct",
    "trade_exit_histogram",
    "trade_sample",
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


def stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def long_projection(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in row.items() if not str(key).startswith("short_")}
    samples: list[dict[str, Any]] = []
    for trade in result.get("trade_sample", []) if isinstance(result.get("trade_sample"), list) else []:
        if isinstance(trade, dict):
            samples.append({key: value for key, value in trade.items() if key != "side"})
    if "trade_sample" in result:
        result["trade_sample"] = samples
    return result


def flatten(value: Any, prefix: str = "$") -> dict[str, Any]:
    output: dict[str, Any] = {}
    if isinstance(value, dict):
        for key in sorted(value):
            output.update(flatten(value[key], f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            output.update(flatten(item, f"{prefix}[{index}]"))
        output[f"{prefix}.__len__"] = len(value)
    else:
        output[prefix] = value
    return output


def field_diff(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    lhs = flatten(left)
    rhs = flatten(right)
    rows: list[dict[str, Any]] = []
    for path in sorted(set(lhs) | set(rhs)):
        if stable(lhs.get(path)) != stable(rhs.get(path)):
            rows.append({"path": path, "prior": lhs.get(path), "current": rhs.get(path)})
    return rows


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net = [finite(row.get("net_pnl_pct")) for row in trades]
    gross = [finite(row.get("gross_pnl_pct")) for row in trades]
    costs = [finite(row.get("cost_pct")) for row in trades]
    pnl_r = [finite(row.get("pnl_r")) for row in trades if row.get("pnl_r") is not None]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    flats = [value for value in net if value == 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf: float | str
    if gross_loss > 0:
        pf = round(gross_profit / gross_loss, 10)
    elif gross_profit > 0:
        pf = "Infinity"
    else:
        pf = 0.0
    average_win = statistics.fmean(wins) if wins else 0.0
    average_loss = statistics.fmean(losses) if losses else 0.0
    payoff = average_win / abs(average_loss) if average_loss < 0 else (math.inf if average_win > 0 else 0.0)
    return {
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": len(flats),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 10) if trades else 0.0,
        "net_pnl_sum_pct": round(sum(net), 10),
        "gross_pnl_sum_pct": round(sum(gross), 10),
        "cost_sum_pct": round(sum(costs), 10),
        "gross_profit_pct": round(gross_profit, 10),
        "gross_loss_pct": round(gross_loss, 10),
        "profit_factor": pf,
        "average_win_pct": round(average_win, 10),
        "average_loss_pct": round(average_loss, 10),
        "payoff_ratio": round(payoff, 10) if math.isfinite(payoff) else "Infinity",
        "expectancy_net_pct_per_trade": round(statistics.fmean(net), 10) if net else 0.0,
        "expectancy_r": round(statistics.fmean(pnl_r), 10) if pnl_r else 0.0,
        "median_r": round(statistics.median(pnl_r), 10) if pnl_r else 0.0,
        "mean_mfe_pct": round(statistics.fmean(finite(row.get("mfe_pct")) for row in trades), 10) if trades else 0.0,
        "mean_mae_pct": round(statistics.fmean(finite(row.get("mae_pct")) for row in trades), 10) if trades else 0.0,
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in trades).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_short_perf_runner")
    contract = load_json(Path(args.contract).resolve())
    contract["indicator_preroll_bars"] = 320

    proof_path = root / "runtime/r7a4d2_short_execution_harness_verify/short_execution_harness_proof_v1.json"
    entry_path = root / "runtime/r7a4d2_entry_chain_minimal_patch_verify/entry_chain_patch_proof_v1.json"
    plan_path = root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json"
    proof = load_json(proof_path)
    entry_proof = load_json(entry_path)
    short_plan = load_json(plan_path)
    manifest = load_json(root / str(contract["selected_manifest_path"]))
    scenario_plan = load_json(root / str(contract["scenario_plan_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    expected_initial = ["LONG_REGRESSION_MISMATCH:1"]
    if proof.get("state") != "HOLD_SHORT_EXECUTION_HARNESS_MINIMAL_PATCH":
        blockers.append("SHORT_PROOF_STATE_UNEXPECTED")
    if sorted(str(item) for item in proof.get("blockers", [])) != expected_initial:
        blockers.append("SHORT_PROOF_BLOCKER_SET_UNEXPECTED")
    if int(proof.get("targeted_scenario_count", -1)) != 600:
        blockers.append("SHORT_PROOF_SCENARIO_COUNT_INVALID")
    if int(proof.get("completed_scenario_count", -1)) != 600 or int(proof.get("failed_scenario_count", -1)) != 0:
        blockers.append("SHORT_PROOF_COMPLETION_INVALID")
    if int(proof.get("short_closed_trade_count", -1)) != 120:
        blockers.append("SHORT_PROOF_TRADE_COUNT_UNEXPECTED")
    if proof.get("source_registry_parity") is not True:
        blockers.append("SHORT_PROOF_SOURCE_PARITY_INVALID")
    if proof.get("side_effect_attempts") or proof.get("mutation_paths"):
        blockers.append("SHORT_PROOF_SIDE_EFFECT_OR_MUTATION")
    if entry_proof.get("state") != "PASS_ENTRY_CHAIN_MINIMAL_PATCH" or int(entry_proof.get("blocker_count", -1)) != 0:
        blockers.append("ENTRY_CHAIN_PROOF_INVALID")
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_PLAN_INVALID")

    entries = {
        str(row.get("strategy_id") or ""): row
        for row in registry.get("entries", [])
        if isinstance(row, dict)
    }
    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    scenarios = [row for row in scenario_plan.get("scenarios", []) if isinstance(row, dict)]
    scenario_index = {
        (
            str(row.get("strategy_id") or ""),
            str(row.get("segment_id") or ""),
            str(row.get("cost_profile") or ""),
            str(row.get("perturbation") or ""),
        ): row
        for row in scenarios
    }
    if len(entries) != 25:
        blockers.append(f"REGISTRY_ENTRY_COUNT_INVALID:{len(entries)}")
    if len(segments) != 24:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")

    dual_results = {
        str(row.get("scenario_id") or ""): row
        for row in proof.get("results", [])
        if isinstance(row, dict)
    }
    prior_results = {
        str(row.get("scenario_id") or ""): row
        for row in entry_proof.get("results", [])
        if isinstance(row, dict)
    }
    if len(dual_results) != 600:
        blockers.append(f"DUAL_RESULT_COUNT_INVALID:{len(dual_results)}")
    if len(prior_results) != 120:
        blockers.append(f"PRIOR_RESULT_COUNT_INVALID:{len(prior_results)}")

    costs = {str(row["id"]): row for row in contract.get("cost_profiles", []) if isinstance(row, dict)}
    perturbations = {str(row["id"]): row for row in contract.get("perturbations", []) if isinstance(row, dict)}
    if "cost_profile_0" not in costs or "perturbation_0" not in perturbations:
        blockers.append("BASELINE_COST_OR_PERTURBATION_MISSING")

    bindings: dict[str, tuple[type[Any], str]] = {}
    canonical_paths = [registry_path, root / "backend/strategy25/canonical_strategy25_config_v1.json"]
    source_registry_parity = True
    sys.path.insert(0, str(root))
    try:
        for strategy_id in sorted(entries):
            row = entries[strategy_id]
            engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
            repo_path = runner.safe_repo_path(str(engine.get("implementation_path") or ""))
            source_path = root / repo_path
            canonical_paths.append(source_path)
            expected_sha = str(engine.get("source_sha256") or "")
            if not expected_sha or runner.sha256_file(source_path) != expected_sha:
                source_registry_parity = False
                blockers.append(f"SOURCE_REGISTRY_SHA_MISMATCH:{strategy_id}")
                continue
            module = runner.load_module(root, repo_path, strategy_id + "_short_perf")
            bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    before = runner.snapshot(canonical_paths)
    long_results: dict[str, dict[str, Any]] = {}
    replay_failures: list[dict[str, Any]] = []
    side_effect_attempts: list[str] = []
    frame_cache: dict[str, Any] = {}
    contract_long = dict(contract)
    contract_long["short_execution_enabled"] = False
    contract_long["short_target_strategy_ids"] = sorted(short_plan.get("short_target_strategy_ids", []))

    if not blockers:
        sys.path.insert(0, str(root))
        try:
            with runner.side_effect_guard(side_effect_attempts):
                progress = 0
                for segment in segments:
                    segment_id = str(segment["segment_id"])
                    source_path = runner.safe_repo_path(str(segment["source_path"]))
                    path = root / source_path
                    if runner.sha256_file(path) != segment.get("source_sha256"):
                        raise ValueError(f"SEGMENT_SOURCE_SHA_MISMATCH:{segment_id}")
                    frame = frame_cache.get(str(path))
                    if frame is None:
                        frame = runner.load_market_frame(path)
                        frame_cache[str(path)] = frame
                    sample = runner.select_segment_with_preroll(
                        frame,
                        int(segment["start_row"]),
                        int(segment["end_row_exclusive"]),
                        int(contract["segment_bars"]),
                        int(contract["indicator_preroll_bars"]),
                    )
                    for strategy_id in sorted(entries):
                        key = (strategy_id, segment_id, "cost_profile_0", "perturbation_0")
                        scenario = scenario_index.get(key)
                        if not isinstance(scenario, dict):
                            raise ValueError(f"TARGET_SCENARIO_MISSING:{key}")
                        owner, method_name = bindings[strategy_id]
                        try:
                            row = runner.simulate_scenario(
                                scenario,
                                sample,
                                owner,
                                method_name,
                                costs["cost_profile_0"],
                                perturbations["perturbation_0"],
                                contract_long,
                            )
                            long_results[str(scenario.get("scenario_id") or "")] = row
                        except Exception as exc:
                            replay_failures.append({
                                "scenario_id": scenario.get("scenario_id"),
                                "strategy_id": strategy_id,
                                "error": f"{type(exc).__name__}:{exc}",
                            })
                        progress += 1
                        if progress % 50 == 0:
                            print(f"A4D2_PERF_PROGRESS={progress}/600 FAILED={len(replay_failures)}")
        except Exception as exc:
            blockers.append(f"LONG_BASELINE_REPLAY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    after = runner.snapshot(canonical_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if len(long_results) != 600 or replay_failures:
        blockers.append(f"LONG_BASELINE_RESULT_INVALID:{len(long_results)}:{len(replay_failures)}")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPT:{len(side_effect_attempts)}")
    if mutation_paths:
        blockers.append("CANONICAL_MUTATION_DETECTED")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    prior_mismatches: list[dict[str, Any]] = []
    for scenario_id, prior in sorted(prior_results.items()):
        current = long_results.get(scenario_id)
        if not isinstance(current, dict):
            prior_mismatches.append({"scenario_id": scenario_id, "reason": "CURRENT_RESULT_MISSING"})
            continue
        prior_projection = long_projection(prior)
        current_projection = long_projection(current)
        if stable(prior_projection) != stable(current_projection):
            diffs = field_diff(prior_projection, current_projection)
            economic = [row for row in diffs if any(row["path"].startswith(f"$.{field}") for field in ECONOMIC_FIELDS)]
            prior_mismatches.append({
                "scenario_id": scenario_id,
                "strategy_id": current.get("strategy_id"),
                "segment_id": current.get("segment_id"),
                "classification": "LONG_ECONOMIC_MISMATCH" if economic else "LONG_METADATA_ONLY_MISMATCH",
                "diff_count": len(diffs),
                "economic_diff_count": len(economic),
                "diffs": diffs[:50],
            })

    short_trades: list[dict[str, Any]] = []
    short_detail_expected = 0
    detail_missing_scenarios: list[dict[str, Any]] = []
    for row in dual_results.values():
        expected = int(row.get("short_closed_trade_count") or 0)
        short_detail_expected += expected
        samples = [
            trade for trade in row.get("trade_sample", [])
            if isinstance(trade, dict) and str(trade.get("side") or "") == "short"
        ] if isinstance(row.get("trade_sample"), list) else []
        short_trades.extend({**trade, "strategy_id": row.get("strategy_id"), "regime": row.get("regime"), "scenario_id": row.get("scenario_id")} for trade in samples)
        if len(samples) != expected:
            detail_missing_scenarios.append({
                "scenario_id": row.get("scenario_id"),
                "strategy_id": row.get("strategy_id"),
                "expected": expected,
                "captured": len(samples),
            })

    dual_net_sum = round(sum(finite(row.get("net_return_pct")) for row in dual_results.values()), 10)
    long_net_sum = round(sum(finite(row.get("net_return_pct")) for row in long_results.values()), 10)
    incremental_net_sum = round(dual_net_sum - long_net_sum, 10)
    dual_cost_sum = round(sum(finite(row.get("total_cost_pct")) for row in dual_results.values()), 10)
    long_cost_sum = round(sum(finite(row.get("total_cost_pct")) for row in long_results.values()), 10)
    incremental_cost_sum = round(dual_cost_sum - long_cost_sum, 10)

    by_strategy_delta: dict[str, dict[str, Any]] = {}
    by_regime_delta: dict[str, dict[str, Any]] = {}
    grouped_strategy: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    grouped_regime: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for scenario_id, dual in dual_results.items():
        baseline = long_results.get(scenario_id, {})
        grouped_strategy[str(dual.get("strategy_id") or "")].append((dual, baseline))
        grouped_regime[str(dual.get("regime") or "")].append((dual, baseline))
    for key, pairs in sorted(grouped_strategy.items()):
        by_strategy_delta[key] = {
            "scenario_count": len(pairs),
            "short_closed_trade_count": sum(int(dual.get("short_closed_trade_count") or 0) for dual, _ in pairs),
            "dual_net_sum_pct": round(sum(finite(dual.get("net_return_pct")) for dual, _ in pairs), 10),
            "long_baseline_net_sum_pct": round(sum(finite(base.get("net_return_pct")) for _, base in pairs), 10),
            "dual_minus_long_net_pct": round(sum(finite(dual.get("net_return_pct")) - finite(base.get("net_return_pct")) for dual, base in pairs), 10),
            "dual_minus_long_cost_pct": round(sum(finite(dual.get("total_cost_pct")) - finite(base.get("total_cost_pct")) for dual, base in pairs), 10),
        }
    for key, pairs in sorted(grouped_regime.items()):
        by_regime_delta[key] = {
            "scenario_count": len(pairs),
            "short_closed_trade_count": sum(int(dual.get("short_closed_trade_count") or 0) for dual, _ in pairs),
            "dual_minus_long_net_pct": round(sum(finite(dual.get("net_return_pct")) - finite(base.get("net_return_pct")) for dual, base in pairs), 10),
            "dual_minus_long_cost_pct": round(sum(finite(dual.get("total_cost_pct")) - finite(base.get("total_cost_pct")) for dual, base in pairs), 10),
        }

    short_metrics = trade_metrics(short_trades)
    loss_ranking = sorted(
        ({"strategy_id": key, **value} for key, value in by_strategy_delta.items()),
        key=lambda row: (float(row["dual_minus_long_net_pct"]), row["strategy_id"]),
    )
    profit_ranking = sorted(
        ({"strategy_id": key, **value} for key, value in by_strategy_delta.items()),
        key=lambda row: (-float(row["dual_minus_long_net_pct"]), row["strategy_id"]),
    )

    performance_flags: list[str] = []
    if incremental_net_sum <= 0:
        performance_flags.append("DUAL_MINUS_LONG_NET_NON_POSITIVE")
    pf = short_metrics.get("profit_factor")
    if isinstance(pf, (int, float)) and float(pf) < 1.0:
        performance_flags.append("SHORT_PROFIT_FACTOR_BELOW_ONE")
    if finite(short_metrics.get("expectancy_r")) <= 0:
        performance_flags.append("SHORT_EXPECTANCY_R_NON_POSITIVE")
    if finite(short_metrics.get("expectancy_net_pct_per_trade")) <= 0:
        performance_flags.append("SHORT_EXPECTANCY_NET_NON_POSITIVE")
    if detail_missing_scenarios:
        performance_flags.append("SHORT_TRADE_DETAIL_INCOMPLETE")

    mismatch_economic = any(row.get("classification") == "LONG_ECONOMIC_MISMATCH" for row in prior_mismatches)
    if len(prior_mismatches) != 1:
        blockers.append(f"LONG_MISMATCH_REPRO_COUNT_INVALID:{len(prior_mismatches)}")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        state = "HOLD_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_INPUT"
        next_stage = "R7.A4D2_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE"
    elif mismatch_economic:
        state = "HOLD_LONG_REGRESSION_SINGLE_CASE"
        next_stage = "R7.A4D2_LONG_REGRESSION_SINGLE_CASE_CLOSURE"
    elif detail_missing_scenarios:
        state = "HOLD_SHORT_TRADE_DETAIL_COVERAGE"
        next_stage = "R7.A4D2_SHORT_TRADE_DETAIL_COVERAGE_CLOSURE"
    elif performance_flags:
        state = "HOLD_SHORT_PERFORMANCE_NEGATIVE"
        next_stage = "R7.A4D2_SHORT_PERFORMANCE_ROOT_CAUSE_CLOSURE"
    else:
        state = "PASS_SHORT_MISMATCH_AND_PERFORMANCE_DIAGNOSE"
        next_stage = "R7.A4D2_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE"

    evidence = {
        "schema": "r7a4d2_short_harness_mismatch_performance_diagnose_v1",
        "official_stage": "R7.A4D2_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "source_registry_parity": source_registry_parity,
        "side_effect_attempts": side_effect_attempts,
        "mutation_paths": mutation_paths,
        "dual_result_count": len(dual_results),
        "long_baseline_result_count": len(long_results),
        "long_regression_mismatch_count": len(prior_mismatches),
        "long_regression_mismatch_sample": prior_mismatches[:5],
        "short_trade_detail_expected_count": short_detail_expected,
        "short_trade_detail_captured_count": len(short_trades),
        "short_trade_detail_missing_scenario_count": len(detail_missing_scenarios),
        "short_trade_detail_missing_sample": detail_missing_scenarios[:20],
        "dual_net_return_sum_pct": dual_net_sum,
        "long_baseline_net_return_sum_pct": long_net_sum,
        "dual_minus_long_net_return_pct": incremental_net_sum,
        "dual_total_cost_sum_pct": dual_cost_sum,
        "long_baseline_total_cost_sum_pct": long_cost_sum,
        "dual_minus_long_cost_pct": incremental_cost_sum,
        "short_trade_metrics": short_metrics,
        "performance_flags": performance_flags,
        "by_strategy_delta": by_strategy_delta,
        "by_regime_delta": by_regime_delta,
        "loss_driver_top5": loss_ranking[:5],
        "profit_driver_top5": profit_ranking[:5],
        "next_stage": next_stage,
    }
    output = root / "runtime/r7a4d2_short_harness_mismatch_performance/diagnose_v1.json"
    runner.atomic_json(output, evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("DUAL_RESULT_COUNT=" + str(len(dual_results)))
    print("LONG_BASELINE_RESULT_COUNT=" + str(len(long_results)))
    print("LONG_REGRESSION_MISMATCH_COUNT=" + str(len(prior_mismatches)))
    print("LONG_REGRESSION_MISMATCH_SAMPLE=" + json.dumps(prior_mismatches[:5], ensure_ascii=False, sort_keys=True))
    print("SHORT_TRADE_DETAIL_EXPECTED_COUNT=" + str(short_detail_expected))
    print("SHORT_TRADE_DETAIL_CAPTURED_COUNT=" + str(len(short_trades)))
    print("SHORT_TRADE_DETAIL_MISSING_SCENARIO_COUNT=" + str(len(detail_missing_scenarios)))
    print("DUAL_NET_RETURN_SUM_PCT=" + str(dual_net_sum))
    print("LONG_BASELINE_NET_RETURN_SUM_PCT=" + str(long_net_sum))
    print("DUAL_MINUS_LONG_NET_RETURN_PCT=" + str(incremental_net_sum))
    print("DUAL_MINUS_LONG_COST_PCT=" + str(incremental_cost_sum))
    print("SHORT_TRADE_METRICS=" + json.dumps(short_metrics, ensure_ascii=False, sort_keys=True))
    print("PERFORMANCE_FLAGS=" + json.dumps(performance_flags, ensure_ascii=False))
    print("LOSS_DRIVER_TOP5=" + json.dumps(loss_ranking[:5], ensure_ascii=False, sort_keys=True))
    print("PROFIT_DRIVER_TOP5=" + json.dumps(profit_ranking[:5], ensure_ascii=False, sort_keys=True))
    print("REGIME_DELTA=" + json.dumps(by_regime_delta, ensure_ascii=False, sort_keys=True))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if state.startswith("PASS_") else "2"))
    return 0 if state.startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
