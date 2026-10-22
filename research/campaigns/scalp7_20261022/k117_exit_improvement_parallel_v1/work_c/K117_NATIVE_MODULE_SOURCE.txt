"""Native used-DEV comparison for the preregistered Keltner fresh-touch successor.

This is a research-only adapter around the frozen Scalp7 30m callbacks.  It does
not mutate the parent implementation, export price bodies, or open fresh/OOS.
The previously rejected child is read from its receipt-bound saved artifact and
is never replayed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping

import pandas as pd

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild import scalp7_source_data_v2 as source
from ops import scalp7_dual_native_funnel_v1 as native
from research.campaigns.scalp7_20261013.dual_streak_v1.streak_successor_policies import (
    KELTNER_SUCCESSOR,
    RejectedHGEventReset,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / (
    "research/campaigns/scalp7_20261013/dual_streak_v1/"
    "KELTNER_FRESH_TOUCH_SUCCESSOR_V1.json"
)
EXPECTED_REJECTED_RECEIPT = (
    "a17e2d42d89875e5c215824c68c324aaf95d867e217a08c981fdcb0e76289137"
)
EXPECTED_REJECTED_CHILD = "scalp7_keltner_hg_entry_accepted_episode_utc30m_v1"
EXPECTED_REJECTED_T = 146
SYMBOLS = {"BTC-USDT", "DOGE-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("receipt_sha256", None)
    raw = (
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _load_rejected(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report = json.loads(path.read_text())
    if report.get("receipt_sha256") != EXPECTED_REJECTED_RECEIPT:
        raise ValueError("SAVED_REJECTED_RECEIPT_PIN_MISMATCH")
    if _receipt(report) != EXPECTED_REJECTED_RECEIPT:
        raise ValueError("SAVED_REJECTED_RECEIPT_RECOMPUTE_FAILED")
    if report.get("source_inventory_sha256") != native.EXPECTED_INVENTORY:
        raise ValueError("SAVED_REJECTED_SOURCE_MISMATCH")
    result = report.get("keltner_single_axis_result")
    if not isinstance(result, dict):
        raise ValueError("SAVED_REJECTED_RESULT_MISSING")
    if result.get("child_identity") != EXPECTED_REJECTED_CHILD:
        raise ValueError("SAVED_REJECTED_IDENTITY_MISMATCH")
    if result.get("contract_sha256") != (
        "20e1905141cb32aabdfed66d3bddac2266fde506cccab577d29c3df963c4f9d8"
    ):
        raise ValueError("SAVED_REJECTED_CONTRACT_MISMATCH")
    rows = result.get("trade_rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_REJECTED_T:
        raise ValueError("SAVED_REJECTED_T_MISMATCH")
    return report, result


def _relabel(value: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(value))
    out["identity"] = KELTNER_SUCCESSOR
    signal = out.get("signal")
    if isinstance(signal, dict):
        signal["identity"] = KELTNER_SUCCESSOR
        signal.setdefault("meta", {})["lifecycle_adapter_parent_identity"] = (
            positive.KELTNER_PARENT
        )
        signal["meta"]["successor_axis"] = "FRESH_TOUCH_AFTER_REJECT"
    position = out.get("position")
    if isinstance(position, dict) and isinstance(position.get("signal"), dict):
        position["signal"]["identity"] = KELTNER_SUCCESSOR
        position["signal"].setdefault("meta", {})[
            "lifecycle_adapter_parent_identity"
        ] = positive.KELTNER_PARENT
        position["signal"]["meta"]["successor_axis"] = "FRESH_TOUCH_AFTER_REJECT"
    return out


def _state(value: positive.HolyGrailState) -> dict[str, Any]:
    return native._state(value)


def _reject_generated(
    policy: RejectedHGEventReset,
    state: positive.HolyGrailState,
    *,
    signal_ts_ms: int,
    decision_ts_ms: int,
    reason: str,
    symbol: str,
    segment_id: str,
    pending: dict[str, Any] | None,
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    if pending is not None:
        if pending.get("new_touch_ts_ms") is None:
            raise ValueError("REJECTED_SUCCESSOR_TURN_WITHOUT_NEW_TOUCH:" + symbol)
        if int(pending["new_touch_ts_ms"]) <= int(pending["rejected_decision_ts_ms"]):
            raise ValueError("NEW_TOUCH_NOT_STRICTLY_AFTER_REJECTION:" + symbol)
        pending["new_turn_ts_ms"] = signal_ts_ms
        pending["next_decision"] = "REJECTED"
        pending["next_rejection_reason"] = reason
        traces.append(pending)
    before = _state(state)
    policy.decided(state, accepted=False, decision_ts_ms=decision_ts_ms)
    after = _state(state)
    if (
        after["stage"] != 0
        or after["pull_low"] is not None
        or after["pull_high"] is not None
        or after["side"] != before["side"]
    ):
        raise ValueError("REJECT_RESET_INVARIANT_FAILED:" + symbol)
    return {
        "symbol": symbol,
        "segment_id": segment_id,
        "rejected_event_ts_ms": signal_ts_ms,
        "rejected_decision_ts_ms": decision_ts_ms,
        "rejection_reason": reason,
        "reset_state_before": before,
        "reset_state_after": after,
        "rejected_side": int(after["side"]),
        "new_touch_ts_ms": None,
        "new_turn_ts_ms": None,
        "accepted_entry_ts_ms": None,
        "next_decision": None,
    }


def _fresh_touch_successor(
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    windows: list[dict[str, Any]],
    *, benchmark_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    first_start = min(int(window["start_ms"]) for window in windows)
    ordered_windows = sorted(windows, key=lambda item: int(item["start_ms"]))
    prepared: dict[
        tuple[str, str], tuple[pd.DataFrame, list[dict[str, Any]], dict[int, int]]
    ] = {}
    for window in windows:
        start, end = int(window["start_ms"]), int(window["end_ms"])
        prefix_start = start - 200 * positive.TIMEFRAME_MS
        for symbol, frame in frames.items():
            sliced = frame[
                (frame["open_ts_ms"] >= prefix_start)
                & (frame["close_ts_ms"] <= end)
            ].reset_index(drop=True)
            records, index = execution._frame_records(
                sliced, positive.TIMEFRAME_MIN
            )
            prepared[(str(window["label"]), symbol)] = (sliced, records, index)

    rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    boundary_excluded: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    by_partition: dict[str, Counter[str]] = {
        "validation": Counter(),
        "rolling": Counter(),
    }
    unverified_admissions: Counter[str] = Counter()
    unverified_by_partition: dict[str, Counter[str]] = {
        "validation": Counter(),
        "rolling": Counter(),
    }
    candidates: Counter[str] = Counter()
    admitted: Counter[str] = Counter()
    ownership: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str, int]] = set()

    for symbol, frame in sorted(frames.items()):
        cost = float(costs.get(symbol, float("nan")))
        if not math.isfinite(cost) or cost <= 0:
            raise ValueError("KELTNER_SUCCESSOR_COST_UNBOUND:" + symbol)
        for segment in positive.enriched_segments(frame):
            source_rows = segment.to_dict("records")
            state = positive.HolyGrailState()
            if benchmark_observations is not None:
                from ops.scalp7_benchmark_observer_v1 import HGObserver
                watcher = HGObserver(symbol)
            pending: dict[str, Any] | None = None
            for i in range(1, len(source_rows)):
                row, previous = source_rows[i], source_rows[i - 1]
                before = _state(state)
                observation = None
                if i >= 121 and benchmark_observations is not None:
                    from dataclasses import asdict
                    from ops.scalp7_benchmark_observer_v1 import _state_view
                    raw_before = asdict(state)
                    # Exactly one native call. Observe raw dataclass state, not
                    # the JSON null-sanitized projection used by existing traces.
                    event = positive._hg_event(state, row, previous)
                    try:
                        observation = watcher.observe(raw_before, asdict(state), row, previous, event)
                    except (ValueError, KeyError, TypeError, IndexError) as exc:
                        observation = {"kind": "KELTNER_TRANSITION_UNKNOWN", "symbol": symbol,
                            "signal_open_ts_ms": int(row["open_ts_ms"]),
                            "error_type": type(exc).__name__, "error": str(exc),
                            "coverage": "UNKNOWN_NOT_ZERO"}
                    observation["admission"] = {"state": "NO_GENERATED_EVENT", "reason": None}
                    benchmark_observations.append(observation)
                else:
                    event = positive._hg_event(state, row, previous) if i >= 121 else None
                after = _state(state)
                row_available = int(row["feature_available_ts_ms"])
                if (
                    pending is not None
                    and int(after["side"]) != int(pending["rejected_side"])
                ):
                    pending["next_decision"] = (
                        "NATIVE_SIDE_OR_WEAK_RESET_BEFORE_NEW_TOUCH"
                    )
                    traces.append(pending)
                    pending = None
                if (
                    pending is not None
                    and before["stage"] == 0
                    and after["stage"] == 1
                    and event is None
                ):
                    if row_available <= int(pending["rejected_decision_ts_ms"]):
                        raise ValueError("NONCAUSAL_NEW_TOUCH:" + symbol)
                    pending["new_touch_ts_ms"] = row_available
                    pending["new_touch_open_ts_ms"] = int(row["open_ts_ms"])
                if event is None:
                    continue
                if observation is not None:
                    observation["admission"] = {"state": "OUTSIDE_EVALUATION_WINDOW", "reason": None}
                regime, regime_available = positive._regime(row, None)
                stamp = max(row_available, int(regime_available))
                if stamp < first_start:
                    continue
                # Match the accepted-entry child control: evaluation alone
                # must not consume the episode.  Geometry is unchanged here.
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
                    if observation is not None:
                        observation["admission"] = {"state": "REGIME_INELIGIBLE_NO_RESET", "reason": regime}
                    continue

                candidates[partition] += 1
                signal = native._keltner_parent_signal(
                    symbol,
                    row,
                    int(event[0]),
                    float(event[1]),
                    regime,
                    int(regime_available),
                    cost,
                )
                policy = RejectedHGEventReset()
                policy.generated(int(stamp))
                duplicate = (str(window["label"]), symbol, int(stamp))
                reason: str | None = None
                decision_ts: int | None = int(stamp)
                trade = open_position = None
                until = int(stamp)

                if duplicate in seen:
                    reason = "DUPLICATE_SIGNAL"
                else:
                    seen.add(duplicate)
                    owner = (str(window["label"]), symbol)
                    if stamp < ownership.get(owner, -1):
                        reason = "POSITION_ALREADY_OWNED"
                    else:
                        sliced, records, index = prepared[
                            (str(window["label"]), symbol)
                        ]
                        gate_allowed, gate_ts, gate_reason = native._entry_gate(
                            signal, {symbol: sliced}
                        )
                        trade, open_position, until, reason = execution._single(
                            signal,
                            sliced,
                            records,
                            index,
                            cost,
                            positive.exit_update,
                            positive.entry_update,
                        )
                        decision_ts = (
                            int(gate_ts) if gate_ts is not None else None
                        )
                        if reason is None and (
                            not gate_allowed or decision_ts is None
                        ):
                            raise ValueError(
                                "ENTRY_GATE_SINGLE_DISAGREEMENT:"
                                + symbol
                                + ":"
                                + str(gate_reason)
                            )
                        if reason is not None and not gate_allowed:
                            reason = str(reason)
                if reason is not None and decision_ts is None:
                    reason = str(reason)
                    unverified_admissions[reason] += 1
                    unverified_by_partition[partition][reason] += 1
                    if observation is not None:
                        observation["admission"] = {"state": "UNKNOWN_NO_RESET", "reason": reason}
                    continue
                if reason is not None:
                    reason = str(reason)
                    rejections[reason] += 1
                    by_partition[partition][reason] += 1
                    pending = _reject_generated(
                        policy,
                        state,
                        signal_ts_ms=int(stamp),
                        decision_ts_ms=int(decision_ts),
                        reason=reason,
                        symbol=symbol,
                        segment_id=str(row["segment_id"]),
                        pending=pending,
                        traces=traces,
                    )
                    if observation is not None:
                        observation["admission"] = {"state": "REJECTED_RESET", "reason": reason,
                            "decision_ts_ms": int(decision_ts),
                            "state_after_policy": _state_view(asdict(state))}
                    continue

                if pending is not None:
                    if pending.get("new_touch_ts_ms") is None:
                        raise ValueError(
                            "ACCEPTED_SUCCESSOR_TURN_WITHOUT_NEW_TOUCH:" + symbol
                        )
                    if int(pending["new_touch_ts_ms"]) <= int(
                        pending["rejected_decision_ts_ms"]
                    ):
                        raise ValueError(
                            "NEW_TOUCH_NOT_STRICTLY_AFTER_REJECTION:" + symbol
                        )
                    pending["new_turn_ts_ms"] = int(stamp)
                    pending["accepted_entry_ts_ms"] = int(decision_ts)
                    pending["next_decision"] = "ACCEPTED"
                    traces.append(pending)
                    pending = None
                policy.decided(
                    state, accepted=True, decision_ts_ms=int(decision_ts)
                )
                if observation is not None:
                    observation["admission"] = {"state": "ACCEPTED", "reason": None,
                        "decision_ts_ms": int(decision_ts),
                        "state_after_policy": _state_view(asdict(state))}
                admitted[partition] += 1
                owner = (str(window["label"]), symbol)
                ownership[owner] = int(until)
                if trade is not None:
                    child = _relabel(trade)
                    child["window_label"] = str(window["label"])
                    child["partition"] = partition
                    if int(child["outcome_available_ts_ms"]) >= int(
                        window["end_ms"]
                    ):
                        child["boundary_exclusion_reason"] = (
                            "OUTCOME_AT_OR_AFTER_WINDOW_END_UNAVAILABLE"
                        )
                        child["window_end_ms"] = int(window["end_ms"])
                        boundary_excluded.append(child)
                    else:
                        rows.append(child)
                if open_position is not None:
                    child_open = _relabel(open_position)
                    child_open["window_label"] = str(window["label"])
                    child_open["partition"] = partition
                    child_open["window_end_ms"] = int(window["end_ms"])
                    unresolved.append(child_open)
            if pending is not None:
                pending["next_decision"] = "NO_LATER_ACCEPTED_EVENT_IN_SEGMENT"
                traces.append(pending)

    rows.sort(
        key=lambda item: (
            int(item["outcome_available_ts_ms"]),
            int(item["exit_ts_ms"]),
            str(item["symbol"]),
            str(item["identity"]),
            int(item["signal_ts_ms"]),
        )
    )
    return {
        "trades": rows,
        "unresolved": unresolved,
        "boundary_excluded": boundary_excluded,
        "traces": traces,
        "candidate_count_by_partition": dict(candidates),
        "admitted_count_by_partition": dict(admitted),
        "rejections": dict(sorted(rejections.items())),
        "rejections_by_partition": {
            key: dict(sorted(value.items())) for key, value in by_partition.items()
        },
        "unverified_admissions": dict(sorted(unverified_admissions.items())),
        "unverified_admissions_by_partition": {
            key: dict(sorted(value.items()))
            for key, value in unverified_by_partition.items()
        },
    }


def _runs(values: list[float], positive_run: bool) -> list[list[float]]:
    output: list[list[float]] = []
    current: list[float] = []
    for value in values:
        matches = value > 0 if positive_run else value < 0
        if matches:
            current.append(value)
        elif current:
            output.append(current)
            current = []
    if current:
        output.append(current)
    return output


def _streaks(rows: list[dict[str, Any]], multiplier: float) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row["outcome_available_ts_ms"]),
            int(row["exit_ts_ms"]),
            str(row["symbol"]),
            str(row["identity"]),
            int(row["signal_ts_ms"]),
        ),
    )
    nets = [
        float(row["gross_bps"]) - multiplier * float(row["cost_bps"])
        for row in ordered
    ]
    wins, losses = _runs(nets, True), _runs(nets, False)
    win_lengths = [len(run) for run in wins]
    loss_lengths = [len(run) for run in losses]
    positive_count = sum(value > 0 for value in nets)

    cohort_values: list[float] = []
    equity_points: list[tuple[int, float]] = []
    grouped: dict[int, float] = {}
    for row, value in zip(ordered, nets):
        grouped[int(row["outcome_available_ts_ms"])] = (
            grouped.get(int(row["outcome_available_ts_ms"]), 0.0) + value
        )
    equity = 0.0
    peak = 0.0
    peak_ts: int | None = None
    max_dd = 0.0
    max_peak = 0.0
    dd_peak_ts: int | None = None
    trough_ts: int | None = None
    for ts, value in sorted(grouped.items()):
        cohort_values.append(value)
        equity += value
        equity_points.append((ts, equity))
        if equity > peak:
            peak, peak_ts = equity, ts
        drawdown = peak - equity
        if drawdown > max_dd:
            max_dd = drawdown
            max_peak = peak
            dd_peak_ts = peak_ts
            trough_ts = ts
    recovery_ts = next(
        (
            ts
            for ts, value in equity_points
            if trough_ts is not None and ts > trough_ts and value >= max_peak
        ),
        None,
    )

    by_symbol: dict[str, dict[str, int]] = {}
    for symbol in sorted({str(row["symbol"]) for row in ordered}):
        symbol_values = [
            float(row["gross_bps"]) - multiplier * float(row["cost_bps"])
            for row in ordered
            if str(row["symbol"]) == symbol
        ]
        by_symbol[symbol] = {
            "max_win_run": max(
                (len(run) for run in _runs(symbol_values, True)), default=0
            ),
            "max_loss_run": max(
                (len(run) for run in _runs(symbol_values, False)), default=0
            ),
        }
    return {
        "ordering": "outcome_available_ts_then_exit_ts_then_symbol_then_identity_then_signal_ts",
        "zero_terminates_run": True,
        "max_win_run": max(win_lengths, default=0),
        "median_win_run": median(win_lengths) if win_lengths else 0,
        "win_runs_ge_2": sum(length >= 2 for length in win_lengths),
        "positive_trade_share_in_runs_ge_2": (
            sum(len(run) for run in wins if len(run) >= 2) / positive_count
            if positive_count
            else None
        ),
        "max_loss_run": max(loss_lengths, default=0),
        "worst_loss_run_net_bps": min(
            (sum(run) for run in losses), default=0.0
        ),
        "simultaneous_outcome_cohort_max_win_run": max(
            (len(run) for run in _runs(cohort_values, True)), default=0
        ),
        "simultaneous_outcome_cohort_max_loss_run": max(
            (len(run) for run in _runs(cohort_values, False)), default=0
        ),
        "realized_trade_bps_max_drawdown": max_dd,
        "drawdown_peak_ts_ms": dd_peak_ts,
        "drawdown_trough_ts_ms": trough_ts,
        "recovery_ts_ms": recovery_ts,
        "recovery_hours": (
            None
            if recovery_ts is None or trough_ts is None
            else (recovery_ts - trough_ts) / 3_600_000
        ),
        "unrecovered": trough_ts is not None and recovery_ts is None,
        "per_symbol": by_symbol,
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cost1x": metrics.summarize(
            rows, native.START, native.END, 1.0
        ),
        "cost2x": metrics.summarize(
            rows, native.START, native.END, 2.0
        ),
        "daily_cost1x": native._daily_economics(rows, 1.0),
        "daily_cost2x": native._daily_economics(rows, 2.0),
        "streak_cost1x": _streaks(rows, 1.0),
        "streak_cost2x": _streaks(rows, 2.0),
    }


def run(
    source_root: Path, saved_rejected_result: Path, output: Path,
    *, benchmark_observations: bool = False,
) -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text())
    if contract.get("successor_identity") != KELTNER_SUCCESSOR:
        raise ValueError("SUCCESSOR_CONTRACT_IDENTITY_MISMATCH")
    if contract.get("source_inventory_sha256") != native.EXPECTED_INVENTORY:
        raise ValueError("SUCCESSOR_CONTRACT_SOURCE_MISMATCH")
    campaign = json.loads(
        (native.REPORT / "CAMPAIGN_PREREGISTERED_V2.json").read_text()
    )
    windows = campaign["windows"]
    frames = source.load_candles(source_root, 30, cache_dir=None)
    if set(frames) != SYMBOLS:
        raise ValueError("SOURCE_COHORT_DRIFT")
    if {
        frame.attrs["source_inventory_sha256"] for frame in frames.values()
    } != {native.EXPECTED_INVENTORY}:
        raise ValueError("SOURCE_INVENTORY_SHA_MISMATCH")
    features = context.cross_features(frames)
    bound, fits = context.bind_context(frames, features, windows)
    context_sha = hashlib.sha256(
        json.dumps(fits, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    costs = json.loads(native.COST_PATH.read_text())["costs_bps"]

    saved_parent_path, saved_parent = native._load_saved(
        positive.KELTNER_PARENT
    )
    parent_signals = positive.generate_signals(
        bound, costs=costs, identities=(positive.KELTNER_PARENT,)
    )
    parent_rows, parent_unresolved, _, _ = native._replay_parent(
        positive.KELTNER_PARENT,
        bound,
        costs,
        windows,
        parent_signals,
    )
    if (
        parent_rows != saved_parent["trades"]
        or parent_unresolved != saved_parent["unresolved"]
    ):
        raise ValueError("EXACT_PARENT_REPLAY_PARITY_FAILED")
    parent_trade_rows = [
        row for row in parent_rows if row["partition"] == "rolling"
    ]
    if len(parent_trade_rows) != 109:
        raise ValueError("PARENT_ROLLING_T_MISMATCH")

    saved_report, rejected_result = _load_rejected(saved_rejected_result)
    if saved_report.get("context_fit_sha256") != context_sha:
        raise ValueError("SAVED_REJECTED_CONTEXT_SHA_MISMATCH")
    rejected_rows = rejected_result["trade_rows"]

    observations = [] if benchmark_observations else None
    successor = _fresh_touch_successor(bound, costs, windows, benchmark_observations=observations)
    successor_rows = [
        row for row in successor["trades"] if row["partition"] == "rolling"
    ]
    successor_unresolved = [
        row for row in successor["unresolved"] if row["partition"] == "rolling"
    ]
    successor_boundary = [
        row
        for row in successor["boundary_excluded"]
        if row["partition"] == "rolling"
    ]
    rolling_traces = [
        row
        for row in successor["traces"]
        if native.START <= int(row["rejected_event_ts_ms"]) < native.END
    ]
    completed_traces = [
        row for row in rolling_traces if row["next_decision"] == "ACCEPTED"
    ]
    if not completed_traces:
        raise ValueError("NO_COMPLETED_CAUSAL_TRACE")
    if any(
        not (
            int(row["rejected_event_ts_ms"])
            <= int(row["rejected_decision_ts_ms"])
            < int(row["new_touch_ts_ms"])
            <= int(row["new_turn_ts_ms"])
            <= int(row["accepted_entry_ts_ms"])
        )
        for row in completed_traces
    ):
        raise ValueError("COMPLETED_CAUSAL_TRACE_ORDER_FAILED")

    result = {
        "state": "USED_DEV_COSTED_SINGLE_AXIS_RESULT_NOT_FRESH_NOT_SURVIVOR",
        "contract_path": str(CONTRACT_PATH.relative_to(ROOT)),
        "contract_sha256": _sha(CONTRACT_PATH),
        "parent_identity": positive.KELTNER_PARENT,
        "saved_rejected_child_identity": EXPECTED_REJECTED_CHILD,
        "successor_identity": KELTNER_SUCCESSOR,
        "saved_rejected_child_replayed": False,
        "new_candidate_native_comparisons_this_run": 1,
        "candidate_count": successor[
            "candidate_count_by_partition"
        ].get("rolling", 0),
        "admitted_count": successor[
            "admitted_count_by_partition"
        ].get("rolling", 0),
        "rejections": successor["rejections_by_partition"].get("rolling", {}),
        "unverified_admissions": successor[
            "unverified_admissions_by_partition"
        ].get("rolling", {}),
        "unresolved_count": len(successor_unresolved),
        "boundary_excluded_count": len(successor_boundary),
        "causal_trace": {
            "rolling_rejected_resets": len(rolling_traces),
            "rolling_completed_reject_reset_touch_turn_accept": len(
                completed_traces
            ),
            "records": rolling_traces,
        },
        "parent": _metrics(parent_trade_rows),
        "saved_rejected_child": _metrics(rejected_rows),
        "successor": _metrics(successor_rows),
        "parent_to_successor": native._opportunity_comparison(
            parent_trade_rows, successor_rows
        ),
        "saved_rejected_to_successor": native._opportunity_comparison(
            rejected_rows, successor_rows
        ),
        "trade_rows": successor_rows,
        "unresolved": successor_unresolved,
        "boundary_excluded": successor_boundary,
        "promotion": False,
        "survivor_count_delta": 0,
    }
    report = {
        "schema": "zel.scalp7.keltner_fresh_touch_successor_native.v1",
        "state": "KELTNER_SUCCESSOR_USED_DEV_NATIVE_COMPARISON_COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "used_dev_only": True,
        "fresh_or_oos": False,
        "source_inventory_sha256": native.EXPECTED_INVENTORY,
        "context_fit_sha256": context_sha,
        "window": {
            "start_ms": native.START,
            "end_exclusive_ms": native.END,
            "calendar_days": 245,
            "timeframe_min": 30,
        },
        "parent_ledger_path": str(saved_parent_path.relative_to(ROOT)),
        "parent_ledger_sha256": native.EXPECTED[
            positive.KELTNER_PARENT
        ]["ledger_sha256"],
        "saved_rejected_report_receipt_sha256": EXPECTED_REJECTED_RECEIPT,
        "result": result,
        "raw_price_bodies_exported": False,
        "market_requests": 0,
        "economic_runs": 1,
        "observer_changes_parent_state": False,
        "account_nav_or_mtm": None,
        "order_live_paper_deploy": "BLOCKED_UNSURE_HOLD",
    }
    if observations is not None:
        report["benchmark_observations"] = {"kind": "H02_READ_ONLY_NOT_NEW_RULE",
            "native_warmup_min_index": 121, "records": observations,
            "economic_improvement": "NOT_MEASURED_BY_OBSERVER"}
    report["receipt_sha256"] = _receipt(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--saved-rejected-result", type=Path, required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark-observations", action="store_true")
    args = parser.parse_args()
    result = run(
        args.source_root, args.saved_rejected_result, args.output,
        benchmark_observations=args.benchmark_observations,
    )
    print("KELTNER_FRESH_TOUCH_RECEIPT=" + result["receipt_sha256"])
    summary = result["result"]
    print(
        json.dumps(
            {
                "saved_rejected_replayed": summary[
                    "saved_rejected_child_replayed"
                ],
                "candidate_count": summary["candidate_count"],
                "admitted_count": summary["admitted_count"],
                "causal_trace": summary["causal_trace"][
                    "rolling_completed_reject_reset_touch_turn_accept"
                ],
                "parent_T": summary["parent"]["cost1x"]["T"],
                "rejected_T": summary["saved_rejected_child"]["cost1x"]["T"],
                "successor_T": summary["successor"]["cost1x"]["T"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
