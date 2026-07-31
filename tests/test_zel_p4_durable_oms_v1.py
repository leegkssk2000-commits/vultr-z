from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.contracts.zel_oms_command_v2 import OmsContractError
from backend.runtime.zel_durable_oms_v2 import DurableOmsError, PrivateExchangeAdapterBlocked
from backend.runtime.zel_durable_oms_v2_1 import DurableOmsCoordinatorV2_1

BASE_MS = 1_800_000_000_000


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def command(
    target: str,
    sequence: int,
    token: int,
    *,
    owner: str = "zico.test",
    filled: float = 0.0,
    reduce_only: bool = False,
    deadline_delta: int = 0,
    venue_event_id: str = "",
    order_id: str = "order.test",
    position_id: str = "position.test",
) -> dict:
    at_ms = BASE_MS + sequence * 1000
    return {
        "order_intent_id": order_id,
        "client_order_id": "client." + order_id,
        "decision_id": "decision.test",
        "position_id": position_id,
        "strategy_id": "trend_ma_macd",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "mode": "SIMULATION",
        "target_state": target,
        "quantity": 1.0,
        "filled_quantity": filled,
        "reduce_only": reduce_only,
        "risk_snapshot_sha256": "2" * 64,
        "event_ts": iso(at_ms),
        "event_ts_ms": at_ms,
        "idempotency_key": f"{order_id}:{sequence}:{target}",
        "reason_codes": ["TEST"],
        "lease_owner": owner,
        "fencing_token": token,
        "deadline_ms": at_ms + deadline_delta if deadline_delta else 0,
        "venue_event_id": venue_event_id,
    }


def apply_until_partial(store: DurableOmsCoordinatorV2_1, token: int, order_id: str = "order.test", position_id: str = "position.test") -> None:
    rows = [
        ("INTENT_CREATED", 0, 0.0, False, 0, ""),
        ("RISK_APPROVED", 1, 0.0, False, 0, ""),
        ("SENT", 2, 0.0, False, 10_000, ""),
        ("ACKNOWLEDGED", 3, 0.0, False, 10_000, "ack.1"),
        ("PARTIALLY_FILLED", 4, 0.4, False, 10_000, "fill.1"),
    ]
    for target, sequence, filled, reduce_only, deadline, venue in rows:
        store.apply(command(
            target, sequence, token, filled=filled, reduce_only=reduce_only,
            deadline_delta=deadline, venue_event_id=venue,
            order_id=order_id, position_id=position_id,
        ))


def test_full_lifecycle_is_durable_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "oms.sqlite3"
    store = DurableOmsCoordinatorV2_1(path)
    lease = store.acquire_lease("position.test", "zico.test", BASE_MS - 1000, 100_000)
    token = lease["fencing_token"]
    first = command("INTENT_CREATED", 0, token)
    assert store.apply(first)["to_state"] == "INTENT_CREATED"
    assert store.apply(first)["replayed"] is True
    lifecycle = [
        command("RISK_APPROVED", 1, token),
        command("SENT", 2, token, deadline_delta=10_000),
        command("ACKNOWLEDGED", 3, token, deadline_delta=10_000, venue_event_id="ack.1"),
        command("PARTIALLY_FILLED", 4, token, filled=0.4, deadline_delta=10_000, venue_event_id="fill.1"),
        command("PARTIALLY_FILLED", 5, token, filled=0.7, deadline_delta=10_000, venue_event_id="fill.2"),
        command("FILLED", 6, token, filled=1.0, venue_event_id="fill.3"),
        command("CLOSE_SENT", 7, token, filled=1.0, reduce_only=True, deadline_delta=10_000),
        command("CLOSED", 8, token, filled=1.0, reduce_only=True, venue_event_id="close.1"),
    ]
    for row in lifecycle:
        result = store.apply(row)
        assert result["private_exchange_call_performed"] is False
        assert result["capital_activation_allowed"] is False
    reopened = DurableOmsCoordinatorV2_1(path)
    assert reopened.status("order.test")["state"] == "CLOSED"
    assert reopened.event_count("order.test") == 9
    assert reopened.apply(lifecycle[-1])["replayed"] is True


def test_lease_fencing_rejects_stale_owner_and_token(tmp_path: Path) -> None:
    store = DurableOmsCoordinatorV2_1(tmp_path / "oms.sqlite3")
    first = store.acquire_lease("position.test", "owner.a", BASE_MS, 1000)
    with pytest.raises(DurableOmsError, match="LEASE_HELD_BY_OTHER"):
        store.acquire_lease("position.test", "owner.b", BASE_MS + 500, 1000)
    second = store.acquire_lease("position.test", "owner.b", BASE_MS + 1001, 1000)
    assert second["fencing_token"] == first["fencing_token"] + 1
    stale = command("INTENT_CREATED", 2, first["fencing_token"], owner="owner.a")
    with pytest.raises(DurableOmsError, match="LEASE_OWNER_MISMATCH|FENCING_TOKEN_STALE"):
        store.apply(stale)


