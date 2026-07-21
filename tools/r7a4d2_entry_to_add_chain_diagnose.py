#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
import tempfile
from collections import Counter
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
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"JSONL_EMPTY_LINE:{number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{number}")
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


def prior_call_window_acceptable(
    call_window: dict[str, Any], geometry: dict[str, Any]
) -> bool:
    if int(geometry.get("invalid_geometry_count", -1)) != 0:
        return False
    if int(call_window.get("target_strategy_count", -1)) != 5:
        return False
    if int(call_window.get("flat_executable_long_enter_count", -1)) != 0:
        return False
    if int(call_window.get("flat_terminal_long_enter_count", -1)) != 0:
        return False
    if int(call_window.get("long_state_add_count", -1)) <= 0:
        return False
    if int(call_window.get("targeted_replay_trade_count", -1)) != 0:
        return False
    histogram = call_window.get("classification_histogram")
    if not isinstance(histogram, dict) or int(
        histogram.get("ORPHAN_ADD_ONLY_WITHOUT_FLAT_ENTRY", 0)
    ) != 5:
        return False
    blockers = call_window.get("blockers")
    if not isinstance(blockers, list):
        return False
    allowed_false_blocker = blockers == ["PRIOR_GEOMETRY_NOT_CLOSED"]
    clean_state = not blockers and str(call_window.get("state") or "") == (
        "HOLD_ORPHAN_ADD_TRIGGER_CHAIN_GAP"
    )
    return allowed_false_blocker or clean_state


def action_literals(source: str) -> Counter[str]:
    values: Counter[str] = Counter()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "action":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value, str
            ):
                values[str(keyword.value.value).strip().lower()] += 1
    return values


def role_metadata(entry: dict[str, Any]) -> tuple[bool, str]:
    candidates = (
        entry.get("strategy_role"),
        entry.get("execution_role"),
        entry.get("composition_role"),
        entry.get("role"),
    )
    for value in candidates:
        text = str(value or "").strip().lower()
        if text:
            return True, text
    engine = entry.get("canonical_engine")
    if isinstance(engine, dict):
        for key in ("strategy_role", "execution_role", "composition_role", "role"):
            text = str(engine.get(key) or "").strip().lower()
            if text:
                return True, text
    return False, ""


