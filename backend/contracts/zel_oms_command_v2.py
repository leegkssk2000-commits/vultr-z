from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

SCHEMA_VERSION = "zel.oms.command.v2"
MODES = {"SIMULATION", "PAPER_CANARY"}
STATES = {
    "INTENT_CREATED", "RISK_APPROVED", "SENT", "ACKNOWLEDGED", "PARTIALLY_FILLED",
    "FILLED", "CANCEL_REQUESTED", "CANCELED", "CLOSE_SENT", "CLOSED", "HELD",
    "BLOCKED", "RECONCILIATION_REQUIRED", "ROLLED_BACK",
}
TERMINAL_STATES = {"CLOSED", "BLOCKED", "ROLLED_BACK"}
VENUE_CONFIRMED_STATES = {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELED", "CLOSED"}
TIMEOUT_STATES = {"SENT", "ACKNOWLEDGED", "CANCEL_REQUESTED", "CLOSE_SENT"}
TRANSITIONS = {
    None: {"INTENT_CREATED"},
    "INTENT_CREATED": {"RISK_APPROVED", "HELD", "BLOCKED"},
    "RISK_APPROVED": {"SENT", "HELD", "BLOCKED"},
    "SENT": {"ACKNOWLEDGED", "HELD", "BLOCKED", "RECONCILIATION_REQUIRED"},
    "ACKNOWLEDGED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_REQUESTED", "HELD", "RECONCILIATION_REQUIRED"},
    "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_REQUESTED", "CLOSE_SENT", "RECONCILIATION_REQUIRED"},
    "FILLED": {"CLOSE_SENT", "RECONCILIATION_REQUIRED", "HELD"},
    "CANCEL_REQUESTED": {"CANCELED", "PARTIALLY_FILLED", "FILLED", "RECONCILIATION_REQUIRED"},
    "CANCELED": {"CLOSE_SENT", "CLOSED", "RECONCILIATION_REQUIRED"},
    "CLOSE_SENT": {"PARTIALLY_FILLED", "CLOSED", "RECONCILIATION_REQUIRED", "ROLLED_BACK"},
    "RECONCILIATION_REQUIRED": {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELED", "CLOSED", "HELD", "BLOCKED"},
    "HELD": {"RISK_APPROVED", "SENT", "CLOSE_SENT", "BLOCKED"},
    "BLOCKED": set(), "CLOSED": set(), "ROLLED_BACK": set(),
}
REQUIRED_FIELDS = {
    "order_intent_id", "client_order_id", "decision_id", "position_id", "strategy_id",
    "symbol", "side", "mode", "target_state", "quantity", "filled_quantity",
    "reduce_only", "risk_snapshot_sha256", "event_ts", "event_ts_ms", "idempotency_key",
    "reason_codes", "lease_owner", "fencing_token", "deadline_ms", "venue_event_id",
}
PRIVATE_TOKENS = {
    "api_key", "apikey", "secret", "credential", "password", "private_key",
    "account_id", "wallet", "access_token", "refresh_token",
}


class OmsContractError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise OmsContractError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, *, maximum: int = 240, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if not result and not allow_empty:
        _fail("STRING_REQUIRED", name)
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INT_REQUIRED", name)
    return value


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        _fail("NUMBER_INVALID", name)
    return result


