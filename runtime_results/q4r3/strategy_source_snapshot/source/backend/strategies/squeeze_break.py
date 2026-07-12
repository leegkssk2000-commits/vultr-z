from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "squeeze_break"

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
class SqueezeBreakConfig:
    bb_len: int = 20
    bb_mult: float = 2.0
    kc_len: int = 20
    kc_mult: float = 1.5
    ema_len: int = 34
    atr_len: int = 14
    min_bars: int = 90

    min_atr_pct: float = 0.22
    max_atr_pct: float = 5.80

    min_release_impulse_atr: float = 0.22
    beam_release_impulse_atr: float = 0.48
    max_chase_dist_atr: float = 1.85
    fake_break_reject_atr: float = 0.22

    stop_atr_mult: float = 1.45
    trail_atr_mult: float = 0.90
    base_rr: float = 2.20
    beam_rr: float = 2.90

    long_base_size: float = 0.56
    short_base_size: float = 0.36
    beam_bonus_long: float = 0.16
    beam_bonus_short: float = 0.12

    scale_in_size_long: float = 0.24
    scale_in_size_short: float = 0.16
    retest_add_size_long: float = 0.16
    retest_add_size_short: float = 0.10
    reduce_size_long: float = 0.25
    reduce_size_short: float = 0.20

    scale_in_progress_min: float = 0.35
    retest_reclaim_atr: float = 0.18
    max_add_count: int = 2
    max_pyramiding: int = 3

    beam_body_ratio_min: float = 0.42
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


