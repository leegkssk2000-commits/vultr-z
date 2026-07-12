from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "scalp_snap"

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
class ScalpSnapConfig:
    atr_len: int = 10
    ema_fast_len: int = 9
    ema_slow_len: int = 21
    vol_ma_len: int = 20
    min_bars: int = 40

    min_atr_pct: float = 0.12
    max_atr_pct: float = 4.20

    snap_drive_atr: float = 1.15
    snap_reversal_atr: float = 0.52
    beam_drive_atr: float = 1.60
    beam_reversal_atr: float = 0.78

    reclaim_atr_min: float = 0.18
    max_chase_dist_atr: float = 1.10
    fake_snap_reject_atr: float = 0.24

    stop_atr_mult: float = 0.72
    trail_atr_mult: float = 0.55
    base_rr: float = 1.10
    beam_rr: float = 1.55

    long_base_size: float = 0.28
    short_base_size: float = 0.22
    beam_bonus_long: float = 0.10
    beam_bonus_short: float = 0.08

    retest_add_size_long: float = 0.12
    retest_add_size_short: float = 0.10
    reduce_size_long: float = 0.20
    reduce_size_short: float = 0.18

    max_add_count: int = 1
    max_pyramiding: int = 1

    beam_body_ratio_min: float = 0.48
    beam_close_location_min: float = 0.64
    vol_mult: float = 1.25


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
    config: Optional[ScalpSnapConfig] = None,
) -> Dict[str, Any]:
    cfg = config or ScalpSnapConfig()

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
            why="scalp_snap_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.atr_len + 5, cfg.ema_slow_len + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="scalp_snap_not_enough_bars",
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
    df["vol_ma"] = df["volume"].rolling(cfg.vol_ma_len, min_periods=cfg.vol_ma_len).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    price = _to_float(last["close"])
    open_ = _to_float(last["open"])
    high = _to_float(last["high"])
    low = _to_float(last["low"])

    atr_now = _to_float(last["atr"])
    ema_fast = _to_float(last["ema_fast"])
    ema_slow = _to_float(last["ema_slow"])
    ema_fast_prev = _to_float(prev["ema_fast"])
    ema_slow_prev = _to_float(prev["ema_slow"])
    vol_now = _to_float(last["volume"])
    vol_ma = _to_float(last["vol_ma"], 1.0)

    if min(price, atr_now, ema_fast, ema_slow) <= 0:
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="scalp_snap_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    close_3 = _to_float(prev2["close"])
    close_2 = _to_float(prev["close"])
    move1 = close_2 - close_3
    move2 = price - close_2

    drive_atr = abs(move1) / max(atr_now, 1e-9)
    reversal_atr = abs(move2) / max(atr_now, 1e-9)
    atr_pct = (atr_now / max(price, 1e-9)) * 100.0
    body_ratio = _body_ratio(open_, price, low, high)
    close_loc = _close_location(price, low, high)
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)

    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev

    spike_ok = vol_now >= vol_ma * cfg.vol_mult if vol_ma > 0 else True
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct

    snap_short = (
        move1 > atr_now * cfg.snap_drive_atr
        and move2 < -atr_now * cfg.snap_reversal_atr
        and price < open_
    )
    snap_long = (
        move1 < -atr_now * cfg.snap_drive_atr
        and move2 > atr_now * cfg.snap_reversal_atr
        and price > open_
    )

    reclaim_short = price < close_2 - atr_now * cfg.reclaim_atr_min
    reclaim_long = price > close_2 + atr_now * cfg.reclaim_atr_min

    short_beam = (
        snap_short
        and drive_atr >= cfg.beam_drive_atr
        and reversal_atr >= cfg.beam_reversal_atr
        and body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )
    long_beam = (
        snap_long
        and drive_atr >= cfg.beam_drive_atr
        and reversal_atr >= cfg.beam_reversal_atr
        and body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )

    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr

    failed_long_snap = prev["close"] > prev["open"] and price < close_2 - atr_now * cfg.fake_snap_reject_atr
    failed_short_snap = prev["close"] < prev["open"] and price > close_2 + atr_now * cfg.fake_snap_reject_atr

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
        "move1": round(move1, 6),
        "move2": round(move2, 6),
        "drive_atr": round(drive_atr, 6),
        "reversal_atr": round(reversal_atr, 6),
        "snap_long": snap_long,
        "snap_short": snap_short,
        "reclaim_long": reclaim_long,
        "reclaim_short": reclaim_short,
        "body_ratio": round(body_ratio, 6),
        "close_location": round(close_loc, 6),
        "vol_now": round(vol_now, 6),
        "vol_ma": round(vol_ma, 6),
        "spike_ok": spike_ok,
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
        "late_chase_block": late_chase_block,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "failed_long_snap": failed_long_snap,
        "failed_short_snap": failed_short_snap,
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
            why="scalp_snap_volatility_out_of_range",
            skill="none",
            confidence=0.0,
            tags=["volatility_gate"],
            indicators=indicators,
        )

    if not spike_ok and (snap_long or snap_short):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="scalp_snap_volume_not_confirmed",
            skill="none",
            confidence=0.0,
            tags=["volume_gate"],
            indicators=indicators,
        )

    if late_chase_block and (snap_long or snap_short):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=price,
            sl=price,
            tp=price,
            pyramiding=cfg.max_pyramiding,
            why="scalp_snap_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = min(price - atr_now * cfg.stop_atr_mult, ema_fast - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(price + atr_now * cfg.stop_atr_mult, ema_fast + atr_now * cfg.trail_atr_mult, high)

    long_risk = max(price - long_sl, atr_now * 0.25)
    short_risk = max(short_sl - price, atr_now * 0.25)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_retest_add = False
    short_retest_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more:
        long_retest_add = reclaim_long and price > ema_fast and snap_long
        long_reduce = failed_long_snap

    if in_short and can_add_more:
        short_retest_add = reclaim_short and price < ema_fast and snap_short
        short_reduce = failed_short_snap

    if snap_long and reclaim_long and not in_long and not in_short:
        size = cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0)
        conf = 0.84 if long_beam else 0.68
        return _build_result(
            side="long",
            action="enter",
            size=size,
            entry=price,
            sl=long_sl,
            tp=long_tp,
            pyramiding=cfg.max_pyramiding,
            why="scalp_snap_long",
            skill="long_beam" if long_beam else "snap_reversal",
            confidence=conf,
            tags=["scalp", "snap", "long"],
            indicators=indicators,
        )

    if snap_short and reclaim_short and not in_long and not in_short:
        size = cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0)
        conf = 0.80 if short_beam else 0.64
        return _build_result(
            side="short",
            action="enter",
            size=size,
            entry=price,
            sl=short_sl,
            tp=short_tp,
            pyramiding=cfg.max_pyramiding,
            why="scalp_snap_short",
            skill="short_beam" if short_beam else "snap_reversal",
            confidence=conf,
            tags=["scalp", "snap", "short"],
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
            why="scalp_snap_long_retest_add",
            skill="retest_add",
            confidence=0.60,
            tags=["scalp", "snap", "retest_add", "long"],
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
            why="scalp_snap_short_retest_add",
            skill="retest_add",
            confidence=0.56,
            tags=["scalp", "snap", "retest_add", "short"],
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
            why="scalp_snap_failed_long_reduce",
            skill="failed_snap_reduce",
            confidence=0.68,
            tags=["scalp", "snap", "failed", "reduce", "long"],
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
            why="scalp_snap_failed_short_reduce",
            skill="failed_snap_reduce",
            confidence=0.64,
            tags=["scalp", "snap", "failed", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "scalp_snap_no_setup"
    if snap_long and not reclaim_long:
        hold_reason = "snap_long_without_reclaim"
    elif snap_short and not reclaim_short:
        hold_reason = "snap_short_without_reclaim"
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


class ScalpSnapLBotStrategy(LBotStrategyBase):
    strategy_name = "scalp_snap"

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
            config=ScalpSnapConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "scalp_snap_no_reason")
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
