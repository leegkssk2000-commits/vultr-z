"""Read-only native opportunity funnel for the frozen Scalp7 30m parents.

This diagnostic replays the unchanged parent implementations on the already-used
245-day DEV source.  It emits counts and hashes only; it never exports candles,
changes a strategy rule, or opens fresh/OOS evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild import scalp7_source_data_v2 as source


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "research/campaigns/scalp7_20260915/broad_rebuild_v2"
COST_PATH = ROOT / (
    "research/campaigns/scalp7_20260915/cost_snapshot_v2/"
    "SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
)
START = 1768262400000
END = 1789430400000
DAY = 86_400_000
EXPECTED_INVENTORY = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
EXPECTED = {
    positive.KELTNER_PARENT: {
        "ledger_sha256": "8863caa8231282fbd7dfd5660811b74e007c018c9cdafdaa52c24830cddfd989",
        "rolling_T": 109,
        "lane": "KELTNER_HG_30M",
    },
    positive.SQUEEZE_PARENT: {
        "ledger_sha256": "5f1af277aefb4e0887d723ef7a59311385551abf500cd4308693f9cbf6000e52",
        "rolling_T": 25,
        "lane": "SQUEEZE_PANIC_30M",
    },
}
KELTNER_CHILD = "scalp7_keltner_hg_entry_accepted_episode_utc30m_v1"
KELTNER_CHILD_CONTRACT = ROOT / (
    "research/campaigns/scalp7_20261012/dual_frequency_v1/"
    "KELTNER_ENTRY_ACCEPTED_EPISODE_STATE_CHILD_V1.json"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).date().isoformat()


def _daily_summary(timestamps: list[int]) -> dict[str, Any]:
    days = [_day(START + i * DAY) for i in range((END - START) // DAY)]
    counts = Counter(_day(value) for value in timestamps if START <= value < END)
    values = [int(counts.get(day, 0)) for day in days]
    return {
        "calendar_days": len(days),
        "total": sum(values),
        "days_with_event": sum(value > 0 for value in values),
        "zero_days": sum(value == 0 for value in values),
        "mean_per_calendar_day": sum(values) / len(values),
        "median_per_calendar_day": float(np.median(values)),
        "days_ge_3": sum(value >= 3 for value in values),
        "days_ge_4": sum(value >= 4 for value in values),
        "histogram": {str(key): value for key, value in sorted(Counter(values).items())},
        "counts": dict(zip(days, values)),
    }


def _signal_id(identity: str, symbol: str, signal_ts: int, signal_open_ts: int) -> str:
    value = f"{identity}|{symbol}|{signal_ts}|{signal_open_ts}".encode()
    return hashlib.sha256(value).hexdigest()


def _state(state: positive.HolyGrailState) -> dict[str, Any]:
    return {
        "side": int(state.side),
        "episode_traded": bool(state.episode_traded),
        "stage": int(state.stage),
        "pull_low": float(state.pull_low) if math.isfinite(state.pull_low) else None,
        "pull_high": float(state.pull_high) if math.isfinite(state.pull_high) else None,
    }


def _hg_release_reason(
    before: Mapping[str, Any], after: Mapping[str, Any], row: Mapping[str, Any]
) -> str | None:
    if not before["episode_traded"] or after["episode_traded"]:
        return None
    values = [float(row[f"g{n}"]) for n in positive.LONG_GMMA]
    long = all(a > z for a, z in zip(values, values[1:]))
    short = all(a < z for a, z in zip(values, values[1:]))
    side = 1 if long else -1 if short else 0
    renewed = (
        float(row["high"]) > float(row["hi20"])
        if side == 1
        else float(row["low"]) < float(row["lo20"])
        if side == -1
        else False
    )
    if renewed and int(before["side"]) == side and int(after["side"]) == side:
        return "RENEWED_BREAKOUT_REARM"
    return "WEAK_OR_SIDE_RESET"


def _native_stage_events(
    frames: Mapping[str, pd.DataFrame], identity: str
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    stages: dict[str, list[dict[str, Any]]] = {
        "raw_setup": [],
        "source_condition": [],
        "regime_eligible": [],
    }
    observations: list[dict[str, Any]] = []
    releases: list[dict[str, Any]] = []
    for symbol, frame in sorted(frames.items()):
        for segment in positive.enriched_segments(frame):
            rows = segment.to_dict("records")
            if identity == positive.KELTNER_PARENT:
                state = positive.HolyGrailState()
                for i in range(1, len(rows)):
                    row, previous = rows[i], rows[i - 1]
                    before = _state(state)
                    event = positive._hg_event(state, row, previous) if i >= 121 else None
                    after = _state(state)
                    released = _hg_release_reason(before, after, row)
                    if released:
                        releases.append(
                            {
                                "symbol": symbol,
                                "segment_id": str(row["segment_id"]),
                                "release_ts_ms": int(row["feature_available_ts_ms"]),
                                "release_open_ts_ms": int(row["open_ts_ms"]),
                                "reason": released,
                            }
                        )
                    if not event:
                        continue
                    stamp = int(max(row["feature_available_ts_ms"], row.get("regime_available_ts_ms", 0)))
                    opened = int(row["open_ts_ms"])
                    regime, regime_available = positive._regime(row, None)
                    record = {
                        "symbol": symbol,
                        "signal_ts_ms": stamp,
                        "signal_open_ts_ms": opened,
                    }
                    stages["raw_setup"].append(record)
                    stages["source_condition"].append(record)
                    eligible = regime in {"PANIC_DISPERSION", "TREND_DISPERSED"}
                    if eligible:
                        stages["regime_eligible"].append(record)
                    observations.append(
                        {
                            "signal_id": _signal_id(identity, symbol, stamp, opened),
                            "strategy_id": identity,
                            "lane": "KELTNER_HG_30M",
                            "utc_day": _day(stamp),
                            "symbol": symbol,
                            "signal_open_ts_ms": opened,
                            "feature_available_ts_ms": int(row["feature_available_ts_ms"]),
                            "regime_available_ts_ms": int(regime_available),
                            "signal_ts_ms": stamp,
                            "segment_id": str(row["segment_id"]),
                            "warmup_ok": i >= 121,
                            "raw_setup": True,
                            "source_condition": True,
                            "source_condition_components": {"hg_turn_event": True},
                            "regime": regime,
                            "regime_eligible": eligible,
                            "episode_before": before,
                            "episode_after": after,
                        }
                    )
            else:
                for i in range(1, len(rows)):
                    row, previous = rows[i], rows[i - 1]
                    first_fire = i >= 80 and bool(previous["squeeze_on"]) and not bool(row["squeeze_on"])
                    if not first_fire:
                        continue
                    stamp = int(max(row["feature_available_ts_ms"], row.get("regime_available_ts_ms", 0)))
                    opened = int(row["open_ts_ms"])
                    record = {"symbol": symbol, "signal_ts_ms": stamp, "signal_open_ts_ms": opened}
                    stages["raw_setup"].append(record)
                    components = {
                        "momentum_finite": math.isfinite(float(row["momentum"])),
                        "momentum_positive": float(row["momentum"]) > 0,
                        "momentum_accelerating": float(row["momentum"]) > float(previous["momentum"]),
                        "close_above_g34": float(row["close"]) > float(row["g34"]),
                        "ma_stack_g8_gt_g21_gt_g34": float(row["g8"]) > float(row["g21"]) > float(row["g34"]),
                    }
                    conditioned = all(components.values())
                    regime, regime_available = positive._regime(row, None)
                    eligible = conditioned and regime == "PANIC_DISPERSION"
                    observations.append(
                        {
                            "signal_id": _signal_id(identity, symbol, stamp, opened),
                            "strategy_id": identity,
                            "lane": "SQUEEZE_PANIC_30M",
                            "utc_day": _day(stamp),
                            "symbol": symbol,
                            "signal_open_ts_ms": opened,
                            "feature_available_ts_ms": int(row["feature_available_ts_ms"]),
                            "regime_available_ts_ms": int(regime_available),
                            "signal_ts_ms": stamp,
                            "segment_id": str(row["segment_id"]),
                            "warmup_ok": i >= 80,
                            "raw_setup": True,
                            "source_condition": conditioned,
                            "source_condition_components": components,
                            "regime": regime,
                            "regime_eligible": eligible,
                            "episode_before": {"squeeze_on": bool(previous["squeeze_on"])},
                            "episode_after": {"squeeze_on": bool(row["squeeze_on"])},
                        }
                    )
                    if not conditioned:
                        continue
                    stages["source_condition"].append(record)
                    if regime == "PANIC_DISPERSION":
                        stages["regime_eligible"].append(record)
    return stages, observations, releases


def _entry_gate(
    signal: Mapping[str, Any], frames: Mapping[str, pd.DataFrame]
) -> tuple[bool, int | None, str]:
    frame = frames[str(signal["symbol"])]
    hits = frame.index[frame["open_ts_ms"] == int(signal["signal_open_ts_ms"])].tolist()
    if len(hits) != 1:
        return False, None, "SIGNAL_BAR_MISSING_OR_DUPLICATE"
    i = int(hits[0])
    if i + 1 >= len(frame):
        return False, None, "NO_NEXT_BAR"
    source_bar, entry_bar = frame.iloc[i], frame.iloc[i + 1]
    if (
        source_bar["segment_id"] != entry_bar["segment_id"]
        or int(entry_bar["open_ts_ms"]) != int(source_bar["close_ts_ms"])
    ):
        return False, None, "ENTRY_GAP"
    if int(signal["signal_ts_ms"]) > int(entry_bar["open_ts_ms"]):
        return False, None, "LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL"
    result = positive.entry_admission(signal, float(entry_bar["open"]))
    return bool(result["allowed"]), int(entry_bar["open_ts_ms"]), str(result["reason"])


def _key(row: Mapping[str, Any]) -> tuple[str, int, int]:
    return (
        str(row["symbol"]),
        int(row["signal_ts_ms"]),
        int(row["signal_open_ts_ms"]),
    )


def _source_rejection(record: Mapping[str, Any]) -> str | None:
    if not record["source_condition"]:
        ordered = (
            ("momentum_finite", "SOURCE_MOMENTUM_NONFINITE"),
            ("momentum_positive", "SOURCE_MOMENTUM_NOT_POSITIVE"),
            ("momentum_accelerating", "SOURCE_MOMENTUM_NOT_ACCELERATING"),
            ("close_above_g34", "SOURCE_CLOSE_NOT_ABOVE_G34"),
            ("ma_stack_g8_gt_g21_gt_g34", "SOURCE_MA_NOT_STACKED"),
        )
        values = record["source_condition_components"]
        for name, reason in ordered:
            if not values.get(name, False):
                return reason
        return "SOURCE_CONDITION_FAILED"
    if not record["regime_eligible"]:
        return "REGIME_NOT_ALLOWED:" + str(record["regime"])
    return None


def _bind_observation_outcomes(
    identity: str,
    observations: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    frames: Mapping[str, pd.DataFrame],
    rows: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rolling = [row for row in observations if START <= int(row["signal_ts_ms"]) < END]
    by_key = {_key(row): row for row in rolling}
    signal_by_key = {
        _key(row): row for row in signals if START <= int(row["signal_ts_ms"]) < END
    }
    completed_keys = {
        _key(row) for row in rows if row.get("partition") == "rolling"
    }
    accepted_keys = set(completed_keys)
    for row in unresolved:
        signal = row.get("position", {}).get("signal", {})
        if signal and START <= int(signal["signal_ts_ms"]) < END:
            accepted_keys.add(_key(signal))
    releases_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in releases:
        releases_by_symbol.setdefault(str(row["symbol"]), []).append(row)
    for values in releases_by_symbol.values():
        values.sort(key=lambda row: int(row["release_ts_ms"]))
    for key, record in by_key.items():
        signal = signal_by_key.get(key)
        record["signal_generated"] = signal is not None
        record["fill_clock_eligible"] = False
        record["cost_admitted"] = False
        record["entry_ts_ms"] = None
        record["occupancy_accepted"] = key in accepted_keys
        record["modeled_next_open_fill"] = key in accepted_keys
        record["completed_trade"] = key in completed_keys
        record["first_rejection"] = _source_rejection(record)
        if signal is not None:
            allowed, entry_ts, reason = _entry_gate(signal, frames)
            record["fill_clock_eligible"] = entry_ts is not None
            record["cost_admitted"] = allowed
            record["entry_ts_ms"] = entry_ts
            gate = signal["meta"]["entry_cost_gate"]
            record["cost_gate_min_ratio"] = float(gate["min_ratio"])
            record["frozen_cost_bps"] = float(signal["meta"]["frozen_cost_bps"])
            if entry_ts is not None:
                entry_rows = frames[str(signal["symbol"])].loc[
                    frames[str(signal["symbol"])]["open_ts_ms"] == entry_ts,
                    "open",
                ]
                if len(entry_rows) != 1:
                    raise ValueError("OBSERVATION_ENTRY_PRICE_BINDING_FAILED")
                entry_price = float(entry_rows.iloc[0])
                record["entry_atr_cost_ratio"] = (
                    float(gate["atr_price"])
                    / entry_price
                    * 10_000
                    / float(signal["meta"]["frozen_cost_bps"])
                )
            if not allowed:
                record["first_rejection"] = reason
            elif key not in accepted_keys:
                record["first_rejection"] = "POSITION_ALREADY_OWNED"
            else:
                record["first_rejection"] = None
        if identity == positive.KELTNER_PARENT:
            consumed = bool(record["episode_after"]["episode_traded"]) and key not in accepted_keys
            record["episode_consumed_without_entry"] = consumed
            if consumed:
                release = next(
                    (
                        item
                        for item in releases_by_symbol.get(str(record["symbol"]), [])
                        if str(item["segment_id"]) == str(record["segment_id"])
                        and int(item["release_ts_ms"]) > int(record["signal_ts_ms"])
                    ),
                    None,
                )
                record["episode_release"] = release
                record["episode_release_delay_bars"] = (
                    None
                    if release is None
                    else (
                        int(release["release_open_ts_ms"])
                        - int(record["signal_open_ts_ms"])
                    )
                    // positive.TIMEFRAME_MS
                )
    first_rejections = Counter(
        str(row["first_rejection"])
        for row in rolling
        if row["first_rejection"] is not None
    )
    source_regimes = Counter(
        str(row["regime"]) for row in rolling if row["source_condition"]
    )
    summary: dict[str, Any] = {
        "observation_count": len(rolling),
        "first_rejections": dict(sorted(first_rejections.items())),
        "source_conditioned_by_regime": dict(sorted(source_regimes.items())),
        "generated_signal_count": sum(row["signal_generated"] for row in rolling),
        "cost_admitted_count": sum(row["cost_admitted"] for row in rolling),
        "occupancy_accepted_count": sum(row["occupancy_accepted"] for row in rolling),
        "completed_trade_count": sum(row["completed_trade"] for row in rolling),
        "execution_first_rejections": dict(
            sorted(
                Counter(
                    str(row["first_rejection"])
                    for row in rolling
                    if row["signal_generated"] and row["first_rejection"] is not None
                ).items()
            )
        ),
    }
    if identity == positive.KELTNER_PARENT:
        consumed = [row for row in rolling if row["episode_consumed_without_entry"]]
        summary["episode_consumed_without_entry_count"] = len(consumed)
        summary["episode_consumed_without_entry_by_rejection"] = dict(
            sorted(Counter(str(row["first_rejection"]) for row in consumed).items())
        )
        summary["episode_release_reason"] = dict(
            sorted(
                Counter(
                    "UNRELEASED_IN_OBSERVED_SOURCE"
                    if row.get("episode_release") is None
                    else str(row["episode_release"]["reason"])
                    for row in consumed
                ).items()
            )
        )
    return rolling, summary


def _load_saved(identity: str) -> tuple[Path, dict[str, Any]]:
    path = REPORT / "results" / (identity + ".trades.json.gz")
    expected = EXPECTED[identity]["ledger_sha256"]
    if _sha(path) != expected:
        raise ValueError("PARENT_LEDGER_SHA_MISMATCH:" + identity)
    with gzip.open(path, "rt") as handle:
        return path, json.load(handle)


def _replay_parent(
    identity: str,
    frames: dict[str, pd.DataFrame],
    costs: Mapping[str, float],
    windows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str], list[int]]:
    all_rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    accepted_entry_ts: list[int] = []
    for window in windows:
        start, end = int(window["start_ms"]), int(window["end_ms"])
        chosen = [row for row in signals if start <= int(row["signal_ts_ms"]) < end]
        prefix_start = start - 200 * 30 * 60_000
        sliced = {
            symbol: frame[(frame["open_ts_ms"] >= prefix_start) & (frame["close_ts_ms"] <= end)].reset_index(drop=True)
            for symbol, frame in frames.items()
        }
        out = execution.replay(
            chosen,
            sliced,
            costs,
            identity=identity,
            exit_update=positive.exit_update,
            entry_update=positive.entry_update,
        )
        for row in out["trades"]:
            row["window_label"] = window["label"]
            row["partition"] = window["partition"]
            accepted_entry_ts.append(int(row["entry_ts_ms"]))
        for position in out["unresolved"]:
            position["window_label"] = window["label"]
            position["window_end_ms"] = end
            accepted_entry_ts.append(int(position["entry_ts_ms"]))
        all_rows.extend(out["trades"])
        unresolved.extend(out["unresolved"])
        if window["partition"] == "rolling":
            rejections.update(out["rejections"])
    return all_rows, unresolved, rejections, accepted_entry_ts


def _keltner_parent_signal(
    symbol: str,
    row: Mapping[str, Any],
    side: int,
    reference: float,
    regime: str,
    regime_available: int,
    cost: float,
) -> dict[str, Any]:
    """Reproduce the frozen parent signal exactly for the one-axis adapter."""
    stamp = max(int(row["feature_available_ts_ms"]), int(regime_available))
    return {
        "symbol": symbol,
        "timeframe_min": positive.TIMEFRAME_MIN,
        "signal_open_ts_ms": int(row["open_ts_ms"]),
        "signal_ts_ms": stamp,
        "segment_id": row["segment_id"],
        "take_profit_r": None,
        # The common engine must see the parent identity so the exact frozen
        # entry/exit callbacks remain byte-for-byte unchanged.  Result rows are
        # relabelled only after execution as the separately frozen child.
        "identity": positive.KELTNER_PARENT,
        "lane": "keltner_holygrail",
        "side": int(side),
        "stop_price": float(reference) - int(side) * 0.10 * float(row["atr"]),
        "invalidation_price": float(reference),
        "max_hold_bars": 25,
        "exit_policy": "KELTNER_HG_FEE_BE_PARTIAL_RUNNER",
        "partial_take_profit_r": 2.0,
        "partial_fraction": 0.10,
        "meta": {
            "spec_sha256": positive.SPEC_SHA256,
            "regime": regime,
            "feature_available_ts_ms": stamp,
            "frozen_cost_bps": float(cost),
            "historical_parity_claim": False,
            "atr_price": float(row["atr"]),
            "entry_cost_gate": {"atr_price": float(row["atr"]), "min_ratio": 4.5},
            "fallback_stop_atr_mult": 1.2,
            "be_arm_r": 1.0,
            "event_trace": [
                "HG_GMMA",
                "FIRST_OR_RENEWED_EPISODE",
                "20EMA_PULLBACK",
                "TURN_TRIGGER",
            ],
        },
    }


def _relabel_child(value: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(value))
    out["identity"] = KELTNER_CHILD
    signal = out.get("signal")
    if isinstance(signal, dict):
        signal["identity"] = KELTNER_CHILD
        signal.setdefault("meta", {})["lifecycle_adapter_parent_identity"] = (
            positive.KELTNER_PARENT
        )
    position = out.get("position")
    if isinstance(position, dict) and isinstance(position.get("signal"), dict):
        position["signal"]["identity"] = KELTNER_CHILD
        position["signal"].setdefault("meta", {})[
            "lifecycle_adapter_parent_identity"
        ] = positive.KELTNER_PARENT
    return out


def _accepted_episode_child(
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replay one frozen axis: consume an HG episode only after entry accepts.

    Signal state remains continuous across preregistered windows.  Execution
    ownership remains flat and independent per window, matching the parent
    campaign contract.  Before the first validation boundary the unchanged
    parent state machine is used only to warm continuous signal state.
    """
    first_start = min(int(window["start_ms"]) for window in windows)
    prepared: dict[tuple[str, str], tuple[pd.DataFrame, list[dict[str, Any]], dict[int, int]]] = {}
    for window in windows:
        start, end = int(window["start_ms"]), int(window["end_ms"])
        prefix_start = start - 200 * positive.TIMEFRAME_MS
        for symbol, frame in frames.items():
            sliced = frame[
                (frame["open_ts_ms"] >= prefix_start) & (frame["close_ts_ms"] <= end)
            ].reset_index(drop=True)
            records, index = execution._frame_records(sliced, positive.TIMEFRAME_MIN)
            prepared[(str(window["label"]), symbol)] = (sliced, records, index)
    rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    boundary_excluded: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    rejections_by_partition: dict[str, Counter[str]] = {
        "validation": Counter(),
        "rolling": Counter(),
    }
    candidate_count = 0
    admitted_count = 0
    candidate_count_by_partition: Counter[str] = Counter()
    admitted_count_by_partition: Counter[str] = Counter()
    ownership: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str, int]] = set()
    ordered_windows = sorted(windows, key=lambda item: int(item["start_ms"]))

    for symbol, frame in sorted(frames.items()):
        cost = float(costs.get(symbol, float("nan")))
        if not math.isfinite(cost) or cost <= 0:
            raise ValueError("KELTNER_CHILD_COST_UNBOUND:" + symbol)
        for segment in positive.enriched_segments(frame):
            source_rows = segment.to_dict("records")
            state = positive.HolyGrailState()
            for i in range(1, len(source_rows)):
                row, previous = source_rows[i], source_rows[i - 1]
                event = positive._hg_event(state, row, previous) if i >= 121 else None
                if not event:
                    continue
                regime, regime_available = positive._regime(row, None)
                stamp = max(
                    int(row["feature_available_ts_ms"]), int(regime_available)
                )
                # Preserve the exact parent warm state before evaluation.  From
                # the first validation boundary onward only accepted modeled
                # entries may consume the episode.
                if stamp < first_start:
                    continue
                state.episode_traded = False
                window = next(
                    (
                        item
                        for item in ordered_windows
                        if int(item["start_ms"]) <= stamp < int(item["end_ms"])
                    ),
                    None,
                )
                if window is None:
                    continue
                partition = str(window["partition"])
                if regime not in {"PANIC_DISPERSION", "TREND_DISPERSED"}:
                    reason = "REGIME_NOT_ALLOWED:" + str(regime)
                    rejections[reason] += 1
                    rejections_by_partition[partition][reason] += 1
                    continue
                candidate_count += 1
                candidate_count_by_partition[partition] += 1
                signal = _keltner_parent_signal(
                    symbol, row, int(event[0]), float(event[1]), regime,
                    int(regime_available), cost,
                )
                duplicate = (str(window["label"]), symbol, stamp)
                if duplicate in seen:
                    rejections["DUPLICATE_SIGNAL"] += 1
                    rejections_by_partition[partition]["DUPLICATE_SIGNAL"] += 1
                    continue
                seen.add(duplicate)
                owner = (str(window["label"]), symbol)
                if stamp < ownership.get(owner, -1):
                    rejections["POSITION_ALREADY_OWNED"] += 1
                    rejections_by_partition[partition]["POSITION_ALREADY_OWNED"] += 1
                    continue
                sliced, records, index = prepared[(str(window["label"]), symbol)]
                trade, open_position, until, reason = execution._single(
                    signal,
                    sliced,
                    records,
                    index,
                    cost,
                    positive.exit_update,
                    positive.entry_update,
                )
                if reason is not None:
                    rejections[str(reason)] += 1
                    rejections_by_partition[partition][str(reason)] += 1
                    continue
                admitted_count += 1
                admitted_count_by_partition[partition] += 1
                state.episode_traded = True
                ownership[owner] = int(until)
                if trade is not None:
                    child = _relabel_child(trade)
                    child["window_label"] = str(window["label"])
                    child["partition"] = partition
                    if int(child["outcome_available_ts_ms"]) >= int(window["end_ms"]):
                        child["boundary_exclusion_reason"] = (
                            "OUTCOME_AT_OR_AFTER_WINDOW_END_UNAVAILABLE"
                        )
                        child["window_end_ms"] = int(window["end_ms"])
                        boundary_excluded.append(child)
                    else:
                        rows.append(child)
                if open_position is not None:
                    child_open = _relabel_child(open_position)
                    child_open["window_label"] = str(window["label"])
                    child_open["partition"] = partition
                    child_open["window_end_ms"] = int(window["end_ms"])
                    unresolved.append(child_open)
    rows.sort(
        key=lambda item: (
            int(item["outcome_available_ts_ms"]),
            str(item["identity"]),
            str(item["symbol"]),
        )
    )
    return {
        "trades": rows,
        "unresolved": unresolved,
        "boundary_excluded": boundary_excluded,
        "rejections": dict(sorted(rejections.items())),
        "rejections_by_partition": {
            name: dict(sorted(values.items()))
            for name, values in rejections_by_partition.items()
        },
        "candidate_count": candidate_count,
        "admitted_count": admitted_count,
        "candidate_count_by_partition": dict(candidate_count_by_partition),
        "admitted_count_by_partition": dict(admitted_count_by_partition),
    }


