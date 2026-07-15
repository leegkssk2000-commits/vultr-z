from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .ledger import ZliceRecord, ZliceSnapshot

ZLICE_PROJECTION_VERSION = "zlice-projection/1.0.0"


@dataclass(frozen=True, slots=True)
class ProofCapsule:
    event_id: str
    decision_id: str
    position_id: str
    event_type: str
    sequence_no: int
    record_hash: str
    previous_hash: str
    parent_event_id: str
    attribution_id: str
    producer_id: str
    producer_version: str
    source_ids: tuple[str, ...]
    metadata: Mapping[str, str]
    projection_version: str = ZLICE_PROJECTION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ReceiptArchive:
    position_id: str
    event_ids: tuple[str, ...]
    event_types: tuple[str, ...]
    head_hash: str
    record_count: int
    projection_version: str = ZLICE_PROJECTION_VERSION


@dataclass(frozen=True, slots=True)
class ReplayDrawer:
    decision_id: str
    records: tuple[ProofCapsule, ...]
    chain_valid: bool
    projection_version: str = ZLICE_PROJECTION_VERSION


@dataclass(frozen=True, slots=True)
class IntegritySummary:
    record_count: int
    unique_event_count: int
    duplicate_event_count: int
    missing_parent_count: int
    sequence_gap_count: int
    chain_valid: bool
    head_hash: str
    projection_version: str = ZLICE_PROJECTION_VERSION


class ZliceProjection:
    """Read-only consumer over an immutable ZliceSnapshot."""

    __slots__ = ("_snapshot",)

    def __init__(self, snapshot: ZliceSnapshot) -> None:
        self._snapshot = snapshot

    @staticmethod
    def _capsule(record: ZliceRecord) -> ProofCapsule:
        event = record.event
        return ProofCapsule(
            event_id=event.event_id,
            decision_id=event.decision_id,
            position_id=event.position_id,
            event_type=event.event_type,
            sequence_no=record.sequence_no,
            record_hash=record.record_hash,
            previous_hash=record.previous_hash,
            parent_event_id=event.parent_event_id,
            attribution_id=event.attribution_id,
            producer_id=event.producer_id,
            producer_version=event.producer_version,
            source_ids=event.source_ids,
            metadata=event.metadata,
        )

    def proof_capsule(self, event_id: str) -> ProofCapsule:
        sequence = self._snapshot.event_index.get(event_id)
        if sequence is None:
            raise KeyError("ZLICE_EVENT_NOT_FOUND")
        return self._capsule(self._snapshot.records[sequence])

    def receipt_archive(self, position_id: str) -> ReceiptArchive:
        records = tuple(record for record in self._snapshot.records if record.event.position_id == position_id)
        return ReceiptArchive(
            position_id=position_id,
            event_ids=tuple(record.event.event_id for record in records),
            event_types=tuple(record.event.event_type for record in records),
            head_hash=records[-1].record_hash if records else "0" * 64,
            record_count=len(records),
        )

    def replay_drawer(self, decision_id: str) -> ReplayDrawer:
        records = tuple(
            self._capsule(record)
            for record in self._snapshot.records
            if record.event.decision_id == decision_id
        )
        return ReplayDrawer(decision_id=decision_id, records=records, chain_valid=self.integrity_summary().chain_valid)

    def integrity_summary(self) -> IntegritySummary:
        records = self._snapshot.records
        event_ids = [record.event.event_id for record in records]
        event_set = set(event_ids)
        duplicate_count = len(event_ids) - len(event_set)
        missing_parent_count = sum(
            1
            for index, record in enumerate(records)
            if index > 0 and record.event.parent_event_id not in event_set
        )
        sequence_gap_count = sum(1 for index, record in enumerate(records) if record.sequence_no != index)
        chain_valid = duplicate_count == 0 and missing_parent_count == 0 and sequence_gap_count == 0
        previous_hash = "0" * 64
        for record in records:
            if record.previous_hash != previous_hash:
                chain_valid = False
                break
            previous_hash = record.record_hash
        return IntegritySummary(
            record_count=len(records),
            unique_event_count=len(event_set),
            duplicate_event_count=duplicate_count,
            missing_parent_count=missing_parent_count,
            sequence_gap_count=sequence_gap_count,
            chain_valid=chain_valid,
            head_hash=self._snapshot.head_hash,
        )
