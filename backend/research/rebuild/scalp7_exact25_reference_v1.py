"""Source-bound numerical reference components and causal pattern grammars.

No market replay, economic credit, order submission, or complete-source claim.
Numerical choices absent from source are explicit configured hypotheses.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules

SOURCES = {
    "anchor_vwap_trend": (
        "V2_SHANNON_ESSAY",
        "https://alphatrends.net/anchored-vwap/",
        "Q15",
    ),
    "vwap_revert": (
        "S307",
        "https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/",
        "Q06/Q15",
    ),
    "fvg_revert": ("S304", "https://www.youtube.com/watch?v=Bkt8B3kLATQ", "Q08"),
    "liquidity_sweep": (
        "S309",
        "https://tradingmarkets.com/recent/todays_trading_lesson_from_tradingmarkets-649736",
        "Q07",
    ),
    "sr_levels": (
        "V2_SHANNON_CASE",
        "https://alphatrends.net/archives/podcast/check-out-this-avwap-example/",
        "Q15/reference",
    ),
}
MODES = {
    "anchor_vwap_trend": ["FIXED_AVWAP_COMPONENT", "AVWAP_RECLAIM"],
    "vwap_revert": ["FIXED_VWAP_COMPONENT", "VWAP_FAILED_RETEST_SHORT"],
    "fvg_revert": ["THREE_BAR_GEOMETRY", "SWEEP_MSS_FVG_REVISIT"],
    "liquidity_sweep": ["TURTLE_SOUP_DAILY_LONG", "GENUINE_BBO_OFI_COMPONENT"],
    "sr_levels": ["FIXED_BOX_COMPONENT", "BOX_RETEST_RECLAIM"],
}


def catalog() -> dict[str, dict[str, Any]]:
    return {
        key: {
            "strategy_id": key,
            "modes": list(MODES[key]),
            "source_ids": [source[0]],
            "complete_strategy": False,
            "implementation": "RAW_NUMERICAL_COMPONENT_AND_CAUSAL_GRAMMAR",
            "economic_runs": 0,
        }
        for key, source in SOURCES.items()
    }


def _number(value: Any, name: str, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER:" + name)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_NUMBER:" + name) from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("INVALID_NUMBER:" + name)
    return result


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    result = _number(value, name)
    if result != int(result) or result < minimum:
        raise ValueError("INVALID_INTEGER:" + name)
    return int(result)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("MISSING_TEXT:" + name)
    return value


def _bars(frame: pd.DataFrame, minutes: int | None) -> list[dict[str, Any]]:
    required = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
    }
    if not required <= set(frame.columns):
        raise ValueError("CANONICAL_BAR_FIELDS_REQUIRED")
    result: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for original in frame.to_dict("records"):
        row = dict(original)
        for field in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            row[field] = _integer(row[field], field)
        _text(row["segment_id"], "segment_id")
        o, c, a = (row[x] for x in ("open_ts_ms", "close_ts_ms", "available_ts_ms"))
        if not o < c <= a or (minutes is not None and c - o != minutes * 60000):
            raise ValueError("INVALID_BAR_CLOCK_OR_TIMEFRAME")
        if previous is not None and (
            o < previous["close_ts_ms"] or a < previous["available_ts_ms"]
        ):
            raise ValueError("NONCHRONOLOGICAL_BARS")
        for field in ("open", "high", "low", "close"):
            row[field] = _number(row[field], field, True)
        if (
            not row["low"]
            <= min(row["open"], row["close"])
            <= max(row["open"], row["close"])
            <= row["high"]
        ):
            raise ValueError("INVALID_OHLC")
        row["continuous"] = (
            previous is not None
            and o == previous["close_ts_ms"]
            and row["segment_id"] == previous["segment_id"]
        )
        result.append(row)
        previous = row
    return result


def _rule(strategy: str, key: str, expression: str, unit: str) -> dict[str, Any]:
    source, locator, mode = SOURCES[strategy]
    return {
        "rule_id": key,
        "origin": "SOURCE_DIRECT",
        "expression": expression,
        "unit": unit,
        "version": "final-package-20260920",
        "source_id": source,
        "source_locator": locator,
        "source_mode": mode,
    }


def _choice(
    config: dict[str, Any], key: str, expression: str, unit: str
) -> dict[str, Any]:
    return {
        "rule_id": key,
        "origin": "DECLARED_HYPOTHESIS",
        "expression": expression,
        "unit": unit,
        "version": "configured-v1",
        "hypothesis_id": _text(config.get("hypothesis_id"), "hypothesis_id"),
        "rationale": _text(config.get("rationale"), "rationale"),
        "exact_source_reproduction": False,
    }


def _event(row: dict[str, Any], kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "event": kind,
        "event_ts_ms": row["close_ts_ms"],
        "available_ts_ms": row["available_ts_ms"],
        "segment_id": row["segment_id"],
        **extra,
    }


def _intent(
    result: dict[str, Any],
    row: dict[str, Any],
    config: dict[str, Any],
    side: int,
    kind: str,
    trigger: float | None,
    stop: float,
    expires: int,
    **extra: Any,
) -> None:
    known = row["available_ts_ms"]
    if known >= expires:
        result["events"].append(_event(row, "ORDER_EXPIRED_BEFORE_KNOWN"))
        return
    if stop <= 0 or (trigger is not None and side * (trigger - stop) <= 0):
        result["events"].append(_event(row, "INVALID_PROTECTIVE_STOP"))
        return
    result["intents"].append(
        {
            "strategy_id": result["strategy_id"],
            "mode_id": result["mode_id"],
            "symbol": _text(config.get("symbol"), "symbol"),
            "side": side,
            "setup_ts_ms": row["close_ts_ms"],
            "feature_available_ts_ms": known,
            "order_submit_ts_ms": known,
            "order_active_ts_ms": known,
            "decision_tf_min": config["timeframe_min"],
            "order_kind": kind,
            "trigger_price": trigger,
            "protective_stop": stop,
            "expires_ts_ms": expires,
            "lifecycle_gap": "FULL_POSITION_MANAGEMENT_NOT_BOUND",
            "execution_evidence": "INTENT_ONLY_NOT_FILL",
            **extra,
        }
    )


def _vwap(
    rows: list[dict[str, Any]], config: dict[str, Any], result: dict[str, Any]
) -> None:
    anchor = _integer(config.get("anchor_event_ts_ms"), "anchor_event_ts_ms")
    known = _integer(config.get("anchor_known_ts_ms"), "anchor_known_ts_ms")
    anchor_id = _text(config.get("anchor_id"), "anchor_id")
    basis = config.get("volume_basis")
    if basis not in {"BASE_QUOTE_SUMS", "HLC3_BASE_PROXY"}:
        raise ValueError("EXPLICIT_VOLUME_BASIS_REQUIRED")
    if config.get("volume_unit") != "BASE":
        raise ValueError("BASE_VOLUME_UNIT_REQUIRED")
    indices = [i for i, r in enumerate(rows) if r["open_ts_ms"] == anchor]
    if len(indices) != 1:
        raise ValueError("FIXED_ANCHOR_NOT_IN_INPUT_NO_ROLLING_SUBSTITUTE")
    start = indices[0]
    if known < rows[start]["available_ts_ms"]:
        raise ValueError("ANCHOR_KNOWN_BEFORE_OBSERVABLE_BAR")
    result["rules"] += [
        _rule(
            result["strategy_id"],
            "fixed_anchor",
            "Accumulate quote/base from fixed anchor; expose only at anchor_known_ts",
            "price=quote/base",
        ),
        _choice(
            config,
            "anchor_and_mode",
            f"anchor={anchor}, known={known}, basis={basis}, mode={result['mode_id']}",
            "timestamp_ms/price",
        ),
    ]
    component = "COMPONENT" in result["mode_id"]
    ttl = (
        0
        if component
        else _integer(config.get("intent_ttl_bars"), "intent_ttl_bars", 1)
    )
    if not component:
        result["rules"].append(
            _choice(
                config,
                "close_confirmation",
                f"Completed-price retest/reclaim; setup extreme stop; intent expiry={ttl} decision bars",
                "bars/price",
            )
        )
    numerator = denominator = 0.0
    state = "WAIT"
    extreme: float | None = None
    broken = False
    for i in range(start, len(rows)):
        row = rows[i]
        if i > start and not row["continuous"]:
            broken = True
            result["events"].append(
                _event(row, "ANCHOR_CUMULATION_GAP_BLOCKED", reference_id=anchor_id)
            )
        if broken:
            continue
        if "volume_unit" in row and row["volume_unit"] != "BASE":
            raise ValueError("MIXED_VOLUME_UNITS")
        if basis == "BASE_QUOTE_SUMS":
            base = _number(row.get("volume_base"), "volume_base")
            quote = _number(row.get("volume_quote"), "volume_quote")
            if (
                base < 0
                or quote < 0
                or (base == 0 and quote != 0)
                or (base > 0 and not row["low"] <= quote / base <= row["high"])
            ):
                raise ValueError("INVALID_BASE_QUOTE_SUMS")
        else:
            base = _number(row.get("volume"), "volume")
            if base < 0:
                raise ValueError("NEGATIVE_VOLUME")
            quote = base * (row["high"] + row["low"] + row["close"]) / 3
        numerator += quote
        denominator += base
        if row["available_ts_ms"] < known:
            continue
        value = numerator / denominator if denominator > 0 else None
        result["components"].append(
            {
                "component": "FIXED_ANCHOR_VWAP",
                "reference_id": anchor_id,
                "anchor_event_ts_ms": anchor,
                "anchor_known_ts_ms": known,
                "available_ts_ms": row["available_ts_ms"],
                "value": value,
                "cumulative_base": denominator,
                "basis": basis,
                "trade_vwap_claim": basis == "BASE_QUOTE_SUMS",
            }
        )
        if value is None or component:
            continue
        if result["mode_id"] == "AVWAP_RECLAIM":
            if row["close"] < value:
                state = "BELOW"
                extreme = row["low"] if extreme is None else min(extreme, row["low"])
            elif state == "BELOW" and row["low"] <= value < row["close"]:
                assert extreme is not None
                stop = min(extreme, row["low"])
                result["events"].append(
                    _event(
                        row,
                        "AVWAP_RECLAIM_CONFIRMED",
                        reference_id=anchor_id,
                        value=value,
                    )
                )
                _intent(
                    result,
                    row,
                    config,
                    1,
                    "NEXT_OPEN",
                    None,
                    stop,
                    row["available_ts_ms"] + ttl * config["timeframe_min"] * 60000,
                    reference_id=anchor_id,
                )
                state, extreme = "WAIT", None
        else:
            if row["close"] > value:
                state, extreme = "ABOVE", None
            elif state == "ABOVE" and row["close"] < value:
                state, extreme = "BELOW_AFTER_BREAK", row["high"]
                result["events"].append(
                    _event(row, "VWAP_BREAKDOWN", reference_id=anchor_id)
                )
            elif state == "BELOW_AFTER_BREAK" and row["high"] >= value > row["close"]:
                assert extreme is not None
                stop = max(extreme, row["high"])
                result["events"].append(
                    _event(
                        row,
                        "VWAP_RETEST_FAILURE_CONFIRMED",
                        reference_id=anchor_id,
                        value=value,
                    )
                )
                _intent(
                    result,
                    row,
                    config,
                    -1,
                    "NEXT_OPEN",
                    None,
                    stop,
                    row["available_ts_ms"] + ttl * config["timeframe_min"] * 60000,
                    reference_id=anchor_id,
                )
                state, extreme = "WAIT", None
    result["limitations"] += [
        "Anchor selection is supplied and declared, not an automatic Shannon taxonomy.",
        "Full position exits and sizing are unbound.",
        "HLC3_BASE_PROXY is candle approximation, not observed trade VWAP.",
    ]


def _fvg(
    rows: list[dict[str, Any]], config: dict[str, Any], result: dict[str, Any]
) -> None:
    result["rules"].append(
        _rule(
            "fvg_revert",
            "three_bar_geometry",
            "Bull low[t]>high[t-2]; bear high[t]<low[t-2]; zone known after third completed bar",
            "price/3 bars",
        )
    )
    full = result["mode_id"] == "SWEEP_MSS_FVG_REVISIT"
    left = right = expiry = 0
    body_fraction = 0.0
    if full:
        left = _integer(config.get("swing_left"), "swing_left", 1)
        right = _integer(config.get("swing_right"), "swing_right", 1)
        expiry = _integer(config.get("setup_expiry_bars"), "setup_expiry_bars", 1)
        body_fraction = _number(
            config.get("displacement_min_body_fraction"),
            "displacement_min_body_fraction",
        )
        if not 0 <= body_fraction <= 1:
            raise ValueError("INVALID_BODY_FRACTION")
        result["rules"].append(
            _choice(
                config,
                "swing_displacement_expiry",
                f"strict pivot left={left},right={right}; body/range>={body_fraction}; expiry={expiry}; sweep-extreme stop; proximal resting limit",
                "bars/ratio/price",
            )
        )
    pivots: dict[str, dict[str, Any]] = {}
    setup: dict[str, Any] | None = None
    zones: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if i and not row["continuous"]:
            pivots, setup, zones = {}, None, []
            result["events"].append(_event(row, "GAP_INVALIDATION"))
        for zone in list(zones):
            if row["open_ts_ms"] < zone["known"]:
                continue
            invalid = (
                row["low"] <= zone["stop"]
                if zone["side"] == 1
                else row["high"] >= zone["stop"]
            )
            touch = row["low"] <= zone["upper"] and row["high"] >= zone["lower"]
            if row["open_ts_ms"] >= zone["expires"]:
                result["events"].append(_event(row, "ZONE_EXPIRED", zone_id=zone["id"]))
                zones.remove(zone)
            elif invalid:
                result["events"].append(
                    _event(
                        row,
                        "TOUCH_STOP_ORDER_UNRESOLVED" if touch else "ZONE_INVALIDATED",
                        zone_id=zone["id"],
                    )
                )
                zones.remove(zone)
            elif touch:
                result["events"].append(
                    _event(row, "ZONE_TOUCH_NOT_OBSERVED_FILL", zone_id=zone["id"])
                )
                zones.remove(zone)
        if full and setup is not None:
            if i - setup["index"] > expiry:
                result["events"].append(_event(row, "SWEEP_SETUP_EXPIRED"))
                setup = None
            elif row["open_ts_ms"] >= setup["known"] and i > setup["index"]:
                if (setup["side"] == 1 and row["low"] < setup["stop"]) or (
                    setup["side"] == -1 and row["high"] > setup["stop"]
                ):
                    result["events"].append(_event(row, "SWEEP_SETUP_INVALIDATED"))
                    setup = None
                elif setup["mss_known"] is None:
                    cross = setup["side"] * (row["close"] - setup["structure"]) > 0
                    span = row["high"] - row["low"]
                    displacement = (
                        span > 0
                        and abs(row["close"] - row["open"]) / span >= body_fraction
                        and setup["side"] * (row["close"] - row["open"]) > 0
                    )
                    if cross and displacement:
                        setup["mss_known"] = row["available_ts_ms"]
                        result["events"].append(
                            _event(
                                row, "MSS_DISPLACEMENT_CONFIRMED", side=setup["side"]
                            )
                        )
        if i >= 2 and rows[i - 1]["continuous"] and row["continuous"]:
            first = rows[i - 2]
            side = (
                1
                if row["low"] > first["high"]
                else -1 if row["high"] < first["low"] else 0
            )
            if side:
                lower, upper = (
                    (first["high"], row["low"])
                    if side == 1
                    else (row["high"], first["low"])
                )
                zid = f"fvg:{first['open_ts_ms']}:{row['close_ts_ms']}:{side}"
                result["components"].append(
                    {
                        "component": "THREE_BAR_FVG",
                        "zone_id": zid,
                        "side": side,
                        "lower": lower,
                        "upper": upper,
                        "available_ts_ms": row["available_ts_ms"],
                        "institutional_flow_observed": False,
                    }
                )
                if (
                    full
                    and setup is not None
                    and setup["side"] == side
                    and setup["mss_known"] is not None
                    and first["open_ts_ms"] >= setup["event_open"]
                ):
                    expires = (
                        row["available_ts_ms"]
                        + expiry * config["timeframe_min"] * 60000
                    )
                    result["events"].append(
                        _event(row, "SWEEP_MSS_FVG_READY", zone_id=zid)
                    )
                    _intent(
                        result,
                        row,
                        config,
                        side,
                        "LIMIT",
                        upper if side == 1 else lower,
                        setup["stop"],
                        expires,
                        zone_id=zid,
                    )
                    zones.append(
                        {
                            "id": zid,
                            "known": row["available_ts_ms"],
                            "lower": lower,
                            "upper": upper,
                            "side": side,
                            "stop": setup["stop"],
                            "expires": expires,
                        }
                    )
                    setup = None
        if full and setup is None and "low" in pivots and "high" in pivots:
            lo, hi = pivots["low"], pivots["high"]
            if max(lo["known"], hi["known"]) <= row["open_ts_ms"]:
                side = (
                    1
                    if row["low"] < lo["value"] < row["close"]
                    else -1 if row["high"] > hi["value"] > row["close"] else 0
                )
                if side:
                    setup = {
                        "side": side,
                        "stop": row["low"] if side == 1 else row["high"],
                        "structure": hi["value"] if side == 1 else lo["value"],
                        "known": row["available_ts_ms"],
                        "index": i,
                        "event_open": row["open_ts_ms"],
                        "mss_known": None,
                    }
                    result["events"].append(_event(row, "PRIOR_LEVEL_SWEEP", side=side))
        if full and i >= left + right:
            center = i - right
            window = rows[center - left : i + 1]
            if all(r["continuous"] for r in window[1:]):
                for field, fn in (("low", min), ("high", max)):
                    neighbors = [r[field] for j, r in enumerate(window) if j != left]
                    candidate = rows[center][field]
                    if (field == "low" and candidate < fn(neighbors)) or (
                        field == "high" and candidate > fn(neighbors)
                    ):
                        pivots[field] = {
                            "value": candidate,
                            "known": row["available_ts_ms"],
                        }
                        result["events"].append(
                            _event(
                                row,
                                "CONFIRMED_SWING",
                                field=field,
                                value=candidate,
                                pivot_open_ts_ms=rows[center]["open_ts_ms"],
                            )
                        )
    result["limitations"] += [
        "Gap-only geometry is not the full ICT model.",
        "Configured pivot/displacement/expiry/stop choices are adaptations.",
        "Limit touches and institutional absorption are not observed fills or order flow.",
        "Full partial exits and target management remain unbound.",
    ]


def _box(
    rows: list[dict[str, Any]], config: dict[str, Any], result: dict[str, Any]
) -> None:
    start = _integer(config.get("reference_start_ts_ms"), "reference_start_ts_ms")
    end = _integer(config.get("reference_end_ts_ms"), "reference_end_ts_ms")
    known = _integer(config.get("reference_known_ts_ms"), "reference_known_ts_ms")
    rid = _text(config.get("reference_id"), "reference_id")
    reference_type = config.get("reference_type")
    if reference_type not in {"DECLARED_PRIOR_BOX", "DECLARED_PRIOR_SESSION"}:
        raise ValueError("EXPLICIT_REFERENCE_TYPE_REQUIRED")
    selected = [r for r in rows if start <= r["open_ts_ms"] and r["close_ts_ms"] <= end]
    if (
        not selected
        or selected[0]["open_ts_ms"] != start
        or selected[-1]["close_ts_ms"] != end
        or not all(r["continuous"] for r in selected[1:])
    ):
        raise ValueError("COMPLETE_FIXED_REFERENCE_REQUIRED")
    if known < max(r["available_ts_ms"] for r in selected):
        raise ValueError("REFERENCE_NOT_YET_KNOWN")
    lower, upper = min(r["low"] for r in selected), max(r["high"] for r in selected)
    result["rules"].append(
        _choice(
            config,
            "fixed_reference",
            f"Reference {reference_type} [{start},{end}) known={known}; strict close breakout, later retest/reclaim; opposite fixed box edge stop",
            "timestamp_ms/price",
        )
    )
    result["components"].append(
        {
            "component": "FIXED_REFERENCE",
            "reference_id": rid,
            "reference_type": reference_type,
            "lower": lower,
            "upper": upper,
            "available_ts_ms": known,
            "current_trigger_bar_excluded": True,
        }
    )
    if result["mode_id"] == "FIXED_BOX_COMPONENT":
        return
    ttl = _integer(config.get("intent_ttl_bars"), "intent_ttl_bars", 1)
    result["rules"].append(
        _choice(
            config,
            "intent_expiry",
            f"Intent expires {ttl} decision bars after confirmation",
            "bars",
        )
    )
    state = 0
    invalid = False
    for row in rows:
        if row["open_ts_ms"] < known:
            continue
        if not row["continuous"] or row["segment_id"] != selected[-1]["segment_id"]:
            invalid = True
            result["events"].append(
                _event(row, "FIXED_REFERENCE_GAP_INVALIDATION", reference_id=rid)
            )
        if invalid:
            continue
        if state == 0:
            state = 1 if row["close"] > upper else -1 if row["close"] < lower else 0
            if state:
                result["events"].append(
                    _event(
                        row, "FIXED_REFERENCE_BREAKOUT", side=state, reference_id=rid
                    )
                )
        elif (state == 1 and row["close"] < upper) or (
            state == -1 and row["close"] > lower
        ):
            result["events"].append(
                _event(row, "BOX_REENTRY_FAILURE", reference_id=rid)
            )
            invalid = True
        elif (state == 1 and row["low"] <= upper < row["close"]) or (
            state == -1 and row["high"] >= lower > row["close"]
        ):
            result["events"].append(
                _event(
                    row, "FIXED_REFERENCE_RETEST_RECLAIM", side=state, reference_id=rid
                )
            )
            _intent(
                result,
                row,
                config,
                state,
                "NEXT_OPEN",
                None,
                lower if state == 1 else upper,
                row["available_ts_ms"] + ttl * config["timeframe_min"] * 60000,
                reference_id=rid,
            )
            invalid = True
    result["limitations"] += [
        "Box/session selection is a declared hypothesis; not a complete Carter detector.",
        "Frozen edges never move to include the breakout or failure candle.",
        "Full position lifecycle is unbound; no inherited time scratch.",
    ]


def _soup(
    rows: list[dict[str, Any]],
    frames: dict[str, pd.DataFrame],
    config: dict[str, Any],
    result: dict[str, Any],
) -> None:
    if (
        config.get("source_timeframe") != "1d"
        or config.get("daily_calendar") != "EXPLICIT_SESSIONS"
    ):
        raise ValueError("NATIVE_DAILY_CALENDAR_REQUIRED")
    if "1d" not in frames:
        raise ValueError("DAILY_HISTORY_REQUIRED_NOT_INTRADAY_SUBSTITUTE")
    daily = _bars(frames["1d"], 1440)
    for i, row in enumerate(daily):
        row["session_index"] = _integer(row.get("session_index"), "session_index")
        if i and row["session_index"] <= daily[i - 1]["session_index"]:
            raise ValueError("DAILY_SESSION_ORDER_INVALID")
    sessions = config.get("session_bounds")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("EXPLICIT_SESSION_BOUNDS_REQUIRED")
    previous_end = -1
    for session in sessions:
        opened = _integer(session.get("open_ts_ms"), "session_open")
        closed = _integer(session.get("close_ts_ms"), "session_close")
        if not previous_end <= opened < closed:
            raise ValueError("INVALID_SESSION_BOUNDS")
        _text(session.get("session_id"), "session_id")
        previous_end = closed
    tick = _number(config.get("tick_size"), "tick_size", True)
    offset = _integer(config.get("entry_offset_ticks"), "entry_offset_ticks", 5)
    buffer_ticks = _integer(config.get("stop_buffer_ticks"), "stop_buffer_ticks", 1)
    if offset > 10:
        raise ValueError("SOURCE_ENTRY_OFFSET_REQUIRES_5_TO_10_TICKS")
    result["rules"] += [
        _rule(
            "liquidity_sweep",
            "native_soup",
            "Prior 20 DAILY session extreme excluding current session; most recent tied extreme age>=4 DAILY sessions; new low then stop entry old low+5..10 ticks; same-session cancellation",
            "daily_sessions/ticks",
        ),
        _choice(
            config,
            "calendar_stop_buffer",
            f"Explicit session calendar, tick={tick}, offset={offset}, protective current-session-low minus {buffer_ticks} ticks; completed decision-bar recognition",
            "price/ticks/15m_or_30m",
        ),
    ]
    state: dict[str, Any] | None = None
    for row in rows:
        matching = [
            s
            for s in sessions
            if s["open_ts_ms"] <= row["open_ts_ms"]
            and row["close_ts_ms"] <= s["close_ts_ms"]
        ]
        if len(matching) != 1:
            raise ValueError("BAR_OUTSIDE_EXPLICIT_SESSION")
        session = matching[0]
        if state is None or state["id"] != session["session_id"]:
            history = [
                d
                for d in daily
                if d["close_ts_ms"] <= session["open_ts_ms"]
                and d["available_ts_ms"] <= session["open_ts_ms"]
            ][-20:]
            good = len(history) == 20 and all(
                history[j]["session_index"] == history[j - 1]["session_index"] + 1
                and history[j]["segment_id"] == history[j - 1]["segment_id"]
                for j in range(1, 20)
            )
            state = {
                "id": session["session_id"],
                "valid": good and row["open_ts_ms"] == session["open_ts_ms"],
                "low": row["low"],
                "issued": False,
            }
            if good:
                old = min(d["low"] for d in history)
                latest = max(j for j, d in enumerate(history) if d["low"] == old)
                state.update(old=old, age=20 - latest)
                result["components"].append(
                    {
                        "component": "PRIOR_20_DAILY_LOW",
                        "reference_id": state["id"],
                        "value": old,
                        "age_daily_sessions": state["age"],
                        "available_ts_ms": session["open_ts_ms"],
                        "current_session_excluded": True,
                    }
                )
            else:
                result["events"].append(_event(row, "DAILY_HISTORY_INCOMPLETE"))
        elif not row["continuous"]:
            state["valid"] = False
            result["events"].append(_event(row, "CURRENT_SESSION_GAP_BLOCKED"))
        state["low"] = min(state["low"], row["low"])
        if (
            state["valid"]
            and not state["issued"]
            and state["age"] >= 4
            and row["low"] < state["old"]
        ):
            trigger = state["old"] + offset * tick
            result["events"].append(
                _event(
                    row,
                    "NEW_DAILY_LOW_RECOVERY_ORDER_READY",
                    old_low=state["old"],
                    age_daily_sessions=state["age"],
                )
            )
            _intent(
                result,
                row,
                config,
                1,
                "STOP_MARKET",
                trigger,
                state["low"] - buffer_ticks * tick,
                session["close_ts_ms"],
                reference_id=state["id"],
                cancellation="SAME_SESSION_END",
                protective_reference="CURRENT_SESSION_LOW_AT_ORDER_RECOGNITION",
            )
            state["issued"] = True
    result["limitations"] += [
        "This path requires actual 24-hour daily source bars and an explicit session calendar; other session durations are not silently accepted.",
        "Completed 15m/30m recognition is an explicit execution adaptation of daily Soup, not retrospective intraday fill.",
        "Plus One is not implemented or silently combined with same-day Soup.",
        "No synthetic order-flow/absorption; full trailing management remains unbound.",
    ]


def _ofi(
    frame: pd.DataFrame | None, config: dict[str, Any], result: dict[str, Any]
) -> None:
    if frame is None or config.get("genuine_bbo") is not True:
        raise ValueError("GENUINE_BBO_REQUIRED_NO_OHLC_SUBSTITUTE")
    receipt = _text(config.get("source_receipt_sha256"), "source_receipt_sha256")
    if len(receipt) != 64 or any(c not in "0123456789abcdef" for c in receipt):
        raise ValueError("SOURCE_RECEIPT_SHA256_REQUIRED")
    rule = _rule(
        "liquidity_sweep",
        "cont_ofi",
        "e=I(bid>=prev_bid)*bid_size-I(bid<=prev_bid)*prev_bid_size-I(ask<=prev_ask)*ask_size+I(ask>=prev_ask)*prev_ask_size",
        "base_quantity",
    )
    rule.update(
        source_id="R23",
        source_locator="https://arxiv.org/abs/1011.6402",
        source_mode="Q19_OFI_COMPONENT",
    )
    result["rules"].append(rule)
    if config.get("volume_unit") != "BASE":
        raise ValueError("BASE_QUANTITY_REQUIRED")
    previous: dict[str, Any] | None = None
    for source in frame.to_dict("records"):
        row = dict(source)
        for key in ("ts_ms", "available_ts_ms", "sequence"):
            row[key] = _integer(row.get(key), key)
        _text(row.get("segment_id"), "segment_id")
        for key in ("bid", "ask", "bid_size", "ask_size"):
            row[key] = _number(row.get(key), key, key in {"bid", "ask"})
        if (
            row["bid"] >= row["ask"]
            or min(row["bid_size"], row["ask_size"]) < 0
            or row["available_ts_ms"] < row["ts_ms"]
        ):
            raise ValueError("INVALID_BBO")
        if previous is not None:
            if (
                row["ts_ms"] < previous["ts_ms"]
                or row["available_ts_ms"] < previous["available_ts_ms"]
            ):
                raise ValueError("NONCHRONOLOGICAL_BBO")
            if (
                row["segment_id"] == previous["segment_id"]
                and row["sequence"] == previous["sequence"] + 1
            ):
                value = (
                    (row["bid_size"] if row["bid"] >= previous["bid"] else 0)
                    - (previous["bid_size"] if row["bid"] <= previous["bid"] else 0)
                    - (row["ask_size"] if row["ask"] <= previous["ask"] else 0)
                    + (previous["ask_size"] if row["ask"] >= previous["ask"] else 0)
                )
                result["components"].append(
                    {
                        "component": "CONT_BBO_OFI",
                        "value": value,
                        "available_ts_ms": row["available_ts_ms"],
                        "sequence": row["sequence"],
                        "source_receipt_sha256": receipt,
                    }
                )
            else:
                result["events"].append(
                    {
                        "event": "BBO_SEQUENCE_RESET_NO_BRIDGE",
                        "available_ts_ms": row["available_ts_ms"],
                    }
                )
        previous = row
    result["limitations"].append(
        "BBO OFI is a feature, not a standalone trading strategy; no reconstructed L2 or queue."
    )


def _evaluate_one(
    strategy_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    if strategy_id not in SOURCES:
        raise ValueError("UNKNOWN_REFERENCE_STRATEGY")
    mode = config.get("mode_id")
    result: dict[str, Any] = {
        "strategy_id": strategy_id,
        "mode_id": mode,
        "events": [],
        "intents": [],
        "components": [],
        "rules": [],
        "limitations": [],
        "complete_strategy": False,
        "status": "COMPONENT_AND_GRAMMAR_ONLY",
        "economic_runs": 0,
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
    }
    try:
        if mode not in MODES[strategy_id]:
            raise ValueError("EXPLICIT_SUPPORTED_MODE_REQUIRED")
        tf = _integer(config.get("timeframe_min"), "timeframe_min")
        if tf not in (15, 30):
            raise ValueError("DECISION_TIMEFRAME_MUST_BE_15_OR_30")
        _text(config.get("source_clock"), "source_clock")
        if mode == "GENUINE_BBO_OFI_COMPONENT":
            _ofi(frames.get("bbo"), config, result)
        else:
            frame = frames.get(f"{tf}m", frames.get("decision"))
            if frame is None:
                raise ValueError("DECISION_FRAME_REQUIRED")
            rows = _bars(frame, tf)
            if not rows:
                raise ValueError("DECISION_FRAME_EMPTY")
            if strategy_id in {"anchor_vwap_trend", "vwap_revert"}:
                _vwap(rows, config, result)
            elif strategy_id == "fvg_revert":
                _fvg(rows, config, result)
            elif strategy_id == "sr_levels":
                _box(rows, config, result)
            else:
                _soup(rows, frames, config, result)
        result["rule_digest"] = validate_rules(result["rules"])
    except (ValueError, KeyError, TypeError) as exc:
        result.update(
            status="BLOCKED_ITEM_CONFIGURATION_OR_DATA",
            error=str(exc),
            intents=[],
            components=[],
            events=[],
            rule_digest=None,
        )
        result["limitations"].append(str(exc))
    return result


def evaluate(
    strategy_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate symbol-keyed canonical frames; daily_frames are separately keyed.

    Direct decision/15m/30m/1d/bbo keys remain supported for component fixtures.
    Per-symbol anchor/reference choices can be supplied in symbol_configs.
    """
    if not frames or set(frames) & {"decision", "15m", "30m", "1d", "bbo"}:
        return _evaluate_one(strategy_id, frames, config)
    outputs = {}
    for symbol, frame in frames.items():
        own = {
            **config,
            **config.get("symbol_configs", {}).get(symbol, {}),
            "symbol": symbol,
        }
        inputs = {"decision": frame}
        daily = config.get("daily_frames", {}).get(symbol)
        if daily is not None:
            inputs["1d"] = daily
        if own.get("mode_id") == "GENUINE_BBO_OFI_COMPONENT":
            inputs = {"bbo": frame}
        outputs[symbol] = _evaluate_one(strategy_id, inputs, own)
    result: dict[str, Any] = {
        "strategy_id": strategy_id,
        "mode_id": config.get("mode_id"),
        "events": [],
        "intents": [],
        "components": [],
        "rules": [],
        "limitations": [],
        "complete_strategy": False,
        "status": "COMPONENT_AND_GRAMMAR_ONLY",
        "economic_runs": 0,
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
        "per_symbol": outputs,
    }
    blocked = 0
    for symbol, output in outputs.items():
        blocked += int(output["status"].startswith("BLOCKED"))
        for key in ("events", "intents", "components"):
            result[key].extend({**row, "symbol": symbol} for row in output[key])
        result["rules"].extend(
            {**row, "rule_id": symbol + ":" + row["rule_id"]} for row in output["rules"]
        )
        result["limitations"].extend(
            symbol + ":" + item for item in output["limitations"]
        )
    result["rule_digest"] = validate_rules(result["rules"]) if result["rules"] else None
    if blocked:
        result["status"] = (
            "BLOCKED_ITEM_CONFIGURATION_OR_DATA"
            if blocked == len(outputs)
            else "PARTIAL_SYMBOLS_BLOCKED"
        )
    return result
