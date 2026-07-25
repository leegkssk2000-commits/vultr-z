from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from backend.strategies.semantic_common import (
    DecisionContext,
    LBotStrategyBase,
    StrategyDecision,
    atr,
    body_ratio,
    build_result,
    close_location,
    decision_from_context,
    ema,
    infer_position_state,
    invalid_result,
    prepare_ohlcv,
    to_float,
)


@dataclass
class SessionBiasConfig:
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    range_lookback: int = 24
    min_bars: int = 90
    min_atr_pct: float = 0.18
    max_atr_pct: float = 5.50
    breakout_buffer_atr: float = 0.10
    reclaim_atr_min: float = 0.16
    max_chase_dist_atr: float = 1.70
    fail_break_reject_atr: float = 0.22
    stop_atr_mult: float = 1.15
    trail_atr_mult: float = 0.85
    base_rr: float = 1.90
    beam_rr: float = 2.50
    long_base_size: float = 0.46
    short_base_size: float = 0.30
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10
    scale_in_size_long: float = 0.20
    scale_in_size_short: float = 0.14
    retest_add_size_long: float = 0.14
    retest_add_size_short: float = 0.10
    reduce_size_long: float = 0.25
    reduce_size_short: float = 0.20
    scale_in_progress_min: float = 0.34
    max_add_count: int = 2
    max_pyramiding: int = 2
    beam_body_ratio_min: float = 0.38
    beam_close_location_min: float = 0.60
    asia_start_hour: int = 0
    asia_end_hour: int = 8
    london_start_hour: int = 8
    london_end_hour: int = 16
    ny_start_hour: int = 13
    ny_end_hour: int = 21
    default_tz: str = "UTC"
    require_timestamp: bool = True


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        stamp = value
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        return stamp.to_pydatetime()
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    try:
        numeric = float(value)
        if numeric > 1e12:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except Exception:
        pass
    try:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        return stamp.to_pydatetime()
    except Exception:
        return None


def _extract_datetime(row: pd.Series, index_value: Any) -> Optional[datetime]:
    for key in ("ts", "timestamp", "time", "open_time", "close_time", "timestamp_ms"):
        if key in row.index:
            parsed = _coerce_datetime(row.get(key))
            if parsed is not None:
                return parsed
    return _coerce_datetime(index_value)


def _in_window(hour: int, start: int, end: int) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _session_name(dt_value: Optional[datetime], tz_name: str, cfg: SessionBiasConfig) -> str:
    if dt_value is None:
        return "unknown"
    try:
        dt_utc = dt_value.astimezone(timezone.utc)
        dt_local = dt_utc.astimezone(ZoneInfo(tz_name)) if ZoneInfo is not None else dt_utc
    except Exception:
        return "unknown"
    hour = dt_local.hour
    asia = _in_window(hour, cfg.asia_start_hour, cfg.asia_end_hour)
    london = _in_window(hour, cfg.london_start_hour, cfg.london_end_hour)
    newyork = _in_window(hour, cfg.ny_start_hour, cfg.ny_end_hour)
    if london and newyork:
        return "london_newyork_overlap"
    if asia:
        return "asia"
    if london:
        return "london"
    if newyork:
        return "newyork"
    return "off_session"


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[SessionBiasConfig] = None,
    session_tz: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = config or SessionBiasConfig()
    frame = prepare_ohlcv(df)
    if frame is None:
        return invalid_result("session_bias_invalid_input", cfg.max_pyramiding)
    if len(frame) < max(cfg.min_bars, cfg.range_lookback + 2, cfg.ema_slow_len + 5):
        return invalid_result("session_bias_not_enough_bars", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["atr"] = atr(frame, cfg.atr_len)
    frame["ema_fast"] = ema(frame["close"], cfg.ema_fast_len)
    frame["ema_slow"] = ema(frame["close"], cfg.ema_slow_len)
    last, prev = frame.iloc[-1], frame.iloc[-2]
    # The current signal candle must not define the level it is required to break.
    prior_range = frame.iloc[-(cfg.range_lookback + 1):-1]

    price = to_float(last["close"])
    open_ = to_float(last["open"])
    high = to_float(last["high"])
    low = to_float(last["low"])
    prev_close = to_float(prev["close"])
    atr_now = to_float(last["atr"])
    ema_fast = to_float(last["ema_fast"])
    ema_slow = to_float(last["ema_slow"])
    ema_fast_prev = to_float(prev["ema_fast"])
    ema_slow_prev = to_float(prev["ema_slow"])
    session_high = to_float(prior_range["high"].max())
    session_low = to_float(prior_range["low"].min())
    session_mid = (session_high + session_low) / 2.0
    if min(price, atr_now, ema_fast, ema_slow, session_high, session_low) <= 0:
        return invalid_result("session_bias_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    tz_name = session_tz or cfg.default_tz
    current_dt = _extract_datetime(last, frame.index[-1])
    session_name = _session_name(current_dt, tz_name, cfg)
    if cfg.require_timestamp and session_name in {"unknown", "off_session"}:
        return build_result(
            side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
            pyramiding=cfg.max_pyramiding, why="session_bias_timestamp_or_session_unavailable",
            skill="none", confidence=0.0, tags=["session_gate"],
            indicators={
                "session_name": session_name,
                "session_tz": tz_name,
                "prior_range_excludes_signal_bar": True,
            },
        )

    trend_long = price > ema_fast > ema_slow and ema_fast > ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast < ema_fast_prev and ema_slow <= ema_slow_prev
    long_break = price > session_high + atr_now * cfg.breakout_buffer_atr
    short_break = price < session_low - atr_now * cfg.breakout_buffer_atr
    long_reclaim = prev_close <= session_high and price > session_high + atr_now * cfg.reclaim_atr_min
    short_reclaim = prev_close >= session_low and price < session_low - atr_now * cfg.reclaim_atr_min

    if session_name == "asia":
        bias_long = trend_long and price >= session_mid
        bias_short = trend_short and price <= session_mid
        bias_strength = 0.52
    elif session_name == "london":
        bias_long, bias_short, bias_strength = trend_long, trend_short, 0.70
    elif session_name == "newyork":
        bias_long, bias_short, bias_strength = trend_long and long_break, trend_short and short_break, 0.76
    elif session_name == "london_newyork_overlap":
        bias_long = trend_long and long_reclaim
        bias_short = trend_short and short_reclaim
        bias_strength = 0.82
    else:
        bias_long = bias_short = False
        bias_strength = 0.0

    candle_body_ratio = body_ratio(open_, price, low, high)
    close_loc = close_location(price, low, high)
    long_setup = bias_long and long_break
    short_setup = bias_short and short_break
    long_beam = long_setup and candle_body_ratio >= cfg.beam_body_ratio_min and close_loc >= cfg.beam_close_location_min
    short_beam = short_setup and candle_body_ratio >= cfg.beam_body_ratio_min and (1.0 - close_loc) >= cfg.beam_close_location_min
    atr_pct = atr_now / max(price, 1e-9) * 100.0
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr
    failed_long = prev_close > session_high and price < session_high - atr_now * cfg.fail_break_reject_atr
    failed_short = prev_close < session_low and price > session_low + atr_now * cfg.fail_break_reject_atr
    pos = infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "session_name": session_name,
        "session_tz": tz_name,
        "session_high_prior": round(session_high, 6),
        "session_low_prior": round(session_low, 6),
        "session_mid_prior": round(session_mid, 6),
        "prior_range_excludes_signal_bar": True,
        "overlap_classified_before_single_session": True,
        "trend_long": trend_long,
        "trend_short": trend_short,
        "bias_long": bias_long,
        "bias_short": bias_short,
        "bias_strength": round(bias_strength, 6),
        "long_break": long_break,
        "short_break": short_break,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "late_chase_block": late_chase_block,
        "failed_long": failed_long,
        "failed_short": failed_short,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "add_count": pos["add_count"],
    }
    if not vol_ok:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="session_bias_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)
    if late_chase_block and (long_setup or short_setup):
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="session_bias_late_chase_block",
                            skill="none", confidence=0.0, tags=["late_chase_block"], indicators=indicators)

    long_sl = min(session_high - atr_now * cfg.stop_atr_mult, ema_fast - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(session_low + atr_now * cfg.stop_atr_mult, ema_fast + atr_now * cfg.trail_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.40)
    short_risk = max(short_sl - price, atr_now * 0.40)
    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    if in_long and failed_long:
        return build_result(side="long", action="reduce", size=cfg.reduce_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="session_bias_failed_long_reduce", skill="failed_break_reduce", confidence=0.70,
                            tags=["session", "reduce", "long"], indicators=indicators)
    if in_short and failed_short:
        return build_result(side="short", action="reduce", size=cfg.reduce_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="session_bias_failed_short_reduce", skill="failed_break_reduce", confidence=0.66,
                            tags=["session", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and bias_long and low <= session_high and price > session_high:
        return build_result(side="long", action="add", size=cfg.retest_add_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="session_bias_long_retest_add", skill="retest_add", confidence=0.62,
                            tags=["session", "add", "long"], indicators=indicators)
    if in_short and can_add_more and bias_short and high >= session_low and price < session_low:
        return build_result(side="short", action="add", size=cfg.retest_add_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="session_bias_short_retest_add", skill="retest_add", confidence=0.58,
                            tags=["session", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        confidence = min(0.86 if long_beam else 0.70, 0.52 + bias_strength * 0.40)
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="session_bias_long", skill="long_beam" if long_beam else "session_breakout",
                            confidence=confidence, tags=["session", session_name, "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        confidence = min(0.82 if short_beam else 0.66, 0.48 + bias_strength * 0.38)
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="session_bias_short", skill="short_beam" if short_beam else "session_breakout",
                            confidence=confidence, tags=["session", session_name, "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="session_bias_no_setup", skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class SessionBiasLBotStrategy(LBotStrategyBase):
    strategy_name = "session_bias"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, SessionBiasConfig(), self.strategy_name)


__all__ = ["SessionBiasConfig", "SessionBiasLBotStrategy", "strategy"]
