#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() and not path.is_symlink() else None


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def prior_gate(status: dict[str, Any], expected: int) -> bool:
    required = {
        "official_stage": "R7.A4B",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": expected,
        "strategy_import_count": expected,
        "strategy_pass_count": expected,
        "fixture_count": 4,
        "repeat_count": 2,
        "deterministic_pair_count": expected * 4,
        "dry_run_call_count": expected * 8,
        "successful_call_count": expected * 8,
        "side_effect_attempt_count": 0,
        "canonical_input_parity_count": expected + 3,
        "historical_market_data_used_count": 0,
        "execution_cost_model_applied_count": 0,
        "historical_replay_execution_count": 0,
        "active_entry_count": 0,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "paper_live_order_count": 0,
        "next_stage": "R7.A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE",
    }
    return all(status.get(key) == value for key, value in required.items()) and bool(status.get("dry_run_input_set_id"))


def read_text(path: Path, limit: int = 1048576) -> str:
    try:
        return path.read_bytes()[:limit].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def load_market_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(path)
    elif suffix == ".jsonl":
        frame = pd.read_json(path, lines=True)
    elif suffix == ".json":
        try:
            frame = pd.read_json(path)
        except ValueError:
            frame = pd.read_json(path, lines=True)
    elif suffix == ".parquet":
        frame = pd.read_parquet(path)
    elif suffix == ".feather":
        frame = pd.read_feather(path)
    elif suffix == ".npz":
        data = np.load(path, allow_pickle=False)
        frame = pd.DataFrame({key: data[key] for key in data.files})
    else:
        raise ValueError(f"UNSUPPORTED_MARKET_FORMAT:{suffix}")
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("MARKET_DATA_NOT_FRAME")
    frame = frame.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    return frame


