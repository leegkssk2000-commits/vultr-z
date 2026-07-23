#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

DEFECT2_SUMMARY = Path("runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_summary_v1.json")
DEFECT2_TRADES = Path("runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_trade_rows_v1.jsonl")
DEFECT2_CELLS = Path("runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_cell_rows_v1.jsonl")
SECOND_SUMMARY = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json")
SECOND_TRADES = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_incremental_defect3_consecutive_loss_causality_audit")

ATR5 = "dual_atr_volatility_bot:5m"
ATR15 = "dual_atr_volatility_bot:15m"
MA5 = "dual_ma_trend_bot:5m"
ACTIVE_LANES = (ATR5, ATR15, MA5)
DISCOVERY_FOLDS = {0, 1, 2}
VALIDATION_FOLDS = {3, 4, 5}
BASE_CELL = ("cost_profile_0", "timing_0")
ADVERSE_CELL = ("cost_profile_1", "timing_1")
SEVERE_CELL = ("cost_profile_2", "timing_1")
PROFILE_CELLS = {
    "base": BASE_CELL,
    "adverse": ADVERSE_CELL,
    "severe": SEVERE_CELL,
}
MIN_STREAK_LENGTH = 2
STRUCTURAL_MIN_STREAK = 3
STRUCTURAL_MIN_TOTAL_LOSSES = 4
MIN_REMAINING_TRADES = 24
MIN_REMAINING_SYMBOLS = 3
PERMUTATIONS = 1000
MAX_ACTIVE_REPAIR_LANES = 3

CAUSE_TO_REPAIR = {
    "REENTRY_CHURN": "MATCHED_CLUSTER_COOLDOWN",
    "COST_EROSION": "MATCHED_CLUSTER_EXECUTION_COST_DEFENSE",
    "NO_FAVORABLE_EXCURSION": "MATCHED_CLUSTER_ENTRY_VETO",
    "EXIT_CAPTURE_FAILURE": "MATCHED_CLUSTER_MFE_LOCK_EXIT",
    "FAST_STOP_VOLATILITY": "MATCHED_CLUSTER_POST_SHOCK_COOLDOWN",
    "TIMEOUT_DRIFT": "MATCHED_CLUSTER_TIMEOUT_EXIT_REDESIGN",
    "MIXED_LOSS_MECHANISM": "READ_ONLY_SUBCLUSTER_REQUIRED",
}

def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value

def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            rows.append(value)
    return rows

def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def snapshot(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path): sha256_file(path) for path in paths}

def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default

def lane_map(summary: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in summary.get(key) or []:
        if not isinstance(row, dict):
            continue
        lane = str(row.get("lane_id") or row.get("source_lane_id") or "")
        if lane:
            output[lane] = row
    return output

def cell_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("cost_profile_id") or ""), str(row.get("timing_id") or "")

def row_lane(row: dict[str, Any]) -> str:
    return str(row.get("lane_id") or row.get("source_lane_id") or "")

def row_variant(row: dict[str, Any]) -> str:
    return str(row.get("control_variant_id") or row.get("variant_id") or "")

