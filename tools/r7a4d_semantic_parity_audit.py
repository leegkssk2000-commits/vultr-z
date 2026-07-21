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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
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


def normalized_signal(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("side", "action", "why", "skill"):
        result[key] = str(value.get(key) or "").strip().lower()
    for key in ("size", "entry", "sl", "tp", "confidence"):
        raw = value.get(key)
        try:
            number = float(raw or 0.0)
            result[key] = round(number, 10) if math.isfinite(number) else None
        except Exception:
            result[key] = None
    return result


def signal_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return normalized_signal(left) == normalized_signal(right)


def expected_intent(legacy: dict[str, Any]) -> str:
    side = str(legacy.get("side") or "").lower()
    action = str(legacy.get("action") or "hold").lower()
    if side == "long" and action in LONG_EXPECTED_INTENT:
        return LONG_EXPECTED_INTENT[action]
    if action == "block":
        return "block"
    return "hold"


def call_direct_strategy(module: Any, frame: pd.DataFrame, state: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
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
        and parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
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


def make_state(label: str, close: float) -> dict[str, Any]:
    if label == "flat":
        return {"position_side": "", "position_qty": 0.0, "avg_entry": 0.0, "add_count": 0, "last_add_price": 0.0}
    if label == "long":
        return {"position_side": "long", "position_qty": 0.50, "avg_entry": close * 0.99, "add_count": 0, "last_add_price": close * 0.99}
    return {"position_side": "short", "position_qty": 0.40, "avg_entry": close * 1.01, "add_count": 0, "last_add_price": close * 1.01}


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


def static_scope(source: str) -> dict[str, bool]:
    lowered = source.lower()
    return {
        "explicit_long_only_marker": "short_signal_generated_but_core_is_long_only" in lowered or "short_pending_core_upgrade" in lowered,
        "enter_short_intent_present": "enter_short" in lowered,
        "legacy_signal_payload_present": "legacy_signal" in lowered,
        "enter_long_intent_present": "enter_long" in lowered,
        "reduce_intent_present": "strategyintent.reduce" in lowered or 'intent="reduce"' in lowered,
        "exit_long_intent_present": "exit_long" in lowered,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--a4d-runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.a4d_runner), "r7a4d_semantic_audit_runner")
    contract = load_json(Path(args.contract))

    registry_path = root / str(contract["registry_path"])
    manifest_path = root / str(contract["selected_manifest_path"])
    results_path = root / str(contract["scenario_results_path"])
    status_path = root / str(contract["status_path"])
    proof_path = root / str(contract["proof_path"])

    registry = load_json(registry_path)
    manifest = load_json(manifest_path)
    status = load_json(status_path)
    proof = load_json(proof_path)
    result_rows = load_results(results_path)

    blockers: list[str] = []
    if len(result_rows) != 3600 or sum(row.get("completed") is True for row in result_rows) != 3600:
        blockers.append("A4D_RESULT_ARTIFACT_INVALID")
    result_sha = sha256_file(results_path)
    if any(str(source.get("scenario_results_sha256") or "") != result_sha for source in (status, proof)):
        blockers.append("A4D_RESULT_HASH_MISMATCH")

    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    if len(entries) != 25:
        blockers.append(f"REGISTRY_ENTRY_COUNT_INVALID:{len(entries)}")
    if len(segments) != 24:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")

    trade_by_strategy: Counter[str] = Counter()
    active_by_strategy: Counter[str] = Counter()
    for row in result_rows:
        strategy_id = str(row.get("strategy_id") or "")
        trades = int(row.get("trade_count") or 0)
        trade_by_strategy[strategy_id] += trades
        active_by_strategy[strategy_id] += int(trades > 0)

    segment_frames: list[tuple[str, str, pd.DataFrame]] = []
    for segment in segments:
        try:
            source_path = root / runner.safe_repo_path(str(segment["source_path"]))
            if runner.sha256_file(source_path) != segment.get("source_sha256"):
                raise ValueError("SOURCE_SHA_MISMATCH")
            frame = runner.load_market_frame(source_path)
            sample = frame.iloc[int(segment["start_row"]):int(segment["end_row_exclusive"])].copy().reset_index(drop=True)
            if len(sample) != int(contract["segment_bars"]):
                raise ValueError(f"BAR_COUNT:{len(sample)}")
            segment_frames.append((str(segment["segment_id"]), str(segment.get("regime") or "unknown"), sample))
        except Exception as exc:
            blockers.append(f"SEGMENT_LOAD_FAILED:{segment.get('segment_id')}:{type(exc).__name__}:{exc}")

    cost_profiles = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]
    cost_profile = cost_profiles[0] if cost_profiles else {
        "fee_bps_per_side": 0.0,
        "slippage_bps_per_side": 0.0,
        "latency_bars": 0,
        "funding_bps_per_8h": 0.0,
    }

    strategy_reports: list[dict[str, Any]] = []
    total_adapter_calls = 0
    total_direct_calls = 0
    direct_payload_mismatch_count = 0
    long_mapping_mismatch_count = 0
    short_downgrade_count = 0
    critical_payload_missing_count = 0
    adapter_error_count = 0
    direct_error_count = 0

    sys.path.insert(0, str(root))
    try:
        for entry in sorted(entries, key=lambda row: str(row.get("strategy_id") or "")):
            strategy_id = str(entry.get("strategy_id") or "")
            engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
            implementation_path = runner.safe_repo_path(str(engine.get("implementation_path") or ""))
            source_path = root / implementation_path
            expected_sha = str(engine.get("source_sha256") or "")
            if expected_sha and runner.sha256_file(source_path) != expected_sha:
                blockers.append(f"STRATEGY_SOURCE_SHA_MISMATCH:{strategy_id}")
                continue
            module = runner.load_module(root, implementation_path, f"semantic_{strategy_id}")
            owner, method_name = runner.resolve_callable(module, str(engine.get("callable") or ""))
            instance = owner()
            scope = static_scope(source_path.read_text(encoding="utf-8", errors="replace"))

            counters: Counter[str] = Counter()
            intent_hist: Counter[str] = Counter()
            action_hist: Counter[str] = Counter()
            state_action_hist: dict[str, Counter[str]] = defaultdict(Counter)
            error_sample: list[str] = []
            mismatch_sample: list[dict[str, Any]] = []

            for segment_id, regime, frame in segment_frames:
                start = max(int(contract.get("minimum_call_bars", 32)), 64)
                checkpoints = sorted(set([start, 160, 208, 256, 304, len(frame) - 1]))
                checkpoints = [value for value in checkpoints if 2 <= value < len(frame)]
                for end_exclusive in checkpoints:
                    sample = frame.iloc[:end_exclusive].copy().reset_index(drop=True)
                    public_columns = [column for column in sample.columns if not str(column).startswith("__")]
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
                            ctx = runner.build_context(strategy_id, row_records, position, regime, cost_profile)
                            decision = getattr(instance, method_name)(ctx)
                            fields = runner.decision_fields(decision)
                            legacy = runner.legacy_signal(fields)
                            total_adapter_calls += 1
                            counters["adapter_calls"] += 1
                            intent = str(fields.get("intent") or "hold")
                            intent_hist[intent] += 1
                            side = str(legacy.get("side") or "").lower()
                            action = str(legacy.get("action") or "hold").lower()
                            action_hist[f"{side or 'none'}:{action}"] += 1
                            state_action_hist[state_label][f"{side or 'none'}:{action}"] += 1

                            if side == "short" and action in ACTIVE_ACTIONS and intent == "hold":
                                counters["short_downgrade"] += 1
                                short_downgrade_count += 1
                            if side == "long" and action in LONG_EXPECTED_INTENT and intent != LONG_EXPECTED_INTENT[action]:
                                counters["long_mapping_mismatch"] += 1
                                long_mapping_mismatch_count += 1
                                if len(mismatch_sample) < 8:
                                    mismatch_sample.append({"segment_id": segment_id, "state": state_label, "kind": "LONG_MAPPING", "legacy": normalized_signal(legacy), "intent": intent})
                            if side in {"long", "short"} and action in {"enter", "add"}:
                                size = float(legacy.get("size") or 0.0)
                                entry_price = float(legacy.get("entry") or 0.0)
                                sl = float(legacy.get("sl") or 0.0)
                                tp = float(legacy.get("tp") or 0.0)
                                valid_geometry = size > 0 and entry_price > 0 and ((side == "long" and sl < entry_price < tp) or (side == "short" and tp < entry_price < sl))
                                if not valid_geometry:
                                    counters["critical_payload_missing"] += 1
                                    critical_payload_missing_count += 1

                            direct, direct_error = call_direct_strategy(module, sample[public_columns].copy(), state)
                            if direct_error:
                                counters["direct_errors"] += 1
                                direct_error_count += 1
                                if len(error_sample) < 8:
                                    error_sample.append(f"{segment_id}:{state_label}:{direct_error}")
                            else:
                                total_direct_calls += 1
                                counters["direct_calls"] += 1
                                if not signal_equal(direct or {}, legacy):
                                    counters["direct_payload_mismatch"] += 1
                                    direct_payload_mismatch_count += 1
                                    if len(mismatch_sample) < 8:
                                        mismatch_sample.append({"segment_id": segment_id, "state": state_label, "kind": "DIRECT_VS_PAYLOAD", "direct": normalized_signal(direct or {}), "legacy": normalized_signal(legacy)})
                        except Exception as exc:
                            counters["adapter_errors"] += 1
                            adapter_error_count += 1
                            if len(error_sample) < 8:
                                error_sample.append(f"{segment_id}:{state_label}:ADAPTER:{type(exc).__name__}:{exc}")

            long_signal_count = sum(count for key, count in action_hist.items() if key.startswith("long:") and key.split(":", 1)[1] in ACTIVE_ACTIONS)
            short_signal_count = sum(count for key, count in action_hist.items() if key.startswith("short:") and key.split(":", 1)[1] in ACTIVE_ACTIONS)
            a4d_trades = int(trade_by_strategy.get(strategy_id, 0))
            unresolved_zero = bool(a4d_trades == 0 and long_signal_count > 0 and counters["long_mapping_mismatch"] == 0)
            if counters["adapter_errors"] or counters["direct_payload_mismatch"] or counters["long_mapping_mismatch"] or counters["critical_payload_missing"]:
                classification = "SEMANTIC_PARITY_FAIL"
            elif counters["short_downgrade"]:
                classification = "LONG_PARITY_PASS_SHORT_SCOPE_GAP"
            elif a4d_trades == 0 and long_signal_count == 0:
                classification = "NO_LONG_TRIGGER_SELECTED_FOLDS"
            elif unresolved_zero:
                classification = "UNEXPLAINED_ZERO_TRADE"
            else:
                classification = "LONG_ONLY_PARITY_PASS"

            strategy_reports.append({
                "strategy_id": strategy_id,
                "implementation_path": implementation_path,
                "a4d_trade_count": a4d_trades,
                "a4d_active_scenario_count": int(active_by_strategy.get(strategy_id, 0)),
                "classification": classification,
                "static_scope": scope,
                "adapter_call_count": counters["adapter_calls"],
                "direct_call_count": counters["direct_calls"],
                "adapter_error_count": counters["adapter_errors"],
                "direct_error_count": counters["direct_errors"],
                "direct_payload_mismatch_count": counters["direct_payload_mismatch"],
                "long_mapping_mismatch_count": counters["long_mapping_mismatch"],
                "short_downgrade_count": counters["short_downgrade"],
                "critical_payload_missing_count": counters["critical_payload_missing"],
                "sampled_long_active_signal_count": long_signal_count,
                "sampled_short_active_signal_count": short_signal_count,
                "intent_histogram": dict(sorted(intent_hist.items())),
                "legacy_action_histogram": dict(sorted(action_hist.items())),
                "state_action_histogram": {key: dict(sorted(value.items())) for key, value in sorted(state_action_hist.items())},
                "error_sample": error_sample,
                "mismatch_sample": mismatch_sample,
            })
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    class_histogram = Counter(row["classification"] for row in strategy_reports)
    parity_failure_count = class_histogram["SEMANTIC_PARITY_FAIL"]
    short_scope_gap_strategy_count = class_histogram["LONG_PARITY_PASS_SHORT_SCOPE_GAP"]
    unexplained_zero_count = class_histogram["UNEXPLAINED_ZERO_TRADE"]
    zero_trigger_count = class_histogram["NO_LONG_TRIGGER_SELECTED_FOLDS"]

    if blockers:
        state = "HOLD_INPUT_INVALID"
        next_stage = "R7.A4D_SEMANTIC_PARITY_DIAGNOSE"
    elif parity_failure_count or unexplained_zero_count:
        state = "HOLD_SEMANTIC_PARITY_GAP"
        next_stage = "R7.A4D2_TARGETED_CALLER_AND_ADAPTER_CLOSURE"
    elif short_scope_gap_strategy_count or short_downgrade_count:
        state = "HOLD_LONG_ONLY_SCOPE_CONFIRMED"
        next_stage = "R7.A4D2_SHORT_EXECUTION_SCOPE_DECISION"
    else:
        state = "PASS_LONG_ONLY_SEMANTIC_PARITY"
        next_stage = "R7.A4E_EVENT_REPLAY_2880_INPUT_SELECTION"

    evidence = {
        "schema": "r7a4d_semantic_parity_audit_v1",
        "official_stage": "R7.A4D_SEMANTIC_PARITY_AUDIT",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(strategy_reports),
        "segment_count": len(segment_frames),
        "sample_state_count": 3,
        "adapter_call_count": total_adapter_calls,
        "direct_call_count": total_direct_calls,
        "adapter_error_count": adapter_error_count,
        "direct_error_count": direct_error_count,
        "direct_payload_mismatch_count": direct_payload_mismatch_count,
        "long_mapping_mismatch_count": long_mapping_mismatch_count,
        "short_downgrade_count": short_downgrade_count,
        "critical_payload_missing_count": critical_payload_missing_count,
        "semantic_parity_failure_strategy_count": parity_failure_count,
        "short_scope_gap_strategy_count": short_scope_gap_strategy_count,
        "no_long_trigger_strategy_count": zero_trigger_count,
        "unexplained_zero_trade_strategy_count": unexplained_zero_count,
        "classification_histogram": dict(sorted(class_histogram.items())),
        "a4d_result_sha256": result_sha,
        "strategy_reports": strategy_reports,
        "next_stage": next_stage,
    }
    output_path = root / "runtime/r7a4d_semantic_parity_audit/semantic_parity_audit_v1.json"
    atomic_json(output_path, evidence)

    for key in (
        "state", "blocker_count", "strategy_count", "segment_count", "sample_state_count",
        "adapter_call_count", "direct_call_count", "adapter_error_count", "direct_error_count",
        "direct_payload_mismatch_count", "long_mapping_mismatch_count", "short_downgrade_count",
        "critical_payload_missing_count", "semantic_parity_failure_strategy_count",
        "short_scope_gap_strategy_count", "no_long_trigger_strategy_count",
        "unexplained_zero_trade_strategy_count", "next_stage",
    ):
        print(f"{key.upper()}={evidence[key]}")
    print("CLASSIFICATION_HISTOGRAM=" + json.dumps(evidence["classification_histogram"], ensure_ascii=False, sort_keys=True))
    print("STRATEGY_CLASSIFICATIONS=" + json.dumps([
        {
            "strategy_id": row["strategy_id"],
            "classification": row["classification"],
            "a4d_trade_count": row["a4d_trade_count"],
            "long_signals": row["sampled_long_active_signal_count"],
            "short_signals": row["sampled_short_active_signal_count"],
            "short_downgrades": row["short_downgrade_count"],
            "mismatches": row["direct_payload_mismatch_count"] + row["long_mapping_mismatch_count"],
        }
        for row in strategy_reports
    ], ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output_path))
    print("RC=" + ("0" if state.startswith("PASS") else "2"))
    return 0 if state.startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
