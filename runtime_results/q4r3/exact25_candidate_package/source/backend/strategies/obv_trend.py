from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "obv_trend"

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
class ObvTrendConfig:
    obv_len: int = 34
    price_len: int = 34
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    atr_len: int = 14
    min_bars: int = 90

    min_atr_pct: float = 0.14
    max_atr_pct: float = 5.40

    min_obv_slope: float = 0.0
    obv_impulse_ratio: float = 1.12
    beam_obv_impulse_ratio: float = 1.32

    breakout_buffer_atr: float = 0.08
    reclaim_atr_min: float = 0.14
    max_chase_dist_atr: float = 1.65
    fail_cross_reject_atr: float = 0.24

    stop_atr_mult: float = 1.08
    trail_atr_mult: float = 0.72
    base_rr: float = 2.10
    beam_rr: float = 2.70

    long_base_size: float = 0.52
    short_base_size: float = 0.36
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10

    scale_in_size_long: float = 0.18
    scale_in_size_short: float = 0.14
    retest_add_size_long: float = 0.14
    retest_add_size_short: float = 0.10
    reduce_size_long: float = 0.25
    reduce_size_short: float = 0.20

    scale_in_progress_min: float = 0.34
    max_add_count: int = 2
    max_pyramiding: int = 3

    beam_body_ratio_min: float = 0.38
    beam_close_location_min: float = 0.60


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.astype(float).ewm(span=length, adjust=False, min_periods=length).mean()


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


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = df["close"].diff().fillna(0.0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * df["volume"].astype(float)).cumsum()


def _body_ratio(open_: float, close: float, low: float, high: float) -> float:
    width = max(high - low, 1e-9)
    return abs(close - open_) / width


def _close_location(close: float, low: float, high: float) -> float:
    width = max(high - low, 1e-9)
    return (close - low) / width