def classify_chain(
    *, enter_literal_count: int, add_literal_count: int, role_present: bool
) -> str:
    if add_literal_count <= 0:
        return "SOURCE_ADD_BRANCH_NOT_PROVEN"
    if enter_literal_count <= 0:
        return (
            "STRUCTURAL_ADD_OVERLAY_ROLE_DECLARED"
            if role_present
            else "STRUCTURAL_ADD_OVERLAY_ROLE_UNDECLARED"
        )
    return (
        "STANDALONE_CAPABLE_SELECTED_MARKET_CHAIN_UNREACHABLE"
        if role_present
        else "STANDALONE_CAPABLE_ROLE_UNDECLARED_CHAIN_UNREACHABLE"
    )


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
    runner = load_module(Path(args.runner), "r7a4d2_chain_runner")
    contract = load_json(Path(args.contract))

    registry_path = root / str(contract["registry_path"])
    manifest_path = root / str(contract["selected_manifest_path"])
    results_path = root / str(contract["scenario_results_path"])
    geometry_path = (
        root
        / "runtime/r7a4d2_targeted_trigger_geometry_diagnose/targeted_diagnose_v1.json"
    )
    call_window_path = (
        root
        / "runtime/r7a4d2_call_window_causality_diagnose/call_window_causality_v1.json"
    )

    blockers: list[str] = []
    side_effect_attempts: list[str] = []
    try:
        registry = load_json(registry_path)
        manifest = load_json(manifest_path)
        result_rows = load_jsonl(results_path)
        geometry = load_json(geometry_path)
        call_window = load_json(call_window_path)
    except Exception as exc:
        registry = {}
        manifest = {}
        result_rows = []
        geometry = {}
        call_window = {}
        blockers.append(f"INPUT_LOAD_FAILED:{type(exc).__name__}:{exc}")

    if not prior_call_window_acceptable(call_window, geometry):
        blockers.append("PRIOR_CALL_WINDOW_EVIDENCE_INVALID")
    if len(result_rows) != 3600:
        blockers.append(f"A4D_RESULT_ROW_COUNT_INVALID:{len(result_rows)}")

    target_ids = sorted(
        str(row.get("strategy_id") or "")
        for row in call_window.get("strategy_reports", [])
        if isinstance(row, dict)
        and str(row.get("classification") or "")
        == "ORPHAN_ADD_ONLY_WITHOUT_FLAT_ENTRY"
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

    cost_profiles = {
        str(row.get("id") or ""): row
        for row in contract.get("cost_profiles", [])
        if isinstance(row, dict) and row.get("id")
    }
    cost = cost_profiles.get("cost_profile_0")
    if not isinstance(cost, dict):
        blockers.append("BASELINE_COST_PROFILE_MISSING")
        cost = {}

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
            for index, strategy_id in enumerate(target_ids, start=1):
                counters: Counter[str] = Counter()
                flat_reason_hist: Counter[str] = Counter()
                paired_samples: list[dict[str, Any]] = []
                entry = entries.get(strategy_id, {})
                engine = (
                    entry.get("canonical_engine")
                    if isinstance(entry.get("canonical_engine"), dict)
                    else {}
                )
                implementation_path = ""
                source_action_hist: Counter[str] = Counter()
                role_present, declared_role = role_metadata(entry)
                try:
                    implementation_path = runner.safe_repo_path(
                        str(engine.get("implementation_path") or "")
                    )
                    source_path = root / implementation_path
                    expected_sha = str(engine.get("source_sha256") or "")
                    if expected_sha and runner.sha256_file(source_path) != expected_sha:
                        raise ValueError("STRATEGY_SOURCE_SHA_MISMATCH")
                    source_action_hist = action_literals(
                        source_path.read_text(encoding="utf-8")
                    )
                    module = runner.load_module(
                        root, implementation_path, f"r7a4d2_chain_{strategy_id}"
                    )
                    owner, method_name = runner.resolve_callable(
                        module, str(engine.get("callable") or "")
                    )
                except Exception as exc:
                    counters["strategy_error_count"] += 1
                    reports.append(
                        {
                            "strategy_id": strategy_id,
                            "classification": "SOURCE_OR_BIND_ERROR",
                            "error": f"{type(exc).__name__}:{exc}",
                        }
                    )
                    continue

                instance = owner()
                for segment, frame in segment_frames:
                    public_columns = [
                        column
                        for column in frame.columns
                        if not str(column).startswith("__")
                    ]
                    records = frame[public_columns].to_dict(orient="records")
                    minimum = int(contract["minimum_call_bars"])
                    for bar_index in range(minimum - 1, len(frame)):
                        sample_records = records[: bar_index + 1]
                        close = float(frame.iloc[bar_index]["close"])
                        try:
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
                            if not (
                                bool(long_fields.get("ok"))
                                and str(long_fields.get("intent") or "") == "enter_long"
                                and str(long_signal.get("side") or "").lower() == "long"
                                and str(long_signal.get("action") or "").lower() == "add"
                            ):
                                continue
                            counters["paired_long_add_count"] += 1

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
                            flat_action = str(flat_signal.get("action") or "hold").lower()
                            flat_reason = str(
                                flat_signal.get("why")
                                or flat_fields.get("reason")
                                or "unknown"
                            )
                            flat_reason_hist[flat_reason] += 1
                            counters[f"paired_flat_action_{flat_action}"] += 1
                            if len(paired_samples) < 25:
                                paired_samples.append(
                                    {
                                        "segment_id": segment.get("segment_id"),
                                        "regime": segment.get("regime"),
                                        "bar_index": bar_index,
                                        "long_add_why": long_signal.get("why"),
                                        "long_add_entry": long_signal.get("entry"),
                                        "long_add_sl": long_signal.get("sl"),
                                        "long_add_tp": long_signal.get("tp"),
                                        "flat_action": flat_action,
                                        "flat_why": flat_reason,
                                        "flat_side": flat_signal.get("side"),
                                    }
                                )
                        except Exception as exc:
                            counters["strategy_error_count"] += 1
                            if len(paired_samples) < 25:
                                paired_samples.append(
                                    {
                                        "segment_id": segment.get("segment_id"),
                                        "bar_index": bar_index,
                                        "error": f"{type(exc).__name__}:{exc}",
                                    }
                                )

                enter_count = int(source_action_hist.get("enter", 0))
                add_count = int(source_action_hist.get("add", 0))
                classification = classify_chain(
                    enter_literal_count=enter_count,
                    add_literal_count=add_count,
                    role_present=role_present,
                )
                report = {
                    "strategy_id": strategy_id,
                    "implementation_path": implementation_path,
                    "classification": classification,
                    "registry_role_metadata_present": role_present,
                    "declared_role": declared_role,
                    "source_enter_branch_count": enter_count,
                    "source_add_branch_count": add_count,
                    "paired_long_add_count": int(counters["paired_long_add_count"]),
                    "paired_flat_enter_count": int(
                        counters["paired_flat_action_enter"]
                    ),
                    "paired_flat_hold_count": int(
                        counters["paired_flat_action_hold"]
                    ),
                    "strategy_error_count": int(counters["strategy_error_count"]),
                    "flat_reason_histogram": dict(flat_reason_hist.most_common(12)),
                    "paired_sample": paired_samples,
                }
                reports.append(report)
                print(
                    f"A4D2_CHAIN_PROGRESS={index}/{len(target_ids)} "
                    f"STRATEGY={strategy_id} CLASS={classification} "
                    f"ENTER_BRANCH={enter_count} ADD_BRANCH={add_count} "
                    f"PAIRED_ADD={report['paired_long_add_count']} "
                    f"PAIRED_FLAT_ENTER={report['paired_flat_enter_count']} "
                    f"ROLE_META={str(role_present).lower()}",
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
    role_missing_count = sum(
        not bool(row.get("registry_role_metadata_present")) for row in reports
    )
    source_enter_capable_count = sum(
        int(row.get("source_enter_branch_count") or 0) > 0 for row in reports
    )
    structural_overlay_count = sum(
        str(row.get("classification") or "").startswith("STRUCTURAL_ADD_OVERLAY")
        for row in reports
    )
    unreachable_chain_count = sum(
        "CHAIN_UNREACHABLE" in str(row.get("classification") or "")
        for row in reports
    )
    paired_add_count = sum(
        int(row.get("paired_long_add_count") or 0) for row in reports
    )
    paired_flat_enter_count = sum(
        int(row.get("paired_flat_enter_count") or 0) for row in reports
    )
    error_count = sum(int(row.get("strategy_error_count") or 0) for row in reports)

    if blockers:
        state = "HOLD_INPUT_INVALID"
        next_stage = "R7.A4D2_ENTRY_TO_ADD_CHAIN_DIAGNOSE"
    elif side_effect_attempts or error_count:
        state = "HOLD_ENTRY_TO_ADD_DIAG_ERROR"
        next_stage = "R7.A4D2_ENTRY_TO_ADD_CHAIN_DIAGNOSE"
    elif role_missing_count:
        state = "HOLD_STRATEGY_ROLE_AUTHORITY_MISSING"
        next_stage = "R7.A4D2_STRATEGY_ROLE_AUTHORITY_CLOSURE"
    elif unreachable_chain_count:
        state = "HOLD_ENTRY_TO_ADD_CHAIN_UNREACHABLE"
        next_stage = "R7.A4D2_ENTRY_TRIGGER_CHAIN_REDESIGN"
    elif structural_overlay_count:
        state = "HOLD_ADD_OVERLAY_EXECUTION_SCOPE_GAP"
        next_stage = "R7.A4D2_OVERLAY_EXECUTION_HARNESS"
    else:
        state = "PASS_ENTRY_TO_ADD_CHAIN_AUTHORITY"
        next_stage = "R7.A4D2_SHORT_EXECUTION_HARNESS"

    evidence = {
        "schema": "r7a4d2_entry_to_add_chain_diagnose_v1",
        "official_stage": "R7.A4D2_ENTRY_TO_ADD_CHAIN_DIAGNOSE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "target_strategy_count": len(target_ids),
        "target_strategy_ids": target_ids,
        "segment_count": len(segment_frames),
        "registry_role_metadata_missing_count": role_missing_count,
        "source_enter_capable_strategy_count": source_enter_capable_count,
        "structural_add_overlay_strategy_count": structural_overlay_count,
        "unreachable_entry_to_add_chain_strategy_count": unreachable_chain_count,
        "paired_long_add_count": paired_add_count,
        "paired_flat_enter_count": paired_flat_enter_count,
        "classification_histogram": dict(sorted(histogram.items())),
        "strategy_reports": reports,
        "side_effect_attempts": side_effect_attempts,
        "next_stage": next_stage,
    }
    output_path = (
        root
        / "runtime/r7a4d2_entry_to_add_chain_diagnose/entry_to_add_chain_v1.json"
    )
    atomic_json(output_path, evidence)

    for key in (
        "state",
        "blocker_count",
        "target_strategy_count",
        "segment_count",
        "registry_role_metadata_missing_count",
        "source_enter_capable_strategy_count",
        "structural_add_overlay_strategy_count",
        "unreachable_entry_to_add_chain_strategy_count",
        "paired_long_add_count",
        "paired_flat_enter_count",
        "next_stage",
    ):
        print(f"{key.upper()}={evidence[key]}")
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print(
        "CLASSIFICATION_HISTOGRAM="
        + json.dumps(evidence["classification_histogram"], ensure_ascii=False, sort_keys=True)
    )
    print(
        "STRATEGY_CHAIN_SUMMARY="
        + json.dumps(
            [
                {
                    "strategy_id": row.get("strategy_id"),
                    "classification": row.get("classification"),
                    "role_meta": row.get("registry_role_metadata_present"),
                    "declared_role": row.get("declared_role"),
                    "enter_branch": row.get("source_enter_branch_count"),
                    "add_branch": row.get("source_add_branch_count"),
                    "paired_add": row.get("paired_long_add_count"),
                    "paired_flat_enter": row.get("paired_flat_enter_count"),
                    "top_flat_reasons": list(
                        (row.get("flat_reason_histogram") or {}).items()
                    )[:5],
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
