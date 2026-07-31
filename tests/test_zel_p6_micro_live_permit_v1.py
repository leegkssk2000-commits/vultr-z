from __future__ import annotations

import copy
from pathlib import Path

import pytest

from backend.contracts.zel_micro_live_canary_v1 import MicroLiveContractError
from backend.runtime.zel_micro_live_permit_registry_v1 import MicroLivePermitError, MicroLivePermitRegistry

NOW_MS = 1_800_000_000_000


def policy() -> dict:
    return {
        "policy_ref": "runtime:ssot/micro_live_policy",
        "policy_sha256": "f" * 64,
        "minimum_notional_usdt": 5.0,
        "maximum_notional_usdt": 10.0,
        "maximum_leverage": 10.0,
        "maximum_position_pct": 5.0,
        "maximum_concurrent_positions": 1,
        "maximum_planned_loss_r": 0.75,
        "minimum_liquidation_buffer_pct": 5.0,
        "maximum_funding_8h_pct": 0.1,
        "maximum_exposure_minutes": 1440.0,
        "maximum_daily_dd_pct": 1.0,
        "maximum_total_dd_pct": 2.0,
    }


def approval(*, approval_id: str = "approval.1", nonce: str = "nonce.1") -> dict:
    return {
        "approval_id": approval_id,
        "human_approved": True,
        "actor_ref": "user:repository-owner",
        "nonce": nonce,
        "issued_at_ms": NOW_MS - 1000,
        "expires_at_ms": NOW_MS + 100_000,
        "p5_state": "PASS_P5_PAPER_30D_CANARY",
        "p5_result_sha256": "1" * 64,
        "risk_policy_sha256": "f" * 64,
        "strategy_id": "trend_ma_macd",
        "strategy_source_sha256": "04d98299bd3bd869c379585ba3aed364e2448e180cacaaf21277a4f88a63ec94",
        "family": "TREND",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "notional_usdt": 5.0,
        "leverage": 10.0,
        "position_pct": 5.0,
        "planned_loss_r": 0.75,
        "liquidation_buffer_pct": 8.0,
        "funding_8h_pct": 0.02,
        "exposure_minutes": 720.0,
        "concurrent_positions": 1,
        "add_allowed": False,
        "private_api_scope_ref": "secret-ref:bingx-micro-live-canary-only",
        "emergency_stop_receipt_sha256": "2" * 64,
        "rollback_receipt_sha256": "3" * 64,
        "reconciliation_receipt_sha256": "4" * 64,
        "source_ref": "runtime:micro-live/approval/1",
        "fixture_only": False,
    }


def completion(permit_sha: str, *, incident_count: int = 0, fixture_only: bool = False) -> dict:
    return {
        "canary_id": "micro.canary.1",
        "permit_sha256": permit_sha,
        "source_ref": "runtime:micro-live/completion/1",
        "source_sha256": "5" * 64,
        "fixture_only": fixture_only,
        "started_at_ms": NOW_MS + 1000,
        "ended_at_ms": NOW_MS + 60_000,
        "closed_position_count": 1,
        "incident_count": incident_count,
        "threshold_breach_count": 0,
        "duplicate_order_count": 0,
        "unreconciled_position_count": 0,
        "lifecycle_mismatch_count": 0,
        "formal_ledger_mismatch_count": 0,
        "display_mismatch_count": 0,
        "emergency_stop_drill_pass": True,
        "rollback_drill_pass": True,
        "reconciliation_pass": True,
        "minimum_liquidation_buffer_pct_observed": 8.0,
        "maximum_leverage_observed": 10.0,
        "maximum_position_pct_observed": 5.0,
        "maximum_planned_loss_r_observed": 0.75,
    }


def test_issue_and_consume_permit_once_without_execution(tmp_path: Path) -> None:
    registry = MicroLivePermitRegistry(tmp_path / "permits.sqlite3")
    issued = registry.issue(approval(), policy(), now_ms=NOW_MS)
    assert issued["exchange_execution_performed"] is False
    assert issued["live_execution_adapter_present"] is False
    request = registry.consume(issued["permit_sha256"], "nonce.1", now_ms=NOW_MS + 1000)
    assert request["exchange_execution_performed"] is False
    assert request["live_execution_adapter_present"] is False
    assert request["capital_scale_allowed"] is False
    assert registry.status(issued["permit_sha256"])["status"] == "CONSUMED"
    with pytest.raises(MicroLivePermitError, match="PERMIT_ALREADY_CONSUMED"):
        registry.consume(issued["permit_sha256"], "nonce.1", now_ms=NOW_MS + 2000)


