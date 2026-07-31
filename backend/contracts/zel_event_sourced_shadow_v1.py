from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "zel.shadow.event.v1"
EVENT_TYPES = {
    "strategy_signal_emitted", "admission_decided", "shadow_open_requested",
    "shadow_open_confirmed", "skill_triggered", "skill_blocked", "shadow_managed",
    "shadow_close_requested", "shadow_closed", "formal_ledger_joined", "held",
    "blocked", "rolled_back",
}
REQUIRED_FIELDS = {
    "event_id", "parent_event_id", "decision_id", "position_id", "strategy_id",
    "strategy_source_sha256", "method_id", "skill_set", "team_id", "symbol", "side",
    "market_snapshot_sha256", "risk_snapshot_sha256", "sequence_no", "event_ts",
    "idempotency_key", "event_type", "payload", "source_ids",
}
NEXT_TYPES = {
    None: {"strategy_signal_emitted"},
    "strategy_signal_emitted": {"admission_decided", "held", "blocked"},
    "admission_decided": {"shadow_open_requested", "held", "blocked"},
    "shadow_open_requested": {"shadow_open_confirmed", "held", "blocked", "rolled_back"},
    "shadow_open_confirmed": {"skill_triggered", "skill_blocked", "shadow_managed", "shadow_close_requested", "held", "blocked"},
    "skill_triggered": {"shadow_managed", "shadow_close_requested", "held", "blocked"},
    "skill_blocked": {"shadow_managed", "shadow_close_requested", "held", "blocked"},
    "shadow_managed": {"skill_triggered", "skill_blocked", "shadow_managed", "shadow_close_requested", "held", "blocked"},
    "shadow_close_requested": {"shadow_closed", "held", "blocked", "rolled_back"},
    "shadow_closed": {"formal_ledger_joined", "held", "blocked"},
    "held": {"admission_decided", "shadow_open_requested", "shadow_managed", "shadow_close_requested", "blocked"},
    "formal_ledger_joined": set(), "blocked": set(), "rolled_back": set(),
}


class ShadowEventError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ShadowEventError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _string(value: Any, name: str, *, maximum: int = 300, allow_empty: bool = False) -> str:
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
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _list_of_strings(value: Any, name: str, *, maximum_items: int = 64) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        _fail("STRING_LIST_REQUIRED", name)
    return sorted({_string(item, f"{name}[]") for item in value})


def seal_event(value: Mapping[str, Any], *, require_sealed_sha: bool = False) -> dict[str, Any]:
    raw = _mapping(value, "event")
    missing = sorted(REQUIRED_FIELDS - set(raw))
    if missing:
        _fail("EVENT_FIELDS_MISSING", ",".join(missing))
    event_type = _string(raw["event_type"], "event_type")
    if event_type not in EVENT_TYPES:
        _fail("EVENT_TYPE_INVALID", event_type)
    sequence_no = raw["sequence_no"]
    if isinstance(sequence_no, bool) or not isinstance(sequence_no, int) or sequence_no < 0:
        _fail("SEQUENCE_INVALID")
    side = _string(raw["side"], "side").upper()
    if side not in {"LONG", "SHORT"}:
        _fail("SIDE_INVALID")
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": _string(raw["event_id"], "event_id", maximum=160),
        "parent_event_id": _string(raw["parent_event_id"], "parent_event_id", maximum=160, allow_empty=True),
        "decision_id": _string(raw["decision_id"], "decision_id", maximum=160),
        "position_id": _string(raw["position_id"], "position_id", maximum=160),
        "strategy_id": _string(raw["strategy_id"], "strategy_id", maximum=120),
        "strategy_source_sha256": _sha(raw["strategy_source_sha256"], "strategy_source_sha256"),
        "method_id": _string(raw["method_id"], "method_id", maximum=120),
        "skill_set": _list_of_strings(raw["skill_set"], "skill_set"),
        "team_id": _string(raw["team_id"], "team_id", maximum=80),
        "symbol": _string(raw["symbol"], "symbol", maximum=30).upper(),
        "side": side,
        "market_snapshot_sha256": _sha(raw["market_snapshot_sha256"], "market_snapshot_sha256"),
        "risk_snapshot_sha256": _sha(raw["risk_snapshot_sha256"], "risk_snapshot_sha256"),
        "sequence_no": sequence_no,
        "event_ts": _string(raw["event_ts"], "event_ts", maximum=64),
        "idempotency_key": _string(raw["idempotency_key"], "idempotency_key", maximum=200),
        "event_type": event_type,
        "payload": _mapping(raw["payload"], "payload"),
        "source_ids": _list_of_strings(raw["source_ids"], "source_ids"),
        "authority": {
            "shadow_only": True, "runtime_bound": False,
            "formal_ledger_write_allowed": False, "paper_allowed": False,
            "live_allowed": False, "execution_authority": "NONE", "order_authority": "BLOCKED",
        },
    }
    supplied_authority = _mapping(raw.get("authority", event["authority"]), "authority")
    for key, expected in event["authority"].items():
        if supplied_authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    event_sha = canonical_sha(event)
    if require_sealed_sha:
        supplied = _sha(raw.get("event_sha256"), "event_sha256")
        if supplied != event_sha:
            _fail("EVENT_SHA_MISMATCH")
    event["event_sha256"] = event_sha
    return event


