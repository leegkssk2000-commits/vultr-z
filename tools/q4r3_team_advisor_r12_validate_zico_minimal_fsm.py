#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.zico import (
    ALLOWED_TRANSITIONS,
    ZICO_CONTROL_VERSION,
    IdempotencyConflict,
    ZicoControlRequest,
    ZicoMinimalController,
    ZicoState,
)


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


def request(**changes: object) -> ZicoControlRequest:
    value = {
        "decision_id": "decision.r12.validator",
        "position_id": "position.r12.validator",
        "event_id": "event.r12.validator",
        "parent_event_id": "event.parent",
        "event_ts": "2026-07-15T00:00:00+00:00",
        "current_state": ZicoState.RECEIVED,
        "target_state": ZicoState.EVIDENCE_BOUND,
        "action": "hold",
        "reason_codes": ("VALIDATOR",),
        "evidence_ids": ("evidence:r12",),
        "source_ids": ("src:r12",),
        "idempotency_key": "idem.r12.validator",
        "integrity_ok": True,
        "data_fresh": True,
    }
    value.update(changes)
    return ZicoControlRequest(**value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r11", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--control-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r11 = load(args.r11)
    manifest = load(args.manifest)
    config = load(args.config)
    blockers: list[str] = []

    if r11.get("state") != "PASS" or r11.get("official_stage") != "R1.1":
        blockers.append("R11_NOT_PASS")
    if int(r11.get("row_count") or 0) <= 0:
        blockers.append("R11_LEDGER_EMPTY")
    if r11.get("runtime_binding") is not False:
        blockers.append("R11_RUNTIME_BOUND")

    expected_manifest = {
        "canonical_name": "Zico",
        "byte_parity": True,
        "direct_order_calls": 0,
        "embedded_secret_literals": 0,
        "execution_authority": "none",
        "git_mirror_path": "canonical/zico/adapter.py",
        "git_mirror_path_kind": "repo_relative",
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            blockers.append(f"ZICO_MANIFEST_{key.upper()}_INVALID")

    if config.get("official_stage") != "R1.2":
        blockers.append("R12_STAGE_INVALID")
    if config.get("control_contract_version") != ZICO_CONTROL_VERSION:
        blockers.append("R12_CONTRACT_VERSION_INVALID")
    if config.get("state_count") != len(ZicoState):
        blockers.append("R12_STATE_COUNT_INVALID")
    if config.get("runtime_binding") is not False or config.get("execution_authority") != "none":
        blockers.append("R12_AUTHORITY_INVALID")
    if config.get("data_stale_threshold_source") != "SSOT.DATA_STALE_MS":
        blockers.append("R12_STALE_SOURCE_INVALID")

    controller = ZicoMinimalController()
    first = controller.decide(request(), sequence_no=1)
    replay = controller.decide(request(), sequence_no=2)
    if first.evidence_event is None or first.evidence_event.event_type != "zico_gate_decided":
        blockers.append("ZLICE_EVIDENCE_BINDING_INVALID")
    if replay.replayed is not True or replay.evidence_event is not None or controller.registry.size != 1:
        blockers.append("IDEMPOTENT_REPLAY_INVALID")
    conflict_blocked = False
    try:
        controller.decide(request(action="block"), sequence_no=3)
    except IdempotencyConflict:
        conflict_blocked = True
    if not conflict_blocked:
        blockers.append("IDEMPOTENCY_CONFLICT_NOT_BLOCKED")

    stale = ZicoMinimalController().decide(
        request(idempotency_key="idem.r12.stale", data_fresh=False), sequence_no=1
    )
    missing = ZicoMinimalController().decide(
        request(idempotency_key="idem.r12.missing", evidence_ids=()), sequence_no=1
    )
    integrity = ZicoMinimalController().decide(
        request(idempotency_key="idem.r12.integrity", integrity_ok=False), sequence_no=1
    )
    fail_closed = (stale, missing, integrity)
    if any(item.to_state is not ZicoState.HELD or item.action != "hold" for item in fail_closed):
        blockers.append("FAIL_CLOSED_INVALID")

    forbidden = ("create_order(", "place_order(", "submit_order(", "cancel_order(", "ccxt.", "os.environ")
    source = args.control_source.read_text(encoding="utf-8", errors="replace")
    forbidden_hits = [token for token in forbidden if token in source]
    if forbidden_hits:
        blockers.append("FORBIDDEN_EXECUTION_SURFACE")

    transition_count = sum(len(targets) for targets in ALLOWED_TRANSITIONS.values())
    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r12_zico_minimal_fsm_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R1.2",
        "state": state,
        "verdict": "R12_ZICO_MINIMAL_FSM_EVIDENCE_LOCK_PASS" if state == "PASS" else "R12_ZICO_MINIMAL_FSM_BLOCKED",
        "blockers": blockers,
        "report": {
            "state_count": len(ZicoState),
            "transition_count": transition_count,
            "idempotent_replay_count": 1 if replay.replayed else 0,
            "idempotency_conflict_blocked_count": 1 if conflict_blocked else 0,
            "fail_closed_scenario_count": 3,
            "zlice_evidence_binding_count": 1 if first.evidence_event is not None else 0,
            "manifest_path_normalized": manifest.get("git_mirror_path") == "canonical/zico/adapter.py",
            "r11_row_count": int(r11.get("row_count") or 0),
            "persistent_registry_enabled": False,
            "runtime_binding": False,
            "full_orchestration_enabled": False,
            "forbidden_hits": forbidden_hits,
            "next_route": "R2.1_REVALIDATE_CANONICAL_BOT_PACKAGES_AGAINST_R1_FOUNDATION",
        },
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none",
        },
        "action": "hold",
    }
    write(args.output, payload)
    print(json.dumps({
        "state": state,
        "blocker_count": len(blockers),
        "state_count": len(ZicoState),
        "transition_count": transition_count,
        "fail_closed_scenario_count": 3,
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
