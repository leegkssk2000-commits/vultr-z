#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.performance.evaluator import FormalLedgerOutcomeView, ReadOnlyPerformanceEvaluator
from canonical.zlice.contracts import ZliceEvent
from canonical.zlice.ledger import ZliceLedger
from canonical.zlice.projection import ZliceProjection


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def event(sequence_no: int, event_id: str, event_type: str, parent_event_id: str) -> ZliceEvent:
    return ZliceEvent(
        event_id=event_id,
        parent_event_id=parent_event_id,
        decision_id="decision.r10",
        position_id="position.r10",
        event_type=event_type,
        event_ts=f"2026-07-15T00:00:0{sequence_no}+00:00",
        producer_id="R10Validator",
        producer_version="r10-validator/1.0.0",
        attribution_id="attr.r10",
        payload_hash=str(sequence_no) * 64,
        source_ids=("src:r10",),
        sequence_no=sequence_no,
        metadata={"mode": "validation"},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r09", type=Path, required=True)
    parser.add_argument("--architecture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r09 = load(args.r09)
    architecture = load(args.architecture)
    blockers: list[str] = []

    if r09.get("state") != "PASS" or r09.get("verdict") != "R09_TEAM_PROPOSAL_ATTRIBUTION_LOCK_PASS":
        blockers.append("R09_NOT_PASS")
    if (r09.get("report") or {}).get("performance_layer_count") != 9:
        blockers.append("R09_PERFORMANCE_LAYER_COUNT_INVALID")

    if architecture.get("schema") != "q4r3_zlice_architecture_v1":
        blockers.append("ZLICE_ARCHITECTURE_SCHEMA_INVALID")
    layers = architecture.get("layers") or {}
    if set(layers) != {"core", "projection", "performance_evaluator"}:
        blockers.append("ZLICE_LAYER_SET_INVALID")
    if (layers.get("performance_evaluator") or {}).get("zlice_member") is not False:
        blockers.append("PERFORMANCE_EVALUATOR_MUST_BE_EXTERNAL")
    ui = architecture.get("ui_contract") or {}
    if ui.get("existing_surface_preserved") is not True:
        blockers.append("EXISTING_ZLICE_UI_NOT_PRESERVED")
    if set(ui.get("allowed_features") or []) != {"proof_capsule", "receipt_archive", "replay_drawer"}:
        blockers.append("ZLICE_UI_FEATURE_SET_INVALID")
    ssot = architecture.get("ssot_contract") or {}
    if ssot.get("formal_ledger_remains_pnl_ssot") is not True or ssot.get("zlice_is_second_pnl_ledger") is not False:
        blockers.append("PNL_SSOT_BOUNDARY_INVALID")
    authority = architecture.get("authority") or {}
    if authority.get("runtime_binding") is not False or authority.get("execution_authority") != "none":
        blockers.append("ZLICE_AUTHORITY_INVALID")

    ledger = ZliceLedger()
    ledger.append(event(0, "event.strategy", "strategy_selected", ""))
    ledger.append(event(1, "event.team", "team_proposal_emitted", "event.strategy"))
    ledger.append(event(2, "event.closed", "position_closed", "event.team"))
    snapshot = ledger.snapshot()
    projection = ZliceProjection(snapshot)
    integrity = projection.integrity_summary()
    receipt = projection.receipt_archive("position.r10")
    replay = projection.replay_drawer("decision.r10")
    capsule = projection.proof_capsule("event.team")

    outcome = FormalLedgerOutcomeView(
        ledger_row_id="ledger.row.r10",
        ledger_row_hash="a" * 64,
        position_id="position.r10",
        pnl_r=1.25,
        fee_r=0.02,
        slippage_r=0.01,
        closed_at="2026-07-15T00:01:00+00:00",
    )
    evaluation = ReadOnlyPerformanceEvaluator(snapshot, {outcome.position_id: outcome}).boundary_report()

    if not ledger.verify() or not integrity.chain_valid:
        blockers.append("ZLICE_HASH_CHAIN_INVALID")
    if receipt.record_count != 3 or len(replay.records) != 3 or capsule.event_type != "team_proposal_emitted":
        blockers.append("ZLICE_PROJECTION_INVALID")
    if evaluation.joined_position_count != 1 or not evaluation.read_only or evaluation.execution_authority != "none":
        blockers.append("PERFORMANCE_EVALUATOR_BOUNDARY_INVALID")
    if hasattr(projection, "append") or hasattr(projection, "delete"):
        blockers.append("ZLICE_PROJECTION_MUTATION_SURFACE_PRESENT")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r10_zlice_core_projection_boundary_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "verdict": "R10_ZLICE_CORE_PROJECTION_BOUNDARY_LOCK_PASS" if state == "PASS" else "R10_ZLICE_CORE_PROJECTION_BOUNDARY_BLOCKED",
        "blockers": blockers,
        "report": {
            "zlice_layer_count": len(layers),
            "event_count": len(snapshot.records),
            "unique_event_count": integrity.unique_event_count,
            "hash_chain_valid": integrity.chain_valid,
            "proof_capsule_count": 1,
            "receipt_record_count": receipt.record_count,
            "replay_record_count": len(replay.records),
            "outcome_join_candidate_count": evaluation.outcome_join_candidate_count,
            "joined_position_count": evaluation.joined_position_count,
            "formal_ledger_remains_pnl_ssot": ssot.get("formal_ledger_remains_pnl_ssot"),
            "existing_ui_surface_preserved": ui.get("existing_surface_preserved"),
            "runtime_binding": False,
            "next_route": architecture.get("next_route")
        },
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none"
        },
        "action": "hold"
    }
    write(args.output, payload)
    print(json.dumps({
        "state": state,
        "blocker_count": len(blockers),
        "zlice_layer_count": len(layers),
        "event_count": len(snapshot.records),
        "hash_chain_valid": integrity.chain_valid,
        "joined_position_count": evaluation.joined_position_count,
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
