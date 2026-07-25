from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
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
class GateSpec:
    gate_id: str
    family: str
    required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class ExitSpec:
    exit_id: str
    stop_mult: float = 1.0
    target_mult: float = 1.0
    breakeven_r: float | None = None
    partial_r: float | None = None
    partial_fraction: float = 0.0
    runner_target_r: float | None = None
    trail_activate_r: float | None = None
    trail_atr_mult: float | None = None
    time_stop_bars: int | None = None


EXIT_SPECS: tuple[ExitSpec, ...] = (
    ExitSpec("ORIG"),
    ExitSpec("RR125", target_mult=1.25),
    ExitSpec("RR150", target_mult=1.50),
    ExitSpec("TIGHT085", stop_mult=0.85),
    ExitSpec("WIDE115_RR125", stop_mult=1.15, target_mult=1.25),
    ExitSpec("BE075", breakeven_r=0.75),
    ExitSpec("BE100", breakeven_r=1.00),
    ExitSpec("PARTIAL30_1R_RUNNER2R", partial_r=1.0, partial_fraction=0.30, runner_target_r=2.0, breakeven_r=1.0),
    ExitSpec("TRAIL1R_ATR1", trail_activate_r=1.0, trail_atr_mult=1.0),
    ExitSpec("TIME48", time_stop_bars=48),
)


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.astype(float).ewm(span=length, adjust=False, min_periods=length).mean()


def _atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat((high - low, (high - previous).abs(), (low - previous).abs()), axis=1).max(axis=1)
    return true_range.rolling(length, min_periods=length).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _mfi(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    flow = typical * frame["volume"]
    direction = typical.diff()
    positive = flow.where(direction > 0.0, 0.0).rolling(length, min_periods=length).sum()
    negative = flow.where(direction < 0.0, 0.0).rolling(length, min_periods=length).sum()
    ratio = positive / negative.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + ratio)


def _adx(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0)
    atr = _atr(frame, length)
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr.replace(0.0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def _cci(frame: pd.DataFrame, length: int = 20) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    mean = typical.rolling(length, min_periods=length).mean()
    deviation = typical.rolling(length, min_periods=length).apply(lambda values: float(np.mean(np.abs(values - np.mean(values)))), raw=True)
    return (typical - mean) / (0.015 * deviation.replace(0.0, np.nan))


def _rolling_percentile(series: pd.Series, length: int = 100) -> pd.Series:
    def rank_last(values: np.ndarray) -> float:
        if len(values) == 0 or not np.isfinite(values[-1]):
            return np.nan
        return float(np.mean(values <= values[-1]) * 100.0)
    return series.rolling(length, min_periods=max(30, length // 2)).apply(rank_last, raw=True)


def compute_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume", "timestamp"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        raise ValueError("FEATURE_FRAME_INVALID")
    data = frame.copy()
    for column in ("open", "high", "low", "close", "volume"):
        data[column] = data[column].astype(float)

    close = data["close"]
    open_ = data["open"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]
    width = (high - low).replace(0.0, np.nan)

    for length in (10, 20, 50, 100, 200):
        data[f"ema{length}"] = _ema(close, length)
    data["atr14"] = _atr(data, 14)
    data["atr_pct"] = data["atr14"] / close.replace(0.0, np.nan) * 100.0
    data["atr_percentile"] = _rolling_percentile(data["atr_pct"], 100)
    data["rsi14"] = _rsi(close, 14)
    data["mfi14"] = _mfi(data, 14)
    data["adx14"] = _adx(data, 14)
    data["cci20"] = _cci(data, 20)
    data["roc10"] = close.pct_change(10) * 100.0

    data["macd"] = _ema(close, 12) - _ema(close, 26)
    data["macd_signal"] = _ema(data["macd"], 9)
    data["macd_hist"] = data["macd"] - data["macd_signal"]

    direction = np.sign(close.diff()).fillna(0.0)
    data["obv"] = (direction * volume).cumsum()
    data["obv_slope10"] = data["obv"] - data["obv"].shift(10)

    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    data["bb_mid"] = bb_mid
    data["bb_upper"] = bb_mid + 2.0 * bb_std
    data["bb_lower"] = bb_mid - 2.0 * bb_std
    data["bb_z"] = (close - bb_mid) / bb_std.replace(0.0, np.nan)
    data["bb_width"] = (data["bb_upper"] - data["bb_lower"]) / bb_mid.replace(0.0, np.nan)
    data["bb_width_percentile"] = _rolling_percentile(data["bb_width"], 100)

    data["keltner_upper"] = data["ema20"] + 1.5 * data["atr14"]
    data["keltner_lower"] = data["ema20"] - 1.5 * data["atr14"]
    squeeze = (data["bb_upper"] < data["keltner_upper"]) & (data["bb_lower"] > data["keltner_lower"])
    data["squeeze_on"] = squeeze
    data["squeeze_release"] = squeeze.shift(1).fillna(False) & ~squeeze

    low14 = data["rsi14"].rolling(14, min_periods=14).min()
    high14 = data["rsi14"].rolling(14, min_periods=14).max()
    data["stoch_rsi"] = (data["rsi14"] - low14) / (high14 - low14).replace(0.0, np.nan)
    data["stoch_cross_up"] = (data["stoch_rsi"] > 0.20) & (data["stoch_rsi"].shift(1) <= 0.20)

    typical = (high + low + close) / 3.0
    date_key = pd.to_datetime(data["timestamp"], utc=True).dt.floor("D")
    pv = typical * volume
    data["daily_vwap"] = pv.groupby(date_key).cumsum() / volume.groupby(date_key).cumsum().replace(0.0, np.nan)
    data["vwap_distance_atr"] = (close - data["daily_vwap"]) / data["atr14"].replace(0.0, np.nan)

    volume_mean = volume.rolling(30, min_periods=20).mean()
    volume_std = volume.rolling(30, min_periods=20).std(ddof=0)
    data["volume_z"] = (volume - volume_mean) / volume_std.replace(0.0, np.nan)

    data["close_location"] = (close - low) / width
    data["body_atr"] = (close - open_).abs() / data["atr14"].replace(0.0, np.nan)
    data["lower_wick_ratio"] = (np.minimum(open_, close) - low).clip(lower=0.0) / width
    data["upper_wick_ratio"] = (high - np.maximum(open_, close)).clip(lower=0.0) / width

    prior_high20 = high.shift(1).rolling(20, min_periods=20).max()
    prior_low20 = low.shift(1).rolling(20, min_periods=20).min()
    data["donchian_break_long"] = close > prior_high20
    data["sweep_reclaim_long"] = (low < prior_low20) & (close > prior_low20)
    data["fvg_bull"] = low > high.shift(2)
    data["rejection_long"] = (close > open_) & (data["lower_wick_ratio"] >= 0.35) & (data["close_location"] >= 0.60)
    data["directional_close_long"] = data["close_location"] >= 0.70

    data["ema20_slope"] = data["ema20"] - data["ema20"].shift(4)
    data["ema50_slope"] = data["ema50"] - data["ema50"].shift(4)
    data["distance_ema20_atr"] = (close - data["ema20"]).abs() / data["atr14"].replace(0.0, np.nan)

    hourly = data.set_index(pd.DatetimeIndex(pd.to_datetime(data["timestamp"], utc=True))).resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    hourly["ema20_h"] = _ema(hourly["close"], 20)
    hourly["ema50_h"] = _ema(hourly["close"], 50)
    hourly["htf_trend_up"] = (hourly["close"] > hourly["ema20_h"]) & (hourly["ema20_h"] > hourly["ema50_h"])
    htf = hourly[["htf_trend_up"]].reindex(pd.DatetimeIndex(pd.to_datetime(data["timestamp"], utc=True)), method="ffill")
    data["htf_trend_up"] = htf["htf_trend_up"].fillna(False).to_numpy()

    timestamp = pd.to_datetime(data["timestamp"], utc=True)
    data["active_session"] = timestamp.dt.hour.between(7, 20)

    data["trend_ema20_50"] = (close > data["ema20"]) & (data["ema20"] > data["ema50"]) & (data["ema20_slope"] > 0.0)
    data["trend_ema20_50_200"] = data["trend_ema20_50"] & (data["ema50"] > data["ema200"]) & (data["ema50_slope"] >= 0.0)
    data["macd_positive"] = data["macd_hist"] > 0.0
    data["obv_positive"] = data["obv_slope10"] > 0.0
    data["roc_positive"] = data["roc10"] > 0.0
    data["vwap_above"] = close > data["daily_vwap"]
    data["vwap_below"] = close < data["daily_vwap"]
    data["pullback_near_ema"] = data["distance_ema20_atr"] <= 0.80
    data["no_late_15"] = data["distance_ema20_atr"] <= 1.50
    data["no_late_20"] = data["distance_ema20_atr"] <= 2.00
    data["no_late_25"] = data["distance_ema20_atr"] <= 2.50

    for level in (15, 20, 25):
        data[f"adx_gt_{level}"] = data["adx14"] >= float(level)
    data["adx_lt_20"] = data["adx14"] < 20.0
    data["adx_lt_25"] = data["adx14"] < 25.0
    for level in (30, 35, 40, 50, 55, 60):
        if level <= 40:
            data[f"rsi_lt_{level}"] = data["rsi14"] <= float(level)
        else:
            data[f"rsi_gt_{level}"] = data["rsi14"] >= float(level)
    data["mfi_lt_30"] = data["mfi14"] <= 30.0
    data["mfi_lt_40"] = data["mfi14"] <= 40.0
    data["mfi_gt_50"] = data["mfi14"] >= 50.0
    data["cci_lt_m100"] = data["cci20"] <= -100.0
    for level in (0.0, 0.5, 1.0, 1.5):
        suffix = str(level).replace(".", "_")
        data[f"volume_z_gt_{suffix}"] = data["volume_z"] >= level
    for level in (40, 60, 80):
        data[f"atr_pctile_gt_{level}"] = data["atr_percentile"] >= float(level)
        data[f"atr_pctile_lt_{level}"] = data["atr_percentile"] <= float(level)
    data["bb_z_lt_m1"] = data["bb_z"] <= -1.0
    data["bb_z_lt_m1_5"] = data["bb_z"] <= -1.5
    data["bb_z_lt_m2"] = data["bb_z"] <= -2.0
    data["bb_width_expand"] = data["bb_width_percentile"] >= 60.0
    data["vwap_below_1atr"] = data["vwap_distance_atr"] <= -1.0
    data["vwap_below_1_5atr"] = data["vwap_distance_atr"] <= -1.5

    return data


def _spec(gate_id: str, family: str, required: Sequence[str] = (), forbidden: Sequence[str] = (), description: str = "") -> GateSpec:
    return GateSpec(gate_id, family, tuple(required), tuple(forbidden), description)


def gate_specs_for(strategy_id: str) -> tuple[GateSpec, ...]:
    family = FAMILY_MAP[strategy_id]
    common = [_spec("BASE", family, description="No external context gate")]
    if family == "trend_following":
        common.extend(
            [
                _spec("TF_EMA", family, ("trend_ema20_50",)),
                _spec("TF_EMA_ADX20", family, ("trend_ema20_50", "adx_gt_20")),
                _spec("TF_EMA_ADX25", family, ("trend_ema20_50", "adx_gt_25")),
                _spec("TF_EMA_MACD", family, ("trend_ema20_50", "macd_positive")),
                _spec("TF_EMA_OBV", family, ("trend_ema20_50", "obv_positive")),
                _spec("TF_EMA_HTF", family, ("trend_ema20_50", "htf_trend_up")),
                _spec("TF_EMA_HTF_MACD", family, ("trend_ema20_50", "htf_trend_up", "macd_positive")),
                _spec("TF_EMA_VOLUME", family, ("trend_ema20_50", "volume_z_gt_0_5")),
                _spec("TF_EMA_ATR60", family, ("trend_ema20_50", "atr_pctile_gt_60")),
                _spec("TF_EMA_RSI50", family, ("trend_ema20_50", "rsi_gt_50")),
                _spec("TF_EMA_NO_LATE15", family, ("trend_ema20_50", "no_late_15")),
                _spec("TF_EMA_NO_LATE20", family, ("trend_ema20_50", "no_late_20")),
                _spec("TF_PULLBACK", family, ("trend_ema20_50", "pullback_near_ema", "rsi_gt_50")),
                _spec("TF_STRICT", family, ("trend_ema20_50_200", "htf_trend_up", "adx_gt_20", "macd_positive", "no_late_20")),
            ]
        )
    elif family == "mean_reversion":
        common.extend(
            [
                _spec("MR_LOW_ADX", family, ("adx_lt_25",)),
                _spec("MR_BB1", family, ("bb_z_lt_m1",)),
                _spec("MR_BB15", family, ("bb_z_lt_m1_5",)),
                _spec("MR_RSI35", family, ("rsi_lt_35",)),
                _spec("MR_MFI40", family, ("mfi_lt_40",)),
                _spec("MR_RANGE_BB", family, ("adx_lt_25", "bb_z_lt_m1")),
                _spec("MR_RANGE_RSI", family, ("adx_lt_25", "rsi_lt_40")),
                _spec("MR_RANGE_BB_RSI", family, ("adx_lt_25", "bb_z_lt_m1", "rsi_lt_40")),
                _spec("MR_VWAP1", family, ("vwap_below_1atr",)),
                _spec("MR_VWAP15", family, ("vwap_below_1_5atr",)),
                _spec("MR_REJECTION", family, ("rejection_long",)),
                _spec("MR_SWEEP", family, ("sweep_reclaim_long",)),
                _spec("MR_STOCH", family, ("stoch_cross_up",)),
                _spec("MR_CCI", family, ("cci_lt_m100",)),
                _spec("MR_STRICT", family, ("adx_lt_20", "bb_z_lt_m1_5", "rsi_lt_35", "rejection_long")),
            ]
        )
    elif family == "breakout_momentum":
        common.extend(
            [
                _spec("BO_DONCHIAN", family, ("donchian_break_long",)),
                _spec("BO_DONCHIAN_VOL", family, ("donchian_break_long", "volume_z_gt_0_5")),
                _spec("BO_DONCHIAN_VOL1", family, ("donchian_break_long", "volume_z_gt_1_0")),
                _spec("BO_DONCHIAN_ATR", family, ("donchian_break_long", "atr_pctile_gt_60")),
                _spec("BO_SQUEEZE", family, ("squeeze_release",)),
                _spec("BO_SQUEEZE_VOL", family, ("squeeze_release", "volume_z_gt_0_5")),
                _spec("BO_CLOSE_VOL", family, ("directional_close_long", "volume_z_gt_0_5")),
                _spec("BO_TREND_DONCHIAN", family, ("trend_ema20_50", "donchian_break_long")),
                _spec("BO_TREND_ADX", family, ("trend_ema20_50", "adx_gt_20", "directional_close_long")),
                _spec("BO_TREND_VOL_ATR", family, ("trend_ema20_50", "volume_z_gt_0_5", "atr_pctile_gt_60")),
                _spec("BO_NO_LATE", family, ("no_late_20",)),
                _spec("BO_STRICT", family, ("trend_ema20_50", "adx_gt_25", "volume_z_gt_1_0", "directional_close_long", "no_late_20")),
            ]
        )
    elif family == "market_structure":
        common.extend(
            [
                _spec("MS_SWEEP", family, ("sweep_reclaim_long",)),
                _spec("MS_FVG", family, ("fvg_bull",)),
                _spec("MS_REJECTION", family, ("rejection_long",)),
                _spec("MS_SWEEP_REJECTION", family, ("sweep_reclaim_long", "rejection_long")),
                _spec("MS_SWEEP_VOLUME", family, ("sweep_reclaim_long", "volume_z_gt_0_5")),
                _spec("MS_TREND_SWEEP", family, ("trend_ema20_50", "sweep_reclaim_long")),
                _spec("MS_TREND_FVG", family, ("trend_ema20_50", "fvg_bull")),
                _spec("MS_LOW_ADX_REJECT", family, ("adx_lt_25", "rejection_long")),
                _spec("MS_VWAP_REJECT", family, ("vwap_below", "rejection_long")),
                _spec("MS_NO_LATE", family, ("no_late_20",)),
                _spec("MS_STRICT", family, ("trend_ema20_50", "sweep_reclaim_long", "rejection_long", "volume_z_gt_0")),
            ]
        )
    elif family == "session_volatility":
        common.extend(
            [
                _spec("SV_ACTIVE", family, ("active_session",)),
                _spec("SV_VOLUME", family, ("volume_z_gt_0_5",)),
                _spec("SV_VOLUME1", family, ("volume_z_gt_1_0",)),
                _spec("SV_ATR60", family, ("atr_pctile_gt_60",)),
                _spec("SV_ACTIVE_VOL", family, ("active_session", "volume_z_gt_0_5")),
                _spec("SV_VOL_ATR", family, ("volume_z_gt_0_5", "atr_pctile_gt_60")),
                _spec("SV_REJECTION_VOL", family, ("rejection_long", "volume_z_gt_0_5")),
                _spec("SV_RANGE_FADE", family, ("adx_lt_25", "bb_z_lt_m1", "rejection_long")),
                _spec("SV_TREND", family, ("trend_ema20_50", "volume_z_gt_0_5")),
                _spec("SV_NO_LATE", family, ("no_late_20",)),
                _spec("SV_STRICT", family, ("active_session", "volume_z_gt_1_0", "atr_pctile_gt_60", "rejection_long")),
            ]
        )
    else:
        common.extend(
            [
                _spec("HY_TREND", family, ("trend_ema20_50",)),
                _spec("HY_TREND_MACD", family, ("trend_ema20_50", "macd_positive")),
                _spec("HY_TREND_VOLUME", family, ("trend_ema20_50", "volume_z_gt_0_5")),
                _spec("HY_RANGE_REJECT", family, ("adx_lt_25", "rejection_long")),
                _spec("HY_SWEEP", family, ("sweep_reclaim_long",)),
                _spec("HY_BREAKOUT", family, ("donchian_break_long", "volume_z_gt_0_5")),
                _spec("HY_NO_LATE", family, ("no_late_20",)),
                _spec("HY_HTF", family, ("htf_trend_up", "macd_positive")),
                _spec("HY_STRICT", family, ("trend_ema20_50", "htf_trend_up", "adx_gt_20", "volume_z_gt_0_5", "no_late_20")),
            ]
        )
    return tuple(common)


def gate_allows(spec: GateSpec, feature_row: Mapping[str, Any]) -> bool:
    return all(bool(feature_row.get(name)) for name in spec.required) and all(not bool(feature_row.get(name)) for name in spec.forbidden)


def feature_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "atr14", "atr_pct", "atr_percentile", "rsi14", "mfi14", "adx14", "cci20", "roc10",
        "macd_hist", "obv_slope10", "bb_z", "bb_width_percentile", "stoch_rsi", "vwap_distance_atr",
        "volume_z", "close_location", "body_atr", "lower_wick_ratio", "upper_wick_ratio", "distance_ema20_atr",
        "trend_ema20_50", "trend_ema20_50_200", "htf_trend_up", "macd_positive", "obv_positive",
        "donchian_break_long", "squeeze_release", "sweep_reclaim_long", "fvg_bull", "rejection_long",
        "directional_close_long", "active_session",
    )
    output: dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if isinstance(value, (bool, np.bool_)):
            output[key] = bool(value)
        elif value is not None and pd.notna(value):
            try:
                output[key] = float(value)
            except (TypeError, ValueError):
                pass
    return output
