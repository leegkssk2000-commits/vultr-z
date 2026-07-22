#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ARCHITECTURES = (
    ("TF5_STRUCTURE_TF5_TRIGGER", 5, 5),
    ("TF15_STRUCTURE_TF15_TRIGGER", 15, 15),
    ("TF15_STRUCTURE_TF5_TRIGGER", 15, 5),
)
TARGET_PER_ARCHITECTURE = 12
DISCOVERY_PER_ARCHITECTURE = 6
VALIDATION_PER_ARCHITECTURE = 6
TARGET_CANDIDATE_COUNT = 36
TARGET_CELL_COUNT = 216
PREROLL_BARS = 320
EVALUATION_BARS = 320
WINDOW_BARS = PREROLL_BARS + EVALUATION_BARS
WINDOW_STEP_BARS = 160
PIVOT_SPAN = 2
PIVOT_LOOKBACK = 48
CONDITIONAL_REQUIRED_RAW_DISTANCE_PCT = 0.9696969697
ROBUST_REQUIRED_RAW_DISTANCE_PCT = 1.28


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def window_starts(length: int) -> list[int]:
    if length < WINDOW_BARS:
        return []
    starts = list(range(0, length - WINDOW_BARS + 1, WINDOW_STEP_BARS))
    final_start = length - WINDOW_BARS
    if final_start not in starts:
        starts.append(final_start)
    return sorted(set(starts))


def latest_confirmed_pivot_high(structure: pd.DataFrame, trigger_timestamp: float) -> tuple[float, float, int] | None:
    eligible = structure[structure["__timestamp"] < trigger_timestamp].reset_index(drop=True)
    if len(eligible) < PIVOT_SPAN * 2 + 1:
        return None
    start = max(PIVOT_SPAN, len(eligible) - PIVOT_LOOKBACK)
    end = len(eligible) - PIVOT_SPAN
    for index in range(end - 1, start - 1, -1):
        center = finite(eligible.iloc[index]["high"])
        left = [finite(value) for value in eligible.iloc[index - PIVOT_SPAN:index]["high"]]
        right = [finite(value) for value in eligible.iloc[index + 1:index + 1 + PIVOT_SPAN]["high"]]
        if center > 0 and all(center > value for value in left) and all(center >= value for value in right):
            return center, finite(eligible.iloc[index]["__timestamp"]), index
    return None


def natural_short_distance(entry_price: float, pivot_high: float) -> float:
    if entry_price <= 0 or pivot_high <= entry_price:
        return 0.0
    return round((pivot_high - entry_price) / entry_price * 100.0, 10)


