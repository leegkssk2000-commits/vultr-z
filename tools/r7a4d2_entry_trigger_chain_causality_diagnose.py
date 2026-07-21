#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

TARGET_IDS = (
    "break_and_continue",
    "rbreaker_like",
    "squeeze_break",
    "trend_ma_macd",
    "vwap_revert",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


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


def is_long_enter(fields: dict[str, Any], signal: dict[str, Any]) -> bool:
    return (
        bool(fields.get("ok"))
        and str(fields.get("intent") or "").lower() == "enter_long"
        and str(signal.get("side") or "").lower() == "long"
        and str(signal.get("action") or "").lower() == "enter"
    )


def is_long_add(fields: dict[str, Any], signal: dict[str, Any]) -> bool:
    return (
        bool(fields.get("ok"))
        and str(fields.get("intent") or "").lower() == "enter_long"
        and str(signal.get("side") or "").lower() == "long"
        and str(signal.get("action") or "").lower() == "add"
    )


def missing_entry_predicates(strategy_id: str, indicators: dict[str, Any]) -> list[str]:
    def flag(name: str) -> bool:
        return bool(indicators.get(name))

    if strategy_id == "break_and_continue":
        required = ("up_break", "tight_box", "long_breakout_now", "long_reclaim", "trend_long")
        return [name for name in required if not flag(name)]
    if strategy_id == "rbreaker_like":
        if flag("long_break") or flag("long_reversal"):
            return []
        return ["long_break_or_long_reversal"]
    if strategy_id == "squeeze_break":
        required = ("released", "long_break", "trend_long")
        return [name for name in required if not flag(name)]
    if strategy_id == "trend_ma_macd":
        required = ("trend_long", "hist_cross_up")
        return [name for name in required if not flag(name)]
    if strategy_id == "vwap_revert":
        missing: list[str] = []
        if not flag("long_extension"):
            missing.append("long_extension")
        if not (flag("long_reclaim") or flag("long_beam")):
            missing.append("long_reclaim_or_long_beam")
        return missing
    return ["UNKNOWN_STRATEGY_PREDICATE_MODEL"]


def classify_report(report: dict[str, Any]) -> str:
    if int(report.get("strategy_error_count") or 0) > 0:
        return "DIAGNOSTIC_CALL_ERROR"
    selected_enters = int(report.get("selected_flat_enter_count") or 0)
    pre_enters = int(report.get("presegment_flat_enter_count") or 0)
    baseline_trades = int(report.get("baseline_trade_count") or 0)
    extended_trades = int(report.get("extended_trade_count") or 0)
    add_count = int(report.get("selected_synthetic_add_count") or 0)
    strategy_id = str(report.get("strategy_id") or "")

    if selected_enters > 0 and baseline_trades == 0:
        return "SIMULATION_ENTRY_EXECUTION_GAP"
    if pre_enters > 0 and selected_enters == 0 and extended_trades > 0:
        return "PRESEGMENT_ENTRY_CHAIN_DEPENDENCY"
    if pre_enters > 0 and selected_enters == 0 and extended_trades == 0:
        return "PRESEGMENT_SIGNAL_NOT_EXECUTABLE"
    if add_count <= 0:
        return "NO_ADD_CHAIN_REPRODUCED"
    if strategy_id == "break_and_continue":
        return "ENTRY_FILTER_STRICTER_THAN_ADD"
    if strategy_id in {"rbreaker_like", "squeeze_break", "trend_ma_macd"}:
        return "ONE_SHOT_EVENT_TO_ADD_CHAIN_GAP"
    if strategy_id == "vwap_revert":
        return "SYNTHETIC_POSITION_ADD_ARTIFACT"
    return "UNCLASSIFIED_ENTRY_CHAIN_CAUSE"


def synthetic_position(label: str, close: float) -> dict[str, Any]:
    if label == "flat":
        return {
            "side": "",
            "qty": 0.0,
            "avg_entry": 0.0,
            "add_count": 0,
            "last_add_price": 0.0,
        }
    return {
        "side": "long",
        "qty": 0.50,
        "avg_entry": close * 0.99,
        "add_count": 0,
        "last_add_price": close * 0.99,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner), "r7a4d2_entry_chain_runner")
    contract = load_json(Path(args.contract))

    registry_path = root / str(contract["registry_path"])
    manifest_path = root / str(contract["selected_manifest_path"])
    geometry_path = root / "runtime/r7a4d2_targeted_trigger_geometry_diagnose/targeted_diagnose_v1.json"
    chain_path = root / "runtime/r7a4d2_entry_to_add_chain_diagnose/entry_to_add_chain_v1.json"

    blockers: list[str] = []
    side_effect_attempts: list[str] = []
    try:
        registry = load_json(registry_path)
        manifest = load_json(manifest_path)
        geometry = load_json(geometry_path)
        prior_chain = load_json(chain_path)
    except Exception as exc:
        registry = {}
        manifest = {}
        geometry = {}
        prior_chain = {}
        blockers.append(f"INPUT_LOAD_FAILED:{type(exc).__name__}:{exc}")

    if int(geometry.get("invalid_geometry_count", -1)) != 0:
        blockers.append("PRIOR_GEOMETRY_NOT_CLOSED")
    prior_hist = prior_chain.get("classification_histogram")
    if not isinstance(prior_hist, dict) or int(
        prior_hist.get("STANDALONE_CAPABLE_ROLE_UNDECLARED_CHAIN_UNREACHABLE", 0)
    ) != 5:
        blockers.append("PRIOR_ENTRY_TO_ADD_CHAIN_EVIDENCE_INVALID")

    entries = {
        str(row.get("strategy_id") or ""): row
        for row in registry.get("entries", [])
        if isinstance(row, dict) and row.get("strategy_id")
    }
    for strategy_id in TARGET_IDS:
        row = entries.get(strategy_id)
        if not isinstance(row, dict):
            blockers.append(f"REGISTRY_ENTRY_MISSING:{strategy_id}")
            continue
        if str(row.get("strategy_role") or "").lower() != "standalone":
            blockers.append(f"ROLE_AUTHORITY_NOT_CLOSED:{strategy_id}")
        if str(row.get("execution_scope") or "") != "independent_entry_add_reduce_exit":
            blockers.append(f"EXECUTION_SCOPE_NOT_CLOSED:{strategy_id}")

    segments = [
        row for row in manifest.get("selected_segments", []) if isinstance(row, dict)
    ]
    if len(segments) != 24:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")

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

    minimum = int(contract.get("minimum_call_bars") or 100)
    segment_bars = int(contract.get("segment_bars") or 320)
    pre_roll_target = max(segment_bars, minimum * 2)

    reports: list[dict[str, Any]] = []
    sys.path.insert(0, str(root))
    try:
        with runner.side_effect_guard(side_effect_attempts):
            for strategy_index, strategy_id in enumerate(TARGET_IDS, start=1):
                counters: Counter[str] = Counter()
                missing_hist: Counter[str] = Counter()
                add_reason_hist: Counter[str] = Counter()
                sample_rows: list[dict[str, Any]] = []
                entry = entries.get(strategy_id, {})
                engine = entry.get("canonical_engine") if isinstance(entry, dict) else {}
                if not isinstance(engine, dict):
                    engine = {}
                try:
                    implementation_path = runner.safe_repo_path(
                        str(engine.get("implementation_path") or "")
                    )
                    source_path = root / implementation_path
                    expected_sha = str(engine.get("source_sha256") or "")
                    if expected_sha and runner.sha256_file(source_path) != expected_sha:
                        raise ValueError("STRATEGY_SOURCE_SHA_MISMATCH")
                    module = runner.load_module(
                        root, implementation_path, f"r7a4d2_entry_chain_{strategy_id}"
                    )
                    owner, method_name = runner.resolve_callable(
                        module, str(engine.get("callable") or "")
                    )
                    instance = owner()
                except Exception as exc:
                    reports.append(
                        {
                            "strategy_id": strategy_id,
                            "strategy_error_count": 1,
                            "error": f"{type(exc).__name__}:{exc}",
                            "classification": "SOURCE_OR_BIND_ERROR",
                        }
                    )
                    continue

                for segment in segments:
                    try:
                        source_path = root / runner.safe_repo_path(str(segment["source_path"]))
                        if runner.sha256_file(source_path) != str(segment.get("source_sha256") or ""):
                            raise ValueError("MARKET_SOURCE_SHA_MISMATCH")
                        full_frame = runner.load_market_frame(source_path)
                        selected_start = int(segment["start_row"])
                        selected_stop = int(segment["end_row_exclusive"])
                        extended_start = max(0, selected_start - pre_roll_target)
                        selected = full_frame.iloc[selected_start:selected_stop].copy().reset_index(drop=True)
                        extended = full_frame.iloc[extended_start:selected_stop].copy().reset_index(drop=True)
                        if len(selected) != segment_bars:
                            raise ValueError(f"SELECTED_BAR_COUNT:{len(selected)}")

                        scenario = {
                            "scenario_id": f"entry-chain:{strategy_id}:{segment.get('segment_id')}",
                            "strategy_id": strategy_id,
                            "segment_id": str(segment.get("segment_id") or ""),
                            "regime": str(segment.get("regime") or "unknown"),
                            "fold": 0,
                            "cost_profile": "cost_profile_0",
                            "perturbation": "perturbation_0",
                        }
                        baseline = runner.simulate_scenario(
                            scenario, selected, owner, method_name, cost, perturbation, contract
                        )
                        extended_result = runner.simulate_scenario(
                            scenario, extended, owner, method_name, cost, perturbation, contract
                        )
                        counters["baseline_trade_count"] += int(baseline.get("trade_count") or 0)
                        counters["extended_trade_count"] += int(extended_result.get("trade_count") or 0)
                        counters["extended_enter_signal_count"] += int(
                            extended_result.get("enter_signal_count") or 0
                        )

                        public_columns = [
                            column for column in extended.columns if not str(column).startswith("__")
                        ]
                        records = extended[public_columns].to_dict(orient="records")
                        selected_offset = selected_start - extended_start
                        for bar_index in range(minimum - 1, len(extended)):
                            sample_records = records[: bar_index + 1]
                            close = float(extended.iloc[bar_index]["close"])
                            flat_ctx = runner.build_context(
                                strategy_id,
                                sample_records,
                                synthetic_position("flat", close),
                                str(segment.get("regime") or "unknown"),
                                cost,
                            )
                            flat_fields = runner.decision_fields(
                                getattr(instance, method_name)(flat_ctx)
                            )
                            flat_signal = runner.legacy_signal(flat_fields)
                            if is_long_enter(flat_fields, flat_signal):
                                if bar_index < selected_offset:
                                    counters["presegment_flat_enter_count"] += 1
                                else:
                                    counters["selected_flat_enter_count"] += 1

                            if bar_index < selected_offset:
                                continue
                            long_ctx = runner.build_context(
                                strategy_id,
                                sample_records,
                                synthetic_position("long", close),
                                str(segment.get("regime") or "unknown"),
                                cost,
                            )
                            long_fields = runner.decision_fields(
                                getattr(instance, method_name)(long_ctx)
                            )
                            long_signal = runner.legacy_signal(long_fields)
                            if not is_long_add(long_fields, long_signal):
                                continue
                            counters["selected_synthetic_add_count"] += 1
                            reason = str(long_signal.get("why") or long_fields.get("reason") or "unknown")
                            add_reason_hist[reason] += 1
                            indicators = (
                                flat_signal.get("indicators")
                                if isinstance(flat_signal.get("indicators"), dict)
                                else {}
                            )
                            missing = missing_entry_predicates(strategy_id, indicators)
                            if not missing:
                                missing_hist["NONE"] += 1
                            else:
                                for name in missing:
                                    missing_hist[name] += 1
                            if len(sample_rows) < 20:
                                sample_rows.append(
                                    {
                                        "segment_id": segment.get("segment_id"),
                                        "regime": segment.get("regime"),
                                        "source_row": extended_start + bar_index,
                                        "bar_index_in_selected": bar_index - selected_offset,
                                        "add_reason": reason,
                                        "flat_reason": flat_signal.get("why")
                                        or flat_fields.get("reason"),
                                        "missing_entry_predicates": missing,
                                    }
                                )
                    except Exception as exc:
                        counters["strategy_error_count"] += 1
                        if len(sample_rows) < 20:
                            sample_rows.append(
                                {
                                    "segment_id": segment.get("segment_id"),
                                    "error": f"{type(exc).__name__}:{exc}",
                                }
                            )

                report = {
                    "strategy_id": strategy_id,
                    "strategy_error_count": int(counters["strategy_error_count"]),
                    "baseline_trade_count": int(counters["baseline_trade_count"]),
                    "extended_trade_count": int(counters["extended_trade_count"]),
                    "extended_enter_signal_count": int(counters["extended_enter_signal_count"]),
                    "presegment_flat_enter_count": int(counters["presegment_flat_enter_count"]),
                    "selected_flat_enter_count": int(counters["selected_flat_enter_count"]),
                    "selected_synthetic_add_count": int(counters["selected_synthetic_add_count"]),
                    "missing_entry_predicate_histogram": dict(missing_hist.most_common()),
                    "add_reason_histogram": dict(add_reason_hist.most_common()),
                    "sample": sample_rows,
                }
                report["classification"] = classify_report(report)
                reports.append(report)
                print(
                    f"A4D2_ENTRY_CHAIN_PROGRESS={strategy_index}/5 "
                    f"STRATEGY={strategy_id} CLASS={report['classification']} "
                    f"BASE_TRADES={report['baseline_trade_count']} "
                    f"EXT_TRADES={report['extended_trade_count']} "
                    f"PRE_ENTER={report['presegment_flat_enter_count']} "
                    f"SELECTED_ENTER={report['selected_flat_enter_count']} "
                    f"SYNTH_ADD={report['selected_synthetic_add_count']}",
                    flush=True,
                )
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    classification_hist = Counter(
        str(row.get("classification") or "UNKNOWN") for row in reports
    )
    diagnostic_errors = sum(int(row.get("strategy_error_count") or 0) for row in reports)
    unknown_count = sum(
        str(row.get("classification") or "")
        in {
            "UNCLASSIFIED_ENTRY_CHAIN_CAUSE",
            "NO_ADD_CHAIN_REPRODUCED",
            "DIAGNOSTIC_CALL_ERROR",
            "SOURCE_OR_BIND_ERROR",
        }
        for row in reports
    )

    if blockers:
        state = "HOLD_INPUT_INVALID"
        next_stage = "R7.A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_DIAGNOSE"
    elif side_effect_attempts or diagnostic_errors or unknown_count:
        state = "HOLD_ENTRY_TRIGGER_CAUSALITY_UNRESOLVED"
        next_stage = "R7.A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_DIAGNOSE"
    else:
        state = "HOLD_ENTRY_TRIGGER_REDESIGN_REQUIRED"
        next_stage = "R7.A4D2_STRATEGY_SPECIFIC_ENTRY_CHAIN_PLAN"

    evidence = {
        "schema": "r7a4d2_entry_trigger_chain_causality_v1",
        "official_stage": "R7.A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_DIAGNOSE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "target_strategy_count": len(TARGET_IDS),
        "segment_count": len(segments),
        "pre_roll_target_bars": pre_roll_target,
        "classification_histogram": dict(sorted(classification_hist.items())),
        "strategy_reports": reports,
        "side_effect_attempts": side_effect_attempts,
        "next_stage": next_stage,
    }
    output_path = root / (
        "runtime/r7a4d2_entry_trigger_chain_causality/entry_trigger_chain_causality_v1.json"
    )
    atomic_json(output_path, evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("TARGET_STRATEGY_COUNT=5")
    print("SEGMENT_COUNT=" + str(len(segments)))
    print("PRE_ROLL_TARGET_BARS=" + str(pre_roll_target))
    print(
        "BASELINE_TRADE_COUNT="
        + str(sum(int(row.get("baseline_trade_count") or 0) for row in reports))
    )
    print(
        "EXTENDED_TRADE_COUNT="
        + str(sum(int(row.get("extended_trade_count") or 0) for row in reports))
    )
    print(
        "PRESEGMENT_FLAT_ENTER_COUNT="
        + str(sum(int(row.get("presegment_flat_enter_count") or 0) for row in reports))
    )
    print(
        "SELECTED_FLAT_ENTER_COUNT="
        + str(sum(int(row.get("selected_flat_enter_count") or 0) for row in reports))
    )
    print(
        "SELECTED_SYNTHETIC_ADD_COUNT="
        + str(sum(int(row.get("selected_synthetic_add_count") or 0) for row in reports))
    )
    print("CLASSIFICATION_HISTOGRAM=" + json.dumps(evidence["classification_histogram"], ensure_ascii=False))
    print("STRATEGY_CAUSALITY=" + json.dumps(reports, ensure_ascii=False, sort_keys=True))
    print("SIDE_EFFECT_ATTEMPTS=" + json.dumps(side_effect_attempts, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output_path))
    print("NEXT_STAGE=" + next_stage)
    print("R7A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_COMPLETE")
    print("RC=2")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