def test_nonce_cannot_be_reused_by_another_approval(tmp_path: Path) -> None:
    registry = MicroLivePermitRegistry(tmp_path / "permits.sqlite3")
    registry.issue(approval(), policy(), now_ms=NOW_MS)
    with pytest.raises(MicroLivePermitError, match="NONCE_OR_PERMIT_REPLAY_BLOCKED"):
        registry.issue(approval(approval_id="approval.2", nonce="nonce.1"), policy(), now_ms=NOW_MS)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("p5_state", "HOLD_P5_PAPER_30D_INCOMPLETE", "P5_PASS_REQUIRED"),
        ("leverage", 11.0, "LEVERAGE_OUT_OF_POLICY"),
        ("add_allowed", True, "MICRO_LIVE_ADD_FORBIDDEN"),
        ("fixture_only", True, "REAL_APPROVAL_REQUIRED"),
        ("concurrent_positions", 2, "ONE_CONCURRENT_POSITION_REQUIRED"),
        ("liquidation_buffer_pct", 2.0, "LIQUIDATION_BUFFER_TOO_LOW"),
    ],
)
def test_approval_fails_closed_on_policy_violation(tmp_path: Path, field: str, value: object, error: str) -> None:
    raw = approval()
    raw[field] = value
    with pytest.raises(MicroLiveContractError, match=error):
        MicroLivePermitRegistry(tmp_path / "permits.sqlite3").issue(raw, policy(), now_ms=NOW_MS)


def test_expired_permit_cannot_be_consumed(tmp_path: Path) -> None:
    registry = MicroLivePermitRegistry(tmp_path / "permits.sqlite3")
    issued = registry.issue(approval(), policy(), now_ms=NOW_MS)
    with pytest.raises(MicroLivePermitError, match="PERMIT_EXPIRED_OR_NOT_CURRENT"):
        registry.consume(issued["permit_sha256"], "nonce.1", now_ms=NOW_MS + 200_000)


def test_completion_requires_consumed_permit_and_zero_incidents(tmp_path: Path) -> None:
    registry = MicroLivePermitRegistry(tmp_path / "permits.sqlite3")
    issued = registry.issue(approval(), policy(), now_ms=NOW_MS)
    with pytest.raises(MicroLivePermitError, match="PERMIT_NOT_CONSUMED"):
        registry.record_completion(completion(issued["permit_sha256"]), policy())
    registry.consume(issued["permit_sha256"], "nonce.1", now_ms=NOW_MS + 500)
    result = registry.record_completion(completion(issued["permit_sha256"]), policy())
    assert result["state"] == "PASS_P6_MICRO_LIVE_CANARY_COMPLETE"
    assert result["capital_scale_allowed"] is False
    assert result["next_activation_requires_new_human_approval"] is True


def test_incident_completion_stays_hold(tmp_path: Path) -> None:
    registry = MicroLivePermitRegistry(tmp_path / "permits.sqlite3")
    issued = registry.issue(approval(), policy(), now_ms=NOW_MS)
    registry.consume(issued["permit_sha256"], "nonce.1", now_ms=NOW_MS + 500)
    result = registry.record_completion(completion(issued["permit_sha256"], incident_count=1), policy())
    assert result["state"] == "HOLD_P6_MICRO_LIVE_CANARY"
    assert "NONZERO_INCIDENT_COUNT" in result["blockers"]


def test_fixture_completion_is_rejected(tmp_path: Path) -> None:
    registry = MicroLivePermitRegistry(tmp_path / "permits.sqlite3")
    issued = registry.issue(approval(), policy(), now_ms=NOW_MS)
    registry.consume(issued["permit_sha256"], "nonce.1", now_ms=NOW_MS + 500)
    with pytest.raises(MicroLiveContractError, match="REAL_COMPLETION_EVIDENCE_REQUIRED"):
        registry.record_completion(completion(issued["permit_sha256"], fixture_only=True), policy())


def test_private_value_fields_are_rejected(tmp_path: Path) -> None:
    raw = approval()
    raw["api_key"] = "must-not-persist"
    with pytest.raises(MicroLiveContractError, match="PRIVATE_FIELD_FORBIDDEN"):
        MicroLivePermitRegistry(tmp_path / "permits.sqlite3").issue(raw, policy(), now_ms=NOW_MS)
