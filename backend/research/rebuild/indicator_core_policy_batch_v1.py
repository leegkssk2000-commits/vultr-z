from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild.policy_kernel_v1 import (
    DecisionIntent,
    atr,
    digest,
    ema,
    f,
    hold_intent,
    risk_geometry,
    rsi,
    ts,
    validate_authority,
    validate_bars,
)

FIVE_MIN_MS = 300_000
SUPPORTED = ("alpha_combo", "ema_ribbon_scalp", "mfi_rsi_div", "obv_trend")


@dataclass(frozen=True)
class IndicatorCoreConfig:
    timeframe_ms: int = FIVE_MIN_MS
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_mid_len: int = 55
    ema_slow_len: int = 100
    breakout_lookback: int = 20
    divergence_lookback: int = 28
    volume_lookback: int = 34
    max_stale_intervals: int = 2
    risk_fraction_of_equity: float = 0.0035
    max_notional_fraction_of_equity: float = 0.10
    min_cost_budget_ratio: float = 1.25
    timeout_bars: int = 36

    @property
    def sha(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class FeatureSnapshot:
    strategy_id: str
    symbol: str
    signal_ts: int
    fresh: bool
    close: float
    atr: float
    values: Mapping[str, Any]
    feature_sha: str


EVIDENCE = {
    "alpha_combo": ("HIST_R7_ALPHA_COMBO", "SSRN_6272239", "PR405_COMPONENT_ABLATION", "BINGX_FEE_SCHEDULE"),
    "ema_ribbon_scalp": ("HIST_R7_EMA_RIBBON_SCALP", "SSRN_6272239", "BINGX_FEE_SCHEDULE"),
    "mfi_rsi_div": ("HIST_R7_MFI_RSI_DIV", "EVIDENCE_MOMENTUM_FAILURE", "BINGX_FEE_SCHEDULE"),
    "obv_trend": ("HIST_R7_OBV_TREND", "SSRN_6272239", "EVIDENCE_VOLUME_CONFIRMATION", "BINGX_FEE_SCHEDULE"),
}


def _fresh(signal_ts: int, now_ts_ms: int, cfg: IndicatorCoreConfig) -> bool:
    return 0 <= int(now_ts_ms) - int(signal_ts) <= cfg.max_stale_intervals * cfg.timeframe_ms


def _ema_now(closes: Sequence[float], length: int) -> float:
    return ema(closes, length)[-1]


def _money_flow_index(bars: Sequence[Mapping[str, Any]], length: int = 14) -> float:
    if len(bars) < length + 1:
        raise ValueError("MFI_WARMUP_INSUFFICIENT")
    selected = bars[-(length + 1):]
    pos = 0.0
    neg = 0.0
    prev_tp = None
    for bar in selected:
        tp = (f(bar, "high") + f(bar, "low") + f(bar, "close")) / 3.0
        volume = f(bar, "volume", positive=False)
        if volume < 0:
            raise ValueError("BAR_VOLUME_NEGATIVE")
        flow = tp * volume
        if prev_tp is not None:
            if tp > prev_tp:
                pos += flow
            elif tp < prev_tp:
                neg += flow
        prev_tp = tp
    if neg <= 1e-12:
        return 100.0
    ratio = pos / neg
    return 100.0 - 100.0 / (1.0 + ratio)


def _obv_series(bars: Sequence[Mapping[str, Any]]) -> list[float]:
    out = [0.0]
    for prev, cur in zip(bars[:-1], bars[1:]):
        delta = f(cur, "close") - f(prev, "close")
        volume = f(cur, "volume", positive=False)
        if volume < 0:
            raise ValueError("BAR_VOLUME_NEGATIVE")
        signed = volume if delta > 0 else (-volume if delta < 0 else 0.0)
        out.append(out[-1] + signed)
    return out


def _snapshot(strategy_id: str, symbol: str, bars: Sequence[Mapping[str, Any]], now_ts_ms: int,
              values: Mapping[str, Any], cfg: IndicatorCoreConfig) -> FeatureSnapshot:
    signal_ts = ts(bars[-1])
    close = f(bars[-1], "close")
    current_atr = atr(bars, cfg.atr_len)
    body = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "signal_ts": signal_ts,
        "close": close,
        "atr": current_atr,
        "values": values,
    }
    return FeatureSnapshot(
        strategy_id=strategy_id,
        symbol=symbol,
        signal_ts=signal_ts,
        fresh=_fresh(signal_ts, now_ts_ms, cfg),
        close=close,
        atr=current_atr,
        values=values,
        feature_sha=digest(body),
    )


