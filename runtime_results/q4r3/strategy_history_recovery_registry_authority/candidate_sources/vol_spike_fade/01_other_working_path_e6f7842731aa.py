from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "vol_spike_fade"

    class StrategyIntent: # type: ignore
        HOLD = "hold"
        ENTER_LONG = "enter_long"
        EXIT_LONG = "exit_long"
        REDUCE = "reduce"
        BLOCK = "block"

    class StrategyDecision: # type: ignore
        def __init__(
            self,
            ok: bool,
            intent: str,
            confidence: float = 0.0,
            reason: str = "",
            target_qty: float = 0.0,
            target_price: float = 0.0,
            tags: Optional[List[str]] = None,
            payload: Optional[Dict[str, Any]] = None,
        ) -> None:
            self.ok = ok
            self.intent = intent
            self.confidence = confidence
            self.reason = reason
            self.target_qty = target_qty
            self.target_price = target_price
            self.tags = tags or []
            self.payload = payload or {}

    DecisionContext = Any # type: ignore


@dataclass
class VolSpikeFadeConfig:
    vol_lookback: int = 30
    atr_len: int = 14
    ema_fast_len: int = 20
    ema_slow_len: int = 55
    min_bars: int = 90

    vol_mult: float = 2.40
    atr_spike_mult: float = 1.40

    min_atr_pct: float = 0.25
    max_atr_pct: float = 6.50
    max_trend_stretch_pct: float = 4.80

    peak_body_atr_min: float = 0.80
    wick_ratio_max: float = 0.45
    reclaim_atr_min: float = 0.20

    base_rr: float = 1.60
    beam_rr: float = 2.10
    stop_atr_mult: float = 0.45

    long_base_size: float = 0.32
    short_base_size: float = 0.28
    beam_bonus_long: float = 0.12
    beam_bonus_short: float = 0.10

    scale_in_size_long: float = 0.16
    scale_in_size_short: float = 0.12
    water_add_size_long: float = 0.10
    water_add_size_short: float = 0.08

    max_add_count: int = 2
    max_pyramiding: int = 2

    water_add_extension_atr: float = 1.80
    progress_to_mean_min: float = 0.35


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return tr.rolling(length, min_periods=length).mean()


def _close_location(close: float, low: float, high: float) -> float:
    width = max(high - low, 1e-9)
    return (close - low) / width


def _body_ratio(open_: float, close: float, low: float, high: float) -> float:
    width = max(high - low, 1e-9)
    return abs(close - open_) / width


def _upper_wick_ratio(open_: float, close: float, low: float, high: float) -> float:
    width = max(high - low, 1e-9)
    body_high = max(open_, close)
    return max(high - body_high, 0.0) / width


def _lower_wick_ratio(open_: float, close: float, low: float, high: float) -> float:
    width = max(high - low, 1e-9)
    body_low = min(open_, close)
    return max(body_low - low, 0.0) / width


