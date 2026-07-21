#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
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


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def long_projection(row: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in row.items()
        if not str(key).startswith("short_")
    }
    samples: list[dict[str, Any]] = []
    for trade in result.get("trade_sample", []) if isinstance(result.get("trade_sample"), list) else []:
        if isinstance(trade, dict):
            samples.append({key: value for key, value in trade.items() if key != "side"})
    if "trade_sample" in result:
        result["trade_sample"] = samples
    return result


def stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_short_verify_runner")
    contract = load_json(Path(args.contract).resolve())
    contract["indicator_preroll_bars"] = 320

    short_plan_path = root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json"
    entry_proof_path = root / "runtime/r7a4d2_entry_chain_minimal_patch_verify/entry_chain_patch_proof_v1.json"
    short_plan = load_json(short_plan_path)
    entry_proof = load_json(entry_proof_path)
    manifest = load_json(root / str(contract["selected_manifest_path"]))
    scenario_plan = load_json(root / str(contract["scenario_plan_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    targets = {
        str(item)
        for item in short_plan.get("short_target_strategy_ids", [])
        if str(item)
    }
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_PLAN_NOT_PASS")
    if len(targets) != int(short_plan.get("short_target_strategy_count") or -1):
        blockers.append("SHORT_PLAN_TARGET_COUNT_INVALID")
    if len(targets) != 12:
        blockers.append(f"SHORT_TARGET_COUNT_NOT_12:{len(targets)}")
    if entry_proof.get("state") != "PASS_ENTRY_CHAIN_MINIMAL_PATCH":
        blockers.append("ENTRY_CHAIN_PROOF_NOT_PASS")
    if int(entry_proof.get("blocker_count") or -1) != 0:
        blockers.append("ENTRY_CHAIN_PROOF_BLOCKED")

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

    prior_results = {
        str(row.get("scenario_id") or ""): row
        for row in entry_proof.get("results", [])
        if isinstance(row, dict)
    }
    if len(prior_results) != 120:
        blockers.append(f"ENTRY_CHAIN_RESULT_COUNT_INVALID:{len(prior_results)}")

    costs = {str(row["id"]): row for row in contract.get("cost_profiles", [])}
    perturbations = {str(row["id"]): row for row in contract.get("perturbations", [])}
    if "cost_profile_0" not in costs or "perturbation_0" not in perturbations:
        blockers.append("BASELINE_COST_OR_PERTURBATION_MISSING")

    bindings: dict[str, tuple[type[Any], str]] = {}
    canonical_paths = [
        registry_path,
        root / "backend/strategy25/canonical_strategy25_config_v1.json",
    ]
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
            module = runner.load_module(root, repo_path, strategy_id + "_short_verify")
            bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    before = runner.snapshot(canonical_paths)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    long_mismatches: list[dict[str, Any]] = []
    side_effect_attempts: list[str] = []
    frame_cache: dict[str, Any] = {}

    contract_short = dict(contract)
    contract_short["short_execution_enabled"] = True
    contract_short["short_target_strategy_ids"] = sorted(targets)
    contract_long_only = dict(contract)
    contract_long_only["short_execution_enabled"] = False
    contract_long_only["short_target_strategy_ids"] = sorted(targets)

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
                    cache_key = str(path)
                    frame = frame_cache.get(cache_key)
                    if frame is None:
                        frame = runner.load_market_frame(path)
                        frame_cache[cache_key] = frame
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
                            dual_row = runner.simulate_scenario(
                                scenario,
                                sample,
                                owner,
                                method_name,
                                costs["cost_profile_0"],
                                perturbations["perturbation_0"],
                                contract_short,
                            )
                        except Exception as exc:
                            dual_row = {
                                "scenario_id": scenario.get("scenario_id"),
                                "strategy_id": strategy_id,
                                "segment_id": segment_id,
                                "completed": False,
                                "error": f"{type(exc).__name__}:{exc}",
                            }
                        results.append(dual_row)
                        if dual_row.get("completed") is not True:
                            failures.append(dual_row)

                        if strategy_id in ENTRY_CHAIN_TARGETS:
                            prior = prior_results.get(str(scenario.get("scenario_id") or ""))
                            if not isinstance(prior, dict):
                                long_mismatches.append({
                                    "scenario_id": scenario.get("scenario_id"),
                                    "strategy_id": strategy_id,
                                    "reason": "PRIOR_RESULT_MISSING",
                                })
                            else:
                                try:
                                    long_row = runner.simulate_scenario(
                                        scenario,
                                        sample,
                                        owner,
                                        method_name,
                                        costs["cost_profile_0"],
                                        perturbations["perturbation_0"],
                                        contract_long_only,
                                    )
                                    if stable(long_projection(long_row)) != stable(long_projection(prior)):
                                        long_mismatches.append({
                                            "scenario_id": scenario.get("scenario_id"),
                                            "strategy_id": strategy_id,
                                            "reason": "LONG_PROJECTION_MISMATCH",
                                        })
                                except Exception as exc:
                                    long_mismatches.append({
                                        "scenario_id": scenario.get("scenario_id"),
                                        "strategy_id": strategy_id,
                                        "reason": f"LONG_REPLAY_ERROR:{type(exc).__name__}:{exc}",
                                    })
                        progress += 1
                        if progress % 25 == 0:
                            print(
                                f"A4D2_SHORT_PROGRESS={progress}/600 "
                                f"FAILED={len(failures)} LONG_MISMATCH={len(long_mismatches)}"
                            )
        except Exception as exc:
            blockers.append(f"SHORT_TARGETED_VERIFY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    after = runner.snapshot(canonical_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    completed = [row for row in results if row.get("completed") is True]
    bars_invalid = sum(int(row.get("bars") or 0) != 320 for row in completed)
    context_invalid = sum(
        not (320 <= int(row.get("context_bars") or 0) <= 640)
        for row in completed
    )
    short_enter = sum(int(row.get("short_enter_signal_count") or 0) for row in completed)
    short_add = sum(int(row.get("short_add_signal_count") or 0) for row in completed)
    short_reduce = sum(int(row.get("short_reduce_signal_count") or 0) for row in completed)
    short_exit = sum(int(row.get("short_exit_signal_count") or 0) for row in completed)
    short_trades = sum(int(row.get("short_closed_trade_count") or 0) for row in completed)
    short_invalid = sum(int(row.get("short_invalid_geometry_count") or 0) for row in completed)
    short_orphan = sum(int(row.get("short_orphan_add_block_count") or 0) for row in completed)

    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in completed:
        by_strategy[str(row.get("strategy_id") or "")].append(row)
    strategy_summary = {}
    for strategy_id in sorted(entries):
        rows = by_strategy.get(strategy_id, [])
        strategy_summary[strategy_id] = {
            "scenario_count": len(rows),
            "trade_count": sum(int(row.get("trade_count") or 0) for row in rows),
            "short_enter_signal_count": sum(int(row.get("short_enter_signal_count") or 0) for row in rows),
            "short_add_signal_count": sum(int(row.get("short_add_signal_count") or 0) for row in rows),
            "short_closed_trade_count": sum(int(row.get("short_closed_trade_count") or 0) for row in rows),
            "short_invalid_geometry_count": sum(int(row.get("short_invalid_geometry_count") or 0) for row in rows),
            "short_orphan_add_block_count": sum(int(row.get("short_orphan_add_block_count") or 0) for row in rows),
            "net_return_sum_pct": round(sum(float(row.get("net_return_pct") or 0.0) for row in rows), 10),
        }

    if len(results) != 600:
        blockers.append(f"TARGETED_SCENARIO_COUNT_INVALID:{len(results)}")
    if len(completed) != 600 or failures:
        blockers.append(f"TARGETED_SCENARIO_FAILURES:{len(failures)}")
    if short_enter <= 0:
        blockers.append("SHORT_ENTER_SIGNAL_MISSING")
    if short_trades <= 0:
        blockers.append("SHORT_CLOSED_TRADE_MISSING")
    if short_invalid != 0:
        blockers.append(f"SHORT_INVALID_GEOMETRY_NOT_ZERO:{short_invalid}")
    if short_orphan != 0:
        blockers.append(f"SHORT_ORPHAN_ADD_NOT_ZERO:{short_orphan}")
    if long_mismatches:
        blockers.append(f"LONG_REGRESSION_MISMATCH:{len(long_mismatches)}")
    if bars_invalid:
        blockers.append(f"EVALUATION_BAR_COUNT_INVALID:{bars_invalid}")
    if context_invalid:
        blockers.append(f"CONTEXT_BAR_COUNT_INVALID:{context_invalid}")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPTS:{len(side_effect_attempts)}")
    if mutation_paths:
        blockers.append("CANONICAL_MUTATION_DETECTED")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    blockers = list(dict.fromkeys(blockers))
    passed = not blockers
    state = (
        "PASS_SHORT_EXECUTION_HARNESS_MINIMAL_PATCH"
        if passed
        else "HOLD_SHORT_EXECUTION_HARNESS_MINIMAL_PATCH"
    )
    evidence = {
        "schema": "r7a4d2_short_execution_harness_verify_v1",
        "official_stage": "R7.A4D2_SHORT_EXECUTION_HARNESS_MINIMAL_PATCH",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "short_target_strategy_count": len(targets),
        "short_target_strategy_ids": sorted(targets),
        "targeted_scenario_count": len(results),
        "completed_scenario_count": len(completed),
        "failed_scenario_count": len(failures),
        "long_regression_reference_count": len(prior_results),
        "long_regression_mismatch_count": len(long_mismatches),
        "short_enter_signal_count": short_enter,
        "short_add_signal_count": short_add,
        "short_reduce_signal_count": short_reduce,
        "short_exit_signal_count": short_exit,
        "short_closed_trade_count": short_trades,
        "short_invalid_geometry_count": short_invalid,
        "short_orphan_add_block_count": short_orphan,
        "evaluation_bar_invalid_count": bars_invalid,
        "context_bar_invalid_count": context_invalid,
        "source_registry_parity": source_registry_parity,
        "side_effect_attempts": side_effect_attempts,
        "mutation_paths": mutation_paths,
        "error_histogram": dict(sorted(Counter(str(row.get("error") or "") for row in failures).items())),
        "long_mismatch_sample": long_mismatches[:20],
        "strategy_summary": strategy_summary,
        "results": results,
        "next_stage": (
            "R7.A4D2_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE"
            if passed
            else "R7.A4D2_SHORT_EXECUTION_HARNESS_DIAGNOSE"
        ),
    }
    output = root / "runtime/r7a4d2_short_execution_harness_verify/short_execution_harness_proof_v1.json"
    runner.atomic_json(output, evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("SHORT_TARGET_STRATEGY_COUNT=" + str(len(targets)))
    print("TARGETED_SCENARIO_COUNT=" + str(len(results)))
    print("COMPLETED_SCENARIO_COUNT=" + str(len(completed)))
    print("FAILED_SCENARIO_COUNT=" + str(len(failures)))
    print("LONG_REGRESSION_REFERENCE_COUNT=" + str(len(prior_results)))
    print("LONG_REGRESSION_MISMATCH_COUNT=" + str(len(long_mismatches)))
    print("SHORT_ENTER_SIGNAL_COUNT=" + str(short_enter))
    print("SHORT_ADD_SIGNAL_COUNT=" + str(short_add))
    print("SHORT_REDUCE_SIGNAL_COUNT=" + str(short_reduce))
    print("SHORT_EXIT_SIGNAL_COUNT=" + str(short_exit))
    print("SHORT_CLOSED_TRADE_COUNT=" + str(short_trades))
    print("SHORT_INVALID_GEOMETRY_COUNT=" + str(short_invalid))
    print("SHORT_ORPHAN_ADD_BLOCK_COUNT=" + str(short_orphan))
    print("EVALUATION_BAR_INVALID_COUNT=" + str(bars_invalid))
    print("SOURCE_REGISTRY_PARITY=" + str(source_registry_parity).lower())
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("STRATEGY_SUMMARY=" + json.dumps(strategy_summary, ensure_ascii=False, sort_keys=True))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("PROOF_JSON=" + str(output))
    print("NEXT_STAGE=" + str(evidence["next_stage"]))
    print("RC=" + ("0" if passed else "2"))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
