from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, TypeVar

import pandas as pd

try:
    from backend.engine.lbot_models import DecisionContext, StrategyDecision, StrategyIntent
    from backend.engine.lbot_strategy_base import LBotStrategyBase
except Exception:
    class LBotStrategyBase:  # type: ignore
        strategy_name = "semantic_strategy"

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
            tags: Optional[list[str]] = None,
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


ConfigT = TypeVar("ConfigT")


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.astype(float).ewm(span=length, adjust=False, min_periods=length).mean()


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    true_range = pd.concat(
        (high - low, (high - prev_close).abs(), (low - prev_close).abs()),
        axis=1,
    ).max(axis=1)
    return true_range.rolling(length, min_periods=length).mean()


def rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100.0 - 100.0 / (1.0 + rs)


def mfi(df: pd.DataFrame, length: int) -> pd.Series:
    typical = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    flow = typical * df["volume"].astype(float)
    positive = flow.where(typical > typical.shift(1), 0.0)
    negative = flow.where(typical < typical.shift(1), 0.0)
    positive_sum = positive.rolling(length, min_periods=length).sum()
    negative_sum = negative.rolling(length, min_periods=length).sum()
    ratio = positive_sum / (negative_sum + 1e-9)
    return 100.0 - 100.0 / (1.0 + ratio)


def body_ratio(open_: float, close: float, low: float, high: float) -> float:
    return abs(close - open_) / max(high - low, 1e-9)


def close_location(close: float, low: float, high: float) -> float:
    return (close - low) / max(high - low, 1e-9)


def infer_position_state(state: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    value = dict(state or {})
    return {
        "position_side": str(value.get("position_side") or "").lower(),
        "position_qty": to_float(value.get("position_qty")),
        "avg_entry": to_float(value.get("avg_entry")),
        "add_count": int(value.get("add_count") or 0),
        "last_add_price": to_float(value.get("last_add_price")),
    }


def build_result(
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
    tags: list[str],
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
        "tags": list(tags),
        "indicators": dict(indicators),
    }


def invalid_result(why: str, pyramiding: int, *, tags: Optional[list[str]] = None) -> Dict[str, Any]:
    return build_result(
        side=None,
        action="hold",
        size=0.0,
        entry=0.0,
        sl=0.0,
        tp=0.0,
        pyramiding=pyramiding,
        why=why,
        skill="none",
        confidence=0.0,
        tags=tags or ["invalid_input"],
        indicators={},
    )


def prepare_ohlcv(df: pd.DataFrame, *, require_volume: bool = False) -> Optional[pd.DataFrame]:
    required = {"open", "high", "low", "close"}
    if require_volume:
        required.add("volume")
    if df is None or df.empty or not required.issubset(df.columns):
        return None
    out = df.copy()
    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    else:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    if out[["open", "high", "low", "close", "volume"]].isna().any().any():
        return None
    if (out[["open", "high", "low", "close"]] <= 0).any().any() or (out["volume"] < 0).any():
        return None
    return out


def payload_to_df(payload: Mapping[str, Any]) -> pd.DataFrame:
    for key in ("ohlcv", "candles", "bars", "df"):
        candidate = payload.get(key)
        if isinstance(candidate, pd.DataFrame):
            return candidate.copy()
        if isinstance(candidate, list) and candidate:
            frame = pd.DataFrame(candidate)
            if "timestamp" in frame.columns and "ts" not in frame.columns:
                frame["ts"] = frame["timestamp"]
            return frame
    return pd.DataFrame()


def decision_from_context(
    ctx: DecisionContext,
    strategy_fn: Callable[..., Dict[str, Any]],
    config: ConfigT,
    strategy_name: str,
) -> StrategyDecision:
    signal = getattr(ctx, "signal", None)
    payload = dict(getattr(signal, "payload", {}) or {})
    frame = payload_to_df(payload)
    state = {
        "position_side": payload.get("position_side") or payload.get("current_side"),
        "position_qty": payload.get("position_qty") or payload.get("qty"),
        "avg_entry": payload.get("avg_entry") or payload.get("entry_price"),
        "add_count": payload.get("add_count") or 0,
        "last_add_price": payload.get("last_add_price") or payload.get("avg_entry"),
    }
    risk = getattr(ctx, "risk", None)
    result = strategy_fn(
        frame,
        state=state,
        risk_action=str(getattr(risk, "action", "hold") or "hold"),
        config=config,
    )
    side = result.get("side")
    action = result.get("action")
    reason = str(result.get("why") or f"{strategy_name}_no_reason")
    confidence = to_float(result.get("confidence"))
    size = to_float(result.get("size"))
    entry = to_float(result.get("entry"))
    tags = list(result.get("tags") or [])

    if side == "long" and action in {"enter", "add"}:
        intent = StrategyIntent.ENTER_LONG
        target_qty = size
    elif side == "long" and action == "reduce":
        intent = StrategyIntent.REDUCE
        target_qty = size
    elif side == "short" and action in {"enter", "add", "reduce"}:
        intent = StrategyIntent.HOLD
        target_qty = 0.0
        confidence = 0.0
        reason = "short_signal_generated_but_core_is_long_only"
        tags.append("short_pending_core_upgrade")
    else:
        intent = StrategyIntent.HOLD
        target_qty = 0.0
        confidence = 0.0

    return StrategyDecision(
        ok=True,
        intent=intent,
        confidence=confidence,
        reason=reason,
        target_qty=target_qty,
        target_price=entry,
        tags=tags,
        payload={"legacy_signal": result},
    )


__all__ = [
    "DecisionContext",
    "LBotStrategyBase",
    "StrategyDecision",
    "StrategyIntent",
    "atr",
    "body_ratio",
    "build_result",
    "close_location",
    "decision_from_context",
    "ema",
    "infer_position_state",
    "invalid_result",
    "mfi",
    "payload_to_df",
    "prepare_ohlcv",
    "rsi",
    "to_float",
]