def _bollinger(series: pd.Series, length: int, mult: float) -> pd.DataFrame:
    basis = series.astype(float).rolling(length, min_periods=length).mean()
    dev = series.astype(float).rolling(length, min_periods=length).std(ddof=0)
    upper = basis + dev * mult
    lower = basis - dev * mult
    return pd.DataFrame({"basis": basis, "upper": upper, "lower": lower})


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
    config: Optional[SqueezeBreakConfig] = None,
) -> Dict[str, Any]:
    cfg = config or SqueezeBreakConfig()

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
            why="squeeze_break_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.bb_len + 5, cfg.kc_len + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="squeeze_break_not_enough_bars",
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

    bb = _bollinger(df["close"], cfg.bb_len, cfg.bb_mult)
    atr_now_series = _atr(df, cfg.atr_len)
    ema = _ema(df["close"], cfg.ema_len)
    ema_kc = _ema(df["close"], cfg.kc_len)

    df["bb_basis"] = bb["basis"]
    df["bb_upper"] = bb["upper"]
    df["bb_lower"] = bb["lower"]
    df["atr"] = atr_now_series
    df["ema"] = ema
    df["kc_upper"] = ema_kc + df["atr"] * cfg.kc_mult
    df["kc_lower"] = ema_kc - df["atr"] * cfg.kc_mult
    df["squeeze_on"] = (df["bb_upper"] < df["kc_upper"]) & (df["bb_lower"] > df["kc_lower"])

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    atr_now = _to_float(last["atr"])
    ema_now = _to_float(last["ema"])
    ema_prev = _to_float(prev["ema"])
    bb_upper = _to_float(last["bb_upper"])
    bb_lower = _to_float(last["bb_lower"])
    bb_basis = _to_float(last["bb_basis"])
    prev_close = _to_float(prev["close"])
    prev_squeeze = bool(prev["squeeze_on"])
    now_squeeze = bool(last["squeeze_on"])

    if min(price, atr_now, ema_now, bb_upper, bb_lower, bb_basis) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="squeeze_break_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    atr_pct = (atr_now / max(price, 1e-9)) * 100.0
    ema_up = ema_now > ema_prev
    ema_down = ema_now < ema_prev
    dist_from_ema_atr = abs(price - ema_now) / max(atr_now, 1e-9)

    released = prev_squeeze and not now_squeeze
    long_break = released and price > bb_upper
    short_break = released and price < bb_lower

    trend_long = price > ema_now and ema_up
    trend_short = price < ema_now and ema_down

    impulse_atr = abs(price - prev_close) / max(atr_now, 1e-9)
    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    long_reclaim = prev_close <= bb_upper and price > bb_upper + atr_now * cfg.retest_reclaim_atr
    short_reclaim = prev_close >= bb_lower and price < bb_lower - atr_now * cfg.retest_reclaim_atr

    long_beam = (
        long_break
        and trend_long
        and impulse_atr >= cfg.beam_release_impulse_atr
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )

    short_beam = (
        short_break
        and trend_short
        and impulse_atr >= cfg.beam_release_impulse_atr
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_ema_atr > cfg.max_chase_dist_atr

    failed_long_break = (
        prev_close > bb_upper
        and price < bb_upper - atr_now * cfg.fake_break_reject_atr
    )
    failed_short_break = (
        prev_close < bb_lower
        and price > bb_lower + atr_now * cfg.fake_break_reject_atr
    )

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema": round(ema_now, 6),
        "ema_prev": round(ema_prev, 6),
        "ema_up": ema_up,
        "ema_down": ema_down,
        "bb_basis": round(bb_basis, 6),
        "bb_upper": round(bb_upper, 6),
        "bb_lower": round(bb_lower, 6),
        "prev_squeeze": prev_squeeze,
        "now_squeeze": now_squeeze,
        "released": released,
        "long_break": long_break,
        "short_break": short_break,
        "trend_long": trend_long,
        "trend_short": trend_short,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "impulse_atr": round(impulse_atr, 6),
        "dist_from_ema_atr": round(dist_from_ema_atr, 6),
        "late_chase_block": late_chase_block,
        "failed_long_break": failed_long_break,
        "failed_short_break": failed_short_break,
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "long_beam": long_beam,
        "short_beam": short_beam,
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
            why="squeeze_break_volatility_out_of_range",
            skill="none",
            confidence=0.0,
            tags=["volatility_gate"],
            indicators=indicators,
        )

    if late_chase_block and (long_break or short_break):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="squeeze_break_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    if released and impulse_atr < cfg.min_release_impulse_atr:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="squeeze_break_release_too_weak",
            skill="none",
            confidence=0.0,
            tags=["weak_release"],
            indicators=indicators,
        )

    long_sl = min(bb_basis - atr_now * cfg.stop_atr_mult, ema_now - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(bb_basis + atr_now * cfg.stop_atr_mult, ema_now + atr_now * cfg.trail_atr_mult, high)

    long_risk = max(price - long_sl, atr_now * 0.40)
    short_risk = max(short_sl - price, atr_now * 0.40)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_scale_in = False
    short_scale_in = False
    long_retest_add = False
    short_retest_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(long_tp - pos["avg_entry"], 1e-9)
        progress = (price - pos["avg_entry"]) / move_to_tp if move_to_tp > 0 else 0.0
        long_scale_in = progress >= cfg.scale_in_progress_min and price > bb_upper and trend_long
        long_retest_add = (
            low <= bb_upper
            and price >= bb_upper + atr_now * cfg.retest_reclaim_atr
            and trend_long
        )
        long_reduce = failed_long_break

    if in_short and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(pos["avg_entry"] - short_tp, 1e-9)
        progress = (pos["avg_entry"] - price) / move_to_tp if move_to_tp > 0 else 0.0
        short_scale_in = progress >= cfg.scale_in_progress_min and price < bb_lower and trend_short
        short_retest_add = (
            high >= bb_lower
            and price <= bb_lower - atr_now * cfg.retest_reclaim_atr
            and trend_short
        )
        short_reduce = failed_short_break

    if long_break and trend_long and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0)
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="squeeze_break_long",
            skill="long_beam" if long_beam else "release_breakout",
            confidence=0.84 if long_beam else 0.72,
            tags=["squeeze", "break", "long"],
            indicators=indicators,
        )

    if short_break and trend_short and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0)
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="squeeze_break_short",
            skill="short_beam" if short_beam else "release_breakout",
            confidence=0.78 if short_beam else 0.66,
            tags=["squeeze", "break", "short"],
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
            why="squeeze_break_long_scale_in",
            skill="scale_in",
            confidence=0.68,
            tags=["squeeze", "break", "scale_in", "long"],
            indicators=indicators,
        )

    if long_retest_add:
        return _build_result(
            side="long",
            action="add",
            size=cfg.retest_add_size_long,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="squeeze_break_long_retest_add",
            skill="retest_add",
            confidence=0.64,
            tags=["squeeze", "break", "retest_add", "long"],
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
            why="squeeze_break_short_scale_in",
            skill="scale_in",
            confidence=0.60,
            tags=["squeeze", "break", "scale_in", "short"],
            indicators=indicators,
        )

    if short_retest_add:
        return _build_result(
            side="short",
            action="add",
            size=cfg.retest_add_size_short,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="squeeze_break_short_retest_add",
            skill="retest_add",
            confidence=0.56,
            tags=["squeeze", "break", "retest_add", "short"],
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
            why="squeeze_break_failed_long_break_reduce",
            skill="failed_break_reduce",
            confidence=0.72,
            tags=["squeeze", "failed_break", "reduce", "long"],
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
            why="squeeze_break_failed_short_break_reduce",
            skill="failed_break_reduce",
            confidence=0.68,
            tags=["squeeze", "failed_break", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "squeeze_break_no_setup"
    if released and not (long_break or short_break):
        hold_reason = "released_without_band_break"
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


class SqueezeBreakLBotStrategy(LBotStrategyBase):
    strategy_name = "squeeze_break"

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
            config=SqueezeBreakConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "squeeze_break_no_reason")
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
