from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

import math
import pandas as pd


EPS = 1e-9


@dataclass
class MarketRegime:
    regime: str
    htf_regime: str
    atr: float
    atr_pct: float
    adx: float
    volume_z: float
    vwap: float
    vwap_dev_atr: float
    ema20: float
    ema50: float
    ema200: float
    trend_slope_atr: float
    spread_bps: float
    funding_8h_pct: float
    oi_6h_pct: float
    data_penalty: float
    context_flags: tuple[str, ...]


def to_float(v: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(v):
            return default
        x = float(v)
        if not math.isfinite(x):
            return default
        return x
    except Exception:
        return default


def ensure_ohlcv(df: Any) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for c in ["open", "high", "low", "close"]:
        if c not in out.columns:
            return pd.DataFrame()
        out[c] = pd.to_numeric(out[c], errors="coerce")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
    return out.dropna(subset=["open", "high", "low", "close"])


def ema(s: pd.Series, n: int) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    df = ensure_ohlcv(df)
    if df.empty:
        return pd.Series(dtype=float)
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    d = s.diff()
    up = d.clip(lower=0.0)
    dn = -d.clip(upper=0.0)
    au = up.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = au / (ad + EPS)
    return 100.0 - 100.0 / (1.0 + rs)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    df = ensure_ohlcv(df)
    if df.empty:
        return pd.Series(dtype=float)
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = atr(df, n)
    plus_di = 100.0 * plus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / (tr + EPS)
    minus_di = 100.0 * minus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / (tr + EPS)
    dx = ((plus_di - minus_di).abs() / ((plus_di + minus_di) + EPS)) * 100.0
    return dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean()


def vwap(df: pd.DataFrame, window: int = 80) -> pd.Series:
    df = ensure_ohlcv(df)
    if df.empty:
        return pd.Series(dtype=float)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, 1.0)
    return (typical * vol).rolling(window, min_periods=min(20, window)).sum() / vol.rolling(window, min_periods=min(20, window)).sum()


def close_location(row: Mapping[str, Any]) -> float:
    h = to_float(row.get("high"))
    l = to_float(row.get("low"))
    c = to_float(row.get("close"))
    return (c - l) / max(h - l, EPS)


def body_ratio(row: Mapping[str, Any]) -> float:
    h = to_float(row.get("high"))
    l = to_float(row.get("low"))
    o = to_float(row.get("open"))
    c = to_float(row.get("close"))
    return abs(c - o) / max(h - l, EPS)


def wick_ratios(row: Mapping[str, Any]) -> Tuple[float, float]:
    h = to_float(row.get("high"))
    l = to_float(row.get("low"))
    o = to_float(row.get("open"))
    c = to_float(row.get("close"))
    rng = max(h - l, EPS)
    upper = (h - max(o, c)) / rng
    lower = (min(o, c) - l) / rng
    return upper, lower


