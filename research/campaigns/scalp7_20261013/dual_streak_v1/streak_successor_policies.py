"""Experimental research-only policies; NOT wired into live or native replay yet.

One new structural axis per lane. No fee/risk threshold, indicator period or
streak-count optimization. Use only with the frozen original execution callbacks.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
import math

KELTNER_SUCCESSOR='scalp7_keltner_hg_fresh_touch_after_reject_utc30m_v1'
SQUEEZE_SUCCESSOR='scalp7_squeeze_trend_signal_low_invalidation_utc30m_v1'

class HGState(Protocol):
    side: int
    episode_traded: bool
    def event_reset(self) -> None: ...

@dataclass
class RejectedHGEventReset:
    """After an unfilled generated HG setup, require a NEW native touch/turn.

Call generated() once on the native event, decided() at the modeled next-open
admission decision. The original HG state machine still defines touch, turn,
strong regime, indicator periods and later accepted-episode renewal. No reset
on 'no signal', accepted positions, filled trades, weak-market state or price
outcome labels. Missing/late admission evidence is an error, not a rejection.
"""
    pending_ts_ms: int | None = None

    def generated(self, signal_available_ts_ms: int) -> None:
        if type(signal_available_ts_ms) is not int or signal_available_ts_ms < 0:
            raise ValueError('SIGNAL_TIMESTAMP_REQUIRED')
        if self.pending_ts_ms is not None:
            raise ValueError('UNRESOLVED_PRIOR_ENTRY_DECISION')
        self.pending_ts_ms=signal_available_ts_ms

    def decided(self, state: HGState, *, accepted: bool, decision_ts_ms: int) -> None:
        if self.pending_ts_ms is None:
            raise ValueError('NO_GENERATED_HG_EVENT')
        if type(accepted) is not bool or type(decision_ts_ms) is not int:
            raise ValueError('ADMISSION_DECISION_REQUIRED')
        if decision_ts_ms < self.pending_ts_ms:
            raise ValueError('ENTRY_DECISION_BEFORE_SIGNAL_AVAILABLE')
        if accepted:
            state.episode_traded=True
        else:
            state.episode_traded=False
            state.event_reset()  # stage=0, extrema cleared; side preserved.
        self.pending_ts_ms=None


def squeeze_signal_low_invalidation(
    *, regime: str, signal_low: float | None, signal_segment: Any,
    bar: Mapping[str, Any], signal_available_ts_ms: int,
    entry_ts_ms: int, asof_ms: int, parent_update: Mapping[str, Any],
) -> dict[str, Any]:
    """TREND_DISPERSED add-on only: a completed close below signal low invalidates.

The parent handles the existing stop, gaps, two-weak-momentum rule and max-hold
FIRST. This function may add a next-open market exit; it never moves a stop,
changes a filled price, tests future MFE or opens a position. PANIC behavior is
returned unchanged. Never substitute signal_low for a stop fill inside the bar.
"""
    result=dict(parent_update)
    if regime=='PANIC_DISPERSION':
        return result
    if regime!='TREND_DISPERSED':
        raise ValueError('UNAUTHORIZED_REGIME_FOR_SUCCESSOR')
    required=('close','open_ts_ms','close_ts_ms','available_ts_ms','segment_id')
    if any(key not in bar for key in required):
        raise ValueError('COMPLETED_BAR_FIELDS_REQUIRED')
    stamps=[signal_available_ts_ms,entry_ts_ms,asof_ms,bar['open_ts_ms'],bar['close_ts_ms'],bar['available_ts_ms']]
    if any(type(v) is not int for v in stamps):
        raise ValueError('INTEGER_CLOCK_REQUIRED')
    if not(signal_available_ts_ms<=entry_ts_ms<=bar['open_ts_ms']<bar['close_ts_ms']<=bar['available_ts_ms']<=asof_ms):
        raise ValueError('CAUSAL_CLOSED_BAR_REQUIRED')
    if bar['close_ts_ms']-bar['open_ts_ms']!=1_800_000 or bar['open_ts_ms']%1_800_000:
        raise ValueError('NATIVE_30M_CLOCK_REQUIRED')
    if signal_segment!=bar['segment_id']:
        raise ValueError('SEGMENT_BREAK_NO_SYNTHETIC_PATH')
    if signal_low is None or not math.isfinite(float(signal_low)) or float(signal_low)<=0:
        raise ValueError('FROZEN_SIGNAL_LOW_REQUIRED')
    close=float(bar['close'])
    if not math.isfinite(close) or close<=0:
        raise ValueError('POSITIVE_CLOSE_REQUIRED')
    if result.get('exit_next_open') is True:
        return result
    if close<float(signal_low):
        result.update(exit_next_open=True,reason='TREND_SIGNAL_BAR_LOW_INVALIDATION_NEXT_OPEN')
    return result
