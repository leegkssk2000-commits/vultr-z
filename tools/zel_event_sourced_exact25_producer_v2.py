from __future__ import annotations

import copy
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tools.zel_event_sourced_exact25_producer_v1 as base
from backend.contracts.zel_event_sourced_shadow_v2 import canonical_sha
from backend.runtime.zel_shadow_event_journal_v2 import (
    SqliteShadowEventJournalV2,
    build_event_v2,
)

VERSION = "ZEL_EVENT_SOURCED_EXACT25_PRODUCER_V2"


class EventSourcedProducerHooksV2(base.EventSourcedProducerHooks):
    journal: SqliteShadowEventJournalV2

    def _emit(
        self,
        identity: Mapping[str, Any],
        event_type: str,
        event_ts: str,
        payload: Mapping[str, Any],
        *,
        skill_set: list[str] | None = None,
    ) -> dict[str, Any]:
        event_identity = copy.deepcopy(dict(identity))
        event_identity["runtime_bound"] = True
        if skill_set is not None:
            event_identity["skill_set"] = list(skill_set)
        raw = build_event_v2(event_identity, event_type, event_ts, payload, self.journal)
        return self.journal.append(raw)

    def append_jsonl_once(self, path: Path, row: Mapping[str, Any]) -> bool:
        appended = self.original_append_jsonl_once(path, row)
        if row.get("schema") != "q4r3_exact25_dedicated_shadow_close_v1":
            return appended
        key = str(row.get("event_id") or "")
        pending = self.pending_close.get(key)
        if pending is None:
            identity = {
                "decision_id": row.get("decision_id"),
                "position_id": row.get("position_id"),
                "strategy_id": row.get("strategy_id"),
                "strategy_source_sha256": row.get("owner_sha256"),
                "method_id": row.get("method_id"),
                "skill_set": row.get("skill_set") or [],
                "team_id": row.get("team_id"),
                "symbol": row.get("symbol"),
                "side": str(row.get("side") or "").upper(),
                "market_snapshot_sha256": row.get("market_snapshot_sha256"),
                "risk_snapshot_sha256": row.get("risk_snapshot_sha256"),
                "source_ids": row.get("source_ids") or [],
                "runtime_bound": True,
            }
            if any(value in (None, "") for field, value in identity.items() if field not in {"skill_set", "runtime_bound"}):
                base._fail("CLOSE_EVENT_IDENTITY_MISSING", key)
            pending = {
                "identity": identity,
                "event_ts": str(row.get("exit_ts")),
                "row_sha256": canonical_sha(row),
            }
        identity = dict(pending["identity"])
        identity["runtime_bound"] = True
        event_ts = pending["event_ts"]
        context = self.journal.next_context(str(identity["position_id"]))
        if context and context["last_event_type"] == "shadow_close_requested":
            self._emit(identity, "shadow_closed", event_ts, {
                "close_row_sha256": pending["row_sha256"],
                "realized_R": row.get("realized_R"),
                "exit_reason": row.get("exit_reason"),
            })
        context = self.journal.next_context(str(identity["position_id"]))
        if context and context["last_event_type"] == "shadow_closed":
            self._emit(identity, "shadow_ledger_joined", event_ts, {
                "shadow_ledger_path": str(path),
                "close_row_sha256": pending["row_sha256"],
                "append_was_new": appended,
            })
        self.pending_close.pop(key, None)
        self.write_status()
        return appended

    def write_status(self) -> None:
        coverage = self.journal.coverage()
        projection = self.journal.sync_projection()
        status = {
            "schema_version": "zel.event_sourced_exact25_producer.status.v2",
            "version": VERSION,
            "producer_blob_sha": self.producer_blob_sha,
            "event_database": str(self.journal.database_path),
            "event_projection": str(self.journal.projection_path),
            "event_count": projection["event_count"],
            "projection_sha256": projection["projection_sha256"],
            "unresolved_signal_count": self.unresolved_signal_count,
            "coverage": coverage,
            "polling_is_proof_authority": False,
            "shadow_ledger_is_formal_ledger": False,
            "runtime_bound": True,
            "paper_allowed": False,
            "live_allowed": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }
        base.atomic_json(self.status_path, status)


def main() -> int:
    if os.environ.get("ZEL_EVENT_SOURCED_SHADOW") != "1":
        base._fail("EVENT_SOURCED_SHADOW_ENV_REQUIRED")
    wrapper, producer_args = base.parse_wrapper_args(sys.argv[1:])
    module = base.load_producer(wrapper.producer_source.resolve(), wrapper.producer_blob_sha)
    journal = SqliteShadowEventJournalV2(wrapper.event_db, wrapper.event_jsonl)

    original_identity = base.identity_for_position

    def runtime_identity(position: Mapping[str, Any], result: Mapping[str, Any], frame: Any) -> dict[str, Any]:
        identity = original_identity(position, result, frame)
        identity["runtime_bound"] = True
        return identity

    base.identity_for_position = runtime_identity
    hooks = EventSourcedProducerHooksV2(module, journal, wrapper.event_status, wrapper.producer_blob_sha)
    hooks.install()
    sys.argv = [str(wrapper.producer_source)] + producer_args
    try:
        module.main()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
