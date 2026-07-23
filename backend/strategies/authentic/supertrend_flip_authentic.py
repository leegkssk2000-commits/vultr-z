from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional
import math

import pandas as pd


STRATEGY_ID = "supertrend_flip_authentic"
STATE_SCHEMA = "supertrend_flip_authentic_state_v1"
REPLAY_PROFILE_ID = "supertrend_flip_authentic_replay_v1"

HOLD = "HOLD"
ENTER_LONG = "ENTER_LONG"
ENTER_SHORT = "ENTER_SHORT"
EXIT_LONG = "EXIT_LONG"
EXIT_SHORT = "EXIT_SHORT"
REVERSE_TO_LONG = "REVERSE_TO_LONG"
REVERSE_TO_SHORT = "REVERSE_TO_SHORT"
BLOCK = "BLOCK"

ALLOWED_INTENTS = {
    HOLD,
    ENTER_LONG,
    ENTER_SHORT,
    EXIT_LONG,
    EXIT_SHORT,
    REVERSE_TO_LONG,
    REVERSE_TO_SHORT,
}

UP = 1
DOWN = -1
FLAT = "flat"
LONG = "long"
SHORT = "short"


@dataclass(frozen=True)
class SupertrendFlipAuthenticConfig:
    atr_length: int = 10
    factor: float = 3.0
    control_notional: float = 1.0

    def validate(self) -> None:
        if isinstance(self.atr_length, bool) or int(self.atr_length) < 1:
            raise ValueError("ATR_LENGTH_INVALID")
        if not math.isfinite(float(self.factor)) or float(self.factor) <= 0:
            raise ValueError("SUPERTREND_FACTOR_INVALID")
        if not math.isfinite(float(self.control_notional)) or float(self.control_notional) <= 0:
            raise ValueError("CONTROL_NOTIONAL_INVALID")


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _normalize_position_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "1"}:
        return LONG
    if text in {"short", "sell", "-1"}:
        return SHORT
    if text in {"", "none", "flat", "0"}:
        return FLAT
    raise ValueError("POSITION_SIDE_INVALID")


def _confirmed_bar_ts(frame: pd.DataFrame, position: int) -> Any:
    row = frame.iloc[position]
    for key in ("bar_close_ts", "close_ts", "ts", "timestamp", "time"):
        if key in frame.columns:
            value = row[key]
            if pd.notna(value):
                return value.item() if hasattr(value, "item") else value
    index_value = frame.index[position]
    return index_value.item() if hasattr(index_value, "item") else index_value


def _validated_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("OHLC_FRAME_EMPTY")
    required = ("open", "high", "low", "close")
    if any(column not in frame.columns for column in required):
        raise ValueError("OHLC_COLUMNS_MISSING")

    result = frame.copy()
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    values = result.loc[:, list(required)]
    finite_mask = values.applymap(_is_finite)
    if not bool(finite_mask.to_numpy().all()):
        raise ValueError("OHLC_NONFINITE")
    if bool((result["high"] < result["low"]).any()):
        raise ValueError("OHLC_HIGH_BELOW_LOW")
    if bool(((result["open"] < result["low"]) | (result["open"] > result["high"])).any()):
        raise ValueError("OHLC_OPEN_OUTSIDE_RANGE")
    if bool(((result["close"] < result["low"]) | (result["close"] > result["high"])).any()):
        raise ValueError("OHLC_CLOSE_OUTSIDE_RANGE")
    return result


def true_range(frame: pd.DataFrame) -> pd.Series:
    """TradingView-compatible True Range with high-low on the first bar."""
    validated = _validated_ohlc(frame)
    high = validated["high"].astype(float)
    low = validated["low"].astype(float)
    close = validated["close"].astype(float)
    previous_close = close.shift(1)

    intrabar = high - low
    gap_high = (high - previous_close).abs()
    gap_low = (low - previous_close).abs()
    result = pd.concat([intrabar, gap_high, gap_low], axis=1).max(axis=1, skipna=True)
    result.name = "true_range"
    return result.astype(float)