def test_partial_fill_timeout_enters_reconciliation(tmp_path: Path) -> None:
    store = DurableOmsCoordinatorV2_1(tmp_path / "oms.sqlite3")
    token = store.acquire_lease("position.test", "zico.test", BASE_MS - 1000, 100_000)["fencing_token"]
    apply_until_partial(store, token)
    timeout_at = BASE_MS + 15_000
    scan = store.recovery_scan(timeout_at)
    assert scan["partial_fill_timeout_count"] == 1
    assert scan["recommended_action"] == "hold"
    receipt = store.mark_timeouts_for_reconciliation(timeout_at)
    assert receipt["changed_order_intent_ids"] == ["order.test"]
    assert store.status("order.test")["state"] == "RECONCILIATION_REQUIRED"


def test_partial_fill_must_be_monotonic(tmp_path: Path) -> None:
    store = DurableOmsCoordinatorV2_1(tmp_path / "oms.sqlite3")
    token = store.acquire_lease("position.test", "zico.test", BASE_MS - 1000, 100_000)["fencing_token"]
    apply_until_partial(store, token)
    regressed = command(
        "PARTIALLY_FILLED", 5, token, filled=0.2,
        deadline_delta=10_000, venue_event_id="fill.regressed",
    )
    with pytest.raises(DurableOmsError, match="FILLED_QUANTITY_REGRESSION"):
        store.apply(regressed)


def test_reconciliation_mismatch_holds_local_state(tmp_path: Path) -> None:
    store = DurableOmsCoordinatorV2_1(tmp_path / "oms.sqlite3")
    token = store.acquire_lease("position.test", "zico.test", BASE_MS - 1000, 100_000)["fencing_token"]
    for row in (
        command("INTENT_CREATED", 0, token),
        command("RISK_APPROVED", 1, token),
        command("SENT", 2, token, deadline_delta=10_000),
        command("ACKNOWLEDGED", 3, token, deadline_delta=10_000, venue_event_id="ack.1"),
    ):
        store.apply(row)
    snapshot = {
        "source_ref": "fixture:venue",
        "source_sha256": "3" * 64,
        "observed_at_ms": BASE_MS + 5000,
        "venue_event_id": "venue.snapshot.1",
        "client_order_id": "client.order.test",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "state": "FILLED",
        "quantity": 1.0,
        "filled_quantity": 1.0,
        "reduce_only": False,
    }
    result = store.reconcile("order.test", snapshot)
    assert result["pass"] is False
    assert set(result["mismatch_fields"]) == {"filled_quantity", "state"}
    assert store.status("order.test")["state"] == "RECONCILIATION_REQUIRED"


def test_manual_desync_requires_human_receipt(tmp_path: Path) -> None:
    store = DurableOmsCoordinatorV2_1(tmp_path / "oms.sqlite3")
    token = store.acquire_lease("position.test", "zico.test", BASE_MS - 1000, 100_000)["fencing_token"]
    store.apply(command("INTENT_CREATED", 0, token))
    denied = {
        "receipt_id": "manual.1", "human_approved": False, "reason": "manual intervention",
        "evidence_sha256": "4" * 64, "issued_at_ms": BASE_MS + 1000,
    }
    with pytest.raises(OmsContractError, match="HUMAN_APPROVAL_REQUIRED"):
        store.record_manual_desync("order.test", denied)
    approved = copy.deepcopy(denied)
    approved["human_approved"] = True
    result = store.record_manual_desync("order.test", approved)
    assert result["state"] == "PASS_MANUAL_DESYNC_RECEIPT_BOUND"
    assert store.status("order.test")["state"] == "RECONCILIATION_REQUIRED"


def test_private_exchange_adapter_is_hard_blocked() -> None:
    with pytest.raises(DurableOmsError, match="PRIVATE_EXCHANGE_CALL_BLOCKED"):
        PrivateExchangeAdapterBlocked().execute({"symbol": "BTCUSDT"})


def test_private_fields_are_rejected_before_persistence(tmp_path: Path) -> None:
    store = DurableOmsCoordinatorV2_1(tmp_path / "oms.sqlite3")
    token = store.acquire_lease("position.test", "zico.test", BASE_MS - 1000, 100_000)["fencing_token"]
    raw = command("INTENT_CREATED", 0, token)
    raw["api_key"] = "must-not-persist"
    with pytest.raises(OmsContractError, match="PRIVATE_FIELD_FORBIDDEN"):
        store.apply(raw)
