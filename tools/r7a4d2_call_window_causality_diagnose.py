#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"JSONL_EMPTY_LINE:{line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{line_number}")
            rows.append(value)
    return rows


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_position(label: str, close: float) -> dict[str, Any]:
    if label == "flat":
        return {
            "side": "",
            "qty": 0.0,
            "avg_entry": 0.0,
            "add_count": 0,
            "last_add_price": 0.0,
        }
    if label == "long":
        return {
            "side": "long",
            "qty": 0.50,
            "avg_entry": close * 0.99,
            "add_count": 0,
            "last_add_price": close * 0.99,
        }
    return {
        "side": "short",
        "qty": 0.40,
        "avg_entry": close * 1.01,
        "add_count": 0,
        "last_add_price": close * 1.01,
    }


def classify_causality(metrics: dict[str, int]) -> str:
    if metrics.get("adapter_error_count", 0) or metrics.get("targeted_replay_error_count", 0):
        return "CALLER_ERROR"
    if metrics.get("targeted_replay_trade_count", 0) > 0:
        return "CURRENT_SOURCE_TARGETED_REPLAY_TRADES_PRESENT"
    if metrics.get("flat_executable_long_enter_count", 0) > 0:
        if metrics.get("targeted_replay_enter_signal_count", 0) > 0 and metrics.get(
            "targeted_replay_invalid_signal_count", 0
        ) > 0:
            return "EXECUTABLE_ENTRY_REJECTED_AT_FILL_GEOMETRY"
        if metrics.get("targeted_replay_enter_signal_count", 0) == 0:
            return "EXECUTABLE_ENTRY_SUPPRESSED_BY_DYNAMIC_CONTEXT"
        return "EXECUTABLE_ENTRY_NO_CLOSED_TRADE"
    if metrics.get("flat_terminal_long_enter_count", 0) > 0:
        return "TERMINAL_BAR_ONLY_NON_EXECUTABLE_ENTRY"
    if metrics.get("long_state_add_count", 0) > 0:
        return "ORPHAN_ADD_ONLY_WITHOUT_FLAT_ENTRY"
    if metrics.get("flat_executable_short_enter_count", 0) > 0:
        return "SHORT_ENTRY_SCOPE_ONLY"
    return "NO_EXECUTABLE_ENTRY_TRIGGER"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner), "r7a4d2_call_window_runner")
    contract = load_json(Path(args.contract))

    manifest_path = root / str(contract["selected_manifest_path"])
    registry_path = root / str(contract["registry_path"])
    results_path = root / str(contract["scenario_results_path"])
    prior_diag_path = (
        root
        / "runtime/r7a4d2_targeted_trigger_geometry_diagnose/targeted_diagnose_v1.json"
    )

    blockers: list[str] = []
    side_effect_attempts: list[str] = []
    try:
        manifest = load_json(manifest_path)
        registry = load_json(registry_path)
        result_rows = load_jsonl(results_path)
        prior_diag = load_json(prior_diag_path)
    except Exception as exc:
        manifest = {}
        registry = {}
        result_rows = []
        prior_diag = {}
        blockers.append(f"INPUT_LOAD_FAILED:{type(exc).__name__}:{exc}")

    if str(prior_diag.get("state") or "") != "HOLD_A4D_CALL_WINDOW_GAP":
        blockers.append(f"PRIOR_STATE_INVALID:{prior_diag.get('state')}")
    if int(prior_diag.get("invalid_geometry_count") or -1) != 0:
        blockers.append("PRIOR_GEOMETRY_NOT_CLOSED")
    if len(result_rows) != 3600:
        blockers.append(f"A4D_RESULT_ROW_COUNT_INVALID:{len(result_rows)}")

    target_ids = sorted(
        str(row.get("strategy_id") or "")
        for row in prior_diag.get("strategy_reports", [])
        if isinstance(row, dict)
        and str(row.get("classification") or "")
        == "A4D_ZERO_WITH_FULL_SCAN_LONG_TRIGGER"
        and row.get("strategy_id")
    )
    if len(target_ids) != 5:
        blockers.append(f"TARGET_STRATEGY_COUNT_INVALID:{len(target_ids)}")

    entries = {
        str(row.get("strategy_id") or ""): row
        for row in registry.get("entries", [])
        if isinstance(row, dict) and row.get("strategy_id")
    }
    segments = [
        row
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict)
    ]
    if len(segments) != 24:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")

    original_trade_by_strategy: Counter[str] = Counter()
    for row in result_rows:
        original_trade_by_strategy[str(row.get("strategy_id") or "")] += int(
            row.get("trade_count") or 0
        )

    cost_profiles = {
        str(row.get("id") or ""): row
        for row in contract.get("cost_profiles", [])
        if isinstance(row, dict) and row.get("id")
    }
    perturbations = {
        str(row.get("id") or ""): row
        for row in contract.get("perturbations", [])
        if isinstance(row, dict) and row.get("id")
    }
    cost = cost_profiles.get("cost_profile_0")
    perturbation = perturbations.get("perturbation_0")
    if not isinstance(cost, dict) or not isinstance(perturbation, dict):
        blockers.append("BASELINE_COST_OR_PERTURBATION_MISSING")
        cost = {}
        perturbation = {}

    segment_frames: list[tuple[dict[str, Any], Any]] = []
    for segment in segments:
        try:
            source_path = root / runner.safe_repo_path(str(segment["source_path"]))
            if runner.sha256_file(source_path) != segment.get("source_sha256"):
                raise ValueError("SOURCE_SHA_MISMATCH")
            frame = runner.load_market_frame(source_path)
            sample = frame.iloc[
                int(segment["start_row"]): int(segment["end_row_exclusive"])
            ].copy().reset_index(drop=True)
            if len(sample) != int(contract["segment_bars"]):
                raise ValueError(f"BAR_COUNT:{len(sample)}")
            segment_frames.append((segment, sample))
        except Exception as exc:
            blockers.append(
                f"SEGMENT_LOAD_FAILED:{segment.get('segment_id')}:{type(exc).__name__}:{exc}"
            )

    reports: list[dict[str, Any]] = []
    sys.path.insert(0, str(root))
    try:
        with runner.side_effect_guard(side_effect_attempts):
            for strategy_index, strategy_id in enumerate(target_ids, start=1):
                counters: Counter[str] = Counter()
                signal_samples: list[dict[str, Any]] = []
                replay_samples: list[dict[str, Any]] = []
                entry = entries.get(strategy_id, {})
                engine = (
                    entry.get("canonical_engine")
                    if isinstance(entry.get("canonical_engine"), dict)
                    else {}
                )
                try:
                    implementation_path = runner.safe_repo_path(
                        str(engine.get("implementation_path") or "")
                    )
                    source_path = root / implementation_path
                    expected_sha = str(engine.get("source_sha256") or "")
                    if expected_sha and runner.sha256_file(source_path) != expected_sha:
                        raise ValueError("STRATEGY_SOURCE_SHA_MISMATCH")
                    module = runner.load_module(
                        root, implementation_path, f"r7a4d2_window_{strategy_id}"
                    )
                    owner, method_name = runner.resolve_callable(
                        module, str(engine.get("callable") or "")
                    )
                except Exception as exc:
                    counters["adapter_error_count"] += 1
                    reports.append(
                        {
                            "strategy_id": strategy_id,
                            "classification": "CALLER_ERROR",
                            "error": f"BIND:{type(exc).__name__}:{exc}",
                        }
                    )
                    continue

                for segment, frame in segment_frames:
                    public_columns = [
                        column
                        for column in frame.columns
                        if not str(column).startswith("__")
                    ]
                    row_records = frame[public_columns].to_dict(orient="records")
                    minimum_call_bars = int(contract["minimum_call_bars"])
                    instance = owner()

                    for bar_index in range(minimum_call_bars - 1, len(frame)):
                        sample_records = row_records[: bar_index + 1]
                        close = float(frame.iloc[bar_index]["close"])
                        for state_label in ("flat", "long", "short"):
                            position = synthetic_position(state_label, close)
                            try:
                                ctx = runner.build_context(
                                    strategy_id,
                                    sample_records,
                                    position,
                                    str(segment.get("regime") or "unknown"),
                                    cost,
                                )
                                decision = getattr(instance, method_name)(ctx)
                                fields = runner.decision_fields(decision)
                                legacy = runner.legacy_signal(fields)
                                side = str(legacy.get("side") or "").lower()
                                action = str(legacy.get("action") or "hold").lower()
                                intent = str(fields.get("intent") or "hold")
                                ok = bool(fields.get("ok"))
                                terminal = bar_index == len(frame) - 1

                                if state_label == "flat" and side == "long" and action == "enter":
                                    if ok and intent == "enter_long":
                                        key = (
                                            "flat_terminal_long_enter_count"
                                            if terminal
                                            else "flat_executable_long_enter_count"
                                        )
                                        counters[key] += 1
                                        if len(signal_samples) < 30:
                                            signal_samples.append(
                                                {
                                                    "segment_id": segment.get("segment_id"),
                                                    "regime": segment.get("regime"),
                                                    "bar_index": bar_index,
                                                    "terminal": terminal,
                                                    "state": state_label,
                                                    "side": side,
                                                    "action": action,
                                                    "intent": intent,
                                                    "entry": legacy.get("entry"),
                                                    "sl": legacy.get("sl"),
                                                    "tp": legacy.get("tp"),
                                                    "why": legacy.get("why"),
                                                }
                                            )
                                if state_label == "long" and side == "long" and action == "add":
                                    counters["long_state_add_count"] += 1
                                if state_label == "flat" and side == "short" and action == "enter":
                                    if terminal:
                                        counters["flat_terminal_short_enter_count"] += 1
                                    else:
                                        counters["flat_executable_short_enter_count"] += 1
                                if state_label == "short" and side == "short" and action == "add":
                                    counters["short_state_add_count"] += 1
                            except Exception as exc:
                                counters["adapter_error_count"] += 1
                                if len(signal_samples) < 30:
                                    signal_samples.append(
                                        {
                                            "segment_id": segment.get("segment_id"),
                                            "bar_index": bar_index,
                                            "state": state_label,
                                            "error": f"{type(exc).__name__}:{exc}",
                                        }
                                    )

                    try:
                        scenario = {
                            "scenario_id": f"r7a4d2.window.{strategy_id}.{segment.get('segment_id')}",
                            "strategy_id": strategy_id,
                            "segment_id": str(segment.get("segment_id") or ""),
                            "regime": str(segment.get("regime") or "unknown"),
                            "fold": int(segment.get("fold") or 0),
                            "cost_profile": "cost_profile_0",
                            "perturbation": "perturbation_0",
                        }
                        replay = runner.simulate_scenario(
                            scenario,
                            frame,
                            owner,
                            method_name,
                            cost,
                            perturbation,
                            contract,
                        )
                        counters["targeted_replay_scenario_count"] += 1
                        counters["targeted_replay_trade_count"] += int(
                            replay.get("trade_count") or 0
                        )
                        counters["targeted_replay_enter_signal_count"] += int(
                            replay.get("enter_signal_count") or 0
                        )
                        counters["targeted_replay_invalid_signal_count"] += int(
                            replay.get("invalid_signal_count") or 0
                        )
                        counters["targeted_replay_short_shadow_count"] += int(
                            replay.get("short_shadow_signal_count") or 0
                        )
                        if (
                            int(replay.get("trade_count") or 0) > 0
                            or int(replay.get("enter_signal_count") or 0) > 0
                            or int(replay.get("invalid_signal_count") or 0) > 0
                        ) and len(replay_samples) < 20:
                            replay_samples.append(
                                {
                                    "segment_id": segment.get("segment_id"),
                                    "regime": segment.get("regime"),
                                    "trade_count": replay.get("trade_count"),
                                    "enter_signal_count": replay.get("enter_signal_count"),
                                    "invalid_signal_count": replay.get("invalid_signal_count"),
                                    "short_shadow_signal_count": replay.get(
                                        "short_shadow_signal_count"
                                    ),
                                    "intent_histogram": replay.get("intent_histogram"),
                                }
                            )
                    except Exception as exc:
                        counters["targeted_replay_error_count"] += 1
                        if len(replay_samples) < 20:
                            replay_samples.append(
                                {
                                    "segment_id": segment.get("segment_id"),
                                    "error": f"{type(exc).__name__}:{exc}",
                                }
                            )

                metrics = {
                    key: int(counters[key])
                    for key in (
                        "adapter_error_count",
                        "flat_executable_long_enter_count",
                        "flat_terminal_long_enter_count",
                        "long_state_add_count",
                        "flat_executable_short_enter_count",
                        "flat_terminal_short_enter_count",
                        "short_state_add_count",
                        "targeted_replay_scenario_count",
                        "targeted_replay_trade_count",
                        "targeted_replay_enter_signal_count",
                        "targeted_replay_invalid_signal_count",
                        "targeted_replay_short_shadow_count",
                        "targeted_replay_error_count",
                    )
                }
                classification = classify_causality(metrics)
                report = {
                    "strategy_id": strategy_id,
                    "implementation_path": implementation_path,
                    "original_a4d_trade_count": int(
                        original_trade_by_strategy.get(strategy_id, 0)
                    ),
                    "classification": classification,
                    **metrics,
                    "signal_sample": signal_samples,
                    "targeted_replay_sample": replay_samples,
                }
                reports.append(report)
                print(
                    f"A4D2_WINDOW_PROGRESS={strategy_index}/{len(target_ids)} "
                    f"STRATEGY={strategy_id} CLASS={classification} "
                    f"FLAT_EXEC={metrics['flat_executable_long_enter_count']} "
                    f"TERMINAL={metrics['flat_terminal_long_enter_count']} "
                    f"ADD_ONLY={metrics['long_state_add_count']} "
                    f"REPLAY_TRADES={metrics['targeted_replay_trade_count']}",
                    flush=True,
                )
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    histogram = Counter(
        str(row.get("classification") or "UNKNOWN") for row in reports
    )
    total_flat_executable = sum(
        int(row.get("flat_executable_long_enter_count") or 0) for row in reports
    )
    total_terminal = sum(
        int(row.get("flat_terminal_long_enter_count") or 0) for row in reports
    )
    total_add_only = sum(int(row.get("long_state_add_count") or 0) for row in reports)
    total_replay_trades = sum(
        int(row.get("targeted_replay_trade_count") or 0) for row in reports
    )
    total_errors = sum(
        int(row.get("adapter_error_count") or 0)
        + int(row.get("targeted_replay_error_count") or 0)
        for row in reports
    )

    if blockers:
        state = "HOLD_INPUT_INVALID"
        next_stage = "R7.A4D2_CALL_WINDOW_CAUSALITY_DIAGNOSE"
    elif side_effect_attempts or total_errors:
        state = "HOLD_CALL_WINDOW_DIAG_ERROR"
        next_stage = "R7.A4D2_CALL_WINDOW_CAUSALITY_DIAGNOSE"
    elif total_replay_trades > 0:
        state = "HOLD_CURRENT_SOURCE_REPLAY_DELTA"
        next_stage = "R7.A4D2_AFFECTED_SCENARIO_REPLAY_PLAN"
    elif total_flat_executable > 0:
        state = "HOLD_TRUE_A4D_DYNAMIC_EXECUTION_GAP"
        next_stage = "R7.A4D2_DYNAMIC_EXECUTION_CLOSURE"
    elif total_terminal > 0:
        state = "HOLD_TERMINAL_SIGNAL_WINDOW_GAP"
        next_stage = "R7.A4D2_EVALUATION_EXECUTION_WINDOW_SPLIT"
    elif total_add_only > 0:
        state = "HOLD_ORPHAN_ADD_TRIGGER_CHAIN_GAP"
        next_stage = "R7.A4D2_ENTRY_TO_ADD_CHAIN_DIAGNOSE"
    else:
        state = "HOLD_NO_EXECUTABLE_ENTRY_TRIGGER"
        next_stage = "R7.A4D2_MARKET_TRIGGER_COVERAGE_REDESIGN"

    evidence = {
        "schema": "r7a4d2_call_window_causality_diagnose_v1",
        "official_stage": "R7.A4D2_CALL_WINDOW_CAUSALITY_DIAGNOSE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "target_strategy_count": len(target_ids),
        "target_strategy_ids": target_ids,
        "segment_count": len(segment_frames),
        "targeted_replay_scenario_count": sum(
            int(row.get("targeted_replay_scenario_count") or 0) for row in reports
        ),
        "flat_executable_long_enter_count": total_flat_executable,
        "flat_terminal_long_enter_count": total_terminal,
        "long_state_add_count": total_add_only,
        "targeted_replay_trade_count": total_replay_trades,
        "classification_histogram": dict(sorted(histogram.items())),
        "strategy_reports": reports,
        "side_effect_attempts": side_effect_attempts,
        "next_stage": next_stage,
    }
    output_path = (
        root
        / "runtime/r7a4d2_call_window_causality_diagnose/call_window_causality_v1.json"
    )
    atomic_json(output_path, evidence)

    for key in (
        "state",
        "blocker_count",
        "target_strategy_count",
        "segment_count",
        "targeted_replay_scenario_count",
        "flat_executable_long_enter_count",
        "flat_terminal_long_enter_count",
        "long_state_add_count",
        "targeted_replay_trade_count",
        "next_stage",
    ):
        print(f"{key.upper()}={evidence[key]}")
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print(
        "CLASSIFICATION_HISTOGRAM="
        + json.dumps(evidence["classification_histogram"], ensure_ascii=False, sort_keys=True)
    )
    print(
        "STRATEGY_CAUSALITY="
        + json.dumps(
            [
                {
                    "strategy_id": row.get("strategy_id"),
                    "classification": row.get("classification"),
                    "flat_exec": row.get("flat_executable_long_enter_count"),
                    "terminal": row.get("flat_terminal_long_enter_count"),
                    "add_only": row.get("long_state_add_count"),
                    "replay_trades": row.get("targeted_replay_trade_count"),
                    "replay_enter": row.get("targeted_replay_enter_signal_count"),
                    "replay_invalid": row.get("targeted_replay_invalid_signal_count"),
                }
                for row in reports
            ],
            ensure_ascii=False,
        )
    )
    print("SIDE_EFFECT_ATTEMPTS=" + json.dumps(side_effect_attempts, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output_path))
    print("RC=" + ("0" if state.startswith("PASS") else "2"))
    return 0 if state.startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
