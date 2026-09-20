"""Raw-price structure producers for six exact25 rows; no trading authority.

Qualitative source grammar is bound separately from explicit numeric hypotheses.
Every output is a partial research intent: no fill, size, expiry or exit invented.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import pandas as pd

from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules

VERSION = "exact25.structure.v1"
MODES = {
    "ema_ribbon_scalp": ("KELL_BASE_BREAK_DECLARED",),
    "keltner_trend": ("HG_1997_CONDITIONAL", "HG_2004_MOMENTUM_CASE"),
    "pivot_reversal": ("KELL_REVERSAL_PIVOT_DECLARED",),
    "range_fade": ("ANTI_IMPULSE_CONTINUATION_DECLARED",),
    "scalp_snap": ("GAJJALA_FLAG_15M_DECLARED", "SHORT_SKIRT_NATIVE_UNAVAILABLE"),
    "vol_spike_fade": ("PARABOLIC_FIRST_CRACK_RETEST_DECLARED",),
}
SOURCES = {
    "ema_ribbon_scalp": ("S305,S306", "Kell ARM / reversal-extension case sections"),
    "keltner_trend": ("R09,S312", "August1997 p2; March2004 printed78 Figure1"),
    "pivot_reversal": ("S306", "Reversal Extension watch versus pivot; SWAV failure"),
    "range_fade": ("S314", "Raschke FAQ Anti; final correction C02"),
    "scalp_snap": ("S301", "Gajjala interview: 5m/15m impulse and low-volume flag"),
    "vol_spike_fade": ("S307", "Qullamaggie three setups: parabolic short"),
}
LIMITATIONS = [
    "PARTIAL_INTENT_ONLY: quantity, expiry, order latency and full exit management absent",
    "OHLC event or stop level is not an observed fill; intrabar ordering unresolved",
    "Numeric qualitative-pattern translations are declared hypotheses, not source defaults",
    "No economic evaluation, promotion, order or LIVE authority",
]


ROW_GAPS = {
    "ema_ribbon_scalp": "Kell six-phase classification, higher-timeframe selection and staged partial exits/size remain unspecified; numeric watch/base/pivot is a declared translation",
    "keltner_trend": "Source conditional order has no inferred fill; source trailing/re-entry/order expiry/size remain incomplete; qualification expiry and rearm are explicit hypotheses",
    "pivot_reversal": "Kell discretionary support/pivot classifier is a declared translation; current EMA target is contextual only, not a live moving-target exit",
    "range_fade": "Anti continuation only; no Soup/BBIII range-reversal implementation claimed; small-flag thresholds and close confirmation are declared hypotheses",
    "scalp_snap": "Gajjala qualitative stock selection and discretionary management absent; 15m flag adaptation only; Short Skirt 1m and 2-10min holding cannot be recovered from 15m candles",
    "vol_spike_fade": "Qullamaggie source is stocks; UTC24h daily history is explicitly a crypto adaptation; price-retest mode only, no VWAP-failure or borrow-equivalence claim; split exits absent",
}
PARAMETERS = {
    "ema_ribbon_scalp": [
        "ema_length",
        "pivot_left_bars",
        "pivot_right_bars",
        "base_bars",
        "base_range_ratio",
        "watch_extension_fraction",
        "setup_expiry_bars",
        "tick_size",
    ],
    "pivot_reversal": [
        "ema_length",
        "pivot_left_bars",
        "pivot_right_bars",
        "base_bars",
        "base_range_ratio",
        "watch_extension_fraction",
        "setup_expiry_bars",
        "tick_size",
    ],
    "keltner_trend": [
        "requalification_adx_below",
        "qualification_expiry_bars",
        "tick_size",
    ],
    "range_fade": [
        "impulse_lookback_bars",
        "impulse_range_multiple",
        "flag_max_retracement_fraction",
        "flag_min_bars",
        "flag_max_bars",
        "tick_size",
    ],
    "scalp_snap": [
        "impulse_lookback_bars",
        "impulse_range_multiple",
        "flag_max_retracement_fraction",
        "flag_min_bars",
        "flag_max_bars",
        "pullback_volume_ratio",
        "tick_size",
    ],
    "vol_spike_fade": [
        "extension_sessions",
        "extension_return_fraction",
        "max_rebound_fraction",
        "tick_size",
        "daily_frames",
        "daily_calendar",
    ],
}


def catalog() -> dict[str, dict[str, Any]]:
    return {
        key: {
            "strategy_id": key,
            "mode_ids": list(modes),
            "input_kind": "RAW_OHLCV_CAUSAL_PRODUCER",
            "implementation_status": "PARTIAL_SOURCE_GRAMMAR_WITH_DECLARED_NUMERICS",
            "complete_strategy": False,
            "source_ids": SOURCES[key][0].split(","),
            "required_common_config": ["timeframe_min", "mode_id", "hypothesis_id"],
            "required_mode_parameters": PARAMETERS[key],
            "remaining_gap": ROW_GAPS[key],
        }
        for key, modes in MODES.items()
    }


def _number(config: dict[str, Any], key: str, *, integer: bool = False) -> float:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("EXPLICIT_NUMERIC_PARAMETER_REQUIRED:" + key)
    if not math.isfinite(value) or value <= 0 or (integer and int(value) != value):
        raise ValueError("INVALID_NUMERIC_PARAMETER:" + key)
    return float(value)


def _text(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("EXPLICIT_TEXT_PARAMETER_REQUIRED:" + key)
    return value


def _frame(frame: pd.DataFrame, minutes: int) -> list[list[dict[str, Any]]]:
    required = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    if not required.issubset(frame.columns):
        raise ValueError("CANONICAL_FRAME_REQUIRED")
    segments: list[list[dict[str, Any]]] = []
    previous: dict[str, Any] | None = None
    for raw in frame.to_dict("records"):
        row = dict(raw)
        for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            value = row[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or int(value) != value
                or value < 0
            ):
                raise ValueError("INVALID_TIMESTAMP:" + key)
            row[key] = int(value)
        if not row["open_ts_ms"] < row["close_ts_ms"] <= row["available_ts_ms"]:
            raise ValueError("BAR_CLOCK_NOT_CAUSAL")
        if row["close_ts_ms"] - row["open_ts_ms"] not in (
            minutes * 60000,
            minutes * 60000 - 1,
        ):
            raise ValueError("NATIVE_TIMEFRAME_MISMATCH")
        if not isinstance(row["segment_id"], str) or not row["segment_id"]:
            raise ValueError("SEGMENT_ID_REQUIRED")
        for key in ("open", "high", "low", "close", "volume"):
            value = row[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or (key != "volume" and value == 0)
            ):
                raise ValueError("INVALID_OHLCV:" + key)
            row[key] = float(value)
        if (
            not row["low"]
            <= min(row["open"], row["close"])
            <= max(row["open"], row["close"])
            <= row["high"]
        ):
            raise ValueError("OHLC_GEOMETRY_INVALID")
        if previous and (
            row["open_ts_ms"] <= previous["open_ts_ms"]
            or row["available_ts_ms"] <= previous["available_ts_ms"]
        ):
            raise ValueError("NONMONOTONIC_FRAME")
        if (
            previous is None
            or row["segment_id"] != previous["segment_id"]
            or row["open_ts_ms"] - previous["open_ts_ms"] != minutes * 60000
        ):
            segments.append([])
        segments[-1].append(row)
        previous = row
    return segments


def _smooth(values: list[float], period: int, alpha: float) -> list[float]:
    out = [float("nan")] * len(values)
    if len(values) < period:
        return out
    out[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return out


def _measures(rows: list[dict[str, Any]], ema_length: int = 20) -> list[dict[str, Any]]:
    """Explicit SMA-seeded EMA and Wilder ADX14; each physical segment rewarms."""
    close = [r["close"] for r in rows]
    ema = _smooth(close, ema_length, 2 / (ema_length + 1))
    tr, plus, minus = [], [], []
    for i in range(1, len(rows)):
        r, p = rows[i], rows[i - 1]
        tr.append(
            max(
                r["high"] - r["low"],
                abs(r["high"] - p["close"]),
                abs(r["low"] - p["close"]),
            )
        )
        up, down = r["high"] - p["high"], p["low"] - r["low"]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
    atr, pos, neg = [_smooth(v, 14, 1 / 14) for v in (tr, plus, minus)]
    dx = [
        100 * abs(p - n) / (p + n) if p + n > 0 else 0.0
        for p, n in zip(pos[13:], neg[13:])
    ]
    adx = [float("nan")] * 27 + _smooth(dx, 14, 1 / 14)[13:]
    osc = pd.Series(close).rolling(3).mean() - pd.Series(close).rolling(10).mean()
    signal = osc.rolling(16).mean()
    return [
        {
            **r,
            "ema": ema[i],
            "adx14": adx[i] if i < len(adx) else float("nan"),
            "osc_3_10_sma": float(osc.iloc[i]),
            "osc_signal_sma16": float(signal.iloc[i]),
            "atr14": atr[i - 1] if i else float("nan"),
        }
        for i, r in enumerate(rows)
    ]


def _rules(strategy: str, mode: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    source, locator = SOURCES[strategy]
    if mode == "HG_1997_CONDITIONAL":
        source, locator = "R09", "August1997 p2 Holy Grail"
    elif mode == "HG_2004_MOMENTUM_CASE":
        source, locator = "S312", "March2004 printed78 Figure1 30m SPX"
    grammar = {
        "ema_ribbon_scalp": "Watch is distinct from later base/pivot and price break; cross alone is not full Kell model",
        "keltner_trend": "ADX14 qualification precedes first EMA20 touch; conditional price trigger is separate from completed-close entry",
        "pivot_reversal": "Potential reversal watch precedes support/contraction, known swing pivot and actual trigger",
        "range_fade": "C02 Anti: directional impulse then small flag then same-direction continuation; not range-boundary fade",
        "scalp_snap": "Gajjala: impulse then high-level lower-volume pullback then price resumption; 5m/15m source clock",
        "vol_spike_fade": "Multi-session extension then first crack then weak rebound and price failure; volume alone is no short",
    }[strategy]
    return [
        {
            "rule_id": "source_grammar",
            "origin": "SOURCE_DIRECT",
            "expression": grammar,
            "unit": "ordered_price_events",
            "version": VERSION,
            "source_id": source,
            "source_locator": locator,
            "source_mode": mode,
        },
        {
            "rule_id": "quantitative_translation",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": "Explicit config="
            + repr(sorted(config.items()))
            + "; strict completed bars; segment reset; EMA SMA seed; fixed first references; no default hold/BE/TP",
            "unit": "config_declared_units",
            "version": VERSION,
            "hypothesis_id": config["hypothesis_id"],
            "rationale": "Public qualitative cases omit comprehensive numeric thresholds, expiry, size and management; this is an explicit research translation",
            "exact_source_reproduction": False,
        },
    ]


def _event(
    out: dict[str, Any], row: dict[str, Any], kind: str, **payload: Any
) -> dict[str, Any]:
    event = {
        "kind": kind,
        "symbol": out["symbol"],
        "event_ts_ms": row["close_ts_ms"],
        "available_ts_ms": row["available_ts_ms"],
        "segment_id": row["segment_id"],
        **payload,
    }
    out["events"].append(event)
    return event


def _intent(
    out: dict[str, Any],
    row: dict[str, Any],
    side: int,
    stop: float,
    trigger: float,
    order_kind: str,
    origin: int,
    **payload: Any,
) -> None:
    if (
        not all(math.isfinite(x) and x > 0 for x in (trigger, stop))
        or side * (trigger - stop) <= 0
    ):
        _event(
            out,
            row,
            "INVALID_PLANNED_RISK",
            trigger_price=trigger,
            protective_stop=stop,
        )
        return
    out["intents"].append(
        {
            "strategy_id": out["strategy_id"],
            "mode_id": out["mode_id"],
            "symbol": out["symbol"],
            "side": side,
            "order_kind": order_kind,
            "decision_ts_ms": row["available_ts_ms"],
            "feature_available_ts_ms": row["available_ts_ms"],
            "origin_ts_ms": origin,
            "segment_id": row["segment_id"],
            "trigger_price": trigger,
            "protective_stop": stop,
            "qty_base": None,
            "expires_ts_ms": None,
            "fill_price": None,
            "fill_ts_ms": None,
            "complete_order": False,
            "execution_status": "PARTIAL_RESEARCH_INTENT",
            "rule_digest": out["rule_digest"],
            **payload,
        }
    )


def _hg(
    out: dict[str, Any], segments: list[list[dict[str, Any]]], config: dict[str, Any]
) -> None:
    reset_adx = _number(config, "requalification_adx_below")
    if reset_adx >= 30:
        raise ValueError("REQUALIFICATION_ADX_MUST_BE_BELOW30")
    expiry = int(_number(config, "qualification_expiry_bars", integer=True))
    tick = _number(config, "tick_size")
    case2004 = out["mode_id"] == "HG_2004_MOMENTUM_CASE"
    lookback = (
        int(_number(config, "momentum_lookback", integer=True)) if case2004 else 0
    )
    for raw in segments:
        rows = _measures(raw)
        state, side, qualified, origin = "READY", 0, 0, 0
        for i in range(1, len(rows)):
            r, p = rows[i], rows[i - 1]
            if not all(
                math.isfinite(r[k]) and math.isfinite(p[k]) for k in ("ema", "adx14")
            ):
                continue
            if state == "CONSUMED":
                if r["adx14"] < reset_adx:
                    state = "READY"
                    _event(out, r, "REQUALIFICATION_RESET")
                continue
            if state == "READY":
                side = (
                    1
                    if r["close"] > r["ema"] and r["ema"] > p["ema"]
                    else -1 if r["close"] < r["ema"] and r["ema"] < p["ema"] else 0
                )
                momentum = True
                if case2004:
                    history = rows[max(0, i - lookback) : i]
                    momentum = (
                        len(history) == lookback
                        and all(math.isfinite(x["osc_3_10_sma"]) for x in history)
                        and side * r["osc_3_10_sma"]
                        > max(side * x["osc_3_10_sma"] for x in history)
                    )
                if side and r["adx14"] > 30 and r["adx14"] > p["adx14"] and momentum:
                    state, qualified, origin = "QUALIFIED", i, r["available_ts_ms"]
                    _event(
                        out,
                        r,
                        "INITIAL_ADX_QUALIFICATION",
                        side=side,
                        adx14=r["adx14"],
                        ema20=r["ema"],
                        version=out["mode_id"],
                    )
                continue
            if i - qualified > expiry:
                _event(out, r, "QUALIFICATION_EXPIRED_HYPOTHESIS")
                state = "CONSUMED"
                continue
            touched = r["low"] <= r["ema"] if side == 1 else r["high"] >= r["ema"]
            if touched:
                _event(
                    out,
                    r,
                    "FIRST_POST_QUALIFICATION_EMA_TOUCH",
                    side=side,
                    qualification_available_ts_ms=origin,
                    ema20=r["ema"],
                )
                trigger = r["high"] + tick if side == 1 else r["low"] - tick
                stop = r["low"] - tick if side == 1 else r["high"] + tick
                _intent(
                    out,
                    r,
                    side,
                    stop,
                    trigger,
                    "STOP_MARKET",
                    origin,
                    entry_reference="COMPLETED_TOUCH_BAR_HIGH_LOW_FOR_FUTURE_BAR",
                    source_version=out["mode_id"],
                )
                state = "CONSUMED"


def _kell(
    out: dict[str, Any], segments: list[list[dict[str, Any]]], config: dict[str, Any]
) -> None:
    ema_length = int(_number(config, "ema_length", integer=True))
    left = int(_number(config, "pivot_left_bars", integer=True))
    right = int(_number(config, "pivot_right_bars", integer=True))
    base_bars = int(_number(config, "base_bars", integer=True))
    contraction = _number(config, "base_range_ratio")
    extension = _number(config, "watch_extension_fraction")
    expiry = int(_number(config, "setup_expiry_bars", integer=True))
    tick = _number(config, "tick_size")
    reversal = out["strategy_id"] == "pivot_reversal"
    for raw in segments:
        rows = _measures(raw, ema_length)
        watch: dict[str, Any] | None = None
        for i in range(1, len(rows)):
            r, p = rows[i], rows[i - 1]
            if not math.isfinite(p["ema"]) or not math.isfinite(r["ema"]):
                continue
            if watch is None:
                qualifies = (
                    r["close"] < r["ema"] * (1 - extension)
                    if reversal
                    else p["close"] <= p["ema"] and r["close"] > r["ema"]
                )
                if qualifies:
                    watch = {
                        "index": i,
                        "origin": r["available_ts_ms"],
                        "low": r["low"],
                        "span": r["high"] - r["low"],
                    }
                    _event(
                        out,
                        r,
                        "REVERSAL_WATCH_ONLY" if reversal else "EMA_CROSS_WATCH_ONLY",
                    )
                continue
            if r["low"] < watch["low"] or i - watch["index"] > expiry:
                _event(out, r, "WATCH_INVALIDATED", support=watch["low"])
                watch = None
                continue
            center = i - right
            if center - left <= watch["index"] or i - watch["index"] < base_bars:
                continue
            neighborhood = rows[center - left : i + 1]
            pivot = rows[center]
            others = [v for j, v in enumerate(neighborhood) if j != left]
            pivot_known = all(pivot["high"] > v["high"] for v in others)
            base = rows[i - base_bars + 1 : i + 1]
            contracted = (
                max(v["high"] for v in base) - min(v["low"] for v in base)
                <= watch["span"] * contraction
            )
            if pivot_known and contracted:
                _event(
                    out,
                    r,
                    "CONFIRMED_SWING_PIVOT",
                    pivot_event_ts_ms=pivot["close_ts_ms"],
                    pivot_known_ts_ms=r["available_ts_ms"],
                    reference_type="CONFIRMED_PRICE_SWING_NOT_DAILY_HLC",
                    pivot_price=pivot["high"],
                )
                _intent(
                    out,
                    r,
                    1,
                    watch["low"] - tick,
                    pivot["high"] + tick,
                    "STOP_MARKET",
                    watch["origin"],
                    pivot_known_ts_ms=r["available_ts_ms"],
                    limited_reversal_target_ema=r["ema"] if reversal else None,
                )
                watch = None


def _flag(
    out: dict[str, Any], segments: list[list[dict[str, Any]]], config: dict[str, Any]
) -> None:
    lookback = int(_number(config, "impulse_lookback_bars", integer=True))
    multiplier = _number(config, "impulse_range_multiple")
    max_depth = _number(config, "flag_max_retracement_fraction")
    min_bars = int(_number(config, "flag_min_bars", integer=True))
    max_bars = int(_number(config, "flag_max_bars", integer=True))
    if min_bars > max_bars or max_depth >= 1:
        raise ValueError("INVALID_FLAG_GEOMETRY_CONFIG")
    volume_ratio = (
        _number(config, "pullback_volume_ratio")
        if out["strategy_id"] == "scalp_snap"
        else None
    )
    tick = _number(config, "tick_size")
    for raw in segments:
        rows = _measures(raw)
        state: dict[str, Any] | None = None
        for i in range(lookback, len(rows)):
            r, p = rows[i], rows[i - 1]
            if state is None:
                history = rows[i - lookback : i]
                scale = sum(x["high"] - x["low"] for x in history) / lookback
                side = 1 if r["close"] > r["open"] else -1
                impulse = r["high"] - r["low"] >= multiplier * scale and scale > 0
                if volume_ratio is not None:
                    impulse = (
                        impulse
                        and side == 1
                        and r["volume"] > sum(x["volume"] for x in history) / lookback
                    )
                else:
                    impulse = (
                        impulse
                        and math.isfinite(r["osc_signal_sma16"])
                        and side * r["osc_3_10_sma"] > side * r["osc_signal_sma16"]
                    )
                if impulse:
                    state = {
                        "i": i,
                        "side": side,
                        "origin": r["available_ts_ms"],
                        "high": r["high"],
                        "low": r["low"],
                        "span": r["high"] - r["low"],
                        "volume": r["volume"],
                        "flag": [],
                    }
                    _event(out, r, "DIRECTIONAL_IMPULSE", side=side)
                continue
            side = state["side"]
            elapsed = i - state["i"]
            depth = state["high"] - r["low"] if side == 1 else r["high"] - state["low"]
            if elapsed > max_bars + 1 or depth > max_depth * state["span"]:
                _event(out, r, "FLAG_INVALIDATED", side=side)
                state = None
                continue
            flag = state["flag"]
            boundary = (
                max(x["high"] for x in flag)
                if flag and side == 1
                else min(x["low"] for x in flag) if flag else None
            )
            resumed = boundary is not None and side * (r["close"] - boundary) > 0
            if len(flag) >= min_bars and resumed:
                stop = (
                    min(x["low"] for x in flag) - tick
                    if side == 1
                    else max(x["high"] for x in flag) + tick
                )
                _event(
                    out,
                    r,
                    "SAME_DIRECTION_CONTINUATION",
                    side=side,
                    prior_flag_boundary=boundary,
                    prior_boundary_available_ts_ms=flag[-1]["available_ts_ms"],
                )
                _intent(
                    out,
                    r,
                    side,
                    stop,
                    r["close"],
                    "NEXT_OPEN",
                    state["origin"],
                    reference_price_only_not_fill=True,
                )
                state = None
                continue
            counter = side * (r["close"] - p["close"]) < 0
            lower_volume = (
                volume_ratio is None or r["volume"] <= state["volume"] * volume_ratio
            )
            if lower_volume and (flag or counter) and len(flag) < max_bars:
                flag.append(r)
                _event(out, r, "SMALL_FLAG", side=side)
            else:
                _event(out, r, "FLAG_INVALIDATED", side=side)
                state = None


def _parabolic(
    out: dict[str, Any],
    segments: list[list[dict[str, Any]]],
    frames: dict[str, pd.DataFrame],
    config: dict[str, Any],
) -> None:
    sessions = int(_number(config, "extension_sessions", integer=True))
    if sessions < 2:
        raise ValueError("MULTI_SESSION_EXTENSION_REQUIRED")
    extension = _number(config, "extension_return_fraction")
    bounce_ratio = _number(config, "max_rebound_fraction")
    if bounce_ratio >= 1:
        raise ValueError("REBOUND_MUST_REMAIN_BELOW_EXTENSION_HIGH")
    tick = _number(config, "tick_size")
    if "1d" not in frames:
        raise ValueError("GENUINE_DAILY_CONTEXT_REQUIRED_NOT_INTRADAY_BARS")
    daily_segments = _frame(frames["1d"], 1440)
    daily_rows = [r for segment in daily_segments for r in segment]
    for rows in segments:
        state: dict[str, Any] | None = None
        session = None
        for i in range(1, len(rows)):
            r, p = rows[i], rows[i - 1]
            current_session = r.get("session_id")
            if not isinstance(current_session, str) or not current_session:
                raise ValueError("EXPLICIT_SESSION_ID_REQUIRED")
            if current_session != session:
                state, session = None, current_session
            if state is None:
                history = [
                    x for x in daily_rows if x["available_ts_ms"] <= r["open_ts_ms"]
                ][-sessions - 1 :]
                contiguous = len(history) == sessions + 1 and all(
                    b["open_ts_ms"] - a["open_ts_ms"] == 86400000
                    and a["segment_id"] == b["segment_id"]
                    for a, b in zip(history, history[1:])
                )
                if (
                    contiguous
                    and history[-1]["close"] / history[0]["close"] - 1 >= extension
                ):
                    state = {
                        "phase": "EXTENDED",
                        "origin": r["available_ts_ms"],
                        "high": max(r["high"], p["high"]),
                        "daily_known": history[-1]["available_ts_ms"],
                    }
                    _event(
                        out,
                        r,
                        "MULTI_SESSION_EXTENSION",
                        context_available_ts_ms=history[-1]["available_ts_ms"],
                    )
                continue
            if r["high"] > state["high"]:
                if state["phase"] != "EXTENDED":
                    _event(
                        out,
                        r,
                        "PARABOLIC_SHORT_INVALIDATED",
                        invalidation_price=state["high"],
                    )
                    state = None
                    continue
                state["high"] = r["high"]
            if state["phase"] == "EXTENDED" and r["close"] < p["low"]:
                state.update(phase="CRACK", crack_low=r["low"], crack_high=r["high"])
                _event(out, r, "FIRST_CRACK")
            elif state["phase"] == "CRACK":
                if r["close"] > p["close"]:
                    max_bounce = state["crack_low"] + bounce_ratio * (
                        state["high"] - state["crack_low"]
                    )
                    if r["high"] <= max_bounce:
                        state.update(
                            phase="RETEST", rebound_high=r["high"], rebound_low=r["low"]
                        )
                        _event(out, r, "WEAK_REBOUND_RETEST")
                    else:
                        _event(out, r, "REBOUND_NOT_WEAK")
                        state = None
                elif r["low"] < state["crack_low"]:
                    state["crack_low"] = r["low"]
            elif state["phase"] == "RETEST":
                if r["high"] > state["rebound_high"]:
                    _event(
                        out,
                        r,
                        "RETEST_INVALIDATED",
                        invalidation_price=state["rebound_high"],
                    )
                    state = None
                elif r["close"] < state["rebound_low"]:
                    _event(out, r, "RETEST_PRICE_FAILURE")
                    _intent(
                        out,
                        r,
                        -1,
                        state["rebound_high"] + tick,
                        r["close"],
                        "NEXT_OPEN",
                        state["origin"],
                        context_available_ts_ms=state["daily_known"],
                        reference_price_only_not_fill=True,
                    )
                    state = None


def evaluate(
    strategy_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate per-symbol canonical frames without external precomputed booleans."""
    if strategy_id not in MODES:
        raise ValueError("UNKNOWN_STRUCTURE_STRATEGY")
    mode = _text(config, "mode_id")
    _text(config, "hypothesis_id")
    if mode not in MODES[strategy_id]:
        raise ValueError("SOURCE_MODE_MISMATCH")
    tf = int(_number(config, "timeframe_min", integer=True))
    if mode == "SHORT_SKIRT_NATIVE_UNAVAILABLE":
        raise ValueError("SHORT_SKIRT_NATIVE_1M_2_TO10MIN_HOLD_UNAVAILABLE_NO15M_PORT")
    if tf not in (15, 30) or (strategy_id == "scalp_snap" and tf != 15):
        raise ValueError("SOURCE_CLOCK_MISMATCH")
    numeric_config = {
        k: v for k, v in config.items() if k not in ("daily_frames", "context_frames")
    }
    json.dumps(numeric_config, allow_nan=False)
    rules = _rules(strategy_id, mode, numeric_config)
    out: dict[str, Any] = {
        "strategy_id": strategy_id,
        "mode_id": mode,
        "events": [],
        "intents": [],
        "components": {
            "input": "RAW_OHLCV",
            "timeframe_min": tf,
            "physical_segments": {},
            "input_sha256": {},
            "full_runs": 0,
        },
        "rules": rules,
        "rule_digest": validate_rules(rules),
        "limitations": [*LIMITATIONS, ROW_GAPS[strategy_id]],
        "complete_strategy": False,
        "exact_source_reproduction": False,
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
    }
    if not frames:
        raise ValueError("SYMBOL_FRAMES_REQUIRED")
    for symbol, frame in sorted(frames.items()):
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("SYMBOL_REQUIRED")
        segments = _frame(frame, tf)
        if strategy_id == "scalp_snap":
            units = (
                set(frame["volume_unit"])
                if "volume_unit" in frame
                else {config.get("volume_unit")}
            )
            if len(units) != 1 or next(iter(units), None) not in {
                "BASE",
                "QUOTE",
                "CONTRACTS",
            }:
                raise ValueError("EXPLICIT_CONSISTENT_VOLUME_UNIT_REQUIRED")
            if "volume_unit" in config and config["volume_unit"] not in units:
                raise ValueError("VOLUME_UNIT_CONFIG_MISMATCH")
        out["symbol"] = symbol
        out["components"]["physical_segments"][symbol] = len(segments)
        out["components"]["input_sha256"][symbol] = hashlib.sha256(
            frame.to_json(orient="split", double_precision=15).encode()
        ).hexdigest()
        if strategy_id == "keltner_trend":
            _hg(out, segments, config)
        elif strategy_id in ("ema_ribbon_scalp", "pivot_reversal"):
            _kell(out, segments, config)
        elif strategy_id in ("range_fade", "scalp_snap"):
            _flag(out, segments, config)
        else:
            daily = config.get("daily_frames", {})
            if symbol not in daily:
                raise ValueError(
                    "GENUINE_DAILY_CONTEXT_REQUIRED_NOT_INTRADAY_BARS:" + symbol
                )
            if config.get("daily_calendar") != "UTC_24H_DECLARED_ADAPTATION":
                raise ValueError(
                    "EXPLICIT_24H_DAILY_ADAPTATION_REQUIRED_NOT_STOCK_SESSION"
                )
            out["components"]["input_sha256"][symbol + ":daily"] = hashlib.sha256(
                daily[symbol].to_json(orient="split", double_precision=15).encode()
            ).hexdigest()
            _parabolic(out, segments, {"1d": daily[symbol]}, config)
    out.pop("symbol", None)
    out["events"].sort(key=lambda e: (e["available_ts_ms"], e["symbol"], e["kind"]))
    out["intents"].sort(key=lambda e: (e["decision_ts_ms"], e["symbol"]))
    return out
