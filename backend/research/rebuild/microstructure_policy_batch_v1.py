from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild.policy_kernel_v1 import (
    DecisionIntent, atr, digest, ema, f, hold_intent, risk_geometry, ts,
    validate_authority, validate_bars,
)

FIVE_MIN_MS = 300_000


@dataclass(frozen=True)
class MicroPolicyConfig:
    timeframe_ms: int = FIVE_MIN_MS
    atr_len: int = 14
    lookback: int = 20
    volume_lookback: int = 20
    max_stale_intervals: int = 2
    risk_fraction_of_equity: float = 0.0035
    max_notional_fraction_of_equity: float = 0.10
    min_cost_budget_ratio: float = 1.25
    timeout_bars: int = 18

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
    "liquidity_sweep": (
        "HIST_R7_LIQUIDITY_SWEEP",
        "DOI_10.1111_JFIR.12317",
        "ARXIV_2602.00776",
        "BINGX_FEE_SCHEDULE",
    ),
    "scalp_snap": (
        "HIST_R7_SCALP_SNAP",
        "ARXIV_2012.12555",
        "ARXIV_2602.00776",
        "BINGX_FEE_SCHEDULE",
    ),
    "vol_spike_fade": (
        "HIST_R7_VOL_SPIKE_FADE",
        "ARXIV_2607.09426",
        "DOI_10.1002_FUT.22305",
        "BINGX_FEE_SCHEDULE",
    ),
}


def _fresh(signal_ts: int, now_ts_ms: int, cfg: MicroPolicyConfig) -> bool:
    return 0 <= int(now_ts_ms) - int(signal_ts) <= cfg.max_stale_intervals * cfg.timeframe_ms


def _snapshot(strategy_id: str, symbol: str, bars: Sequence[Mapping[str, Any]], now_ts_ms: int,
              close: float, a: float, values: Mapping[str, Any], cfg: MicroPolicyConfig) -> FeatureSnapshot:
    signal_ts = ts(bars[-1])
    body = {"strategy_id": strategy_id, "symbol": symbol, "signal_ts": signal_ts,
            "close": close, "atr": a, "values": values}
    return FeatureSnapshot(strategy_id, symbol, signal_ts, _fresh(signal_ts, now_ts_ms, cfg),
                           close, a, values, digest(body))


def compute_liquidity_sweep_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str,
                                    now_ts_ms: int, config: MicroPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or MicroPolicyConfig()
    validate_bars(bars, minimum=max(32, cfg.lookback + cfg.atr_len + 2))
    a = atr(bars, cfg.atr_len)
    last = bars[-1]
    prev = bars[-2]
    close = f(last, "close")
    high = f(last, "high")
    low = f(last, "low")
    open_ = f(last, "open")
    hist = bars[-(cfg.lookback + 1):-1]
    swing_high = max(f(x, "high") for x in hist)
    swing_low = min(f(x, "low") for x in hist)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    upper_sweep = high > swing_high and close < swing_high and upper_wick >= 0.35 * a
    lower_sweep = low < swing_low and close > swing_low and lower_wick >= 0.35 * a
    prev_close = f(prev, "close")
    values = {
        "upper_sweep": upper_sweep,
        "lower_sweep": lower_sweep,
        "short_reclaim": close < prev_close - 0.10 * a,
        "long_reclaim": close > prev_close + 0.10 * a,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "wick_atr": max(upper_wick, lower_wick) / max(a, 1e-12),
    }
    return _snapshot("liquidity_sweep", symbol, bars, now_ts_ms, close, a, values, cfg)


def compute_scalp_snap_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str,
                               now_ts_ms: int, config: MicroPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or MicroPolicyConfig()
    validate_bars(bars, minimum=max(32, cfg.volume_lookback + cfg.atr_len + 3))
    a = atr(bars, cfg.atr_len)
    close = f(bars[-1], "close")
    c2 = f(bars[-2], "close")
    c3 = f(bars[-3], "close")
    move1 = c2 - c3
    move2 = close - c2
    volumes = [max(0.0, f(x, "volume")) for x in bars[-(cfg.volume_lookback + 1):-1]]
    vol_ma = sum(volumes) / max(1, len(volumes))
    vol_now = max(0.0, f(bars[-1], "volume"))
    snap_long = move1 <= -0.90 * a and move2 >= 0.40 * a
    snap_short = move1 >= 0.90 * a and move2 <= -0.40 * a
    values = {
        "snap_long": snap_long,
        "snap_short": snap_short,
        "drive_atr": abs(move1) / max(a, 1e-12),
        "reversal_atr": abs(move2) / max(a, 1e-12),
        "volume_ratio": vol_now / max(vol_ma, 1e-12),
    }
    return _snapshot("scalp_snap", symbol, bars, now_ts_ms, close, a, values, cfg)


