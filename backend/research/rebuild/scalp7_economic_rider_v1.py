"""Two-clock GMMA pullback architecture; research signals only, never orders.

Guppy supplies qualitative two-group context. Every exact period, predicate,
clock and lifecycle below is an explicitly declared mechanical adaptation.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import pandas as pd

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_rider_architecture_v2 as parent

IDENTITY = "scalp7_rider_gmma_pullback_15m_exit15_v1"
IDENTITY30 = "scalp7_rider_gmma_pullback_15m_exit30_v1"
IDENTITIES = (IDENTITY, IDENTITY30)
LANE = "trend_rider"
TIMEFRAME_MIN = 15
TIMEFRAME_MS = 900_000
CONTEXT_MS = 1_800_000
SHORT_GMMA = (3, 5, 8, 10, 12, 15)
LONG_GMMA = (30, 35, 40, 45, 50, 60)
WARMUP_BARS = 60
SETUP_TTL_BARS = 8
MAX_HOLD_BARS = 36
SOURCE_URL = "https://www.guppytraders.com/gmma-info"

SPEC: dict[str, Any] = {
    "identities": list(IDENTITIES),
    "lane": LANE,
    "timeframe_min": TIMEFRAME_MIN,
    "context_timeframe_min": 30,
    "classification": "NEW_WHOLE_ARCHITECTURE_AND_PAIRED_EXIT_CLOCK_ABLATION",
    "source": SOURCE_URL,
    "source_sections": ["APPLICATION", "TACTICS", "RULES"],
    "source_direct": [
        "Use long and short average groups to characterize trend and activity.",
        "Established-trend weakness can be a continuation opportunity.",
        "Both-group compression differs from short-group compression alone.",
    ],
    "own_mechanical_rules": [
        "EMA periods short3,5,8,10,12,15 / long30,35,40,45,50,60 reuse only V6 numerical convention; not source-specified periods.",
        "Seed EMA at segment first close, adjust=False; require60 completed30m bars and a warm previous row.",
        "Long strict directional period-order plus EMA60 directional slope qualifies trend; previous short group must be wholly beyond previous long group in that direction.",
        "A new30m event requires short width decrease, long width nondecrease, current long trend qualification and actual low/close decline for long or high/close rise for short.",
        "Consume one compression event; another requires intervening short-width expansion. Long-order episode change or source gap resets this state.",
        "A later independently rearmed compression replaces any still-pending setup before trigger evaluation; the new event cannot trigger at its own availability instant.",
        "Join only completed30m features actually available by completed15m decision; prefix feature availability includes all EMA source rows.",
        "Trigger strictly after setup availability when completed15m close exceeds prior15m high for long or falls below prior15m low for short.",
        "Initial stop is actual worst low/high from30m setup through15m trigger; no ATR fallback or numeric distance retune.",
        "Cancel setup if current long-group order loses direction, 15m continuity breaks, 30m context is stale by more than one30m interval, or age exceeds8x15m since setup availability.",
        "Hold36x15m from entry identically; no target, BE or cost gate.",
        "Exit15 and exit30 use the same inherited three-bar confirmed-pivot geometry on their respective complete bars.",
        "Pivot candle open must be at/after entry; left reference may precede entry. Right bar must be available. New stop applies next15m bar and never loosens.",
    ],
    "short_gmma": list(SHORT_GMMA),
    "long_gmma": list(LONG_GMMA),
    "warmup_bars": WARMUP_BARS,
    "setup_ttl_bars": SETUP_TTL_BARS,
    "max_hold_bars": MAX_HOLD_BARS,
    "legacy_parent": parent.IDENTITY,
    "legacy_parent_comparison": "CONTEXTUAL_WHOLE_SYSTEM_ONLY_NOT_MATCHED_SINGLE_AXIS",
    "exact_author_strategy_replication": False,
    "historical_status": "ALREADY_INSPECTED_DEV_NOT_FRESH",
    "order": "BLOCKED",
    "live": "BLOCKED",
}
SPEC_SHA256 = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()


def _ordered(row: dict[str, Any]) -> int:
    values = [float(row[f"g{n}"]) for n in LONG_GMMA]
    if all(a > b for a, b in zip(values, values[1:])):
        return 1
    if all(a < b for a, b in zip(values, values[1:])):
        return -1
    return 0


def _features(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Compute only causal30m context; no economic engine or signal scan."""
    rows, _ = execution._frame_records(frame, 30)
    out: list[dict[str, Any]] = []
    averages: dict[int, float] = {}
    segment_rows: list[dict[str, Any]] = []
    feature_available = 0
    episode: int | None = None
    previous_order = 0
    armed = True
    for raw in rows:
        if segment_rows and not execution._can_follow(segment_rows[-1], raw):
            averages = {}
            segment_rows = []
            feature_available = 0
            episode = None
            previous_order = 0
            armed = True
        row = dict(raw)
        feature_available = max(feature_available, int(row["available_ts_ms"]))
        for n in SHORT_GMMA + LONG_GMMA:
            before = averages.get(n, float(row["close"]))
            averages[n] = before + (2.0 / (n + 1)) * (float(row["close"]) - before)
            row[f"g{n}"] = averages[n]
        short = [row[f"g{n}"] for n in SHORT_GMMA]
        long = [row[f"g{n}"] for n in LONG_GMMA]
        row["short_width"] = max(short) - min(short)
        row["long_width"] = max(long) - min(long)
        row["separated_long"] = min(short) > max(long)
        row["separated_short"] = max(short) < min(long)
        row["ready"] = len(segment_rows) + 1 >= WARMUP_BARS
        order = _ordered(row) if row["ready"] else 0
        if order != previous_order:
            episode = int(row["open_ts_ms"]) if order else None
            armed = True
        previous = segment_rows[-1] if segment_rows else None
        event = False
        if previous is not None and previous["ready"] and order:
            if row["short_width"] > previous["short_width"]:
                armed = True
            directional = order * (row["g60"] - previous["g60"]) > 0
            separated = previous["separated_long" if order == 1 else "separated_short"]
            pullback = (
                row["low"] < previous["low"] and row["close"] < previous["close"]
                if order == 1
                else row["high"] > previous["high"] and row["close"] > previous["close"]
            )
            event = bool(
                armed
                and directional
                and separated
                and row["short_width"] < previous["short_width"]
                and row["long_width"] >= previous["long_width"]
                and pullback
            )
            if event:
                armed = False
        payload: dict[str, Any] = {
            "ctx_open_ts_ms": int(row["open_ts_ms"]),
            "ctx_close_ts_ms": int(row["close_ts_ms"]),
            "ctx_available_ts_ms": feature_available,
            "ctx_order": order,
            "ctx_episode_ts_ms": episode,
            "ctx_event_origin_ts_ms": int(row["open_ts_ms"]) if event else None,
            "ctx_event_available_ts_ms": feature_available if event else None,
            "ctx_event_low": float(row["low"]) if event else None,
            "ctx_event_high": float(row["high"]) if event else None,
            "ctx_pivot_open_ts_ms": None,
            "ctx_pivot_low": None,
            "ctx_pivot_high": None,
            "ctx_pivot_available_ts_ms": None,
        }
        if len(segment_rows) >= 2:
            left, pivot = segment_rows[-2:]
            payload["ctx_pivot_open_ts_ms"] = int(pivot["open_ts_ms"])
            payload["ctx_pivot_available_ts_ms"] = max(
                int(x["available_ts_ms"]) for x in (left, pivot, row)
            )
            if (
                pivot["low"] < left["low"]
                and pivot["low"] <= row["low"]
                and row["close"] > pivot["high"]
            ):
                payload["ctx_pivot_low"] = float(pivot["low"])
            if (
                pivot["high"] > left["high"]
                and pivot["high"] >= row["high"]
                and row["close"] < pivot["low"]
            ):
                payload["ctx_pivot_high"] = float(pivot["high"])
        out.append(payload)
        segment_rows.append(row)
        previous_order = order
    return out


