from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from canonical.zlice.ledger import ZliceSnapshot

PERFORMANCE_EVALUATOR_VERSION = "performance-evaluator/1.0.0"


@dataclass(frozen=True, slots=True)
class FormalLedgerOutcomeView:
    ledger_row_id: str
    ledger_row_hash: str
    position_id: str
    pnl_r: float
    fee_r: float
    slippage_r: float
    closed_at: str

    def __post_init__(self) -> None:
        required = (
            self.ledger_row_id,
            self.ledger_row_hash,
            self.position_id,
            self.closed_at,
        )
        if any(not str(value or "").strip() for value in required):
            raise ValueError("FORMAL_LEDGER_OUTCOME_FIELD_MISSING")


@dataclass(frozen=True, slots=True)
class EvaluatorBoundaryReport:
    zlice_event_count: int
    outcome_view_count: int
    outcome_join_candidate_count: int
    joined_position_count: int
    missing_outcome_position_ids: tuple[str, ...]
    duplicate_outcome_position_ids: tuple[str, ...]
    evaluator_version: str = PERFORMANCE_EVALUATOR_VERSION
    read_only: bool = True
    execution_authority: str = "none"


class ReadOnlyPerformanceEvaluator:
    """External evaluator. It cannot append Zlice events or mutate the Formal Ledger."""

    __slots__ = ("_snapshot", "_outcomes")

    def __init__(
        self,
        snapshot: ZliceSnapshot,
        outcomes: Mapping[str, FormalLedgerOutcomeView],
    ) -> None:
        self._snapshot = snapshot
        self._outcomes = MappingProxyType(dict(outcomes))

    def boundary_report(self) -> EvaluatorBoundaryReport:
        closed_positions = {
            record.event.position_id
            for record in self._snapshot.records
            if record.event.event_type in {"position_closed", "outcome_joined"}
        }
        duplicate_outcomes: list[str] = []
        seen_rows: set[str] = set()
        for position_id, row in self._outcomes.items():
            if position_id != row.position_id:
                duplicate_outcomes.append(position_id)
            if row.ledger_row_id in seen_rows:
                duplicate_outcomes.append(position_id)
            seen_rows.add(row.ledger_row_id)
        joined = closed_positions.intersection(self._outcomes)
        missing = tuple(sorted(closed_positions.difference(self._outcomes)))
        return EvaluatorBoundaryReport(
            zlice_event_count=len(self._snapshot.records),
            outcome_view_count=len(self._outcomes),
            outcome_join_candidate_count=len(closed_positions),
            joined_position_count=len(joined),
            missing_outcome_position_ids=missing,
            duplicate_outcome_position_ids=tuple(sorted(set(duplicate_outcomes))),
        )
