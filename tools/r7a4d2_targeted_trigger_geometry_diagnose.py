#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import math
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

ACTIVE_ACTIONS = {"enter", "add", "reduce", "exit", "close"}
ENTRY_ACTIONS = {"enter", "add"}
LONG_EXPECTED_INTENT = {
    "enter": "enter_long",
    "add": "enter_long",
    "reduce": "reduce",
    "exit": "exit_long",
    "close": "exit_long",
}


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_results(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"RESULT_EMPTY_LINE:{number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"RESULT_ROW_NOT_OBJECT:{number}")
            rows.append(value)
    return rows


def make_state(label: str, close: float) -> dict[str, Any]:
    if label == "flat":
        return {
            "position_side": "",
            "position_qty": 0.0,
            "avg_entry": 0.0,
            "add_count": 0,
            "last_add_price": 0.0,
        }
    if label == "long":
        return {
            "position_side": "long",
            "position_qty": 0.50,
            "avg_entry": close * 0.99,
            "add_count": 0,
            "last_add_price": close * 0.99,
        }
    return {
        "position_side": "short",
        "position_qty": 0.40,
        "avg_entry": close * 1.01,
        "add_count": 0,
        "last_add_price": close * 1.01,
    }


def normalized_signal(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, Any] = {}
    for key in ("side", "action", "why", "skill"):
        output[key] = str(value.get(key) or "").strip().lower()
    for key in ("size", "entry", "sl", "tp", "confidence"):
        try:
            number = float(value.get(key) or 0.0)
            output[key] = round(number, 10) if math.isfinite(number) else None
        except Exception:
            output[key] = None
    return output


def signal_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return normalized_signal(left) == normalized_signal(right)


def call_direct_strategy(
    module: Any, frame: pd.DataFrame, state: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    function = getattr(module, "strategy", None)
    if not callable(function):
        return None, "DIRECT_STRATEGY_CALLABLE_MISSING"
    signature = inspect.signature(function)
    parameters = list(signature.parameters.values())
    if not parameters:
        return None, "DIRECT_STRATEGY_SIGNATURE_EMPTY"
    kwargs: dict[str, Any] = {}
    if "state" in signature.parameters:
        kwargs["state"] = state
    if "risk_action" in signature.parameters:
        kwargs["risk_action"] = "hold"
    required_unknown = [
        parameter.name
        for parameter in parameters[1:]
        if parameter.default is inspect.Signature.empty
        and parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
        and parameter.name not in kwargs
    ]
    if required_unknown:
        return None, "DIRECT_STRATEGY_REQUIRED_ARGS:" + ",".join(required_unknown)
    try:
        result = function(frame.copy(), **kwargs)
    except Exception as exc:
        return None, f"DIRECT_STRATEGY_ERROR:{type(exc).__name__}:{exc}"
    if not isinstance(result, dict):
        return None, f"DIRECT_STRATEGY_NON_DICT:{type(result).__name__}"
    return result, None


def valid_geometry(signal: dict[str, Any]) -> bool:
    side = str(signal.get("side") or "").lower()
    action = str(signal.get("action") or "").lower()
    if side not in {"long", "short"} or action not in ENTRY_ACTIONS:
        return True
    try:
        size = float(signal.get("size") or 0.0)
        entry = float(signal.get("entry") or 0.0)
        stop = float(signal.get("sl") or 0.0)
        target = float(signal.get("tp") or 0.0)
    except Exception:
        return False
    if not all(math.isfinite(value) for value in (size, entry, stop, target)):
        return False
    if size <= 0 or entry <= 0:
        return False
    if side == "long":
        return stop < entry < target
    return target < entry < stop


def compact_indicators(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, Any] = {}
    for key in sorted(value)[:40]:
        item = value[key]
        if isinstance(item, bool):
            output[str(key)] = item
        elif isinstance(item, (int, float)) and math.isfinite(float(item)):
            output[str(key)] = round(float(item), 8)
        elif isinstance(item, str):
            output[str(key)] = item[:120]
    return output


def classify_strategy(metrics: dict[str, int], a4d_trade_count: int) -> str:
    if metrics.get("adapter_errors", 0) or metrics.get("direct_errors", 0):
        return "CALL_ERROR"
    if metrics.get("direct_payload_mismatches", 0) or metrics.get("long_mapping_mismatches", 0):
        return "ADAPTER_DIRECT_OR_LONG_MAPPING_MISMATCH"
    if metrics.get("invalid_geometry", 0):
        return "PAYLOAD_GEOMETRY_FAIL"
    long_count = metrics.get("long_active", 0)
    short_count = metrics.get("short_active", 0)
    if long_count > 0 and a4d_trade_count == 0:
        return "A4D_ZERO_WITH_FULL_SCAN_LONG_TRIGGER"
    if long_count > 0 and short_count > 0:
        return "FULL_SCAN_BOTH_SIDES_TRIGGER"
    if long_count > 0:
        return "FULL_SCAN_LONG_TRIGGER"
    if short_count > 0:
        return "FULL_SCAN_SHORT_ONLY_TRIGGER"
    return "FULL_SCAN_NO_ACTIVE_TRIGGER"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--a4d-runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.a4d_runner), "r7a4d2_runner")
    contract = load_json(Path(args.contract))

    registry_path = root / str(contract["registry_path"])
    manifest_path = root / str(contract["selected_manifest_path"])
    results_path = root / str(contract["scenario_results_path"])
    status_path = root / str(contract["status_path"])
    proof_path = root / str(contract["proof_path"])
    semantic_path = root / "runtime/r7a4d_semantic_parity_audit/semantic_parity_audit_v1.json"

    blockers: list[str] = []
    try:
        registry = load_json(registry_path)
        manifest = load_json(manifest_path)
        status = load_json(status_path)
        proof = load_json(proof_path)
        semantic = load_json(semantic_path)
        result_rows = load_results(results_path)
    except Exception as exc:
        registry = {}
        manifest = {}
        status = {}
        proof = {}
        semantic = {}
        result_rows = []
        blockers.append(f"INPUT_LOAD_FAILED:{type(exc).__name__}:{exc}")

    result_sha = sha256_file(results_path) if results_path.is_file() else ""
    if len(result_rows) != 3600 or sum(row.get("completed") is True for row in result_rows) != 3600:
        blockers.append("A4D_RESULT_ARTIFACT_INVALID")
    if any(str(source.get("scenario_results_sha256") or "") != result_sha for source in (status, proof)):
        blockers.append("A4D_RESULT_HASH_MISMATCH")
    if str(semantic.get("state") or "") != "HOLD_SEMANTIC_PARITY_GAP":
        blockers.append(f"SEMANTIC_PRIOR_STATE_INVALID:{semantic.get('state')}")

    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    semantic_reports = [row for row in semantic.get("strategy_reports", []) if isinstance(row, dict)]
    target_ids = sorted(
        str(row.get("strategy_id") or "")
        for row in semantic_reports
        if str(row.get("classification") or "")
        in {"SEMANTIC_PARITY_FAIL", "NO_LONG_TRIGGER_SELECTED_FOLDS"}
        and row.get("strategy_id")
    )
    if len(entries) != 25:
        blockers.append(f"REGISTRY_ENTRY_COUNT_INVALID:{len(entries)}")
    if len(segments) != 24:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")
    if not target_ids:
        blockers.append("TARGET_STRATEGY_SET_EMPTY")

    trade_by_strategy: Counter[str] = Counter()
    for row in result_rows:
        trade_by_strategy[str(row.get("strategy_id") or "")] += int(row.get("trade_count") or 0)

    segment_frames: list[tuple[str, str, pd.DataFrame]] = []
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
            segment_frames.append(
                (str(segment["segment_id"]), str(segment.get("regime") or "unknown"), sample)
            )
        except Exception as exc:
            blockers.append(
                f"SEGMENT_LOAD_FAILED:{segment.get('segment_id')}:{type(exc).__name__}:{exc}"
            )

    cost_profiles = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]
    cost_profile = cost_profiles[0] if cost_profiles else {
        "fee_bps_per_side": 0.0,
        "slippage_bps_per_side": 0.0,
        "latency_bars": 0,
        "funding_bps_per_8h": 0.0,
    }
    entry_by_id = {
        str(row.get("strategy_id") or ""): row
        for row in entries
        if row.get("strategy_id")
    }

    reports: list[dict[str, Any]] = []
    total_calls = 0
    side_effect_attempts: list[str] = []
    global_geometry_samples: list[dict[str, Any]] = []

    sys.path.insert(0, str(root))
    try:
        with runner.side_effect_guard(side_effect_attempts):
            for strategy_index, strategy_id in enumerate(target_ids, start=1):
                entry = entry_by_id.get(strategy_id, {})
                engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
                implementation_path = runner.safe_repo_path(str(engine.get("implementation_path") or ""))
                source_path = root / implementation_path
                expected_sha = str(engine.get("source_sha256") or "")
                if expected_sha and runner.sha256_file(source_path) != expected_sha:
                    blockers.append(f"STRATEGY_SOURCE_SHA_MISMATCH:{strategy_id}")
                    continue
                module = runner.load_module(root, implementation_path, f"r7a4d2_{strategy_id}")
                owner, method_name = runner.resolve_callable(module, str(engine.get("callable") or ""))
                instance = owner()

                counters: Counter[str] = Counter()
                action_hist: Counter[str] = Counter()
                reason_hist: Counter[str] = Counter()
                regime_active_hist: dict[str, Counter[str]] = defaultdict(Counter)
                state_active_hist: dict[str, Counter[str]] = defaultdict(Counter)
                error_samples: list[str] = []
                mismatch_samples: list[dict[str, Any]] = []
                geometry_samples: list[dict[str, Any]] = []

                for segment_id, regime, frame in segment_frames:
                    start = max(int(contract.get("minimum_call_bars", 32)), 2)
                    for end_exclusive in range(start, len(frame)):
                        sample = frame.iloc[: end_exclusive + 1].copy().reset_index(drop=True)
                        public_columns = [
                            column for column in sample.columns if not str(column).startswith("__")
                        ]
                        row_records = sample[public_columns].to_dict(orient="records")
                        close = float(sample.iloc[-1]["close"])
                        for state_label in ("flat", "long", "short"):
                            state = make_state(state_label, close)
                            position = {
                                "side": state["position_side"],
                                "qty": state["position_qty"],
                                "avg_entry": state["avg_entry"],
                                "add_count": state["add_count"],
                                "last_add_price": state["last_add_price"],
                            }
                            try:
                                ctx = runner.build_context(
                                    strategy_id, row_records, position, regime, cost_profile
                                )
                                decision = getattr(instance, method_name)(ctx)
                                fields = runner.decision_fields(decision)
                                legacy = runner.legacy_signal(fields)
                                counters["adapter_calls"] += 1
                                total_calls += 1

                                side = str(legacy.get("side") or "").lower()
                                action = str(legacy.get("action") or "hold").lower()
                                intent = str(fields.get("intent") or "hold")
                                reason = str(legacy.get("why") or fields.get("reason") or "unknown")
                                action_hist[f"{side or 'none'}:{action}"] += 1
                                reason_hist[reason] += 1

                                if side in {"long", "short"} and action in ACTIVE_ACTIONS:
                                    counters[f"{side}_active"] += 1
                                    regime_active_hist[regime][side] += 1
                                    state_active_hist[state_label][f"{side}:{action}"] += 1
                                if side == "short" and action in ACTIVE_ACTIONS and intent == "hold":
                                    counters["short_downgrades"] += 1
                                if side == "long" and action in LONG_EXPECTED_INTENT and intent != LONG_EXPECTED_INTENT[action]:
                                    counters["long_mapping_mismatches"] += 1
                                    if len(mismatch_samples) < 10:
                                        mismatch_samples.append({
                                            "segment_id": segment_id,
                                            "bar_end_exclusive": end_exclusive + 1,
                                            "state": state_label,
                                            "kind": "LONG_MAPPING",
                                            "legacy": normalized_signal(legacy),
                                            "intent": intent,
                                        })
                                if not valid_geometry(legacy):
                                    counters["invalid_geometry"] += 1
                                    item = {
                                        "strategy_id": strategy_id,
                                        "segment_id": segment_id,
                                        "regime": regime,
                                        "bar_end_exclusive": end_exclusive + 1,
                                        "state": state_label,
                                        "intent": intent,
                                        "signal": normalized_signal(legacy),
                                        "indicators": compact_indicators(legacy.get("indicators")),
                                    }
                                    if len(geometry_samples) < 20:
                                        geometry_samples.append(item)
                                    if len(global_geometry_samples) < 50:
                                        global_geometry_samples.append(item)

                                direct, direct_error = call_direct_strategy(
                                    module, sample[public_columns].copy(), state
                                )
                                if direct_error:
                                    counters["direct_errors"] += 1
                                    if len(error_samples) < 10:
                                        error_samples.append(
                                            f"{segment_id}:{end_exclusive + 1}:{state_label}:{direct_error}"
                                        )
                                elif not signal_equal(direct or {}, legacy):
                                    counters["direct_payload_mismatches"] += 1
                                    if len(mismatch_samples) < 10:
                                        mismatch_samples.append({
                                            "segment_id": segment_id,
                                            "bar_end_exclusive": end_exclusive + 1,
                                            "state": state_label,
                                            "kind": "DIRECT_VS_PAYLOAD",
                                            "direct": normalized_signal(direct or {}),
                                            "legacy": normalized_signal(legacy),
                                        })
                            except Exception as exc:
                                counters["adapter_errors"] += 1
                                if len(error_samples) < 10:
                                    error_samples.append(
                                        f"{segment_id}:{end_exclusive + 1}:{state_label}:ADAPTER:{type(exc).__name__}:{exc}"
                                    )

                a4d_trades = int(trade_by_strategy.get(strategy_id, 0))
                metrics = {
                    "adapter_errors": counters["adapter_errors"],
                    "direct_errors": counters["direct_errors"],
                    "direct_payload_mismatches": counters["direct_payload_mismatches"],
                    "long_mapping_mismatches": counters["long_mapping_mismatches"],
                    "invalid_geometry": counters["invalid_geometry"],
                    "long_active": counters["long_active"],
                    "short_active": counters["short_active"],
                }
                classification = classify_strategy(metrics, a4d_trades)
                reports.append({
                    "strategy_id": strategy_id,
                    "implementation_path": implementation_path,
                    "classification": classification,
                    "a4d_trade_count": a4d_trades,
                    "adapter_call_count": counters["adapter_calls"],
                    "adapter_error_count": counters["adapter_errors"],
                    "direct_error_count": counters["direct_errors"],
                    "direct_payload_mismatch_count": counters["direct_payload_mismatches"],
                    "long_mapping_mismatch_count": counters["long_mapping_mismatches"],
                    "invalid_geometry_count": counters["invalid_geometry"],
                    "long_active_signal_count": counters["long_active"],
                    "short_active_signal_count": counters["short_active"],
                    "short_downgrade_count": counters["short_downgrades"],
                    "action_histogram": dict(sorted(action_hist.items())),
                    "top_hold_reasons": reason_hist.most_common(12),
                    "regime_active_histogram": {
                        key: dict(sorted(value.items()))
                        for key, value in sorted(regime_active_hist.items())
                    },
                    "state_active_histogram": {
                        key: dict(sorted(value.items()))
                        for key, value in sorted(state_active_hist.items())
                    },
                    "geometry_failure_sample": geometry_samples,
                    "error_sample": error_samples,
                    "mismatch_sample": mismatch_samples,
                })
                print(
                    f"A4D2_PROGRESS={strategy_index}/{len(target_ids)} "
                    f"STRATEGY={strategy_id} CLASS={classification} "
                    f"LONG={counters['long_active']} SHORT={counters['short_active']} "
                    f"GEOMETRY={counters['invalid_geometry']}",
                    flush=True,
                )
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    class_histogram = Counter(row["classification"] for row in reports)
    invalid_geometry_count = sum(int(row["invalid_geometry_count"]) for row in reports)
    adapter_error_count = sum(int(row["adapter_error_count"]) for row in reports)
    direct_error_count = sum(int(row["direct_error_count"]) for row in reports)
    direct_mismatch_count = sum(int(row["direct_payload_mismatch_count"]) for row in reports)
    long_mapping_mismatch_count = sum(int(row["long_mapping_mismatch_count"]) for row in reports)
    long_active_count = sum(int(row["long_active_signal_count"]) for row in reports)
    short_active_count = sum(int(row["short_active_signal_count"]) for row in reports)
    short_only_count = class_histogram["FULL_SCAN_SHORT_ONLY_TRIGGER"]
    no_active_count = class_histogram["FULL_SCAN_NO_ACTIVE_TRIGGER"]
    zero_with_long_count = class_histogram["A4D_ZERO_WITH_FULL_SCAN_LONG_TRIGGER"]
    prior_short_gap_count = int(semantic.get("short_scope_gap_strategy_count") or 0)

    if blockers:
        state = "HOLD_INPUT_INVALID"
        next_stage = "R7.A4D2_TARGETED_DIAGNOSE"
    elif side_effect_attempts:
        state = "HOLD_SIDE_EFFECT_ATTEMPT"
        next_stage = "R7.A4D2_TARGETED_DIAGNOSE"
    elif adapter_error_count or direct_error_count or direct_mismatch_count or long_mapping_mismatch_count or invalid_geometry_count:
        state = "HOLD_TARGETED_PAYLOAD_GAP"
        next_stage = "R7.A4D2_PAYLOAD_GEOMETRY_CLOSURE"
    elif zero_with_long_count:
        state = "HOLD_A4D_CALL_WINDOW_GAP"
        next_stage = "R7.A4D2_CALL_WINDOW_CLOSURE"
    elif prior_short_gap_count or short_only_count:
        state = "HOLD_SHORT_EXECUTION_SCOPE_CONFIRMED"
        next_stage = "R7.A4D2_SHORT_EXECUTION_HARNESS"
    elif no_active_count:
        state = "HOLD_TRIGGER_COVERAGE_GAP"
        next_stage = "R7.A4D2_MARKET_TRIGGER_COVERAGE_REDESIGN"
    else:
        state = "PASS_TARGETED_TRIGGER_GEOMETRY"
        next_stage = "R7.A4E_EVENT_REPLAY_2880_INPUT_SELECTION"

    evidence = {
        "schema": "r7a4d2_targeted_trigger_geometry_diagnose_v1",
        "official_stage": "R7.A4D2_TARGETED_TRIGGER_GEOMETRY_DIAGNOSE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "target_strategy_count": len(target_ids),
        "target_strategy_ids": target_ids,
        "segment_count": len(segment_frames),
        "sample_state_count": 3,
        "full_scan_call_count": total_calls,
        "adapter_error_count": adapter_error_count,
        "direct_error_count": direct_error_count,
        "direct_payload_mismatch_count": direct_mismatch_count,
        "long_mapping_mismatch_count": long_mapping_mismatch_count,
        "invalid_geometry_count": invalid_geometry_count,
        "long_active_signal_count": long_active_count,
        "short_active_signal_count": short_active_count,
        "full_scan_short_only_strategy_count": short_only_count,
        "full_scan_no_active_trigger_strategy_count": no_active_count,
        "a4d_zero_with_long_trigger_strategy_count": zero_with_long_count,
        "prior_short_scope_gap_strategy_count": prior_short_gap_count,
        "classification_histogram": dict(sorted(class_histogram.items())),
        "geometry_failure_sample": global_geometry_samples,
        "side_effect_attempts": side_effect_attempts,
        "a4d_result_sha256": result_sha,
        "strategy_reports": reports,
        "next_stage": next_stage,
    }
    output_path = root / "runtime/r7a4d2_targeted_trigger_geometry_diagnose/targeted_diagnose_v1.json"
    atomic_json(output_path, evidence)

    for key in (
        "state",
        "blocker_count",
        "target_strategy_count",
        "segment_count",
        "sample_state_count",
        "full_scan_call_count",
        "adapter_error_count",
        "direct_error_count",
        "direct_payload_mismatch_count",
        "long_mapping_mismatch_count",
        "invalid_geometry_count",
        "long_active_signal_count",
        "short_active_signal_count",
        "full_scan_short_only_strategy_count",
        "full_scan_no_active_trigger_strategy_count",
        "a4d_zero_with_long_trigger_strategy_count",
        "prior_short_scope_gap_strategy_count",
        "next_stage",
    ):
        print(f"{key.upper()}={evidence[key]}")
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("CLASSIFICATION_HISTOGRAM=" + json.dumps(evidence["classification_histogram"], ensure_ascii=False, sort_keys=True))
    print("TARGET_STRATEGY_SUMMARY=" + json.dumps([
        {
            "strategy_id": row["strategy_id"],
            "classification": row["classification"],
            "a4d_trades": row["a4d_trade_count"],
            "long": row["long_active_signal_count"],
            "short": row["short_active_signal_count"],
            "geometry": row["invalid_geometry_count"],
            "top_reasons": row["top_hold_reasons"][:5],
        }
        for row in reports
    ], ensure_ascii=False))
    print("GEOMETRY_FAILURE_SAMPLE=" + json.dumps(global_geometry_samples[:20], ensure_ascii=False))
    print("SIDE_EFFECT_ATTEMPTS=" + json.dumps(side_effect_attempts, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output_path))
    print("RC=" + ("0" if state.startswith("PASS") else "2"))
    return 0 if state.startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
