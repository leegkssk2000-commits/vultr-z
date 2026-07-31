from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.contracts.zel_event_sourced_shadow_v1 import NEXT_TYPES, canonical_json, canonical_sha, seal_event

SCHEMA_VERSION = "zel.shadow.event_journal.v1"
PRIVATE_TOKENS = {
    "api_key", "apikey", "secret", "credential", "password", "private_key",
    "account_id", "wallet", "access_token", "refresh_token",
}
IDENTITY_FIELDS = (
    "decision_id", "position_id", "strategy_id", "strategy_source_sha256",
    "method_id", "team_id", "symbol", "side",
)


class ShadowJournalError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ShadowJournalError(f"{code}:{detail}" if detail else code)


def _reject_private(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            text = str(key).lower()
            if any(token in text for token in PRIVATE_TOKENS):
                _fail("PRIVATE_FIELD_FORBIDDEN", f"{path}.{key}")
            _reject_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private(child, f"{path}[{index}]")


def _timestamp(value: str) -> str:
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        _fail("EVENT_TIMESTAMP_INVALID", text)
        raise AssertionError from exc
    if parsed.tzinfo is None:
        _fail("EVENT_TIMESTAMP_TIMEZONE_REQUIRED", text)
    return parsed.isoformat()


def strict_event(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = copy.deepcopy(dict(value))
    _reject_private(raw.get("payload", {}), "$.payload")
    sources = raw.get("source_ids")
    if not isinstance(sources, list) or not sources:
        _fail("SOURCE_IDS_REQUIRED")
    raw["event_ts"] = _timestamp(str(raw.get("event_ts") or ""))
    event = seal_event(raw, require_sealed_sha=bool(raw.get("event_sha256")))
    event["event_ts"] = raw["event_ts"]
    event.pop("event_sha256", None)
    event["event_sha256"] = canonical_sha(event)
    return event


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class SqliteShadowEventJournal:
    """SQLite is authoritative; JSONL is an atomic derived projection."""

    def __init__(self, database_path: str | Path, projection_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.projection_path = Path(projection_path)
        self.lock_path = self.projection_path.with_suffix(self.projection_path.suffix + ".lock")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.projection_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS shadow_events (
                    event_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    position_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    parent_event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_ts TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    event_sha256 TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL,
                    UNIQUE(position_id, sequence_no)
                );
                CREATE TABLE IF NOT EXISTS shadow_positions (
                    position_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_source_sha256 TEXT NOT NULL,
                    method_id TEXT NOT NULL,
                    team_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    last_event_id TEXT NOT NULL,
                    last_event_type TEXT NOT NULL,
                    last_sequence_no INTEGER NOT NULL,
                    last_event_ts TEXT NOT NULL,
                    terminal INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS shadow_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    command_sha256 TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES shadow_events(event_id)
                );
                """
            )

    def append(self, value: Mapping[str, Any]) -> dict[str, Any]:
        event = strict_event(value)
        command_sha = canonical_sha({key: child for key, child in event.items() if key != "event_sha256"})
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT command_sha256, event_id FROM shadow_idempotency WHERE idempotency_key=?",
                (event["idempotency_key"],),
            ).fetchone()
            if prior is not None:
                if prior["command_sha256"] != command_sha:
                    _fail("IDEMPOTENCY_PAYLOAD_CONFLICT", event["idempotency_key"])
                row = connection.execute(
                    "SELECT event_json FROM shadow_events WHERE event_id=?", (prior["event_id"],)
                ).fetchone()
                connection.commit()
                replay = json.loads(row["event_json"])
                replay["replayed"] = True
                self.sync_projection()
                return replay

            current = connection.execute(
                "SELECT * FROM shadow_positions WHERE position_id=?", (event["position_id"],)
            ).fetchone()
            previous_type = current["last_event_type"] if current is not None else None
            expected_sequence = int(current["last_sequence_no"]) + 1 if current is not None else 0
            expected_parent = current["last_event_id"] if current is not None else ""
            if event["sequence_no"] != expected_sequence:
                _fail("SEQUENCE_GAP", f"{event['position_id']}:{expected_sequence}->{event['sequence_no']}")
            if event["parent_event_id"] != expected_parent:
                _fail("PARENT_EVENT_MISMATCH", event["position_id"])
            if event["event_type"] not in NEXT_TYPES[previous_type]:
                _fail("EVENT_TRANSITION_FORBIDDEN", f"{previous_type}->{event['event_type']}")
            if current is not None:
                for field in IDENTITY_FIELDS:
                    if event[field] != current[field]:
                        _fail("POSITION_IDENTITY_DRIFT", field)
                if event["event_ts"] < current["last_event_ts"]:
                    _fail("EVENT_TIMESTAMP_REGRESSION", event["position_id"])
                if int(current["terminal"]):
                    _fail("EVENT_AFTER_TERMINAL", event["position_id"])

            event_json = canonical_json(event)
            connection.execute(
                """INSERT INTO shadow_events (
                    event_id, position_id, sequence_no, parent_event_id, event_type,
                    event_ts, idempotency_key, event_sha256, event_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["event_id"], event["position_id"], event["sequence_no"],
                    event["parent_event_id"], event["event_type"], event["event_ts"],
                    event["idempotency_key"], event["event_sha256"], event_json,
                ),
            )
            terminal = int(event["event_type"] in {"formal_ledger_joined", "blocked", "rolled_back"})
            if current is None:
                connection.execute(
                    """INSERT INTO shadow_positions (
                        position_id, decision_id, strategy_id, strategy_source_sha256,
                        method_id, team_id, symbol, side, last_event_id, last_event_type,
                        last_sequence_no, last_event_ts, terminal
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event["position_id"], event["decision_id"], event["strategy_id"],
                        event["strategy_source_sha256"], event["method_id"], event["team_id"],
                        event["symbol"], event["side"], event["event_id"], event["event_type"],
                        event["sequence_no"], event["event_ts"], terminal,
                    ),
                )
            else:
                connection.execute(
                    """UPDATE shadow_positions SET last_event_id=?, last_event_type=?,
                    last_sequence_no=?, last_event_ts=?, terminal=? WHERE position_id=?""",
                    (
                        event["event_id"], event["event_type"], event["sequence_no"],
                        event["event_ts"], terminal, event["position_id"],
                    ),
                )
            connection.execute(
                "INSERT INTO shadow_idempotency (idempotency_key, command_sha256, event_id) VALUES (?, ?, ?)",
                (event["idempotency_key"], command_sha, event["event_id"]),
            )
            connection.commit()
        self.sync_projection()
        result = copy.deepcopy(event)
        result["replayed"] = False
        return result

    def next_context(self, position_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM shadow_positions WHERE position_id=?", (position_id,)
            ).fetchone()
            if row is None:
                return None
            return {
                "parent_event_id": row["last_event_id"],
                "sequence_no": int(row["last_sequence_no"]) + 1,
                "last_event_type": row["last_event_type"],
                "last_event_ts": row["last_event_ts"],
                "terminal": bool(row["terminal"]),
            }

    def events(self, position_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT event_json FROM shadow_events"
        params: tuple[Any, ...] = ()
        if position_id is not None:
            query += " WHERE position_id=?"
            params = (position_id,)
        query += " ORDER BY event_no"
        with self._connect() as connection:
            return [json.loads(row["event_json"]) for row in connection.execute(query, params)]

    def sync_projection(self) -> dict[str, Any]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            rows = self.events()
            text = "".join(canonical_json(row) + "\n" for row in rows)
            _atomic_text(self.projection_path, text)
            return {
                "event_count": len(rows),
                "projection_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "projection_path": str(self.projection_path),
            }

    def coverage(self) -> dict[str, Any]:
        by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in self.events():
            by_position[event["position_id"]].append(event)
        opened = 0
        complete_opened = 0
        non_admitted_terminal = 0
        incomplete: list[dict[str, Any]] = []
        required_opened = {
            "strategy_signal_emitted", "admission_decided", "shadow_open_requested",
            "shadow_open_confirmed", "shadow_close_requested", "shadow_closed", "formal_ledger_joined",
        }
        for position_id, rows in sorted(by_position.items()):
            types = {row["event_type"] for row in rows}
            last_type = rows[-1]["event_type"]
            if "shadow_open_confirmed" in types:
                opened += 1
                missing = sorted(required_opened - types)
                if not missing and last_type == "formal_ledger_joined":
                    complete_opened += 1
                else:
                    incomplete.append({"position_id": position_id, "missing_event_types": missing, "last_event_type": last_type})
            elif last_type in {"held", "blocked", "rolled_back"}:
                non_admitted_terminal += 1
            else:
                incomplete.append({"position_id": position_id, "missing_event_types": [], "last_event_type": last_type})
        coverage = 100.0 if opened == 0 else round(100.0 * complete_opened / opened, 10)
        return {
            "schema_version": SCHEMA_VERSION,
            "position_chain_count": len(by_position),
            "opened_position_count": opened,
            "complete_opened_position_count": complete_opened,
            "non_admitted_terminal_count": non_admitted_terminal,
            "event_lineage_coverage_pct": coverage,
            "incomplete_chain_count": len(incomplete),
            "incomplete_chains": incomplete,
            "pass": bool(by_position) and coverage == 100.0 and not incomplete,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }


def build_event(identity: Mapping[str, Any], event_type: str, event_ts: str, payload: Mapping[str, Any], journal: SqliteShadowEventJournal) -> dict[str, Any]:
    position_id = str(identity["position_id"])
    context = journal.next_context(position_id)
    sequence = context["sequence_no"] if context else 0
    parent = context["parent_event_id"] if context else ""
    event_id = "zel.shadow.runtime." + hashlib.sha256(
        f"{position_id}|{sequence}|{event_type}".encode("utf-8")
    ).hexdigest()[:32]
    return {
        "event_id": event_id,
        "parent_event_id": parent,
        "decision_id": identity["decision_id"],
        "position_id": position_id,
        "strategy_id": identity["strategy_id"],
        "strategy_source_sha256": identity["strategy_source_sha256"],
        "method_id": identity["method_id"],
        "skill_set": list(identity.get("skill_set") or []),
        "team_id": identity["team_id"],
        "symbol": identity["symbol"],
        "side": identity["side"],
        "market_snapshot_sha256": identity["market_snapshot_sha256"],
        "risk_snapshot_sha256": identity["risk_snapshot_sha256"],
        "sequence_no": sequence,
        "event_ts": event_ts,
        "idempotency_key": f"{position_id}:{sequence}:{event_type}",
        "event_type": event_type,
        "payload": dict(payload),
        "source_ids": list(identity["source_ids"]),
    }
