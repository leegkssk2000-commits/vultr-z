from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "rbreaker_like"

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
class RBreakerLikeConfig:
    lookback: int = 48
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 90

    min_atr_pct: float = 0.18
    max_atr_pct: float = 5.80

    breakout_mult: float = 0.30
    reversal_mult: float = 0.50
    breakout_buffer_atr: float = 0.12
    reversal_reclaim_atr: float = 0.16
    max_chase_dist_atr: float = 1.70
    failed_reversal_reject_atr: float = 0.22

    stop_atr_mult: float = 0.90
    trail_atr_mult: float = 0.60
    base_rr: float = 2.00
    beam_rr: float = 2.60

    long_base_size: float = 0.54
    short_base_size: float = 0.36
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10

    scale_in_size_long: float = 0.20
    scale_in_size_short: float = 0.14
    retest_add_size_long: float = 0.14
    retest_add_size_short: float = 0.10
    reduce_size_long: float = 0.25
    reduce_size_short: float = 0.20

    scale_in_progress_min: float = 0.34
    max_add_count: int = 1
    max_pyramiding: int = 2

    beam_body_ratio_min: float = 0.40
    beam_close_location_min: float = 0.62


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
    config: Optional[RBreakerLikeConfig] = None,
) -> Dict[str, Any]:
    cfg = config or RBreakerLikeConfig()

    required_cols = {"open", "high", "low", "close"}
    if df is None or df.empty or not required_cols.issubset(df.columns):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="rbr_empty",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.lookback + 5, cfg.ema_slow_len + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="rbr_short",
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
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)

    if "volume" not in df.columns:
        df["volume"] = 0.0
    else:
        df["volume"] = df["volume"].astype(float)

    df["atr"] = _atr(df, cfg.atr_len)
    df["ema_fast"] = _ema(df["close"], cfg.ema_fast_len)
    df["ema_slow"] = _ema(df["close"], cfg.ema_slow_len)

    recent = df.iloc[-(cfg.lookback + 1):-1]
    last = df.iloc[-1]
    prev = df.iloc[-2]

    hi = _to_float(recent["high"].max())
    lo = _to_float(recent["low"].min())
    cl = _to_float(recent["close"].iloc[-1])
    rng = hi - lo

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    prev_close = _to_float(prev["close"])
    prev_high = _to_float(prev["high"])
    prev_low = _to_float(prev["low"])

    atr_now = _to_float(last["atr"])
    ema_fast = _to_float(last["ema_fast"])
    ema_slow = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_slow_prev = _to_float(prev["ema_slow"])

    if min(price, atr_now, ema_fast, ema_slow) <= 0 or rng <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="rbr_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    mid = (hi + lo + cl) / 3.0
    breakout_buy = hi + rng * cfg.breakout_mult
    breakout_sell = lo - rng * cfg.breakout_mult
    rev_sell = mid + rng * cfg.reversal_mult
    rev_buy = mid - rng * cfg.reversal_mult

    atr_pct = (atr_now / max(price, 1e-9)) * 100.0
    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev

    long_break = price > breakout_buy + atr_now * cfg.breakout_buffer_atr and prev_close <= breakout_buy
    short_break = price < breakout_sell - atr_now * cfg.breakout_buffer_atr and prev_close >= breakout_sell

    short_reversal = prev_high >= rev_sell and price < mid - atr_now * cfg.reversal_reclaim_atr
    long_reversal = prev_low <= rev_buy and price > mid + atr_now * cfg.reversal_reclaim_atr

    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)
    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    long_break_beam = (
        long_break
        and trend_long
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_break_beam = (
        short_break
        and trend_short
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )
    long_rev_beam = (
        long_reversal
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_rev_beam = (
        short_reversal
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr

    failed_long_reversal = prev_close > mid and price < mid - atr_now * cfg.failed_reversal_reject_atr
    failed_short_reversal = prev_close < mid and price > mid + atr_now * cfg.failed_reversal_reject_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "range_high": round(hi, 6),
        "range_low": round(lo, 6),
        "range_close": round(cl, 6),
        "mid": round(mid, 6),
        "breakout_buy": round(breakout_buy, 6),
        "breakout_sell": round(breakout_sell, 6),
        "rev_sell": round(rev_sell, 6),
        "rev_buy": round(rev_buy, 6),
        "long_break": long_break,
        "short_break": short_break,
        "long_reversal": long_reversal,
        "short_reversal": short_reversal,
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
        "late_chase_block": late_chase_block,
        "failed_long_reversal": failed_long_reversal,
        "failed_short_reversal": failed_short_reversal,
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "long_break_beam": long_break_beam,
        "short_break_beam": short_break_beam,
        "long_rev_beam": long_rev_beam,
        "short_rev_beam": short_rev_beam,
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
            why="rbr_volatility_out_of_range",
            skill="none",
            confidence=0.0,
            tags=["volatility_gate"],
            indicators=indicators,
        )

    if late_chase_block and (long_break or short_break or long_reversal or short_reversal):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="rbr_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_break_sl = min(breakout_buy - atr_now * cfg.stop_atr_mult, ema_fast - atr_now * cfg.trail_atr_mult, low)
    short_break_sl = max(breakout_sell + atr_now * cfg.stop_atr_mult, ema_fast + atr_now * cfg.trail_atr_mult, high)
    long_rev_sl = min(lo - atr_now * 0.5, ema_fast - atr_now * cfg.trail_atr_mult, low)
    short_rev_sl = max(hi + atr_now * 0.5, ema_fast + atr_now * cfg.trail_atr_mult, high)

    long_break_risk = max(price - long_break_sl, atr_now * 0.35)
    short_break_risk = max(short_break_sl - price, atr_now * 0.35)
    long_rev_risk = max(price - long_rev_sl, atr_now * 0.35)
    short_rev_risk = max(short_rev_sl - price, atr_now * 0.35)

    long_break_tp = price + long_break_risk * (cfg.beam_rr if long_break_beam else cfg.base_rr)
    short_break_tp = price - short_break_risk * (cfg.beam_rr if short_break_beam else cfg.base_rr)
    long_rev_tp = price + long_rev_risk * (cfg.beam_rr if long_rev_beam else cfg.base_rr)
    short_rev_tp = price - short_rev_risk * (cfg.beam_rr if short_rev_beam else cfg.base_rr)

    long_scale_in = False
    short_scale_in = False
    long_retest_add = False
    short_retest_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more:
        long_scale_in = price > breakout_buy and trend_long
        long_retest_add = price > mid and price >= ema_fast and (long_reversal or prev_close <= mid <= price)
        long_reduce = failed_long_reversal

    if in_short and can_add_more:
        short_scale_in = price < breakout_sell and trend_short
        short_retest_add = price < mid and price <= ema_fast and (short_reversal or prev_close >= mid >= price)
        short_reduce = failed_short_reversal

    if long_break and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_break_beam else 0.0)
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_break_sl,
            tp=long_break_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_breakout_long",
            skill="long_beam" if long_break_beam else "breakout_entry",
            confidence=0.84 if long_break_beam else 0.72,
            tags=["rbreaker", "breakout", "long"],
            indicators=indicators,
        )

    if short_break and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_break_beam else 0.0)
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_break_sl,
            tp=short_break_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_breakout_short",
            skill="short_beam" if short_break_beam else "breakout_entry",
            confidence=0.78 if short_break_beam else 0.66,
            tags=["rbreaker", "breakout", "short"],
            indicators=indicators,
        )

    if long_reversal and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_rev_beam else 0.0)
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_rev_sl,
            tp=long_rev_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_reversal_long",
            skill="long_beam" if long_rev_beam else "reversal_entry",
            confidence=0.80 if long_rev_beam else 0.68,
            tags=["rbreaker", "reversal", "long"],
            indicators=indicators,
        )

    if short_reversal and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_rev_beam else 0.0)
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_rev_sl,
            tp=short_rev_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_reversal_short",
            skill="short_beam" if short_rev_beam else "reversal_entry",
            confidence=0.76 if short_rev_beam else 0.64,
            tags=["rbreaker", "reversal", "short"],
            indicators=indicators,
        )

    if long_scale_in:
        return _build_result(
            side="long",
            action="add",
            size=cfg.scale_in_size_long,
            entry=price,
            sl=long_break_sl,
            tp=long_break_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_long_scale_in",
            skill="scale_in",
            confidence=0.64,
            tags=["rbreaker", "scale_in", "long"],
            indicators=indicators,
        )

    if short_scale_in:
        return _build_result(
            side="short",
            action="add",
            size=cfg.scale_in_size_short,
            entry=price,
            sl=short_break_sl,
            tp=short_break_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_short_scale_in",
            skill="scale_in",
            confidence=0.58,
            tags=["rbreaker", "scale_in", "short"],
            indicators=indicators,
        )

    if long_retest_add:
        return _build_result(
            side="long",
            action="add",
            size=cfg.retest_add_size_long,
            entry=price,
            sl=long_rev_sl,
            tp=long_rev_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_long_retest_add",
            skill="retest_add",
            confidence=0.60,
            tags=["rbreaker", "retest_add", "long"],
            indicators=indicators,
        )

    if short_retest_add:
        return _build_result(
            side="short",
            action="add",
            size=cfg.retest_add_size_short,
            entry=price,
            sl=short_rev_sl,
            tp=short_rev_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_short_retest_add",
            skill="retest_add",
            confidence=0.56,
            tags=["rbreaker", "retest_add", "short"],
            indicators=indicators,
        )

    if long_reduce:
        return _build_result(
            side="long",
            action="reduce",
            size=cfg.reduce_size_long,
            entry=price,
            sl=long_rev_sl,
            tp=long_rev_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_failed_long_reversal_reduce",
            skill="failed_reversal_reduce",
            confidence=0.68,
            tags=["rbreaker", "failed_reversal", "reduce", "long"],
            indicators=indicators,
        )

    if short_reduce:
        return _build_result(
            side="short",
            action="reduce",
            size=cfg.reduce_size_short,
            entry=price,
            sl=short_rev_sl,
            tp=short_rev_tp,
            pyramiding=cfg.max_pyramiding,
            why="rbr_failed_short_reversal_reduce",
            skill="failed_reversal_reduce",
            confidence=0.64,
            tags=["rbreaker", "failed_reversal", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "rbr_no_setup"
    if price > breakout_buy and not long_break:
        hold_reason = "above_breakout_buy_without_trigger"
    elif price < breakout_sell and not short_break:
        hold_reason = "below_breakout_sell_without_trigger"
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


class RBreakerLikeLBotStrategy(LBotStrategyBase):
    strategy_name = "rbreaker_like"

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
            config=RBreakerLikeConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "rbr_no_reason")
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
