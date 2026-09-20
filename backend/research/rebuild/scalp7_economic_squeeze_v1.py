"""Frozen Squeeze 30m-context / 15m-execution research architecture.

Source concepts and expected cases are in SQUEEZE_SOURCE_CASES.md.
No order API, fitted threshold, completed-bar fill or synthetic market data.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.research.rebuild import scalp7_execution_v2 as engine
from backend.research.rebuild import scalp7_positive_lanes_v2 as parent

TF_MS = 900_000
CONTEXT_MS = 1_800_000
CONTROL = "scalp7_squeeze_30m_context_15m_exec_control_v1"
HIGH2 = "scalp7_squeeze_30m_context_15m_high2_replacement_v1"
IDENTITIES = (CONTROL, HIGH2)
SPEC = {
    "identities": IDENTITIES,
    "parent": parent.SQUEEZE_PARENT,
    "parent_spec_sha256": parent.SPEC_SHA256,
    "decision_timeframe_min": 15,
    "context_timeframe_min": 30,
    "context": "exact frozen parent potential fires; genuine reference costs",
    "control": "original fire entry/stop/fallback on 15m execution",
    "child": "replace immediate entry, never supplement",
    "sequence": [
        "post-fire completed15m low<prior low",
        "later completed15m high>prior high",
        "later completed15m high<prior high",
        "later completed15m high>prior high",
    ],
    "transitions": "one per bar; no bullish-close or strong-close requirement",
    "structural_stop": "minimum low from first pullback through High2",
    "child_wrong_side_stop": "reject without fallback or retry",
    "preentry_cancel": [
        "completed15m low<origin fire low before trigger",
        "gap or segment change",
        "new visible parent fire before trigger",
        "completed30m momentum<=0",
        "two weakening positive30m endpoints after original fire",
        "elapsed from origin fire close >10*30min",
    ],
    "attempts_per_fire": 1,
    "cost_gate": "origin ATR20 / actual next-open price *10000 / bound cost >=4",
    "fire_close_proxy_gate": False,
    "position_exit": "inherited two-positive-weakening30m pattern only",
    "post_entry_momentum": "second-latest30m open>=actual entry; no straddling count",
    "absolute_deadline": "origin fire close+11*30min; no restart at delayed entry",
    "setup_last_eligible_minutes": 300,
    "max_hold_control_15m_bars": 22,
    "entry": "common frozen next-open admission; stop-first execution",
    "source_exact_or_platform_numeric_parity": False,
    "interpretation": "multi-component source-inspired entry/risk replacement",
    "BE1R": False,
    "Carter_thrust4": False,
    "grid_search": False,
    "promotion": False,
    "order": "BLOCKED",
    "live": "BLOCKED",
}
SPEC_SHA256 = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()


def _weak(row: Mapping[str, Any], entry_ts: int) -> bool:
    values = [
        float(row.get("c30_momentum" + suffix, math.nan))
        for suffix in ("_prev2", "_prev1", "")
    ]
    return (
        all(math.isfinite(v) for v in values)
        and values[2] > 0
        and values[1] > 0
        and values[2] < values[1] < values[0]
        and int(row.get("c30_previous_open_ts_ms", -1)) >= entry_ts
    )


def prepare_frames(
    frames15: Mapping[str, pd.DataFrame],
    frames30: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
) -> dict[str, pd.DataFrame]:
    """Bind exact parent potential events and only available completed context."""
    if set(frames15) != set(frames30):
        raise ValueError("SQUEEZE_TIMEFRAME_SYMBOL_MISMATCH")
    for symbol in frames15:
        if not math.isfinite(float(costs[symbol])) or float(costs[symbol]) <= 0:
            raise ValueError("SQUEEZE_GENUINE_COST_REQUIRED")
    fires = parent.generate_signals(
        dict(frames30), costs=costs, identities=(parent.SQUEEZE_PARENT,)
    )
    by_symbol: dict[str, list[dict[str, Any]]] = {s: [] for s in frames15}
    for fire in fires:
        by_symbol[fire["symbol"]].append(fire)
    prepared = {}
    for symbol, raw in sorted(frames15.items()):
        frame = raw.copy().reset_index(drop=True)
        rows, indexes = engine._frame_records(frame, 15)
        if frame.segment_id.isna().any():
            raise ValueError("SQUEEZE_SEGMENT_REQUIRED")
        contexts = []
        for segment in parent.enriched_segments(frames30[symbol]):
            segment = segment.copy()
            segment["momentum_prev1"] = segment.momentum.shift(1)
            segment["momentum_prev2"] = segment.momentum.shift(2)
            segment["previous_open_ts_ms"] = segment.open_ts_ms.shift(1).fillna(-1)
            contexts.extend(segment.to_dict("records"))
        context_by_close = {int(c["close_ts_ms"]): c for c in contexts}
        expected_starts = {
            int(a["open_ts_ms"])
            for a, b in zip(rows, rows[1:])
            if int(a["open_ts_ms"]) % CONTEXT_MS == 0
            and int(b["open_ts_ms"]) == int(a["close_ts_ms"])
            and a["segment_id"] == b["segment_id"]
        }
        if expected_starts != {int(c["open_ts_ms"]) for c in contexts}:
            raise ValueError("SQUEEZE_CONTEXT_COVERAGE_MISMATCH")
        # The two actual half bars must produce the supplied complete30m candle.
        for context in contexts:
            start = int(context["open_ts_ms"])
            ix = indexes.get(start)
            if ix is None or ix + 1 >= len(rows):
                raise ValueError("SQUEEZE_CONTEXT_HALVES_MISSING")
            a, b = rows[ix], rows[ix + 1]
            if (
                int(b["open_ts_ms"]) != start + TF_MS
                or a["segment_id"] != b["segment_id"]
            ):
                raise ValueError("SQUEEZE_CONTEXT_STRADDLES_GAP")
            expected = (
                a["open"],
                max(a["high"], b["high"]),
                min(a["low"], b["low"]),
                b["close"],
            )
            actual = [context[k] for k in ("open", "high", "low", "close")]
            if not np.allclose(expected, actual, rtol=1e-12, atol=0):
                raise ValueError("SQUEEZE_CONTEXT_OHLC_MISMATCH")
        control_at = {}
        activations: dict[int, list[dict[str, Any]]] = {}
        closes = [int(r["close_ts_ms"]) for r in rows]
        for original in by_symbol[symbol]:
            fire = deepcopy(original)
            fire_close = int(fire["signal_open_ts_ms"]) + CONTEXT_MS
            source = context_by_close[fire_close]
            fire["meta"].update(
                origin_fire_ts_ms=fire_close,
                origin_fire_available_ts_ms=int(fire["signal_ts_ms"]),
                origin_context_open_ts_ms=int(source["open_ts_ms"]),
                origin_fire_low=float(source["low"]),
                origin_execution_segment_id=rows[indexes[fire_close - TF_MS]][
                    "segment_id"
                ],
                origin_event_key=f"{symbol}:1:{fire_close}",
            )
            control_at[fire_close] = fire
            ix = int(np.searchsorted(closes, int(fire["signal_ts_ms"])))
            if ix < len(rows):
                activations.setdefault(ix, []).append(fire)
        cindex = -1
        output = []
        for i, row in enumerate(rows):
            value = dict(row)
            decision_time = int(row["close_ts_ms"])
            while cindex + 1 < len(contexts):
                following = contexts[cindex + 1]
                if (
                    max(
                        int(following["feature_available_ts_ms"]),
                        int(following["close_ts_ms"]),
                    )
                    > decision_time
                ):
                    break
                cindex += 1
            value.update(
                squeeze_spec_sha256=SPEC_SHA256,
                squeeze_control_fire=control_at.get(decision_time),
                squeeze_visible_fires=activations.get(i, []),
            )
            for key in (
                "open_ts_ms",
                "close_ts_ms",
                "feature_available_ts_ms",
                "momentum",
                "momentum_prev1",
                "momentum_prev2",
                "previous_open_ts_ms",
            ):
                value["c30_" + key] = (
                    contexts[cindex][key]
                    if cindex >= 0
                    else (math.nan if key.startswith("momentum") else -1)
                )
            output.append(value)
        prepared[symbol] = pd.DataFrame(
            output, columns=None if output else frame.columns
        )
    return prepared


@dataclass
class High2State:
    fire: dict[str, Any]
    segment_id: Any
    stage: int = 0
    pull_low: float = math.inf
    consumed: bool = False
    trace: list[dict[str, Any]] | None = None

    def invalidated(self, row: Mapping[str, Any], previous: Mapping[str, Any]) -> bool:
        meta = self.fire["meta"]
        origin = int(meta["origin_fire_ts_ms"])
        elapsed = int(row["close_ts_ms"]) - origin
        momentum = float(row.get("c30_momentum", math.nan))
        invalid = (
            row["segment_id"] != self.segment_id
            or row["open_ts_ms"] != previous["close_ts_ms"]
            or int(row["available_ts_ms"]) > int(row["close_ts_ms"])
            or int(previous["available_ts_ms"]) > int(row["close_ts_ms"])
            or elapsed > 10 * CONTEXT_MS
            or float(row["low"]) < float(meta["origin_fire_low"])
            or (math.isfinite(momentum) and momentum <= 0)
            or _weak(row, origin)
        )
        return invalid

    def observe(self, row: Mapping[str, Any], previous: Mapping[str, Any]) -> bool:
        if self.consumed:
            return False
        if self.invalidated(row, previous):
            self.consumed = True
            return False
        meta = self.fire["meta"]
        available = int(meta["origin_fire_available_ts_ms"])
        elapsed = int(row["close_ts_ms"]) - int(meta["origin_fire_ts_ms"])
        if int(row["open_ts_ms"]) < available or elapsed <= 0:
            return False
        if self.stage:
            self.pull_low = min(self.pull_low, float(row["low"]))
        advance = (
            float(row["low"]) < float(previous["low"])
            if self.stage == 0
            else (
                float(row["high"]) > float(previous["high"])
                if self.stage in (1, 3)
                else float(row["high"]) < float(previous["high"])
            )
        )
        if not advance:
            return False
        if not self.stage:
            self.pull_low = float(row["low"])
        label = ("PULLBACK", "HIGH1", "LOWER_HIGH", "HIGH2")[self.stage]
        if self.trace is None:
            self.trace = []
        self.trace.append(
            {
                "stage": label,
                "open_ts_ms": int(row["open_ts_ms"]),
                "close_ts_ms": int(row["close_ts_ms"]),
                "available_ts_ms": int(row["available_ts_ms"]),
            }
        )
        self.stage += 1
        self.consumed = self.stage == 4
        return self.consumed


def _signal(
    fire: Mapping[str, Any],
    row: Mapping[str, Any],
    identity: str,
    stop: float,
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    signal = deepcopy(dict(fire))
    origin = int(signal["meta"]["origin_fire_ts_ms"])
    deadline = origin + 11 * CONTEXT_MS
    close = int(row["close_ts_ms"])
    remaining = (deadline - close) // TF_MS
    if remaining < 1:
        raise ValueError("SQUEEZE_SIGNAL_AFTER_ORIGINAL_DEADLINE")
    signal.update(
        identity=identity,
        timeframe_min=15,
        signal_open_ts_ms=int(row["open_ts_ms"]),
        signal_ts_ms=max(int(row["available_ts_ms"]), int(fire["signal_ts_ms"])),
        segment_id=row["segment_id"],
        stop_price=stop,
        max_hold_bars=int(remaining),
        exit_policy="SQUEEZE_COMPLETED_30M_MOMENTUM",
    )
    signal["meta"].update(
        spec_sha256=SPEC_SHA256,
        source_parent_spec_sha256=parent.SPEC_SHA256,
        feature_available_ts_ms=signal["signal_ts_ms"],
        absolute_deadline_ts_ms=deadline,
        setup_trace=deepcopy(trace),
        entry_architecture=(
            "PARENT_FIRE" if identity == CONTROL else "HIGH2_REPLACEMENT"
        ),
    )
    return signal


def generate_signals(
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    identity: str = CONTROL,
) -> list[dict[str, Any]]:
    if identity not in IDENTITIES:
        raise ValueError("SQUEEZE_ECONOMIC_IDENTITY_UNKNOWN")
    result = []
    for symbol, frame in sorted(frames.items()):
        rows = frame.to_dict("records")
        state: High2State | None = None
        for i, row in enumerate(rows):
            if row.get("squeeze_spec_sha256") != SPEC_SHA256:
                raise ValueError("SQUEEZE_PREPARED_FRAME_REQUIRED")
            original = row.get("squeeze_control_fire")
            if identity == CONTROL and isinstance(original, dict):
                if float(original["meta"]["frozen_cost_bps"]) != float(costs[symbol]):
                    raise ValueError("SQUEEZE_PREPARED_COST_MISMATCH")
                result.append(
                    _signal(original, row, identity, float(original["stop_price"]), [])
                )
            if identity == CONTROL:
                continue
            visible = row.get("squeeze_visible_fires") or []
            if visible:
                fire = visible[-1]
                if float(fire["meta"]["frozen_cost_bps"]) != float(costs[symbol]):
                    raise ValueError("SQUEEZE_PREPARED_COST_MISMATCH")
                state = High2State(
                    deepcopy(fire), fire["meta"]["origin_execution_segment_id"]
                )
                if i and state.invalidated(row, rows[i - 1]):
                    state.consumed = True
                # New context overrides old trigger; the visibility bar is not
                # reconstructed retrospectively as a post-fire pullback.
                continue
            if state is not None and i and state.observe(row, rows[i - 1]):
                result.append(
                    _signal(
                        state.fire, row, identity, state.pull_low, state.trace or []
                    )
                )
    return sorted(result, key=lambda s: (s["signal_ts_ms"], s["symbol"]))


def entry_update(signal: Mapping[str, Any], price: float) -> dict[str, Any]:
    if signal["identity"] not in IDENTITIES:
        raise ValueError("SQUEEZE_ECONOMIC_IDENTITY_UNKNOWN")
    if signal["identity"] == HIGH2 and price <= float(signal["stop_price"]):
        return {"reject": True, "reason": "HIGH2_ENTRY_INVALIDATES_STRUCTURE"}
    copied = {**signal, "identity": parent.SQUEEZE_PARENT}
    return parent.entry_update(copied, price)


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    if position["signal"]["identity"] not in IDENTITIES:
        raise ValueError("SQUEEZE_ECONOMIC_IDENTITY_UNKNOWN")
    if (
        history.empty
        or int(history.iloc[-1]["open_ts_ms"]) != int(bar["open_ts_ms"])
        or int(bar["open_ts_ms"]) < int(position["entry_ts_ms"])
    ):
        raise ValueError("SQUEEZE_CLOSED_POSTENTRY_PREFIX_REQUIRED")
    if (history.available_ts_ms > int(bar["available_ts_ms"])).any():
        raise ValueError("SQUEEZE_FUTURE_EXECUTION_PREFIX")
    close = int(bar.get("c30_close_ts_ms", -1))
    available = int(bar.get("c30_feature_available_ts_ms", -1))
    if max(close, available) > int(bar["close_ts_ms"]):
        raise ValueError("SQUEEZE_FUTURE_30M_CONTEXT")
    seen = int(position.get("_squeeze_last_momentum_close", -1))
    if close <= seen:
        return {"exit_next_open": False, "reason": "SQUEEZE_NO_NEW_30M_OBSERVATION"}
    position["_squeeze_last_momentum_close"] = close
    if _weak(bar, int(position["entry_ts_ms"])):
        return {"exit_next_open": True, "reason": "SQUEEZE_TWO_WEAK_MOMENTUM_NEXT_OPEN"}
    return {"exit_next_open": False, "reason": "SQUEEZE_COMPLETED_30M_HOLD"}
