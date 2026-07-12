from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "range_fade"

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
class RangeFadeConfig:
    lookback: int = 60
    atr_len: int = 14
    rsi_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 100

    max_box_pct: float = 2.00
    max_atr_pct: float = 1.20
    min_atr_pct: float = 0.08

    upper_zone_pct: float = 0.80
    lower_zone_pct: float = 0.20
    mid_zone_pct: float = 0.50

    long_rsi_max: float = 40.0
    short_rsi_min: float = 60.0
    beam_long_rsi_max: float = 34.0
    beam_short_rsi_min: float = 66.0

    reclaim_atr_min: float = 0.10
    max_chase_dist_atr: float = 1.00
    fail_range_break_atr: float = 0.22

    stop_atr_mult: float = 0.80
    trail_atr_mult: float = 0.55
    base_rr: float = 1.50
    beam_rr: float = 2.00

    long_base_size: float = 0.44
    short_base_size: float = 0.34
    beam_bonus_long: float = 0.12
    beam_bonus_short: float = 0.10

    add_size_long: float = 0.14
    add_size_short: float = 0.10
    reduce_size_long: float = 0.22
    reduce_size_short: float = 0.20

    max_add_count: int = 3
    max_pyramiding: int = 4

    beam_body_ratio_min: float = 0.34
    beam_close_location_min: float = 0.58


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


def _rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))


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
    config: Optional[RangeFadeConfig] = None,
) -> Dict[str, Any]:
    cfg = config or RangeFadeConfig()

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
            why="range_invalid_input",
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
            why="range_short",
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
    df["rsi"] = _rsi(df["close"], cfg.rsi_len)
    df["ema_fast"] = _ema(df["close"], cfg.ema_fast_len)
    df["ema_slow"] = _ema(df["close"], cfg.ema_slow_len)

    last = df.iloc[-1]
    prev = df.iloc[-2]
    recent = df.iloc[-cfg.lookback:]

    high_max = _to_float(recent["high"].max())
    low_min = _to_float(recent["low"].min())
    box_height = high_max - low_min

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    prev_close = _to_float(prev["close"])
    atr_now = _to_float(last["atr"])
    rsi_now = _to_float(last["rsi"])
    ema_fast = _to_float(last["ema_fast"])
    ema_slow = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_slow_prev = _to_float(prev["ema_slow"])

    if min(price, atr_now, high_max, low_min) <= 0 or box_height <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="range_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    box_pct = box_height / max(price, 1e-9) * 100.0
    atr_pct = atr_now / max(price, 1e-9) * 100.0

    upper_zone = low_min + box_height * cfg.upper_zone_pct
    lower_zone = low_min + box_height * cfg.lower_zone_pct
    mid_zone = low_min + box_height * cfg.mid_zone_pct

    dist_from_mid_atr = abs(price - mid_zone) / max(atr_now, 1e-9)
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)

    ema_flat = abs(ema_fast - ema_fast_prev) <= atr_now * 0.18 and abs(ema_slow - ema_slow_prev) <= atr_now * 0.14
    slight_up = ema_fast >= ema_slow
    slight_down = ema_fast <= ema_slow

    sideways_ok = box_pct <= cfg.max_box_pct and cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    reclaim_up = price > prev_close + atr_now * cfg.reclaim_atr_min
    reclaim_down = price < prev_close - atr_now * cfg.reclaim_atr_min

    long_setup = price <= lower_zone and rsi_now < cfg.long_rsi_max and reclaim_up and slight_up
    short_setup = price >= upper_zone and rsi_now > cfg.short_rsi_min and reclaim_down and slight_down

    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    long_beam = (
        long_setup
        and rsi_now <= cfg.beam_long_rsi_max
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup
        and rsi_now >= cfg.beam_short_rsi_min
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    late_chase_block = dist_from_mid_atr > cfg.max_chase_dist_atr or dist_from_fast_atr > cfg.max_chase_dist_atr

    range_break_up = price > high_max + atr_now * cfg.fail_range_break_atr
    range_break_down = price < low_min - atr_now * cfg.fail_range_break_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "rsi": round(rsi_now, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "ema_flat": ema_flat,
        "slight_up": slight_up,
        "slight_down": slight_down,
        "range_high": round(high_max, 6),
        "range_low": round(low_min, 6),
        "box_height": round(box_height, 6),
        "box_pct": round(box_pct, 6),
        "upper_zone": round(upper_zone, 6),
        "lower_zone": round(lower_zone, 6),
        "mid_zone": round(mid_zone, 6),
        "dist_from_mid_atr": round(dist_from_mid_atr, 6),
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
        "sideways_ok": sideways_ok,
        "reclaim_up": reclaim_up,
        "reclaim_down": reclaim_down,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "long_beam": long_beam,
        "short_beam": short_beam,
        "late_chase_block": late_chase_block,
        "range_break_up": range_break_up,
        "range_break_down": range_break_down,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "avg_entry": pos["avg_entry"],
        "add_count": pos["add_count"],
    }

    if not sideways_ok:
        why = "range_not_sideways" if box_pct > cfg.max_box_pct else "range_too_volatile"
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why=why,
            skill="none",
            confidence=0.0,
            tags=["range_gate"],
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
            why="range_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(low_min - atr_now * cfg.stop_atr_mult, price - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(high_max + atr_now * cfg.stop_atr_mult, price + atr_now * cfg.trail_atr_mult, high)

    long_risk = max(price - long_sl, atr_now * 0.22)
    short_risk = max(short_sl - price, atr_now * 0.22)

    long_tp = min(mid_zone + (mid_zone - lower_zone) * 0.60, price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr))
    short_tp = max(mid_zone - (upper_zone - mid_zone) * 0.60, price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr))

    long_add = False
    short_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more:
        long_add = price <= lower_zone and reclaim_up and not range_break_down
        long_reduce = range_break_down

    if in_short and can_add_more:
        short_add = price >= upper_zone and reclaim_down and not range_break_up
        short_reduce = range_break_up

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
            why="range_fade_long",
            skill="long_beam" if long_beam else "range_fade",
            confidence=0.80 if long_beam else 0.66,
            tags=["range", "fade", "long"],
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
            why="range_fade_short",
            skill="short_beam" if short_beam else "range_fade",
            confidence=0.76 if short_beam else 0.62,
            tags=["range", "fade", "short"],
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
            why="range_long_add",
            skill="water_add",
            confidence=0.58,
            tags=["range", "fade", "add", "long"],
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
            why="range_short_add",
            skill="water_add",
            confidence=0.54,
            tags=["range", "fade", "add", "short"],
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
            why="range_breakdown_reduce",
            skill="failed_range_reduce",
            confidence=0.70,
            tags=["range", "breakdown", "reduce", "long"],
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
            why="range_breakup_reduce",
            skill="failed_range_reduce",
            confidence=0.66,
            tags=["range", "breakup", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "range_no_setup"
    if price >= upper_zone and rsi_now <= cfg.short_rsi_min:
        hold_reason = "upper_zone_without_overbought"
    elif price <= lower_zone and rsi_now >= cfg.long_rsi_max:
        hold_reason = "lower_zone_without_oversold"
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


class RangeFadeLBotStrategy(LBotStrategyBase):
    strategy_name = "range_fade"

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
            config=RangeFadeConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "range_no_reason")
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
