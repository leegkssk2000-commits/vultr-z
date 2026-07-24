from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
import json
import math

import pandas as pd


STRATEGY_ID = "integrated_supertrend_pullback_v1"
CONTRACT_FILENAME = "ZOS_R7A4D_INTEGRATED_SUPERTREND_PULLBACK_v1.json"
AUTHORITY = "RESEARCH_ONLY_NO_EXECUTION"

HOLD = "HOLD"
BLOCK = "BLOCK"
ENTER_LONG = "ENTER_LONG"
ENTER_SHORT = "ENTER_SHORT"
EXIT_LONG = "EXIT_LONG"
EXIT_SHORT = "EXIT_SHORT"

FLAT = "flat"
LONG = "long"
SHORT = "short"
UP = 1
DOWN = -1

REQUIRED_GEOMETRY_COLUMNS = (
    "structure_long",
    "structure_short",
    "sr_touch",
    "trendline_touch",
    "ma50_touch",
    "counter_trend_break_up",
    "counter_trend_break_down",
)


@dataclass(frozen=True)
class IntegratedSupertrendPullbackConfig:
    dema_length: int = 200
    supertrend_atr_length: int = 12
    supertrend_factor: float = 3.0
    rsi_length: int = 14
    minimum_confluence_count: int = 2
    timeframe: str = "15m"

    def validate(self) -> None:
        if int(self.dema_length) != 200:
            raise ValueError("DEMA_LENGTH_CONTRACT_MISMATCH")
        if int(self.supertrend_atr_length) != 12:
            raise ValueError("SUPERTREND_ATR_LENGTH_CONTRACT_MISMATCH")
        if float(self.supertrend_factor) != 3.0:
            raise ValueError("SUPERTREND_FACTOR_CONTRACT_MISMATCH")
        if int(self.rsi_length) != 14:
            raise ValueError("RSI_LENGTH_CONTRACT_MISMATCH")
        if int(self.minimum_confluence_count) != 2:
            raise ValueError("CONFLUENCE_COUNT_CONTRACT_MISMATCH")
        if str(self.timeframe) != "15m":
            raise ValueError("TIMEFRAME_CONTRACT_MISMATCH")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _bool_series(values: pd.Series, name: str) -> pd.Series:
    if values.dtype == bool:
        return values.astype(bool)
    mapped = values.map(
        lambda value: value
        if isinstance(value, bool)
        else str(value).strip().lower() in {"1", "true", "yes", "y"}
    )
    if mapped.isna().any():
        raise ValueError(f"BOOLEAN_COLUMN_INVALID:{name}")
    return mapped.astype(bool)


def _validated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("FRAME_EMPTY")
    required = ("open", "high", "low", "close", *REQUIRED_GEOMETRY_COLUMNS)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("OBJECTIVE_GEOMETRY_MISSING:" + ",".join(missing))

    result = frame.copy()
    for column in ("open", "high", "low", "close"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if not bool(result[["open", "high", "low", "close"]].apply(lambda s: s.map(_finite)).to_numpy().all()):
        raise ValueError("OHLC_NONFINITE")
    if bool((result["high"] < result["low"]).any()):
        raise ValueError("OHLC_HIGH_BELOW_LOW")
    if bool(((result["open"] < result["low"]) | (result["open"] > result["high"])).any()):
        raise ValueError("OHLC_OPEN_OUTSIDE_RANGE")
    if bool(((result["close"] < result["low"]) | (result["close"] > result["high"])).any()):
        raise ValueError("OHLC_CLOSE_OUTSIDE_RANGE")

    for column in REQUIRED_GEOMETRY_COLUMNS:
        result[column] = _bool_series(result[column], column)
    return result


def load_contract(path: Optional[Path] = None) -> Dict[str, Any]:
    contract_path = path or (Path(__file__).resolve().parents[2] / "contracts" / CONTRACT_FILENAME)
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if payload.get("strategy_id") != STRATEGY_ID:
        raise ValueError("CONTRACT_STRATEGY_ID_MISMATCH")
    if payload.get("registration_invariants", {}).get("canonical_strategy_count") != 1:
        raise ValueError("CONTRACT_CANONICAL_STRATEGY_COUNT_INVALID")
    if payload.get("single_strategy_pipeline", {}).get("pullback_location_gate", {}).get("minimum_confluence_count") != 2:
        raise ValueError("CONTRACT_CONFLUENCE_COUNT_INVALID")
    return payload


def _ema(values: pd.Series, length: int) -> pd.Series:
    return values.astype(float).ewm(span=int(length), adjust=False, min_periods=1).mean()


def _dema(values: pd.Series, length: int) -> pd.Series:
    ema1 = _ema(values, length)
    ema2 = _ema(ema1, length)
    return (2.0 * ema1) - ema2


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=True)


