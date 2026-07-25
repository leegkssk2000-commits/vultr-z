from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import pandas as pd


FAMILY_MAP: Mapping[str, str] = MappingProxyType(
    {
        "alpha_combo": "hybrid",
        "anchor_vwap_trend": "trend_following",
        "bb_revert": "mean_reversion",
        "break_and_continue": "breakout_momentum",
        "ema_ribbon_scalp": "trend_following",
        "fvg_revert": "market_structure",
        "grid_rebalance": "mean_reversion",
        "keltner_trend": "trend_following",
        "liquidity_sweep": "market_structure",
        "mfi_rsi_div": "mean_reversion",
        "obv_trend": "trend_following",
        "pivot_reversal": "market_structure",
        "range_fade": "mean_reversion",
        "rbreaker_like": "breakout_momentum",
        "rsi_swing_fail": "mean_reversion",
        "scalp_snap": "hybrid",
        "session_bias": "session_volatility",
        "squeeze_break": "breakout_momentum",
        "sr_levels": "market_structure",
        "supertrend_pullback": "trend_following",
        "trend_ma_macd": "trend_following",
        "trend_rider": "trend_following",
        "turtle_trend": "breakout_momentum",
        "vol_spike_fade": "session_volatility",
        "vwap_revert": "mean_reversion",
    }
)


@dataclass(frozen=True)
class VariantSpec:
    variant_id: str
    family: str
    required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    description: str = ""


FAMILY_VARIANTS: Mapping[str, tuple[VariantSpec, ...]] = MappingProxyType(
    {
        "trend_following": (
            VariantSpec("BASE", "trend_following", description="No additional gate"),
            VariantSpec("TF_TREND_STACK", "trend_following", required=("trend_stack",)),
            VariantSpec("TF_TREND_STACK_MACD", "trend_following", required=("trend_stack", "macd_long")),
            VariantSpec("TF_TREND_STACK_VOLUME", "trend_following", required=("trend_stack", "volume_expand")),
            VariantSpec("TF_TREND_STACK_ATR", "trend_following", required=("trend_stack", "atr_expand")),
            VariantSpec("TF_NO_LATE_CHASE", "trend_following", forbidden=("late_chase",)),
            VariantSpec("TF_TREND_NO_LATE", "trend_following", required=("trend_stack",), forbidden=("late_chase",)),
            VariantSpec("TF_BREAKOUT_CONFIRM", "trend_following", required=("breakout_confirm", "trend_stack")),
        ),
        "mean_reversion": (
            VariantSpec("BASE", "mean_reversion", description="No additional gate"),
            VariantSpec("MR_RANGE_REGIME", "mean_reversion", required=("range_regime",)),
            VariantSpec("MR_EXTREME", "mean_reversion", required=("mean_reversion_extreme",)),
            VariantSpec("MR_RANGE_EXTREME", "mean_reversion", required=("range_regime", "mean_reversion_extreme")),
            VariantSpec("MR_EXHAUSTION", "mean_reversion", required=("exhaustion",)),
            VariantSpec("MR_RANGE_EXHAUSTION", "mean_reversion", required=("range_regime", "exhaustion")),
            VariantSpec("MR_NO_TREND", "mean_reversion", forbidden=("strong_trend",)),
            VariantSpec("MR_RANGE_NO_TREND", "mean_reversion", required=("range_regime",), forbidden=("strong_trend",)),
        ),
        "breakout_momentum": (
            VariantSpec("BASE", "breakout_momentum", description="No additional gate"),
            VariantSpec("BO_VOLUME", "breakout_momentum", required=("volume_expand",)),
            VariantSpec("BO_ATR", "breakout_momentum", required=("atr_expand",)),
            VariantSpec("BO_VOLUME_ATR", "breakout_momentum", required=("volume_expand", "atr_expand")),
            VariantSpec("BO_CLOSE_LOCATION", "breakout_momentum", required=("directional_close",)),
            VariantSpec("BO_TREND", "breakout_momentum", required=("trend_stack",)),
            VariantSpec("BO_TREND_VOLUME", "breakout_momentum", required=("trend_stack", "volume_expand")),
            VariantSpec("BO_FULL_CONFIRM", "breakout_momentum", required=("trend_stack", "volume_expand", "directional_close")),
        ),
        "market_structure": (
            VariantSpec("BASE", "market_structure", description="No additional gate"),
            VariantSpec("MS_TREND_ALIGN", "market_structure", required=("trend_stack",)),
            VariantSpec("MS_REJECTION", "market_structure", required=("rejection_candle",)),
            VariantSpec("MS_TREND_REJECTION", "market_structure", required=("trend_stack", "rejection_candle")),
            VariantSpec("MS_VOLUME_REJECTION", "market_structure", required=("volume_expand", "rejection_candle")),
            VariantSpec("MS_NO_LATE_CHASE", "market_structure", forbidden=("late_chase",)),
            VariantSpec("MS_TREND_NO_LATE", "market_structure", required=("trend_stack",), forbidden=("late_chase",)),
        ),
        "session_volatility": (
            VariantSpec("BASE", "session_volatility", description="No additional gate"),
            VariantSpec("SV_ACTIVE_SESSION", "session_volatility", required=("active_session",)),
            VariantSpec("SV_VOLUME", "session_volatility", required=("volume_expand",)),
            VariantSpec("SV_ATR", "session_volatility", required=("atr_expand",)),
            VariantSpec("SV_ACTIVE_VOLUME", "session_volatility", required=("active_session", "volume_expand")),
            VariantSpec("SV_ACTIVE_ATR", "session_volatility", required=("active_session", "atr_expand")),
            VariantSpec("SV_NO_LATE_CHASE", "session_volatility", forbidden=("late_chase",)),
        ),
        "hybrid": (
            VariantSpec("BASE", "hybrid", description="No additional gate"),
            VariantSpec("HY_TREND", "hybrid", required=("trend_stack",)),
            VariantSpec("HY_VOLUME", "hybrid", required=("volume_expand",)),
            VariantSpec("HY_ATR", "hybrid", required=("atr_expand",)),
            VariantSpec("HY_TREND_VOLUME", "hybrid", required=("trend_stack", "volume_expand")),
            VariantSpec("HY_NO_LATE_CHASE", "hybrid", forbidden=("late_chase",)),
            VariantSpec("HY_TREND_NO_LATE", "hybrid", required=("trend_stack",), forbidden=("late_chase",)),
        ),
    }
)


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.astype(float).ewm(span=length, adjust=False, min_periods=length).mean()