def _timestamp(value: Any, expected_ms: int) -> str:
    text = _string(value, "event_ts", maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("EVENT_TIMESTAMP_INVALID", text)
    if parsed.tzinfo is None:
        _fail("EVENT_TIMESTAMP_TIMEZONE_REQUIRED")
    actual_ms = int(parsed.timestamp() * 1000)
    if abs(actual_ms - expected_ms) > 1000:
        _fail("EVENT_TIMESTAMP_MS_MISMATCH", f"{actual_ms}!={expected_ms}")
    return parsed.isoformat()


def _reject_private(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lower = str(key).lower()
            if any(token in lower for token in PRIVATE_TOKENS):
                _fail("PRIVATE_FIELD_FORBIDDEN", f"{path}.{key}")
            _reject_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private(child, f"{path}[{index}]")


def authority(mode: str) -> dict[str, Any]:
    return {
        "runtime_bound": False,
        "private_exchange_call_allowed": False,
        "live_allowed": False,
        "paper_canary_contract_allowed": mode == "PAPER_CANARY",
        "capital_activation_allowed": False,
        "execution_authority": "PAPER_SIMULATION_ONLY" if mode == "PAPER_CANARY" else "NONE",
        "order_authority": "BLOCKED",
    }


def normalize_command(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "command")
    missing = sorted(REQUIRED_FIELDS - set(raw))
    if missing:
        _fail("COMMAND_FIELDS_MISSING", ",".join(missing))
    _reject_private(raw)
    mode = _string(raw["mode"], "mode").upper()
    if mode not in MODES:
        _fail("MODE_FORBIDDEN", mode)
    target = _string(raw["target_state"], "target_state").upper()
    if target not in STATES:
        _fail("TARGET_STATE_INVALID", target)
    side = _string(raw["side"], "side").upper()
    if side not in {"LONG", "SHORT"}:
        _fail("SIDE_INVALID", side)
    quantity = _number(raw["quantity"], "quantity")
    if quantity <= 0:
        _fail("QUANTITY_MUST_BE_POSITIVE")
    filled = _number(raw["filled_quantity"], "filled_quantity")
    if filled > quantity:
        _fail("FILLED_EXCEEDS_QUANTITY")
    if not isinstance(raw["reduce_only"], bool):
        _fail("BOOL_REQUIRED", "reduce_only")
    event_ms = _integer(raw["event_ts_ms"], "event_ts_ms", minimum=1)
    deadline_ms = _integer(raw["deadline_ms"], "deadline_ms")
    fencing_token = _integer(raw["fencing_token"], "fencing_token", minimum=1)
    venue_event = _string(raw["venue_event_id"], "venue_event_id", maximum=200, allow_empty=True)
    if target in VENUE_CONFIRMED_STATES and not venue_event:
        _fail("VENUE_EVENT_ID_REQUIRED", target)
    if target in TIMEOUT_STATES and deadline_ms <= event_ms:
        _fail("FUTURE_DEADLINE_REQUIRED", target)
    if target == "PARTIALLY_FILLED" and not 0 < filled < quantity:
        _fail("PARTIAL_FILL_QUANTITY_INVALID")
    if target == "FILLED" and filled != quantity:
        _fail("FILLED_QUANTITY_MUST_EQUAL_QUANTITY")
    if target in {"CLOSE_SENT", "CLOSED"} and raw["reduce_only"] is not True:
        _fail("CLOSE_REQUIRES_REDUCE_ONLY")
    reasons = raw["reason_codes"]
    if not isinstance(reasons, list) or len(reasons) > 32:
        _fail("REASON_CODES_INVALID")
    command = {
        "schema_version": SCHEMA_VERSION,
        "order_intent_id": _string(raw["order_intent_id"], "order_intent_id"),
        "client_order_id": _string(raw["client_order_id"], "client_order_id"),
        "decision_id": _string(raw["decision_id"], "decision_id"),
        "position_id": _string(raw["position_id"], "position_id"),
        "strategy_id": _string(raw["strategy_id"], "strategy_id"),
        "symbol": _string(raw["symbol"], "symbol", maximum=30).upper(),
        "side": side,
        "mode": mode,
        "target_state": target,
        "quantity": quantity,
        "filled_quantity": filled,
        "reduce_only": raw["reduce_only"],
        "risk_snapshot_sha256": _sha(raw["risk_snapshot_sha256"], "risk_snapshot_sha256"),
        "event_ts": _timestamp(raw["event_ts"], event_ms),
        "event_ts_ms": event_ms,
        "idempotency_key": _string(raw["idempotency_key"], "idempotency_key"),
        "reason_codes": sorted({_string(item, "reason_codes[]", maximum=100) for item in reasons}),
        "lease_owner": _string(raw["lease_owner"], "lease_owner", maximum=120),
        "fencing_token": fencing_token,
        "deadline_ms": deadline_ms,
        "venue_event_id": venue_event,
        "authority": authority(mode),
    }
    supplied = raw.get("authority", command["authority"])
    if not isinstance(supplied, Mapping):
        _fail("OBJECT_REQUIRED", "authority")
    for key, expected in command["authority"].items():
        if supplied.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    command["command_sha256"] = canonical_sha(command)
    return command


def normalize_venue_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "venue_snapshot")
    _reject_private(raw)
    required = {
        "source_ref", "source_sha256", "observed_at_ms", "venue_event_id", "client_order_id",
        "symbol", "side", "state", "quantity", "filled_quantity", "reduce_only",
    }
    missing = sorted(required - set(raw))
    if missing:
        _fail("VENUE_SNAPSHOT_FIELDS_MISSING", ",".join(missing))
    state = _string(raw["state"], "venue.state").upper()
    if state not in STATES:
        _fail("VENUE_STATE_INVALID", state)
    side = _string(raw["side"], "venue.side").upper()
    if side not in {"LONG", "SHORT"}:
        _fail("VENUE_SIDE_INVALID")
    quantity = _number(raw["quantity"], "venue.quantity")
    filled = _number(raw["filled_quantity"], "venue.filled_quantity")
    if filled > quantity:
        _fail("VENUE_FILLED_EXCEEDS_QUANTITY")
    if not isinstance(raw["reduce_only"], bool):
        _fail("BOOL_REQUIRED", "venue.reduce_only")
    snapshot = {
        "source_ref": _string(raw["source_ref"], "venue.source_ref", maximum=300),
        "source_sha256": _sha(raw["source_sha256"], "venue.source_sha256"),
        "observed_at_ms": _integer(raw["observed_at_ms"], "venue.observed_at_ms", minimum=1),
        "venue_event_id": _string(raw["venue_event_id"], "venue.venue_event_id"),
        "client_order_id": _string(raw["client_order_id"], "venue.client_order_id"),
        "symbol": _string(raw["symbol"], "venue.symbol", maximum=30).upper(),
        "side": side,
        "state": state,
        "quantity": quantity,
        "filled_quantity": filled,
        "reduce_only": raw["reduce_only"],
    }
    snapshot["snapshot_sha256"] = canonical_sha(snapshot)
    return snapshot


def normalize_manual_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "manual_receipt")
    _reject_private(raw)
    required = {"receipt_id", "human_approved", "reason", "evidence_sha256", "issued_at_ms"}
    missing = sorted(required - set(raw))
    if missing:
        _fail("MANUAL_RECEIPT_FIELDS_MISSING", ",".join(missing))
    if raw["human_approved"] is not True:
        _fail("HUMAN_APPROVAL_REQUIRED")
    receipt = {
        "receipt_id": _string(raw["receipt_id"], "receipt_id"),
        "human_approved": True,
        "reason": _string(raw["reason"], "reason", maximum=500),
        "evidence_sha256": _sha(raw["evidence_sha256"], "evidence_sha256"),
        "issued_at_ms": _integer(raw["issued_at_ms"], "issued_at_ms", minimum=1),
    }
    receipt["receipt_sha256"] = canonical_sha(receipt)
    return receipt