def _wilder_rma(values: pd.Series, length: int) -> pd.Series:
    numeric = values.astype(float)
    output = pd.Series(float("nan"), index=numeric.index, dtype="float64")
    if len(numeric) < length:
        return output
    seed_index = length - 1
    seed = float(numeric.iloc[:length].mean())
    output.iloc[seed_index] = seed
    previous = seed
    for position in range(seed_index + 1, len(numeric)):
        previous = ((previous * (length - 1)) + float(numeric.iloc[position])) / length
        output.iloc[position] = previous
    return output


def _supertrend(frame: pd.DataFrame, length: int, factor: float) -> pd.DataFrame:
    atr = _wilder_rma(_true_range(frame), length)
    hl2 = (frame["high"] + frame["low"]) / 2.0
    basic_upper = hl2 + factor * atr
    basic_lower = hl2 - factor * atr
    final_upper = pd.Series(float("nan"), index=frame.index, dtype="float64")
    final_lower = pd.Series(float("nan"), index=frame.index, dtype="float64")
    direction = pd.Series(float("nan"), index=frame.index, dtype="float64")
    line = pd.Series(float("nan"), index=frame.index, dtype="float64")

    valid = [i for i, value in enumerate(atr.tolist()) if _finite(value)]
    if valid:
        seed = valid[0]
        final_upper.iloc[seed] = float(basic_upper.iloc[seed])
        final_lower.iloc[seed] = float(basic_lower.iloc[seed])
        direction.iloc[seed] = float(DOWN)
        line.iloc[seed] = float(final_upper.iloc[seed])
        for i in range(seed + 1, len(frame)):
            prev_upper = float(final_upper.iloc[i - 1])
            prev_lower = float(final_lower.iloc[i - 1])
            prev_close = float(frame["close"].iloc[i - 1])
            upper = float(basic_upper.iloc[i])
            lower = float(basic_lower.iloc[i])
            final_upper.iloc[i] = upper if upper < prev_upper or prev_close > prev_upper else prev_upper
            final_lower.iloc[i] = lower if lower > prev_lower or prev_close < prev_lower else prev_lower
            prev_direction = int(direction.iloc[i - 1])
            close = float(frame["close"].iloc[i])
            if prev_direction == DOWN:
                current = UP if close > float(final_upper.iloc[i]) else DOWN
            else:
                current = DOWN if close < float(final_lower.iloc[i]) else UP
            direction.iloc[i] = float(current)
            line.iloc[i] = float(final_lower.iloc[i]) if current == UP else float(final_upper.iloc[i])

    previous_direction = direction.shift(1)
    return pd.DataFrame(
        {
            "atr": atr,
            "supertrend_line": line,
            "supertrend_direction": direction,
            "supertrend_flip_up": ((previous_direction == DOWN) & (direction == UP)).fillna(False),
            "supertrend_flip_down": ((previous_direction == UP) & (direction == DOWN)).fillna(False),
        },
        index=frame.index,
    )


def _rsi(values: pd.Series, length: int) -> pd.Series:
    delta = values.astype(float).diff()
    gain = delta.clip(lower=0.0).fillna(0.0)
    loss = (-delta.clip(upper=0.0)).fillna(0.0)
    avg_gain = _wilder_rma(gain, length)
    avg_loss = _wilder_rma(loss, length)
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(avg_gain != 0.0, 0.0)
    both_zero = (avg_gain == 0.0) & (avg_loss == 0.0)
    return rsi.where(~both_zero, 50.0)


