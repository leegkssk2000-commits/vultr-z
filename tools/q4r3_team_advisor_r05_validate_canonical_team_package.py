#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from canonical.teams import TEAM_REGISTRY, validate_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    blockers = list(validate_registry())
    expected = contract.get("teams") or {}

    for name, spec in TEAM_REGISTRY.items():
        row = expected.get(name) or {}
        checks = {
            "mission": spec.mission,
            "main": spec.main,
            "support": spec.support,
            "external_proof_watcher": spec.external_proof_watcher,
        }
        for field, actual in checks.items():
            if row.get(field) != actual:
                blockers.append(f"{name}:{field}:MISMATCH")
        if tuple(row.get("watchers") or ()) != spec.watchers:
            blockers.append(f"{name}:watchers:MISMATCH")
        if tuple(row.get("conditional_helpers") or ()) != spec.conditional_helpers:
            blockers.append(f"{name}:helpers:MISMATCH")
        if tuple(row.get("helper_triggers") or ()) != spec.helper_triggers:
            blockers.append(f"{name}:helper_triggers:MISMATCH")

    payload = {
        "schema": "q4r3_team_advisor_r05_canonical_team_package_validation_v1",
        "state": "PASS" if not blockers else "HOLD",
        "verdict": "R05_CANONICAL_TEAM_PACKAGE_PASS" if not blockers else "R05_CANONICAL_TEAM_PACKAGE_INVALID",
        "blockers": blockers,
        "package_owner_count": len(TEAM_REGISTRY),
        "package_teams": {name: asdict(spec) for name, spec in TEAM_REGISTRY.items()},
        "runtime_binding_changed": False,
        "runtime_enabled": False,
        "execution_authority": "none",
        "action": "hold",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": payload["state"], "blocker_count": len(blockers), "package_owner_count": len(TEAM_REGISTRY)}, sort_keys=True))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
