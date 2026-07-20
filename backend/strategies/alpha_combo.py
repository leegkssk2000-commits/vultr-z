from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

from backend.strategies.common_utils import atr, bollinger, ema, macd, rsi


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "alpha_combo"

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
class AlphaComboConfig:
    ema_fast_len: int = 21
    ema_mid_len: int = 55
    ema_slow_len: int = 100
    atr_len: int = 14
    rsi_len: int = 14
    bb_len: int = 20
    bb_mult: float = 2.0

    breakout_lookback: int = 20
    pullback_reclaim_atr: float = 0.10
    breakout_buffer_atr: float = 0.10
    max_chase_dist_atr: float = 1.75
    fail_reject_atr: float = 0.26

    min_atr_pct: float = 0.12
    max_atr_pct: float = 5.80

    beam_body_atr: float = 0.78
    beam_body_ratio_min: float = 0.38
    beam_close_location_min: float = 0.62

    stop_atr_mult: float = 0.95
    trail_atr_mult: float = 0.58
    base_rr: float = 2.10
    beam_rr: float = 2.80

    long_base_size: float = 0.56
    short_base_size: float = 0.38
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10

    add_size_long: float = 0.14
    add_size_short: float = 0.10
    reduce_size_long: float = 0.24
    reduce_size_short: float = 0.20

    max_add_count: int = 1
    max_pyramiding: int = 3
    min_bars: int = 160


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


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
    config: Optional[AlphaComboConfig] = None,
) -> Dict[str, Any]:
    cfg = config or AlphaComboConfig()

    required_cols = {"open", "high", "low", "close"}
    if df is None or df.empty or not required_cols.issubset(df.columns):
        return _build_result(
            side=None, action="hold", size=0.0, entry=0.0, sl=0.0, tp=0.0,
            pyramiding=cfg.max_pyramiding, why="alpha_invalid_input", skill="none",
            confidence=0.0, tags=["invalid_input"], indicators={}
        )

    need = max(cfg.min_bars, cfg.ema_slow_len + 10, cfg.breakout_lookback + 10)
    if len(df) < need:
        return _build_result(
            side=None, action="hold", size=0.0, entry=0.0, sl=0.0, tp=0.0,
            pyramiding=cfg.max_pyramiding, why="alpha_short", skill="none",
            confidence=0.0, tags=["warmup"], indicators={}
        )

    if str(risk_action or "hold").lower() in ("block", "stop", "rollback"):
        return _build_result(
            side=None, action="hold", size=0.0, entry=0.0, sl=0.0, tp=0.0,
            pyramiding=cfg.max_pyramiding, why=f"risk_gate_{risk_action}", skill="none",
            confidence=0.0, tags=["risk_gated"], indicators={}
        )

    df = df.copy()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    else:
        df["volume"] = df["volume"].astype(float)

    df["ema_fast"] = ema(df["close"], cfg.ema_fast_len)
    df["ema_mid"] = ema(df["close"], cfg.ema_mid_len)
    df["ema_slow"] = ema(df["close"], cfg.ema_slow_len)
    df["atr"] = atr(df, cfg.atr_len)
    df["rsi"] = rsi(df["close"], cfg.rsi_len)
    bb_mid, bb_upper, bb_lower = bollinger(df["close"], cfg.bb_len, cfg.bb_mult)
    df["bb_mid"] = bb_mid
    df["bb_upper"] = bb_upper
    df["bb_lower"] = bb_lower
    macd_line, macd_signal, macd_hist = macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    prev_close = _to_float(prev["close"])

    ema_fast_now = _to_float(last["ema_fast"])
    ema_mid_now = _to_float(last["ema_mid"])
    ema_slow_now = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_mid_prev = _to_float(prev["ema_mid"])
    ema_slow_prev = _to_float(prev["ema_slow"])

    atr_now = _to_float(last["atr"])
    rsi_now = _to_float(last["rsi"])
    bb_mid_now = _to_float(last["bb_mid"])
    bb_upper_now = _to_float(last["bb_upper"])
    bb_lower_now = _to_float(last["bb_lower"])
    macd_now = _to_float(last["macd"])
    macd_signal_now = _to_float(last["macd_signal"])
    macd_hist_now = _to_float(last["macd_hist"])
    macd_hist_prev = _to_float(prev["macd_hist"])

    if min(price, ema_fast_now, ema_mid_now, ema_slow_now, atr_now) <= 0:
        return _build_result(
            side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
            pyramiding=cfg.max_pyramiding, why="alpha_indicator_nan", skill="none",
            confidence=0.0, tags=["indicator_nan"], indicators={}
        )

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    body_atr = abs(price - open_) / max(atr_now, 1e-9)
    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    trend_long = (
        price > ema_fast_now > ema_mid_now > ema_slow_now
        and ema_fast_now >= ema_fast_prev
        and ema_mid_now >= ema_mid_prev
        and ema_slow_now >= ema_slow_prev
    )
    trend_short = (
        price < ema_fast_now < ema_mid_now < ema_slow_now
        and ema_fast_now <= ema_fast_prev
        and ema_mid_now <= ema_mid_prev
        and ema_slow_now <= ema_slow_prev
    )

    hh = _to_float(df["high"].iloc[-cfg.breakout_lookback:-1].max())
    ll = _to_float(df["low"].iloc[-cfg.breakout_lookback:-1].min())

    breakout_long = price > hh + atr_now * cfg.breakout_buffer_atr
    breakout_short = price < ll - atr_now * cfg.breakout_buffer_atr

    pullback_long = price >= ema_fast_now and price <= ema_mid_now + atr_now * 0.15
    pullback_short = price <= ema_fast_now and price >= ema_mid_now - atr_now * 0.15

    long_reclaim = price > prev_close + atr_now * cfg.pullback_reclaim_atr
    short_reclaim = price < prev_close - atr_now * cfg.pullback_reclaim_atr

    macd_long = macd_now >= macd_signal_now and macd_hist_now >= macd_hist_prev
    macd_short = macd_now <= macd_signal_now and macd_hist_now <= macd_hist_prev

    bb_bias_long = price >= bb_mid_now and price <= bb_upper_now + atr_now * 0.20
    bb_bias_short = price <= bb_mid_now and price >= bb_lower_now - atr_now * 0.20

    long_score = 0
    short_score = 0

    if trend_long:
        long_score += 2
    if breakout_long:
        long_score += 2
    if pullback_long:
        long_score += 1
    if macd_long:
        long_score += 1
    if rsi_now >= 52.0 and rsi_now <= 74.0:
        long_score += 1
    if bb_bias_long:
        long_score += 1

    if trend_short:
        short_score += 2
    if breakout_short:
        short_score += 2
    if pullback_short:
        short_score += 1
    if macd_short:
        short_score += 1
    if rsi_now <= 48.0 and rsi_now >= 26.0:
        short_score += 1
    if bb_bias_short:
        short_score += 1

    long_setup = long_score >= 5 and long_reclaim and not trend_short
    short_setup = short_score >= 5 and short_reclaim and not trend_long

    bull_beam = (
        long_setup
        and price > open_
        and body_atr >= cfg.beam_body_atr
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    bear_beam = (
        short_setup
        and price < open_
        and body_atr >= cfg.beam_body_atr
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    dist_from_fast_atr = abs(price - ema_fast_now) / max(atr_now, 1e-9)
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = (long_setup or short_setup) and dist_from_fast_atr > cfg.max_chase_dist_atr

    failed_long = price < ema_mid_now - atr_now * cfg.fail_reject_atr
    failed_short = price > ema_mid_now + atr_now * cfg.fail_reject_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    add_long = in_long and can_add_more and pullback_long and long_reclaim and not failed_long
    add_short = in_short and can_add_more and pullback_short and short_reclaim and not failed_short
    reduce_long = in_long and failed_long
    reduce_short = in_short and failed_short

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema_fast": round(ema_fast_now, 6),
        "ema_mid": round(ema_mid_now, 6),
        "ema_slow": round(ema_slow_now, 6),
        "rsi": round(rsi_now, 6),
        "bb_mid": round(bb_mid_now, 6),
        "bb_upper": round(bb_upper_now, 6),
        "bb_lower": round(bb_lower_now, 6),
        "macd": round(macd_now, 6),
        "macd_signal": round(macd_signal_now, 6),
        "macd_hist": round(macd_hist_now, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "breakout_high": round(hh, 6),
        "breakout_low": round(ll, 6),
        "breakout_long": breakout_long,
        "breakout_short": breakout_short,
        "pullback_long": pullback_long,
        "pullback_short": pullback_short,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "macd_long": macd_long,
        "macd_short": macd_short,
        "bb_bias_long": bb_bias_long,
        "bb_bias_short": bb_bias_short,
        "long_score": long_score,
        "short_score": short_score,
        "body_atr": round(body_atr, 6),
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
        "late_chase_block": late_chase_block,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "bull_beam": bull_beam,
        "bear_beam": bear_beam,
        "failed_long": failed_long,
        "failed_short": failed_short,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "avg_entry": pos["avg_entry"],
        "add_count": pos["add_count"],
    }

    if not vol_ok:
        return _build_result(
            side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
            pyramiding=cfg.max_pyramiding, why="alpha_volatility_out_of_range", skill="none",
            confidence=0.0, tags=["volatility_gate"], indicators=indicators
        )

    if late_chase_block:
        return _build_result(
            side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
            pyramiding=cfg.max_pyramiding, why="alpha_late_chase_block", skill="none",
            confidence=0.0, tags=["late_chase_block"], indicators=indicators
        )

    long_sl = min(low, ema_mid_now - atr_now * cfg.stop_atr_mult, ema_fast_now - atr_now * cfg.trail_atr_mult)
    short_sl = max(high, ema_mid_now + atr_now * cfg.stop_atr_mult, ema_fast_now + atr_now * cfg.trail_atr_mult)

    long_risk = max(price - long_sl, atr_now * 0.28)
    short_risk = max(short_sl - price, atr_now * 0.28)

    long_tp = price + long_risk * (cfg.beam_rr if bull_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if bear_beam else cfg.base_rr)

    if long_setup and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if bull_beam else 0.0)
        return _build_result(
            side="long", action="enter", size=size, entry=price, sl=long_sl, tp=long_tp,
            pyramiding=cfg.max_pyramiding, why=f"alpha_combo_long_s{long_score}",
            skill="long_beam" if bull_beam else "alpha_combo",
            confidence=0.86 if bull_beam else 0.72,
            tags=["alpha", "combo", "long"], indicators=indicators
        )

    if short_setup and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if bear_beam else 0.0)
        return _build_result(
            side="short", action="enter", size=size, entry=price, sl=short_sl, tp=short_tp,
            pyramiding=cfg.max_pyramiding, why=f"alpha_combo_short_s{short_score}",
            skill="short_beam" if bear_beam else "alpha_combo",
            confidence=0.80 if bear_beam else 0.66,
            tags=["alpha", "combo", "short"], indicators=indicators
        )

    if add_long:
        return _build_result(
            side="long", action="add", size=cfg.add_size_long, entry=price, sl=long_sl, tp=long_tp,
            pyramiding=cfg.max_pyramiding, why="alpha_long_pullback_add",
            skill="pullback_add", confidence=0.58,
            tags=["alpha", "combo", "add", "long"], indicators=indicators
        )

    if add_short:
        return _build_result(
            side="short", action="add", size=cfg.add_size_short, entry=price, sl=short_sl, tp=short_tp,
            pyramiding=cfg.max_pyramiding, why="alpha_short_pullback_add",
            skill="pullback_add", confidence=0.54,
            tags=["alpha", "combo", "add", "short"], indicators=indicators
        )

    if reduce_long:
        return _build_result(
            side="long", action="reduce", size=cfg.reduce_size_long, entry=price, sl=long_sl, tp=long_tp,
            pyramiding=cfg.max_pyramiding, why="alpha_failed_long_reduce",
            skill="failed_reduce", confidence=0.66,
            tags=["alpha", "combo", "failed", "reduce", "long"], indicators=indicators
        )

    if reduce_short:
        return _build_result(
            side="short", action="reduce", size=cfg.reduce_size_short, entry=price, sl=short_sl, tp=short_tp,
            pyramiding=cfg.max_pyramiding, why="alpha_failed_short_reduce",
            skill="failed_reduce", confidence=0.62,
            tags=["alpha", "combo", "failed", "reduce", "short"], indicators=indicators
        )

    hold_reason = "alpha_no_setup"
    if long_score >= 4 and not long_setup:
        hold_reason = "long_bias_but_not_enough_confirmation"
    elif short_score >= 4 and not short_setup:
        hold_reason = "short_bias_but_not_enough_confirmation"
    elif in_long or in_short:
        hold_reason = "position_active_but_no_add_signal"

    return _build_result(
        side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
        pyramiding=cfg.max_pyramiding, why=hold_reason, skill="none",
        confidence=0.0, tags=["hold"], indicators=indicators
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


class AlphaComboLBotStrategy(LBotStrategyBase):
    strategy_name = "alpha_combo"

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
            config=AlphaComboConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "alpha_no_reason")
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
