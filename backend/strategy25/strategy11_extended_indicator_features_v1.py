from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

VERSION = "STRATEGY11_EXTENDED_INDICATOR_FEATURES_V1"

EXTENDED_FEATURES = (
    "ema_cross_20_50_up", "ema_cross_50_100_up", "ema_cross_50_200_up", "ema_cross_100_200_up",
    "sma20_gt_50", "sma50_gt_200", "wma20_gt_50", "hma20_slope_up",
    "ichimoku_bull", "supertrend_up", "psar_bull", "aroon_up", "vortex_bull",
    "linreg_slope20_up", "ppo_positive", "trix_positive",
    "natr_pctile_gt_60", "bb_reentry_long", "bb_percent_b_gt_0_5",
    "bb_squeeze_release_ext", "keltner_break_long", "donchian_55_break_long",
    "choppiness_lt_38", "hv_expand",
    "williams_r_cross_up_m80", "ultimate_osc_gt_50", "tsi_cross_up",
    "awesome_osc_positive", "roc20_positive", "rsi_50_cross_up",
    "cmf_positive", "adl_slope_positive", "force_index_positive", "eom_positive",
    "volume_price_confirm",
    "fib_retrace_382_618_bull", "fib_618_reclaim", "fib_extension_break",
    "pivot_r1_break", "pivot_s1_reclaim", "confirmed_fractal_break", "prior_day_pivot_above",
    "zscore_revert_long", "bullish_engulfing", "hammer_causal",
    "inside_bar_break_long", "three_bar_momentum",
)


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.astype(float).ewm(span=length, adjust=False, min_periods=length).mean()


def _wma(series: pd.Series, length: int) -> pd.Series:
    weights = np.arange(1, length + 1, dtype=float)
    divisor = float(weights.sum())
    return series.astype(float).rolling(length, min_periods=length).apply(
        lambda values: float(np.dot(values, weights) / divisor), raw=True
    )


