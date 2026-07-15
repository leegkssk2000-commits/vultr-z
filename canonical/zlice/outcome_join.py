from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from canonical.performance import AttributionEnvelope
from .contracts import ZliceEvent

FORMAL_LEDGER_JOIN_VERSION = "zlice-formal-ledger-join/1.0.0"
PRODUCER_ID = "FormalLedgerReadOnlyOutcomeJoinAdapter"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _first(row: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = row.get(name)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            return value
    return None


def _text(row: Mapping[str, Any], names: Sequence[str]) -> str:
    value = _first(row, names)
    return str(value).strip() if value is not None else ""


def _number(row: Mapping[str, Any], names: Sequence[str]) -> float | None:
    value = _first(row, names)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _row_hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dict(row))).hexdigest()


def _event_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return f"zlice.outcome.{hashlib.sha256(raw).hexdigest()[:32]}"


@dataclass(frozen=True, slots=True)
class FormalLedgerOutcome:
    ledger_row_id: str
    ledger_row_hash: str
    ledger_line_no: int
    close_event_id: str
    position_id: str
    symbol: str
    side: str
    strategy_id: str
    method_id: str
    skill_id: str
    realized_r: float | None
    fee_r: float | None
    fee_bps: float | None
    slippage_r: float | None
    slippage_bps: float | None
    mfe_r: float | None
    mae_r: float | None
    exposure_time_min: float | None
    closed_at: str
    source_path: str
    adapter_version: str = FORMAL_LEDGER_JOIN_VERSION

    def __post_init__(self) -> None:
        required = {
            "ledger_row_id": self.ledger_row_id,
            "ledger_row_hash": self.ledger_row_hash,
            "close_event_id": self.close_event_id,
            "position_id": self.position_id,
            "closed_at": self.closed_at,
            "source_path": self.source_path,
        }
        missing = sorted(name for name, value in required.items() if not str(value or "").strip())
        if missing:
            raise ValueError(f"FORMAL_LEDGER_OUTCOME_FIELDS_MISSING:{','.join(missing)}")
        if self.ledger_line_no < 1:
            raise ValueError("FORMAL_LEDGER_LINE_INVALID")
        if len(self.ledger_row_hash) != 64:
            raise ValueError("FORMAL_LEDGER_ROW_HASH_INVALID")
        if self.adapter_version != FORMAL_LEDGER_JOIN_VERSION:
            raise ValueError("FORMAL_LEDGER_JOIN_VERSION_MISMATCH")

    @property
    def lineage_complete(self) -> bool:
        return all((self.strategy_id, self.method_id, self.skill_id))


@dataclass(frozen=True, slots=True)
class FormalLedgerReadResult:
    outcomes: tuple[FormalLedgerOutcome, ...]
    parse_errors: tuple[str, ...]
    rejected_rows: tuple[str, ...]
    duplicate_close_event_ids: tuple[str, ...]
    duplicate_ledger_row_ids: tuple[str, ...]
    duplicate_position_ids: tuple[str, ...]
    file_sha256: str
    file_size_bytes: int
    source_path: str

    @property
    def join_ready(self) -> bool:
        return not (
            self.parse_errors
            or self.rejected_rows
            or self.duplicate_close_event_ids
            or self.duplicate_ledger_row_ids
        )


def parse_formal_ledger_row(row: Mapping[str, Any], *, line_no: int, source_path: str) -> FormalLedgerOutcome:
    row_copy = dict(row)
    digest = _row_hash(row_copy)
    close_event_id = _text(row_copy, ("close_event_id", "event_id"))
    position_id = _text(row_copy, ("position_id", "positionId", "trade_id"))
    closed_at = _text(row_copy, ("closed_at", "exit_ts", "close_ts", "exit_time", "timestamp", "ts"))
    explicit_row_id = _text(row_copy, ("ledger_row_id", "row_id"))
    ledger_row_id = explicit_row_id or close_event_id or f"formal-ledger.{line_no}.{digest[:16]}"
    return FormalLedgerOutcome(
        ledger_row_id=ledger_row_id,
        ledger_row_hash=digest,
        ledger_line_no=line_no,
        close_event_id=close_event_id,
        position_id=position_id,
        symbol=_text(row_copy, ("symbol", "market", "instrument")),
        side=_text(row_copy, ("side", "direction")),
        strategy_id=_text(row_copy, ("strategy_id", "strategy")),
        method_id=_text(row_copy, ("method_id", "trade_method_id", "method")),
        skill_id=_text(row_copy, ("skill_id", "skill")),
        realized_r=_number(row_copy, ("realized_r", "pnl_r", "net_r", "r")),
        fee_r=_number(row_copy, ("fee_r", "fees_r")),
        fee_bps=_number(row_copy, ("fee_bps", "fees_bps")),
        slippage_r=_number(row_copy, ("slippage_r",)),
        slippage_bps=_number(row_copy, ("slippage_bps",)),
        mfe_r=_number(row_copy, ("mfe_r",)),
        mae_r=_number(row_copy, ("mae_r",)),
        exposure_time_min=_number(row_copy, ("exposure_time_min", "hold_min", "holding_time_min")),
        closed_at=closed_at,
        source_path=source_path,
    )


