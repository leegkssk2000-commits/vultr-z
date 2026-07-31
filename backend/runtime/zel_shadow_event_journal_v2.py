from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from backend.contracts.zel_event_sourced_shadow_v2 import (
    NEXT_TYPES,
    canonical_json,
    canonical_sha,
    default_authority,
    seal_event,
)
from backend.runtime.zel_shadow_event_journal_v1 import (
    IDENTITY_FIELDS,
    SqliteShadowEventJournal,
    _fail,
)

SCHEMA_VERSION = "zel.shadow.event_journal.v2"


class SqliteShadowEventJournalV2(SqliteShadowEventJournal):
    """V2 distinguishes the producer Shadow ledger from the Formal Ledger."""

    def append(self, value: Mapping[str, Any]) -> dict[str, Any]:
        event = seal_event(value, require_sealed_sha=bool(value.get("event_sha256")))
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

    def coverage(self) -> dict[str, Any]:
        by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in self.events():
            by_position[event["position_id"]].append(event)
        opened = 0
        shadow_complete = 0
        formal_complete = 0
        non_admitted_terminal = 0
        incomplete: list[dict[str, Any]] = []
        shadow_required = {
            "strategy_signal_emitted", "admission_decided", "shadow_open_requested",
            "shadow_open_confirmed", "shadow_close_requested", "shadow_closed", "shadow_ledger_joined",
        }
        for position_id, rows in sorted(by_position.items()):
            types = {row["event_type"] for row in rows}
            last_type = rows[-1]["event_type"]
            if "shadow_open_confirmed" in types:
                opened += 1
                missing_shadow = sorted(shadow_required - types)
                if not missing_shadow:
                    shadow_complete += 1
                if "formal_ledger_joined" in types:
                    formal_complete += 1
                if missing_shadow or last_type not in {"shadow_ledger_joined", "formal_ledger_joined"}:
                    incomplete.append({
                        "position_id": position_id,
                        "missing_shadow_event_types": missing_shadow,
                        "formal_ledger_joined": "formal_ledger_joined" in types,
                        "last_event_type": last_type,
                    })
            elif last_type in {"held", "blocked", "rolled_back"}:
                non_admitted_terminal += 1
            else:
                incomplete.append({
                    "position_id": position_id,
                    "missing_shadow_event_types": [],
                    "formal_ledger_joined": False,
                    "last_event_type": last_type,
                })
        shadow_pct = 100.0 if opened == 0 else round(100.0 * shadow_complete / opened, 10)
        formal_pct = 100.0 if opened == 0 else round(100.0 * formal_complete / opened, 10)
        return {
            "schema_version": SCHEMA_VERSION,
            "position_chain_count": len(by_position),
            "opened_position_count": opened,
            "shadow_complete_position_count": shadow_complete,
            "formal_complete_position_count": formal_complete,
            "non_admitted_terminal_count": non_admitted_terminal,
            "shadow_event_lineage_coverage_pct": shadow_pct,
            "formal_ledger_lineage_coverage_pct": formal_pct,
            "incomplete_chain_count": len(incomplete),
            "incomplete_chains": incomplete,
            "shadow_pass": bool(by_position) and shadow_pct == 100.0 and not incomplete,
            "p1_pass": bool(by_position) and shadow_pct == 100.0 and formal_pct == 100.0 and not incomplete,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }


def build_event_v2(
    identity: Mapping[str, Any],
    event_type: str,
    event_ts: str,
    payload: Mapping[str, Any],
    journal: SqliteShadowEventJournalV2,
    *,
    formal_ledger_write_allowed: bool = False,
) -> dict[str, Any]:
    position_id = str(identity["position_id"])
    context = journal.next_context(position_id)
    sequence = context["sequence_no"] if context else 0
    parent = context["parent_event_id"] if context else ""
    event_id = "zel.shadow.runtime.v2." + hashlib.sha256(
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
        "authority": default_authority(
            runtime_bound=bool(identity.get("runtime_bound", False)),
            formal_ledger_write_allowed=formal_ledger_write_allowed,
        ),
    }
