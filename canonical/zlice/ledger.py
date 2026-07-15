from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .contracts import ZliceEvent

ZLICE_LEDGER_VERSION = "zlice-ledger/1.0.0"
ZERO_HASH = "0" * 64
ROOT_EVENT_TYPES = frozenset({"strategy_selected"})


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _event_payload(event: ZliceEvent) -> dict[str, object]:
    payload = asdict(event)
    payload["source_ids"] = list(event.source_ids)
    payload["metadata"] = dict(event.metadata)
    return payload


def _record_hash(previous_hash: str, event: ZliceEvent) -> str:
    digest = hashlib.sha256()
    digest.update(previous_hash.encode("ascii"))
    digest.update(b"|")
    digest.update(_canonical_json(_event_payload(event)))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ZliceRecord:
    sequence_no: int
    previous_hash: str
    record_hash: str
    event: ZliceEvent
    ledger_version: str = ZLICE_LEDGER_VERSION

    def __post_init__(self) -> None:
        if self.sequence_no != self.event.sequence_no:
            raise ValueError("ZLICE_RECORD_SEQUENCE_MISMATCH")
        if self.ledger_version != ZLICE_LEDGER_VERSION:
            raise ValueError("ZLICE_LEDGER_VERSION_MISMATCH")
        if len(self.previous_hash) != 64 or len(self.record_hash) != 64:
            raise ValueError("ZLICE_RECORD_HASH_INVALID")
        if _record_hash(self.previous_hash, self.event) != self.record_hash:
            raise ValueError("ZLICE_RECORD_HASH_MISMATCH")


@dataclass(frozen=True, slots=True)
class ZliceSnapshot:
    records: tuple[ZliceRecord, ...]
    event_index: Mapping[str, int]
    head_hash: str
    ledger_version: str = ZLICE_LEDGER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_index", MappingProxyType(dict(self.event_index)))
        if self.head_hash != (self.records[-1].record_hash if self.records else ZERO_HASH):
            raise ValueError("ZLICE_SNAPSHOT_HEAD_HASH_INVALID")


class ZliceLedger:
    """In-memory canonical core. Runtime persistence is intentionally deferred."""

    __slots__ = ("_records", "_event_index")

    def __init__(self, records: Iterable[ZliceRecord] = ()) -> None:
        self._records: list[ZliceRecord] = list(records)
        self._event_index: dict[str, int] = {
            record.event.event_id: record.sequence_no for record in self._records
        }
        self.verify()

    def append(self, event: ZliceEvent) -> ZliceRecord:
        if event.event_id in self._event_index:
            raise ValueError("ZLICE_DUPLICATE_EVENT_ID")
        expected_sequence = len(self._records)
        if event.sequence_no != expected_sequence:
            raise ValueError("ZLICE_SEQUENCE_NOT_MONOTONIC")
        if expected_sequence == 0:
            if event.event_type not in ROOT_EVENT_TYPES or event.parent_event_id:
                raise ValueError("ZLICE_ROOT_EVENT_INVALID")
            previous_hash = ZERO_HASH
        else:
            if not event.parent_event_id or event.parent_event_id not in self._event_index:
                raise ValueError("ZLICE_PARENT_EVENT_MISSING")
            previous_hash = self._records[-1].record_hash
        record = ZliceRecord(
            sequence_no=event.sequence_no,
            previous_hash=previous_hash,
            record_hash=_record_hash(previous_hash, event),
            event=event,
        )
        self._records.append(record)
        self._event_index[event.event_id] = event.sequence_no
        return record

    def snapshot(self) -> ZliceSnapshot:
        return ZliceSnapshot(
            records=tuple(self._records),
            event_index=dict(self._event_index),
            head_hash=self._records[-1].record_hash if self._records else ZERO_HASH,
        )

    def verify(self) -> bool:
        seen: dict[str, int] = {}
        previous_hash = ZERO_HASH
        for expected_sequence, record in enumerate(self._records):
            if record.sequence_no != expected_sequence:
                raise ValueError("ZLICE_REPLAY_SEQUENCE_MISMATCH")
            if record.event.event_id in seen:
                raise ValueError("ZLICE_REPLAY_DUPLICATE_EVENT_ID")
            if record.previous_hash != previous_hash:
                raise ValueError("ZLICE_REPLAY_CHAIN_MISMATCH")
            if expected_sequence == 0:
                if record.event.event_type not in ROOT_EVENT_TYPES or record.event.parent_event_id:
                    raise ValueError("ZLICE_REPLAY_ROOT_INVALID")
            elif record.event.parent_event_id not in seen:
                raise ValueError("ZLICE_REPLAY_PARENT_MISSING")
            ZliceRecord(
                sequence_no=record.sequence_no,
                previous_hash=record.previous_hash,
                record_hash=record.record_hash,
                event=record.event,
                ledger_version=record.ledger_version,
            )
            seen[record.event.event_id] = record.sequence_no
            previous_hash = record.record_hash
        if seen != self._event_index:
            raise ValueError("ZLICE_EVENT_INDEX_MISMATCH")
        return True