def compute_feature(strategy_id: str, bars: Sequence[Mapping[str, Any]], *, symbol: str,
                    now_ts_ms: int, config: IndicatorCoreConfig | None = None) -> FeatureSnapshot:
    if strategy_id not in SUPPORTED:
        raise ValueError("UNSUPPORTED_STRATEGY")
    cfg = config or IndicatorCoreConfig()
    minimum = max(120, cfg.ema_slow_len + 5, cfg.divergence_lookback + 20, cfg.volume_lookback + 20)
    validate_bars(bars, minimum=minimum)
    closes = [f(x, "close") for x in bars]
    close = closes[-1]
    prev_close = closes[-2]
    current_atr = atr(bars, cfg.atr_len)
    ema_fast = _ema_now(closes, cfg.ema_fast_len)
    ema_mid = _ema_now(closes, cfg.ema_mid_len)
    ema_slow = _ema_now(closes, cfg.ema_slow_len)
    prev_ema_fast = ema(closes[:-1], cfg.ema_fast_len)[-1]
    prev_ema_mid = ema(closes[:-1], cfg.ema_mid_len)[-1]
    prev_ema_slow = ema(closes[:-1], cfg.ema_slow_len)[-1]
    atr_pct = current_atr / close * 100.0
    recent = bars[-(cfg.breakout_lookback + 1):-1]
    high_ref = max(f(x, "high") for x in recent)
    low_ref = min(f(x, "low") for x in recent)

    if strategy_id == "alpha_combo":
        rv = rsi(closes, 14)
        values = {
            "trend_long": close > ema_fast > ema_mid > ema_slow and ema_fast >= prev_ema_fast and ema_mid >= prev_ema_mid,
            "trend_short": close < ema_fast < ema_mid < ema_slow and ema_fast <= prev_ema_fast and ema_mid <= prev_ema_mid,
            "breakout_long": close > high_ref + current_atr * 0.10,
            "breakout_short": close < low_ref - current_atr * 0.10,
            "reclaim_long": close > prev_close + current_atr * 0.10,
            "reclaim_short": close < prev_close - current_atr * 0.10,
            "rsi": rv,
            "atr_pct": atr_pct,
            "dist_fast_atr": abs(close - ema_fast) / current_atr,
        }
    elif strategy_id == "ema_ribbon_scalp":
        e8 = _ema_now(closes, 8)
        e21 = _ema_now(closes, 21)
        e55 = _ema_now(closes, 55)
        p8 = ema(closes[:-1], 8)[-1]
        p21 = ema(closes[:-1], 21)[-1]
        body_atr = abs(close - f(bars[-1], "open")) / current_atr
        values = {
            "long_ribbon": close > e8 > e21 > e55 and e8 >= p8 and e21 >= p21,
            "short_ribbon": close < e8 < e21 < e55 and e8 <= p8 and e21 <= p21,
            "reclaim_long": close > prev_close + current_atr * 0.10,
            "reclaim_short": close < prev_close - current_atr * 0.10,
            "body_atr": body_atr,
            "atr_pct": atr_pct,
            "dist_e21_atr": abs(close - e21) / current_atr,
        }
    elif strategy_id == "mfi_rsi_div":
        look = cfg.divergence_lookback
        old = bars[-(look + 1):-1]
        old_closes = closes[-(look + 1):-1]
        rv = rsi(closes, 14)
        old_rv = rsi(closes[:-1], 14)
        mfi_now = _money_flow_index(bars, 14)
        mfi_prev = _money_flow_index(bars[:-1], 14)
        values = {
            "failed_low": f(bars[-1], "low") < min(f(x, "low") for x in old) and close > min(old_closes),
            "failed_high": f(bars[-1], "high") > max(f(x, "high") for x in old) and close < max(old_closes),
            "rsi": rv,
            "rsi_improving": rv > old_rv,
            "rsi_weakening": rv < old_rv,
            "mfi": mfi_now,
            "mfi_improving": mfi_now > mfi_prev,
            "mfi_weakening": mfi_now < mfi_prev,
            "atr_pct": atr_pct,
        }
    else:
        obv = _obv_series(bars)
        look = cfg.volume_lookback
        slope = obv[-1] - obv[-look]
        price_move = close - closes[-look]
        recent_volumes = [f(x, "volume", positive=False) for x in bars[-look:]]
        avg_volume = sum(recent_volumes) / len(recent_volumes)
        volume_ratio = recent_volumes[-1] / max(avg_volume, 1e-12)
        values = {
            "trend_long": close > ema_fast > ema_mid and ema_fast >= prev_ema_fast,
            "trend_short": close < ema_fast < ema_mid and ema_fast <= prev_ema_fast,
            "obv_slope": slope,
            "price_move": price_move,
            "volume_ratio": volume_ratio,
            "breakout_long": close > high_ref + current_atr * 0.08,
            "breakout_short": close < low_ref - current_atr * 0.08,
            "atr_pct": atr_pct,
        }
    return _snapshot(strategy_id, symbol, bars, now_ts_ms, values, cfg)