def current_lane_sources(
    defect2_summary: dict[str, Any],
    defect2_trades: list[dict[str, Any]],
    second_summary: dict[str, Any],
    second_trades: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    defect_rows = lane_map(defect2_summary, "lane_result_rows")
    second_rows = lane_map(second_summary, "lane_best_rows")
    passed = {str(value) for value in defect2_summary.get("incremental_pass_lane_ids") or []}
    failed = {str(value) for value in defect2_summary.get("failed_lane_ids") or []}
    metadata: dict[str, dict[str, Any]] = {}
    trades_by_lane: dict[str, list[dict[str, Any]]] = {}

    for lane in ACTIVE_LANES:
        if lane in passed:
            row = defect_rows[lane]
            variant = str(row.get("control_variant_id") or "")
            source_rows = [
                dict(trade)
                for trade in defect2_trades
                if row_lane(trade) == lane and row_variant(trade) == variant
            ]
            status = "ROBUST_PARENT" if bool(row.get("robust_survivor_pass")) else "INCREMENTAL_PARENT"
            metadata[lane] = {
                "lane_id": lane,
                "authoritative_source": "DEFECT2",
                "authoritative_variant_id": variant,
                "authoritative_status": status,
                "execution_timeframe": str(
                    (row.get("base_metrics") or {}).get("execution_timeframe")
                    or row.get("execution_timeframe")
                    or lane.rsplit(":", 1)[-1]
                ),
                "robust_survivor_pass": bool(row.get("robust_survivor_pass")),
            }
            trades_by_lane[lane] = source_rows
        elif lane in failed:
            row = second_rows[lane]
            variant = str(row.get("variant_id") or "")
            source_rows = [
                {
                    **dict(trade),
                    "lane_id": lane,
                    "control_variant_id": variant,
                }
                for trade in second_trades
                if row_lane(trade) == lane and row_variant(trade) == variant
            ]
            metadata[lane] = {
                "lane_id": lane,
                "authoritative_source": "SECOND_WAVE_ROLLBACK_CONTROL",
                "authoritative_variant_id": variant,
                "authoritative_status": "FAILED_CHILD_ROLLED_BACK",
                "execution_timeframe": str(
                    row.get("execution_timeframe")
                    or row.get("timeframe")
                    or lane.rsplit(":", 1)[-1]
                ),
                "robust_survivor_pass": False,
            }
            trades_by_lane[lane] = source_rows
        else:
            raise ValueError(f"ACTIVE_LANE_STATUS_UNRESOLVED:{lane}")
    return metadata, trades_by_lane

def enrich_trade(
    row: dict[str, Any],
    frame: pd.DataFrame,
    timeframe: str,
) -> dict[str, Any]:
    output = dict(row)
    entry_index = int(row.get("entry_index") if row.get("entry_index") is not None else -1)
    exit_index = int(row.get("exit_index") if row.get("exit_index") is not None else -1)
    if not (0 <= entry_index < len(frame) and entry_index <= exit_index < len(frame)):
        raise ValueError(
            f"TRADE_INDEX_INVALID:{row_lane(row)}:{row.get('segment_id')}:{entry_index}:{exit_index}:{len(frame)}"
        )
    entry = finite(row.get("entry_price"), math.nan)
    risk_pct = finite(row.get("risk_pct"), math.nan)
    side = str(row.get("side") or "")
    path = frame.iloc[entry_index : exit_index + 1]
    highs = path["high"].astype(float)
    lows = path["low"].astype(float)
    if side == "long":
        mfe_pct = max(finite(highs.max(), entry) - entry, 0.0) / entry * 100.0
        mae_pct = max(entry - finite(lows.min(), entry), 0.0) / entry * 100.0
        mfe_offset = int(highs.to_numpy().argmax())
        mae_offset = int(lows.to_numpy().argmin())
    elif side == "short":
        mfe_pct = max(entry - finite(lows.min(), entry), 0.0) / entry * 100.0
        mae_pct = max(finite(highs.max(), entry) - entry, 0.0) / entry * 100.0
        mfe_offset = int(lows.to_numpy().argmin())
        mae_offset = int(highs.to_numpy().argmax())
    else:
        raise ValueError(f"SIDE_INVALID:{side}")

    post_end = min(exit_index + 4, len(frame))
    post = frame.iloc[exit_index:post_end]
    if side == "long":
        post_favorable_pct = max(finite(post["high"].max(), entry) - entry, 0.0) / entry * 100.0
    else:
        post_favorable_pct = max(entry - finite(post["low"].min(), entry), 0.0) / entry * 100.0

    net_pct = finite(row.get("net_return_pct"))
    gross_pct = finite(row.get("gross_return_pct"))
    cost_pct = finite(row.get("round_trip_cost_pct")) + finite(row.get("funding_cost_pct"))
    mfe_r = mfe_pct / risk_pct if math.isfinite(risk_pct) and risk_pct > 0 else 0.0
    mae_r = mae_pct / risk_pct if math.isfinite(risk_pct) and risk_pct > 0 else 0.0
    output.update(
        {
            "entry_timestamp": finite(frame.iloc[entry_index]["__timestamp"]),
            "exit_timestamp": finite(frame.iloc[exit_index]["__timestamp"]),
            "entry_source_index": int(frame.iloc[entry_index].get("__first_source_index") or 0),
            "exit_source_index": int(frame.iloc[exit_index].get("__last_source_index") or 0),
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "bars_to_mfe": mfe_offset,
            "bars_to_mae": mae_offset,
            "post_exit_3bar_favorable_pct": post_favorable_pct,
            "total_cost_pct": cost_pct,
            "is_loss": net_pct < 0.0,
            "timeframe": timeframe,
        }
    )
    if net_pct >= 0:
        output["loss_mechanism"] = "NON_LOSS"
    elif gross_pct > 0 and net_pct < 0:
        output["loss_mechanism"] = "COST_EROSION"
    elif mfe_r < 0.25:
        output["loss_mechanism"] = "NO_FAVORABLE_EXCURSION"
    elif mfe_r >= 0.75:
        output["loss_mechanism"] = "EXIT_CAPTURE_FAILURE"
    elif str(row.get("exit_reason") or "") == "stop" and int(row.get("holding_bars") or 0) <= 2 and mae_r >= 0.80:
        output["loss_mechanism"] = "FAST_STOP_VOLATILITY"
    elif str(row.get("exit_reason") or "") == "rule_exit_or_timeout":
        output["loss_mechanism"] = "TIMEOUT_DRIFT"
    else:
        output["loss_mechanism"] = "MIXED_LOSS_MECHANISM"
    return output

def build_enriched_rows(
    root: Path,
    raw: Any,
    manifest: dict[str, Any],
    metadata: dict[str, dict[str, Any]],
    trades_by_lane: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[Path]]:
    segments = {
        str(row["segment_id"]): row
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict)
    }
    source_sha = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict)
    }
    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    source_paths = sorted({str(row["source_path"]) for row in segments.values()})
    protected_sources = [root / raw.safe_repo_path(path) for path in source_paths]
    enriched: list[dict[str, Any]] = []

    for lane in ACTIVE_LANES:
        timeframe = str(metadata[lane]["execution_timeframe"])
        for row in trades_by_lane[lane]:
            segment_id = str(row.get("segment_id") or "")
            if segment_id not in segments:
                raise ValueError(f"SEGMENT_MISSING:{segment_id}")
            segment = segments[segment_id]
            source_path = str(segment["source_path"])
            if source_path not in source_cache:
                source_cache[source_path] = raw.fixed_ohlcv_frame(
                    root / raw.safe_repo_path(source_path), source_sha[source_path]
                )
            key = (segment_id, timeframe)
            if key not in frame_cache:
                frame_cache[key] = raw.resample_for_segment(
                    source_cache[source_path],
                    int(segment["start_row"]),
                    int(segment["end_row_exclusive"]),
                    timeframe,
                )
            enriched_row = enrich_trade(row, frame_cache[key], timeframe)
            enriched_row.update(
                {
                    "lane_id": lane,
                    "authoritative_source": metadata[lane]["authoritative_source"],
                    "authoritative_variant_id": metadata[lane]["authoritative_variant_id"],
                    "source_path": source_path,
                    "fold_group": (
                        "discovery"
                        if int(row.get("fold") if row.get("fold") is not None else -1) in DISCOVERY_FOLDS
                        else "validation"
                    ),
                }
            )
            enriched.append(enriched_row)
    return enriched, protected_sources

