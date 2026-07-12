from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "ema_ribbon_scalp"

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
class EmaRibbonScalpConfig:
    ema1_len: int = 8
    ema2_len: int = 21
    ema3_len: int = 55
    atr_len: int = 14
    min_bars: int = 90

    min_atr_pct: float = 0.12
    max_atr_pct: float = 4.80

    min_body_atr: float = 0.55
    beam_body_atr: float = 0.85
    reclaim_atr_min: float = 0.10
    max_chase_dist_atr: float = 1.10
    fail_ribbon_reject_atr: float = 0.18

    beam_close_location_min: float = 0.64
    pullback_to_ema2_atr: float = 0.40

    stop_atr_mult: float = 0.75
    trail_atr_mult: float = 0.48
    base_rr: float = 1.25
    beam_rr: float = 1.65

    long_base_size: float = 0.34
    short_base_size: float = 0.24
    beam_bonus_long: float = 0.10
    beam_bonus_short: float = 0.08

    add_size_long: float = 0.10
    add_size_short: float = 0.08
    reduce_size_long: float = 0.20
    reduce_size_short: float = 0.18

    max_add_count: int = 1
    max_pyramiding: int = 2


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
    config: Optional[EmaRibbonScalpConfig] = None,
) -> Dict[str, Any]:
    cfg = config or EmaRibbonScalpConfig()

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
            why="ribbon_empty",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    need = max(cfg.ema1_len, cfg.ema2_len, cfg.ema3_len) + 20
    if len(df) < max(need, cfg.min_bars):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="ribbon_short",
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

    close = df["close"]
    df["ema1"] = _ema(close, cfg.ema1_len)
    df["ema2"] = _ema(close, cfg.ema2_len)
    df["ema3"] = _ema(close, cfg.ema3_len)
    df["atr"] = _atr(df, cfg.atr_len)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    prev_close = _to_float(prev["close"])

    atr_now = _to_float(last["atr"])
    e1 = _to_float(last["ema1"])
    e2 = _to_float(last["ema2"])
    e3 = _to_float(last["ema3"])
    pe1 = _to_float(prev["ema1"])
    pe2 = _to_float(prev["ema2"])
    pe3 = _to_float(prev["ema3"])

    if min(price, atr_now, e1, e2, e3) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="ribbon_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    body = abs(price - open_)
    is_bull = price > open_
    is_bear = price < open_
    body_atr = body / max(atr_now, 1e-9)
    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    ribbon_long = e1 > e2 > e3 and e1 >= pe1 and e2 >= pe2 and e3 >= pe3
    ribbon_short = e1 < e2 < e3 and e1 <= pe1 and e2 <= pe2 and e3 <= pe3

    ribbon_spread = abs(e1 - e3) / max(atr_now, 1e-9)
    dist_from_e2_atr = abs(price - e2) / max(atr_now, 1e-9)

    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min

    long_setup = ribbon_long and is_bull and body_atr >= cfg.min_body_atr and long_reclaim
    short_setup = ribbon_short and is_bear and body_atr >= cfg.min_body_atr and short_reclaim

    long_beam = (
        long_setup
        and body_atr >= cfg.beam_body_atr
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup
        and body_atr >= cfg.beam_body_atr
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    pullback_long_add = ribbon_long and price >= e2 and dist_from_e2_atr <= cfg.pullback_to_ema2_atr
    pullback_short_add = ribbon_short and price <= e2 and dist_from_e2_atr <= cfg.pullback_to_ema2_atr

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_e2_atr > cfg.max_chase_dist_atr

    failed_long = price < e2 - atr_now * cfg.fail_ribbon_reject_atr
    failed_short = price > e2 + atr_now * cfg.fail_ribbon_reject_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema1": round(e1, 6),
        "ema2": round(e2, 6),
        "ema3": round(e3, 6),
        "ribbon_long": ribbon_long,
        "ribbon_short": ribbon_short,
        "ribbon_spread": round(ribbon_spread, 6),
        "body_atr": round(body_atr, 6),
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "dist_from_e2_atr": round(dist_from_e2_atr, 6),
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
            why="ribbon_volatility_out_of_range",
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
            why="ribbon_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(price - atr_now * cfg.stop_atr_mult, e2 - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(price + atr_now * cfg.stop_atr_mult, e2 + atr_now * cfg.trail_atr_mult, high)

    long_risk = max(price - long_sl, atr_now * 0.24)
    short_risk = max(short_sl - price, atr_now * 0.24)

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
            why="ribbon_long_beam" if long_beam else "ribbon_long_scalp",
            skill="long_beam" if long_beam else "ribbon_scalp",
            confidence=0.82 if long_beam else 0.68,
            tags=["ribbon", "scalp", "long"],
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
            why="ribbon_short_beam" if short_beam else "ribbon_short_scalp",
            skill="short_beam" if short_beam else "ribbon_scalp",
            confidence=0.78 if short_beam else 0.64,
            tags=["ribbon", "scalp", "short"],
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
            why="ribbon_long_pullback_add",
            skill="pullback_add",
            confidence=0.58,
            tags=["ribbon", "scalp", "add", "long"],
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
            why="ribbon_short_pullback_add",
            skill="pullback_add",
            confidence=0.54,
            tags=["ribbon", "scalp", "add", "short"],
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
            why="ribbon_failed_long_reduce",
            skill="failed_ribbon_reduce",
            confidence=0.66,
            tags=["ribbon", "failed", "reduce", "long"],
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
            why="ribbon_failed_short_reduce",
            skill="failed_ribbon_reduce",
            confidence=0.62,
            tags=["ribbon", "failed", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "ribbon_no_setup"
    if ribbon_long and not is_bull:
        hold_reason = "ribbon_long_without_bull_body"
    elif ribbon_short and not is_bear:
        hold_reason = "ribbon_short_without_bear_body"
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


class EmaRibbonScalpLBotStrategy(LBotStrategyBase):
    strategy_name = "ema_ribbon_scalp"

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
            config=EmaRibbonScalpConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "ribbon_no_reason")
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
