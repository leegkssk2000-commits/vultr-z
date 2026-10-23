from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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
        return digest(asdict(self))


def f(bar: Mapping[str, Any], key: str, *, positive: bool = True) -> float:
    try:
        value = float(bar[key])
    except Exception as exc:
        raise ValueError(f"BAR_FIELD_INVALID:{key}") from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"BAR_FIELD_INVALID:{key}")
    return value


def ts(bar: Mapping[str, Any]) -> int:
    try:
        return int(bar["ts_ms"])
    except Exception as exc:
        raise ValueError("BAR_TS_INVALID") from exc


def validate_bars(bars: Sequence[Mapping[str, Any]], *, minimum: int) -> None:
    if len(bars) < minimum:
        raise ValueError("WARMUP_INSUFFICIENT")
    last = None
    for bar in bars:
        t = ts(bar)
        if last is not None and t <= last:
            raise ValueError("BAR_TS_NON_MONOTONIC_OR_DUPLICATE")
        o, h, l, c = (f(bar, k) for k in ("open", "high", "low", "close"))
        if h < max(o, c) or l > min(o, c) or h < l:
            raise ValueError("BAR_OHLC_INTEGRITY_FAIL")
        if "volume" in bar:
            f(bar, "volume", positive=False)
        last = t


def ema(values: Sequence[float], length: int) -> list[float]:
    alpha = 2.0 / (length + 1.0)
    out = [float(values[0])]
    for value in values[1:]:
        out.append(alpha * float(value) + (1.0 - alpha) * out[-1])
    return out


def sma(values: Sequence[float], length: int) -> float:
    return sum(float(x) for x in values[-length:]) / length


def stdev(values: Sequence[float], length: int) -> float:
    xs = [float(x) for x in values[-length:]]
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))


def true_ranges(bars: Sequence[Mapping[str, Any]]) -> list[float]:
    out: list[float] = []
    prev = None
    for bar in bars:
        h, l, c = f(bar, "high"), f(bar, "low"), f(bar, "close")
        out.append(h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev)))
        prev = c
    return out


def atr(bars: Sequence[Mapping[str, Any]], length: int) -> float:
    trs = true_ranges(bars)
    current = sum(trs[:length]) / length
    for tr in trs[length:]:
        current = ((length - 1) * current + tr) / length
    return current


def rsi(values: Sequence[float], length: int) -> float:
    if len(values) < length + 1:
        raise ValueError("RSI_WARMUP_INSUFFICIENT")
    gains = 0.0
    losses = 0.0
    segment = values[-(length + 1):]
    for a, b in zip(segment[:-1], segment[1:]):
        d = float(b) - float(a)
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g = gains / length
    avg_l = losses / length
    if avg_l <= 1e-12:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def rolling_vwap(bars: Sequence[Mapping[str, Any]], length: int) -> float:
    selected = bars[-length:]
    num = 0.0
    den = 0.0
    for bar in selected:
        vol = f(bar, "volume", positive=False)
        if vol < 0:
            raise ValueError("BAR_VOLUME_NEGATIVE")
        tp = (f(bar, "high") + f(bar, "low") + f(bar, "close")) / 3.0
        num += tp * vol
        den += vol
    if den <= 0:
        raise ValueError("VWAP_VOLUME_UNAVAILABLE")
    return num / den


def anchored_vwap(bars: Sequence[Mapping[str, Any]], lookback: int, *, side: str) -> tuple[float, int]:
    start = max(0, len(bars) - lookback)
    window = bars[start:]
    if side == "long":
        rel = min(range(len(window)), key=lambda i: f(window[i], "low"))
    else:
        rel = max(range(len(window)), key=lambda i: f(window[i], "high"))
    anchor = start + rel
    return rolling_vwap(bars[anchor:], len(bars) - anchor), ts(bars[anchor])


def validate_authority(*, policy_source_sha: str, verified_round_trip_cost_bps: float) -> None:
    if not policy_source_sha:
        raise ValueError("SOURCE_SHA_REQUIRED")
    if verified_round_trip_cost_bps <= 0:
        raise ValueError("VERIFIED_COST_AUTHORITY_REQUIRED")


def risk_geometry(*, entry: float, stop: float, risk_fraction: float, exposure_cap: float) -> tuple[float, float]:
    distance = abs(entry - stop)
    if entry <= 0 or distance <= 0:
        raise ValueError("RISK_GEOMETRY_INVALID")
    stop_fraction = distance / entry
    notional = min(exposure_cap, risk_fraction / stop_fraction)
    return notional, stop_fraction * 10_000.0


def control_direction_flip(intent: DecisionIntent) -> DecisionIntent:
    side = {"long": "short", "short": "long"}.get(intent.side, intent.side)
    return replace(intent, side=side, reason_codes=intent.reason_codes + ("CONTROL_DIRECTION_FLIP",))


def control_time_placebo(intent: DecisionIntent, offset_ms: int) -> DecisionIntent:
    return replace(intent, signal_ts=intent.signal_ts + int(offset_ms), reason_codes=intent.reason_codes + ("CONTROL_TIME_PLACEBO",))


def control_delayed_entry(intent: DecisionIntent, bars: int, timeframe_ms: int) -> DecisionIntent:
    return replace(intent, signal_ts=intent.signal_ts + int(bars) * int(timeframe_ms), reason_codes=intent.reason_codes + ("CONTROL_DELAYED_ENTRY",))


def evaluator_adapter_sha(intent: DecisionIntent) -> str:
    # The evaluator adapter is accounting-only; parity means byte-identical intent economics.
    return intent.sha


def hold_intent(*, strategy_id: str, policy_schema: str, source_sha: str, config_sha: str,
                feature_sha: str, evidence_ids: Iterable[str], symbol: str, signal_ts: int,
                entry_rule: str, strength_normalization: str, regime: str, reasons: Iterable[str],
                verified_cost_bps: float, timeout_bars: int, risk_fraction: float,
                exposure_cap: float) -> DecisionIntent:
    return DecisionIntent(
        schema_version=policy_schema, strategy_id=strategy_id, source_sha=source_sha,
        config_sha=config_sha, feature_sha=feature_sha, evidence_ids=tuple(evidence_ids),
        symbol=symbol, side="flat", signal_ts=signal_ts, entry_rule=entry_rule,
        entry_strength=0.0, strength_normalization=strength_normalization, regime=regime,
        no_trade=True, invalidation={"type":"none"},
        risk_size={"risk_fraction_of_equity":risk_fraction},
        exposure={"notional_fraction_of_equity":0.0,"cap":exposure_cap}, sl=None, tp=None,
        timeout={"bars":timeout_bars}, partial={"enabled":False}, trailing={"enabled":False},
        runner={"enabled":False}, pyramiding={"enabled":False,"adverse_add":False},
        cooldown={"one_entry_per_transition":True}, turnover={"duplicate_transition_forbidden":True},
        reason_codes=tuple(reasons), verified_round_trip_cost_bps=float(verified_cost_bps),
        move_budget_bps=0.0, cost_budget_ratio=0.0,
    )