def compute_vol_spike_fade_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str,
                                   now_ts_ms: int, config: MicroPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or MicroPolicyConfig()
    validate_bars(bars, minimum=max(40, cfg.volume_lookback + cfg.atr_len + 3))
    a = atr(bars, cfg.atr_len)
    close = f(bars[-1], "close")
    open_ = f(bars[-1], "open")
    high = f(bars[-1], "high")
    low = f(bars[-1], "low")
    rng = max(high - low, 1e-12)
    body_atr = abs(close - open_) / max(a, 1e-12)
    volumes = [max(0.0, f(x, "volume")) for x in bars[-(cfg.volume_lookback + 1):-1]]
    vol_ma = sum(volumes) / max(1, len(volumes))
    vol_now = max(0.0, f(bars[-1], "volume"))
    closes = [f(x, "close") for x in bars]
    trend = ema(closes, 20)
    up_peak = close > open_ and body_atr >= 0.75 and (high - close) / rng <= 0.35
    down_peak = close < open_ and body_atr >= 0.75 and (close - low) / rng <= 0.35
    values = {
        "short_fade": vol_now >= 2.0 * max(vol_ma, 1e-12) and up_peak,
        "long_fade": vol_now >= 2.0 * max(vol_ma, 1e-12) and down_peak,
        "volume_ratio": vol_now / max(vol_ma, 1e-12),
        "body_atr": body_atr,
        "trend_stretch_atr": abs(close - trend[-1]) / max(a, 1e-12),
    }
    return _snapshot("vol_spike_fade", symbol, bars, now_ts_ms, close, a, values, cfg)


def _build(feature: FeatureSnapshot, *, policy_source_sha: str, verified_round_trip_cost_bps: float,
           config: MicroPolicyConfig | None = None) -> DecisionIntent:
    cfg = config or MicroPolicyConfig()
    validate_authority(policy_source_sha=policy_source_sha,
                       verified_round_trip_cost_bps=verified_round_trip_cost_bps)
    sid = feature.strategy_id
    if sid not in EVIDENCE:
        raise ValueError("UNKNOWN_STRATEGY")
    schema = f"zel.{sid}.policy.v1"
    entry_rule = {
        "liquidity_sweep": "closed_bar_prior_extreme_sweep_and_reclaim",
        "scalp_snap": "closed_bar_impulse_reversal_with_volume_confirmation",
        "vol_spike_fade": "closed_bar_volume_spike_exhaustion_fade",
    }[sid]
    if not feature.fresh:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization="signal_quality_clipped_0_1", regime="NO_TRADE_STALE",
                           reasons=("STALE_SOURCE_FAIL_CLOSED",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)
    v = feature.values
    if sid == "liquidity_sweep":
        long_ok = bool(v["lower_sweep"] and v["long_reclaim"])
        short_ok = bool(v["upper_sweep"] and v["short_reclaim"])
        strength = min(1.0, float(v["wick_atr"]) / 1.5)
        regime = "STOP_SWEEP_RECLAIM"
    elif sid == "scalp_snap":
        long_ok = bool(v["snap_long"] and float(v["volume_ratio"]) >= 1.15)
        short_ok = bool(v["snap_short"] and float(v["volume_ratio"]) >= 1.15)
        strength = min(1.0, 0.5 * float(v["drive_atr"]) + 0.5 * float(v["reversal_atr"]))
        regime = "IMPULSE_REVERSAL_SNAP"
    else:
        long_ok = bool(v["long_fade"] and float(v["trend_stretch_atr"]) <= 5.0)
        short_ok = bool(v["short_fade"] and float(v["trend_stretch_atr"]) <= 5.0)
        strength = min(1.0, 0.25 * float(v["volume_ratio"]) + 0.25 * float(v["body_atr"]))
        regime = "VOLUME_EXHAUSTION_FADE"

    if long_ok == short_ok:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization="signal_quality_clipped_0_1", regime="NO_TRADE",
                           reasons=("NO_UNAMBIGUOUS_ENTRY",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)
    side = "long" if long_ok else "short"
    entry = feature.close
    stop = entry - 1.25 * feature.atr if side == "long" else entry + 1.25 * feature.atr
    notional, risk_distance_bps = risk_geometry(entry=entry, stop=stop,
                                                 risk_fraction=cfg.risk_fraction_of_equity,
                                                 exposure_cap=cfg.max_notional_fraction_of_equity)
    move_budget_bps = 2.0 * risk_distance_bps
    ratio = move_budget_bps / verified_round_trip_cost_bps
    if ratio < cfg.min_cost_budget_ratio:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization="signal_quality_clipped_0_1", regime="NO_TRADE_COST",
                           reasons=("STRUCTURAL_COST_BUDGET_BELOW_MIN",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)
    return DecisionIntent(
        schema_version=schema, strategy_id=sid, source_sha=policy_source_sha, config_sha=cfg.sha,
        feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid], symbol=feature.symbol, side=side,
        signal_ts=feature.signal_ts, entry_rule=entry_rule, entry_strength=strength,
        strength_normalization="signal_quality_clipped_0_1", regime=regime, no_trade=False,
        invalidation={"initial_stop": stop, "hard_no_adverse_add": True},
        risk_size={"risk_fraction_of_equity": cfg.risk_fraction_of_equity,
                   "risk_distance_bps": risk_distance_bps},
        exposure={"notional_fraction_of_equity": notional, "cap": cfg.max_notional_fraction_of_equity},
        sl=stop, tp=None, timeout={"bars": cfg.timeout_bars}, partial={"enabled": False},
        trailing={"enabled": False}, runner={"enabled": False},
        pyramiding={"enabled": False, "adverse_add": False},
        cooldown={"bars": 3, "one_entry_per_transition": True},
        turnover={"duplicate_transition_forbidden": True, "max_new_entries_per_bar": 1},
        reason_codes=("ENTRY_POLICY_PASS",),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=move_budget_bps, cost_budget_ratio=ratio,
    )


def build_liquidity_sweep_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "liquidity_sweep":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


def build_scalp_snap_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "scalp_snap":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


def build_vol_spike_fade_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "vol_spike_fade":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)