def prepare_frames(
    frames15: dict[str, pd.DataFrame],
    frames30: dict[str, pd.DataFrame],
    costs: dict[str, float] | None = None,
) -> dict[str, pd.DataFrame]:
    """Join complete30m source prefixes by actual availability, never nearest."""
    del costs
    if set(frames15) != set(frames30):
        raise ValueError("RIDER_TIMEFRAME_SYMBOL_MISMATCH")
    prepared: dict[str, pd.DataFrame] = {}
    for symbol in sorted(frames15):
        rows, _ = execution._frame_records(frames15[symbol], 15)
        contexts = _features(frames30[symbol])
        by_available = sorted(
            contexts, key=lambda r: (r["ctx_available_ts_ms"], r["ctx_open_ts_ms"])
        )
        pointer = 0
        known: dict[str, Any] | None = None
        enriched: list[dict[str, Any]] = []
        last_decision = -1
        previous15 = None
        segment_start = 0
        for row in rows:
            if previous15 is None or not execution._can_follow(previous15, row):
                segment_start = int(row["open_ts_ms"])
            previous15 = row
            decision = int(row["available_ts_ms"])
            if decision < last_decision:
                raise ValueError("RIDER_DECISION_AVAILABILITY_ORDER_INVALID")
            last_decision = decision
            while pointer < len(by_available):
                context = by_available[pointer]
                if context["ctx_available_ts_ms"] > decision:
                    break
                if known is None or context["ctx_open_ts_ms"] > known["ctx_open_ts_ms"]:
                    known = context
                pointer += 1
            usable = known is not None and (
                known["ctx_open_ts_ms"] >= segment_start
                and known["ctx_close_ts_ms"] <= int(row["close_ts_ms"])
                and int(row["close_ts_ms"]) - known["ctx_close_ts_ms"] <= CONTEXT_MS
            )
            if usable:
                assert known is not None
                enriched.append({**row, **known, "ctx_usable": True})
            else:
                enriched.append({**row, "ctx_usable": False})
        prepared[symbol] = (
            pd.DataFrame(enriched) if enriched else frames15[symbol].copy()
        )
    return prepared


