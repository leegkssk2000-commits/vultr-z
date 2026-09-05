from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence

from backend.research.rebuild import microstructure_policy_batch_v1 as base
from backend.research.rebuild.policy_kernel_v1 import atr, digest, ema, f, ts, validate_bars


@dataclass(frozen=True)
class VolSpikeFadeConfirmationConfig(base.MicroPolicyConfig):
    """Single causal-axis v2: wait one completed bar for reversal confirmation.

    All baseline spike thresholds, risk, stop, timeout, turnover and cost rules are inherited unchanged.
    """

    @property
    def sha(self) -> str:
        return digest(asdict(self))


FeatureSnapshot = base.FeatureSnapshot
POLICY_SCHEMA = "zel.vol_spike_fade.policy.v2.post_spike_reversal_confirmation"
EVIDENCE = (
    "HIST_R7_VOL_SPIKE_FADE",
    "ARXIV_1704.08175",
    "SSRN_3258508",
    "DOI_10.5195_LEDGER.2021.213",
    "SSRN_3239670",
    "BINGX_FEE_SCHEDULE",
)


def compute_vol_spike_fade_feature(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: VolSpikeFadeConfirmationConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or VolSpikeFadeConfirmationConfig()
    validate_bars(bars, minimum=max(41, cfg.volume_lookback + cfg.atr_len + 4))
    a = atr(bars, cfg.atr_len)
    spike = bars[-2]
    confirm = bars[-1]

    spike_open = f(spike, "open")
    spike_close = f(spike, "close")
    spike_high = f(spike, "high")
    spike_low = f(spike, "low")
    spike_range = max(spike_high - spike_low, 1e-12)
    spike_body_atr = abs(spike_close - spike_open) / max(a, 1e-12)

    prior_volumes = [max(0.0, f(x, "volume")) for x in bars[-(cfg.volume_lookback + 2):-2]]
    vol_ma = sum(prior_volumes) / max(1, len(prior_volumes))
    spike_volume = max(0.0, f(spike, "volume"))
    volume_ratio = spike_volume / max(vol_ma, 1e-12)

    up_peak = spike_close > spike_open and spike_body_atr >= 0.75 and (spike_high - spike_close) / spike_range <= 0.35
    down_peak = spike_close < spike_open and spike_body_atr >= 0.75 and (spike_close - spike_low) / spike_range <= 0.35
    baseline_spike = volume_ratio >= 2.0

    body_midpoint = (spike_open + spike_close) / 2.0
    confirm_close = f(confirm, "close")
    confirm_open = f(confirm, "open")
    confirm_long = down_peak and baseline_spike and confirm_close > confirm_open and confirm_close >= body_midpoint
    confirm_short = up_peak and baseline_spike and confirm_close < confirm_open and confirm_close <= body_midpoint

    closes = [f(x, "close") for x in bars]
    trend = ema(closes, 20)
    trend_stretch_atr = abs(confirm_close - trend[-1]) / max(a, 1e-12)
    values = {
        "long_fade": bool(confirm_long),
        "short_fade": bool(confirm_short),
        "volume_ratio": volume_ratio,
        "body_atr": spike_body_atr,
        "trend_stretch_atr": trend_stretch_atr,
        "spike_body_midpoint": body_midpoint,
        "confirmation_close": confirm_close,
        "confirmation_axis": "POST_SPIKE_REVERSAL_CONFIRMATION",
        "baseline_spike_thresholds_unchanged": True,
    }
    close = confirm_close
    body = {
        "strategy_id": "vol_spike_fade",
        "symbol": symbol,
        "signal_ts": ts(confirm),
        "close": close,
        "atr": a,
        "values": values,
    }
    return FeatureSnapshot(
        strategy_id="vol_spike_fade",
        symbol=symbol,
        signal_ts=ts(confirm),
        fresh=base._fresh(ts(confirm), now_ts_ms, cfg),
        close=close,
        atr=a,
        values=values,
        feature_sha=digest(body),
    )


def build_vol_spike_fade_intent(
    feature: FeatureSnapshot, *, policy_source_sha: str, verified_round_trip_cost_bps: float,
    config: VolSpikeFadeConfirmationConfig | None = None,
):
    cfg = config or VolSpikeFadeConfirmationConfig()
    intent = base._build(
        feature,
        policy_source_sha=policy_source_sha,
        verified_round_trip_cost_bps=verified_round_trip_cost_bps,
        config=cfg,
    )
    reasons = tuple(getattr(intent, "reason_codes", ()) or ())
    if not getattr(intent, "no_trade", True):
        reasons = reasons + ("AXIS_POST_SPIKE_REVERSAL_CONFIRMATION",)
    return replace(
        intent,
        schema_version=POLICY_SCHEMA,
        evidence_ids=EVIDENCE,
        entry_rule="closed_bar_volume_spike_then_next_bar_midbody_reversal_confirmation",
        regime="POST_SPIKE_REVERSAL_CONFIRMED" if not intent.no_trade else intent.regime,
        reason_codes=reasons,
    )
