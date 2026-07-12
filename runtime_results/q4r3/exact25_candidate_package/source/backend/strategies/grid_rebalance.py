from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd


try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase: # type: ignore
        strategy_name = "grid_rebalance"

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
class GridRebalanceConfig:
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    anchor_len: int = 96
    min_bars: int = 120

    grid_step_pct: float = 0.30
    atr_step_mult: float = 0.55

    min_atr_pct: float = 0.10
    max_atr_pct: float = 3.20

    long_trigger_k: float = -1.10
    short_trigger_k: float = 1.10
    beam_long_k: float = -1.80
    beam_short_k: float = 1.80

    reclaim_atr_min: float = 0.10
    max_chase_dist_atr: float = 2.40
    fail_anchor_break_atr: float = 0.35

    stop_grid_mult: float = 1.25
    base_rr: float = 1.30
    beam_rr: float = 1.75

    long_base_size: float = 0.26
    short_base_size: float = 0.18
    beam_bonus_long: float = 0.10
    beam_bonus_short: float = 0.08

    add_size_long: float = 0.12
    add_size_short: float = 0.08
    reduce_size_long: float = 0.22
    reduce_size_short: float = 0.18

    max_add_count: int = 3
    max_pyramiding: int = 4


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
    config: Optional[GridRebalanceConfig] = None,
) -> Dict[str, Any]:
    cfg = config or GridRebalanceConfig()

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
            why="grid_invalid_input",
            skill="none",
            confidence=0.0,
            tags=["invalid_input"],
            indicators={},
        )

    if len(df) < max(cfg.min_bars, cfg.anchor_len + 5, cfg.ema_slow_len + 5):
        return _build_result(
            side=None,
            action="hold",
            size=0.0,
            entry=0.0,
            sl=0.0,
            tp=0.0,
            pyramiding=cfg.max_pyramiding,
            why="grid_short",
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

    price = _to_float(last["close"])
    prev_close = _to_float(prev["close"])
    atr_now = _to_float(last["atr"])
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
            why="grid_indicator_nan",
            skill="none",
            confidence=0.0,
            tags=["indicator_nan"],
            indicators={},
        )

    anchor = _to_float(df["close"].tail(cfg.anchor_len).mean())
    step_abs_pct = price * (cfg.grid_step_pct / 100.0)
    grid_step = max(step_abs_pct, atr_now * cfg.atr_step_mult)

    distance = price - anchor
    k = distance / max(grid_step, 1e-9)
    atr_pct = atr_now / max(price, 1e-9) * 100.0

    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev

    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min

    long_setup = k <= cfg.long_trigger_k and long_reclaim and not trend_short
    short_setup = k >= cfg.short_trigger_k and short_reclaim and not trend_long

    long_beam = long_setup and k <= cfg.beam_long_k
    short_beam = short_setup and k >= cfg.beam_short_k

    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)
    late_chase_block = abs(k) > cfg.max_chase_dist_atr and dist_from_fast_atr > cfg.max_chase_dist_atr
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct

    failed_long = price < anchor - abs(cfg.long_trigger_k) * grid_step - atr_now * cfg.fail_anchor_break_atr
    failed_short = price > anchor + abs(cfg.short_trigger_k) * grid_step + atr_now * cfg.fail_anchor_break_atr

    pos = _infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "anchor": round(anchor, 6),
        "grid_step": round(grid_step, 6),
        "distance": round(distance, 6),
        "k": round(k, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "dist_from_fast_atr": round(dist_from_fast_atr, 6),
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
            why="grid_volatility_out_of_range",
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
            why="grid_late_chase_block",
            skill="none",
            confidence=0.0,
            tags=["late_chase_block"],
            indicators=indicators,
        )

    long_sl = price - grid_step * cfg.stop_grid_mult
    short_sl = price + grid_step * cfg.stop_grid_mult

    long_risk = max(price - long_sl, grid_step * 0.50)
    short_risk = max(short_sl - price, grid_step * 0.50)

    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    long_add = False
    short_add = False
    long_reduce = False
    short_reduce = False

    if in_long and can_add_more:
        long_add = k <= cfg.long_trigger_k - 0.60 and long_reclaim and not failed_long
        long_reduce = failed_long

    if in_short and can_add_more:
        short_add = k >= cfg.short_trigger_k + 0.60 and short_reclaim and not failed_short
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
            why=f"grid_long_k={k:.2f}",
            skill="long_beam" if long_beam else "grid_rebalance",
            confidence=0.78 if long_beam else 0.62,
            tags=["grid", "rebalance", "long"],
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
            why=f"grid_short_k={k:.2f}",
            skill="short_beam" if short_beam else "grid_rebalance",
            confidence=0.74 if short_beam else 0.58,
            tags=["grid", "rebalance", "short"],
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
            why="grid_long_add",
            skill="water_add",
            confidence=0.56,
            tags=["grid", "rebalance", "add", "long"],
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
            why="grid_short_add",
            skill="water_add",
            confidence=0.52,
            tags=["grid", "rebalance", "add", "short"],
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
            why="grid_failed_long_reduce",
            skill="failed_grid_reduce",
            confidence=0.66,
            tags=["grid", "rebalance", "failed", "reduce", "long"],
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
            why="grid_failed_short_reduce",
            skill="failed_grid_reduce",
            confidence=0.62,
            tags=["grid", "rebalance", "failed", "reduce", "short"],
            indicators=indicators,
        )

    hold_reason = "grid_no_setup"
    if k > 0 and k < cfg.short_trigger_k:
        hold_reason = "positive_k_but_not_stretched_enough"
    elif k < 0 and k > cfg.long_trigger_k:
        hold_reason = "negative_k_but_not_stretched_enough"
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


class GridRebalanceLBotStrategy(LBotStrategyBase):
    strategy_name = "grid_rebalance"

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
            config=GridRebalanceConfig(),
        )

        side = result.get("side")
        action = result.get("action")
        reason = str(result.get("why") or "grid_no_reason")
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
