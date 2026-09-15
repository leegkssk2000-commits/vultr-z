from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class LifecycleResult:
    exit_price: float
    exit_ts: int
    gross_bps: float
    net_bps: float
    reason: str
    armed_1r: bool


def apply_be1r_long(
    *,
    entry_price: float,
    risk_price: float,
    cost_bps: float,
    original_exit_price: float,
    original_exit_ts: int,
    bars: Sequence[Mapping[str, float | int]],
) -> LifecycleResult:
    """Apply a fee-adjusted break-even stop only after +1R was seen.

    The stop becomes active on the bar *after* the +1R witness bar. This avoids
    assuming an intrabar high/low ordering that the OHLC source cannot prove.
    """
    if entry_price <= 0 or risk_price <= 0:
        raise ValueError("entry_price and risk_price must be positive")
    stop_price = entry_price * (1.0 + cost_bps / 10_000.0)
    armed = False
    exit_price = original_exit_price
    exit_ts = original_exit_ts
    reason = "ORIGINAL_EXIT"
    for bar in bars:
        high = float(bar["high"])
        low = float(bar["low"])
        ts = int(bar["ts_ms"])
        if armed and low <= stop_price:
            exit_price = stop_price
            exit_ts = ts
            reason = "BE1R_FEE_ADJUSTED_STOP"
            break
        if not armed and high >= entry_price + risk_price:
            armed = True

    gross_bps = (exit_price - entry_price) / entry_price * 10_000.0
    return LifecycleResult(
        exit_price=exit_price,
        exit_ts=exit_ts,
        gross_bps=gross_bps,
        net_bps=gross_bps - cost_bps,
        reason=reason,
        armed_1r=armed,
    )