def first_column(columns: list[str], aliases: list[str]) -> str | None:
    lowered = {str(column).lower(): str(column) for column in columns}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def normalize_market_frame(frame: pd.DataFrame, contract: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("MARKET_DATA_NOT_FRAME")
    frame = frame.copy()
    normalized_columns = [str(column).strip().lower() for column in frame.columns]
    collisions = sorted(column for column, count in Counter(normalized_columns).items() if count > 1)
    if collisions:
        raise ValueError("MARKET_COLUMN_COLLISION:" + ",".join(collisions))
    frame.columns = normalized_columns

    required = [str(item).lower() for item in contract.get("market_required_columns", [])]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("MARKET_COLUMNS_MISSING:" + ",".join(missing))
    timestamp_col = first_column(list(frame.columns), [str(item) for item in contract.get("timestamp_aliases", [])])
    if timestamp_col is None:
        raise ValueError("MARKET_TIMESTAMP_MISSING")
    symbol_col = first_column(list(frame.columns), [str(item) for item in contract.get("symbol_aliases", [])])
    timeframe_col = first_column(list(frame.columns), [str(item) for item in contract.get("timeframe_aliases", [])])
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    timestamp_numeric = pd.to_numeric(frame[timestamp_col], errors="coerce")
    if timestamp_numeric.notna().sum() >= max(2, len(frame) // 2):
        frame["__timestamp"] = timestamp_numeric
    else:
        parsed = pd.to_datetime(frame[timestamp_col], errors="coerce", utc=True)
        frame["__timestamp"] = parsed.astype("int64", errors="ignore")
    frame = frame.dropna(subset=required + ["__timestamp"])
    frame = frame[(frame["high"] >= frame[["open", "close"]].max(axis=1))]
    frame = frame[(frame["low"] <= frame[["open", "close"]].min(axis=1))]
    frame = frame[frame["close"] > 0]
    frame = frame.sort_values("__timestamp").drop_duplicates("__timestamp", keep="last").reset_index(drop=True)
    metadata = {
        "symbol": str(frame[symbol_col].dropna().iloc[0]) if symbol_col and not frame[symbol_col].dropna().empty else None,
        "timeframe": str(frame[timeframe_col].dropna().iloc[0]) if timeframe_col and not frame[timeframe_col].dropna().empty else None,
        "timestamp_column": timestamp_col,
    }
    return frame, metadata


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
    trough = float(close[trough_index])
    recovery = float(close[-1] / max(trough, 1e-12) - 1.0)
    shock_score = abs(max_drawdown) + max(recovery, 0.0)
    return {
        "return": round(total_return, 12),
        "volatility": round(volatility, 12),
        "trend_score": round(trend_score, 12),
        "max_drawdown": round(max_drawdown, 12),
        "recovery": round(recovery, 12),
        "shock_score": round(shock_score, 12),
    }


def build_segments(root: Path, entries: list[dict[str, Any]], contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bars = int(contract.get("segment_bars", 320))
    minimum_rows = int(contract.get("minimum_source_rows", bars * 2))
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for entry in entries:
        repo_path = str(entry.get("path") or "")
        try:
            repo_path = safe_repo_path(repo_path)
            path = root / repo_path
            digest = sha256_file(path)
            if digest is None or digest != entry.get("sha256"):
                raise ValueError("FROZEN_SHA_MISMATCH")
            frame, metadata = normalize_market_frame(load_market_frame(path), contract)
            if len(frame) < minimum_rows:
                raise ValueError(f"INSUFFICIENT_ROWS:{len(frame)}")
            for start in range(0, len(frame) - bars + 1, bars):
                stop = start + bars
                sample = frame.iloc[start:stop]
                metrics = segment_metrics(sample)
                segment_id = sha256_bytes(f"{repo_path}:{digest}:{start}:{stop}".encode())[:24]
                accepted.append({
                    "segment_id": segment_id,
                    "source_path": repo_path,
                    "source_sha256": digest,
                    "start_row": start,
                    "end_row_exclusive": stop,
                    "bars": bars,
                    "start_timestamp": str(sample["__timestamp"].iloc[0]),
                    "end_timestamp": str(sample["__timestamp"].iloc[-1]),
                    "symbol": metadata.get("symbol"),
                    "timeframe": metadata.get("timeframe"),
                    "metrics": metrics,
                })
        except Exception as exc:
            rejected.append({"path": repo_path, "reason": f"{type(exc).__name__}:{exc}"})
    return accepted, rejected


def select_regime_segments(segments: list[dict[str, Any]], regimes: list[str], folds: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    coverage: dict[str, int] = {}

    def choose(regime: str, ordered: list[dict[str, Any]]) -> None:
        picks: list[dict[str, Any]] = []
        for row in ordered:
            if row["segment_id"] in used:
                continue
            copy = dict(row)
            copy["regime"] = regime
            copy["fold"] = len(picks)
            picks.append(copy)
            used.add(row["segment_id"])
            if len(picks) == folds:
                break
        selected.extend(picks)
        coverage[regime] = len(picks)

    shock = sorted(
        [row for row in segments if row["metrics"]["max_drawdown"] < 0 and row["metrics"]["recovery"] > 0],
        key=lambda row: (-row["metrics"]["shock_score"], row["segment_id"]),
    )
    up = sorted(
        [row for row in segments if row["metrics"]["return"] > 0],
        key=lambda row: (-row["metrics"]["trend_score"], row["segment_id"]),
    )
    down = sorted(
        [row for row in segments if row["metrics"]["return"] < 0],
        key=lambda row: (row["metrics"]["trend_score"], row["segment_id"]),
    )
    range_like = sorted(segments, key=lambda row: (abs(row["metrics"]["trend_score"]), row["segment_id"]))
    order_map = {"shock_recovery": shock, "trend_up": up, "trend_down": down, "range": range_like}
    for regime in ("shock_recovery", "trend_up", "trend_down", "range"):
        if regime in regimes:
            choose(regime, order_map[regime])
    for regime in regimes:
        coverage.setdefault(regime, 0)
    selected.sort(key=lambda row: (regimes.index(row["regime"]), row["fold"], row["segment_id"]))
    return selected, coverage


def inspect_replay_candidate(root: Path, entry: dict[str, Any], names: set[str]) -> dict[str, Any] | None:
    repo_path = safe_repo_path(str(entry.get("path") or ""))
    path = root / repo_path
    digest = sha256_file(path)
    if digest is None or digest != entry.get("sha256"):
        return None
    text = read_text(path)
    found: set[str] = set()
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.lower() in names:
                    found.add(node.name)
        except SyntaxError:
            return None
    else:
        lower = text.lower()
        found = {name for name in names if re.search(rf"\b{name}\b", lower)}
    if not found:
        return None
    return {"path": repo_path, "sha256": digest, "entrypoints": sorted(found), "score": len(found)}


def inspect_token_candidate(root: Path, entry: dict[str, Any], tokens: list[str]) -> dict[str, Any] | None:
    repo_path = safe_repo_path(str(entry.get("path") or ""))
    path = root / repo_path
    digest = sha256_file(path)
    if digest is None or digest != entry.get("sha256"):
        return None
    lower = read_text(path).lower()
    found = sorted({token for token in tokens if token in lower})
    if not found:
        return None
    numeric_mentions: dict[str, list[float]] = {}
    for token in found:
        values = []
        for match in re.finditer(rf"{re.escape(token)}[^\n]{{0,80}}?(-?\d+(?:\.\d+)?)", lower):
            try:
                values.append(float(match.group(1)))
            except ValueError:
                pass
        numeric_mentions[token] = sorted(set(values))[:8]
    return {
        "path": repo_path,
        "sha256": digest,
        "tokens": found,
        "numeric_mentions": numeric_mentions,
        "score": len(found) + sum(bool(values) for values in numeric_mentions.values()),
    }


def axis_coverage(rows: list[dict[str, Any]]) -> dict[str, bool]:
    tokens = {token for row in rows for token in row.get("tokens", [])}
    return {
        "fee": bool(tokens & {"fee", "commission"}),
        "slippage": "slippage" in tokens,
        "latency": "latency" in tokens,
        "funding": "funding" in tokens,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    prior_status = load_json(root / str(contract["prior_status_path"]))
    prior_lineage = load_json(root / str(contract["prior_lineage_path"]))
    frozen = load_json(root / str(contract["frozen_manifest_path"]))
    registry = load_json(root / str(contract["registry_path"]))
    blockers: list[str] = []

    if not prior_gate(prior_status, expected):
        blockers.append("PRIOR_A4B_STATUS_INVALID")
    if prior_lineage.get("state") != "PASS" or prior_lineage.get("dry_run_input_set_id") != prior_status.get("dry_run_input_set_id"):
        blockers.append("A4B_LINEAGE_MISMATCH")
    if frozen.get("state") != "PASS" or frozen.get("input_set_id") != prior_status.get("prior_input_set_id"):
        blockers.append("A4_FROZEN_MANIFEST_MISMATCH")

    strategy_ids = sorted(str(row.get("strategy_id") or "") for row in registry.get("entries", []) if isinstance(row, dict))
    if len(strategy_ids) != expected or len(set(strategy_ids)) != expected or any(not item for item in strategy_ids):
        blockers.append("STRATEGY_REGISTRY_INVALID")

    canonical_inputs = [row for row in prior_lineage.get("canonical_inputs", []) if isinstance(row, dict)]
    canonical_paths = [root / safe_repo_path(str(row.get("path") or "")) for row in canonical_inputs]
    protected_paths = [Path(str(item)) for item in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)

    category_inputs = frozen.get("category_inputs") if isinstance(frozen.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    replay_entries = [row for row in category_inputs.get("replay_harness", []) if isinstance(row, dict)]
    cost_entries = [row for row in category_inputs.get("execution_cost", []) if isinstance(row, dict)]
    regime_entries = [row for row in category_inputs.get("regime_context", []) if isinstance(row, dict)]

    all_segments, rejected_market = build_segments(root, market_entries, contract)
    regimes = [str(item) for item in contract.get("required_regimes", [])]
    folds = int(contract.get("folds_per_regime", 6))
    selected_segments, regime_coverage = select_regime_segments(all_segments, regimes, folds)
    expected_segments = int(contract.get("expected_historical_segment_count", len(regimes) * folds))
    if len(selected_segments) != expected_segments or any(regime_coverage.get(regime) != folds for regime in regimes):
        blockers.append("HISTORICAL_REGIME_FOLD_COVERAGE_INCOMPLETE")

    replay_names = {str(item).lower() for item in contract.get("replay_entrypoint_names", [])}
    replay_candidates = [candidate for entry in replay_entries if (candidate := inspect_replay_candidate(root, entry, replay_names))]
    replay_candidates.sort(key=lambda row: (-row["score"], row["path"]))
    selected_replay = replay_candidates[: int(contract.get("maximum_replay_harness_count", 3))]
    if not selected_replay:
        blockers.append("REPLAY_HARNESS_NOT_RESOLVED")

    cost_tokens = [str(item).lower() for item in contract.get("cost_tokens", [])]
    cost_candidates = [candidate for entry in cost_entries if (candidate := inspect_token_candidate(root, entry, cost_tokens))]
    cost_candidates.sort(key=lambda row: (-row["score"], row["path"]))
    selected_cost = cost_candidates[: int(contract.get("maximum_cost_source_count", 6))]
    cost_axes = axis_coverage(selected_cost)
    if not all(cost_axes.values()):
        blockers.append("EXECUTION_COST_AXIS_COVERAGE_INCOMPLETE")

    regime_tokens = [str(item).lower() for item in contract.get("regime_tokens", [])]
    regime_candidates = [candidate for entry in regime_entries if (candidate := inspect_token_candidate(root, entry, regime_tokens))]
    regime_candidates.sort(key=lambda row: (-row["score"], row["path"]))
    selected_regime_sources = regime_candidates[: int(contract.get("maximum_regime_source_count", 4))]
    if not selected_regime_sources:
        blockers.append("REGIME_CONTEXT_SOURCE_NOT_RESOLVED")

    cost_profiles = [f"cost_profile_{index}" for index in range(int(contract.get("cost_profile_count", 3)))]
    perturbations = [f"perturbation_{index}" for index in range(int(contract.get("perturbation_count", 2)))]
    scenario_rows: list[dict[str, Any]] = []
    for strategy_id in strategy_ids:
        for segment in selected_segments:
            for cost_profile in cost_profiles:
                for perturbation in perturbations:
                    scenario_rows.append({
                        "scenario_id": sha256_bytes(
                            f"{strategy_id}:{segment['segment_id']}:{cost_profile}:{perturbation}".encode()
                        )[:24],
                        "strategy_id": strategy_id,
                        "segment_id": segment["segment_id"],
                        "regime": segment["regime"],
                        "fold": segment["fold"],
                        "cost_profile": cost_profile,
                        "perturbation": perturbation,
                    })
    expected_runs = int(contract.get("expected_scenario_run_count", 3600))
    if len(scenario_rows) != expected_runs or len({row["scenario_id"] for row in scenario_rows}) != expected_runs:
        blockers.append(f"SCENARIO_PLAN_COUNT_INVALID:{len(scenario_rows)}")

    after = snapshot(canonical_paths + protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    canonical_set = {str(path) for path in canonical_paths}
    protected_set = {str(path) for path in protected_paths}
    canonical_mutation_count = sum(1 for path in mutation_paths if path in canonical_set)
    protected_change_count = sum(1 for path in mutation_paths if path in protected_set)
    if mutation_paths:
        blockers.append("READ_ONLY_MUTATION_DETECTED")

    source_paths = sorted({row["source_path"] for row in selected_segments})
    lineage_payload = {
        "prior_dry_run_input_set_id": prior_status.get("dry_run_input_set_id"),
        "frozen_input_set_id": frozen.get("input_set_id"),
        "target_commit": args.target_sha,
        "strategy_ids": strategy_ids,
        "segments": selected_segments,
        "replay_harnesses": selected_replay,
        "cost_sources": selected_cost,
        "regime_sources": selected_regime_sources,
        "cost_profiles": cost_profiles,
        "perturbations": perturbations,
    }
    lineage_id = sha256_bytes(json.dumps(lineage_payload, sort_keys=True, separators=(",", ":")).encode())
    all_blockers = list(dict.fromkeys(blockers))
    success = bool(
        not all_blockers
        and len(strategy_ids) == expected
        and len(selected_segments) == expected_segments
        and len(selected_replay) >= 1
        and all(cost_axes.values())
        and len(selected_regime_sources) >= 1
        and len(scenario_rows) == expected_runs
        and canonical_mutation_count == 0
        and protected_change_count == 0
        and int(registry.get("active_entry_count", -1)) == 0
    )
    state = "PASS" if success else "HOLD"
    next_stage = str(contract["next_stage_pass"] if success else contract["next_stage_fail"])

    selected_manifest = {
        "schema": "r7a4c_selected_historical_input_manifest_v1",
        "official_stage": "R7.A4C",
        "state": state,
        "lineage_id": lineage_id,
        "target_commit": args.target_sha,
        "prior_dry_run_input_set_id": prior_status.get("dry_run_input_set_id"),
        "frozen_input_set_id": frozen.get("input_set_id"),
        "selected_market_source_paths": source_paths,
        "selected_segments": selected_segments,
        "regime_coverage": regime_coverage,
        "selected_replay_harnesses": selected_replay,
        "selected_cost_sources": selected_cost,
        "execution_cost_axis_coverage": cost_axes,
        "selected_regime_sources": selected_regime_sources,
        "rejected_market_sources": rejected_market,
        "simulation_execution_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
    }
    scenario_plan = {
        "schema": "r7a4c_historical_scenario_plan_3600_v1",
        "official_stage": "R7.A4C",
        "state": state,
        "lineage_id": lineage_id,
        "dimensions": {
            "strategy_count": len(strategy_ids),
            "regime_count": len(regimes),
            "folds_per_regime": folds,
            "cost_profile_count": len(cost_profiles),
            "perturbation_count": len(perturbations),
            "expected_scenario_run_count": expected_runs,
        },
        "cost_profiles": cost_profiles,
        "perturbations": perturbations,
        "scenarios": scenario_rows,
        "historical_simulation_executed": False,
    }
    proof = {
        "schema": "r7a4c_historical_simulation_input_lineage_proof_v1",
        "official_stage": "R7.A4C",
        "state": state,
        "lineage_id": lineage_id,
        "mutation_paths": mutation_paths,
        "blockers": all_blockers,
    }
    status = {
        "official_stage": "R7.A4C",
        "state": state,
        "blocker_count": len(all_blockers),
        "blockers": all_blockers,
        "strategy_count": len(strategy_ids),
        "market_candidate_count": len(market_entries),
        "market_usable_source_count": len({row["source_path"] for row in all_segments}),
        "market_selected_source_count": len(source_paths),
        "historical_segment_candidate_count": len(all_segments),
        "historical_segment_selected_count": len(selected_segments),
        "regime_coverage_count": sum(1 for regime in regimes if regime_coverage.get(regime) == folds),
        "trend_up_fold_count": regime_coverage.get("trend_up", 0),
        "range_fold_count": regime_coverage.get("range", 0),
        "trend_down_fold_count": regime_coverage.get("trend_down", 0),
        "shock_recovery_fold_count": regime_coverage.get("shock_recovery", 0),
        "replay_candidate_count": len(replay_entries),
        "replay_harness_resolved_count": len(selected_replay),
        "execution_cost_candidate_count": len(cost_entries),
        "execution_cost_source_selected_count": len(selected_cost),
        "execution_cost_axis_coverage_count": sum(cost_axes.values()),
        "regime_context_candidate_count": len(regime_entries),
        "regime_context_source_selected_count": len(selected_regime_sources),
        "scenario_plan_count": len(scenario_rows),
        "historical_simulation_execution_count": 0,
        "lineage_id": lineage_id,
        "active_entry_count": int(registry.get("active_entry_count", -1)),
        "canonical_mutation_count": canonical_mutation_count,
        "protected_change_count": protected_change_count,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "paper_live_order_count": 0,
        "next_stage": next_stage,
        "selected_manifest_path": str(root / str(contract["selected_manifest_path"])),
        "scenario_plan_path": str(root / str(contract["scenario_plan_path"])),
        "proof_path": str(root / str(contract["proof_path"])),
    }

    atomic_json(root / str(contract["selected_manifest_path"]), selected_manifest)
    atomic_json(root / str(contract["scenario_plan_path"]), scenario_plan)
    atomic_json(root / str(contract["proof_path"]), proof)
    atomic_json(root / str(contract["status_path"]), status)

    for key in (
        "state", "blocker_count", "strategy_count", "market_candidate_count",
        "market_usable_source_count", "market_selected_source_count",
        "historical_segment_candidate_count", "historical_segment_selected_count",
        "regime_coverage_count", "trend_up_fold_count", "range_fold_count",
        "trend_down_fold_count", "shock_recovery_fold_count", "replay_candidate_count",
        "replay_harness_resolved_count", "execution_cost_candidate_count",
        "execution_cost_source_selected_count", "execution_cost_axis_coverage_count",
        "regime_context_candidate_count", "regime_context_source_selected_count",
        "scenario_plan_count", "historical_simulation_execution_count", "lineage_id",
        "active_entry_count", "canonical_mutation_count", "protected_change_count",
        "router_mutation_count", "service_mutation_count", "paper_live_order_count",
        "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("REGIME_COVERAGE=" + json.dumps(regime_coverage, ensure_ascii=False, sort_keys=True))
    print("COST_AXIS_COVERAGE=" + json.dumps(cost_axes, ensure_ascii=False, sort_keys=True))
    print("BLOCKERS=" + json.dumps(all_blockers, ensure_ascii=False))
    print("SELECTED_MANIFEST_JSON=" + status["selected_manifest_path"])
    print("SCENARIO_PLAN_JSON=" + status["scenario_plan_path"])
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + ("0" if success else "2"))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
