"""Bounded clock fixtures; these are not market or execution evidence."""

from typing import Any

import pytest

from backend.research.rebuild.scalp7_source_clock_v3 import (
    SourceClockError,
    await_native_time,
)


def barrier(
    native: int,
    received: int,
    walls: list[int],
    monos: list[int],
    budget: int = 5000,
) -> tuple[dict[str, Any], list[float]]:
    wall_iter, mono_iter = iter(walls), iter(monos)
    sleeps: list[float] = []
    result = await_native_time(
        native,
        received,
        budget,
        clock_ms=lambda: next(wall_iter),
        monotonic_ns=lambda: next(mono_iter),
        sleep=sleeps.append,
    )
    return result, sleeps


@pytest.mark.parametrize("lead_ms", [1, 4])
def test_actual_observed_native_lead_waits_for_real_wall_proof(lead_ms: int) -> None:
    receipt = 1_789_500_000_000
    native = receipt + lead_ms
    walls = list(range(receipt, native + 1))
    monos = [i * 1_000_000 for i in range(lead_ms + 1)]
    result, sleeps = barrier(native, receipt, walls, monos)
    assert result["native_ts_ms"] == native
    assert result["received_at_ms"] == receipt
    assert result["usable_at_ms"] == native
    assert result["started_at_ms"] == receipt
    assert result["usable_monotonic_ns"] == lead_ms * 1_000_000
    assert result["waited_ms"] == lead_ms
    assert result["quarantined"] is True
    assert len(sleeps) == lead_ms
    assert all(0 < x <= lead_ms / 1000 for x in sleeps)
    samples = result["clock_samples"]
    assert [x["wall_ms"] for x in samples] == walls
    assert all(x["wall_ms"] < native for x in samples[:-1])
    assert samples[-1]["wall_ms"] >= max(native, receipt)
    assert result["native_timestamp_rewritten"] is False
    assert result["receipt_timestamp_rewritten"] is False
    assert result["clock_offset_or_tolerance_applied"] is False


def test_already_available_source_uses_actual_clock_without_wait() -> None:
    result, sleeps = barrier(998, 999, [1000], [123_000_000])
    assert sleeps == []
    assert result["usable_at_ms"] == 1000
    assert result["native_ts_ms"] == 998
    assert result["received_at_ms"] == 999
    assert result["waited_ms"] == 0
    assert result["quarantined"] is False


def test_lead_within_budget_is_not_permission_before_actual_wall_catches_up() -> None:
    result, sleeps = barrier(
        1004, 1000, [1000, 1000, 1003, 1004], [0, 1_000_000, 3_000_000, 4_000_000]
    )
    assert len(sleeps) == 3
    assert result["usable_at_ms"] == 1004
    assert result["clock_samples"][1]["wall_ms"] == 1000


def test_far_future_native_time_fails_before_sleep_or_admission() -> None:
    with pytest.raises(SourceClockError, match="NATIVE_TIME_BEYOND_WAIT_BUDGET"):
        barrier(6001, 1000, [1000], [0])


def test_exact_deadline_can_admit_only_with_actual_wall_proof() -> None:
    result, _ = barrier(6000, 1000, [1000, 6000], [0, 5_000_000_000])
    assert result["usable_at_ms"] == 6000
    assert result["waited_ms"] == result["max_wait_ms"] == 5000


def test_monotonic_deadline_rejects_even_if_late_wall_sample_reaches_native() -> None:
    with pytest.raises(SourceClockError, match="CLOCK_QUARANTINE_TIMEOUT"):
        barrier(1004, 1000, [1000, 1004], [0, 5_000_000_001])


def test_stalled_wall_hits_monotonic_deadline_without_inventing_usable_time() -> None:
    with pytest.raises(SourceClockError, match="CLOCK_QUARANTINE_TIMEOUT"):
        barrier(1004, 1000, [1000, 1000], [0, 5_000_000_000])


def test_wall_reversal_during_wait_fails_closed() -> None:
    with pytest.raises(SourceClockError, match="CLOCK_REVERSED_DURING_QUARANTINE"):
        barrier(1004, 1000, [1000, 999], [0, 1_000_000])


def test_monotonic_reversal_during_wait_fails_closed() -> None:
    with pytest.raises(SourceClockError, match="CLOCK_REVERSED_DURING_QUARANTINE"):
        barrier(1004, 1000, [1000, 1004], [100, 99])


def test_clock_before_preserved_receipt_holds_without_rewriting_receipt() -> None:
    with pytest.raises(SourceClockError, match="LOCAL_CLOCK_BEFORE_PRESERVED_RECEIPT"):
        barrier(1004, 1002, [1000], [0])


@pytest.mark.parametrize(
    "native,received,budget",
    [
        (True, 1000, 5000),
        (1001.0, 1000, 5000),
        (1001, -1, 5000),
        (1001, 1000, 0),
        (1001, 1000, float("inf")),
        (float("nan"), 1000, 5000),
    ],
)
def test_invalid_or_nonfinite_inputs_never_sample_actual_clock(
    native: Any, received: Any, budget: Any
) -> None:
    def forbidden() -> int:
        raise AssertionError("invalid input must fail before clock sampling")

    with pytest.raises(SourceClockError, match="INVALID_CLOCK_BARRIER_INPUT"):
        await_native_time(
            native, received, budget, clock_ms=forbidden, monotonic_ns=forbidden
        )


@pytest.mark.parametrize("wall,mono", [(1000.0, 0), (1000, float("nan"))])
def test_invalid_initial_actual_clock_sample_fails_closed(wall: Any, mono: Any) -> None:
    with pytest.raises(SourceClockError, match="INVALID_ACTUAL_CLOCK_SAMPLE"):
        await_native_time(1004, 1000, clock_ms=lambda: wall, monotonic_ns=lambda: mono)


def test_invalid_actual_sample_after_wait_fails_closed() -> None:
    walls: Any = iter([1000, float("nan")])
    monos = iter([0, 1_000_000])
    with pytest.raises(SourceClockError, match="INVALID_ACTUAL_CLOCK_SAMPLE"):
        await_native_time(
            1004,
            1000,
            clock_ms=lambda: next(walls),
            monotonic_ns=lambda: next(monos),
            sleep=lambda _: None,
        )