def wilder_rma(values: pd.Series, length: int) -> pd.Series:
    """Wilder RMA seeded by the SMA of the first ``length`` finite values."""
    if isinstance(length, bool) or int(length) < 1:
        raise ValueError("RMA_LENGTH_INVALID")
    length = int(length)
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    if any(not _is_finite(value) for value in numeric.tolist()):
        raise ValueError("RMA_INPUT_NONFINITE")

    output = pd.Series(float("nan"), index=numeric.index, dtype="float64", name="atr")
    if len(numeric) < length:
        return output

    seed_position = length - 1
    seed = float(numeric.iloc[:length].mean())
    output.iloc[seed_position] = seed
    previous = seed
    for position in range(seed_position + 1, len(numeric)):
        current = float(numeric.iloc[position])
        previous = ((previous * (length - 1)) + current) / length
        output.iloc[position] = previous
    return output


def direction_step(previous_direction: int, close: float, final_upper: float, final_lower: float) -> int:
    """Confirmed-close Supertrend direction transition with strict band crossing."""
    if previous_direction not in {UP, DOWN}:
        raise ValueError("PREVIOUS_DIRECTION_INVALID")
    if not all(_is_finite(value) for value in (close, final_upper, final_lower)):
        raise ValueError("DIRECTION_INPUT_NONFINITE")
    if previous_direction == DOWN:
        return UP if float(close) > float(final_upper) else DOWN
    return DOWN if float(close) < float(final_lower) else UP


def compute_supertrend(
    frame: pd.DataFrame,
    config: Optional[SupertrendFlipAuthenticConfig] = None,
) -> pd.DataFrame:
    """Calculate formula-locked ATR, recursive bands, direction and Supertrend line."""
    cfg = config or SupertrendFlipAuthenticConfig()
    cfg.validate()
    validated = _validated_ohlc(frame)

    high = validated["high"].astype(float)
    low = validated["low"].astype(float)
    close = validated["close"].astype(float)
    tr = true_range(validated)
    atr = wilder_rma(tr, cfg.atr_length)
    midpoint = (high + low) / 2.0
    basic_upper = midpoint + float(cfg.factor) * atr
    basic_lower = midpoint - float(cfg.factor) * atr

    final_upper = pd.Series(float("nan"), index=validated.index, dtype="float64")
    final_lower = pd.Series(float("nan"), index=validated.index, dtype="float64")
    direction = pd.Series(float("nan"), index=validated.index, dtype="float64")
    line = pd.Series(float("nan"), index=validated.index, dtype="float64")

    valid_positions = [position for position, value in enumerate(atr.tolist()) if _is_finite(value)]
    if valid_positions:
        seed_position = valid_positions[0]
        final_upper.iloc[seed_position] = float(basic_upper.iloc[seed_position])
        final_lower.iloc[seed_position] = float(basic_lower.iloc[seed_position])
        direction.iloc[seed_position] = float(DOWN)
        line.iloc[seed_position] = float(final_upper.iloc[seed_position])

        for position in range(seed_position + 1, len(validated)):
            if not _is_finite(atr.iloc[position]):
                raise ValueError("ATR_BECAME_NONFINITE_AFTER_WARMUP")

            upper_now = float(basic_upper.iloc[position])
            lower_now = float(basic_lower.iloc[position])
            previous_upper = float(final_upper.iloc[position - 1])
            previous_lower = float(final_lower.iloc[position - 1])
            previous_close = float(close.iloc[position - 1])

            final_upper.iloc[position] = (
                upper_now
                if upper_now < previous_upper or previous_close > previous_upper
                else previous_upper
            )
            final_lower.iloc[position] = (
                lower_now
                if lower_now > previous_lower or previous_close < previous_lower
                else previous_lower
            )

            previous_direction = int(direction.iloc[position - 1])
            current_direction = direction_step(
                previous_direction,
                float(close.iloc[position]),
                float(final_upper.iloc[position]),
                float(final_lower.iloc[position]),
            )
            direction.iloc[position] = float(current_direction)
            line.iloc[position] = (
                float(final_lower.iloc[position])
                if current_direction == UP
                else float(final_upper.iloc[position])
            )

    previous_direction = direction.shift(1)
    flip_up = (previous_direction == DOWN) & (direction == UP)
    flip_down = (previous_direction == UP) & (direction == DOWN)

    return pd.DataFrame(
        {
            "true_range": tr,
            "atr": atr,
            "hl2": midpoint,
            "basic_upper": basic_upper,
            "basic_lower": basic_lower,
            "final_upper": final_upper,
            "final_lower": final_lower,
            "direction": direction,
            "supertrend_line": line,
            "previous_direction": previous_direction,
            "flip_up": flip_up.fillna(False).astype(bool),
            "flip_down": flip_down.fillna(False).astype(bool),
        },
        index=validated.index,
    )


