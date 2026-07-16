#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).with_name("q4r3_team_advisor_r41_lico_sgrade_gap_audit.py")
spec = importlib.util.spec_from_file_location("r41_lico_audit", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

AUDIT_SCHEMA = module.AUDIT_SCHEMA
SURFACES = module.SURFACES
atomic_json = module.atomic_json


def _identifier_char(value: str) -> bool:
    return value.isalnum() or value == "_"


def _standalone_marker(marker: str, text: str) -> bool:
    start = 0
    while True:
        index = text.find(marker, start)
        if index < 0:
            return False
        end = index + len(marker)
        left_ok = index == 0 or not (_identifier_char(marker[0]) and _identifier_char(text[index - 1]))
        right_ok = end == len(text) or not (_identifier_char(marker[-1]) and _identifier_char(text[end]))
        if left_ok and right_ok:
            return True
        start = index + 1


def _has_realistic_fill_surface(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    markers = SURFACES["realistic_fill_model"]
    return any(_standalone_marker(marker, text) for marker in markers)


def _normalize_realistic_fill(payload: dict[str, Any]) -> dict[str, Any]:
    report = payload["report"]
    coverage = report["surface_coverage"]
    original_paths = coverage.get("realistic_fill_model", [])
    valid_paths = sorted({path for path in original_paths if _has_realistic_fill_surface(Path(path))})
    coverage["realistic_fill_model"] = valid_paths

    missing = set(report.get("missing_surfaces", []))
    if valid_paths:
        missing.discard("realistic_fill_model")
    else:
        missing.add("realistic_fill_model")

    report["missing_surfaces"] = sorted(missing)
    report["missing_surface_count"] = len(missing)
    report["ready_surface_count"] = int(report["required_surface_count"]) - len(missing)
    state = "PASS" if not missing and not payload.get("blockers") else "HOLD"
    payload["state"] = state
    payload["verdict"] = "R41_LICO_SGRADE_GAP_AUDIT_PASS" if state == "PASS" else "R41_LICO_SGRADE_GAPS_CLASSIFIED"
    report["sgrade_ready"] = state == "PASS"
    report["next_route"] = "R4.6_LICO_SGRADE_LOCK" if state == "PASS" else "R4.2_LICO_CANONICAL_OWNER_SOURCE_CONSENSUS"
    return payload


def analyze(root: Path, r36: Path) -> dict[str, Any]:
    return _normalize_realistic_fill(module.analyze(root, r36))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--r36", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = analyze(args.root.resolve(), args.r36.resolve())
    report = payload["report"]
    blockers: list[str] = list(payload.get("blockers", []))

    if payload.get("schema") != AUDIT_SCHEMA:
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
    if report.get("required_surface_count") != len(SURFACES):
        blockers.append("R41_SURFACE_SCHEMA_INVALID")
    if report.get("forbidden_hit_count", 0) != len(report.get("forbidden_hits", [])):
        blockers.append("R41_FORBIDDEN_COUNT_MISMATCH")

    payload["blockers"] = sorted(set(blockers))
    if payload["blockers"]:
        payload["state"] = "HOLD"
        payload["verdict"] = "R41_LICO_SGRADE_GAPS_CLASSIFIED"
        report["sgrade_ready"] = False
        report["next_route"] = "R4.2_LICO_CANONICAL_OWNER_SOURCE_CONSENSUS"
    atomic_json(args.output.resolve(), payload)

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
