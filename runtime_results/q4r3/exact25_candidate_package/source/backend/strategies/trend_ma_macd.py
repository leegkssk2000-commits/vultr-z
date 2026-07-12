from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "trend_ma_macd"

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
class TrendMaMacdConfig:
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    macd_fast_len: int = 12
    macd_slow_len: int = 26
    macd_signal_len: int = 9
    atr_len: int = 14
    min_bars: int = 90

    min_atr_pct: float = 0.25
    max_atr_pct: float = 5.50

    max_chase_dist_atr: float = 1.60
    min_hist_impulse: float = 0.03
    beam_hist_impulse: float = 0.08
    beam_body_ratio_min: float = 0.45
    beam_close_location_min: float = 0.62

    stop_atr_mult: float = 1.60
    trail_atr_mult: float = 1.00
    base_rr: float = 2.00
    beam_rr: float = 2.60

    long_base_size: float = 0.50
    short_base_size: float = 0.35
    beam_bonus_long: float = 0.18
    beam_bonus_short: float = 0.12

    scale_in_size_long: float = 0.28
    scale_in_size_short: float = 0.18
    dip_add_size_long: float = 0.18
    dip_add_size_short: float = 0.12

    scale_in_progress_min: float = 0.35
    dip_add_reclaim_atr: float = 0.25
    max_adverse_atr_for_dip: float = 1.10

    max_add_count: int = 2
    max_pyramiding: int = 3


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


def _macd_hist(series: pd.Series, fast_len: int, slow_len: int, signal_len: int) -> pd.DataFrame:
    ema_fast = _ema(series, fast_len)
    ema_slow = _ema(series, slow_len)
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=signal_len, adjust=False, min_periods=signal_len).mean()
    hist = macd - signal
    return pd.DataFrame(
        {
            "macd": macd,
            "macd_signal": signal,
            "macd_hist": hist,
        }
    )


def _close_location(close: float, low: float, high: float) -> float:
    width = max(high - low, 1e-9)
    return (close - low) / width