def _infer_position_state(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    state = dict(state or {})
    return {
        "position_side": str(state.get("position_side") or "").lower(),
        "position_qty": _to_float(state.get("position_qty")),
        "avg_entry": _to_float(state.get("avg_entry")),
        "add_count": int(state.get("add_count") or 0),
        "last_add_price": _to_float(state.get("last_add_price")),
    }


def _build_result(
    *,
    side: Optional[str],
    action: str,
    size: float,
    entry: float,
    sl: float,
    tp: float,
    pyramiding: int,
    why: str,
    skill: str,
    confidence: float,
    tags: List[str],
    indicators: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "side": side,
        "action": action,
        "size": float(max(size, 0.0)),
        "entry": float(entry),
        "sl": float(sl),
        "tp": float(tp),
        "pyramiding": int(pyramiding),
        "why": why,
        "skill": skill,
        "confidence": float(confidence),
        "tags": tags,
        "indicators": indicators,
    }


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[VolSpikeFadeConfig] = None,
) -> Dict[str, Any]:
    cfg = config or VolSpikeFadeConfig()

    required_cols = {"open", "high", "low", "close", "volume"}
    if df is None or df.empty or not required_cols.issubset(df.columns):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="volfade_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.vol_lookback + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="volfade_not_enough_bars",
            skill="none",
            confidence=0.0,
            tags=["warmup"],
            indicators={},
        )

    if str(risk_action or "hold").lower() in ("block", "stop", "rollback"):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why=f"risk_gate_{risk_action}",
            skill="none",
            confidence=0.0,
            tags=["risk_gated"],
            indicators={},
        )

    df = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    df["atr"] = _atr(df, cfg.atr_len)
    df["ema_fast"] = _ema(df["close"], cfg.ema_fast_len)
    df["ema_slow"] = _ema(df["close"], cfg.ema_slow_len)
    df["vol_ma"] = df["volume"].rolling(cfg.vol_lookback, min_periods=cfg.vol_lookback).mean()
    df["atr_ma"] = df["atr"].rolling(cfg.vol_lookback, min_periods=cfg.vol_lookback).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    atr_now = _to_float(last["atr"])
    atr_ma = _to_float(last["atr_ma"])
    vol_now = _to_float(last["volume"])
    vol_ma = _to_float(last["vol_ma"])
    ema_fast = _to_float(last["ema_fast"])
    ema_slow = _to_float(last["ema_slow"])

    if min(price, atr_now, atr_ma, vol_ma, ema_fast, ema_slow) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="volfade_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    atr_pct = (atr_now / max(price, 1e-9)) * 100.0
    body_atr = abs(price - open_) / max(atr_now, 1e-9)
    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)
    upper_wick_ratio = _upper_wick_ratio(open_, price, low, high)
    lower_wick_ratio = _lower_wick_ratio(open_, price, low, high)
    reclaim_atr = abs(price - _to_float(prev["close"])) / max(atr_now, 1e-9)

    vol_spike = vol_now > vol_ma * cfg.vol_mult
    atr_spike = atr_now > atr_ma * cfg.atr_spike_mult
    spike_ok = vol_spike and atr_spike

    trend_up = price > ema_fast > ema_slow
    trend_down = price < ema_fast < ema_slow
    trend_stretch_pct = abs((price - ema_slow) / max(ema_slow, 1e-9)) * 100.0

    strong_up_peak = (
        price > open_
        and body_atr >= cfg.peak_body_atr_min
        and upper_wick_ratio <= cfg.wick_ratio_max
        and close_loc >= 0.60
    )
    strong_down_peak = (
        price < open_
        and body_atr >= cfg.peak_body_atr_min
        and lower_wick_ratio <= cfg.wick_ratio_max
        and close_loc <= 0.40
    )

    short_fade_setup = spike_ok and strong_up_peak
    long_fade_setup = spike_ok and strong_down_peak

    short_beam = short_fade_setup and reclaim_atr >= cfg.reclaim_atr_min and trend_stretch_pct >= 1.30
    long_beam = long_fade_setup and reclaim_atr >= cfg.reclaim_atr_min and trend_stretch_pct >= 1.30

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct

    # Fade veto in extreme directional trend
    long_veto = trend_down and trend_stretch_pct >= cfg.max_trend_stretch_pct
    short_veto = trend_up and trend_stretch_pct >= cfg.max_trend_stretch_pct

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_ma": round(atr_ma, 6),
        "atr_pct": round(atr_pct, 6),
        "vol_now": round(vol_now, 6),
        "vol_ma": round(vol_ma, 6),
        "vol_spike": vol_spike,
        "atr_spike": atr_spike,
        "spike_ok": spike_ok,
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "trend_up": trend_up,
        "trend_down": trend_down,
        "trend_stretch_pct": round(trend_stretch_pct, 6),
        "body_atr": round(body_atr, 6),
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "upper_wick_ratio": round(upper_wick_ratio, 6),
        "lower_wick_ratio": round(lower_wick_ratio, 6),
        "reclaim_atr": round(reclaim_atr, 6),
        "strong_up_peak": strong_up_peak,
        "strong_down_peak": strong_down_peak,
        "short_fade_setup": short_fade_setup,
        "long_fade_setup": long_fade_setup,
        "short_beam": short_beam,
        "long_beam": long_beam,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "avg_entry": pos["avg_entry"],
        "add_count": pos["add_count"],
    }

    if not vol_ok:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="volfade_volatility_out_of_range",
            skill="none",
            confidence=0.0,
            tags=["volatility_gate"],
            indicators=indicators,
        )

    if long_fade_setup and long_veto:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="volfade_long_veto_strong_downtrend",
            skill="none",
            confidence=0.0,
            tags=["trend_veto", "long"],
            indicators=indicators,
        )

    if short_fade_setup and short_veto:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="volfade_short_veto_strong_uptrend",
            skill="none",
            confidence=0.0,
            tags=["trend_veto", "short"],
            indicators=indicators,
        )

    long_sl = low - atr_now * cfg.stop_atr_mult
    short_sl = high + atr_now * cfg.stop_atr_mult

    long_risk = max(price - long_sl, atr_now * 0.35)
    short_risk = max(short_sl - price, atr_now * 0.35)

    # Mean target = ema_fast or better RR
    long_mean_target = ema_fast
    short_mean_target = ema_fast

    long_tp = max(long_mean_target, price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr))
    short_tp = min(short_mean_target, price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr))

    long_scale_in = False
    short_scale_in = False
    long_water_add = False
    short_water_add = False

    if in_long and can_add_more and pos["avg_entry"] > 0:
        move_to_mean = max(long_mean_target - pos["avg_entry"], 1e-9)
        progress = (price - pos["avg_entry"]) / move_to_mean if move_to_mean > 0 else 0.0
        long_scale_in = progress >= cfg.progress_to_mean_min and reclaim_atr >= cfg.reclaim_atr_min
        long_water_add = long_fade_setup and body_atr >= cfg.water_add_extension_atr

    if in_short and can_add_more and pos["avg_entry"] > 0:
        move_to_mean = max(pos["avg_entry"] - short_mean_target, 1e-9)
        progress = (pos["avg_entry"] - price) / move_to_mean if move_to_mean > 0 else 0.0
        short_scale_in = progress >= cfg.progress_to_mean_min and reclaim_atr >= cfg.reclaim_atr_min
        short_water_add = short_fade_setup and body_atr >= cfg.water_add_extension_atr

    if long_fade_setup and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0)
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="vol_spike_fade_long",
            skill="long_beam" if long_beam else "fade_entry",
            confidence=0.77 if long_beam else 0.64,
            tags=["vol_spike", "fade", "long"],
            indicators=indicators,
        )

    if short_fade_setup and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0)
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="vol_spike_fade_short",
            skill="short_beam" if short_beam else "fade_entry",
            confidence=0.74 if short_beam else 0.60,
            tags=["vol_spike", "fade", "short"],
            indicators=indicators,
        )

    if long_scale_in:
        return _build_result(
            side="long",
            action="add",
            size=cfg.scale_in_size_long,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="volfade_long_scale_in",
            skill="scale_in",
            confidence=0.61,
            tags=["vol_spike", "fade", "scale_in", "long"],
            indicators=indicators,
        )

    if long_water_add:
        return _build_result(
            side="long",
            action="add",
            size=cfg.water_add_size_long,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="volfade_long_water_add",
            skill="water_add",
            confidence=0.54,
            tags=["vol_spike", "fade", "water_add", "long"],
            indicators=indicators,
        )

    if short_scale_in:
        return _build_result(
            side="short",
            action="add",
            size=cfg.scale_in_size_short,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="volfade_short_scale_in",
            skill="scale_in",
            confidence=0.58,
            tags=["vol_spike", "fade", "scale_in", "short"],
            indicators=indicators,
        )

    if short_water_add:
        return _build_result(
            side="short",
            action="add",
            size=cfg.water_add_size_short,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="volfade_short_water_add",
            skill="water_add",
            confidence=0.50,
            tags=["vol_spike", "fade", "water_add", "short"],
            indicators=indicators,
        )

    hold_reason = "volfade_no_setup"
    if spike_ok and not (long_fade_setup or short_fade_setup):
        hold_reason = "spike_detected_but_not_exhaustion_shape"
    elif in_long or in_short:
        hold_reason = "position_active_but_no_add_signal"

    return _build_result(
        side=None,
        action="hold",
        size=0.0,
        entry=price,
        sl=price,
        tp=price,
        pyramiding=cfg.max_pyramiding,
        why=hold_reason,
        skill="none",
        confidence=0.0,
        tags=["hold"],
        indicators=indicators,
    )


