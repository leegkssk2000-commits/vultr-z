from __future__ import annotations

import copy
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.contracts.zel_oms_command_v2 import (
    TERMINAL_STATES,
    TIMEOUT_STATES,
    TRANSITIONS,
    OmsContractError,
    canonical_json,
    canonical_sha,
    normalize_command,
    normalize_manual_receipt,
    normalize_venue_snapshot,
)

SCHEMA_VERSION = "zel.durable_oms.v2"
IDENTITY_FIELDS = ("client_order_id", "decision_id", "position_id", "strategy_id", "symbol", "side", "mode")


class DurableOmsError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise DurableOmsError(f"{code}:{detail}" if detail else code)


class PrivateExchangeAdapterBlocked:
    def execute(self, *_: Any, **__: Any) -> None:
        _fail("PRIVATE_EXCHANGE_CALL_BLOCKED")


class DurableOmsCoordinator:
    """Single transactional truth for simulation/Paper contracts. No exchange I/O."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS oms_leases (
                    position_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    acquired_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oms_orders (
                    order_intent_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL UNIQUE,
                    decision_id TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    state TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    filled_quantity REAL NOT NULL,
                    reduce_only INTEGER NOT NULL,
                    risk_snapshot_sha256 TEXT NOT NULL,
                    deadline_ms INTEGER NOT NULL,
                    venue_event_id TEXT NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    terminal INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS oms_events (
                    event_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_intent_id TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    event_ts_ms INTEGER NOT NULL,
                    command_sha256 TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(order_intent_id) REFERENCES oms_orders(order_intent_id)
                );
                CREATE TABLE IF NOT EXISTS oms_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    command_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oms_manual_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    order_intent_id TEXT NOT NULL,
                    receipt_sha256 TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    FOREIGN KEY(order_intent_id) REFERENCES oms_orders(order_intent_id)
                );
                CREATE TABLE IF NOT EXISTS oms_reconciliation (
                    reconcile_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_intent_id TEXT NOT NULL,
                    observed_at_ms INTEGER NOT NULL,
                    venue_event_id TEXT NOT NULL,
                    snapshot_sha256 TEXT NOT NULL,
                    mismatch_json TEXT NOT NULL,
                    pass INTEGER NOT NULL,
                    FOREIGN KEY(order_intent_id) REFERENCES oms_orders(order_intent_id)
                );
                """
            )

    def acquire_lease(self, position_id: str, owner: str, now_ms: int, ttl_ms: int) -> dict[str, Any]:
        if not position_id or not owner or now_ms <= 0 or ttl_ms <= 0:
            _fail("LEASE_INPUT_INVALID")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM oms_leases WHERE position_id=?", (position_id,)
            ).fetchone()
            if current is not None and int(current["expires_at_ms"]) > now_ms and current["owner"] != owner:
                _fail("LEASE_HELD_BY_OTHER", str(current["owner"]))
            if current is None:
                token = 1
            elif current["owner"] == owner and int(current["expires_at_ms"]) > now_ms:
                token = int(current["fencing_token"])
            else:
                token = int(current["fencing_token"]) + 1
            expires = now_ms + ttl_ms
            connection.execute(
                """INSERT INTO oms_leases(position_id,owner,fencing_token,acquired_at_ms,expires_at_ms)
                VALUES(?,?,?,?,?) ON CONFLICT(position_id) DO UPDATE SET
                owner=excluded.owner,fencing_token=excluded.fencing_token,
                acquired_at_ms=excluded.acquired_at_ms,expires_at_ms=excluded.expires_at_ms""",
                (position_id, owner, token, now_ms, expires),
            )
            connection.commit()
            return {
                "position_id": position_id, "owner": owner, "fencing_token": token,
                "acquired_at_ms": now_ms, "expires_at_ms": expires,
                "execution_authority": "NONE", "order_authority": "BLOCKED",
            }

    @staticmethod
    def _lease(connection: sqlite3.Connection, position_id: str, owner: str, token: int, at_ms: int) -> None:
        lease = connection.execute(
            "SELECT * FROM oms_leases WHERE position_id=?", (position_id,)
        ).fetchone()
        if lease is None:
            _fail("LEASE_MISSING", position_id)
        if lease["owner"] != owner:
            _fail("LEASE_OWNER_MISMATCH")
        if int(lease["fencing_token"]) != token:
            _fail("FENCING_TOKEN_STALE")
        if int(lease["expires_at_ms"]) < at_ms:
            _fail("LEASE_EXPIRED")

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        order_intent_id: str,
        from_state: str | None,
        to_state: str,
        event_ts_ms: int,
        command_sha: str,
        payload: Mapping[str, Any],
    ) -> str:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "order_intent_id": order_intent_id,
            "from_state": from_state,
            "to_state": to_state,
            "event_ts_ms": event_ts_ms,
            "command_sha256": command_sha,
            "payload": dict(payload),
        }
        receipt_sha = canonical_sha(receipt)
        connection.execute(
            """INSERT INTO oms_events(order_intent_id,from_state,to_state,event_ts_ms,
            command_sha256,result_sha256,payload_json) VALUES(?,?,?,?,?,?,?)""",
            (order_intent_id, from_state, to_state, event_ts_ms, command_sha, receipt_sha, canonical_json(receipt)),
        )
        return receipt_sha

    def apply(self, value: Mapping[str, Any]) -> dict[str, Any]:
        command = normalize_command(value)
        command_sha = command["command_sha256"]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT command_sha256,result_json FROM oms_idempotency WHERE idempotency_key=?",
                (command["idempotency_key"],),
            ).fetchone()
            if prior is not None:
                if prior["command_sha256"] != command_sha:
                    _fail("IDEMPOTENCY_PAYLOAD_CONFLICT", command["idempotency_key"])
                result = json.loads(prior["result_json"])
                result["replayed"] = True
                connection.commit()
                return result
            self._lease(
                connection, command["position_id"], command["lease_owner"],
                command["fencing_token"], command["event_ts_ms"],
            )
            current = connection.execute(
                "SELECT * FROM oms_orders WHERE order_intent_id=?", (command["order_intent_id"],)
            ).fetchone()
            state = current["state"] if current is not None else None
            if command["target_state"] not in TRANSITIONS[state]:
                _fail("OMS_TRANSITION_FORBIDDEN", f"{state}->{command['target_state']}")
            version = 1
            if current is not None:
                for field in IDENTITY_FIELDS:
                    if command[field] != current[field]:
                        _fail("OMS_IDENTITY_DRIFT", field)
                if command["filled_quantity"] < float(current["filled_quantity"]):
                    _fail("FILLED_QUANTITY_REGRESSION")
                if command["event_ts_ms"] < int(current["updated_at_ms"]):
                    _fail("OMS_TIMESTAMP_REGRESSION")
                if int(current["terminal"]):
                    _fail("OMS_EVENT_AFTER_TERMINAL")
                version = int(current["version"]) + 1
            terminal = int(command["target_state"] in TERMINAL_STATES)
            values = (
                command["client_order_id"], command["decision_id"], command["position_id"],
                command["strategy_id"], command["symbol"], command["side"], command["mode"],
                command["target_state"], command["quantity"], command["filled_quantity"],
                int(command["reduce_only"]), command["risk_snapshot_sha256"], command["deadline_ms"],
                command["venue_event_id"], command["event_ts_ms"], command["fencing_token"], version, terminal,
            )
            if current is None:
                connection.execute(
                    """INSERT INTO oms_orders(order_intent_id,client_order_id,decision_id,position_id,
                    strategy_id,symbol,side,mode,state,quantity,filled_quantity,reduce_only,
                    risk_snapshot_sha256,deadline_ms,venue_event_id,updated_at_ms,fencing_token,version,terminal)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (command["order_intent_id"], *values),
                )
            else:
                connection.execute(
                    """UPDATE oms_orders SET client_order_id=?,decision_id=?,position_id=?,strategy_id=?,
                    symbol=?,side=?,mode=?,state=?,quantity=?,filled_quantity=?,reduce_only=?,
                    risk_snapshot_sha256=?,deadline_ms=?,venue_event_id=?,updated_at_ms=?,
                    fencing_token=?,version=?,terminal=? WHERE order_intent_id=?""",
                    (*values, command["order_intent_id"]),
                )
            receipt_sha = self._insert_event(
                connection, command["order_intent_id"], state, command["target_state"],
                command["event_ts_ms"], command_sha,
                {"reason_codes": command["reason_codes"], "venue_event_id": command["venue_event_id"]},
            )
            result = {
                "schema_version": SCHEMA_VERSION,
                "order_intent_id": command["order_intent_id"],
                "position_id": command["position_id"],
                "from_state": state, "to_state": command["target_state"],
                "quantity": command["quantity"], "filled_quantity": command["filled_quantity"],
                "version": version, "fencing_token": command["fencing_token"],
                "receipt_sha256": receipt_sha, "replayed": False,
                "private_exchange_call_performed": False,
                "capital_activation_allowed": False,
                "execution_authority": command["authority"]["execution_authority"],
                "order_authority": "BLOCKED",
            }
            connection.execute(
                "INSERT INTO oms_idempotency(idempotency_key,command_sha256,result_json) VALUES(?,?,?)",
                (command["idempotency_key"], command_sha, canonical_json(result)),
            )
            connection.commit()
            return result

    def status(self, order_intent_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM oms_orders WHERE order_intent_id=?", (order_intent_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def event_count(self, order_intent_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM oms_events WHERE order_intent_id=?", (order_intent_id,)
            ).fetchone()
            return int(row["n"])

    def recovery_scan(self, now_ms: int) -> dict[str, Any]:
        with self._connect() as connection:
            stale_leases = [dict(row) for row in connection.execute(
                "SELECT * FROM oms_leases WHERE expires_at_ms<? ORDER BY position_id", (now_ms,)
            )]
            timeouts = [dict(row) for row in connection.execute(
                "SELECT * FROM oms_orders WHERE terminal=0 AND deadline_ms>0 AND deadline_ms<? ORDER BY order_intent_id",
                (now_ms,),
            ) if row["state"] in TIMEOUT_STATES]
            nonterminal = [dict(row) for row in connection.execute(
                "SELECT * FROM oms_orders WHERE terminal=0 ORDER BY order_intent_id"
            )]
        return {
            "schema_version": "zel.oms.recovery_scan.v1",
            "now_ms": now_ms,
            "stale_lease_count": len(stale_leases),
            "timeout_order_count": len(timeouts),
            "nonterminal_order_count": len(nonterminal),
            "stale_leases": stale_leases,
            "timeout_orders": timeouts,
            "nonterminal_orders": nonterminal,
            "recommended_action": "hold" if timeouts or stale_leases else "resume",
            "private_exchange_call_performed": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }

    def mark_timeouts_for_reconciliation(self, now_ms: int) -> dict[str, Any]:
        changed: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = list(connection.execute(
                "SELECT * FROM oms_orders WHERE terminal=0 AND deadline_ms>0 AND deadline_ms<? ORDER BY order_intent_id",
                (now_ms,),
            ))
            for row in rows:
                if row["state"] not in TIMEOUT_STATES:
                    continue
                payload = {"reason": "STATE_DEADLINE_EXPIRED", "prior_state": row["state"]}
                command_sha = canonical_sha(payload)
                self._insert_event(
                    connection, row["order_intent_id"], row["state"], "RECONCILIATION_REQUIRED",
                    now_ms, command_sha, payload,
                )
                connection.execute(
                    "UPDATE oms_orders SET state='RECONCILIATION_REQUIRED',updated_at_ms=?,version=version+1 WHERE order_intent_id=?",
                    (now_ms, row["order_intent_id"]),
                )
                changed.append(row["order_intent_id"])
            connection.commit()
        return {
            "state": "PASS_TIMEOUTS_MARKED_FOR_RECONCILIATION",
            "changed_order_intent_ids": changed,
            "private_exchange_call_performed": False,
            "action": "hold",
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }

    def reconcile(self, order_intent_id: str, snapshot_value: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = normalize_venue_snapshot(snapshot_value)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            local = connection.execute(
                "SELECT * FROM oms_orders WHERE order_intent_id=?", (order_intent_id,)
            ).fetchone()
            if local is None:
                _fail("ORDER_NOT_FOUND", order_intent_id)
            comparisons = {
                "client_order_id": local["client_order_id"], "symbol": local["symbol"],
                "side": local["side"], "state": local["state"],
                "quantity": float(local["quantity"]), "filled_quantity": float(local["filled_quantity"]),
                "reduce_only": bool(local["reduce_only"]),
            }
            mismatches = sorted(key for key, expected in comparisons.items() if snapshot[key] != expected)
            passed = not mismatches
            connection.execute(
                """INSERT INTO oms_reconciliation(order_intent_id,observed_at_ms,venue_event_id,
                snapshot_sha256,mismatch_json,pass) VALUES(?,?,?,?,?,?)""",
                (order_intent_id, snapshot["observed_at_ms"], snapshot["venue_event_id"],
                 snapshot["snapshot_sha256"], canonical_json(mismatches), int(passed)),
            )
            if not passed and local["state"] not in TERMINAL_STATES:
                self._insert_event(
                    connection, order_intent_id, local["state"], "RECONCILIATION_REQUIRED",
                    snapshot["observed_at_ms"], snapshot["snapshot_sha256"],
                    {"mismatch_fields": mismatches, "venue_event_id": snapshot["venue_event_id"]},
                )
                connection.execute(
                    "UPDATE oms_orders SET state='RECONCILIATION_REQUIRED',updated_at_ms=?,version=version+1 WHERE order_intent_id=?",
                    (snapshot["observed_at_ms"], order_intent_id),
                )
            connection.commit()
        return {
            "schema_version": "zel.oms.reconciliation.v2",
            "order_intent_id": order_intent_id,
            "pass": passed,
            "mismatch_fields": mismatches,
            "unreconciled_position_count": int(not passed),
            "action": "hold" if not passed else "resume",
            "private_exchange_call_performed": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }

    def record_manual_desync(self, order_intent_id: str, receipt_value: Mapping[str, Any]) -> dict[str, Any]:
        receipt = normalize_manual_receipt(receipt_value)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            local = connection.execute(
                "SELECT * FROM oms_orders WHERE order_intent_id=?", (order_intent_id,)
            ).fetchone()
            if local is None:
                _fail("ORDER_NOT_FOUND", order_intent_id)
            connection.execute(
                "INSERT INTO oms_manual_receipts(receipt_id,order_intent_id,receipt_sha256,receipt_json) VALUES(?,?,?,?)",
                (receipt["receipt_id"], order_intent_id, receipt["receipt_sha256"], canonical_json(receipt)),
            )
            if local["state"] not in TERMINAL_STATES and local["state"] != "RECONCILIATION_REQUIRED":
                self._insert_event(
                    connection, order_intent_id, local["state"], "RECONCILIATION_REQUIRED",
                    receipt["issued_at_ms"], receipt["receipt_sha256"],
                    {"reason": receipt["reason"], "receipt_id": receipt["receipt_id"]},
                )
                connection.execute(
                    "UPDATE oms_orders SET state='RECONCILIATION_REQUIRED',updated_at_ms=?,version=version+1 WHERE order_intent_id=?",
                    (receipt["issued_at_ms"], order_intent_id),
                )
            connection.commit()
        return {
            "state": "PASS_MANUAL_DESYNC_RECEIPT_BOUND",
            "order_intent_id": order_intent_id,
            "receipt_sha256": receipt["receipt_sha256"],
            "action": "hold",
            "private_exchange_call_performed": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }
