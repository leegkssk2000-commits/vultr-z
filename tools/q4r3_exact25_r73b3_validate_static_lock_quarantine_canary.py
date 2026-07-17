#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED = {
    "target_count": 2,
    "quarantined_count": 2,
    "backup_verified_count": 2,
    "isolated_verified_count": 2,
    "original_absent_count": 2,
    "protected_unit_count": 5,
    "protected_state_change_count": 0,
    "formal_ledger_prefix_change_count": 0,
    "rollback_ready_count": 2,
    "rollback_performed": False,
    "cleanup_applied": True,
    "mutation_count": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    status = json.loads(args.status.read_text(encoding="utf-8"))
    blockers: list[str] = []
    if contract.get("official_stage") != "R7.3B3":
        blockers.append("CONTRACT_STAGE_INVALID")
    if status.get("state") != "PASS" or status.get("blocker_count") != 0:
        blockers.append("CANARY_NOT_PASS")
    for key, expected in EXPECTED.items():
        if status.get(key) != expected:
            blockers.append(f"{key.upper()}_INVALID")
    result = {
        "schema": "q4r3_exact25_r73b3_static_lock_quarantine_canary_validation_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "target_count": status.get("target_count", 0),
        "quarantined_count": status.get("quarantined_count", 0),
        "protected_unit_count": status.get("protected_unit_count", 0),
        "cleanup_applied": status.get("cleanup_applied", False),
        "rollback_performed": status.get("rollback_performed", False),
        "next_stage": contract.get("next_stage"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