def _state_snapshot(
    *,
    frame: pd.DataFrame,
    indicator: pd.DataFrame,
    position: int,
    position_side: str,
    last_flip_ts: Any,
    reset_reason: Optional[str],
) -> Dict[str, Any]:
    current_direction = int(indicator["direction"].iloc[position])
    previous_value = indicator["previous_direction"].iloc[position]
    previous_direction = int(previous_value) if _is_finite(previous_value) else None
    return {
        "state_schema": STATE_SCHEMA,
        "bar_close_ts": _confirmed_bar_ts(frame, position),
        "atr": float(indicator["atr"].iloc[position]),
        "basic_upper": float(indicator["basic_upper"].iloc[position]),
        "basic_lower": float(indicator["basic_lower"].iloc[position]),
        "final_upper": float(indicator["final_upper"].iloc[position]),
        "final_lower": float(indicator["final_lower"].iloc[position]),
        "supertrend_line": float(indicator["supertrend_line"].iloc[position]),
        "previous_direction": previous_direction,
        "current_direction": current_direction,
        "position_side": position_side,
        "last_flip_ts": last_flip_ts,
        "warmup_complete": True,
        "reset_reason": reset_reason,
    }


def _ledger_legs(intent: str, close_price: float, signal_ts: Any) -> List[Dict[str, Any]]:
    if intent == ENTER_LONG:
        return [{"intent": ENTER_LONG, "side": LONG, "price": close_price, "signal_ts": signal_ts}]
    if intent == ENTER_SHORT:
        return [{"intent": ENTER_SHORT, "side": SHORT, "price": close_price, "signal_ts": signal_ts}]
    if intent == REVERSE_TO_LONG:
        return [
            {"intent": EXIT_SHORT, "side": SHORT, "price": close_price, "signal_ts": signal_ts},
            {"intent": ENTER_LONG, "side": LONG, "price": close_price, "signal_ts": signal_ts},
        ]
    if intent == REVERSE_TO_SHORT:
        return [
            {"intent": EXIT_LONG, "side": LONG, "price": close_price, "signal_ts": signal_ts},
            {"intent": ENTER_SHORT, "side": SHORT, "price": close_price, "signal_ts": signal_ts},
        ]
    return []


def _position_after(intent: str, current: str) -> str:
    if intent in {ENTER_LONG, REVERSE_TO_LONG}:
        return LONG
    if intent in {ENTER_SHORT, REVERSE_TO_SHORT}:
        return SHORT
    if intent in {EXIT_LONG, EXIT_SHORT}:
        return FLAT
    return current


def _intent_for_flip(previous_direction: int, current_direction: int, position_side: str) -> str:
    if previous_direction == DOWN and current_direction == UP:
        if position_side == FLAT:
            return ENTER_LONG
        if position_side == SHORT:
            return REVERSE_TO_LONG
        raise ValueError("POSITION_DIRECTION_MISMATCH_ALREADY_LONG_ON_UP_FLIP")
    if previous_direction == UP and current_direction == DOWN:
        if position_side == FLAT:
            return ENTER_SHORT
        if position_side == LONG:
            return REVERSE_TO_SHORT
        raise ValueError("POSITION_DIRECTION_MISMATCH_ALREADY_SHORT_ON_DOWN_FLIP")
    return HOLD


