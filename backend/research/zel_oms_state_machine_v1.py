from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "zel.oms.state_machine.v1"
MODES = {"SIMULATION", "PAPER_CANARY"}
STATES = {
    "INTENT_CREATED", "RISK_APPROVED", "SENT", "ACKNOWLEDGED", "PARTIALLY_FILLED",
    "FILLED", "CANCEL_REQUESTED", "CANCELED", "CLOSE_SENT", "CLOSED", "HELD",
    "BLOCKED", "RECONCILIATION_REQUIRED", "ROLLED_BACK",
}
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
REQUIRED = {
    "order_intent_id", "client_order_id", "decision_id", "position_id", "strategy_id",
    "symbol", "side", "mode", "target_state", "quantity", "filled_quantity", "reduce_only",
    "risk_snapshot_sha256", "event_ts", "idempotency_key", "reason_codes",
}


class OmsStateError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise OmsStateError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _string(value: Any, name: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if result < minimum or result != result or result in (float("inf"), float("-inf")):
        _fail("NUMBER_INVALID", name)
    return result


def normalize_command(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", "command")
    raw = dict(value)
    missing = sorted(REQUIRED - set(raw))
    if missing:
        _fail("COMMAND_FIELDS_MISSING", ",".join(missing))
    mode = _string(raw["mode"], "mode").upper()
    if mode not in MODES:
        _fail("MODE_FORBIDDEN", mode)
    target = _string(raw["target_state"], "target_state").upper()
    if target not in STATES:
        _fail("TARGET_STATE_INVALID", target)
    side = _string(raw["side"], "side").upper()
    if side not in {"LONG", "SHORT"}:
        _fail("SIDE_INVALID")
    quantity = _number(raw["quantity"], "quantity")
    if quantity <= 0:
        _fail("QUANTITY_MUST_BE_POSITIVE")
    filled = _number(raw["filled_quantity"], "filled_quantity")
    if filled > quantity:
        _fail("FILLED_EXCEEDS_QUANTITY")
    if not isinstance(raw["reduce_only"], bool):
        _fail("BOOL_REQUIRED", "reduce_only")
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
        "side": side, "mode": mode, "target_state": target,
        "quantity": quantity, "filled_quantity": filled, "reduce_only": raw["reduce_only"],
        "risk_snapshot_sha256": _sha(raw["risk_snapshot_sha256"], "risk_snapshot_sha256"),
        "event_ts": _string(raw["event_ts"], "event_ts", maximum=64),
        "idempotency_key": _string(raw["idempotency_key"], "idempotency_key"),
        "reason_codes": sorted({_string(item, "reason_codes[]", maximum=100) for item in reasons}),
        "authority": {
            "runtime_bound": False, "private_exchange_call_allowed": False,
            "live_allowed": False, "order_authority": "BLOCKED",
            "execution_authority": "PAPER_SIMULATION_ONLY" if mode == "PAPER_CANARY" else "NONE",
        },
    }
    supplied_authority = raw.get("authority", command["authority"])
    if not isinstance(supplied_authority, Mapping):
        _fail("OBJECT_REQUIRED", "authority")
    for key, expected in command["authority"].items():
        if supplied_authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    return command


class SqliteOmsStore:
    """Durable control proof. Records state only and performs no exchange I/O."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS oms_orders (
                    order_intent_id TEXT PRIMARY KEY, client_order_id TEXT NOT NULL UNIQUE,
                    position_id TEXT NOT NULL, strategy_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    side TEXT NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
                    quantity REAL NOT NULL, filled_quantity REAL NOT NULL, reduce_only INTEGER NOT NULL,
                    risk_snapshot_sha256 TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oms_idempotency (
                    idempotency_key TEXT PRIMARY KEY, command_sha256 TEXT NOT NULL, result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oms_events (
                    event_no INTEGER PRIMARY KEY AUTOINCREMENT, order_intent_id TEXT NOT NULL,
                    from_state TEXT, to_state TEXT NOT NULL, command_sha256 TEXT NOT NULL,
                    event_ts TEXT NOT NULL, result_sha256 TEXT NOT NULL,
                    FOREIGN KEY(order_intent_id) REFERENCES oms_orders(order_intent_id)
                );
                """
            )

    def apply(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        command = normalize_command(raw)
        command_sha = canonical_sha(command)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT command_sha256, result_json FROM oms_idempotency WHERE idempotency_key=?",
                (command["idempotency_key"],),
            ).fetchone()
            if prior is not None:
                if prior["command_sha256"] != command_sha:
                    _fail("IDEMPOTENCY_PAYLOAD_CONFLICT", command["idempotency_key"])
                result = json.loads(prior["result_json"])
                result["replayed"] = True
                connection.commit()
                return result
            current = connection.execute(
                "SELECT * FROM oms_orders WHERE order_intent_id=?", (command["order_intent_id"],)
            ).fetchone()
            current_state = current["state"] if current is not None else None
            if command["target_state"] not in TRANSITIONS[current_state]:
                _fail("OMS_TRANSITION_FORBIDDEN", f"{current_state}->{command['target_state']}")
            if current is not None:
                immutable = {
                    "client_order_id": current["client_order_id"], "position_id": current["position_id"],
                    "strategy_id": current["strategy_id"], "symbol": current["symbol"],
                    "side": current["side"], "mode": current["mode"],
                }
                for key, expected in immutable.items():
                    if command[key] != expected:
                        _fail("OMS_IDENTITY_DRIFT", key)
                if command["filled_quantity"] < float(current["filled_quantity"]):
                    _fail("FILLED_QUANTITY_REGRESSION")
                version = int(current["version"]) + 1
            else:
                version = 1
            if current is None:
                connection.execute(
                    """INSERT INTO oms_orders (
                        order_intent_id, client_order_id, position_id, strategy_id, symbol, side,
                        mode, state, quantity, filled_quantity, reduce_only, risk_snapshot_sha256,
                        updated_at, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (command["order_intent_id"], command["client_order_id"], command["position_id"],
                     command["strategy_id"], command["symbol"], command["side"], command["mode"],
                     command["target_state"], command["quantity"], command["filled_quantity"],
                     int(command["reduce_only"]), command["risk_snapshot_sha256"], command["event_ts"], version),
                )
            else:
                connection.execute(
                    """UPDATE oms_orders SET state=?, quantity=?, filled_quantity=?, reduce_only=?,
                    risk_snapshot_sha256=?, updated_at=?, version=? WHERE order_intent_id=?""",
                    (command["target_state"], command["quantity"], command["filled_quantity"],
                     int(command["reduce_only"]), command["risk_snapshot_sha256"], command["event_ts"],
                     version, command["order_intent_id"]),
                )
            result = {
                "schema_version": SCHEMA_VERSION, "order_intent_id": command["order_intent_id"],
                "client_order_id": command["client_order_id"], "position_id": command["position_id"],
                "from_state": current_state, "to_state": command["target_state"],
                "quantity": command["quantity"], "filled_quantity": command["filled_quantity"],
                "reduce_only": command["reduce_only"], "version": version,
                "command_sha256": command_sha, "replayed": False, "authority": command["authority"],
            }
            result["result_sha256"] = canonical_sha(result)
            connection.execute(
                "INSERT INTO oms_events (order_intent_id, from_state, to_state, command_sha256, event_ts, result_sha256) VALUES (?, ?, ?, ?, ?, ?)",
                (command["order_intent_id"], current_state, command["target_state"], command_sha,
                 command["event_ts"], result["result_sha256"]),
            )
            connection.execute(
                "INSERT INTO oms_idempotency (idempotency_key, command_sha256, result_json) VALUES (?, ?, ?)",
                (command["idempotency_key"], command_sha, canonical_json(result)),
            )
            connection.commit()
            return result

    def status(self, order_intent_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM oms_orders WHERE order_intent_id=?", (order_intent_id,)).fetchone()
            return dict(row) if row is not None else None

    def event_count(self, order_intent_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM oms_events WHERE order_intent_id=?", (order_intent_id,)).fetchone()
            return int(row["n"])


def reconciliation_report(local: Mapping[str, Any], venue: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(local, Mapping) or not isinstance(venue, Mapping):
        _fail("RECONCILIATION_OBJECT_REQUIRED")
    fields = ("symbol", "side", "quantity", "filled_quantity", "state")
    mismatches = [field for field in fields if local.get(field) != venue.get(field)]
    return {
        "schema_version": "zel.oms.reconciliation.v1", "mismatch_fields": mismatches,
        "unreconciled_position_count": int(bool(mismatches)), "action": "hold",
        "execution_authority": "NONE", "order_authority": "BLOCKED", "pass": not mismatches,
    }
