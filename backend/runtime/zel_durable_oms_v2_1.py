from __future__ import annotations

from typing import Any

from backend.contracts.zel_oms_command_v2 import TIMEOUT_STATES, canonical_sha
from backend.runtime.zel_durable_oms_v2 import DurableOmsCoordinator

EXTENDED_TIMEOUT_STATES = set(TIMEOUT_STATES) | {"PARTIALLY_FILLED"}


class DurableOmsCoordinatorV2_1(DurableOmsCoordinator):
    """V2.1 treats unfinished partial fills as timeout-governed states."""

    def recovery_scan(self, now_ms: int) -> dict[str, Any]:
        with self._connect() as connection:
            stale_leases = [dict(row) for row in connection.execute(
                "SELECT * FROM oms_leases WHERE expires_at_ms<? ORDER BY position_id", (now_ms,)
            )]
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM oms_orders WHERE terminal=0 AND deadline_ms>0 AND deadline_ms<? ORDER BY order_intent_id",
                (now_ms,),
            )]
            timeouts = [row for row in rows if row["state"] in EXTENDED_TIMEOUT_STATES]
            nonterminal = [dict(row) for row in connection.execute(
                "SELECT * FROM oms_orders WHERE terminal=0 ORDER BY order_intent_id"
            )]
        return {
            "schema_version": "zel.oms.recovery_scan.v1.1",
            "now_ms": now_ms,
            "stale_lease_count": len(stale_leases),
            "timeout_order_count": len(timeouts),
            "partial_fill_timeout_count": sum(row["state"] == "PARTIALLY_FILLED" for row in timeouts),
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
                if row["state"] not in EXTENDED_TIMEOUT_STATES:
                    continue
                payload = {
                    "reason": "STATE_DEADLINE_EXPIRED",
                    "prior_state": row["state"],
                    "partial_fill_incomplete": row["state"] == "PARTIALLY_FILLED",
                }
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