def _atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat((high - low, (high - prev).abs(), (low - prev).abs()), axis=1).max(axis=1)
    return tr.rolling(length, min_periods=length).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - 100.0 / (1.0 + rs)


def context_flags(history: pd.DataFrame, side: str) -> dict[str, bool]:
    if history is None or len(history) < 80:
        return {}
    frame = history.copy()
    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = frame[column].astype(float)

    close = frame["close"]
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema100 = _ema(close, 100)
    atr14 = _atr(frame, 14)
    atr_med = atr14.rolling(50, min_periods=25).median()
    rsi14 = _rsi(close, 14)
    volume = frame["volume"]
    volume_med = volume.rolling(30, min_periods=15).median()
    macd = _ema(close, 12) - _ema(close, 26)
    macd_signal = _ema(macd, 9)

    last = frame.iloc[-1]
    price = float(last["close"])
    open_ = float(last["open"])
    high = float(last["high"])
    low = float(last["low"])
    width = max(high - low, 1e-12)
    close_location = (price - low) / width
    atr_now = float(atr14.iloc[-1]) if pd.notna(atr14.iloc[-1]) else 0.0
    atr_base = float(atr_med.iloc[-1]) if pd.notna(atr_med.iloc[-1]) else 0.0
    ema20_now = float(ema20.iloc[-1]) if pd.notna(ema20.iloc[-1]) else price
    ema50_now = float(ema50.iloc[-1]) if pd.notna(ema50.iloc[-1]) else price
    ema100_now = float(ema100.iloc[-1]) if pd.notna(ema100.iloc[-1]) else price
    ema20_prev = float(ema20.iloc[-4]) if pd.notna(ema20.iloc[-4]) else ema20_now
    ema50_prev = float(ema50.iloc[-4]) if pd.notna(ema50.iloc[-4]) else ema50_now
    rsi_now = float(rsi14.iloc[-1]) if pd.notna(rsi14.iloc[-1]) else 50.0
    volume_now = float(volume.iloc[-1])
    volume_base = float(volume_med.iloc[-1]) if pd.notna(volume_med.iloc[-1]) else 0.0
    macd_now = float(macd.iloc[-1]) if pd.notna(macd.iloc[-1]) else 0.0
    macd_sig = float(macd_signal.iloc[-1]) if pd.notna(macd_signal.iloc[-1]) else 0.0
    if "timestamp" in frame.columns:
        timestamp = pd.Timestamp(last.get("timestamp"))
        timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        hour = int(timestamp.hour)
    else:
        hour = 12

    long_side = str(side).lower() != "short"
    trend_long = price > ema20_now > ema50_now > ema100_now and ema20_now > ema20_prev and ema50_now >= ema50_prev
    trend_short = price < ema20_now < ema50_now < ema100_now and ema20_now < ema20_prev and ema50_now <= ema50_prev
    trend_stack = trend_long if long_side else trend_short
    strong_trend = abs(ema20_now - ema100_now) / max(atr_now, 1e-12) >= 1.0
    range_regime = abs(ema20_now - ema100_now) / max(atr_now, 1e-12) <= 0.65
    atr_expand = atr_now > 0.0 and atr_base > 0.0 and atr_now >= atr_base * 1.10
    volume_expand = volume_base > 0.0 and volume_now >= volume_base * 1.35
    mean_reversion_extreme = rsi_now <= 35.0 if long_side else rsi_now >= 65.0
    exhaustion = (
        (rsi_now <= 40.0 and close_location >= 0.55)
        if long_side
        else (rsi_now >= 60.0 and close_location <= 0.45)
    )
    directional_close = close_location >= 0.68 if long_side else close_location <= 0.32
    rejection_candle = (
        (price > open_ and close_location >= 0.62)
        if long_side
        else (price < open_ and close_location <= 0.38)
    )
    macd_long = macd_now >= macd_sig if long_side else macd_now <= macd_sig
    prior_high = float(frame["high"].iloc[-21:-1].max())
    prior_low = float(frame["low"].iloc[-21:-1].min())
    breakout_confirm = price > prior_high if long_side else price < prior_low
    distance_atr = abs(price - ema20_now) / max(atr_now, 1e-12)
    late_chase = distance_atr > 1.75
    active_session = 7 <= hour <= 20

    return {
        "trend_stack": trend_stack,
        "strong_trend": strong_trend,
        "range_regime": range_regime,
        "atr_expand": atr_expand,
        "volume_expand": volume_expand,
        "mean_reversion_extreme": mean_reversion_extreme,
        "exhaustion": exhaustion,
        "directional_close": directional_close,
        "rejection_candle": rejection_candle,
        "macd_long": macd_long,
        "breakout_confirm": breakout_confirm,
        "late_chase": late_chase,
        "active_session": active_session,
    }