def _infer_position_state(state: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
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
    config: Optional[ObvTrendConfig] = None,
) -> Dict[str, Any]:
    cfg = config or ObvTrendConfig()

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
            why="obv_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.obv_len + 5, cfg.price_len + 5, cfg.ema_slow_len + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="obv_short",
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

    df["obv"] = _obv(df)
    df["obv_ma"] = _ema(df["obv"], cfg.obv_len)
    df["price_ma"] = _ema(df["close"], cfg.price_len)
    df["ema_fast"] = _ema(df["close"], cfg.ema_fast_len)
    df["ema_slow"] = _ema(df["close"], cfg.ema_slow_len)
    df["atr"] = _atr(df, cfg.atr_len)
    df["obv_delta"] = df["obv"].diff()
    df["obv_delta_ma"] = df["obv_delta"].abs().rolling(cfg.obv_len, min_periods=cfg.obv_len).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])

    atr_now = _to_float(last["atr"])
    obv_now = _to_float(last["obv"])
    obv_prev = _to_float(prev["obv"])
    obv_ma_now = _to_float(last["obv_ma"])
    obv_ma_prev = _to_float(prev["obv_ma"])
    obv_delta = _to_float(last["obv_delta"])
    obv_delta_ma = _to_float(last["obv_delta_ma"], 1.0)
    price_ma = _to_float(last["price_ma"])
    ema_fast = _to_float(last["ema_fast"])
    ema_slow = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_slow_prev = _to_float(prev["ema_slow"])
    prev_close = _to_float(prev["close"])

    if min(price, atr_now, price_ma, ema_fast, ema_slow) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="obv_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev

    obv_cross_up = obv_prev <= obv_ma_prev and obv_now > obv_ma_now
    obv_cross_down = obv_prev >= obv_ma_prev and obv_now < obv_ma_now

    obv_slope_up = (obv_now - obv_prev) > cfg.min_obv_slope
    obv_slope_down = (obv_now - obv_prev) < -cfg.min_obv_slope

    obv_impulse_ratio = abs(obv_delta) / max(obv_delta_ma, 1e-9)
    price_above_ma = price > price_ma + atr_now * cfg.breakout_buffer_atr
    price_below_ma = price < price_ma - atr_now * cfg.breakout_buffer_atr

    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min

    long_setup = obv_cross_up and obv_slope_up and price_above_ma and long_reclaim and trend_long
    short_setup = obv_cross_down and obv_slope_down and price_below_ma and short_reclaim and trend_short

    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)

    long_beam = (
        long_setup
        and obv_impulse_ratio >= cfg.beam_obv_impulse_ratio
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup
        and obv_impulse_ratio >= cfg.beam_obv_impulse_ratio
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr

    failed_long = prev_close > price_ma and price < price_ma - atr_now * cfg.fail_cross_reject_atr
    failed_short = prev_close < price_ma and price > price_ma + atr_now * cfg.fail_cross_reject_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "obv": round(obv_now, 6),
        "obv_prev": round(obv_prev, 6),
        "obv_ma": round(obv_ma_now, 6),
        "obv_delta": round(obv_delta, 6),
        "obv_delta_ma": round(obv_delta_ma, 6),
        "obv_impulse_ratio": round(obv_impulse_ratio, 6),
        "obv_cross_up": obv_cross_up,
        "obv_cross_down": obv_cross_down,
        "obv_slope_up": obv_slope_up,
        "obv_slope_down": obv_slope_down,
        "price_ma": round(price_ma, 6),
        "price_above_ma": price_above_ma,
        "price_below_ma": price_below_ma,
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
        "late_chase_block": late_chase_block,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "failed_long": failed_long,
        "failed_short": failed_short,
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
            why="obv_volatility_out_of_range",
            skill="none",
            confidence=0.0,
            tags=["volatility_gate"],
            indicators=indicators,
        )

    if late_chase_block and (long_setup or short_setup):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="obv_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    if obv_impulse_ratio < cfg.obv_impulse_ratio and (long_setup or short_setup):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="obv_impulse_too_weak",
            skill="none",
            confidence=0.0,
            tags=["weak_obv_impulse"],
            indicators=indicators,
        )

    long_sl = min(price - atr_now * cfg.stop_atr_mult, ema_fast - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(price + atr_now * cfg.stop_atr_mult, ema_fast + atr_now * cfg.trail_atr_mult, high)

    long_risk = max(price - long_sl, atr_now * 0.30)
    short_risk = max(short_sl - price, atr_now * 0.30)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_scale_in = False
    short_scale_in = False
    long_retest_add = False
    short_retest_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(long_tp - pos["avg_entry"], 1e-9)
        progress = (price - pos["avg_entry"]) / move_to_tp if move_to_tp > 0 else 0.0
        long_scale_in = progress >= cfg.scale_in_progress_min and obv_now > obv_ma_now and trend_long
        long_retest_add = price >= price_ma and obv_slope_up and not failed_long
        long_reduce = failed_long

    if in_short and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(pos["avg_entry"] - short_tp, 1e-9)
        progress = (pos["avg_entry"] - price) / move_to_tp if move_to_tp > 0 else 0.0
        short_scale_in = progress >= cfg.scale_in_progress_min and obv_now < obv_ma_now and trend_short
        short_retest_add = price <= price_ma and obv_slope_down and not failed_short
        short_reduce = failed_short

    if long_setup and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0)
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="obv_trend_long",
            skill="long_beam" if long_beam else "obv_cross_trend",
            confidence=0.84 if long_beam else 0.70,
            tags=["obv", "trend", "long"],
            indicators=indicators,
        )

    if short_setup and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0)
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="obv_trend_short",
            skill="short_beam" if short_beam else "obv_cross_trend",
            confidence=0.78 if short_beam else 0.64,
            tags=["obv", "trend", "short"],
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
            why="obv_long_scale_in",
            skill="scale_in",
            confidence=0.64,
            tags=["obv", "trend", "scale_in", "long"],
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
            why="obv_short_scale_in",
            skill="scale_in",
            confidence=0.58,
            tags=["obv", "trend", "scale_in", "short"],
            indicators=indicators,
        )

    if long_retest_add:
        return _build_result(
            side="long",
            action="add",
            size=cfg.retest_add_size_long,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="obv_long_retest_add",
            skill="retest_add",
            confidence=0.60,
            tags=["obv", "trend", "retest_add", "long"],
            indicators=indicators,
        )

    if short_retest_add:
        return _build_result(
            side="short",
            action="add",
            size=cfg.retest_add_size_short,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="obv_short_retest_add",
            skill="retest_add",
            confidence=0.56,
            tags=["obv", "trend", "retest_add", "short"],
            indicators=indicators,
        )

    if long_reduce:
        return _build_result(
            side="long",
            action="reduce",
            size=cfg.reduce_size_long,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="obv_failed_long_reduce",
            skill="failed_cross_reduce",
            confidence=0.68,
            tags=["obv", "trend", "failed", "reduce", "long"],
            indicators=indicators,
        )

    if short_reduce:
        return _build_result(
            side="short",
            action="reduce",
            size=cfg.reduce_size_short,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="obv_failed_short_reduce",
            skill="failed_cross_reduce",
            confidence=0.64,
            tags=["obv", "trend", "failed", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "obv_no_setup"
    if obv_cross_up and not price_above_ma:
        hold_reason = "obv_up_cross_without_price_confirm"
    elif obv_cross_down and not price_below_ma:
        hold_reason = "obv_down_cross_without_price_confirm"
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


class ObvTrendLBotStrategy(LBotStrategyBase):
    strategy_name = "obv_trend"

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
            config=ObvTrendConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "obv_no_reason")
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

        if side == "long" and action == "reduce":
            return StrategyDecision(
                ok=True,
                intent=StrategyIntent.REDUCE,
                confidence=confidence,
                reason=reason,
                target_qty=size,
                target_price=entry,
                tags=tags,
                payload={"legacy_signal": result},
            )

        if side == "short" and action in ("enter", "add", "reduce"):
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
