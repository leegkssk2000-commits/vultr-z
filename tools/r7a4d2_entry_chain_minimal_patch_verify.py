#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TARGETS = (
    "break_and_continue",
    "rbreaker_like",
    "squeeze_break",
    "trend_ma_macd",
    "vwap_revert",
)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_entry_chain_verify_runner")
    contract = load_json(Path(args.contract).resolve())
    contract["indicator_preroll_bars"] = 320
    manifest = load_json(root / str(contract["selected_manifest_path"]))
    plan = load_json(root / str(contract["scenario_plan_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    entries = {
        str(row.get("strategy_id") or ""): row
        for row in registry.get("entries", [])
        if isinstance(row, dict)
    }
    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    scenarios = [row for row in plan.get("scenarios", []) if isinstance(row, dict)]
    scenario_index = {
        (
            str(row.get("strategy_id")),
            str(row.get("segment_id")),
            str(row.get("cost_profile")),
            str(row.get("perturbation")),
        ): row
        for row in scenarios
    }
    costs = {str(row["id"]): row for row in contract["cost_profiles"]}
    perturbations = {str(row["id"]): row for row in contract["perturbations"]}

    blockers: list[str] = []
    if len(segments) != 24:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")
    if any(strategy_id not in entries for strategy_id in TARGETS):
        blockers.append("TARGET_REGISTRY_ENTRY_MISSING")

    bindings: dict[str, tuple[type[Any], str]] = {}
    source_registry_parity = True
    canonical_paths = [registry_path, root / "backend/strategy25/canonical_strategy25_config_v1.json"]
    sys.path.insert(0, str(root))
    try:
        for strategy_id in TARGETS:
            row = entries.get(strategy_id, {})
            engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
            repo_path = runner.safe_repo_path(str(engine.get("implementation_path") or ""))
            source_path = root / repo_path
            canonical_paths.append(source_path)
            expected_sha = str(engine.get("source_sha256") or "")
            if not expected_sha or runner.sha256_file(source_path) != expected_sha:
                source_registry_parity = False
                blockers.append(f"SOURCE_REGISTRY_SHA_MISMATCH:{strategy_id}")
                continue
            module = runner.load_module(root, repo_path, strategy_id + "_a4d2")
            bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    before = runner.snapshot(canonical_paths)
    results: list[dict[str, Any]] = []
    side_effect_attempts: list[str] = []
    source_frames: dict[str, Any] = {}

    if not blockers:
        sys.path.insert(0, str(root))
        try:
            with runner.side_effect_guard(side_effect_attempts):
                for segment in segments:
                    segment_id = str(segment["segment_id"])
                    source_path = runner.safe_repo_path(str(segment["source_path"]))
                    path = root / source_path
                    if runner.sha256_file(path) != segment.get("source_sha256"):
                        raise ValueError(f"SEGMENT_SOURCE_SHA_MISMATCH:{segment_id}")
                    cache_key = str(path)
                    frame = source_frames.get(cache_key)
                    if frame is None:
                        frame = runner.load_market_frame(path)
                        source_frames[cache_key] = frame
                    sample = runner.select_segment_with_preroll(
                        frame,
                        int(segment["start_row"]),
                        int(segment["end_row_exclusive"]),
                        int(contract["segment_bars"]),
                        int(contract["indicator_preroll_bars"]),
                    )
                    for strategy_id in TARGETS:
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
                                contract,
                            )
                        except Exception as exc:
                            row = {
                                "scenario_id": scenario.get("scenario_id"),
                                "strategy_id": strategy_id,
                                "segment_id": segment_id,
                                "completed": False,
                                "error": f"{type(exc).__name__}:{exc}",
                            }
                        results.append(row)
        except Exception as exc:
            blockers.append(f"TARGETED_REPLAY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    after = runner.snapshot(canonical_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    completed = [row for row in results if row.get("completed") is True]
    failures = [row for row in results if row.get("completed") is not True]
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in completed:
        by_strategy[str(row.get("strategy_id"))].append(row)

    strategy_trade_counts = {
        strategy_id: sum(int(row.get("trade_count") or 0) for row in by_strategy.get(strategy_id, []))
        for strategy_id in TARGETS
    }
    orphan_add_count = sum(int(row.get("orphan_add_block_count") or 0) for row in completed)
    bars_invalid_count = sum(int(row.get("bars") or 0) != 320 for row in completed)
    preroll_values = [int(row.get("indicator_preroll_bars") or 0) for row in completed]
    context_invalid_count = sum(
        not (320 <= int(row.get("context_bars") or 0) <= 640) for row in completed
    )

    if len(results) != 120:
        blockers.append(f"TARGETED_SCENARIO_COUNT_INVALID:{len(results)}")
    if len(completed) != 120 or failures:
        blockers.append(f"TARGETED_SCENARIO_FAILURES:{len(failures)}")
    if orphan_add_count != 0:
        blockers.append(f"ORPHAN_ADD_NOT_ZERO:{orphan_add_count}")
    if strategy_trade_counts.get("vwap_revert", 0) <= 0:
        blockers.append("VWAP_REVERT_EXECUTABLE_TRADE_MISSING")
    if bars_invalid_count:
        blockers.append(f"EVALUATION_BAR_COUNT_INVALID:{bars_invalid_count}")
    if context_invalid_count:
        blockers.append(f"CONTEXT_BAR_COUNT_INVALID:{context_invalid_count}")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPTS:{len(side_effect_attempts)}")
    if mutation_paths:
        blockers.append("CANONICAL_MUTATION_DETECTED")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    blockers = list(dict.fromkeys(blockers))
    passed = not blockers
    state = "PASS_ENTRY_CHAIN_MINIMAL_PATCH" if passed else "HOLD_ENTRY_CHAIN_MINIMAL_PATCH"
    evidence = {
        "schema": "r7a4d2_entry_chain_minimal_patch_verify_v1",
        "official_stage": "R7.A4D2_ENTRY_CHAIN_MINIMAL_PATCH",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "targeted_scenario_count": len(results),
        "completed_scenario_count": len(completed),
        "failed_scenario_count": len(failures),
        "strategy_trade_counts": strategy_trade_counts,
        "orphan_add_block_count": orphan_add_count,
        "evaluation_bar_invalid_count": bars_invalid_count,
        "context_bar_invalid_count": context_invalid_count,
        "preroll_min_bars": min(preroll_values) if preroll_values else 0,
        "preroll_max_bars": max(preroll_values) if preroll_values else 0,
        "source_registry_parity": source_registry_parity,
        "side_effect_attempts": side_effect_attempts,
        "mutation_paths": mutation_paths,
        "error_histogram": dict(sorted(Counter(str(row.get("error") or "") for row in failures).items())),
        "results": results,
        "next_stage": "R7.A4D2_SHORT_EXECUTION_HARNESS_PLAN" if passed else "R7.A4D2_ENTRY_CHAIN_MINIMAL_PATCH_DIAGNOSE",
    }
    output = root / "runtime/r7a4d2_entry_chain_minimal_patch_verify/entry_chain_patch_proof_v1.json"
    runner.atomic_json(output, evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("TARGETED_SCENARIO_COUNT=" + str(len(results)))
    print("COMPLETED_SCENARIO_COUNT=" + str(len(completed)))
    print("FAILED_SCENARIO_COUNT=" + str(len(failures)))
    print("STRATEGY_TRADE_COUNTS=" + json.dumps(strategy_trade_counts, sort_keys=True))
    print("VWAP_REVERT_TRADE_COUNT=" + str(strategy_trade_counts.get("vwap_revert", 0)))
    print("ORPHAN_ADD_BLOCK_COUNT=" + str(orphan_add_count))
    print("EVALUATION_BAR_INVALID_COUNT=" + str(bars_invalid_count))
    print("PREROLL_MIN_BARS=" + str(evidence["preroll_min_bars"]))
    print("PREROLL_MAX_BARS=" + str(evidence["preroll_max_bars"]))
    print("SOURCE_REGISTRY_PARITY=" + str(source_registry_parity).lower())
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("PROOF_JSON=" + str(output))
    print("NEXT_STAGE=" + str(evidence["next_stage"]))
    print("RC=" + ("0" if passed else "2"))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