def _daily_economics(
    rows: list[dict[str, Any]], cost_multiplier: float
) -> dict[str, Any]:
    days = [_day(START + i * DAY) for i in range((END - START) // DAY)]
    entries = Counter(_day(int(row["entry_ts_ms"])) for row in rows)
    pnl: Counter[str] = Counter()
    for row in rows:
        pnl[_day(int(row["outcome_available_ts_ms"]))] += (
            float(row["gross_bps"])
            - float(row["cost_bps"]) * float(cost_multiplier)
        )
    values = [float(pnl.get(day, 0.0)) for day in days]
    losing_run = longest_losing_run = 0
    for value in values:
        losing_run = losing_run + 1 if value < 0 else 0
        longest_losing_run = max(longest_losing_run, losing_run)
    return {
        "basis": "realized_equal_notional_trade_bps_by_outcome_available_utc_day",
        "calendar_days": len(days),
        "entries_total": sum(entries.values()),
        "entries_per_calendar_day": sum(entries.values()) / len(days),
        "no_entry_days": sum(entries.get(day, 0) == 0 for day in days),
        "days_ge_3_entries": sum(entries.get(day, 0) >= 3 for day in days),
        "days_ge_4_entries": sum(entries.get(day, 0) >= 4 for day in days),
        "profit_days": sum(value > 0 for value in values),
        "loss_days": sum(value < 0 for value in values),
        "zero_realized_days": sum(value == 0 for value in values),
        "worst_day_bps": min(values),
        "max_consecutive_losing_days": longest_losing_run,
        "net_bps_per_calendar_day": sum(values) / len(days),
        "account_nav_or_mtm": None,
    }


def _opportunity_comparison(
    parent_rows: list[dict[str, Any]], child_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    def key(row: Mapping[str, Any]) -> tuple[str, int, int]:
        return (
            str(row["symbol"]),
            int(row["signal_ts_ms"]),
            int(row["signal_open_ts_ms"]),
        )

    parents, children = {key(row): row for row in parent_rows}, {
        key(row): row for row in child_rows
    }
    common = parents.keys() & children.keys()
    added = children.keys() - parents.keys()
    removed = parents.keys() - children.keys()

    def net(rows: list[dict[str, Any]], multiplier: float) -> float:
        return sum(
            float(row["gross_bps"]) - multiplier * float(row["cost_bps"])
            for row in rows
        )

    parent_positive = [row for row in parent_rows if float(row["net_bps"]) > 0]
    biggest = max(parent_positive, key=lambda row: float(row["net_bps"]), default=None)
    return {
        "common_T": len(common),
        "added_T": len(added),
        "removed_T": len(removed),
        "added_net_bps_cost1x": net([children[item] for item in added], 1.0),
        "added_net_bps_cost2x": net([children[item] for item in added], 2.0),
        "removed_parent_net_bps_cost1x": net([parents[item] for item in removed], 1.0),
        "removed_parent_net_bps_cost2x": net([parents[item] for item in removed], 2.0),
        "parent_positive_profit_retained_cost1x": (
            net([row for item, row in parents.items() if item in common and float(row["net_bps"]) > 0], 1.0)
            / net(parent_positive, 1.0)
            if net(parent_positive, 1.0) > 0
            else None
        ),
        "largest_parent_winner_retained": (
            key(biggest) in common if biggest is not None else None
        ),
    }


def run(source_root: Path, output: Path) -> dict[str, Any]:
    contract = json.loads((REPORT / "CAMPAIGN_PREREGISTERED_V2.json").read_text())
    child_contract = json.loads(KELTNER_CHILD_CONTRACT.read_text())
    windows = contract["windows"]
    frames = source.load_candles(source_root, 30, cache_dir=None)
    if set(frames) != {"BTC-USDT", "DOGE-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT"}:
        raise ValueError("SOURCE_COHORT_DRIFT")
    if {frame.attrs["source_inventory_sha256"] for frame in frames.values()} != {EXPECTED_INVENTORY}:
        raise ValueError("SOURCE_INVENTORY_SHA_MISMATCH")
    features = context.cross_features(frames)
    bound, fits = context.bind_context(frames, features, windows)
    costs = json.loads(COST_PATH.read_text())["costs_bps"]
    lanes: dict[str, Any] = {}
    for identity in EXPECTED:
        saved_path, saved = _load_saved(identity)
        signals = positive.generate_signals(bound, costs=costs, identities=(identity,))
        stage_events, observations, releases = _native_stage_events(bound, identity)
        expected_keys = Counter(
            (row["symbol"], int(row["signal_ts_ms"]), int(row["signal_open_ts_ms"]))
            for row in stage_events["regime_eligible"]
        )
        signal_keys = Counter(
            (row["symbol"], int(row["signal_ts_ms"]), int(row["signal_open_ts_ms"]))
            for row in signals
        )
        if signal_keys != expected_keys:
            raise ValueError("NATIVE_STAGE_SIGNAL_PARITY:" + identity)
        fill_clock_ts: list[int] = []
        cost_admitted_ts: list[int] = []
        preoccupancy_rejections: Counter[str] = Counter()
        for signal in signals:
            allowed, entry_ts, reason = _entry_gate(signal, bound)
            if entry_ts is not None:
                fill_clock_ts.append(entry_ts)
            if allowed and entry_ts is not None:
                cost_admitted_ts.append(entry_ts)
            elif START <= int(signal["signal_ts_ms"]) < END:
                preoccupancy_rejections[reason] += 1
        rows, unresolved, rejections, accepted_entry_ts = _replay_parent(
            identity, bound, costs, windows, signals
        )
        if rows != saved["trades"] or unresolved != saved["unresolved"]:
            raise ValueError("EXACT_PARENT_REPLAY_PARITY_FAILED:" + identity)
        rolling_rows = [row for row in rows if row["partition"] == "rolling"]
        if len(rolling_rows) != EXPECTED[identity]["rolling_T"]:
            raise ValueError("ROLLING_PARENT_T_PARITY_FAILED:" + identity)
        stages = {
            name: _daily_summary([int(row["signal_ts_ms"]) for row in values])
            for name, values in stage_events.items()
        }
        stages["fill_clock_eligible"] = _daily_summary(fill_clock_ts)
        stages["cost_admitted_preoccupancy"] = _daily_summary(cost_admitted_ts)
        stages["accepted_entry"] = _daily_summary(accepted_entry_ts)
        stages["completed_trade"] = _daily_summary(
            [int(row["entry_ts_ms"]) for row in rolling_rows]
        )
        rolling_signals = [row for row in signals if START <= int(row["signal_ts_ms"]) < END]
        same_time = Counter(int(row["signal_ts_ms"]) for row in rolling_signals)
        observation_records, observation_summary = _bind_observation_outcomes(
            identity,
            observations,
            releases,
            signals,
            bound,
            rows,
            unresolved,
        )
        if observation_summary["generated_signal_count"] != len(rolling_signals):
            raise ValueError("OBSERVATION_SIGNAL_COUNT_PARITY_FAILED:" + identity)
        if observation_summary["completed_trade_count"] != len(rolling_rows):
            raise ValueError("OBSERVATION_TRADE_COUNT_PARITY_FAILED:" + identity)
        if observation_summary["execution_first_rejections"] != dict(sorted(rejections.items())):
            raise ValueError("OBSERVATION_EXECUTION_REJECTION_PARITY_FAILED:" + identity)
        lanes[identity] = {
            "lane": EXPECTED[identity]["lane"],
            "parent_ledger_path": str(saved_path.relative_to(ROOT)),
            "parent_ledger_sha256": EXPECTED[identity]["ledger_sha256"],
            "rolling_T_exact": len(rolling_rows),
            "exact_generated_signal_parity": True,
            "exact_saved_trade_and_unresolved_parity": True,
            "exact_gross_cost_net_pnl_parity": True,
            "stages": stages,
            "preoccupancy_rejections": dict(sorted(preoccupancy_rejections.items())),
            "execution_rejections": dict(sorted(rejections.items())),
            "same_signal_time_multi_symbol_groups": sum(value > 1 for value in same_time.values()),
            "max_same_signal_time_count": max(same_time.values(), default=0),
            "observation_summary": observation_summary,
            "observation_records": observation_records,
        }
    if child_contract["child_identity"] != KELTNER_CHILD:
        raise ValueError("KELTNER_CHILD_CONTRACT_IDENTITY_MISMATCH")
    child = _accepted_episode_child(bound, costs, windows)
    parent_signals = positive.generate_signals(
        bound, costs=costs, identities=(positive.KELTNER_PARENT,)
    )
    parent_trade_rows, _, _, _ = _replay_parent(
        positive.KELTNER_PARENT, bound, costs, windows, parent_signals
    )
    parent_trade_rows = [
        row for row in parent_trade_rows if row["partition"] == "rolling"
    ]
    child_trade_rows = [
        row for row in child["trades"] if row["partition"] == "rolling"
    ]
    child_unresolved = [
        row for row in child["unresolved"] if row["partition"] == "rolling"
    ]
    child_boundary_excluded = [
        row for row in child["boundary_excluded"] if row["partition"] == "rolling"
    ]
    parent_metrics = {
        "cost1x": metrics.summarize(parent_trade_rows, START, END, 1.0),
        "cost2x": metrics.summarize(parent_trade_rows, START, END, 2.0),
        "daily_cost1x": _daily_economics(parent_trade_rows, 1.0),
        "daily_cost2x": _daily_economics(parent_trade_rows, 2.0),
    }
    child_metrics = {
        "cost1x": metrics.summarize(child_trade_rows, START, END, 1.0),
        "cost2x": metrics.summarize(child_trade_rows, START, END, 2.0),
        "daily_cost1x": _daily_economics(child_trade_rows, 1.0),
        "daily_cost2x": _daily_economics(child_trade_rows, 2.0),
    }
    child_result = {
        "state": "USED_DEV_COSTED_SINGLE_AXIS_RESULT_NOT_FRESH_NOT_SURVIVOR",
        "contract_path": str(KELTNER_CHILD_CONTRACT.relative_to(ROOT)),
        "contract_sha256": _sha(KELTNER_CHILD_CONTRACT),
        "parent_identity": positive.KELTNER_PARENT,
        "child_identity": KELTNER_CHILD,
        "parent_lifecycle_adapter": True,
        "parent_lifecycle_adapter_scope": (
            "internal callback identity only; output remains separate child"
        ),
        "candidate_count": child["candidate_count_by_partition"].get("rolling", 0),
        "admitted_count": child["admitted_count_by_partition"].get("rolling", 0),
        "rejections": child["rejections_by_partition"].get("rolling", {}),
        "unresolved_count": len(child_unresolved),
        "boundary_excluded_count": len(child_boundary_excluded),
        "partition_census": {
            name: {
                "candidate_count": child["candidate_count_by_partition"].get(name, 0),
                "admitted_count": child["admitted_count_by_partition"].get(name, 0),
                "rejections": child["rejections_by_partition"].get(name, {}),
                "completed_trade_count": sum(
                    row["partition"] == name for row in child["trades"]
                ),
                "unresolved_count": sum(
                    row["partition"] == name for row in child["unresolved"]
                ),
                "boundary_excluded_count": sum(
                    row["partition"] == name for row in child["boundary_excluded"]
                ),
            }
            for name in ("validation", "rolling")
        },
        "parent": parent_metrics,
        "child": child_metrics,
        "opportunity_comparison": _opportunity_comparison(
            parent_trade_rows, child_trade_rows
        ),
        "trade_rows": child_trade_rows,
        "unresolved": child_unresolved,
        "boundary_excluded": child_boundary_excluded,
        "promotion": False,
        "survivor_count_delta": 0,
    }
    report = {
        "schema": "zel.scalp7.dual_native_observer_and_keltner_child.v3",
        "state": "PARENT_PARITY_AND_KELTNER_SINGLE_AXIS_COSTED_RESULT_COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "used_dev_only": True,
        "fresh_or_oos": False,
        "economic_improvement": None,
        "source_root": str(source_root),
        "source_inventory_sha256": EXPECTED_INVENTORY,
        "window": {"start_ms": START, "end_exclusive_ms": END, "calendar_days": 245, "timeframe_min": 30},
        "context_fit_sha256": hashlib.sha256(json.dumps(fits, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "lanes": lanes,
        "keltner_single_axis_result": child_result,
        "raw_price_bodies_exported": False,
        "market_requests": 0,
        "economic_runs": 1,
        "observer_changes_parent_state": False,
        "order_live_paper_deploy": "BLOCKED_UNSURE_HOLD",
    }
    unsigned = (json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    report["receipt_sha256"] = hashlib.sha256(unsigned).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.source_root, args.output)
    print("NATIVE_DAILY_FUNNEL_RECEIPT=" + result["receipt_sha256"])
    for identity, row in result["lanes"].items():
        print(identity, json.dumps({name: value["total"] for name, value in row["stages"].items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