def profile_name(row: dict[str, Any]) -> str | None:
    key = cell_key(row)
    for name, expected in PROFILE_CELLS.items():
        if key == expected:
            return name
    return None

def ordered_groups(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, int], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        profile = profile_name(row)
        if profile is None:
            continue
        key = (
            str(row["lane_id"]),
            profile,
            str(row.get("symbol") or ""),
            int(row.get("fold") if row.get("fold") is not None else -1),
        )
        groups[key].append(row)
    for key in groups:
        groups[key].sort(
            key=lambda row: (
                finite(row.get("entry_timestamp")),
                str(row.get("segment_id") or ""),
                int(row.get("entry_index") or 0),
            )
        )
    return groups

def annotate_reentry_churn(groups: dict[tuple[str, str, str, int], list[dict[str, Any]]]) -> None:
    for sequence in groups.values():
        previous: dict[str, Any] | None = None
        for row in sequence:
            if previous is None:
                row["gap_from_previous_exit_bars"] = None
            else:
                gap_source = int(row.get("entry_source_index") or 0) - int(previous.get("exit_source_index") or 0)
                factor = {"5m": 5, "15m": 15}.get(str(row.get("timeframe") or ""), 1)
                gap_bars = gap_source / max(factor, 1)
                row["gap_from_previous_exit_bars"] = gap_bars
                if (
                    bool(previous.get("is_loss"))
                    and bool(row.get("is_loss"))
                    and 0.0 <= gap_bars <= 3.0
                    and str(previous.get("side") or "") == str(row.get("side") or "")
                    and str(previous.get("signal_reason") or "") == str(row.get("signal_reason") or "")
                ):
                    row["loss_mechanism"] = "REENTRY_CHURN"
            previous = row

