from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

from backend.strategies.common_utils import atr, ema


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "break_and_continue"

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
class BreakAndContinueConfig:
    breakout_bars: int = 4
    box_bars: int = 5

    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 100

    min_atr_pct: float = 0.14
    max_atr_pct: float = 5.50

    breakout_strength_atr_mult: float = 0.75
    box_max_height_atr_mult: float = 2.20
    breakout_buffer_atr: float = 0.08
    reclaim_atr_min: float = 0.12
    max_chase_dist_atr: float = 1.40
    fail_box_reject_atr: float = 0.22

    beam_body_ratio_min: float = 0.40
    beam_close_location_min: float = 0.62
    beam_breakout_strength_atr_mult: float = 1.05

    stop_atr_mult: float = 0.52
    trail_atr_mult: float = 0.36
    base_rr: float = 2.10
    beam_rr: float = 2.70

    long_base_size: float = 0.52
    short_base_size: float = 0.36
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10

    add_size_long: float = 0.14
    add_size_short: float = 0.10
    reduce_size_long: float = 0.24
    reduce_size_short: float = 0.20

    max_add_count: int = 1
    max_pyramiding: int = 3


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
    config: Optional[BreakAndContinueConfig] = None,
) -> Dict[str, Any]:
    cfg = config or BreakAndContinueConfig()

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
            why="bnc_empty",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    need = max(cfg.min_bars, cfg.breakout_bars + cfg.box_bars + 5, cfg.ema_slow_len + 5)
    if len(df) < need:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="bnc_short",
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

    df["atr"] = atr(df, cfg.atr_len)
    df["ema_fast"] = ema(df["close"], cfg.ema_fast_len)
    df["ema_slow"] = ema(df["close"], cfg.ema_slow_len)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    prev_close = _to_float(prev["close"])

    atr_now = _to_float(last["atr"])
    ema_fast_now = _to_float(last["ema_fast"])
    ema_slow_now = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_slow_prev = _to_float(prev["ema_slow"])

    if min(price, atr_now, ema_fast_now, ema_slow_now) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="bnc_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    b_start = -(cfg.breakout_bars + cfg.box_bars)
    b_end = -cfg.box_bars
    breakout = df.iloc[b_start:b_end]
    box = df.iloc[-cfg.box_bars:]

    breakout_move = _to_float(breakout["close"].iloc[-1]) - _to_float(breakout["close"].iloc[0])
    breakout_strength_atr = breakout_move / max(atr_now, 1e-9)

    up_break = breakout_strength_atr > cfg.breakout_bars * cfg.breakout_strength_atr_mult
    down_break = breakout_strength_atr < -cfg.breakout_bars * cfg.breakout_strength_atr_mult

    box_high = _to_float(box["high"].max())
    box_low = _to_float(box["low"].min())
    box_mid = (box_high + box_low) / 2.0
    box_height = box_high - box_low
    box_height_atr = box_height / max(atr_now, 1e-9)
    tight_box = box_height_atr <= cfg.box_max_height_atr_mult

    trend_long = price > ema_fast_now > ema_slow_now and ema_fast_now >= ema_fast_prev and ema_slow_now >= ema_slow_prev
    trend_short = price < ema_fast_now < ema_slow_now and ema_fast_now <= ema_fast_prev and ema_slow_now <= ema_slow_prev

    long_breakout_now = price > box_high + atr_now * cfg.breakout_buffer_atr
    short_breakout_now = price < box_low - atr_now * cfg.breakout_buffer_atr

    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min

    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)
    dist_from_fast_atr = abs(price - ema_fast_now) / max(atr_now, 1e-9)

    long_setup = up_break and tight_box and long_breakout_now and long_reclaim and trend_long
    short_setup = down_break and tight_box and short_breakout_now and short_reclaim and trend_short

    long_beam = (
        long_setup
        and breakout_strength_atr >= cfg.breakout_bars * cfg.beam_breakout_strength_atr_mult
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup
        and breakout_strength_atr <= -cfg.breakout_bars * cfg.beam_breakout_strength_atr_mult
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= (atr_now / max(price, 1e-9) * 100.0) <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr

    failed_long = price < box_low - atr_now * cfg.fail_box_reject_atr
    failed_short = price > box_high + atr_now * cfg.fail_box_reject_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_now / max(price, 1e-9) * 100.0, 6),
        "ema_fast": round(ema_fast_now, 6),
        "ema_slow": round(ema_slow_now, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "breakout_move": round(breakout_move, 6),
        "breakout_strength_atr": round(breakout_strength_atr, 6),
        "up_break": up_break,
        "down_break": down_break,
        "box_high": round(box_high, 6),
        "box_low": round(box_low, 6),
        "box_mid": round(box_mid, 6),
        "box_height": round(box_height, 6),
        "box_height_atr": round(box_height_atr, 6),
        "tight_box": tight_box,
        "long_breakout_now": long_breakout_now,
        "short_breakout_now": short_breakout_now,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
        "late_chase_block": late_chase_block,
        "long_setup": long_setup,
        "short_setup": short_setup,
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
            why="bnc_volatility_out_of_range",
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
            why="bnc_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(box_low - atr_now * cfg.stop_atr_mult, ema_fast_now - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(box_high + atr_now * cfg.stop_atr_mult, ema_fast_now + atr_now * cfg.trail_atr_mult, high)

    long_risk = max(price - long_sl, atr_now * 0.26)
    short_risk = max(short_sl - price, atr_now * 0.26)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_add = False
    short_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more:
        long_add = up_break and tight_box and price >= box_mid and long_reclaim and not failed_long
        long_reduce = failed_long

    if in_short and can_add_more:
        short_add = down_break and tight_box and price <= box_mid and short_reclaim and not failed_short
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
            why="bnc_long",
            skill="long_beam" if long_beam else "break_continue",
            confidence=0.84 if long_beam else 0.70,
            tags=["break", "continue", "long"],
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
            why="bnc_short",
            skill="short_beam" if short_beam else "break_continue",
            confidence=0.78 if short_beam else 0.64,
            tags=["break", "continue", "short"],
            indicators=indicators,
        )

    if long_add:
        return _build_result(
            side="long",
            action="add",
            size=cfg.add_size_long,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="bnc_long_add",
            skill="pullback_add",
            confidence=0.58,
            tags=["break", "continue", "add", "long"],
            indicators=indicators,
        )

    if short_add:
        return _build_result(
            side="short",
            action="add",
            size=cfg.add_size_short,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="bnc_short_add",
            skill="pullback_add",
            confidence=0.54,
            tags=["break", "continue", "add", "short"],
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
            why="bnc_failed_long_reduce",
            skill="failed_box_reduce",
            confidence=0.68,
            tags=["break", "continue", "failed", "reduce", "long"],
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
            why="bnc_failed_short_reduce",
            skill="failed_box_reduce",
            confidence=0.64,
            tags=["break", "continue", "failed", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "bnc_no_setup"
    if (up_break or down_break) and not tight_box:
        hold_reason = "breakout_ok_but_box_too_wide"
    elif up_break and not long_breakout_now:
        hold_reason = "up_break_without_box_breakout"
    elif down_break and not short_breakout_now:
        hold_reason = "down_break_without_box_breakout"
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


class BreakAndContinueLBotStrategy(LBotStrategyBase):
    strategy_name = "break_and_continue"

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
            config=BreakAndContinueConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "bnc_no_reason")
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
