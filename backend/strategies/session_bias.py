from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase:  # type: ignore
        strategy_name = "session_bias"

    class StrategyIntent:  # type: ignore
        HOLD = "hold"
        ENTER_LONG = "enter_long"
        EXIT_LONG = "exit_long"
        REDUCE = "reduce"
        BLOCK = "block"

    class StrategyDecision:  # type: ignore
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

    DecisionContext = Any  # type: ignore


@dataclass
class SessionBiasConfig:
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    range_lookback: int = 24
    min_bars: int = 90

    min_atr_pct: float = 0.18
    max_atr_pct: float = 5.50

    breakout_buffer_atr: float = 0.10
    reclaim_atr_min: float = 0.16
    max_chase_dist_atr: float = 1.70
    fail_break_reject_atr: float = 0.22

    stop_atr_mult: float = 1.15
    trail_atr_mult: float = 0.85
    base_rr: float = 1.90
    beam_rr: float = 2.50

    long_base_size: float = 0.46
    short_base_size: float = 0.30
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10

    scale_in_size_long: float = 0.20
    scale_in_size_short: float = 0.14
    retest_add_size_long: float = 0.14
    retest_add_size_short: float = 0.10
    reduce_size_long: float = 0.25
    reduce_size_short: float = 0.20

    scale_in_progress_min: float = 0.34
    max_add_count: int = 2
    max_pyramiding: int = 2

    beam_body_ratio_min: float = 0.38
    beam_close_location_min: float = 0.60

    asia_start_hour: int = 0
    asia_end_hour: int = 8
    london_start_hour: int = 8
    london_end_hour: int = 16
    ny_start_hour: int = 13
    ny_end_hour: int = 21
    default_tz: str = "UTC"


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


def _extract_ts(row: pd.Series) -> Optional[float]:
    for key in ("ts", "timestamp", "time", "open_time", "close_time"):
        if key in row.index:
            v = row.get(key)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            try:
                x = float(v)
                if x > 1e12:
                    x /= 1000.0
                return x
            except Exception:
                pass
    return None


def _session_name_from_ts(ts_value: Optional[float], tz_name: str, cfg: SessionBiasConfig) -> str:
    if ts_value is None:
        return "unknown"

    try:
        dt_utc = datetime.fromtimestamp(float(ts_value), tz=timezone.utc)
        if ZoneInfo is not None:
            dt = dt_utc.astimezone(ZoneInfo(tz_name))
        else:
            dt = dt_utc
    except Exception:
        return "unknown"

    hour = dt.hour

    if cfg.asia_start_hour <= hour < cfg.asia_end_hour:
        return "asia"
    if cfg.london_start_hour <= hour < cfg.london_end_hour:
        return "london"
    if cfg.ny_start_hour <= hour < cfg.ny_end_hour:
        return "newyork"
    return "overlap"


