"""Causal source-clock admission; never rewrite native or receipt timestamps.

A source observation is quarantined until an actual local processing clock sample
reaches both preserved timestamps. The bounded wait is operational, not a source
clock offset estimate or a timestamp tolerance.
"""

from __future__ import annotations

import time
from typing import Any, Callable


class SourceClockError(RuntimeError):
    """No observation may be used without its actual bounded clock barrier."""


def wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def await_native_time(
    native_ts_ms: int,
    received_at_ms: int,
    max_wait_ms: int = 5000,
    *,
    clock_ms: Callable[[], int] = wall_clock_ms,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], Any] = time.sleep,
) -> dict[str, Any]:
    """Return only an actual clock sample >= both original timestamps.

    Injection exists for deterministic clock tests. Production callers use the
    default clocks and must separately enforce any total HTTP request budget.
    Clock reversals, far-future timestamps, and deadline misses fail closed.
    """
    if (
        type(native_ts_ms) is not int
        or type(received_at_ms) is not int
        or native_ts_ms < 0
        or received_at_ms < 0
        or type(max_wait_ms) is not int
        or max_wait_ms <= 0
    ):
        raise SourceClockError("INVALID_CLOCK_BARRIER_INPUT")
    started_wall = clock_ms()
    started_mono = monotonic_ns()
    if type(started_wall) is not int or type(started_mono) is not int:
        raise SourceClockError("INVALID_ACTUAL_CLOCK_SAMPLE")
    if started_wall < received_at_ms:
        raise SourceClockError("LOCAL_CLOCK_BEFORE_PRESERVED_RECEIPT")
    target = max(native_ts_ms, received_at_ms)
    if target - started_wall > max_wait_ms:
        raise SourceClockError("NATIVE_TIME_BEYOND_WAIT_BUDGET")
    previous_wall, previous_mono = started_wall, started_mono
    current_wall, current_mono = started_wall, started_mono
    samples = [{"wall_ms": current_wall, "monotonic_ns": current_mono}]
    while True:
        elapsed_ns = current_mono - started_mono
        if (
            elapsed_ns < 0
            or current_mono < previous_mono
            or current_wall < previous_wall
        ):
            raise SourceClockError("CLOCK_REVERSED_DURING_QUARANTINE")
        if elapsed_ns > max_wait_ms * 1_000_000:
            raise SourceClockError("CLOCK_QUARANTINE_TIMEOUT")
        if current_wall >= target:
            return {
                "schema": "scalp7.actual_source_clock_barrier.v3",
                "state": "USABLE_AFTER_ACTUAL_CLOCK_BARRIER",
                "native_ts_ms": native_ts_ms,
                "received_at_ms": received_at_ms,
                "started_at_ms": started_wall,
                "usable_at_ms": current_wall,
                "started_monotonic_ns": started_mono,
                "usable_monotonic_ns": current_mono,
                "waited_ms": elapsed_ns / 1_000_000,
                "max_wait_ms": max_wait_ms,
                "quarantined": started_wall < target,
                "clock_samples": samples,
                "native_timestamp_rewritten": False,
                "receipt_timestamp_rewritten": False,
                "clock_offset_or_tolerance_applied": False,
            }
        remaining_ns = max_wait_ms * 1_000_000 - elapsed_ns
        if remaining_ns <= 0:
            raise SourceClockError("CLOCK_QUARANTINE_TIMEOUT")
        sleep(min(0.05, (target - current_wall) / 1000, remaining_ns / 1_000_000_000))
        previous_wall, previous_mono = current_wall, current_mono
        current_wall, current_mono = clock_ms(), monotonic_ns()
        if type(current_wall) is not int or type(current_mono) is not int:
            raise SourceClockError("INVALID_ACTUAL_CLOCK_SAMPLE")
        samples.append({"wall_ms": current_wall, "monotonic_ns": current_mono})
