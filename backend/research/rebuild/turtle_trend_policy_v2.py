from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence


STRATEGY_ID = "turtle_trend"
FEATURE_SCHEMA_VERSION = "zel.turtle_trend.features.v2"
POLICY_SCHEMA_VERSION = "zel.turtle_trend.policy.v2"
EVIDENCE_IDS = (
    "JFE_TSMOM_2012",
    "SSRN_6272239",
    "SFI_25_80_CRYPTO_TRENDS",
    "SSRN_3523005_TREND_COST",
    "BINGX_PERP_FEE_2025",
    "GITHUB_GABEKUTNER_TURTLE",
    "TRADINGVIEW_HYco13Su",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TurtleTrendPolicyConfig:
    timeframe_ms: int = 3_600_000
    donchian_entry_len: int = 20
    donchian_exit_len: int = 10
    atr_len: int = 20
    ema_fast_len: int = 20
    ema_slow_len: int = 55
    max_stale_intervals: int = 2
    risk_fraction_of_equity: float = 0.005
    max_notional_fraction_of_equity: float = 0.15
    initial_stop_atr: float = 2.0
    pyramid_step_atr: float = 0.5
    max_units: int = 4
    timeout_bars: int = 120
    min_cost_budget_ratio: float = 1.5
    move_budget_r_multiple: float = 2.0

    def validate(self) -> None:
        ints = {
            "timeframe_ms": self.timeframe_ms,
            "donchian_entry_len": self.donchian_entry_len,
            "donchian_exit_len": self.donchian_exit_len,
            "atr_len": self.atr_len,
            "ema_fast_len": self.ema_fast_len,
            "ema_slow_len": self.ema_slow_len,
            "max_stale_intervals": self.max_stale_intervals,
            "max_units": self.max_units,
            "timeout_bars": self.timeout_bars,
        }
        if any(v <= 0 for v in ints.values()):
            raise ValueError("CONFIG_POSITIVE_INTEGER_REQUIRED")
        if self.ema_fast_len >= self.ema_slow_len:
            raise ValueError("CONFIG_EMA_ORDER_INVALID")
        if not 0 < self.risk_fraction_of_equity <= 0.02:
            raise ValueError("CONFIG_RISK_FRACTION_INVALID")
        if not 0 < self.max_notional_fraction_of_equity <= 1:
            raise ValueError("CONFIG_EXPOSURE_CAP_INVALID")
        if self.initial_stop_atr <= 0 or self.pyramid_step_atr <= 0:
            raise ValueError("CONFIG_ATR_GEOMETRY_INVALID")
        if self.min_cost_budget_ratio < 1:
            raise ValueError("CONFIG_COST_BUDGET_INVALID")

    @property
    def warmup_bars(self) -> int:
        return max(
            self.ema_slow_len + 2,
            self.atr_len + 2,
            self.donchian_entry_len + 2,
            self.donchian_exit_len + 2,
        )

    @property
    def sha(self) -> str:
        return _sha(asdict(self))


@dataclass(frozen=True)
class FeatureSnapshot:
    schema_version: str
    symbol: str
    signal_ts: int
    timeframe_ms: int
    close: float
    atr: float
    atr_bps: float
    ema_fast: float
    ema_fast_prev: float
    ema_slow: float
    entry_high: float
    entry_low: float
    prev_entry_high: float
    prev_entry_low: float
    exit_high: float
    exit_low: float
    breakout_long: bool
    breakout_short: bool
    trend_long: bool
    trend_short: bool
    fresh: bool
    feature_sha: str


@dataclass(frozen=True)
class DecisionIntent:
    schema_version: str
    strategy_id: str
    source_sha: str
    config_sha: str
    feature_sha: str
    evidence_ids: tuple[str, ...]
    symbol: str
    side: str
    signal_ts: int
    entry_rule: str
    entry_strength: float
    strength_normalization: str
    regime: str
    no_trade: bool
    invalidation: Mapping[str, Any]
    risk_size: Mapping[str, Any]
    exposure: Mapping[str, Any]
    sl: float | None
    tp: float | None
    timeout: Mapping[str, Any]
    partial: Mapping[str, Any]
    trailing: Mapping[str, Any]
    runner: Mapping[str, Any]
    pyramiding: Mapping[str, Any]
    cooldown: Mapping[str, Any]
    turnover: Mapping[str, Any]
    reason_codes: tuple[str, ...]
    verified_round_trip_cost_bps: float
    move_budget_bps: float
    cost_budget_ratio: float

    @property
    def sha(self) -> str:
        return _sha(_jsonable(asdict(self)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(x) for x in value]
    if isinstance(value, list):
        return [_jsonable(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _float(bar: Mapping[str, Any], key: str) -> float:
    try:
        value = float(bar[key])
    except Exception as exc:
        raise ValueError(f"BAR_FIELD_INVALID:{key}") from exc
    if not (value == value) or value <= 0:
        raise ValueError(f"BAR_FIELD_NONPOSITIVE_OR_NAN:{key}")
    return value


def _ts(bar: Mapping[str, Any]) -> int:
    try:
        return int(bar["ts_ms"])
    except Exception as exc:
        raise ValueError("BAR_TS_INVALID") from exc


def _validate_bars(bars: Sequence[Mapping[str, Any]], cfg: TurtleTrendPolicyConfig) -> None:
    if len(bars) < cfg.warmup_bars:
        raise ValueError("WARMUP_INSUFFICIENT")
    last_ts = None
    for bar in bars:
        ts = _ts(bar)
        if last_ts is not None and ts <= last_ts:
            raise ValueError("BAR_TS_NON_MONOTONIC_OR_DUPLICATE")
        o, h, l, c = (_float(bar, k) for k in ("open", "high", "low", "close"))
        if h < max(o, c) or l > min(o, c) or h < l:
            raise ValueError("BAR_OHLC_INTEGRITY_FAIL")
        last_ts = ts


def _ema(values: Sequence[float], length: int) -> list[float]:
    alpha = 2.0 / (length + 1.0)
    out: list[float] = []
    current = values[0]
    out.append(current)
    for value in values[1:]:
        current = alpha * value + (1.0 - alpha) * current
        out.append(current)
    return out


def _true_ranges(bars: Sequence[Mapping[str, Any]]) -> list[float]:
    trs: list[float] = []
    prev_close: float | None = None
    for bar in bars:
        high = _float(bar, "high")
        low = _float(bar, "low")
        close = _float(bar, "close")
        tr = high - low if prev_close is None else max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    return trs


def _wilder_atr(trs: Sequence[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(trs)
    if len(trs) < length:
        return out
    current = sum(trs[:length]) / length
    out[length - 1] = current
    for idx in range(length, len(trs)):
        current = ((length - 1) * current + trs[idx]) / length
        out[idx] = current
    return out


def compute_feature_snapshot(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TurtleTrendPolicyConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TurtleTrendPolicyConfig()
    cfg.validate()
    _validate_bars(bars, cfg)
    closes = [_float(bar, "close") for bar in bars]
    highs = [_float(bar, "high") for bar in bars]
    lows = [_float(bar, "low") for bar in bars]
    fast = _ema(closes, cfg.ema_fast_len)
    slow = _ema(closes, cfg.ema_slow_len)
    atrs = _wilder_atr(_true_ranges(bars), cfg.atr_len)
    atr = atrs[-1]
    if atr is None or atr <= 0:
        raise ValueError("ATR_UNAVAILABLE")

    e = cfg.donchian_entry_len
    x = cfg.donchian_exit_len
    entry_high = max(highs[-e - 1 : -1])
    entry_low = min(lows[-e - 1 : -1])
    prev_entry_high = max(highs[-e - 2 : -2])
    prev_entry_low = min(lows[-e - 2 : -2])
    exit_high = max(highs[-x - 1 : -1])
    exit_low = min(lows[-x - 1 : -1])
    close = closes[-1]
    prev_close = closes[-2]
    signal_ts = _ts(bars[-1])
    fresh = 0 <= int(now_ts_ms) - signal_ts <= cfg.max_stale_intervals * cfg.timeframe_ms
    breakout_long = close > entry_high and prev_close <= prev_entry_high
    breakout_short = close < entry_low and prev_close >= prev_entry_low
    trend_long = close > fast[-1] > slow[-1] and fast[-1] > fast[-2]
    trend_short = close < fast[-1] < slow[-1] and fast[-1] < fast[-2]
    body = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "symbol": str(symbol),
        "signal_ts": signal_ts,
        "timeframe_ms": cfg.timeframe_ms,
        "close": close,
        "atr": float(atr),
        "atr_bps": float(atr / close * 10_000.0),
        "ema_fast": float(fast[-1]),
        "ema_fast_prev": float(fast[-2]),
        "ema_slow": float(slow[-1]),
        "entry_high": entry_high,
        "entry_low": entry_low,
        "prev_entry_high": prev_entry_high,
        "prev_entry_low": prev_entry_low,
        "exit_high": exit_high,
        "exit_low": exit_low,
        "breakout_long": breakout_long,
        "breakout_short": breakout_short,
        "trend_long": trend_long,
        "trend_short": trend_short,
        "fresh": fresh,
    }
    return FeatureSnapshot(feature_sha=_sha(body), **body)


def _hold_intent(
    feature: FeatureSnapshot,
    cfg: TurtleTrendPolicyConfig,
    source_sha: str,
    verified_round_trip_cost_bps: float,
    reasons: Iterable[str],
) -> DecisionIntent:
    return DecisionIntent(
        schema_version=POLICY_SCHEMA_VERSION,
        strategy_id=STRATEGY_ID,
        source_sha=source_sha,
        config_sha=cfg.sha,
        feature_sha=feature.feature_sha,
        evidence_ids=EVIDENCE_IDS,
        symbol=feature.symbol,
        side="flat",
        signal_ts=feature.signal_ts,
        entry_rule="closed_bar_donchian_transition_with_directional_structure",
        entry_strength=0.0,
        strength_normalization="breakout_distance_over_atr_clipped_0_3_then_divide_3",
        regime="NO_TRADE",
        no_trade=True,
        invalidation={"type": "none"},
        risk_size={"risk_fraction_of_equity": cfg.risk_fraction_of_equity},
        exposure={"notional_fraction_of_equity": 0.0, "cap": cfg.max_notional_fraction_of_equity},
        sl=None,
        tp=None,
        timeout={"bars": cfg.timeout_bars},
        partial={"enabled": False},
        trailing={"enabled": True, "type": "opposite_donchian_exit"},
        runner={"enabled": True},
        pyramiding={"enabled": True, "profitable_only": True, "max_units": cfg.max_units, "step_atr": cfg.pyramid_step_atr},
        cooldown={"duplicate_breakout_transition_forbidden": True},
        turnover={"one_entry_per_transition": True},
        reason_codes=tuple(reasons),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=0.0,
        cost_budget_ratio=0.0,
    )


def build_decision_intent(
    feature: FeatureSnapshot,
    *,
    policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: TurtleTrendPolicyConfig | None = None,
) -> DecisionIntent:
    cfg = config or TurtleTrendPolicyConfig()
    cfg.validate()
    if not policy_source_sha:
        raise ValueError("SOURCE_SHA_REQUIRED")
    if verified_round_trip_cost_bps <= 0:
        raise ValueError("VERIFIED_COST_AUTHORITY_REQUIRED")
    if not feature.fresh:
        return _hold_intent(feature, cfg, policy_source_sha, verified_round_trip_cost_bps, ["STALE_SOURCE_FAIL_CLOSED"])

    long_ok = feature.breakout_long and feature.trend_long
    short_ok = feature.breakout_short and feature.trend_short
    if long_ok == short_ok:
        reason = "NO_BREAKOUT_TRANSITION" if not long_ok else "AMBIGUOUS_SIDE_FAIL_CLOSED"
        return _hold_intent(feature, cfg, policy_source_sha, verified_round_trip_cost_bps, [reason])

    side = "long" if long_ok else "short"
    entry = feature.close
    atr = feature.atr
    stop = entry - cfg.initial_stop_atr * atr if side == "long" else entry + cfg.initial_stop_atr * atr
    stop_distance = abs(entry - stop)
    stop_fraction = stop_distance / entry
    notional_fraction = min(cfg.max_notional_fraction_of_equity, cfg.risk_fraction_of_equity / stop_fraction)
    risk_distance_bps = stop_fraction * 10_000.0
    move_budget_bps = risk_distance_bps * cfg.move_budget_r_multiple
    cost_budget_ratio = move_budget_bps / verified_round_trip_cost_bps
    breakout_distance = max(0.0, entry - feature.entry_high) if side == "long" else max(0.0, feature.entry_low - entry)
    strength = min(1.0, breakout_distance / max(atr, 1e-12) / 3.0)
    if cost_budget_ratio < cfg.min_cost_budget_ratio:
        return _hold_intent(
            feature,
            cfg,
            policy_source_sha,
            verified_round_trip_cost_bps,
            ["STRUCTURAL_COST_BUDGET_BELOW_MIN"],
        )

    structural_exit = feature.exit_low if side == "long" else feature.exit_high
    next_add_price = entry + cfg.pyramid_step_atr * atr if side == "long" else entry - cfg.pyramid_step_atr * atr
    return DecisionIntent(
        schema_version=POLICY_SCHEMA_VERSION,
        strategy_id=STRATEGY_ID,
        source_sha=policy_source_sha,
        config_sha=cfg.sha,
        feature_sha=feature.feature_sha,
        evidence_ids=EVIDENCE_IDS,
        symbol=feature.symbol,
        side=side,
        signal_ts=feature.signal_ts,
        entry_rule="closed_bar_donchian_transition_with_directional_structure",
        entry_strength=float(strength),
        strength_normalization="breakout_distance_over_atr_clipped_0_3_then_divide_3",
        regime="TREND_BREAKOUT_ALIGNED",
        no_trade=False,
        invalidation={
            "initial_stop": stop,
            "structural_exit_channel": structural_exit,
            "rule": "initial_stop_or_opposite_shorter_donchian_channel",
        },
        risk_size={
            "risk_fraction_of_equity": cfg.risk_fraction_of_equity,
            "stop_distance_bps": risk_distance_bps,
        },
        exposure={
            "notional_fraction_of_equity": notional_fraction,
            "cap": cfg.max_notional_fraction_of_equity,
        },
        sl=stop,
        tp=None,
        timeout={"bars": cfg.timeout_bars, "rule": "time_stop_if_no_structural_exit_or_invalidation"},
        partial={"enabled": False, "reason": "not_adopted_until_independent_ablation"},
        trailing={"enabled": True, "type": "opposite_donchian_exit", "level": structural_exit},
        runner={"enabled": True, "fixed_tp": False},
        pyramiding={
            "enabled": True,
            "profitable_only": True,
            "max_units": cfg.max_units,
            "step_atr": cfg.pyramid_step_atr,
            "next_add_price": next_add_price,
            "adverse_add": False,
        },
        cooldown={"duplicate_breakout_transition_forbidden": True},
        turnover={"one_entry_per_transition": True, "threshold_rescue_forbidden": True},
        reason_codes=("BREAKOUT_TRANSITION", "DIRECTIONAL_STRUCTURE_ALIGNED", "COST_BUDGET_OK"),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=float(move_budget_bps),
        cost_budget_ratio=float(cost_budget_ratio),
    )


def evaluator_adapter_payload(intent: DecisionIntent) -> Mapping[str, Any]:
    """Evaluator may consume the immutable intent only; it may not invent economics."""
    return _jsonable(asdict(intent))


def evaluator_adapter_sha(intent: DecisionIntent) -> str:
    return _sha(evaluator_adapter_payload(intent))


def direction_flip_control(intent: DecisionIntent) -> DecisionIntent:
    side = {"long": "short", "short": "long"}.get(intent.side, intent.side)
    return replace(intent, side=side, reason_codes=tuple(intent.reason_codes) + ("CONTROL_DIRECTION_FLIP",))


def time_placebo_control(intent: DecisionIntent, offset_ms: int) -> DecisionIntent:
    if offset_ms == 0:
        raise ValueError("PLACEBO_OFFSET_NONZERO_REQUIRED")
    return replace(intent, signal_ts=int(intent.signal_ts + offset_ms), reason_codes=tuple(intent.reason_codes) + ("CONTROL_TIME_PLACEBO",))


def delayed_entry_control(intent: DecisionIntent, delay_bars: int, timeframe_ms: int) -> DecisionIntent:
    if delay_bars <= 0:
        raise ValueError("DELAY_BARS_POSITIVE_REQUIRED")
    return replace(intent, signal_ts=int(intent.signal_ts + delay_bars * timeframe_ms), reason_codes=tuple(intent.reason_codes) + ("CONTROL_DELAYED_ENTRY",))
