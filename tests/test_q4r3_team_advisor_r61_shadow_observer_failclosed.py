from __future__ import annotations

from dataclasses import replace

from policy.zbot_shadow_router import build_shadow_observer_plan
from policy.zbot_shadow_types import ShadowObserverPolicy, ShadowSnapshot


def gate_policy() -> ShadowObserverPolicy:
    return ShadowObserverPolicy(1000, 50, 200, "sheets:zbot:shadow_observer_policy")


def snap(
    snapshot_id: str = "shadow.r61.002",
    observed_at_ms: int = 10000,
    closed_count: int = 200,
    ledger_row_count: int = 300,
) -> ShadowSnapshot:
    return ShadowSnapshot(
        snapshot_id=snapshot_id,
        epoch_id="q4.shadow.001",
        observed_at_ms=observed_at_ms,
        schema_version="r61-test",
        shadow_source_ref="cf:shadow:status",
        market_source_ref="cf:market:snapshot",
        position_source_ref="cf:paper:position",
        ledger_source_ref="cf:formal:ledger",
        candidate_count=5,
        open_count=1,
        closed_count=closed_count,
        pnl_r=10.5,
        ledger_row_count=ledger_row_count,
        ledger_sha256="sha256:" + "a" * 64,
    )


def test_stale_snapshot_fails_closed() -> None:
    result = build_shadow_observer_plan(
        snap(observed_at_ms=8000), now_ms=10020, policy=gate_policy(), sgrade_ready=True
    )
    assert result.state == "HOLD"
    assert "SHADOW_SNAPSHOT_STALE" in result.reason_codes


def test_count_and_ledger_regressions_fail_closed() -> None:
    previous = snap("shadow.r61.001", 9900, 199, 299)
    closed_result = build_shadow_observer_plan(
        snap(closed_count=198),
        now_ms=10020,
        policy=gate_policy(),
        sgrade_ready=True,
        previous_snapshot=previous,
    )
    assert "SHADOW_CLOSED_COUNT_REGRESSION" in closed_result.reason_codes

    ledger_result = build_shadow_observer_plan(
        snap(ledger_row_count=298),
        now_ms=10020,
        policy=gate_policy(),
        sgrade_ready=True,
        previous_snapshot=previous,
    )
    assert "LEDGER_ROW_COUNT_REGRESSION" in ledger_result.reason_codes


def test_lineage_digest_and_count_types_fail_closed() -> None:
    bad_source = replace(snap(), shadow_source_ref="other:shadow:status")
    source_result = build_shadow_observer_plan(
        bad_source, now_ms=10020, policy=gate_policy(), sgrade_ready=True
    )
    assert "SHADOW_SOURCE_LINEAGE_INVALID" in source_result.reason_codes

    bad_digest = replace(snap(), ledger_sha256="sha256:bad")
    digest_result = build_shadow_observer_plan(
        bad_digest, now_ms=10020, policy=gate_policy(), sgrade_ready=True
    )
    assert "LEDGER_DIGEST_INVALID" in digest_result.reason_codes

    bad_count = replace(snap(), candidate_count=True)
    count_result = build_shadow_observer_plan(
        bad_count, now_ms=10020, policy=gate_policy(), sgrade_ready=True
    )
    assert "SHADOW_COUNT_INVALID" in count_result.reason_codes


def test_closed_count_and_sgrade_prerequisite_fail_closed() -> None:
    parity_result = build_shadow_observer_plan(
        snap(closed_count=301, ledger_row_count=300),
        now_ms=10020,
        policy=gate_policy(),
        sgrade_ready=True,
    )
    assert "CLOSED_COUNT_EXCEEDS_LEDGER_ROWS" in parity_result.reason_codes

    sgrade_result = build_shadow_observer_plan(
        snap(), now_ms=10020, policy=gate_policy(), sgrade_ready=False
    )
    assert "ZBOT_SGRADE_NOT_READY" in sgrade_result.reason_codes
