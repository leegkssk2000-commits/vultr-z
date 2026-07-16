#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("q4r3_team_advisor_r41_lico_sgrade_gap_audit.py")
spec = importlib.util.spec_from_file_location("r41_lico_audit", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--r36", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = module.analyze(args.root.resolve(), args.r36.resolve())
    report = payload["report"]
    blockers: list[str] = list(payload.get("blockers", []))

    if payload.get("schema") != module.AUDIT_SCHEMA:
        blockers.append("R41_SCHEMA_INVALID")
    if payload.get("official_stage") != "R4.1":
        blockers.append("R41_STAGE_INVALID")
    authority = payload.get("authority", {})
    if authority.get("execution_authority") != "none" or not authority.get("observer_only"):
        blockers.append("R41_AUTHORITY_BOUNDARY_INVALID")
    if authority.get("runtime_mutation_performed") or authority.get("systemd_mutation_performed"):
        blockers.append("R41_MUTATION_DETECTED")
    if report.get("r36_team_sgrade_ready_count") != 4:
        blockers.append("R41_R36_PREREQUISITE_INVALID")
    if report.get("required_surface_count") != len(module.SURFACES):
        blockers.append("R41_SURFACE_SCHEMA_INVALID")
    if report.get("forbidden_hit_count", 0) != len(report.get("forbidden_hits", [])):
        blockers.append("R41_FORBIDDEN_COUNT_MISMATCH")

    payload["blockers"] = sorted(set(blockers))
    if payload["blockers"]:
        payload["state"] = "HOLD"
        payload["verdict"] = "R41_LICO_SGRADE_GAPS_CLASSIFIED"
    module.atomic_json(args.output.resolve(), payload)

    print(json.dumps({
        "state": payload["state"],
        "candidate_count": report["candidate_count"],
        "canonical_owner_count": report["canonical_owner_count"],
        "ready_surface_count": report["ready_surface_count"],
        "missing_surface_count": report["missing_surface_count"],
        "forbidden_hit_count": report["forbidden_hit_count"],
        "blocker_count": len(payload["blockers"]),
        "verdict": payload["verdict"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
