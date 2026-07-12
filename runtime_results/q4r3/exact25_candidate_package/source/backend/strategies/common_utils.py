from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


EPS = 1e-9


# -------------------------
# low-level helpers
# -------------------------
def to_float(v: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    if abs(float(b)) <= EPS:
        return default
    return float(a) / float(b)


def ensure_ohlcv(df: pd.DataFrame, require_volume: bool = False) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()

    out = df.copy()
    required = ["open", "high", "low", "close"]
    if require_volume:
        required.append("volume")

    for col in required:
        if col not in out.columns:
            return pd.DataFrame()
        out[col] = pd.to_numeric(out[col], errors="coerce")

    if "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)

    return out.dropna(subset=["open", "high", "low", "close"])


def clamp(v: float, low: float, high: float) -> float:
    return max(low, min(high, float(v)))


def round_dict(d: Mapping[str, Any], digits: int = 6) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (float, np.floating)):
            out[k] = round(float(v), digits)
        else:
            out[k] = v
    return out


# -------------------------
# classic indicators
# -------------------------
def sma(series: pd.Series, length: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rolling(length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def wma(series: pd.Series, length: int) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    weights = np.arange(1, length + 1, dtype=float)

    def _wavg(x: np.ndarray) -> float:
        return float(np.dot(x, weights) / weights.sum())

    return series.rolling(length, min_periods=length).apply(_wavg, raw=True)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    df = ensure_ohlcv(df, require_volume=False)
    if df.empty:
        return pd.Series(dtype=float)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(length, min_periods=length).mean()


def atr_rma(df: pd.DataFrame, length: int = 14) -> pd.Series:
    df = ensure_ohlcv(df, require_volume=False)
    if df.empty:
        return pd.Series(dtype=float)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def bollinger(series: pd.Series, length: int = 20, mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    series = pd.to_numeric(series, errors="coerce")
    ma = series.rolling(length, min_periods=length).mean()
    std = series.rolling(length, min_periods=length).std(ddof=0)
    upper = ma + std * mult
    lower = ma - std * mult
    return ma, upper, lower


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    series = pd.to_numeric(series, errors="coerce")
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta.clip(upper=0.0))

    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / (avg_loss + EPS)
    return 100.0 - (100.0 / (1.0 + rs))


def mfi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    df = ensure_ohlcv(df, require_volume=True)
    if df.empty:
        return pd.Series(dtype=float)

    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    raw = tp * df["volume"]
    pos = raw.where(tp > tp.shift(1), 0.0)
    neg = raw.where(tp < tp.shift(1), 0.0)
    pos_sum = pos.rolling(length, min_periods=length).sum()
    neg_sum = neg.rolling(length, min_periods=length).sum()
    mr = pos_sum / (neg_sum + EPS)
    return 100.0 - (100.0 / (1.0 + mr))


def obv(df: pd.DataFrame) -> pd.Series:
    df = ensure_ohlcv(df, require_volume=True)
    if df.empty:
        return pd.Series(dtype=float)

    direction = df["close"].diff().fillna(0.0).apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    return (direction * df["volume"]).cumsum()


def vwap(df: pd.DataFrame) -> pd.Series:
    df = ensure_ohlcv(df, require_volume=True)
    if df.empty:
        return pd.Series(dtype=float)

    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (tp * df["volume"]).cumsum()
    return cum_tp_vol / (cum_vol + EPS)


def donchian(df: pd.DataFrame, length: int = 20) -> Tuple[pd.Series, pd.Series, pd.Series]:
    df = ensure_ohlcv(df, require_volume=False)
    if df.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    upper = df["high"].rolling(length, min_periods=length).max()
    lower = df["low"].rolling(length, min_periods=length).min()
    mid = (upper + lower) / 2.0
    return upper, mid, lower


def keltner(df: pd.DataFrame, length: int = 20, mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    df = ensure_ohlcv(df, require_volume=False)
    if df.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    center = ema(df["close"], length)
    a = atr(df, length)
    upper = center + a * mult
    lower = center - a * mult
    return center, upper, lower


def supertrend(df: pd.DataFrame, length: int = 10, mult: float = 3.0) -> Tuple[pd.Series, pd.Series]:
    df = ensure_ohlcv(df, require_volume=False)
    if df.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    _atr = atr(df, length)
    hl2 = (df["high"] + df["low"]) / 2.0
    upperband = hl2 + mult * _atr
    lowerband = hl2 - mult * _atr

    st = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    if len(df) == 0:
        return st, direction

    st.iloc[0] = hl2.iloc[0]
    direction.iloc[0] = 1

    for i in range(1, len(df)):
        if df["close"].iloc[i] > upperband.iloc[i - 1]:
            direction.iloc[i] = 1
        elif df["close"].iloc[i] < lowerband.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

        if direction.iloc[i] == 1:
            prev_st = st.iloc[i - 1] if pd.notna(st.iloc[i - 1]) else lowerband.iloc[i]
            st.iloc[i] = max(lowerband.iloc[i], prev_st)
        else:
            prev_st = st.iloc[i - 1] if pd.notna(st.iloc[i - 1]) else upperband.iloc[i]
            st.iloc[i] = min(upperband.iloc[i], prev_st)

    return st, direction # direction: 1=상승, -1=하락


# -------------------------
# candle / structure helpers
# -------------------------
def body_ratio(open_: float, close: float, low: float, high: float) -> float:
    width = max(float(high) - float(low), EPS)
    return abs(float(close) - float(open_)) / width


def close_location(close: float, low: float, high: float) -> float:
    width = max(float(high) - float(low), EPS)
    return (float(close) - float(low)) / width


def wick_sizes(open_: float, close: float, low: float, high: float) -> Tuple[float, float]:
    upper = float(high) - max(float(open_), float(close))
    lower = min(float(open_), float(close)) - float(low)
    return upper, lower


def rolling_swing_high(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    df = ensure_ohlcv(df, require_volume=False)
    if df.empty:
        return pd.Series(dtype=float)
    return df["high"].rolling(lookback, min_periods=lookback).max()


def rolling_swing_low(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    df = ensure_ohlcv(df, require_volume=False)
    if df.empty:
        return pd.Series(dtype=float)
    return df["low"].rolling(lookback, min_periods=lookback).min()


def find_last_gap(df: pd.DataFrame, lookback: int = 30, min_gap_abs: float = 0.0) -> Dict[str, Any]:
    df = ensure_ohlcv(df, require_volume=False)
    if df.empty or len(df) < 2:
        return {
            "found": False,
            "idx": None,
            "dir": None,
            "gap_low": None,
            "gap_high": None,
            "gap_size": 0.0,
        }

    start_idx = max(1, len(df) - lookback)
    result = {
        "found": False,
        "idx": None,
        "dir": None,
        "gap_low": None,
        "gap_high": None,
        "gap_size": 0.0,
    }

    for i in range(start_idx, len(df)):
        hi_prev = to_float(df["high"].iloc[i - 1])
        lo_prev = to_float(df["low"].iloc[i - 1])
        hi_now = to_float(df["high"].iloc[i])
        lo_now = to_float(df["low"].iloc[i])

        up_gap = lo_now - hi_prev
        down_gap = lo_prev - hi_now

        if up_gap > min_gap_abs:
            result = {
                "found": True,
                "idx": i,
                "dir": "up",
                "gap_low": hi_prev,
                "gap_high": lo_now,
                "gap_size": up_gap,
            }
        elif down_gap > min_gap_abs:
            result = {
                "found": True,
                "idx": i,
                "dir": "down",
                "gap_low": hi_now,
                "gap_high": lo_prev,
                "gap_size": down_gap,
            }

    return result


# -------------------------
# strategy output normalization
# -------------------------
@dataclass
class StrategySignal:
    strategy: str
    symbol: str
    side: Optional[str]
    action: str
    size: float
    entry: float
    sl: float
    tp: float
    pyramiding: int
    why: str
    skill: str = "none"
    confidence: float = 0.0
    tags: Tuple[str, ...] = ()
    indicators: Dict[str, Any] | None = None
    raw: Dict[str, Any] | None = None


def normalize_side(side: Any) -> Optional[str]:
    if side is None:
        return None
    s = str(side).strip().lower()
    if s in ("long", "buy"):
        return "long"
    if s in ("short", "sell"):
        return "short"
    return None


def normalize_action(action: Any, side: Optional[str]) -> str:
    if action is None:
        return "enter" if side else "hold"

    a = str(action).strip().lower()
    mapping = {
        "buy": "enter",
        "sell": "enter",
        "entry": "enter",
        "open": "enter",
        "add": "add",
        "reduce": "reduce",
        "partial": "reduce",
        "close": "exit",
        "exit": "exit",
        "hold": "hold",
        "noop": "hold",
        "block": "hold",
    }
    return mapping.get(a, "enter" if side else "hold")


def normalize_strategy_output(
    strategy_name: str,
    symbol: str,
    output: Mapping[str, Any],
    snapshot_price: Optional[float] = None,
) -> StrategySignal:
    raw = dict(output or {})
    side = normalize_side(raw.get("side"))
    action = normalize_action(raw.get("action"), side)

    fallback_price = to_float(snapshot_price)
    entry = to_float(raw.get("entry"), fallback_price)
    if entry <= 0:
        entry = fallback_price

    sl = to_float(raw.get("sl"), entry)
    tp = to_float(raw.get("tp"), entry)

    size = max(0.0, to_float(raw.get("size"), 0.0 if side is None else 1.0))
    pyramiding = int(raw.get("pyramiding", 0) or 0)
    why = str(raw.get("why") or "no_reason")
    skill = str(raw.get("skill") or "none")
    confidence = clamp(to_float(raw.get("confidence"), 0.0), 0.0, 1.0)

    tags_raw = raw.get("tags") or ()
    if isinstance(tags_raw, str):
        tags = (tags_raw,)
    elif isinstance(tags_raw, Sequence):
        tags = tuple(str(x) for x in tags_raw)
    else:
        tags = ()

    indicators_raw = raw.get("indicators") or {}
    indicators = dict(indicators_raw) if isinstance(indicators_raw, Mapping) else {}

    return StrategySignal(
        strategy=str(strategy_name),
        symbol=str(symbol),
        side=side,
        action=action,
        size=size,
        entry=entry,
        sl=sl,
        tp=tp,
        pyramiding=pyramiding,
        why=why,
        skill=skill,
        confidence=confidence,
        tags=tags,
        indicators=indicators,
        raw=raw,
    )


def signal_to_legacy_dict(sig: StrategySignal) -> Dict[str, Any]:
    return {
        "side": sig.side,
        "action": sig.action,
        "size": float(sig.size),
        "entry": float(sig.entry),
        "sl": float(sig.sl),
        "tp": float(sig.tp),
        "pyramiding": int(sig.pyramiding),
        "why": sig.why,
        "skill": sig.skill,
        "confidence": float(sig.confidence),
        "tags": list(sig.tags),
        "indicators": sig.indicators or {},
        "raw": sig.raw or {},
    }


def make_hold(
    strategy_name: str,
    symbol: str,
    price: float = 0.0,
    why: str = "hold",
    *,
    pyramiding: int = 0,
    tags: Optional[Sequence[str]] = None,
    indicators: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return signal_to_legacy_dict(
        StrategySignal(
            strategy=strategy_name,
            symbol=symbol,
            side=None,
            action="hold",
            size=0.0,
            entry=float(price),
            sl=float(price),
            tp=float(price),
            pyramiding=int(pyramiding),
            why=why,
            skill="none",
            confidence=0.0,
            tags=tuple(tags or ("hold",)),
            indicators=dict(indicators or {}),
            raw={},
        )
    )


# -------------------------
# quick smoke test
# -------------------------
if __name__ == "__main__":
    rows = []
    price = 100.0
    for i in range(120):
        price += 0.12 if i < 80 else -0.05
        rows.append(
            {
                "open": price - 0.04,
                "high": price + 0.10,
                "low": price - 0.09,
                "close": price,
                "volume": 1000 + i * 5,
            }
        )

    df = pd.DataFrame(rows)

    print("ema tail:", ema(df["close"], 8).tail(3).tolist())
    print("atr tail:", atr(df, 14).tail(3).tolist())
    print("rsi tail:", rsi(df["close"], 14).tail(3).tolist())
    st, d = supertrend(df, 10, 3.0)
    print("supertrend tail:", st.tail(3).tolist(), d.tail(3).tolist())

    legacy = {
        "side": "long",
        "size": 0.4,
        "entry": float(df["close"].iloc[-1]),
        "sl": float(df["close"].iloc[-1] - 1.0),
        "tp": float(df["close"].iloc[-1] + 2.0),
        "why": "smoke_test",
    }
    print(normalize_strategy_output("common_utils_test", "BTCUSDT", legacy, snapshot_price=float(df["close"].iloc[-1])))
