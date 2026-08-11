from __future__ import annotations

from copy import deepcopy

import pytest

from backend.production.zel_production_admission_result_bridge_v1 import (
    EXPECTED_OWNER_SHA256,
    bridge,
    stable_sha,
)


def source(state: str) -> dict:
    row = {
        "schema_version": "zel.squeeze_break.150d_admission.v1",
        "state": state,
        "strategy_id": "squeeze_break",
        "source_binding": {
            "expected_owner_sha256": EXPECTED_OWNER_SHA256,
            "owner_sha256_before": EXPECTED_OWNER_SHA256,
            "owner_sha256_after": EXPECTED_OWNER_SHA256,
            "source_unchanged": True,
            "strategy_parameter_changes": 0,
            "feature_gate_changes": 0,
            "side_filter_changes": 0,
        },
        "integrity": {"integrity_ok": True, "duplicate_trade_identity_count": 0},
        "funding": {"complete_for_scoring": True},
        "production_window_gates": {"W1": True, "W2": False, "W3": True},
        "aggregate": {"production_symbols": {"trade_count": 50, "net_R": -1.0}},
        "bootstrap_authority_gates": {
            "risk_request_bound": False,
            "dd_pct_bound": False,
            "retention_semantics_bound": False,
            "bootstrap_pass_evidence_emitted": False,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def rehash(row: dict) -> dict:
    row = deepcopy(row)
    row.pop("receipt_sha256", None)
    row["receipt_sha256"] = stable_sha(row)
    return row


def test_reject_emits_only_terminal_reject_evidence() -> None:
    result = bridge(source("REJECT_SQUEEZE150_PRODUCTION_DURABILITY"))
    assert result["state"] == "PASS_TERMINAL_REJECT_EVIDENCE_READY"
    assert result["write_admission_evidence"] is True
    ev = result["admission_evidence"]
    assert ev["state"] == "REJECT_BOOTSTRAP_ADMISSION_EVIDENCE"
    assert ev["action"] == "route_change"
    assert ev["execution_authority"] == "NONE"
    assert ev["order_authority"] == "BLOCKED"
    assert "authority_candidate" not in ev
    assert "sample_gate_pass" not in ev


def test_economic_pass_does_not_fabricate_bootstrap_pass() -> None:
    row = source("HOLD_SQUEEZE150_ECONOMIC_PASS_AUTHORITY_GATES_PENDING")
    row["production_window_gates"] = {"W1": True, "W2": True, "W3": True}
    row = rehash(row)
    result = bridge(row)
    assert result["state"] == "HOLD_ECONOMIC_PASS_AUTHORITY_BINDING_REQUIRED"
    assert result["write_admission_evidence"] is False
    assert result["admission_evidence"] is None
    assert result["missing_authority"] == ["risk_request", "dd_pct", "retention_semantics"]


def test_funding_gap_holds_without_evidence() -> None:
    row = source("HOLD_SQUEEZE150_FUNDING_SOURCE_GAP")
    row["funding"]["complete_for_scoring"] = False
    row = rehash(row)
    result = bridge(row)
    assert result["state"] == "HOLD_SOURCE_NOT_TERMINAL_FOR_BRIDGE"
    assert result["write_admission_evidence"] is False


def test_integrity_hold_holds_without_evidence() -> None:
    row = source("HOLD_SQUEEZE150_INTEGRITY_FAILURE")
    row["integrity"]["integrity_ok"] = False
    row = rehash(row)
    result = bridge(row)
    assert result["state"] == "HOLD_SOURCE_NOT_TERMINAL_FOR_BRIDGE"
    assert result["write_admission_evidence"] is False


def test_terminal_reject_requires_complete_funding() -> None:
    row = source("REJECT_SQUEEZE150_PRODUCTION_DURABILITY")
    row["funding"]["complete_for_scoring"] = False
    row = rehash(row)
    with pytest.raises(RuntimeError, match="TERMINAL_FUNDING_NOT_COMPLETE"):
        bridge(row)


def test_owner_drift_fails_closed() -> None:
    row = source("REJECT_SQUEEZE150_PRODUCTION_DURABILITY")
    row["source_binding"]["owner_sha256_after"] = "drift"
    row = rehash(row)
    with pytest.raises(RuntimeError, match="OWNER_SHA_MISMATCH"):
        bridge(row)


def test_receipt_tamper_fails_closed() -> None:
    row = source("REJECT_SQUEEZE150_PRODUCTION_DURABILITY")
    row["aggregate"]["production_symbols"]["net_R"] = 999.0
    with pytest.raises(RuntimeError, match="SOURCE_RECEIPT_MISMATCH"):
        bridge(row)