def strategy(
    frame: pd.DataFrame,
    *,
    state: Optional[Mapping[str, Any]] = None,
    symbol: str = "UNKNOWN",
    timeframe: str = "UNKNOWN",
    replay_fold_id: str = "UNKNOWN",
    config: Optional[SupertrendFlipAuthenticConfig] = None,
) -> Dict[str, Any]:
    """Return the latest confirmed-close authentic Supertrend decision.

    This function is research-only. It has no exchange, router, registry, shadow,
    paper, live, sizing, leverage, add or promotion authority.
    """
    cfg = config or SupertrendFlipAuthenticConfig()
    try:
        cfg.validate()
        validated = _validated_ohlc(frame)
        indicator = compute_supertrend(validated, cfg)
        position_side = _normalize_position_side((state or {}).get("position_side"))
    except Exception as exc:
        return {
            "ok": False,
            "strategy_id": STRATEGY_ID,
            "intent": BLOCK,
            "reason": f"FAIL_CLOSED:{type(exc).__name__}:{exc}",
            "authority": "RESEARCH_ONLY_NO_EXECUTION",
            "ledger_legs": [],
            "state_before": dict(state or {}),
            "state_after": dict(state or {}),
        }

    valid_positions = [
        position for position, value in enumerate(indicator["direction"].tolist())
        if _is_finite(value)
    ]
    if not valid_positions:
        return {
            "ok": True,
            "strategy_id": STRATEGY_ID,
            "intent": HOLD,
            "reason": "ATR_WARMUP_INCOMPLETE",
            "authority": "RESEARCH_ONLY_NO_EXECUTION",
            "ledger_legs": [],
            "state_before": dict(state or {}),
            "state_after": dict(state or {}),
        }

    position = len(validated) - 1
    if position not in valid_positions:
        return {
            "ok": True,
            "strategy_id": STRATEGY_ID,
            "intent": HOLD,
            "reason": "ATR_WARMUP_INCOMPLETE",
            "authority": "RESEARCH_ONLY_NO_EXECUTION",
            "ledger_legs": [],
            "state_before": dict(state or {}),
            "state_after": dict(state or {}),
        }

    signal_ts = _confirmed_bar_ts(validated, position)
    last_flip_ts = (state or {}).get("last_flip_ts")
    before = _state_snapshot(
        frame=validated,
        indicator=indicator,
        position=position,
        position_side=position_side,
        last_flip_ts=last_flip_ts,
        reset_reason=(state or {}).get("reset_reason"),
    )

    previous_value = indicator["previous_direction"].iloc[position]
    if not _is_finite(previous_value):
        intent = HOLD
        reason = "INITIAL_VALID_DIRECTION_STATE_ONLY"
    else:
        previous_direction = int(previous_value)
        current_direction = int(indicator["direction"].iloc[position])
        try:
            intent = _intent_for_flip(previous_direction, current_direction, position_side)
            reason = "OPPOSITE_CONFIRMED_FLIP" if intent.startswith("REVERSE") else (
                "CONFIRMED_DIRECTION_FLIP" if intent != HOLD else "NO_DIRECTION_CHANGE"
            )
        except Exception as exc:
            return {
                "ok": False,
                "strategy_id": STRATEGY_ID,
                "intent": BLOCK,
                "reason": f"FAIL_CLOSED:{type(exc).__name__}:{exc}",
                "authority": "RESEARCH_ONLY_NO_EXECUTION",
                "ledger_legs": [],
                "state_before": before,
                "state_after": before,
            }

    if intent not in ALLOWED_INTENTS:
        return {
            "ok": False,
            "strategy_id": STRATEGY_ID,
            "intent": BLOCK,
            "reason": "FAIL_CLOSED:UNSUPPORTED_INTENT",
            "authority": "RESEARCH_ONLY_NO_EXECUTION",
            "ledger_legs": [],
            "state_before": before,
            "state_after": before,
        }

    close_price = float(validated["close"].iloc[position])
    after_position = _position_after(intent, position_side)
    after_last_flip_ts = signal_ts if intent != HOLD else last_flip_ts
    after = dict(before)
    after["position_side"] = after_position
    after["last_flip_ts"] = after_last_flip_ts

    return {
        "ok": True,
        "strategy_id": STRATEGY_ID,
        "parent_strategy_id": "supertrend_pullback",
        "intent": intent,
        "reason": reason,
        "side": after_position if intent != HOLD else None,
        "entry_price": close_price if intent in {ENTER_LONG, ENTER_SHORT, REVERSE_TO_LONG, REVERSE_TO_SHORT} else None,
        "exit_reason": "OPPOSITE_FLIP" if intent in {REVERSE_TO_LONG, REVERSE_TO_SHORT, EXIT_LONG, EXIT_SHORT} else None,
        "exit_trigger_type": "CONFIRMED_BAR_CLOSE_STATE_CHANGE" if intent in {REVERSE_TO_LONG, REVERSE_TO_SHORT, EXIT_LONG, EXIT_SHORT} else None,
        "exit_level_or_state": {"direction": after["current_direction"], "close": close_price} if intent in {REVERSE_TO_LONG, REVERSE_TO_SHORT, EXIT_LONG, EXIT_SHORT} else None,
        "strategy_native_stop": None,
        "forced_segment_exit_flag": False,
        "control_notional": float(cfg.control_notional),
        "leverage": None,
        "ledger_legs": _ledger_legs(intent, close_price, signal_ts),
        "state_key": {
            "strategy_id": STRATEGY_ID,
            "symbol": str(symbol),
            "timeframe": str(timeframe),
            "replay_fold_id": str(replay_fold_id),
        },
        "state_before": before,
        "state_after": after,
        "formula": {
            "atr_method": "WILDER_RMA",
            "atr_length": int(cfg.atr_length),
            "factor": float(cfg.factor),
            "decision_time": "CONFIRMED_BAR_CLOSE_ONLY",
        },
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
    }