def rolling_z(s: pd.Series, n: int = 50) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").fillna(0.0)
    m = s.rolling(n, min_periods=max(10, n // 4)).mean()
    sd = s.rolling(n, min_periods=max(10, n // 4)).std()
    return (s - m) / (sd + EPS)


def ctx_value(ctx: Optional[Mapping[str, Any]], *keys: str, default: float = 0.0) -> float:
    if not isinstance(ctx, Mapping):
        return default
    for k in keys:
        if k in ctx:
            return to_float(ctx.get(k), default)
    extra = ctx.get("extra") if isinstance(ctx.get("extra"), Mapping) else {}
    for k in keys:
        if k in extra:
            return to_float(extra.get(k), default)
    return default


def infer_regime(df: pd.DataFrame, market_context: Optional[Mapping[str, Any]] = None) -> MarketRegime:
    df = ensure_ohlcv(df)
    flags = []
    if len(df) < 220:
        flags.append("htf_proxy_limited_bars")

    if df.empty or len(df) < 80:
        return MarketRegime(
            regime="unknown", htf_regime="unknown", atr=0.0, atr_pct=0.0, adx=0.0, volume_z=0.0,
            vwap=0.0, vwap_dev_atr=0.0, ema20=0.0, ema50=0.0, ema200=0.0,
            trend_slope_atr=0.0, spread_bps=999.0, funding_8h_pct=0.0, oi_6h_pct=0.0,
            data_penalty=0.35, context_flags=("insufficient_bars",)
        )

    close = df["close"]
    price = to_float(close.iloc[-1])
    atr_s = atr(df, 14)
    atr_now = to_float(atr_s.iloc[-1])
    atr_pct = atr_now / max(price, EPS) * 100.0

    ema20_s = ema(close, 20)
    ema50_s = ema(close, 50)
    ema200_s = ema(close, 200)
    ema20_now = to_float(ema20_s.iloc[-1], price)
    ema50_now = to_float(ema50_s.iloc[-1], price)
    ema200_now = to_float(ema200_s.iloc[-1], price)

    adx_now = to_float(adx(df, 14).iloc[-1])
    vwap_now = to_float(vwap(df, 80).iloc[-1], price)
    vwap_dev_atr = (price - vwap_now) / max(atr_now, EPS)

    vol_z = to_float(rolling_z(df["volume"], 50).iloc[-1])
    slope = (ema50_now - to_float(ema50_s.iloc[-8], ema50_now)) / max(atr_now, EPS)

    spread_bps = ctx_value(market_context, "spread_bps", "spread", default=0.0)
    funding = ctx_value(market_context, "funding_8h_pct", "funding", default=0.0)
    oi6h = ctx_value(market_context, "oi_6h_pct", "open_interest_6h_pct", "oi", default=0.0)

    data_penalty = 0.0
    if not isinstance(market_context, Mapping):
        flags.append("external_context_missing")
        data_penalty += 0.06
    if spread_bps <= 0:
        flags.append("spread_missing")
        data_penalty += 0.03
    if funding == 0:
        flags.append("funding_missing_or_zero")
        data_penalty += 0.02
    if oi6h == 0:
        flags.append("oi_missing_or_zero")
        data_penalty += 0.02

    trend_up = price > ema50_now > ema200_now and slope > 0.08 and adx_now >= 18.0
    trend_down = price < ema50_now < ema200_now and slope < -0.08 and adx_now >= 18.0
    squeeze = atr_pct < 0.30 and adx_now < 18.0
    range_regime = adx_now < 22.0 and abs(vwap_dev_atr) < 2.4

    if trend_up:
        regime = "trend_up"
    elif trend_down:
        regime = "trend_down"
    elif squeeze:
        regime = "squeeze"
    elif range_regime:
        regime = "range"
    else:
        regime = "mixed"

    if price > ema50_now > ema200_now and slope > 0:
        htf = "trend_up"
    elif price < ema50_now < ema200_now and slope < 0:
        htf = "trend_down"
    elif adx_now < 20:
        htf = "range"
    else:
        htf = "mixed"

    return MarketRegime(
        regime=regime,
        htf_regime=htf,
        atr=atr_now,
        atr_pct=atr_pct,
        adx=adx_now,
        volume_z=vol_z,
        vwap=vwap_now,
        vwap_dev_atr=vwap_dev_atr,
        ema20=ema20_now,
        ema50=ema50_now,
        ema200=ema200_now,
        trend_slope_atr=slope,
        spread_bps=spread_bps,
        funding_8h_pct=funding,
        oi_6h_pct=oi6h,
        data_penalty=data_penalty,
        context_flags=tuple(flags),
    )


def rr(entry: float, sl: float, tp: float, side: str) -> float:
    entry = to_float(entry)
    sl = to_float(sl)
    tp = to_float(tp)
    if side == "long":
        risk = max(entry - sl, 0.0)
        reward = max(tp - entry, 0.0)
    elif side == "short":
        risk = max(sl - entry, 0.0)
        reward = max(entry - tp, 0.0)
    else:
        return 0.0
    return reward / max(risk, EPS)


def build_signal(
    strategy: str,
    side: Optional[str],
    action: str,
    entry: float,
    sl: float,
    tp: float,
    confidence: float,
    why: str,
    tags: list[str],
    indicators: Dict[str, Any],
    size: float = 0.10,
    pyramiding: int = 0,
    skill: str = "legendary",
) -> Dict[str, Any]:
    if not side or action not in {"enter", "add", "reduce"}:
        action = "hold"
        side = None
        size = 0.0

    return {
        "strategy": strategy,
        "side": side,
        "action": action,
        "size": float(size),
        "entry": float(entry or 0.0),
        "sl": float(sl or 0.0),
        "tp": float(tp or 0.0),
        "pyramiding": int(pyramiding),
        "why": str(why),
        "skill": skill,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "tags": list(tags),
        "indicators": indicators,
        "raw": {"legendary_rebuild": True},
    }


def gate_signal(sig: Dict[str, Any], min_rr: float = 1.45, min_conf: float = 0.62, max_spread_bps: float = 8.0) -> Dict[str, Any]:
    side = sig.get("side")
    action = sig.get("action")
    indicators = dict(sig.get("indicators") or {})
    tags = list(sig.get("tags") or [])
    reasons = []

    if action in {"enter", "add"}:
        r = rr(sig.get("entry", 0), sig.get("sl", 0), sig.get("tp", 0), str(side))
        indicators["rr"] = round(r, 6)
        spread = to_float(indicators.get("spread_bps"))
        if r < min_rr:
            reasons.append("rr_below_legendary_min")
        if to_float(sig.get("confidence")) < min_conf:
            reasons.append("confidence_below_legendary_min")
        if spread > max_spread_bps:
            reasons.append("spread_too_wide")
        if reasons:
            return build_signal(
                strategy=str(sig.get("strategy")),
                side=None,
                action="hold",
                entry=to_float(sig.get("entry")),
                sl=to_float(sig.get("sl")),
                tp=to_float(sig.get("tp")),
                confidence=0.0,
                why="legendary_gate_block:" + ",".join(reasons),
                tags=tags + ["legendary_gate_block"] + reasons,
                indicators=indicators,
                skill="blocked",
            )
        sig["indicators"] = indicators
        sig["tags"] = tags + ["legendary_gate_pass"]
    return sig