def loss_streaks(
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for (lane, profile, symbol, fold), sequence in groups.items():
        current: list[dict[str, Any]] = []
        for row in sequence + [{"is_loss": False}]:
            if bool(row.get("is_loss")):
                current.append(row)
                continue
            if len(current) >= MIN_STREAK_LENGTH:
                mechanisms = Counter(str(item.get("loss_mechanism") or "UNKNOWN") for item in current)
                dominant, count = mechanisms.most_common(1)[0]
                if count / len(current) < 0.50:
                    dominant = "MIXED_LOSS_MECHANISM"
                regimes = Counter(str(item.get("regime") or "UNKNOWN") for item in current)
                sides = Counter(str(item.get("side") or "UNKNOWN") for item in current)
                reasons = Counter(str(item.get("signal_reason") or "UNKNOWN") for item in current)
                exits = Counter(str(item.get("exit_reason") or "UNKNOWN") for item in current)
                events.append(
                    {
                        "lane_id": lane,
                        "profile": profile,
                        "symbol": symbol,
                        "fold": fold,
                        "fold_group": "discovery" if fold in DISCOVERY_FOLDS else "validation",
                        "streak_length": len(current),
                        "streak_net_pnl_pct": sum(finite(item.get("net_return_pct")) for item in current),
                        "streak_net_r": sum(finite(item.get("net_r")) for item in current),
                        "median_mfe_r": sorted(finite(item.get("mfe_r")) for item in current)[len(current)//2],
                        "median_mae_r": sorted(finite(item.get("mae_r")) for item in current)[len(current)//2],
                        "dominant_loss_mechanism": dominant,
                        "dominant_regime": regimes.most_common(1)[0][0],
                        "dominant_side": sides.most_common(1)[0][0],
                        "dominant_signal_reason": reasons.most_common(1)[0][0],
                        "dominant_exit_reason": exits.most_common(1)[0][0],
                        "start_entry_timestamp": finite(current[0].get("entry_timestamp")),
                        "end_exit_timestamp": finite(current[-1].get("exit_timestamp")),
                        "trade_loci": [
                            {
                                "segment_id": item.get("segment_id"),
                                "entry_index": item.get("entry_index"),
                                "exit_index": item.get("exit_index"),
                                "net_return_pct": item.get("net_return_pct"),
                                "mfe_r": item.get("mfe_r"),
                                "mae_r": item.get("mae_r"),
                                "loss_mechanism": item.get("loss_mechanism"),
                            }
                            for item in current
                        ],
                    }
                )
            current = []
    return events

def maximum_streak(sequence: list[bool]) -> int:
    best = 0
    current = 0
    for value in sequence:
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best

def permutation_pvalue(
    lane: str,
    profile: str,
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]],
) -> float:
    sequences = [
        [bool(row.get("is_loss")) for row in sequence]
        for (group_lane, group_profile, _, _), sequence in groups.items()
        if group_lane == lane and group_profile == profile and sequence
    ]
    observed = max((maximum_streak(sequence) for sequence in sequences), default=0)
    if observed < MIN_STREAK_LENGTH:
        return 1.0
    seed_bytes = hashlib.sha256(f"{lane}:{profile}".encode("utf-8")).digest()[:8]
    rng = random.Random(int.from_bytes(seed_bytes, "big"))
    exceed = 0
    for _ in range(PERMUTATIONS):
        simulated_max = 0
        for sequence in sequences:
            shuffled = list(sequence)
            rng.shuffle(shuffled)
            simulated_max = max(simulated_max, maximum_streak(shuffled))
        if simulated_max >= observed:
            exceed += 1
    return (exceed + 1) / (PERMUTATIONS + 1)

def conditional_loss_metrics(
    lane: str,
    profile: str,
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    total = 0
    losses = 0
    prior_loss_opportunities = 0
    loss_after_loss = 0
    for (group_lane, group_profile, _, _), sequence in groups.items():
        if group_lane != lane or group_profile != profile:
            continue
        flags = [bool(row.get("is_loss")) for row in sequence]
        total += len(flags)
        losses += sum(flags)
        for previous, current in zip(flags, flags[1:]):
            if previous:
                prior_loss_opportunities += 1
                if current:
                    loss_after_loss += 1
    loss_rate = losses / total if total else 0.0
    conditional = loss_after_loss / prior_loss_opportunities if prior_loss_opportunities else 0.0
    return {
        "trade_count": total,
        "loss_count": losses,
        "loss_rate": loss_rate,
        "prior_loss_opportunity_count": prior_loss_opportunities,
        "loss_after_loss_count": loss_after_loss,
        "conditional_loss_after_loss_rate": conditional,
        "streak_excess_rate": conditional - loss_rate,
    }

def structural_patterns(
    events: list[dict[str, Any]],
    enriched_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        key = (
            str(event["lane_id"]),
            str(event["profile"]),
            str(event["dominant_loss_mechanism"]),
            str(event["dominant_regime"]),
            str(event["dominant_side"]),
            str(event["dominant_signal_reason"]),
        )
        buckets[key].append(event)

    patterns: list[dict[str, Any]] = []
    for key, bucket in buckets.items():
        lane, profile, mechanism, regime, side, reason = key
        discovery = [event for event in bucket if event["fold_group"] == "discovery"]
        validation = [event for event in bucket if event["fold_group"] == "validation"]
        total_losses = sum(int(event["streak_length"]) for event in bucket)
        max_streak = max(int(event["streak_length"]) for event in bucket)
        discovery_pnl = sum(finite(event["streak_net_pnl_pct"]) for event in discovery)
        validation_pnl = sum(finite(event["streak_net_pnl_pct"]) for event in validation)
        preentry_cluster_rows = [
            row
            for row in enriched_rows
            if str(row.get("lane_id") or "") == lane
            and profile_name(row) == profile
            and str(row.get("regime") or "UNKNOWN") == regime
            and str(row.get("side") or "UNKNOWN") == side
            and str(row.get("signal_reason") or "UNKNOWN") == reason
        ]
        all_profile_rows = [
            row
            for row in enriched_rows
            if str(row.get("lane_id") or "") == lane and profile_name(row) == profile
        ]
        remaining = [row for row in all_profile_rows if row not in preentry_cluster_rows]
        remaining_symbols = {str(row.get("symbol") or "") for row in remaining}
        persistent = (
            bool(discovery)
            and bool(validation)
            and discovery_pnl < 0
            and validation_pnl < 0
            and total_losses >= STRUCTURAL_MIN_TOTAL_LOSSES
            and max_streak >= STRUCTURAL_MIN_STREAK
        )
        executable = (
            persistent
            and len(remaining) >= MIN_REMAINING_TRADES
            and len(remaining_symbols) >= MIN_REMAINING_SYMBOLS
            and mechanism != "MIXED_LOSS_MECHANISM"
        )
        score = (
            -discovery_pnl
            -validation_pnl
            + 0.25 * total_losses
            + 0.50 * max_streak
        )
        patterns.append(
            {
                "lane_id": lane,
                "profile": profile,
                "loss_mechanism": mechanism,
                "cluster": {
                    "axes": ["regime", "side", "signal_reason"],
                    "values": [regime, side, reason],
                },
                "streak_event_count": len(bucket),
                "discovery_streak_count": len(discovery),
                "validation_streak_count": len(validation),
                "total_streak_loss_count": total_losses,
                "maximum_streak_length": max_streak,
                "discovery_streak_pnl_pct": discovery_pnl,
                "validation_streak_pnl_pct": validation_pnl,
                "cluster_trade_count": len(preentry_cluster_rows),
                "remaining_trade_count": len(remaining),
                "remaining_symbol_count": len(remaining_symbols),
                "persistent_across_split": persistent,
                "repair_executable": executable,
                "proposed_repair_mode": CAUSE_TO_REPAIR.get(mechanism, "READ_ONLY_SUBCLUSTER_REQUIRED"),
                "score": score,
            }
        )
    patterns.sort(
        key=lambda row: (
            bool(row["repair_executable"]),
            bool(row["persistent_across_split"]),
            finite(row["score"]),
        ),
        reverse=True,
    )
    return patterns

def select_repair_rows(
    metadata: dict[str, dict[str, Any]],
    lane_audits: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    audit_map = {str(row["lane_id"]): row for row in lane_audits}
    candidates: list[dict[str, Any]] = []
    for pattern in patterns:
        if not bool(pattern.get("repair_executable")):
            continue
        lane = str(pattern["lane_id"])
        if lane == ATR5 and str(pattern["profile"]) != "severe":
            continue
        if lane == ATR15 and str(pattern["profile"]) not in {"adverse", "severe"}:
            continue
        row = {
            "lane_id": lane,
            "authoritative_variant_id": metadata[lane]["authoritative_variant_id"],
            "authoritative_source": metadata[lane]["authoritative_source"],
            "parent_status": metadata[lane]["authoritative_status"],
            "execution_timeframe": metadata[lane]["execution_timeframe"],
            "target_profile": pattern["profile"],
            "single_defect": "PERSISTENT_CONSECUTIVE_LOSS_PATTERN",
            "loss_mechanism": pattern["loss_mechanism"],
            "cluster": pattern["cluster"],
            "proposed_repair_mode": pattern["proposed_repair_mode"],
            "maximum_streak_length": pattern["maximum_streak_length"],
            "discovery_streak_pnl_pct": pattern["discovery_streak_pnl_pct"],
            "validation_streak_pnl_pct": pattern["validation_streak_pnl_pct"],
            "remaining_trade_count": pattern["remaining_trade_count"],
            "remaining_symbol_count": pattern["remaining_symbol_count"],
            "streak_surprise_pvalue": audit_map[lane]["profiles"][pattern["profile"]]["streak_surprise_pvalue"],
            "parent_immutable": True,
            "child_only": True,
            "baseline_non_degrade_required": True,
            "discovery_validation_persistence_required": True,
            "same_frozen_data_and_costs_required": True,
            "no_stop_widening": True,
            "no_entry_threshold_relaxation": True,
            "selection_score": finite(pattern["score"]),
        }
        candidates.append(row)

    candidates.sort(
        key=lambda row: (
            int(row["lane_id"] == ATR15),
            int(row["lane_id"] == MA5),
            int(row["lane_id"] == ATR5),
            finite(row["selection_score"]),
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    used_lanes: set[str] = set()
    for row in candidates:
        lane = str(row["lane_id"])
        if lane in used_lanes:
            continue
        selected.append(row)
        used_lanes.add(lane)
        if len(selected) >= MAX_ACTIVE_REPAIR_LANES:
            break
    return selected

def self_test() -> int:
    rows: list[dict[str, Any]] = []
    for fold in range(6):
        for index, net in enumerate([0.5, -0.7, -0.8, -0.6, 0.4]):
            rows.append(
                {
                    "lane_id": ATR15,
                    "cost_profile_id": SEVERE_CELL[0],
                    "timing_id": SEVERE_CELL[1],
                    "symbol": "BTC",
                    "fold": fold,
                    "net_return_pct": net,
                    "net_r": net,
                    "is_loss": net < 0,
                    "loss_mechanism": "NO_FAVORABLE_EXCURSION" if net < 0 else "NON_LOSS",
                    "regime": "shock_recovery",
                    "side": "long",
                    "signal_reason": "atr_volume_up_break",
                    "exit_reason": "stop",
                    "mfe_r": 0.1,
                    "mae_r": 1.0,
                    "entry_timestamp": fold * 100 + index,
                    "exit_timestamp": fold * 100 + index + 1,
                    "segment_id": f"s{fold}",
                    "entry_index": index,
                    "exit_index": index + 1,
                }
            )
    for fold in range(6):
        for index in range(5):
            rows.append(
                {
                    "lane_id": ATR15,
                    "cost_profile_id": SEVERE_CELL[0],
                    "timing_id": SEVERE_CELL[1],
                    "symbol": ["ETH", "SOL", "XRP"][fold % 3],
                    "fold": fold,
                    "net_return_pct": 0.3,
                    "net_r": 0.3,
                    "is_loss": False,
                    "loss_mechanism": "NON_LOSS",
                    "regime": "trend_up",
                    "side": "long",
                    "signal_reason": "atr_volume_up_break",
                    "exit_reason": "take_profit",
                    "mfe_r": 1.0,
                    "mae_r": 0.2,
                    "entry_timestamp": fold * 100 + 20 + index,
                    "exit_timestamp": fold * 100 + 21 + index,
                    "segment_id": f"g{fold}",
                    "entry_index": 20 + index,
                    "exit_index": 21 + index,
                }
            )
    groups = ordered_groups(rows)
    events = loss_streaks(groups)
    patterns = structural_patterns(events, rows)
    assert len(events) == 6
    assert patterns and patterns[0]["persistent_across_split"]
    assert patterns[0]["repair_executable"]
    metrics = conditional_loss_metrics(ATR15, "severe", groups)
    assert metrics["conditional_loss_after_loss_rate"] > metrics["loss_rate"]
    print("STATE=PASS_INCREMENTAL_DEFECT3_CONSECUTIVE_LOSS_CAUSALITY_AUDIT_SELF_TEST")
    print("RC=0")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--raw-module")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.raw_module:
        raise SystemExit("RAW_MODULE_REQUIRED")

    root = Path(args.root).resolve()
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_defect3_raw")
    required = [
        root / DEFECT2_SUMMARY,
        root / DEFECT2_TRADES,
        root / DEFECT2_CELLS,
        root / SECOND_SUMMARY,
        root / SECOND_TRADES,
        root / MANIFEST_PATH,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_INCREMENTAL_DEFECT3_CONSECUTIVE_LOSS_CAUSALITY_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    defect2_summary = load_json(root / DEFECT2_SUMMARY)
    second_summary = load_json(root / SECOND_SUMMARY)
    manifest = load_json(root / MANIFEST_PATH)
    blockers: list[str] = []
    if defect2_summary.get("state") != "PASS_INCREMENTAL_DEFECT2_EXECUTION":
        blockers.append("DEFECT2_SUMMARY_NOT_PASS")
    if int(defect2_summary.get("incremental_pass_lane_count") or 0) != 2:
        blockers.append("DEFECT2_PASS_COUNT_CHANGED")
    if set(defect2_summary.get("incremental_pass_lane_ids") or []) != {ATR5, ATR15}:
        blockers.append("DEFECT2_PASS_LANES_CHANGED")
    if set(defect2_summary.get("robust_survivor_lane_ids") or []) != {ATR5}:
        blockers.append("ROBUST_PARENT_CHANGED")
    if set(defect2_summary.get("failed_lane_ids") or []) != {MA5}:
        blockers.append("FAILED_LANE_CHANGED")
    if not bool(defect2_summary.get("atr5_control_preserved")):
        blockers.append("ATR5_CONTROL_NOT_PRESERVED")
    if not bool(defect2_summary.get("donchian15_reference_preserved")):
        blockers.append("DONCHIAN15_REFERENCE_NOT_PRESERVED")
    if not bool(defect2_summary.get("keep14_untouched")):
        blockers.append("KEEP14_NOT_PRESERVED")
    if second_summary.get("state") != "PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132":
        blockers.append("SECOND_WAVE_SUMMARY_NOT_PASS")
    if blockers:
        print("STATE=HOLD_INCREMENTAL_DEFECT3_CONSECUTIVE_LOSS_CAUSALITY_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    before = snapshot(required)
    defect2_trades = load_jsonl(root / DEFECT2_TRADES)
    second_trades = load_jsonl(root / SECOND_TRADES)
    metadata, trades_by_lane = current_lane_sources(
        defect2_summary, defect2_trades, second_summary, second_trades
    )
    enriched, source_paths = build_enriched_rows(
        root, raw, manifest, metadata, trades_by_lane
    )
    source_before = snapshot(source_paths)
    groups = ordered_groups(enriched)
    annotate_reentry_churn(groups)
    events = loss_streaks(groups)
    patterns = structural_patterns(events, enriched)

    lane_audits: list[dict[str, Any]] = []
    for lane in ACTIVE_LANES:
        profile_rows: dict[str, dict[str, Any]] = {}
        for profile in PROFILE_CELLS:
            lane_profile = [
                row
                for row in enriched
                if str(row.get("lane_id") or "") == lane and profile_name(row) == profile
            ]
            streak_events = [
                event
                for event in events
                if event["lane_id"] == lane and event["profile"] == profile
            ]
            metrics = conditional_loss_metrics(lane, profile, groups)
            profile_rows[profile] = {
                **metrics,
                "maximum_loss_streak": max(
                    (int(event["streak_length"]) for event in streak_events), default=0
                ),
                "loss_streak_event_count": len(streak_events),
                "loss_streak_trade_count": sum(
                    int(event["streak_length"]) for event in streak_events
                ),
                "loss_streak_net_pnl_pct": sum(
                    finite(event["streak_net_pnl_pct"]) for event in streak_events
                ),
                "streak_surprise_pvalue": permutation_pvalue(lane, profile, groups),
                "loss_mechanism_histogram": dict(
                    sorted(
                        Counter(
                            str(row.get("loss_mechanism") or "UNKNOWN")
                            for row in lane_profile
                            if bool(row.get("is_loss"))
                        ).items()
                    )
                ),
                "streak_events": streak_events,
            }
        lane_patterns = [row for row in patterns if row["lane_id"] == lane]
        lane_audits.append(
            {
                **metadata[lane],
                "profiles": profile_rows,
                "structural_pattern_count": sum(
                    bool(row["persistent_across_split"]) for row in lane_patterns
                ),
                "executable_repair_pattern_count": sum(
                    bool(row["repair_executable"]) for row in lane_patterns
                ),
                "structural_patterns": lane_patterns,
                "preserve_parent_without_change": (
                    lane == ATR5
                    and not any(
                        bool(row["repair_executable"]) and row["profile"] == "severe"
                        for row in lane_patterns
                    )
                ),
            }
        )

    selected = select_repair_rows(metadata, lane_audits, patterns)
    expected_cells = len(selected) * 6
    next_stage = (
        f"R7.A4D2_INCREMENTAL_DEFECT3_SINGLE_CAUSE_EXECUTION_{expected_cells}"
        if selected
        else "R7.A4D2_CURRENT_PARENT_PRESERVE_AND_DATA_EXPANSION"
    )
    summary = {
        "state": "PASS_INCREMENTAL_DEFECT3_CONSECUTIVE_LOSS_CAUSALITY_AUDIT",
        "target_sha": args.target_sha,
        "active_lane_count": len(ACTIVE_LANES),
        "active_lane_ids": list(ACTIVE_LANES),
        "trade_row_count": len(enriched),
        "loss_streak_event_count": len(events),
        "structural_streak_pattern_count": sum(
            bool(row["persistent_across_split"]) for row in patterns
        ),
        "repair_executable_pattern_count": sum(
            bool(row["repair_executable"]) for row in patterns
        ),
        "selected_repair_lane_count": len(selected),
        "selected_repair_lane_ids": [row["lane_id"] for row in selected],
        "expected_defect3_cell_count": expected_cells,
        "atr5_robust_parent_preserved": True,
        "atr15_incremental_parent_preserved": True,
        "ma5_failed_child_rejected": True,
        "ma5_second_wave_control_restored": True,
        "donchian15_reference_preserved": True,
        "keep14_untouched": True,
        "loss_streak_is_not_repair_evidence_without_split_persistence": True,
        "lane_audit_rows": lane_audits,
        "structural_pattern_rows": patterns,
        "defect3_repair_rows": selected,
        "mutation_rows": [],
        "next_stage": next_stage,
    }
    output = root / OUTPUT_DIR
    atomic_json(output / "incremental_defect3_consecutive_loss_causality_audit_v1.json", summary)

    after = snapshot(required)
    source_after = snapshot(source_paths)
    mutations = [
        path for path in before if before[path] != after.get(path)
    ] + [
        path for path in source_before if source_before[path] != source_after.get(path)
    ]
    if mutations:
        print("STATE=HOLD_INCREMENTAL_DEFECT3_CONSECUTIVE_LOSS_CAUSALITY_AUDIT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps([f"INPUT_MUTATIONS:{len(mutations)}"]))
        print("RC=2")
        return 2

    print("STATE=PASS_INCREMENTAL_DEFECT3_CONSECUTIVE_LOSS_CAUSALITY_AUDIT")
    print("BLOCKER_COUNT=0")
    print("ACTIVE_LANE_COUNT=" + str(len(ACTIVE_LANES)))
    print("ACTIVE_LANE_IDS=" + json.dumps(list(ACTIVE_LANES)))
    print("TRADE_ROW_COUNT=" + str(len(enriched)))
    print("LOSS_STREAK_EVENT_COUNT=" + str(len(events)))
    print(
        "STRUCTURAL_STREAK_PATTERN_COUNT="
        + str(summary["structural_streak_pattern_count"])
    )
    print(
        "REPAIR_EXECUTABLE_PATTERN_COUNT="
        + str(summary["repair_executable_pattern_count"])
    )
    print("SELECTED_REPAIR_LANE_COUNT=" + str(len(selected)))
    print("SELECTED_REPAIR_LANE_IDS=" + json.dumps(summary["selected_repair_lane_ids"]))
    print("EXPECTED_DEFECT3_CELL_COUNT=" + str(expected_cells))
    print("ATR5_ROBUST_PARENT_PRESERVED=true")
    print("ATR15_INCREMENTAL_PARENT_PRESERVED=true")
    print("MA5_FAILED_CHILD_REJECTED=true")
    print("MA5_SECOND_WAVE_CONTROL_RESTORED=true")
    print("DONCHIAN15_REFERENCE_PRESERVED=true")
    print("KEEP14_UNTOUCHED=true")
    print("LANE_AUDIT_ROWS=" + json.dumps(lane_audits, sort_keys=True))
    print("DEFECT3_REPAIR_ROWS=" + json.dumps(selected, sort_keys=True))
    print(
        "AUDIT_JSON="
        + str(output / "incremental_defect3_consecutive_loss_causality_audit_v1.json")
    )
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
