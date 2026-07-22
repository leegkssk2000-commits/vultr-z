#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SEGMENT_BARS = 320
PREROLL_BARS = 320
MAX_SCAN_SEGMENTS_PER_BUCKET = 48
MAX_SIGNALS_PER_SEGMENT = 4


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


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def segment_metrics(frame: pd.DataFrame) -> dict[str, float]:
    close = frame["close"].astype(float).to_numpy()
    returns = np.diff(np.log(np.maximum(close, 1e-12)))
    total_return = float(close[-1] / close[0] - 1.0)
    volatility = float(np.std(returns)) if returns.size else 0.0
    scaled_volatility = volatility * math.sqrt(max(len(close), 1))
    trend_score = total_return / max(scaled_volatility, 1e-9)
    peaks = np.maximum.accumulate(close)
    drawdowns = close / np.maximum(peaks, 1e-12) - 1.0
    trough_index = int(np.argmin(drawdowns))
    max_drawdown = float(drawdowns[trough_index])
    recovery = float(close[-1] / max(float(close[trough_index]), 1e-12) - 1.0)
    return {
        "return": round(total_return, 12),
        "volatility": round(volatility, 12),
        "trend_score": round(trend_score, 12),
        "max_drawdown": round(max_drawdown, 12),
        "recovery": round(recovery, 12),
        "shock_score": round(abs(max_drawdown) + max(recovery, 0.0), 12),
    }


def source_symbol(frame: pd.DataFrame) -> str | None:
    for name in ("symbol", "ticker", "market", "instrument"):
        if name in frame.columns and not frame[name].dropna().empty:
            return str(frame[name].dropna().iloc[0])
    return None


def source_timeframe(frame: pd.DataFrame) -> str | None:
    for name in ("timeframe", "interval", "tf"):
        if name in frame.columns and not frame[name].dropna().empty:
            return str(frame[name].dropna().iloc[0])
    return None


def build_all_segments(
    root: Path,
    runner: Any,
    market_entries: list[dict[str, Any]],
    minimum_rows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, pd.DataFrame], int]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    frame_cache: dict[str, pd.DataFrame] = {}
    skipped_preroll = 0
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
            if len(frame) < minimum_rows:
                raise ValueError(f"INSUFFICIENT_ROWS:{len(frame)}")
            frame_cache[repo_path] = frame
            symbol = source_symbol(frame)
            timeframe = source_timeframe(frame)
            for start in range(0, len(frame) - SEGMENT_BARS + 1, SEGMENT_BARS):
                stop = start + SEGMENT_BARS
                if start < PREROLL_BARS:
                    skipped_preroll += 1
                    continue
                sample = frame.iloc[start:stop]
                segment_id = digest_text(f"{repo_path}:{actual_sha}:{start}:{stop}")[:24]
                accepted.append({
                    "segment_id": segment_id,
                    "source_path": repo_path,
                    "source_sha256": actual_sha,
                    "start_row": start,
                    "end_row_exclusive": stop,
                    "bars": SEGMENT_BARS,
                    "start_timestamp": str(sample["__timestamp"].iloc[0]),
                    "end_timestamp": str(sample["__timestamp"].iloc[-1]),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "metrics": segment_metrics(sample),
                })
        except Exception as exc:
            rejected.append({"path": repo_path, "reason": f"{type(exc).__name__}:{exc}"})
    accepted.sort(key=lambda row: (row["source_path"], int(row["start_row"]), row["segment_id"]))
    return accepted, rejected, frame_cache, skipped_preroll