def _body_ratio(open_: float, close: float, low: float, high: float) -> float:
    width = max(high - low, 1e-9)
    return abs(close - open_) / width


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
    config: Optional[TrendMaMacdConfig] = None,
) -> Dict[str, Any]:
    cfg = config or TrendMaMacdConfig()

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
            why="trend_ma_macd_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < cfg.min_bars:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="trend_ma_macd_not_enough_bars",
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

    df["ema_fast"] = _ema(df["close"], cfg.ema_fast_len)
    df["ema_slow"] = _ema(df["close"], cfg.ema_slow_len)
    df["atr"] = _atr(df, cfg.atr_len)

    macd_df = _macd_hist(df["close"], cfg.macd_fast_len, cfg.macd_slow_len, cfg.macd_signal_len)
    df["macd"] = macd_df["macd"]
    df["macd_signal"] = macd_df["macd_signal"]
    df["macd_hist"] = macd_df["macd_hist"]

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    atr_now = _to_float(last["atr"])
    ema_fast = _to_float(last["ema_fast"])
    ema_slow = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_slow_prev = _to_float(prev["ema_slow"])
    macd_hist_now = _to_float(last["macd_hist"])
    macd_hist_prev = _to_float(prev["macd_hist"])

    if min(price, atr_now, ema_fast, ema_slow) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="trend_ma_macd_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    atr_pct = (atr_now / max(price, 1e-9)) * 100.0
    ema_spread_atr = abs(ema_fast - ema_slow) / max(atr_now, 1e-9)
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)

    trend_long = price > ema_fast > ema_slow and ema_fast > ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast < ema_fast_prev and ema_slow <= ema_slow_prev

    hist_cross_up = macd_hist_prev <= 0 and macd_hist_now > 0
    hist_cross_down = macd_hist_prev >= 0 and macd_hist_now < 0
    hist_impulse = abs(macd_hist_now - macd_hist_prev)

    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    long_beam = (
        trend_long
        and hist_cross_up
        and hist_impulse >= cfg.beam_hist_impulse
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )

    short_beam = (
        trend_short
        and hist_cross_down
        and hist_impulse >= cfg.beam_hist_impulse
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr
    weak_cross = hist_impulse < cfg.min_hist_impulse

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
        "ema_spread_atr": round(ema_spread_atr, 6),
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "macd_hist": round(macd_hist_now, 6),
        "macd_hist_prev": round(macd_hist_prev, 6),
        "hist_cross_up": hist_cross_up,
        "hist_cross_down": hist_cross_down,
        "hist_impulse": round(hist_impulse, 6),
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "long_beam": long_beam,
        "short_beam": short_beam,
        "late_chase_block": late_chase_block,
        "weak_cross": weak_cross,
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
            why="trend_ma_macd_volatility_out_of_range",
            skill="none",
            confidence=0.0,
            tags=["volatility_gate"],
            indicators=indicators,
        )

    if weak_cross:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="trend_ma_macd_weak_hist_cross",
            skill="none",
            confidence=0.0,
            tags=["weak_cross"],
            indicators=indicators,
        )

    if late_chase_block and (hist_cross_up or hist_cross_down):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="trend_ma_macd_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(low, ema_fast - atr_now * cfg.trail_atr_mult, price - atr_now * cfg.stop_atr_mult)
    short_sl = max(high, ema_fast + atr_now * cfg.trail_atr_mult, price + atr_now * cfg.stop_atr_mult)

    long_risk = max(price - long_sl, atr_now * 0.40)
    short_risk = max(short_sl - price, atr_now * 0.40)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_scale_in = False
    short_scale_in = False
    long_dip_add = False
    short_dip_add = False

    if in_long and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(long_tp - pos["avg_entry"], 1e-9)
        progress = (price - pos["avg_entry"]) / move_to_tp if move_to_tp > 0 else 0.0
        long_scale_in = progress >= cfg.scale_in_progress_min and macd_hist_now > 0 and trend_long
        long_dip_add = (
            low <= ema_fast
            and price >= ema_fast + atr_now * cfg.dip_add_reclaim_atr
            and price >= pos["avg_entry"] - atr_now * cfg.max_adverse_atr_for_dip
            and macd_hist_now > macd_hist_prev
        )

    if in_short and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(pos["avg_entry"] - short_tp, 1e-9)
        progress = (pos["avg_entry"] - price) / move_to_tp if move_to_tp > 0 else 0.0
        short_scale_in = progress >= cfg.scale_in_progress_min and macd_hist_now < 0 and trend_short
        short_dip_add = (
            high >= ema_fast
            and price <= ema_fast - atr_now * cfg.dip_add_reclaim_atr
            and price <= pos["avg_entry"] + atr_now * cfg.max_adverse_atr_for_dip
            and macd_hist_now < macd_hist_prev
        )

    if trend_long and hist_cross_up and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0)
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="trend_ma_macd_long_entry",
            skill="long_beam" if long_beam else "trend_entry",
            confidence=0.84 if long_beam else 0.70,
            tags=["trend", "ema", "macd", "long"],
            indicators=indicators,
        )

    if trend_short and hist_cross_down and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0)
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="trend_ma_macd_short_entry",
            skill="short_beam" if short_beam else "trend_entry",
            confidence=0.80 if short_beam else 0.66,
            tags=["trend", "ema", "macd", "short"],
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
            why="trend_ma_macd_long_scale_in",
            skill="scale_in",
            confidence=0.68,
            tags=["trend", "ema", "macd", "scale_in", "long"],
            indicators=indicators,
        )

    if long_dip_add:
        return _build_result(
            side="long",
            action="add",
            size=cfg.dip_add_size_long,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="trend_ma_macd_long_dip_add",
            skill="dip_add",
            confidence=0.64,
            tags=["trend", "ema", "macd", "dip_add", "long"],
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
            why="trend_ma_macd_short_scale_in",
            skill="scale_in",
            confidence=0.64,
            tags=["trend", "ema", "macd", "scale_in", "short"],
            indicators=indicators,
        )

    if short_dip_add:
        return _build_result(
            side="short",
            action="add",
            size=cfg.dip_add_size_short,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="trend_ma_macd_short_dip_add",
            skill="dip_add",
            confidence=0.60,
            tags=["trend", "ema", "macd", "dip_add", "short"],
            indicators=indicators,
        )

    hold_reason = "trend_ma_macd_no_setup"
    if hist_cross_up and not trend_long:
        hold_reason = "hist_cross_up_but_trend_filter_failed"
    elif hist_cross_down and not trend_short:
        hold_reason = "hist_cross_down_but_trend_filter_failed"
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


class TrendMaMacdLBotStrategy(LBotStrategyBase):
    strategy_name = "trend_ma_macd"

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
            config=TrendMaMacdConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "trend_ma_macd_no_reason")
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