def _number(value: Any) -> bool:
    return value is not None and math.isfinite(float(value))


def generate_signals(
    frames: dict[str, pd.DataFrame],
    costs: dict[str, float] | None = None,
    identity: str = IDENTITY,
) -> list[dict[str, Any]]:
    """Both variants emit identical opportunities; lifecycle is the sole ablation."""
    del costs
    if identity not in IDENTITIES:
        raise ValueError("RIDER_ECONOMIC_IDENTITY_MISMATCH")
    signals: list[dict[str, Any]] = []
    for symbol in sorted(frames):
        frame = frames[symbol]
        if not frame.empty and "ctx_usable" not in frame:
            raise ValueError("RIDER_PREPARED_CONTEXT_REQUIRED")
        rows, _ = execution._frame_records(frame, 15)
        state: dict[str, Any] | None = None
        previous: dict[str, Any] | None = None
        seen: set[int] = set()
        for index, row in enumerate(rows):
            if previous is not None and not execution._can_follow(previous, row):
                state = None
                previous = None
            usable = bool(row.get("ctx_usable", False))
            if not usable:
                state = None
                previous = row
                continue
            decision = int(row["available_ts_ms"])
            order = int(row["ctx_order"])
            if state is not None and (
                order != state["side"]
                or decision - state["available"] > SETUP_TTL_BARS * TIMEFRAME_MS
                or row["ctx_episode_ts_ms"] != state["episode"]
            ):
                state = None
            origin = row.get("ctx_event_origin_ts_ms")
            if origin is not None and _number(origin) and int(origin) not in seen:
                origin = int(origin)
                seen.add(origin)
                available = int(row["ctx_event_available_ts_ms"])
                if order and decision - available <= SETUP_TTL_BARS * TIMEFRAME_MS:
                    observed = [
                        r
                        for r in rows[max(0, index - 4) : index + 1]
                        if int(r["open_ts_ms"]) >= origin
                        and int(r["available_ts_ms"]) <= decision
                    ]
                    state = {
                        "origin": origin,
                        "available": available,
                        "episode": int(row["ctx_episode_ts_ms"]),
                        "side": order,
                        "low": min(
                            [float(row["ctx_event_low"])]
                            + [float(r["low"]) for r in observed]
                        ),
                        "high": max(
                            [float(row["ctx_event_high"])]
                            + [float(r["high"]) for r in observed]
                        ),
                    }
            if state is not None:
                state["low"] = min(state["low"], float(row["low"]))
                state["high"] = max(state["high"], float(row["high"]))
                side = int(state["side"])
                reclaim = previous is not None and (
                    float(row["close"]) > float(previous["high"])
                    if side == 1
                    else float(row["close"]) < float(previous["low"])
                )
                if decision > state["available"] and reclaim:
                    assert previous is not None
                    key = {
                        "symbol": symbol,
                        "side": side,
                        "context_episode_ts_ms": state["episode"],
                        "compression_origin_ts_ms": state["origin"],
                    }
                    signals.append(
                        {
                            "identity": identity,
                            "lane": LANE,
                            "timeframe_min": TIMEFRAME_MIN,
                            "symbol": symbol,
                            "side": side,
                            "signal_open_ts_ms": int(row["open_ts_ms"]),
                            "signal_ts_ms": decision,
                            "segment_id": row["segment_id"],
                            "stop_price": state["low"] if side == 1 else state["high"],
                            "max_hold_bars": MAX_HOLD_BARS,
                            "take_profit_r": None,
                            "exit_policy": "RIDER_GMMA_CONFIRMED_PIVOT",
                            "meta": {
                                **key,
                                "opportunity_id": hashlib.sha256(
                                    json.dumps(key, sort_keys=True).encode()
                                ).hexdigest(),
                                "spec_sha256": SPEC_SHA256,
                                "exit_timeframe_min": (
                                    15 if identity == IDENTITY else 30
                                ),
                                "compression_available_ts_ms": state["available"],
                                "feature_available_ts_ms": decision,
                                "reclaim_reference_ts_ms": int(previous["open_ts_ms"]),
                                "reclaim_level": float(
                                    previous["high"] if side == 1 else previous["low"]
                                ),
                                "historical_outcome_features": False,
                            },
                        }
                    )
                    state = None
            previous = row
    return sorted(signals, key=lambda r: (r["signal_ts_ms"], r["symbol"]))


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    identity = position["signal"]["identity"]
    if identity not in IDENTITIES:
        raise ValueError("RIDER_ECONOMIC_POSITION_IDENTITY_MISMATCH")
    if identity == IDENTITY:
        return parent.exit_update(position, bar, history)
    result: dict[str, Any] = {
        "exit_next_open": False,
        "reason": "RIDER_30M_STRUCTURE_HOLD",
    }
    if not len(history) or int(history.iloc[-1]["close_ts_ms"]) != int(
        bar["close_ts_ms"]
    ):
        raise ValueError("RIDER_LIFECYCLE_PREFIX_MISMATCH")
    if not bool(bar.get("ctx_usable", False)):
        return result
    stamp = bar.get("ctx_pivot_open_ts_ms")
    available = bar.get("ctx_pivot_available_ts_ms")
    if (
        stamp is None
        or available is None
        or not _number(stamp)
        or not _number(available)
        or int(stamp) < int(position["entry_ts_ms"])
        or int(available) > int(bar["available_ts_ms"])
    ):
        return result
    side = int(position["side"])
    value = bar.get("ctx_pivot_low" if side == 1 else "ctx_pivot_high")
    if value is not None and _number(value):
        level = float(value)
        if (
            side * (level - float(position["stop_price"])) > 0
            and side * (float(bar["close"]) - level) > 0
        ):
            result.update(
                {"next_stop": level, "reason": "RIDER_CONFIRMED_30M_PULLBACK_PIVOT"}
            )
    return result