def overlaps_selected(row: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    for prior in selected:
        if str(prior.get("source_path") or "") != str(row.get("source_path") or ""):
            continue
        start = int(row.get("start_row", -1))
        stop = int(row.get("end_row_exclusive", -1))
        prior_start = int(prior.get("start_row", -1))
        prior_stop = int(prior.get("end_row_exclusive", -1))
        if max(start, prior_start) < min(stop, prior_stop):
            return True
    return False


def regime_match(row: dict[str, Any], regime: str, range_limit: float) -> bool:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    total_return = finite(metrics.get("return"))
    trend_score = finite(metrics.get("trend_score"))
    max_drawdown = finite(metrics.get("max_drawdown"))
    recovery = finite(metrics.get("recovery"))
    if regime == "trend_down":
        return total_return < 0
    if regime == "trend_up":
        return total_return > 0
    if regime == "shock_recovery":
        return max_drawdown < 0 and recovery > 0
    if regime == "range":
        return abs(trend_score) <= range_limit
    return False


def regime_sort_key(row: dict[str, Any], regime: str) -> tuple[Any, ...]:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    if regime == "trend_down":
        score = finite(metrics.get("trend_score"))
    elif regime == "trend_up":
        score = -finite(metrics.get("trend_score"))
    elif regime == "shock_recovery":
        score = -finite(metrics.get("shock_score"))
    else:
        score = abs(finite(metrics.get("trend_score")))
    return (score, str(row.get("source_path") or ""), int(row.get("start_row", -1)), str(row.get("segment_id") or ""))


def diverse_take(rows: list[dict[str, Any]], regime: str, limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, deque[dict[str, Any]]] = {}
    for source, items in sorted(defaultdict(list, {
        source: [row for row in rows if str(row.get("source_path") or "") == source]
        for source in sorted({str(row.get("source_path") or "") for row in rows})
    }).items()):
        grouped[source] = deque(sorted(items, key=lambda row: regime_sort_key(row, regime)))
    selected: list[dict[str, Any]] = []
    while grouped and len(selected) < limit:
        progressed = False
        for source in list(sorted(grouped)):
            queue = grouped[source]
            if queue:
                selected.append(queue.popleft())
                progressed = True
                if len(selected) == limit:
                    break
            if not queue:
                grouped.pop(source, None)
        if not progressed:
            break
    return selected


def select_signals(rows: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    grouped: dict[str, deque[dict[str, Any]]] = {}
    for segment_id in sorted({str(row.get("segment_id") or "") for row in rows}):
        items = sorted(
            [row for row in rows if str(row.get("segment_id") or "") == segment_id],
            key=lambda row: (int(row.get("bar_index", -1)), str(row.get("candidate_id") or "")),
        )[:MAX_SIGNALS_PER_SEGMENT]
        grouped[segment_id] = deque(items)
    selected: list[dict[str, Any]] = []
    while grouped and len(selected) < target:
        progressed = False
        for segment_id in list(sorted(grouped)):
            queue = grouped[segment_id]
            if queue:
                selected.append(queue.popleft())
                progressed = True
                if len(selected) == target:
                    break
            if not queue:
                grouped.pop(segment_id, None)
        if not progressed:
            break
    return selected


def bucket_specifications(plan: dict[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    expected = {
        "baseline_trend_down": ("trend_down",),
        "grid_rebalance_range": ("range",),
        "scalp_snap_trend_up": ("trend_up",),
        "vol_spike_fade_shock_recovery": ("shock_recovery",),
    }
    specs: dict[str, dict[str, str]] = {}
    blockers: list[str] = []
    candidates = [row for row in plan.get("stress_candidates", []) if isinstance(row, dict)]
    for bucket, regimes in expected.items():
        rows = [row for row in candidates if str(row.get("bucket") or "") == bucket]
        strategy_ids = sorted({str(row.get("strategy_id") or "") for row in rows})
        observed_regimes = sorted({str(row.get("regime") or "") for row in rows})
        if len(strategy_ids) != 1 or observed_regimes != sorted(regimes):
            blockers.append(f"BUCKET_SPEC_INVALID:{bucket}:{strategy_ids}:{observed_regimes}")
            continue
        specs[bucket] = {"strategy_id": strategy_ids[0], "regime": regimes[0]}
    return specs, blockers


def repair_queue(scan_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_bucket = {str(row.get("bucket") or ""): row for row in scan_rows}
    return [
        {
            "bucket": "baseline_trend_down",
            "actions": ["expanded_candidate_stress_6_axes", "require_unique_segments_ge_3", "require_independent_closed_trades_ge_12"],
            "candidate_count": int(by_bucket.get("baseline_trend_down", {}).get("selected_candidate_count", 0)),
        },
        {
            "bucket": "grid_rebalance_range",
            "actions": ["retain_quarantine", "deduplicate_same_segment_entries", "cooldown_counterfactual", "cost_edge_floor"],
            "candidate_count": int(by_bucket.get("grid_rebalance_range", {}).get("selected_candidate_count", 0)),
        },
        {
            "bucket": "scalp_snap_trend_up",
            "actions": ["separate_signal_disappearance_from_fill_window", "latency_sensitive_entry_window_repair"],
            "candidate_count": int(by_bucket.get("scalp_snap_trend_up", {}).get("selected_candidate_count", 0)),
        },
        {
            "bucket": "vol_spike_fade_shock_recovery",
            "actions": ["entry_context_filter", "shock_phase_binding", "cooldown_and_duplicate_suppression"],
            "candidate_count": int(by_bucket.get("vol_spike_fade_shock_recovery", {}).get("selected_candidate_count", 0)),
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--a4c-contract", required=True)
    parser.add_argument("--a4d-contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_market_expansion_trace_runner")
    a4c_contract = load_json(Path(args.a4c_contract).resolve())
    a4d_contract = load_json(Path(args.a4d_contract).resolve())

    stress = load_json(root / "runtime/r7a4d2_short_admission_candidate_stress_66/stress66_proof_v1.json")
    allowlist_plan = load_json(root / "runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json")
    short_plan = load_json(root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json")
    selected_manifest = load_json(root / str(a4d_contract["selected_manifest_path"]))
    frozen_manifest = load_json(root / str(a4c_contract["frozen_manifest_path"]))
    registry_path = root / str(a4d_contract["registry_path"])
    registry = load_json(registry_path)

    blockers: list[str] = []
    if stress.get("state") != "PASS_SHORT_ADMISSION_CANDIDATE_STRESS_66" or int(stress.get("blocker_count", -1)) != 0:
        blockers.append("STRESS66_NOT_PASS")
    if "baseline_trend_down" not in stress.get("under_sampled_robust_buckets", []):
        blockers.append("BASELINE_TREND_DOWN_NOT_ROBUST_UNDER_SAMPLED")
    if allowlist_plan.get("state") != "PASS_SHORT_ADMISSION_ALLOWLIST_PLAN":
        blockers.append("ALLOWLIST_PLAN_INVALID")
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_PLAN_INVALID")
    if selected_manifest.get("state") != "PASS":
        blockers.append("SELECTED_MARKET_MANIFEST_INVALID")
    if frozen_manifest.get("state") != "PASS":
        blockers.append("FROZEN_INPUT_MANIFEST_INVALID")

    specs, spec_blockers = bucket_specifications(allowlist_plan)
    blockers.extend(spec_blockers)
    category_inputs = frozen_manifest.get("category_inputs") if isinstance(frozen_manifest.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    if not market_entries:
        blockers.append("FROZEN_MARKET_ENTRY_ZERO")

    selected_segments = [row for row in selected_manifest.get("selected_segments", []) if isinstance(row, dict)]
    selected_ids = {str(row.get("segment_id") or "") for row in selected_segments}
    selected_range_scores = [
        abs(finite(row.get("metrics", {}).get("trend_score")))
        for row in selected_segments
        if row.get("regime") == "range" and isinstance(row.get("metrics"), dict)
    ]
    range_limit = max(selected_range_scores) if selected_range_scores else 0.25

    entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
    used_strategy_ids = sorted({spec["strategy_id"] for spec in specs.values()})
    target_ids = sorted(str(item) for item in short_plan.get("short_target_strategy_ids", []))
    if len(entries) != 25 or len(target_ids) != 12 or not set(used_strategy_ids).issubset(set(target_ids)):
        blockers.append(f"STRATEGY_SHAPE_INVALID:{len(entries)}:{len(target_ids)}:{used_strategy_ids}")

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
                module = runner.load_module(root, repo_path, strategy_id + "_market_expansion")
                bindings[strategy_id] = runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        sys.path.remove(str(root))

    all_segments: list[dict[str, Any]] = []
    rejected_market: list[dict[str, Any]] = []
    frame_cache: dict[str, pd.DataFrame] = {}
    skipped_preroll = 0
    if not blockers:
        all_segments, rejected_market, frame_cache, skipped_preroll = build_all_segments(
            root,
            runner,
            market_entries,
            max(int(a4c_contract.get("minimum_source_rows", 640)), SEGMENT_BARS + PREROLL_BARS),
        )
    unselected = [
        row for row in all_segments
        if str(row.get("segment_id") or "") not in selected_ids and not overlaps_selected(row, selected_segments)
    ]

    protected = [
        root / "runtime/r7a4d2_short_admission_candidate_stress_66/stress66_proof_v1.json",
        root / "runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json",
        root / str(a4d_contract["selected_manifest_path"]),
        root / str(a4c_contract["frozen_manifest_path"]),
    ]
    before = runner.snapshot(canonical_paths + protected)
    side_effect_attempts: list[str] = []
    failures: list[dict[str, Any]] = []
    scan_rows: list[dict[str, Any]] = []
    all_discovered: list[dict[str, Any]] = []

    discovery_contract = dict(a4d_contract)
    discovery_contract.update({
        "allowed_intents": ["hold", "block"],
        "indicator_preroll_bars": PREROLL_BARS,
        "short_execution_enabled": True,
        "short_target_strategy_ids": target_ids,
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
    })
    costs = {str(row.get("id") or ""): row for row in a4d_contract.get("cost_profiles", []) if isinstance(row, dict)}
    perturbations = {str(row.get("id") or ""): row for row in a4d_contract.get("perturbations", []) if isinstance(row, dict)}
    if "cost_profile_0" not in costs or "perturbation_0" not in perturbations:
        blockers.append("BASELINE_AXIS_MISSING")

    if not blockers:
        sys.path.insert(0, str(root))
        try:
            with runner.side_effect_guard(side_effect_attempts):
                bucket_progress = 0
                for bucket, spec in sorted(specs.items()):
                    strategy_id = spec["strategy_id"]
                    regime = spec["regime"]
                    eligible = [row for row in unselected if regime_match(row, regime, range_limit)]
                    scan_segments = diverse_take(eligible, regime, MAX_SCAN_SEGMENTS_PER_BUCKET)
                    discovered: list[dict[str, Any]] = []
                    owner, method_name = bindings[strategy_id]
                    for segment in scan_segments:
                        repo_path = str(segment["source_path"])
                        frame = frame_cache[repo_path]
                        sample = runner.select_segment_with_preroll(
                            frame,
                            int(segment["start_row"]),
                            int(segment["end_row_exclusive"]),
                            SEGMENT_BARS,
                            PREROLL_BARS,
                        )
                        scenario_id = digest_text(
                            f"market-expansion:{bucket}:{strategy_id}:{segment['segment_id']}:cost_profile_0:perturbation_0"
                        )[:24]
                        scenario = {
                            "scenario_id": scenario_id,
                            "strategy_id": strategy_id,
                            "segment_id": str(segment["segment_id"]),
                            "regime": regime,
                            "fold": -1,
                            "cost_profile": "cost_profile_0",
                            "perturbation": "perturbation_0",
                        }
                        try:
                            result = runner.simulate_scenario(
                                scenario,
                                sample,
                                owner,
                                method_name,
                                costs["cost_profile_0"],
                                perturbations["perturbation_0"],
                                discovery_contract,
                            )
                            if int(result.get("short_closed_trade_count") or 0) != 0:
                                raise ValueError("TRACE_ONLY_SHORT_TRADE_DETECTED")
                            trace = [row for row in result.get("short_candidate_trace", []) if isinstance(row, dict)]
                            for row in trace:
                                if (
                                    row.get("strategy_id") == strategy_id
                                    and row.get("regime") == regime
                                    and row.get("legacy_action") == "enter"
                                    and row.get("candidate_state") == "FLAT_ENTER"
                                ):
                                    candidate_id = ":".join((scenario_id, strategy_id, str(int(row.get("bar_index", -1)))))
                                    discovered.append({
                                        "candidate_id": candidate_id,
                                        "bucket": bucket,
                                        "strategy_id": strategy_id,
                                        "regime": regime,
                                        "scenario_id": scenario_id,
                                        "segment_id": str(segment["segment_id"]),
                                        "source_path": repo_path,
                                        "source_sha256": str(segment["source_sha256"]),
                                        "symbol": segment.get("symbol"),
                                        "timeframe": segment.get("timeframe"),
                                        "start_row": int(segment["start_row"]),
                                        "end_row_exclusive": int(segment["end_row_exclusive"]),
                                        "start_timestamp": str(segment["start_timestamp"]),
                                        "end_timestamp": str(segment["end_timestamp"]),
                                        "segment_metrics": segment["metrics"],
                                        "bar_index": int(row.get("bar_index", -1)),
                                        "evaluation_index": int(row.get("evaluation_index", -1)),
                                        "legacy_reason": str(row.get("legacy_reason") or ""),
                                        "target_qty": finite(row.get("target_qty")),
                                        "discovery_only": True,
                                    })
                        except Exception as exc:
                            failures.append({
                                "bucket": bucket,
                                "strategy_id": strategy_id,
                                "segment_id": segment.get("segment_id"),
                                "error": f"{type(exc).__name__}:{exc}",
                            })
                        bucket_progress += 1
                        if bucket_progress % 16 == 0:
                            print(f"A4D2_SEGMENT_EXPANSION_PROGRESS={bucket_progress} FAILED={len(failures)}")
                    unique_discovered = list({row["candidate_id"]: row for row in discovered}.values())
                    target = 24 if bucket == "grid_rebalance_range" else 12
                    selected = select_signals(unique_discovered, target)
                    unique_segment_count = len({row["segment_id"] for row in selected})
                    unique_source_count = len({row["source_path"] for row in selected})
                    scan_rows.append({
                        "bucket": bucket,
                        "strategy_id": strategy_id,
                        "regime": regime,
                        "eligible_unselected_segment_count": len(eligible),
                        "scanned_segment_count": len(scan_segments),
                        "discovered_flat_enter_count": len(unique_discovered),
                        "selected_candidate_count": len(selected),
                        "selected_unique_segment_count": unique_segment_count,
                        "selected_unique_source_count": unique_source_count,
                        "selected_candidates": selected,
                    })
                    all_discovered.extend(unique_discovered)
        except Exception as exc:
            blockers.append(f"MARKET_EXPANSION_SCAN_FAILED:{type(exc).__name__}:{exc}")
        finally:
            sys.path.remove(str(root))

    after = runner.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if failures:
        blockers.append(f"EXPANSION_REPLAY_FAILURE:{len(failures)}")
    if mutation_paths:
        blockers.append("CANONICAL_OR_PROOF_MUTATION_DETECTED")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPT:{len(side_effect_attempts)}")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")

    by_bucket = {str(row.get("bucket") or ""): row for row in scan_rows}
    baseline = by_bucket.get("baseline_trend_down", {})
    baseline_ready = (
        int(baseline.get("selected_candidate_count", 0)) >= 12
        and int(baseline.get("selected_unique_segment_count", 0)) >= 3
    )
    coverage_flags: list[str] = []
    if not baseline_ready:
        coverage_flags.append("BASELINE_TREND_DOWN_EXPANSION_INSUFFICIENT")
    for bucket in ("scalp_snap_trend_up", "vol_spike_fade_shock_recovery"):
        row = by_bucket.get(bucket, {})
        if int(row.get("selected_candidate_count", 0)) < 12 or int(row.get("selected_unique_segment_count", 0)) < 3:
            coverage_flags.append(f"{bucket.upper()}_REPAIR_SAMPLE_INSUFFICIENT")

    blockers = list(dict.fromkeys(blockers))
    state = "PASS_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES" if not blockers else "HOLD_MARKET_SEGMENT_EXPANSION_INPUT"
    if blockers:
        next_stage = "R7.A4D2_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES"
    elif baseline_ready:
        next_stage = "R7.A4D2_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN"
    else:
        next_stage = "R7.A4D2_MARKET_SOURCE_COVERAGE_EXPANSION"

    evidence = {
        "schema": "r7a4d2_market_segment_expansion_for_short_candidates_v1",
        "official_stage": "R7.A4D2_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "coverage_flags": coverage_flags,
        "market_source_count": len(market_entries),
        "rejected_market_source_count": len(rejected_market),
        "rejected_market_sources": rejected_market,
        "all_preroll_eligible_segment_count": len(all_segments),
        "selected_segment_count": len(selected_segments),
        "unselected_disjoint_segment_count": len(unselected),
        "skipped_insufficient_preroll_segment_count": skipped_preroll,
        "range_trend_score_limit": range_limit,
        "max_scan_segments_per_bucket": MAX_SCAN_SEGMENTS_PER_BUCKET,
        "max_signals_per_segment": MAX_SIGNALS_PER_SEGMENT,
        "source_registry_parity": source_registry_parity,
        "mutation_path_count": len(mutation_paths),
        "side_effect_attempt_count": len(side_effect_attempts),
        "baseline_expansion_ready": baseline_ready,
        "bucket_expansion_results": scan_rows,
        "discovered_candidate_count": len(all_discovered),
        "repair_queue": repair_queue(scan_rows),
        "production_admission_expansion_allowed": False,
        "grid_rebalance_quarantined": True,
        "full_3600_reexecution_allowed": False,
        "event_replay_2880_allowed": False,
        "failures": failures[:20],
        "next_stage": next_stage,
    }
    output_dir = root / "runtime/r7a4d2_market_segment_expansion_for_short_candidates"
    runner.atomic_json(output_dir / "market_segment_expansion_v1.json", evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("MARKET_SOURCE_COUNT=" + str(len(market_entries)))
    print("REJECTED_MARKET_SOURCE_COUNT=" + str(len(rejected_market)))
    print("ALL_PREROLL_ELIGIBLE_SEGMENT_COUNT=" + str(len(all_segments)))
    print("SELECTED_SEGMENT_COUNT=" + str(len(selected_segments)))
    print("UNSELECTED_DISJOINT_SEGMENT_COUNT=" + str(len(unselected)))
    print("BASELINE_EXPANSION_READY=" + str(baseline_ready).lower())
    print("BUCKET_EXPANSION_RESULTS=" + json.dumps(scan_rows, ensure_ascii=False, sort_keys=True))
    print("COVERAGE_FLAGS=" + json.dumps(coverage_flags, ensure_ascii=False))
    print("REPAIR_QUEUE=" + json.dumps(evidence["repair_queue"], ensure_ascii=False, sort_keys=True))
    print("SOURCE_REGISTRY_PARITY=" + str(source_registry_parity).lower())
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false")
    print("GRID_REBALANCE_QUARANTINED=true")
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output_dir / "market_segment_expansion_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