def _payload_to_df(payload: Dict[str, Any]) -> pd.DataFrame:
    candidates = [
        payload.get("ohlcv"),
        payload.get("candles"),
        payload.get("bars"),
        payload.get("df"),
    ]

    rows = None
    for candidate in candidates:
        if isinstance(candidate, list) and candidate:
            rows = candidate
            break

    if rows is None:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if "timestamp" in df.columns and "ts" not in df.columns:
        df["ts"] = df["timestamp"]
    return df


class VolSpikeFadeLBotStrategy(LBotStrategyBase):
    strategy_name = "vol_spike_fade"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        payload = dict(getattr(ctx.signal, "payload", {}) or {})
        df = _payload_to_df(payload)

        state = {
            "position_side": payload.get("position_side") or payload.get("current_side"),
            "position_qty": payload.get("position_qty") or payload.get("qty"),
            "avg_entry": payload.get("avg_entry") or payload.get("entry_price"),
            "add_count": payload.get("add_count") or 0,
            "last_add_price": payload.get("last_add_price") or payload.get("avg_entry"),
        }

        result = strategy(
            df,
            state=state,
            risk_action=str(getattr(ctx.risk, "action", "hold") or "hold"),
            config=VolSpikeFadeConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "volfade_no_reason")
        confidence = _to_float(result.get("confidence"))
        size = _to_float(result.get("size"))
        entry = _to_float(result.get("entry"))
        tags = list(result.get("tags") or [])

        if side == "long" and action in ("enter", "add"):
            return StrategyDecision(
                ok=True,
                intent=StrategyIntent.ENTER_LONG,
                confidence=confidence,
                reason=reason,
                target_qty=size,
                target_price=entry,
                tags=tags,
                payload={"legacy_signal": result},
            )

        if side == "short" and action in ("enter", "add"):
            return StrategyDecision(
                ok=True,
                intent=StrategyIntent.HOLD,
                confidence=0.0,
                reason="short_signal_generated_but_core_is_long_only",
                target_qty=0.0,
                target_price=entry,
                tags=tags + ["short_pending_core_upgrade"],
                payload={"legacy_signal": result},
            )

        return StrategyDecision(
            ok=True,
            intent=StrategyIntent.HOLD,
            confidence=0.0,
            reason=reason,
            target_qty=0.0,
            target_price=entry,
            tags=tags,
            payload={"legacy_signal": result},
        )
