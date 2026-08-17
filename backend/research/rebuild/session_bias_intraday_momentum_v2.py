from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Mapping, Sequence

from backend.research.rebuild import final_four_policy_batch_v1 as base
from backend.research.rebuild.policy_kernel_v1 import atr, digest, f, ts, validate_bars


@dataclass(frozen=True)
class SessionBiasMomentumConfig(base.FinalFourConfig):
    """Single causal-axis v2: session-specific first-to-last half-hour momentum entry.

    Baseline stop/target/risk/timeout/cost geometry is inherited unchanged.
    """

    @property
    def sha(self) -> str:
        return digest(asdict(self))


FeatureSnapshot = base.FeatureSnapshot
POLICY_SCHEMA = "zel.session_bias.policy.v2.lny_first_to_last_half_hour_momentum"
EVIDENCE = (
    "HIST_R7_FINAL4",
    "DOI_10.1111_FIRE.12290",
    "DOI_10.1016_J.RIBAF.2022.101625",
    "DOI_10.1016_J.FRL.2019.07.016",
    "ARXIV_2109.12142",
    "BINGX_FEE_SCHEDULE",
)


def _utc_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _lny_overlap_bounds(day_utc: datetime) -> tuple[datetime, datetime]:
    """Return London/NYSE cash-session overlap in UTC with DST handled by zoneinfo."""
    day = day_utc.date()
    london = ZoneInfo("Europe/London")
    new_york = ZoneInfo("America/New_York")
    lse_open = datetime.combine(day, time(8, 0), tzinfo=london).astimezone(timezone.utc)
    lse_close = datetime.combine(day, time(16, 30), tzinfo=london).astimezone(timezone.utc)
    ny_open = datetime.combine(day, time(9, 30), tzinfo=new_york).astimezone(timezone.utc)
    ny_close = datetime.combine(day, time(16, 0), tzinfo=new_york).astimezone(timezone.utc)
    return max(lse_open, ny_open), min(lse_close, ny_close)


def _bar_by_ts(bars: Sequence[Mapping[str, Any]], target_ms: int) -> Mapping[str, Any] | None:
    for bar in reversed(bars):
        if int(bar["ts_ms"]) == target_ms:
            return bar
    return None


def compute_session_bias_feature(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: SessionBiasMomentumConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or SessionBiasMomentumConfig()
    validate_bars(bars, minimum=90)
    closes = [f(b, "close") for b in bars]
    a = atr(bars, cfg.atr_len)
    current = bars[-1]
    current_ts = int(current["ts_ms"])
    current_dt = datetime.fromtimestamp(current_ts / 1000.0, tz=timezone.utc)
    overlap_start, overlap_end = _lny_overlap_bounds(current_dt)
    first_start = overlap_start
    first_last_bar = first_start + timedelta(minutes=25)
    last_half_start = overlap_end - timedelta(minutes=30)
    signal_bar_time = last_half_start - timedelta(minutes=5)

    first_open_bar = _bar_by_ts(bars, _utc_ms(first_start))
    first_close_bar = _bar_by_ts(bars, _utc_ms(first_last_bar))
    at_signal_clock = current_ts == _utc_ms(signal_bar_time)
    side = "flat"
    first_half_return_bps = 0.0
    if at_signal_clock and first_open_bar is not None and first_close_bar is not None:
        p0 = float(first_open_bar["open"])
        p1 = float(first_close_bar["close"])
        first_half_return_bps = (p1 - p0) / p0 * 10_000.0
        if first_half_return_bps > 0:
            side = "long"
        elif first_half_return_bps < 0:
            side = "short"

    values = {
        "overlap_start_utc": overlap_start.isoformat(),
        "overlap_end_utc": overlap_end.isoformat(),
        "first_half_return_bps": first_half_return_bps,
        "signal_clock_match": at_signal_clock,
        "entry_axis": "LNY_FIRST_TO_LAST_HALF_HOUR_MOMENTUM_ENTRY",
    }
    strength = min(1.0, abs(first_half_return_bps) / max(a / closes[-1] * 10_000.0, 1e-12)) if side != "flat" else 0.0
    return FeatureSnapshot(
        strategy_id="session_bias",
        symbol=symbol,
        signal_ts=ts(current),
        fresh=base._fresh(ts(current), now_ts_ms, cfg),
        close=closes[-1],
        atr=a,
        side=side,
        regime="london_newyork_overlap_intraday_momentum" if side != "flat" else "no_trade",
        strength=strength,
        entry_rule="first_overlap_half_hour_return_sign_to_last_overlap_half_hour",
        stop_mult=1.15,
        rr=1.90,
        values=values,
        feature_sha=digest(values),
    )


def build_session_bias_intent(
    feature: FeatureSnapshot, *, policy_source_sha: str, verified_round_trip_cost_bps: float,
    config: SessionBiasMomentumConfig | None = None,
):
    cfg = config or SessionBiasMomentumConfig()
    intent = base.intent_from_snapshot(
        feature,
        policy_source_sha=policy_source_sha,
        verified_round_trip_cost_bps=verified_round_trip_cost_bps,
        config=cfg,
    )
    reasons = tuple(getattr(intent, "reason_codes", ()) or ())
    if not getattr(intent, "no_trade", True):
        reasons = reasons + ("AXIS_LNY_FIRST_TO_LAST_HALF_HOUR_MOMENTUM_ENTRY",)
    return replace(intent, schema_version=POLICY_SCHEMA, evidence_ids=EVIDENCE, reason_codes=reasons)