def _hold(snapshot: FeatureSnapshot, cfg: IndicatorCoreConfig, policy_source_sha: str,
          verified_round_trip_cost_bps: float, regime: str, reason: str) -> DecisionIntent:
    return hold_intent(
        strategy_id=snapshot.strategy_id,
        policy_schema="zel.decision_intent.v2",
        source_sha=policy_source_sha,
        config_sha=cfg.sha,
        feature_sha=snapshot.feature_sha,
        evidence_ids=EVIDENCE[snapshot.strategy_id],
        symbol=snapshot.symbol,
        signal_ts=snapshot.signal_ts,
        entry_rule=f"{snapshot.strategy_id}:closed_bar_feature_confirmation",
        strength_normalization="bounded_0_1",
        regime=regime,
        reasons=(reason,),
        verified_cost_bps=verified_round_trip_cost_bps,
        timeout_bars=cfg.timeout_bars,
        risk_fraction=cfg.risk_fraction_of_equity,
        exposure_cap=cfg.max_notional_fraction_of_equity,
    )


def build_intent(snapshot: FeatureSnapshot, *, policy_source_sha: str,
                 verified_round_trip_cost_bps: float,
                 config: IndicatorCoreConfig | None = None) -> DecisionIntent:
    cfg = config or IndicatorCoreConfig()
    validate_authority(policy_source_sha=policy_source_sha,
                       verified_round_trip_cost_bps=verified_round_trip_cost_bps)
    if snapshot.strategy_id not in SUPPORTED:
        raise ValueError("UNSUPPORTED_STRATEGY")
    if not snapshot.fresh:
        return _hold(snapshot, cfg, policy_source_sha, verified_round_trip_cost_bps, "STALE", "STALE_SOURCE")

    sid = snapshot.strategy_id
    v = snapshot.values
    side = "flat"
    strength = 0.0
    regime = "NO_TRADE"

    if sid == "alpha_combo":
        long_score = int(v["trend_long"]) * 2 + int(v["breakout_long"]) * 2 + int(v["reclaim_long"]) + int(52 <= v["rsi"] <= 74)
        short_score = int(v["trend_short"]) * 2 + int(v["breakout_short"]) * 2 + int(v["reclaim_short"]) + int(26 <= v["rsi"] <= 48)
        if 0.12 <= v["atr_pct"] <= 5.8 and v["dist_fast_atr"] <= 1.75 and long_score >= 5:
            side, strength, regime = "long", min(1.0, long_score / 6.0), "TREND_BREAKOUT_CONFLUENCE"
        elif 0.12 <= v["atr_pct"] <= 5.8 and v["dist_fast_atr"] <= 1.75 and short_score >= 5:
            side, strength, regime = "short", min(1.0, short_score / 6.0), "TREND_BREAKOUT_CONFLUENCE"
    elif sid == "ema_ribbon_scalp":
        if 0.12 <= v["atr_pct"] <= 4.8 and v["dist_e21_atr"] <= 1.10 and v["long_ribbon"] and v["reclaim_long"] and v["body_atr"] >= 0.55:
            side, strength, regime = "long", min(1.0, 0.5 + v["body_atr"] / 2.0), "RIBBON_IMPULSE"
        elif 0.12 <= v["atr_pct"] <= 4.8 and v["dist_e21_atr"] <= 1.10 and v["short_ribbon"] and v["reclaim_short"] and v["body_atr"] >= 0.55:
            side, strength, regime = "short", min(1.0, 0.5 + v["body_atr"] / 2.0), "RIBBON_IMPULSE"
    elif sid == "mfi_rsi_div":
        if 0.14 <= v["atr_pct"] <= 5.2 and v["failed_low"] and v["rsi"] <= 42 and v["mfi"] <= 45 and v["rsi_improving"] and v["mfi_improving"]:
            side, strength, regime = "long", min(1.0, 0.5 + (42-v["rsi"])/42.0), "PRICE_OSCILLATOR_DIVERGENCE"
        elif 0.14 <= v["atr_pct"] <= 5.2 and v["failed_high"] and v["rsi"] >= 58 and v["mfi"] >= 55 and v["rsi_weakening"] and v["mfi_weakening"]:
            side, strength, regime = "short", min(1.0, 0.5 + (v["rsi"]-58)/42.0), "PRICE_OSCILLATOR_DIVERGENCE"
    else:
        if 0.14 <= v["atr_pct"] <= 5.4 and v["trend_long"] and v["obv_slope"] > 0 and v["price_move"] > 0 and v["volume_ratio"] >= 1.12 and v["breakout_long"]:
            side, strength, regime = "long", min(1.0, 0.5 + (v["volume_ratio"]-1.0)), "OBV_CONFIRMED_BREAKOUT"
        elif 0.14 <= v["atr_pct"] <= 5.4 and v["trend_short"] and v["obv_slope"] < 0 and v["price_move"] < 0 and v["volume_ratio"] >= 1.12 and v["breakout_short"]:
            side, strength, regime = "short", min(1.0, 0.5 + (v["volume_ratio"]-1.0)), "OBV_CONFIRMED_BREAKOUT"

    if side == "flat":
        return _hold(snapshot, cfg, policy_source_sha, verified_round_trip_cost_bps, regime, "NO_QUALIFYING_SIGNAL")

    stop_mult = {"alpha_combo": 0.95, "ema_ribbon_scalp": 0.75, "mfi_rsi_div": 0.70, "obv_trend": 1.08}[sid]
    rr = {"alpha_combo": 2.10, "ema_ribbon_scalp": 1.65, "mfi_rsi_div": 2.20, "obv_trend": 2.10}[sid]
    stop = snapshot.close - snapshot.atr * stop_mult if side == "long" else snapshot.close + snapshot.atr * stop_mult
    risk = abs(snapshot.close - stop)
    tp = snapshot.close + risk * rr if side == "long" else snapshot.close - risk * rr
    notional, stop_bps = risk_geometry(
        entry=snapshot.close,
        stop=stop,
        risk_fraction=cfg.risk_fraction_of_equity,
        exposure_cap=cfg.max_notional_fraction_of_equity,
    )
    move_budget_bps = abs(tp - snapshot.close) / snapshot.close * 10_000.0
    cost_ratio = move_budget_bps / verified_round_trip_cost_bps
    if cost_ratio < cfg.min_cost_budget_ratio:
        return _hold(snapshot, cfg, policy_source_sha, verified_round_trip_cost_bps, regime, "COST_BUDGET_FAIL")

    return DecisionIntent(
        schema_version="zel.decision_intent.v2",
        strategy_id=sid,
        source_sha=policy_source_sha,
        config_sha=cfg.sha,
        feature_sha=snapshot.feature_sha,
        evidence_ids=EVIDENCE[sid],
        symbol=snapshot.symbol,
        side=side,
        signal_ts=snapshot.signal_ts,
        entry_rule=f"{sid}:closed_bar_feature_confirmation",
        entry_strength=float(strength),
        strength_normalization="bounded_0_1",
        regime=regime,
        no_trade=False,
        invalidation={"type": "structural_atr_stop", "atr_multiple": stop_mult},
        risk_size={"risk_fraction_of_equity": cfg.risk_fraction_of_equity, "stop_distance_bps": stop_bps},
        exposure={"notional_fraction_of_equity": notional, "cap": cfg.max_notional_fraction_of_equity},
        sl=stop,
        tp=tp,
        timeout={"bars": cfg.timeout_bars},
        partial={"enabled": False},
        trailing={"enabled": False},
        runner={"enabled": False},
        pyramiding={"enabled": False, "adverse_add": False},
        cooldown={"one_entry_per_transition": True},
        turnover={"duplicate_transition_forbidden": True},
        reason_codes=("QUALIFYING_SIGNAL",),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=move_budget_bps,
        cost_budget_ratio=cost_ratio,
    )