def replay_flip_intents(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    replay_fold_id: str,
    config: Optional[SupertrendFlipAuthenticConfig] = None,
) -> Dict[str, Any]:
    """Replay all confirmed direction transitions without segment resets."""
    cfg = config or SupertrendFlipAuthenticConfig()
    cfg.validate()
    validated = _validated_ohlc(frame)
    indicator = compute_supertrend(validated, cfg)

    events: List[Dict[str, Any]] = []
    position_side = FLAT
    last_flip_ts: Any = None
    initialized = False

    for position, direction_value in enumerate(indicator["direction"].tolist()):
        if not _is_finite(direction_value):
            continue
        signal_ts = _confirmed_bar_ts(validated, position)
        previous_value = indicator["previous_direction"].iloc[position]

        if not initialized or not _is_finite(previous_value):
            intent = HOLD
            reason = "INITIAL_VALID_DIRECTION_STATE_ONLY"
            initialized = True
        else:
            intent = _intent_for_flip(int(previous_value), int(direction_value), position_side)
            reason = "NO_DIRECTION_CHANGE" if intent == HOLD else (
                "OPPOSITE_CONFIRMED_FLIP" if intent.startswith("REVERSE") else "CONFIRMED_DIRECTION_FLIP"
            )

        close_price = float(validated["close"].iloc[position])
        before = _state_snapshot(
            frame=validated,
            indicator=indicator,
            position=position,
            position_side=position_side,
            last_flip_ts=last_flip_ts,
            reset_reason="FOLD_START" if len(events) == 0 else None,
        )
        position_side = _position_after(intent, position_side)
        if intent != HOLD:
            last_flip_ts = signal_ts
        after = dict(before)
        after["position_side"] = position_side
        after["last_flip_ts"] = last_flip_ts

        events.append(
            {
                "bar_close_ts": signal_ts,
                "previous_direction": before["previous_direction"],
                "current_direction": before["current_direction"],
                "intent": intent,
                "reason": reason,
                "close": close_price,
                "ledger_legs": _ledger_legs(intent, close_price, signal_ts),
                "state_before": before,
                "state_after": after,
                "forced_segment_exit_flag": False,
            }
        )

    flip_events = [event for event in events if event["intent"] != HOLD]
    return {
        "strategy_id": STRATEGY_ID,
        "replay_profile_id": REPLAY_PROFILE_ID,
        "state_key": {
            "strategy_id": STRATEGY_ID,
            "symbol": str(symbol),
            "timeframe": str(timeframe),
            "replay_fold_id": str(replay_fold_id),
        },
        "formula": {
            "atr_method": "WILDER_RMA",
            "atr_length": int(cfg.atr_length),
            "factor": float(cfg.factor),
        },
        "events": events,
        "valid_direction_bar_count": len(events),
        "flip_event_count": len(flip_events),
        "enter_long_count": sum(event["intent"] == ENTER_LONG for event in events),
        "enter_short_count": sum(event["intent"] == ENTER_SHORT for event in events),
        "reverse_to_long_count": sum(event["intent"] == REVERSE_TO_LONG for event in events),
        "reverse_to_short_count": sum(event["intent"] == REVERSE_TO_SHORT for event in events),
        "short_intent_suppressed_count": 0,
        "native_segment_exit_count": 0,
        "final_position_side": position_side,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
    }


__all__ = [
    "ALLOWED_INTENTS",
    "BLOCK",
    "DOWN",
    "ENTER_LONG",
    "ENTER_SHORT",
    "EXIT_LONG",
    "EXIT_SHORT",
    "HOLD",
    "LONG",
    "REPLAY_PROFILE_ID",
    "REVERSE_TO_LONG",
    "REVERSE_TO_SHORT",
    "SHORT",
    "STATE_SCHEMA",
    "STRATEGY_ID",
    "SupertrendFlipAuthenticConfig",
    "UP",
    "compute_supertrend",
    "direction_step",
    "replay_flip_intents",
    "strategy",
    "true_range",
    "wilder_rma",
]