def _hma(series: pd.Series, length: int) -> pd.Series:
    half = max(2, length // 2)
    root = max(2, int(round(math.sqrt(length))))
    return _wma(2.0 * _wma(series, half) - _wma(series, length), root)


def _tr(frame: pd.DataFrame) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous = close.shift(1)
    return pd.concat((high - low, (high - previous).abs(), (low - previous).abs()), axis=1).max(axis=1)


def _atr(frame: pd.DataFrame, length: int) -> pd.Series:
    return _tr(frame).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _rolling_percentile(series: pd.Series, length: int = 100) -> pd.Series:
    minimum = max(30, length // 2)
    def rank_last(values: np.ndarray) -> float:
        if len(values) == 0 or not np.isfinite(values[-1]):
            return np.nan
        valid = values[np.isfinite(values)]
        if not len(valid):
            return np.nan
        return float(np.mean(valid <= values[-1]) * 100.0)
    return series.rolling(length, min_periods=minimum).apply(rank_last, raw=True)


def _linreg_slope(series: pd.Series, length: int) -> pd.Series:
    x = np.arange(length, dtype=float)
    return series.astype(float).rolling(length, min_periods=length).apply(
        lambda values: float(np.polyfit(x, values, 1)[0]), raw=True
    )


def _supertrend(frame: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    atr = _atr(frame, length)
    middle = (high + low) / 2.0
    upper_basic = middle + multiplier * atr
    lower_basic = middle - multiplier * atr
    upper = upper_basic.copy()
    lower = lower_basic.copy()
    trend = pd.Series(False, index=frame.index, dtype=bool)
    line = pd.Series(np.nan, index=frame.index, dtype=float)
    for i in range(1, len(frame)):
        if not np.isfinite(atr.iloc[i]):
            continue
        if np.isfinite(upper.iloc[i - 1]) and close.iloc[i - 1] <= upper.iloc[i - 1]:
            upper.iloc[i] = min(upper_basic.iloc[i], upper.iloc[i - 1])
        if np.isfinite(lower.iloc[i - 1]) and close.iloc[i - 1] >= lower.iloc[i - 1]:
            lower.iloc[i] = max(lower_basic.iloc[i], lower.iloc[i - 1])
        previous_trend = bool(trend.iloc[i - 1])
        if previous_trend:
            trend.iloc[i] = close.iloc[i] >= lower.iloc[i]
        else:
            trend.iloc[i] = close.iloc[i] > upper.iloc[i]
        line.iloc[i] = lower.iloc[i] if trend.iloc[i] else upper.iloc[i]
    return trend, line


def _psar(frame: pd.DataFrame, step: float = 0.02, maximum: float = 0.2) -> pd.Series:
    high = frame["high"].astype(float).to_numpy()
    low = frame["low"].astype(float).to_numpy()
    if len(frame) == 0:
        return pd.Series(dtype=float)
    sar = np.full(len(frame), np.nan, dtype=float)
    bullish = True
    extreme = high[0]
    acceleration = step
    sar[0] = low[0]
    for i in range(1, len(frame)):
        candidate = sar[i - 1] + acceleration * (extreme - sar[i - 1])
        if bullish:
            candidate = min(candidate, low[i - 1], low[i - 2] if i > 1 else low[i - 1])
            if low[i] < candidate:
                bullish = False
                candidate = extreme
                extreme = low[i]
                acceleration = step
            elif high[i] > extreme:
                extreme = high[i]
                acceleration = min(maximum, acceleration + step)
        else:
            candidate = max(candidate, high[i - 1], high[i - 2] if i > 1 else high[i - 1])
            if high[i] > candidate:
                bullish = True
                candidate = extreme
                extreme = high[i]
                acceleration = step
            elif low[i] < extreme:
                extreme = low[i]
                acceleration = min(maximum, acceleration + step)
        sar[i] = candidate
    return pd.Series(sar, index=frame.index)


def _daily_pivots(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    timestamp = pd.to_datetime(frame["timestamp"], utc=True)
    day = timestamp.dt.floor("D")
    daily = frame.assign(_day=day).groupby("_day", sort=True).agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")
    )
    previous = daily.shift(1)
    pivot = (previous["high"] + previous["low"] + previous["close"]) / 3.0
    r1 = 2.0 * pivot - previous["low"]
    s1 = 2.0 * pivot - previous["high"]
    return day.map(pivot), day.map(r1), day.map(s1)


def extend_feature_frame(frame: pd.DataFrame, base_features: pd.DataFrame | None = None) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume", "timestamp"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        raise ValueError("EXTENDED_FEATURE_FRAME_INVALID")
    data = base_features.copy() if base_features is not None else frame.copy()
    for column in frame.columns:
        if column not in data.columns:
            data[column] = frame[column]
    open_ = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    median = (high + low) / 2.0

    for length in (20, 50, 100, 200):
        data[f"sma{length}"] = close.rolling(length, min_periods=length).mean()
    for length in (20, 50):
        data[f"wma{length}"] = _wma(close, length)
    data["hma20"] = _hma(close, 20)

    for fast, slow in ((20, 50), (50, 100), (50, 200), (100, 200)):
        f = data[f"ema{fast}"] if f"ema{fast}" in data else _ema(close, fast)
        s = data[f"ema{slow}"] if f"ema{slow}" in data else _ema(close, slow)
        data[f"ema_cross_{fast}_{slow}_up"] = (f > s) & (f.shift(1) <= s.shift(1))
        data[f"ema_cross_{fast}_{slow}_down"] = (f < s) & (f.shift(1) >= s.shift(1))
    data["sma20_gt_50"] = data["sma20"] > data["sma50"]
    data["sma50_gt_200"] = data["sma50"] > data["sma200"]
    data["wma20_gt_50"] = data["wma20"] > data["wma50"]
    data["hma20_slope_up"] = data["hma20"] > data["hma20"].shift(3)

    conversion = (high.rolling(9, min_periods=9).max() + low.rolling(9, min_periods=9).min()) / 2.0
    base_line = (high.rolling(26, min_periods=26).max() + low.rolling(26, min_periods=26).min()) / 2.0
    span_a_at_source = (conversion + base_line) / 2.0
    span_b_at_source = (high.rolling(52, min_periods=52).max() + low.rolling(52, min_periods=52).min()) / 2.0
    cloud_a = span_a_at_source.shift(26)
    cloud_b = span_b_at_source.shift(26)
    data["ichimoku_bull"] = (conversion > base_line) & (close > cloud_a) & (close > cloud_b)

    supertrend_up, supertrend_line = _supertrend(frame)
    data["supertrend_up"] = supertrend_up
    data["supertrend_line"] = supertrend_line
    data["psar"] = _psar(frame)
    data["psar_bull"] = close > data["psar"]

    period = 25

    def most_recent_extreme_recency(values: np.ndarray, *, find_max: bool) -> float:
        reversed_values = values[::-1]
        bars_since = int(np.argmax(reversed_values) if find_max else np.argmin(reversed_values))
        return float((period - bars_since) / period * 100.0)

    data["aroon_up_value"] = high.rolling(period, min_periods=period).apply(
        lambda values: most_recent_extreme_recency(values, find_max=True), raw=True
    )
    data["aroon_down_value"] = low.rolling(period, min_periods=period).apply(
        lambda values: most_recent_extreme_recency(values, find_max=False), raw=True
    )
    data["aroon_up"] = (data["aroon_up_value"] >= 70.0) & (data["aroon_down_value"] <= 30.0)

    tr = _tr(frame)
    vm_plus = (high - low.shift(1)).abs()
    vm_minus = (low - high.shift(1)).abs()
    tr_sum = tr.rolling(14, min_periods=14).sum().replace(0.0, np.nan)
    data["vortex_plus"] = vm_plus.rolling(14, min_periods=14).sum() / tr_sum
    data["vortex_minus"] = vm_minus.rolling(14, min_periods=14).sum() / tr_sum
    data["vortex_bull"] = (data["vortex_plus"] > data["vortex_minus"]) & (
        data["vortex_plus"].shift(1) <= data["vortex_minus"].shift(1)
    )

    data["linreg_slope20"] = _linreg_slope(close, 20)
    data["linreg_slope20_up"] = data["linreg_slope20"] > 0.0
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    data["ppo"] = (ema12 - ema26) / ema26.replace(0.0, np.nan) * 100.0
    data["ppo_signal"] = _ema(data["ppo"], 9)
    data["ppo_positive"] = data["ppo"] > data["ppo_signal"]
    trix_line = _ema(_ema(_ema(close, 15), 15), 15)
    data["trix"] = trix_line.pct_change() * 100.0
    data["trix_positive"] = data["trix"] > 0.0

    atr14 = data["atr14"] if "atr14" in data else _atr(frame, 14)
    data["natr"] = atr14 / close.replace(0.0, np.nan) * 100.0
    data["natr_percentile"] = _rolling_percentile(data["natr"], 100)
    data["natr_pctile_gt_60"] = data["natr_percentile"] >= 60.0

    bb_mid = data["bb_mid"] if "bb_mid" in data else close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    bb_upper = data["bb_upper"] if "bb_upper" in data else bb_mid + 2.0 * bb_std
    bb_lower = data["bb_lower"] if "bb_lower" in data else bb_mid - 2.0 * bb_std
    data["bb_percent_b"] = (close - bb_lower) / (bb_upper - bb_lower).replace(0.0, np.nan)
    data["bb_reentry_long"] = (close > bb_lower) & (close.shift(1) <= bb_lower.shift(1))
    data["bb_percent_b_gt_0_5"] = data["bb_percent_b"] > 0.5
    bb_width = (bb_upper - bb_lower) / bb_mid.replace(0.0, np.nan)
    bb_width_pct = _rolling_percentile(bb_width, 100)
    data["bb_squeeze_release_ext"] = (bb_width_pct > 40.0) & (bb_width_pct.shift(1) <= 40.0)

    keltner_upper = data["keltner_upper"] if "keltner_upper" in data else _ema(close, 20) + 1.5 * atr14
    data["keltner_break_long"] = (close > keltner_upper) & (close.shift(1) <= keltner_upper.shift(1))
    prior_high55 = high.shift(1).rolling(55, min_periods=55).max()
    data["donchian_55_break_long"] = close > prior_high55

    range14 = (high.rolling(14, min_periods=14).max() - low.rolling(14, min_periods=14).min()).replace(0.0, np.nan)
    data["choppiness14"] = 100.0 * np.log10(tr.rolling(14, min_periods=14).sum() / range14) / np.log10(14.0)
    data["choppiness_lt_38"] = data["choppiness14"] < 38.2
    log_return = np.log(close / close.shift(1))
    data["historical_volatility20"] = log_return.rolling(20, min_periods=20).std(ddof=0) * math.sqrt(96.0 * 365.0)
    data["historical_volatility_percentile"] = _rolling_percentile(data["historical_volatility20"], 100)
    data["hv_expand"] = data["historical_volatility_percentile"] >= 60.0

    highest14 = high.rolling(14, min_periods=14).max()
    lowest14 = low.rolling(14, min_periods=14).min()
    data["williams_r14"] = -100.0 * (highest14 - close) / (highest14 - lowest14).replace(0.0, np.nan)
    data["williams_r_cross_up_m80"] = (data["williams_r14"] > -80.0) & (data["williams_r14"].shift(1) <= -80.0)

    previous_close = close.shift(1)
    buying_pressure = close - pd.concat((low, previous_close), axis=1).min(axis=1)
    true_range = pd.concat((high, previous_close), axis=1).max(axis=1) - pd.concat((low, previous_close), axis=1).min(axis=1)
    avg7 = buying_pressure.rolling(7, min_periods=7).sum() / true_range.rolling(7, min_periods=7).sum().replace(0.0, np.nan)
    avg14 = buying_pressure.rolling(14, min_periods=14).sum() / true_range.rolling(14, min_periods=14).sum().replace(0.0, np.nan)
    avg28 = buying_pressure.rolling(28, min_periods=28).sum() / true_range.rolling(28, min_periods=28).sum().replace(0.0, np.nan)
    data["ultimate_oscillator"] = 100.0 * (4.0 * avg7 + 2.0 * avg14 + avg28) / 7.0
    data["ultimate_osc_gt_50"] = data["ultimate_oscillator"] > 50.0

    momentum = close.diff()
    abs_momentum = momentum.abs()
    smoothed = _ema(_ema(momentum, 25), 13)
    smoothed_abs = _ema(_ema(abs_momentum, 25), 13)
    data["tsi"] = 100.0 * smoothed / smoothed_abs.replace(0.0, np.nan)
    data["tsi_signal"] = _ema(data["tsi"], 7)
    data["tsi_cross_up"] = (data["tsi"] > data["tsi_signal"]) & (data["tsi"].shift(1) <= data["tsi_signal"].shift(1))
    data["awesome_oscillator"] = median.rolling(5, min_periods=5).mean() - median.rolling(34, min_periods=34).mean()
    data["awesome_osc_positive"] = data["awesome_oscillator"] > 0.0
    data["roc20"] = close.pct_change(20) * 100.0
    data["roc20_positive"] = data["roc20"] > 0.0
    rsi14 = data["rsi14"] if "rsi14" in data else _rsi(close, 14)
    data["rsi_50_cross_up"] = (rsi14 > 50.0) & (rsi14.shift(1) <= 50.0)

    money_flow_multiplier = ((close - low) - (high - close)) / (high - low).replace(0.0, np.nan)
    money_flow_volume = money_flow_multiplier * volume
    data["cmf20"] = money_flow_volume.rolling(20, min_periods=20).sum() / volume.rolling(20, min_periods=20).sum().replace(0.0, np.nan)
    data["cmf_positive"] = data["cmf20"] > 0.0
    data["adl"] = money_flow_volume.fillna(0.0).cumsum()
    data["adl_slope20"] = data["adl"] - data["adl"].shift(20)
    data["adl_slope_positive"] = data["adl_slope20"] > 0.0
    data["force_index"] = _ema(close.diff() * volume, 13)
    data["force_index_positive"] = data["force_index"] > 0.0
    distance_moved = ((high + low) / 2.0).diff()
    box_ratio = (volume / 100_000.0) / (high - low).replace(0.0, np.nan)
    data["eom14"] = (distance_moved / box_ratio.replace(0.0, np.nan)).rolling(14, min_periods=14).mean()
    data["eom_positive"] = data["eom14"] > 0.0
    volume_mean20 = volume.rolling(20, min_periods=20).mean()
    data["volume_price_confirm"] = (close > close.shift(1)) & (volume > volume_mean20)

    prior_high = high.shift(1).rolling(55, min_periods=55).max()
    prior_low = low.shift(1).rolling(55, min_periods=55).min()
    fib_range = (prior_high - prior_low).replace(0.0, np.nan)
    data["fib382"] = prior_low + 0.382 * fib_range
    data["fib500"] = prior_low + 0.500 * fib_range
    data["fib618"] = prior_low + 0.618 * fib_range
    ema50 = data["ema50"] if "ema50" in data else _ema(close, 50)
    ema50_up = ema50 > ema50.shift(4)
    data["fib_retrace_382_618_bull"] = (close >= data["fib382"]) & (close <= data["fib618"]) & ema50_up
    data["fib_618_reclaim"] = (close > data["fib618"]) & (close.shift(1) <= data["fib618"].shift(1)) & ema50_up
    data["fib_extension_break"] = close > (prior_high + 0.272 * fib_range)

    pivot, r1, s1 = _daily_pivots(frame)
    data["daily_pivot"] = pivot.to_numpy()
    data["daily_r1"] = r1.to_numpy()
    data["daily_s1"] = s1.to_numpy()
    data["prior_day_pivot_above"] = close > data["daily_pivot"]
    data["pivot_r1_break"] = (close > data["daily_r1"]) & (close.shift(1) <= data["daily_r1"].shift(1))
    data["pivot_s1_reclaim"] = (close > data["daily_s1"]) & (low <= data["daily_s1"])

    confirmed = high.shift(2).where(high.shift(2) == high.rolling(5, min_periods=5).max())
    data["last_confirmed_fractal_high"] = confirmed.ffill()
    data["confirmed_fractal_break"] = (close > data["last_confirmed_fractal_high"]) & (
        close.shift(1) <= data["last_confirmed_fractal_high"].shift(1)
    )
    mean20 = close.rolling(20, min_periods=20).mean()
    std20 = close.rolling(20, min_periods=20).std(ddof=0)
    data["zscore20"] = (close - mean20) / std20.replace(0.0, np.nan)
    data["zscore_revert_long"] = (data["zscore20"] > -1.5) & (data["zscore20"].shift(1) <= -1.5)

    previous_open = open_.shift(1)
    previous_close2 = close.shift(1)
    data["bullish_engulfing"] = (close > open_) & (previous_close2 < previous_open) & (close >= previous_open) & (open_ <= previous_close2)
    body = (close - open_).abs()
    lower_wick = np.minimum(open_, close) - low
    upper_wick = high - np.maximum(open_, close)
    data["hammer_causal"] = (lower_wick >= body * 2.0) & (upper_wick <= body) & (close >= open_)
    inside_previous = (high.shift(1) < high.shift(2)) & (low.shift(1) > low.shift(2))
    data["inside_bar_break_long"] = inside_previous & (close > high.shift(1))
    data["three_bar_momentum"] = (close > close.shift(1)) & (close.shift(1) > close.shift(2)) & (volume >= volume_mean20)

    for name in EXTENDED_FEATURES:
        data[name] = data[name].fillna(False).astype(bool)
    return data


def all_scalar_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (bool, np.bool_)):
            output[str(key)] = bool(value)
        elif isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
            output[str(key)] = float(value)
    return output
