from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "trend_rider"

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
class TrendRiderConfig:
    st_len: int = 10
    st_mult: float = 3.0
    ema_len: int = 50
    atr_len: int = 14
    min_bars: int = 100

    min_atr_pct: float = 0.22
    max_atr_pct: float = 5.80

    st_gap_atr_min: float = 0.12
    st_gap_atr_beam: float = 0.45
    max_chase_dist_atr: float = 2.10

    stop_atr_mult: float = 2.00
    trail_atr_mult: float = 1.20
    base_rr: float = 2.50
    beam_rr: float = 3.10

    long_base_size: float = 0.60
    short_base_size: float = 0.38
    beam_bonus_long: float = 0.16
    beam_bonus_short: float = 0.12

    scale_in_size_long: float = 0.25
    scale_in_size_short: float = 0.16
    dip_add_size_long: float = 0.16
    dip_add_size_short: float = 0.10

    scale_in_progress_min: float = 0.38
    dip_add_reclaim_atr: float = 0.22
    max_adverse_atr_for_dip: float = 1.20

    beam_body_ratio_min: float = 0.40
    beam_close_location_min: float = 0.62

    max_add_count: int = 3
    max_pyramiding: int = 5


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


def _supertrend(df: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    atr = _atr(df, length)

    hl2 = (high + low) / 2.0
    upperband = hl2 + multiplier * atr
    lowerband = hl2 - multiplier * atr

    final_upperband = upperband.copy()
    final_lowerband = lowerband.copy()
    direction = pd.Series(index=df.index, dtype="float64")
    st = pd.Series(index=df.index, dtype="float64")

    for i in range(len(df)):
        if i == 0:
            direction.iloc[i] = 1.0
            st.iloc[i] = lowerband.iloc[i]
            continue

        if upperband.iloc[i] < final_upperband.iloc[i - 1] or close.iloc[i - 1] > final_upperband.iloc[i - 1]:
            final_upperband.iloc[i] = upperband.iloc[i]
        else:
            final_upperband.iloc[i] = final_upperband.iloc[i - 1]

        if lowerband.iloc[i] > final_lowerband.iloc[i - 1] or close.iloc[i - 1] < final_lowerband.iloc[i - 1]:
            final_lowerband.iloc[i] = lowerband.iloc[i]
        else:
            final_lowerband.iloc[i] = final_lowerband.iloc[i - 1]

        if st.iloc[i - 1] == final_upperband.iloc[i - 1]:
            if close.iloc[i] <= final_upperband.iloc[i]:
                st.iloc[i] = final_upperband.iloc[i]
                direction.iloc[i] = -1.0
            else:
                st.iloc[i] = final_lowerband.iloc[i]
                direction.iloc[i] = 1.0
        else:
            if close.iloc[i] >= final_lowerband.iloc[i]:
                st.iloc[i] = final_lowerband.iloc[i]
                direction.iloc[i] = 1.0
            else:
                st.iloc[i] = final_upperband.iloc[i]
                direction.iloc[i] = -1.0

    return pd.DataFrame(
        {
            "supertrend": st,
            "direction": direction,
            "atr": atr,
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
    config: Optional[TrendRiderConfig] = None,
) -> Dict[str, Any]:
    cfg = config or TrendRiderConfig()

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
            why="trend_rider_empty",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.ema_len + 10, cfg.st_len + 10):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="trend_rider_short",
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

    st_df = _supertrend(df, cfg.st_len, cfg.st_mult)
    df["st"] = st_df["supertrend"]
    df["dir"] = st_df["direction"]
    df["atr"] = st_df["atr"]
    df["ema"] = _ema(df["close"], cfg.ema_len)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    atr_now = _to_float(last["atr"])
    st_now = _to_float(last["st"])
    st_prev = _to_float(prev["st"])
    ema_now = _to_float(last["ema"])
    ema_prev = _to_float(prev["ema"])
    dir_now = int(_to_float(last["dir"]))
    prev_green = _to_float(prev["close"]) >= _to_float(prev["open"])
    prev_red = _to_float(prev["close"]) <= _to_float(prev["open"])

    if min(price, atr_now, st_now, ema_now) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="trend_rider_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    atr_pct = (atr_now / max(price, 1e-9)) * 100.0
    st_gap_atr = abs(price - st_now) / max(atr_now, 1e-9)
    dist_from_ema_atr = abs(price - ema_now) / max(atr_now, 1e-9)

    ema_up = ema_now > ema_prev
    ema_down = ema_now < ema_prev
    st_rising = st_now > st_prev
    st_falling = st_now < st_prev

    trend_long = dir_now == 1 and price > st_now and price > ema_now and ema_up and st_rising
    trend_short = dir_now == -1 and price < st_now and price < ema_now and ema_down and st_falling

    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    long_confirm = prev_green and trend_long and st_gap_atr >= cfg.st_gap_atr_min
    short_confirm = prev_red and trend_short and st_gap_atr >= cfg.st_gap_atr_min

    long_beam = (
        long_confirm
        and st_gap_atr >= cfg.st_gap_atr_beam
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )

    short_beam = (
        short_confirm
        and st_gap_atr >= cfg.st_gap_atr_beam
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_ema_atr > cfg.max_chase_dist_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "st": round(st_now, 6),
        "st_prev": round(st_prev, 6),
        "dir": dir_now,
        "ema": round(ema_now, 6),
        "ema_prev": round(ema_prev, 6),
        "ema_up": ema_up,
        "ema_down": ema_down,
        "st_rising": st_rising,
        "st_falling": st_falling,
        "st_gap_atr": round(st_gap_atr, 6),
        "dist_from_ema_atr": round(dist_from_ema_atr, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "long_confirm": long_confirm,
        "short_confirm": short_confirm,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "late_chase_block": late_chase_block,
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
            why="trend_rider_volatility_out_of_range",
            skill="none",
            confidence=0.0,
            tags=["volatility_gate"],
            indicators=indicators,
        )

    if late_chase_block and (long_confirm or short_confirm):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="trend_rider_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(st_now, ema_now - atr_now * cfg.trail_atr_mult, price - atr_now * cfg.stop_atr_mult)
    short_sl = max(st_now, ema_now + atr_now * cfg.trail_atr_mult, price + atr_now * cfg.stop_atr_mult)

    long_risk = max(price - long_sl, atr_now * 0.50)
    short_risk = max(short_sl - price, atr_now * 0.50)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_scale_in = False
    short_scale_in = False
    long_dip_add = False
    short_dip_add = False

    if in_long and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(long_tp - pos["avg_entry"], 1e-9)
        progress = (price - pos["avg_entry"]) / move_to_tp if move_to_tp > 0 else 0.0
        long_scale_in = progress >= cfg.scale_in_progress_min and trend_long and st_gap_atr >= cfg.st_gap_atr_min
        long_dip_add = (
            low <= ema_now
            and price >= ema_now + atr_now * cfg.dip_add_reclaim_atr
            and price >= pos["avg_entry"] - atr_now * cfg.max_adverse_atr_for_dip
            and trend_long
        )

    if in_short and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(pos["avg_entry"] - short_tp, 1e-9)
        progress = (pos["avg_entry"] - price) / move_to_tp if move_to_tp > 0 else 0.0
        short_scale_in = progress >= cfg.scale_in_progress_min and trend_short and st_gap_atr >= cfg.st_gap_atr_min
        short_dip_add = (
            high >= ema_now
            and price <= ema_now - atr_now * cfg.dip_add_reclaim_atr
            and price <= pos["avg_entry"] + atr_now * cfg.max_adverse_atr_for_dip
            and trend_short
        )

    if long_confirm and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0)
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="trend_rider_long",
            skill="long_beam" if long_beam else "trend_ride_entry",
            confidence=0.84 if long_beam else 0.72,
            tags=["trend_rider", "supertrend", "ema", "long"],
            indicators=indicators,
        )

    if short_confirm and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0)
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="trend_rider_short",
            skill="short_beam" if short_beam else "trend_ride_entry",
            confidence=0.80 if short_beam else 0.66,
            tags=["trend_rider", "supertrend", "ema", "short"],
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
            why="trend_rider_long_scale_in",
            skill="scale_in",
            confidence=0.68,
            tags=["trend_rider", "supertrend", "ema", "scale_in", "long"],
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
            why="trend_rider_long_dip_add",
            skill="dip_add",
            confidence=0.64,
            tags=["trend_rider", "supertrend", "ema", "dip_add", "long"],
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
            why="trend_rider_short_scale_in",
            skill="scale_in",
            confidence=0.60,
            tags=["trend_rider", "supertrend", "ema", "scale_in", "short"],
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
            why="trend_rider_short_dip_add",
            skill="dip_add",
            confidence=0.56,
            tags=["trend_rider", "supertrend", "ema", "dip_add", "short"],
            indicators=indicators,
        )

    hold_reason = "trend_rider_no_setup"
    if dir_now == 1 and not long_confirm and trend_long:
        hold_reason = "trend_rider_long_regime_but_confirmation_missing"
    elif dir_now == -1 and not short_confirm and trend_short:
        hold_reason = "trend_rider_short_regime_but_confirmation_missing"
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


class TrendRiderLBotStrategy(LBotStrategyBase):
    strategy_name = "trend_rider"

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
            config=TrendRiderConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "trend_rider_no_reason")
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
