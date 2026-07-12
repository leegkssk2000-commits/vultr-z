from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pandas as pd

from backend.strategies.common_utils import atr, ema


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "anchor_vwap_trend"

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
class AnchorVwapTrendConfig:
    lookback: int = 120
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    atr_len: int = 14
    min_bars: int = 150

    min_atr_pct: float = 0.12
    max_atr_pct: float = 5.40

    beam_body_atr: float = 0.72
    beam_body_ratio_min: float = 0.36
    beam_close_location_min: float = 0.60

    reclaim_atr_min: float = 0.10
    max_chase_dist_atr: float = 1.55
    add_pullback_atr: float = 0.42
    fail_anchor_break_atr: float = 0.26

    stop_atr_mult: float = 0.92
    trail_atr_mult: float = 0.54
    base_rr: float = 2.20
    beam_rr: float = 2.80

    long_base_size: float = 0.54
    short_base_size: float = 0.38
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


def _anchor_from_swing(df: pd.DataFrame, lookback: int) -> Tuple[int, int]:
    recent = df.iloc[-lookback:]
    low_idx = int(recent["low"].idxmin())
    high_idx = int(recent["high"].idxmax())
    return low_idx, high_idx


def _vwap_from(df: pd.DataFrame, start_idx: int) -> pd.Series:
    part = df.loc[start_idx:].copy()
    tp = (part["high"] + part["low"] + part["close"]) / 3.0
    cum_vol = part["volume"].cumsum()
    cum_tp_vol = (tp * part["volume"]).cumsum()
    vwap = cum_tp_vol / (cum_vol + 1e-9)
    return vwap


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
    config: Optional[AnchorVwapTrendConfig] = None,
) -> Dict[str, Any]:
    cfg = config or AnchorVwapTrendConfig()

    required = {"open", "high", "low", "close", "volume"}
    if df is None or df.empty or not required.issubset(df.columns):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="avwap_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.lookback + 10, cfg.ema_slow_len + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="avwap_short",
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

    df["atr"] = atr(df, cfg.atr_len)
    df["ema_fast"] = ema(df["close"], cfg.ema_fast_len)
    df["ema_slow"] = ema(df["close"], cfg.ema_slow_len)

    low_idx, high_idx = _anchor_from_swing(df, cfg.lookback)
    vwap_long = _vwap_from(df, low_idx)
    vwap_short = _vwap_from(df, high_idx)

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
    avwap_long = _to_float(vwap_long.iloc[-1])
    avwap_short = _to_float(vwap_short.iloc[-1])

    if min(price, atr_now, ema_fast_now, ema_slow_now, avwap_long, avwap_short) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="avwap_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    trend_long = price > ema_fast_now > ema_slow_now and ema_fast_now >= ema_fast_prev and ema_slow_now >= ema_slow_prev
    trend_short = price < ema_fast_now < ema_slow_now and ema_fast_now <= ema_fast_prev and ema_slow_now <= ema_slow_prev

    body = abs(price - open_)
    body_atr = body / max(atr_now, 1e-9)
    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    bull_beam = price > open_ and body_atr >= cfg.beam_body_atr
    bear_beam = price < open_ and body_atr >= cfg.beam_body_atr

    dist_from_long_vwap_atr = abs(price - avwap_long) / max(atr_now, 1e-9)
    dist_from_short_vwap_atr = abs(price - avwap_short) / max(atr_now, 1e-9)

    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min

    long_setup = trend_long and price > avwap_long and bull_beam and long_reclaim
    short_setup = trend_short and price < avwap_short and bear_beam and short_reclaim

    long_beam = (
        long_setup
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = (
        (long_setup and dist_from_long_vwap_atr > cfg.max_chase_dist_atr)
        or (short_setup and dist_from_short_vwap_atr > cfg.max_chase_dist_atr)
    )

    failed_long = price < avwap_long - atr_now * cfg.fail_anchor_break_atr
    failed_short = price > avwap_short + atr_now * cfg.fail_anchor_break_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    pullback_long_add = trend_long and price >= avwap_long and dist_from_long_vwap_atr <= cfg.add_pullback_atr
    pullback_short_add = trend_short and price <= avwap_short and dist_from_short_vwap_atr <= cfg.add_pullback_atr

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema_fast": round(ema_fast_now, 6),
        "ema_slow": round(ema_slow_now, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "anchor_low_idx": int(low_idx),
        "anchor_high_idx": int(high_idx),
        "avwap_long": round(avwap_long, 6),
        "avwap_short": round(avwap_short, 6),
        "body_atr": round(body_atr, 6),
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "bull_beam": bull_beam,
        "bear_beam": bear_beam,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "dist_from_long_vwap_atr": round(dist_from_long_vwap_atr, 6),
        "dist_from_short_vwap_atr": round(dist_from_short_vwap_atr, 6),
        "pullback_long_add": pullback_long_add,
        "pullback_short_add": pullback_short_add,
        "late_chase_block": late_chase_block,
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
            why="avwap_volatility_out_of_range",
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
            why="avwap_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(low, avwap_long - atr_now * cfg.stop_atr_mult, ema_fast_now - atr_now * cfg.trail_atr_mult)
    short_sl = max(high, avwap_short + atr_now * cfg.stop_atr_mult, ema_fast_now + atr_now * cfg.trail_atr_mult)

    long_risk = max(price - long_sl, atr_now * 0.26)
    short_risk = max(short_sl - price, atr_now * 0.26)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_add = False
    short_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more:
        long_add = pullback_long_add and long_reclaim and not failed_long
        long_reduce = failed_long

    if in_short and can_add_more:
        short_add = pullback_short_add and short_reclaim and not failed_short
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
            why="avwap_long_beam" if long_beam else "avwap_long_trend",
            skill="long_beam" if long_beam else "anchor_vwap_trend",
            confidence=0.84 if long_beam else 0.70,
            tags=["anchor_vwap", "trend", "long"],
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
            why="avwap_short_beam" if short_beam else "avwap_short_trend",
            skill="short_beam" if short_beam else "anchor_vwap_trend",
            confidence=0.78 if short_beam else 0.64,
            tags=["anchor_vwap", "trend", "short"],
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
            why="avwap_long_pullback_add",
            skill="pullback_add",
            confidence=0.58,
            tags=["anchor_vwap", "trend", "add", "long"],
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
            why="avwap_short_pullback_add",
            skill="pullback_add",
            confidence=0.54,
            tags=["anchor_vwap", "trend", "add", "short"],
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
            why="avwap_failed_long_reduce",
            skill="failed_anchor_reduce",
            confidence=0.66,
            tags=["anchor_vwap", "trend", "failed", "reduce", "long"],
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
            why="avwap_failed_short_reduce",
            skill="failed_anchor_reduce",
            confidence=0.62,
            tags=["anchor_vwap", "trend", "failed", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "avwap_no_setup"
    if trend_long and price > avwap_long and not bull_beam:
        hold_reason = "above_long_avwap_without_bull_beam"
    elif trend_short and price < avwap_short and not bear_beam:
        hold_reason = "below_short_avwap_without_bear_beam"
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


class AnchorVwapTrendLBotStrategy(LBotStrategyBase):
    strategy_name = "anchor_vwap_trend"

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
            config=AnchorVwapTrendConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "avwap_no_reason")
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