def round_robin_select(candidates: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(candidates, key=lambda item: (finite(item.get("timestamp")), str(item.get("symbol")), str(item.get("candidate_id")))):
        by_symbol[str(row.get("symbol") or "UNKNOWN")].append(row)
    symbols = sorted(by_symbol)
    selected: list[dict[str, Any]] = []
    round_index = 0
    while len(selected) < target:
        added = 0
        for symbol in symbols:
            rows = by_symbol[symbol]
            if round_index < len(rows):
                selected.append(rows[round_index])
                added += 1
                if len(selected) == target:
                    break
        if added == 0:
            break
        round_index += 1
    return sorted(selected, key=lambda item: (finite(item.get("timestamp")), str(item.get("symbol"))))


def assign_split(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, row in enumerate(selected):
        item = dict(row)
        item["split"] = "discovery" if index < DISCOVERY_PER_ARCHITECTURE else "validation"
        output.append(item)
    return output


def validate_bind(bind: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[str] = []
    if bind.get("state") != "PASS_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND":
        errors.append("ADAPTER_BIND_NOT_PASS")
    if int(bind.get("blocker_count", -1)) != 0:
        errors.append("ADAPTER_BIND_BLOCKED")
    if bind.get("candidate_discovery_ready") is not True:
        errors.append("CANDIDATE_DISCOVERY_NOT_READY")
    if int(bind.get("bound_source_count", -1)) != 5 or int(bind.get("bound_symbol_count", -1)) != 5:
        errors.append("BOUND_SOURCE_OR_SYMBOL_COUNT_INVALID")
    if bind.get("layout_signature") != [6, 0, 1, 2, 3, 4]:
        errors.append("BOUND_LAYOUT_SIGNATURE_INVALID")
    if bind.get("next_stage") != "R7.A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36":
        errors.append("ADAPTER_BIND_NEXT_STAGE_INVALID")
    allowlist = [row for row in bind.get("source_allowlist", []) if isinstance(row, dict)]
    if len(allowlist) != 5:
        errors.append("SOURCE_ALLOWLIST_COUNT_INVALID")
    if errors:
        raise ValueError(";".join(errors))
    return allowlist


def scan_architecture(
    architecture_id: str,
    structure_minutes: int,
    trigger_minutes: int,
    frames: dict[str, dict[int, pd.DataFrame]],
    runner: Any,
    owner: type[Any],
    method_name: str,
    contract: dict[str, Any],
    cost: dict[str, Any],
    perturbation: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_candidates: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    discovery_contract = dict(contract)
    discovery_contract.update({
        "indicator_preroll_bars": PREROLL_BARS,
        "segment_bars": EVALUATION_BARS,
        "short_execution_enabled": True,
        "short_target_strategy_ids": ["scalp_snap"],
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
    })
    for symbol in sorted(frames):
        trigger = frames[symbol][trigger_minutes]
        structure = frames[symbol][structure_minutes]
        for start in window_starts(len(trigger)):
            sample = trigger.iloc[start:start + WINDOW_BARS].reset_index(drop=True)
            scenario_id = f"{architecture_id}:{symbol}:{start}"
            scenario = {
                "scenario_id": scenario_id,
                "strategy_id": "scalp_snap",
                "segment_id": f"{architecture_id}:{symbol}:{start}",
                "regime": "trend_down",
                "cost_profile": str(cost.get("id") or "cost_profile_0"),
                "perturbation": str(perturbation.get("id") or "perturbation_0"),
            }
            try:
                result = runner.simulate_scenario(
                    scenario,
                    sample,
                    owner,
                    method_name,
                    cost,
                    perturbation,
                    discovery_contract,
                )
            except Exception as exc:
                failures.append({"scenario_id": scenario_id, "error": f"{type(exc).__name__}:{exc}"})
                continue
            traces = [row for row in result.get("short_candidate_trace", []) if isinstance(row, dict)]
            for trace in traces:
                if trace.get("legacy_action") != "enter" or trace.get("candidate_state") != "FLAT_ENTER":
                    continue
                bar_index = int(trace.get("bar_index", -1))
                if not (0 <= bar_index < len(sample)):
                    failures.append({"scenario_id": scenario_id, "error": f"TRACE_BAR_INDEX_INVALID:{bar_index}"})
                    continue
                bar = sample.iloc[bar_index]
                timestamp = int(finite(bar["__timestamp"]))
                key = (symbol, timestamp)
                if key in seen:
                    continue
                seen.add(key)
                entry_price = finite(bar["close"])
                pivot = latest_confirmed_pivot_high(structure, timestamp)
                if pivot is None:
                    raw_distance = 0.0
                    pivot_high = 0.0
                    pivot_timestamp = 0
                    pivot_found = False
                else:
                    pivot_high, pivot_ts, _ = pivot
                    pivot_timestamp = int(pivot_ts)
                    raw_distance = natural_short_distance(entry_price, pivot_high)
                    pivot_found = True
                candidate_id = hashlib.sha256(
                    f"{architecture_id}|{symbol}|{timestamp}|scalp_snap".encode("utf-8")
                ).hexdigest()[:24]
                raw_candidates.append({
                    "candidate_id": candidate_id,
                    "architecture_id": architecture_id,
                    "strategy_id": "scalp_snap",
                    "side": "short",
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "trigger_timeframe": f"{trigger_minutes}m",
                    "structure_timeframe": f"{structure_minutes}m",
                    "entry_price": round(entry_price, 10),
                    "pivot_high": round(pivot_high, 10),
                    "pivot_timestamp": pivot_timestamp,
                    "pivot_found": pivot_found,
                    "natural_raw_distance_pct": raw_distance,
                    "conditional_distance_pass": raw_distance >= CONDITIONAL_REQUIRED_RAW_DISTANCE_PCT,
                    "robust_distance_pass": raw_distance >= ROBUST_REQUIRED_RAW_DISTANCE_PCT,
                    "legacy_reason": str(trace.get("legacy_reason") or ""),
                    "selection_uses_future_pnl": False,
                    "source_window_start": start,
                    "source_scenario_id": scenario_id,
                })
    return sorted(raw_candidates, key=lambda row: (row["timestamp"], row["symbol"])), failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_scalp_discovery_runner")
    adapter = load_module(Path(args.adapter).resolve(), "r7a4d2_scalp_discovery_adapter")
    contract = load_json(Path(args.contract).resolve())
    bind_path = root / "runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json"
    registry_path = root / str(contract["registry_path"])
    bind = load_json(bind_path)
    registry = load_json(registry_path)
    blockers: list[str] = []
    failures: list[dict[str, Any]] = []

    try:
        allowlist = validate_bind(bind)
    except Exception as exc:
        allowlist = []
        blockers.append(f"ADAPTER_BIND_INPUT_INVALID:{type(exc).__name__}:{exc}")

    entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
    scalp_entry = entries.get("scalp_snap")
    if not isinstance(scalp_entry, dict):
        blockers.append("SCALP_SNAP_REGISTRY_ENTRY_MISSING")
        engine = {}
    else:
        engine = scalp_entry.get("canonical_engine") if isinstance(scalp_entry.get("canonical_engine"), dict) else {}
    implementation_path = str(engine.get("implementation_path") or "")
    implementation = root / runner.safe_repo_path(implementation_path) if implementation_path else root / "missing"
    expected_source_sha = str(engine.get("source_sha256") or "")
    if not expected_source_sha or runner.sha256_file(implementation) != expected_source_sha:
        blockers.append("SCALP_SNAP_SOURCE_REGISTRY_SHA_MISMATCH")

    frames: dict[str, dict[int, pd.DataFrame]] = {}
    protected = [bind_path, registry_path, implementation]
    if not blockers:
        try:
            for row in allowlist:
                path = root / adapter.safe_repo_path(str(row["source_path"]))
                protected.append(path)
                frame_1m = adapter.load_audited_market_frame(path, str(row["source_sha256"]))
                frames[str(row["symbol"])] = {
                    5: adapter.resample_complete_bars(frame_1m, 5),
                    15: adapter.resample_complete_bars(frame_1m, 15),
                }
        except Exception as exc:
            blockers.append(f"MARKET_FRAME_PREPARE_FAILED:{type(exc).__name__}:{exc}")

    before = runner.snapshot(protected)
    all_selected: list[dict[str, Any]] = []
    architecture_summary: dict[str, Any] = {}
    side_effect_attempts: list[str] = []
    if not blockers:
        sys.path.insert(0, str(root))
        try:
            module = runner.load_module(root, runner.safe_repo_path(implementation_path), "scalp_snap_timeframe_discovery")
            owner, method_name = runner.resolve_callable(module, str(engine.get("callable") or ""))
            costs = {str(row.get("id")): row for row in contract.get("cost_profiles", []) if isinstance(row, dict)}
            perturbations = {str(row.get("id")): row for row in contract.get("perturbations", []) if isinstance(row, dict)}
            cost = costs.get("cost_profile_0")
            perturbation = perturbations.get("perturbation_0")
            if not isinstance(cost, dict) or not isinstance(perturbation, dict):
                raise ValueError("BASELINE_COST_OR_PERTURBATION_MISSING")
            with runner.side_effect_guard(side_effect_attempts):
                for architecture_id, structure_minutes, trigger_minutes in ARCHITECTURES:
                    raw, architecture_failures = scan_architecture(
                        architecture_id,
                        structure_minutes,
                        trigger_minutes,
                        frames,
                        runner,
                        owner,
                        method_name,
                        contract,
                        cost,
                        perturbation,
                    )
                    failures.extend(architecture_failures)
                    eligible = [row for row in raw if row["conditional_distance_pass"]]
                    selected = assign_split(round_robin_select(eligible, TARGET_PER_ARCHITECTURE))
                    all_selected.extend(selected)
                    architecture_summary[architecture_id] = {
                        "raw_signal_candidate_count": len(raw),
                        "pivot_found_count": sum(bool(row["pivot_found"]) for row in raw),
                        "conditional_distance_pass_count": len(eligible),
                        "robust_distance_pass_count": sum(bool(row["robust_distance_pass"]) for row in raw),
                        "selected_candidate_count": len(selected),
                        "discovery_count": sum(row["split"] == "discovery" for row in selected),
                        "validation_count": sum(row["split"] == "validation" for row in selected),
                        "selected_symbol_histogram": dict(sorted(Counter(row["symbol"] for row in selected).items())),
                        "median_selected_raw_distance_pct": round(statistics.median([row["natural_raw_distance_pct"] for row in selected]), 10) if selected else 0.0,
                    }
                    if len(selected) != TARGET_PER_ARCHITECTURE:
                        blockers.append(f"ARCHITECTURE_CANDIDATE_SHORTFALL:{architecture_id}:{len(selected)}:{TARGET_PER_ARCHITECTURE}")
        except Exception as exc:
            blockers.append(f"CANDIDATE_DISCOVERY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    after = runner.snapshot(protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPTS:{len(side_effect_attempts)}")
    if failures:
        blockers.append(f"DISCOVERY_SCENARIO_FAILURES:{len(failures)}")
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
    if len(all_selected) != TARGET_CANDIDATE_COUNT:
        blockers.append(f"SELECTED_CANDIDATE_COUNT_INVALID:{len(all_selected)}:{TARGET_CANDIDATE_COUNT}")
    candidate_ids = [str(row.get("candidate_id")) for row in all_selected]
    if len(candidate_ids) != len(set(candidate_ids)):
        blockers.append("SELECTED_CANDIDATE_ID_DUPLICATE")

    blockers = list(dict.fromkeys(blockers))
    passed = not blockers
    result = {
        "schema": "r7a4d2_short_scalp_timeframe_candidate_discovery_36_v1",
        "official_stage": "R7.A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36",
        "state": "PASS_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36" if passed else "HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_id": "scalp_snap",
        "side": "short",
        "architecture_count": len(ARCHITECTURES),
        "architecture_summary": architecture_summary,
        "candidate_target_count": TARGET_CANDIDATE_COUNT,
        "selected_candidate_count": len(all_selected),
        "execution_cell_target_count": TARGET_CELL_COUNT,
        "conditional_required_raw_distance_pct": CONDITIONAL_REQUIRED_RAW_DISTANCE_PCT,
        "robust_required_raw_distance_pct": ROBUST_REQUIRED_RAW_DISTANCE_PCT,
        "selected_candidates": all_selected,
        "failure_count": len(failures),
        "failures": failures[:50],
        "side_effect_attempt_count": len(side_effect_attempts),
        "protected_mutation_path_count": len(mutation_paths),
        "protected_mutation_paths": mutation_paths,
        "future_pnl_selection_allowed": False,
        "short_execution_allowed": False,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": "R7.A4D2_SHORT_SCALP_TIMEFRAME_COUNTERFACTUAL_216" if passed else "R7.A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36",
    }
    output = root / "runtime/r7a4d2_short_scalp_timeframe_candidate_discovery_36/candidate_discovery_v1.json"
    atomic_json(output, result)
    print("STATE=" + str(result["state"]))
    print("BLOCKER_COUNT=" + str(result["blocker_count"]))
    print("ARCHITECTURE_COUNT=" + str(result["architecture_count"]))
    print("CANDIDATE_TARGET_COUNT=" + str(result["candidate_target_count"]))
    print("SELECTED_CANDIDATE_COUNT=" + str(result["selected_candidate_count"]))
    print("EXECUTION_CELL_TARGET_COUNT=" + str(result["execution_cell_target_count"]))
    print("ARCHITECTURE_SUMMARY=" + json.dumps(result["architecture_summary"], ensure_ascii=False, sort_keys=True))
    print("SELECTED_SYMBOL_HISTOGRAM=" + json.dumps(dict(sorted(Counter(row["symbol"] for row in all_selected).items())), sort_keys=True))
    print("FAILURE_COUNT=" + str(result["failure_count"]))
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(result["side_effect_attempt_count"]))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(result["protected_mutation_path_count"]))
    print("CANDIDATE_JSON=" + str(output))
    print("NEXT_STAGE=" + str(result["next_stage"]))
    print("BLOCKERS=" + json.dumps(result["blockers"], ensure_ascii=False))
    print("RC=" + ("0" if passed else "2"))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
