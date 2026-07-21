#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
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


def nested_histogram(rows: list[dict[str, Any]], outer: str, inner: str) -> dict[str, dict[str, int]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        result[str(row.get(outer) or "")][str(row.get(inner) or "")] += 1
    return {key: dict(sorted(value.items())) for key, value in sorted(result.items())}


def classify_trace(rows: list[dict[str, Any]], closed_trades: int) -> tuple[list[str], str]:
    classes: list[str] = []
    allowed = [row for row in rows if bool(row.get("admitted"))]
    blocked = [row for row in rows if not bool(row.get("admitted"))]
    allowed_flat_enter = sum(row.get("candidate_state") == "FLAT_ENTER" for row in allowed)
    blocked_flat_enter = sum(row.get("candidate_state") == "FLAT_ENTER" for row in blocked)
    allowed_orphan = sum(row.get("candidate_state") == "ORPHAN_MANAGEMENT" for row in allowed)
    if blocked_flat_enter:
        classes.append("BLOCKED_REGIME_CONTAINS_FLAT_ENTER")
    if allowed_orphan:
        classes.append("ALLOWED_REGIME_ORPHAN_MANAGEMENT")
    if allowed_flat_enter == 0:
        classes.append("ALLOWED_REGIME_FLAT_ENTER_ZERO")
        next_stage = "R7.A4D2_SHORT_MARKET_REGIME_COVERAGE_REDESIGN"
    elif allowed_flat_enter > closed_trades:
        classes.append("ENTER_TO_CLOSED_TRADE_EXECUTION_GAP")
        next_stage = "R7.A4D2_SHORT_ENTRY_EXECUTION_CLOSURE"
    elif allowed_flat_enter == closed_trades == 1:
        classes.append("ALLOWED_REGIME_SINGLE_ENTER_ONLY")
        next_stage = "R7.A4D2_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE"
    else:
        classes.append("ALLOWED_ENTER_EXECUTION_CLOSED")
        next_stage = "R7.A4D2_NO_TRIGGER_STRATEGY_COVERAGE_DIAGNOSE"
    if not classes:
        classes.append("UNCLASSIFIED")
    return classes, next_stage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_no_trigger_trace_runner")
    contract = load_json(Path(args.contract).resolve())
    contract["indicator_preroll_bars"] = 320

    prior = load_json(root / "runtime/r7a4d2_short_rr_sidecar_counterfactual/counterfactual_proof_v1.json")
    short_plan = load_json(root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json")
    manifest = load_json(root / str(contract["selected_manifest_path"]))
    scenario_plan = load_json(root / str(contract["scenario_plan_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    if prior.get("state") != "PASS_SHORT_RR_SIDECAR_COUNTERFACTUAL_600":
        blockers.append("PRIOR_COUNTERFACTUAL_NOT_PASS")
    if int(prior.get("blocker_count", -1)) != 0:
        blockers.append("PRIOR_COUNTERFACTUAL_BLOCKED")
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_PLAN_INVALID")

    entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
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
            module = runner.load_module(root, repo_path, strategy_id + "_coverage_trace")
            bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        sys.path.remove(str(root))

    protected = [root / "runtime/r7a4d2_short_rr_sidecar_counterfactual/counterfactual_proof_v1.json"]
    before = runner.snapshot(canonical_paths + protected)
    side_effect_attempts: list[str] = []
    failures: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    frame_cache: dict[str, Any] = {}
    policy_contract = dict(contract)
    policy_contract.update({
        "short_execution_enabled": True,
        "short_target_strategy_ids": target_ids,
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
    })

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
                            results.append(runner.simulate_scenario(
                                scenario,
                                sample,
                                owner,
                                method_name,
                                costs["cost_profile_0"],
                                perturbations["perturbation_0"],
                                policy_contract,
                            ))
                        except Exception as exc:
                            failures.append({
                                "scenario_id": scenario.get("scenario_id"),
                                "strategy_id": strategy_id,
                                "error": f"{type(exc).__name__}:{exc}",
                            })
                        progress += 1
                        if progress % 50 == 0:
                            print(f"A4D2_COVERAGE_PROGRESS={progress}/600 FAILED={len(failures)}")
        except Exception as exc:
            blockers.append(f"COVERAGE_TRACE_REPLAY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            sys.path.remove(str(root))

    after = runner.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if len(results) != 600 or failures:
        blockers.append(f"TRACE_RESULT_INVALID:{len(results)}:{len(failures)}")
    if mutation_paths:
        blockers.append("CANONICAL_OR_PRIOR_PROOF_MUTATION")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPT:{len(side_effect_attempts)}")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    trace = [item for row in results for item in row.get("short_candidate_trace", []) if isinstance(item, dict)]
    candidate_count = len(trace)
    admitted = [row for row in trace if bool(row.get("admitted"))]
    blocked = [row for row in trace if not bool(row.get("admitted"))]
    closed_trades = sum(int(row.get("short_closed_trade_count") or 0) for row in results)
    policy_net = sum(finite(row.get("net_return_pct")) for row in results)
    prior_candidate = int(prior.get("short_policy_candidate_count", -1))
    prior_admitted = int(prior.get("short_policy_admitted_action_count", -1))
    prior_blocked = int(prior.get("short_policy_regime_block_count", -1))
    prior_closed = int(prior.get("short_trade_metrics", {}).get("trade_count", -1)) if isinstance(prior.get("short_trade_metrics"), dict) else -1
    if (candidate_count, len(admitted), len(blocked), closed_trades) != (
        prior_candidate,
        prior_admitted,
        prior_blocked,
        prior_closed,
    ):
        blockers.append(
            f"TRACE_PRIOR_PARITY_MISMATCH:{candidate_count}:{len(admitted)}:{len(blocked)}:{closed_trades}"
        )
    if abs(policy_net - finite(prior.get("policy_net_return_sum_pct"))) > 1e-10:
        blockers.append("TRACE_POLICY_NET_PARITY_MISMATCH")

    action_hist = dict(sorted(Counter(str(row.get("legacy_action") or "") for row in trace).items()))
    state_hist = dict(sorted(Counter(str(row.get("candidate_state") or "") for row in trace).items()))
    admission_hist = dict(sorted(Counter(str(row.get("admission_reason") or "") for row in trace).items()))
    regime_action = nested_histogram(trace, "regime", "legacy_action")
    strategy_action = nested_histogram(trace, "strategy_id", "legacy_action")
    strategy_state = nested_histogram(trace, "strategy_id", "candidate_state")

    allowed_flat_enter = sum(row.get("candidate_state") == "FLAT_ENTER" for row in admitted)
    blocked_flat_enter = sum(row.get("candidate_state") == "FLAT_ENTER" for row in blocked)
    allowed_orphan = sum(row.get("candidate_state") == "ORPHAN_MANAGEMENT" for row in admitted)
    allowed_position_management = sum(row.get("candidate_state") == "POSITION_MANAGEMENT" for row in admitted)
    classifications, next_stage = classify_trace(trace, closed_trades)

    blockers = list(dict.fromkeys(blockers))
    state = "PASS_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE" if not blockers else "HOLD_NO_TRIGGER_MARKET_COVERAGE_INPUT"
    if blockers:
        next_stage = "R7.A4D2_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE"

    evidence = {
        "schema": "r7a4d2_no_trigger_market_coverage_diagnose_v1",
        "official_stage": "R7.A4D2_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "targeted_scenario_count": 600,
        "completed_scenario_count": len(results),
        "failed_scenario_count": len(failures),
        "candidate_count": candidate_count,
        "admitted_count": len(admitted),
        "regime_block_count": len(blocked),
        "short_closed_trade_count": closed_trades,
        "allowed_flat_enter_count": allowed_flat_enter,
        "blocked_flat_enter_count": blocked_flat_enter,
        "allowed_orphan_management_count": allowed_orphan,
        "allowed_position_management_count": allowed_position_management,
        "action_histogram": action_hist,
        "candidate_state_histogram": state_hist,
        "admission_histogram": admission_hist,
        "regime_action_histogram": regime_action,
        "strategy_action_histogram": strategy_action,
        "strategy_state_histogram": strategy_state,
        "root_cause_classifications": classifications,
        "trace_policy_net_return_sum_pct": round(policy_net, 10),
        "source_registry_parity": source_registry_parity,
        "mutation_path_count": len(mutation_paths),
        "side_effect_attempt_count": len(side_effect_attempts),
        "candidate_trace": trace,
        "failures": failures[:20],
        "next_stage": next_stage,
    }
    output_dir = root / "runtime/r7a4d2_no_trigger_market_coverage_diagnose"
    runner.atomic_json(output_dir / "coverage_diagnose_v1.json", evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("TARGETED_SCENARIO_COUNT=600")
    print("COMPLETED_SCENARIO_COUNT=" + str(len(results)))
    print("FAILED_SCENARIO_COUNT=" + str(len(failures)))
    print("SHORT_POLICY_CANDIDATE_COUNT=" + str(candidate_count))
    print("SHORT_POLICY_ADMITTED_COUNT=" + str(len(admitted)))
    print("SHORT_POLICY_REGIME_BLOCK_COUNT=" + str(len(blocked)))
    print("SHORT_CLOSED_TRADE_COUNT=" + str(closed_trades))
    print("ALLOWED_FLAT_ENTER_COUNT=" + str(allowed_flat_enter))
    print("BLOCKED_FLAT_ENTER_COUNT=" + str(blocked_flat_enter))
    print("ALLOWED_ORPHAN_MANAGEMENT_COUNT=" + str(allowed_orphan))
    print("ALLOWED_POSITION_MANAGEMENT_COUNT=" + str(allowed_position_management))
    print("ACTION_HISTOGRAM=" + json.dumps(action_hist, ensure_ascii=False, sort_keys=True))
    print("CANDIDATE_STATE_HISTOGRAM=" + json.dumps(state_hist, ensure_ascii=False, sort_keys=True))
    print("REGIME_ACTION_HISTOGRAM=" + json.dumps(regime_action, ensure_ascii=False, sort_keys=True))
    print("STRATEGY_ACTION_HISTOGRAM=" + json.dumps(strategy_action, ensure_ascii=False, sort_keys=True))
    print("STRATEGY_STATE_HISTOGRAM=" + json.dumps(strategy_state, ensure_ascii=False, sort_keys=True))
    print("ROOT_CAUSE_CLASSIFICATIONS=" + json.dumps(classifications, ensure_ascii=False))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output_dir / "coverage_diagnose_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