def _duplicates(values: Iterable[str]) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return tuple(sorted(value for value, count in counts.items() if count > 1))


def read_formal_ledger(path: Path) -> FormalLedgerReadResult:
    parse_errors: list[str] = []
    rejected_rows: list[str] = []
    outcomes: list[FormalLedgerOutcome] = []
    if not path.is_file():
        return FormalLedgerReadResult(
            outcomes=(),
            parse_errors=("FILE_MISSING",),
            rejected_rows=(),
            duplicate_close_event_ids=(),
            duplicate_ledger_row_ids=(),
            duplicate_position_ids=(),
            file_sha256="",
            file_size_bytes=0,
            source_path=str(path),
        )
    raw = path.read_bytes()
    for line_no, raw_line in enumerate(raw.splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except Exception as exc:
            parse_errors.append(f"line={line_no}:{type(exc).__name__}:{exc}")
            continue
        if not isinstance(payload, dict):
            parse_errors.append(f"line={line_no}:ROW_NOT_OBJECT")
            continue
        try:
            outcomes.append(parse_formal_ledger_row(payload, line_no=line_no, source_path=str(path)))
        except ValueError as exc:
            rejected_rows.append(f"line={line_no}:{exc}")
    return FormalLedgerReadResult(
        outcomes=tuple(outcomes),
        parse_errors=tuple(parse_errors),
        rejected_rows=tuple(rejected_rows),
        duplicate_close_event_ids=_duplicates(row.close_event_id for row in outcomes),
        duplicate_ledger_row_ids=_duplicates(row.ledger_row_id for row in outcomes),
        duplicate_position_ids=_duplicates(row.position_id for row in outcomes),
        file_sha256=hashlib.sha256(raw).hexdigest(),
        file_size_bytes=len(raw),
        source_path=str(path),
    )


def build_outcome_join_event(
    *,
    outcome: FormalLedgerOutcome,
    attribution: AttributionEnvelope,
    parent_event_id: str,
    event_ts: str,
    sequence_no: int,
) -> ZliceEvent:
    if outcome.position_id != attribution.position_id:
        raise ValueError("OUTCOME_ATTRIBUTION_POSITION_MISMATCH")
    if not parent_event_id.strip():
        raise ValueError("OUTCOME_JOIN_PARENT_EVENT_REQUIRED")
    payload = {
        "outcome": asdict(outcome),
        "attribution_id": attribution.attribution_id,
        "decision_id": attribution.decision_id,
        "counterfactual_cohort_id": attribution.counterfactual_cohort_id,
    }
    payload_hash = hashlib.sha256(_canonical_json(payload)).hexdigest()
    metadata = {
        "ledger_row_id": outcome.ledger_row_id,
        "ledger_row_hash": outcome.ledger_row_hash,
        "close_event_id": outcome.close_event_id,
        "realized_r": "" if outcome.realized_r is None else format(outcome.realized_r, ".12g"),
        "fee_r": "" if outcome.fee_r is None else format(outcome.fee_r, ".12g"),
        "fee_bps": "" if outcome.fee_bps is None else format(outcome.fee_bps, ".12g"),
        "slippage_r": "" if outcome.slippage_r is None else format(outcome.slippage_r, ".12g"),
        "slippage_bps": "" if outcome.slippage_bps is None else format(outcome.slippage_bps, ".12g"),
        "formal_ledger_is_pnl_ssot": "true",
    }
    return ZliceEvent(
        event_id=_event_id(attribution.attribution_id, outcome.close_event_id, outcome.ledger_row_hash),
        parent_event_id=parent_event_id,
        decision_id=attribution.decision_id,
        position_id=outcome.position_id,
        event_type="outcome_joined",
        event_ts=event_ts,
        producer_id=PRODUCER_ID,
        producer_version=FORMAL_LEDGER_JOIN_VERSION,
        attribution_id=attribution.attribution_id,
        payload_hash=payload_hash,
        source_ids=(f"formal-ledger:{outcome.file_sha256 if hasattr(outcome, 'file_sha256') else outcome.ledger_row_hash}",),
        sequence_no=sequence_no,
        metadata=metadata,
    )