def variant_allows(spec: VariantSpec, history: pd.DataFrame, result: Mapping[str, Any]) -> bool:
    action = str(result.get("action") or "hold").lower()
    if action != "enter":
        return True
    side = str(result.get("side") or "long").lower()
    flags = context_flags(history, side)
    return all(flags.get(name) is True for name in spec.required) and all(flags.get(name) is not True for name in spec.forbidden)


def wrap_strategy(strategy: Callable[..., dict[str, Any]], spec: VariantSpec) -> Callable[..., dict[str, Any]]:
    def wrapped(history: pd.DataFrame, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = strategy(history, *args, **kwargs)
        if not isinstance(result, Mapping):
            raise TypeError("STRATEGY_RESULT_MAPPING_REQUIRED")
        output = dict(result)
        allowed = variant_allows(spec, history, output)
        indicators = dict(output.get("indicators") or {})
        indicators["family_variant_id"] = spec.variant_id
        indicators["family_variant_allowed"] = allowed
        if not allowed and str(output.get("action") or "hold").lower() == "enter":
            indicators["pre_variant_side"] = output.get("side")
            indicators["pre_variant_why"] = output.get("why")
            output.update({"side": None, "action": "hold", "size": 0.0, "why": f"family_variant_block:{spec.variant_id}", "skill": "none", "confidence": 0.0})
        output["indicators"] = indicators
        return output

    wrapped.__name__ = f"{getattr(strategy, '__name__', 'strategy')}__{spec.variant_id.lower()}"
    return wrapped


def variants_for(strategy_id: str) -> Sequence[VariantSpec]:
    family = FAMILY_MAP[strategy_id]
    return FAMILY_VARIANTS[family]
