from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "mfi_rsi_div"

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
class MfiRsiDivConfig:
    length: int = 14
    swing_lookback: int = 28
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 100

    min_atr_pct: float = 0.14
    max_atr_pct: float = 5.20

    bull_rsi_gate: float = 42.0
    bear_rsi_gate: float = 58.0
    bull_mfi_gate: float = 45.0
    bear_mfi_gate: float = 55.0

    min_div_buffer_pct: float = 0.0012
    reclaim_atr_min: float = 0.14
    max_chase_dist_atr: float = 1.35
    fail_div_reject_atr: float = 0.22

    beam_rsi_delta: float = 5.0
    beam_mfi_delta: float = 6.0
    beam_body_ratio_min: float = 0.36
    beam_close_location_min: float = 0.60

    stop_atr_mult: float = 0.70
    trail_atr_mult: float = 0.46
    base_rr: float = 2.20
    beam_rr: float = 2.80

    long_base_size: float = 0.48
    short_base_size: float = 0.34
    beam_bonus_long: float = 0.12
    beam_bonus_short: float = 0.10

    add_size_long: float = 0.14
    add_size_short: float = 0.10
    reduce_size_long: float = 0.24
    reduce_size_short: float = 0.20

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


def _rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _mfi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    tp = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    raw = tp * df["volume"].astype(float)
    pos = raw.where(tp > tp.shift(1), 0.0)
    neg = raw.where(tp < tp.shift(1), 0.0)
    pos_sum = pos.rolling(length, min_periods=length).sum()
    neg_sum = neg.rolling(length, min_periods=length).sum()
    mr = pos_sum / (neg_sum + 1e-9)
    return 100.0 - (100.0 / (1.0 + mr))


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
    config: Optional[MfiRsiDivConfig] = None,
) -> Dict[str, Any]:
    cfg = config or MfiRsiDivConfig()

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
            why="mfi_rsi_div_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.swing_lookback + cfg.length + 5, cfg.ema_slow_len + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="mfi_rsi_div_short",
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

    df["mfi"] = _mfi(df, cfg.length)
    df["rsi"] = _rsi(df["close"], cfg.length)
    df["atr"] = _atr(df, cfg.atr_len)
    df["ema_fast"] = _ema(df["close"], cfg.ema_fast_len)
    df["ema_slow"] = _ema(df["close"], cfg.ema_slow_len)

    last = df.iloc[-1]
    prev = df.iloc[-2]
    recent = df.iloc[-cfg.swing_lookback:]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    prev_close = _to_float(prev["close"])

    atr_now = _to_float(last["atr"])
    mfi_now = _to_float(last["mfi"])
    rsi_now = _to_float(last["rsi"])
    ema_fast = _to_float(last["ema_fast"])
    ema_slow = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_slow_prev = _to_float(prev["ema_slow"])

    if min(price, atr_now, ema_fast, ema_slow) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="mfi_rsi_div_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    swing_low_idx = recent["low"].idxmin()
    swing_high_idx = recent["high"].idxmax()

    swing_low_price = _to_float(df.loc[swing_low_idx, "low"])
    swing_high_price = _to_float(df.loc[swing_high_idx, "high"])
    swing_low_mfi = _to_float(df.loc[swing_low_idx, "mfi"])
    swing_high_mfi = _to_float(df.loc[swing_high_idx, "mfi"])
    swing_low_rsi = _to_float(df.loc[swing_low_idx, "rsi"])
    swing_high_rsi = _to_float(df.loc[swing_high_idx, "rsi"])

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev

    price_makes_lower_low = price < swing_low_price * (1.0 - cfg.min_div_buffer_pct)
    price_makes_higher_high = price > swing_high_price * (1.0 + cfg.min_div_buffer_pct)

    bull_mfi_div = mfi_now > swing_low_mfi
    bull_rsi_div = rsi_now > swing_low_rsi
    bear_mfi_div = mfi_now < swing_high_mfi
    bear_rsi_div = rsi_now < swing_high_rsi

    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min

    long_setup = (
        price_makes_lower_low
        and bull_mfi_div
        and bull_rsi_div
        and mfi_now <= cfg.bull_mfi_gate
        and rsi_now <= cfg.bull_rsi_gate
        and long_reclaim
        and not trend_short
    )
    short_setup = (
        price_makes_higher_high
        and bear_mfi_div
        and bear_rsi_div
        and mfi_now >= cfg.bear_mfi_gate
        and rsi_now >= cfg.bear_rsi_gate
        and short_reclaim
        and not trend_long
    )

    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)

    bull_rsi_delta = rsi_now - swing_low_rsi
    bull_mfi_delta = mfi_now - swing_low_mfi
    bear_rsi_delta = swing_high_rsi - rsi_now
    bear_mfi_delta = swing_high_mfi - mfi_now

    long_beam = (
        long_setup
        and bull_rsi_delta >= cfg.beam_rsi_delta
        and bull_mfi_delta >= cfg.beam_mfi_delta
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup
        and bear_rsi_delta >= cfg.beam_rsi_delta
        and bear_mfi_delta >= cfg.beam_mfi_delta
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr

    failed_long = price < swing_low_price - atr_now * cfg.fail_div_reject_atr
    failed_short = price > swing_high_price + atr_now * cfg.fail_div_reject_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "mfi": round(mfi_now, 6),
        "rsi": round(rsi_now, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "swing_low_price": round(swing_low_price, 6),
        "swing_high_price": round(swing_high_price, 6),
        "swing_low_mfi": round(swing_low_mfi, 6),
        "swing_high_mfi": round(swing_high_mfi, 6),
        "swing_low_rsi": round(swing_low_rsi, 6),
        "swing_high_rsi": round(swing_high_rsi, 6),
        "price_makes_lower_low": price_makes_lower_low,
        "price_makes_higher_high": price_makes_higher_high,
        "bull_mfi_div": bull_mfi_div,
        "bull_rsi_div": bull_rsi_div,
        "bear_mfi_div": bear_mfi_div,
        "bear_rsi_div": bear_rsi_div,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "bull_rsi_delta": round(bull_rsi_delta, 6),
        "bull_mfi_delta": round(bull_mfi_delta, 6),
        "bear_rsi_delta": round(bear_rsi_delta, 6),
        "bear_mfi_delta": round(bear_mfi_delta, 6),
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
            why="mfi_rsi_div_volatility_out_of_range",
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
            why="mfi_rsi_div_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(swing_low_price - atr_now * cfg.stop_atr_mult, ema_fast - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(swing_high_price + atr_now * cfg.stop_atr_mult, ema_fast + atr_now * cfg.trail_atr_mult, high)

    long_risk = max(price - long_sl, atr_now * 0.28)
    short_risk = max(short_sl - price, atr_now * 0.28)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_add = False
    short_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more:
        long_add = long_setup and long_reclaim and not failed_long
        long_reduce = failed_long

    if in_short and can_add_more:
        short_add = short_setup and short_reclaim and not failed_short
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
            why="mfi_rsi_bull_div",
            skill="long_beam" if long_beam else "dual_div_reclaim",
            confidence=0.84 if long_beam else 0.70,
            tags=["mfi", "rsi", "div", "long"],
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
            why="mfi_rsi_bear_div",
            skill="short_beam" if short_beam else "dual_div_reclaim",
            confidence=0.80 if short_beam else 0.66,
            tags=["mfi", "rsi", "div", "short"],
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
            why="mfi_rsi_div_long_add",
            skill="dip_add",
            confidence=0.60,
            tags=["mfi", "rsi", "div", "add", "long"],
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
            why="mfi_rsi_div_short_add",
            skill="dip_add",
            confidence=0.56,
            tags=["mfi", "rsi", "div", "add", "short"],
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
            why="mfi_rsi_div_failed_long_reduce",
            skill="failed_div_reduce",
            confidence=0.68,
            tags=["mfi", "rsi", "div", "failed", "reduce", "long"],
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
            why="mfi_rsi_div_failed_short_reduce",
            skill="failed_div_reduce",
            confidence=0.64,
            tags=["mfi", "rsi", "div", "failed", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "mfi_rsi_div_no_setup"
    if price_makes_lower_low and not (bull_mfi_div and bull_rsi_div):
        hold_reason = "lower_low_without_dual_bull_div"
    elif price_makes_higher_high and not (bear_mfi_div and bear_rsi_div):
        hold_reason = "higher_high_without_dual_bear_div"
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


class MfiRsiDivLBotStrategy(LBotStrategyBase):
    strategy_name = "mfi_rsi_div"

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
            config=MfiRsiDivConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "mfi_rsi_div_no_reason")
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