@dataclass(frozen=True)
class AppendResult:
    event: dict[str, Any]
    replayed: bool


class AppendOnlyShadowEventStore:
    """Deterministic proof store. Runtime adapters must preserve these invariants."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._idempotency: dict[str, tuple[str, dict[str, Any]]] = {}
        self._by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._event_ids: set[str] = set()

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._events))

    def append(self, raw: Mapping[str, Any]) -> AppendResult:
        event = seal_event(raw)
        payload_fingerprint = canonical_sha({k: v for k, v in event.items() if k != "event_sha256"})
        key = event["idempotency_key"]
        prior = self._idempotency.get(key)
        if prior is not None:
            prior_fingerprint, prior_event = prior
            if prior_fingerprint != payload_fingerprint:
                _fail("IDEMPOTENCY_PAYLOAD_CONFLICT", key)
            return AppendResult(copy.deepcopy(prior_event), True)
        if event["event_id"] in self._event_ids:
            _fail("DUPLICATE_EVENT_ID", event["event_id"])
        chain = self._by_position[event["position_id"]]
        previous_type = chain[-1]["event_type"] if chain else None
        expected_sequence = chain[-1]["sequence_no"] + 1 if chain else 0
        expected_parent = chain[-1]["event_id"] if chain else ""
        if event["sequence_no"] != expected_sequence:
            _fail("SEQUENCE_GAP", f"{event['position_id']}:{expected_sequence}->{event['sequence_no']}")
        if event["parent_event_id"] != expected_parent:
            _fail("PARENT_EVENT_MISMATCH", event["position_id"])
        if event["event_type"] not in NEXT_TYPES[previous_type]:
            _fail("EVENT_TRANSITION_FORBIDDEN", f"{previous_type}->{event['event_type']}")
        if chain:
            for field in ("decision_id", "position_id", "strategy_id", "strategy_source_sha256", "method_id", "team_id", "symbol", "side"):
                if event[field] != chain[0][field]:
                    _fail("POSITION_IDENTITY_DRIFT", field)
        self._events.append(copy.deepcopy(event))
        chain.append(copy.deepcopy(event))
        self._event_ids.add(event["event_id"])
        self._idempotency[key] = (payload_fingerprint, copy.deepcopy(event))
        return AppendResult(copy.deepcopy(event), False)

    def validate(self) -> dict[str, Any]:
        return validate_chain(self._events)


def validate_chain(events: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
    store = AppendOnlyShadowEventStore()
    duplicate_replay_count = 0
    for raw in events:
        result = store.append(raw)
        duplicate_replay_count += int(result.replayed)
    return coverage_report(store.events, duplicate_replay_count=duplicate_replay_count)


def coverage_report(events: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...], *, duplicate_replay_count: int = 0) -> dict[str, Any]:
    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in events:
        event = seal_event(raw, require_sealed_sha=True)
        by_position[event["position_id"]].append(event)
    required = {"strategy_signal_emitted", "admission_decided", "shadow_open_requested", "shadow_open_confirmed", "shadow_close_requested", "shadow_closed", "formal_ledger_joined"}
    complete = 0
    missing_rows: list[dict[str, Any]] = []
    terminal_without_join = 0
    for position_id, rows in sorted(by_position.items()):
        types = {row["event_type"] for row in rows}
        missing = sorted(required - types)
        if not missing:
            complete += 1
        else:
            missing_rows.append({"position_id": position_id, "missing_event_types": missing})
        if "shadow_closed" in types and "formal_ledger_joined" not in types:
            terminal_without_join += 1
    total = len(by_position)
    coverage = 100.0 if total == 0 else round(100.0 * complete / total, 10)
    return {
        "schema_version": "zel.shadow.event.coverage.v1",
        "position_count": total, "complete_position_count": complete,
        "lineage_coverage_pct": coverage, "duplicate_replay_count": duplicate_replay_count,
        "missing_close_count": sum(1 for row in missing_rows if "shadow_closed" in row["missing_event_types"]),
        "missing_ledger_join_count": terminal_without_join,
        "cross_position_identity_drift_count": 0, "missing_rows": missing_rows,
        "pass": coverage == 100.0 and duplicate_replay_count == 0 and terminal_without_join == 0,
        "authority": {"shadow_only": True, "execution_authority": "NONE", "order_authority": "BLOCKED"},
    }


def deterministic_event_id(position_id: str, sequence_no: int, event_type: str) -> str:
    return "zel.shadow.event." + hashlib.sha256(f"{position_id}|{sequence_no}|{event_type}".encode("utf-8")).hexdigest()[:32]