def _payload_session_tz(payload: Optional[Mapping[str, Any]], cfg: SessionBiasConfig) -> str:
    payload = dict(payload or {})
    for key in ("session_tz", "tz", "timezone"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return cfg.default_tz


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[SessionBiasConfig] = None,
    session_tz: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = config or SessionBiasConfig()

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
            why="session_bias_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.range_lookback + 5, cfg.ema_slow_len + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="session_bias_not_enough_bars",
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

    last = df.iloc[-1]
    prev = df.iloc[-2]
    recent = df.iloc[-cfg.range_lookback:]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])
    atr_now = _to_float(last["atr"])
    ema_fast = _to_float(last["ema_fast"])
    ema_slow = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_slow_prev = _to_float(prev["ema_slow"])
    prev_close = _to_float(prev["close"])

    if min(price, atr_now, ema_fast, ema_slow) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="session_bias_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    session_high = _to_float(recent["high"].max())
    session_low = _to_float(recent["low"].min())
    session_mid = (session_high + session_low) / 2.0

    atr_pct = (atr_now / max(price, 1e-9)) * 100.0
    ema_fast_up = ema_fast > ema_fast_prev
    ema_fast_down = ema_fast < ema_fast_prev
    ema_slow_up = ema_slow > ema_slow_prev
    ema_slow_down = ema_slow < ema_slow_prev

    trend_long = price > ema_fast > ema_slow and ema_fast_up and ema_slow_up
    trend_short = price < ema_fast < ema_slow and ema_fast_down and ema_slow_down

    breakout_buffer = atr_now * cfg.breakout_buffer_atr
    long_break = price > session_high + breakout_buffer
    short_break = price < session_low - breakout_buffer

    long_reclaim = prev_close <= session_high and price > session_high + atr_now * cfg.reclaim_atr_min
    short_reclaim = prev_close >= session_low and price < session_low - atr_now * cfg.reclaim_atr_min

    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)
    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)

    tz_name = session_tz or cfg.default_tz
    session_name = _session_name_from_ts(_extract_ts(last), tz_name, cfg)

    bias_long = False
    bias_short = False
    bias_strength = 0.0

    if session_name == "asia":
        bias_long = trend_long and price >= session_mid
        bias_short = trend_short and price <= session_mid
        bias_strength = 0.52
    elif session_name == "london":
        bias_long = trend_long
        bias_short = trend_short
        bias_strength = 0.70
    elif session_name == "newyork":
        bias_long = trend_long and long_break
        bias_short = trend_short and short_break
        bias_strength = 0.76
    else:
        bias_long = trend_long and price >= session_mid
        bias_short = trend_short and price <= session_mid
        bias_strength = 0.60

    long_beam = (
        bias_long
        and long_break
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        bias_short
        and short_break
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr

    failed_long_break = prev_close > session_high and price < session_high - atr_now * cfg.fail_break_reject_atr
    failed_short_break = prev_close < session_low and price > session_low + atr_now * cfg.fail_break_reject_atr

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
        "session_name": session_name,
        "session_tz": tz_name,
        "session_high": round(session_high, 6),
        "session_low": round(session_low, 6),
        "session_mid": round(session_mid, 6),
        "bias_long": bias_long,
        "bias_short": bias_short,
        "bias_strength": round(bias_strength, 6),
        "long_break": long_break,
        "short_break": short_break,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
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
            why="session_bias_volatility_out_of_range",
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
            why="session_bias_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(session_high - atr_now * cfg.stop_atr_mult, ema_fast - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(session_low + atr_now * cfg.stop_atr_mult, ema_fast + atr_now * cfg.trail_atr_mult, high)

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
        long_scale_in = progress >= cfg.scale_in_progress_min and bias_long and price > session_high
        long_retest_add = (
            low <= session_high
            and price >= session_high + atr_now * cfg.reclaim_atr_min
            and bias_long
        )
        long_reduce = failed_long_break

    if in_short and can_add_more and pos["avg_entry"] > 0:
        move_to_tp = max(pos["avg_entry"] - short_tp, 1e-9)
        progress = (pos["avg_entry"] - price) / move_to_tp if move_to_tp > 0 else 0.0
        short_scale_in = progress >= cfg.scale_in_progress_min and bias_short and price < session_low
        short_retest_add = (
            high >= session_low
            and price <= session_low - atr_now * cfg.reclaim_atr_min
            and bias_short
        )
        short_reduce = failed_short_break

    if bias_long and long_break and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0)
        confidence = min(0.86 if long_beam else 0.70, 0.52 + bias_strength * 0.40)
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="session_bias_long",
            skill="long_beam" if long_beam else "session_breakout",
            confidence=confidence,
            tags=["session", session_name, "long"],
            indicators=indicators,
        )

    if bias_short and short_break and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0)
        confidence = min(0.80 if short_beam else 0.64, 0.46 + bias_strength * 0.36)
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="session_bias_short",
            skill="short_beam" if short_beam else "session_breakout",
            confidence=confidence,
            tags=["session", session_name, "short"],
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
            why="session_bias_long_scale_in",
            skill="scale_in",
            confidence=0.66,
            tags=["session", session_name, "scale_in", "long"],
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
            why="session_bias_long_retest_add",
            skill="retest_add",
            confidence=0.62,
            tags=["session", session_name, "retest_add", "long"],
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
            why="session_bias_short_scale_in",
            skill="scale_in",
            confidence=0.58,
            tags=["session", session_name, "scale_in", "short"],
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
            why="session_bias_short_retest_add",
            skill="retest_add",
            confidence=0.54,
            tags=["session", session_name, "retest_add", "short"],
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
            why="session_bias_failed_long_break_reduce",
            skill="failed_break_reduce",
            confidence=0.70,
            tags=["session", session_name, "failed_break", "reduce", "long"],
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
            why="session_bias_failed_short_break_reduce",
            skill="failed_break_reduce",
            confidence=0.66,
            tags=["session", session_name, "failed_break", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "session_bias_no_setup"
    if bias_long and not long_break:
        hold_reason = "session_long_bias_without_breakout"
    elif bias_short and not short_break:
        hold_reason = "session_short_bias_without_breakout"
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


class SessionBiasLBotStrategy(LBotStrategyBase):
    strategy_name = "session_bias"

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

        tz_name = _payload_session_tz(payload, SessionBiasConfig())

        result = strategy(
            df,
            state=state,
            risk_action=str(getattr(ctx.risk, "action", "hold") or "hold"),
            config=SessionBiasConfig(),
            session_tz=tz_name,
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "session_bias_no_reason")
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