def compute_features(
    frame: pd.DataFrame,
    config: Optional[IntegratedSupertrendPullbackConfig] = None,
) -> pd.DataFrame:
    cfg = config or IntegratedSupertrendPullbackConfig()
    cfg.validate()
    validated = _validated_frame(frame)
    close = validated["close"].astype(float)
    dema200 = _dema(close, cfg.dema_length)
    st = _supertrend(validated, cfg.supertrend_atr_length, cfg.supertrend_factor)
    rsi14 = _rsi(close, cfg.rsi_length)

    previous_open = validated["open"].shift(1)
    previous_close = close.shift(1)
    bullish_engulfing = (
        (close > validated["open"])
        & (previous_close < previous_open)
        & (validated["open"] <= previous_close)
        & (close >= previous_open)
    )
    bearish_engulfing = (
        (close < validated["open"])
        & (previous_close > previous_open)
        & (validated["open"] >= previous_close)
        & (close <= previous_open)
    )
    body = (close - validated["open"]).abs()
    lower_wick = pd.concat([validated["open"], close], axis=1).min(axis=1) - validated["low"]
    upper_wick = validated["high"] - pd.concat([validated["open"], close], axis=1).max(axis=1)
    hammer = (lower_wick >= 2.0 * body) & (upper_wick <= body)

    confluence_count = (
        validated["sr_touch"].astype(int)
        + validated["trendline_touch"].astype(int)
        + validated["ma50_touch"].astype(int)
    )
    rsi_cross_up = (rsi14 > 50.0) & (rsi14.shift(1) <= 50.0)
    rsi_cross_down = (rsi14 < 50.0) & (rsi14.shift(1) >= 50.0)

    long_confirmation = (
        bullish_engulfing
        | hammer
        | validated["counter_trend_break_up"]
        | rsi_cross_up.fillna(False)
    )
    short_confirmation = (
        bearish_engulfing
        | validated["counter_trend_break_down"]
        | rsi_cross_down.fillna(False)
    )

    long_regime = (close > dema200) & validated["structure_long"]
    short_regime = (close < dema200) & validated["structure_short"]
    long_location = confluence_count >= cfg.minimum_confluence_count
    short_location = confluence_count >= cfg.minimum_confluence_count
    long_st = st["supertrend_direction"] == UP
    short_st = st["supertrend_direction"] == DOWN
    dema_cross_up = (close > dema200) & (close.shift(1) <= dema200.shift(1))
    dema_cross_down = (close < dema200) & (close.shift(1) >= dema200.shift(1))
    long_trigger = st["supertrend_flip_up"] | dema_cross_up.fillna(False) | (
        long_confirmation & ~long_confirmation.shift(1, fill_value=False)
    )
    short_trigger = st["supertrend_flip_down"] | dema_cross_down.fillna(False) | (
        short_confirmation & ~short_confirmation.shift(1, fill_value=False)
    )

    return pd.DataFrame(
        {
            "dema200": dema200,
            "rsi14": rsi14,
            "supertrend_line": st["supertrend_line"],
            "supertrend_direction": st["supertrend_direction"],
            "supertrend_flip_up": st["supertrend_flip_up"].astype(bool),
            "supertrend_flip_down": st["supertrend_flip_down"].astype(bool),
            "confluence_count": confluence_count.astype(int),
            "bullish_engulfing": bullish_engulfing.fillna(False).astype(bool),
            "bearish_engulfing": bearish_engulfing.fillna(False).astype(bool),
            "hammer": hammer.fillna(False).astype(bool),
            "rsi_cross_up": rsi_cross_up.fillna(False).astype(bool),
            "rsi_cross_down": rsi_cross_down.fillna(False).astype(bool),
            "long_confirmation": long_confirmation.fillna(False).astype(bool),
            "short_confirmation": short_confirmation.fillna(False).astype(bool),
            "long_regime": long_regime.fillna(False).astype(bool),
            "short_regime": short_regime.fillna(False).astype(bool),
            "long_location": long_location.fillna(False).astype(bool),
            "short_location": short_location.fillna(False).astype(bool),
            "long_st": long_st.fillna(False).astype(bool),
            "short_st": short_st.fillna(False).astype(bool),
            "long_trigger": long_trigger.fillna(False).astype(bool),
            "short_trigger": short_trigger.fillna(False).astype(bool),
            "long_entry_signal": (long_regime & long_location & long_st & long_confirmation & long_trigger).fillna(False).astype(bool),
            "short_entry_signal": (short_regime & short_location & short_st & short_confirmation & short_trigger).fillna(False).astype(bool),
        },
        index=validated.index,
    )


def _normalize_side(value: Any) -> str:
    text = str(value or "flat").strip().lower()
    if text in {FLAT, "none", "0", ""}:
        return FLAT
    if text in {LONG, "buy", "1"}:
        return LONG
    if text in {SHORT, "sell", "-1"}:
        return SHORT
    raise ValueError("POSITION_SIDE_INVALID")


def evaluate_latest(
    frame: pd.DataFrame,
    *,
    state: Optional[Mapping[str, Any]] = None,
    symbol: str = "UNKNOWN",
    timeframe: str = "15m",
    replay_fold_id: str = "UNKNOWN",
    config: Optional[IntegratedSupertrendPullbackConfig] = None,
) -> Dict[str, Any]:
    cfg = config or IntegratedSupertrendPullbackConfig()
    try:
        cfg.validate()
        if timeframe != cfg.timeframe:
            raise ValueError("TIMEFRAME_NOT_15M")
        contract = load_contract()
        validated = _validated_frame(frame)
        features = compute_features(validated, cfg)
        side = _normalize_side((state or {}).get("position_side"))
    except Exception as exc:
        return {
            "ok": False,
            "strategy_id": STRATEGY_ID,
            "intent": BLOCK,
            "reason": f"FAIL_CLOSED:{type(exc).__name__}:{exc}",
            "authority": AUTHORITY,
            "state_before": dict(state or {}),
            "state_after": dict(state or {}),
        }

    i = len(validated) - 1
    if i < cfg.dema_length or not _finite(features["dema200"].iloc[i]) or not _finite(features["supertrend_line"].iloc[i]):
        return {
            "ok": True,
            "strategy_id": STRATEGY_ID,
            "intent": HOLD,
            "reason": "WARMUP_INCOMPLETE",
            "authority": AUTHORITY,
            "state_before": dict(state or {}),
            "state_after": dict(state or {}),
        }

    row = features.iloc[i]
    intent = HOLD
    reason = "NO_GATE_COMPLETE"
    if side == LONG and bool(row["supertrend_flip_down"]):
        intent, reason = EXIT_LONG, "MANDATORY_OPPOSITE_SUPERTREND_FLIP"
    elif side == SHORT and bool(row["supertrend_flip_up"]):
        intent, reason = EXIT_SHORT, "MANDATORY_OPPOSITE_SUPERTREND_FLIP"
    elif side == FLAT and bool(row["long_entry_signal"]):
        intent, reason = ENTER_LONG, "ALL_LONG_GATES_TRUE_CONFIRMED_CLOSE"
    elif side == FLAT and bool(row["short_entry_signal"]):
        intent, reason = ENTER_SHORT, "ALL_SHORT_GATES_TRUE_CONFIRMED_CLOSE"

    current_stop = (state or {}).get("active_stop")
    line = float(row["supertrend_line"])
    if side == LONG and _finite(current_stop) and int(row["supertrend_direction"]) == UP:
        active_stop = max(float(current_stop), line)
    elif side == SHORT and _finite(current_stop) and int(row["supertrend_direction"]) == DOWN:
        active_stop = min(float(current_stop), line)
    elif intent in {ENTER_LONG, ENTER_SHORT}:
        active_stop = line
    else:
        active_stop = current_stop

    after_side = side
    if intent == ENTER_LONG:
        after_side = LONG
    elif intent == ENTER_SHORT:
        after_side = SHORT
    elif intent in {EXIT_LONG, EXIT_SHORT}:
        after_side = FLAT
        active_stop = None

    after = dict(state or {})
    after.update({"position_side": after_side, "active_stop": active_stop})
    return {
        "ok": True,
        "strategy_id": STRATEGY_ID,
        "intent": intent,
        "reason": reason,
        "signal_time": "CONFIRMED_BAR_CLOSE",
        "fill_time": "NEXT_BAR_OPEN",
        "signal_index": i,
        "signal_close": float(validated["close"].iloc[i]),
        "supertrend_line": line,
        "confluence_count": int(row["confluence_count"]),
        "confirmation": {
            "bullish_engulfing": bool(row["bullish_engulfing"]),
            "bearish_engulfing": bool(row["bearish_engulfing"]),
            "hammer": bool(row["hammer"]),
            "rsi_cross_up": bool(row["rsi_cross_up"]),
            "rsi_cross_down": bool(row["rsi_cross_down"]),
            "counter_trend_break_up": bool(validated["counter_trend_break_up"].iloc[i]),
            "counter_trend_break_down": bool(validated["counter_trend_break_down"].iloc[i]),
        },
        "state_key": {
            "strategy_id": STRATEGY_ID,
            "symbol": str(symbol),
            "timeframe": str(timeframe),
            "replay_fold_id": str(replay_fold_id),
        },
        "state_before": dict(state or {}),
        "state_after": after,
        "contract_id": contract["contract_id"],
        "authority": AUTHORITY,
    }


__all__ = [
    "AUTHORITY",
    "BLOCK",
    "ENTER_LONG",
    "ENTER_SHORT",
    "EXIT_LONG",
    "EXIT_SHORT",
    "FLAT",
    "HOLD",
    "IntegratedSupertrendPullbackConfig",
    "LONG",
    "REQUIRED_GEOMETRY_COLUMNS",
    "SHORT",
    "STRATEGY_ID",
    "compute_features",
    "evaluate_latest",
    "load_contract",
]
