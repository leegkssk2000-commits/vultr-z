#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ALLOWED = {
    "PRESERVE_MEASUREMENT_WRITER",
    "PRESERVE_READ_ONLY_CONSUMER",
    "PLAN_ISOLATION_BEFORE_NEW_EPOCH",
    "RETAIN_EVIDENCE_THEN_PLAN_ISOLATION",
    "REVIEW_REQUIRED",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    blockers: list[str] = []
    if contract.get("official_stage") != "R7.3B1" or contract.get("mutation_authority") != "none":
        blockers.append("CONTRACT_INVALID")
    if plan.get("state") != "PASS" or plan.get("blocker_count") != 0:
        blockers.append("PLAN_NOT_PASS")
    if plan.get("mutation_count") != 0 or plan.get("cleanup_applied") is not False:
        blockers.append("PLAN_MUTATION_DETECTED")
    future = plan.get("future_owner", {})
    if plan.get("future_owner_count") != 1 or future.get("writer_count") != 1 or future.get("enabled_now") is not False:
        blockers.append("FUTURE_OWNER_INVALID")
    candidates = plan.get("writer_candidates", [])
    locks = plan.get("static_locks", [])
    if len(candidates) != plan.get("writer_candidate_count"):
        blockers.append("WRITER_PLAN_COUNT_INVALID")
    if len(locks) != plan.get("static_lock_count"):
        blockers.append("STATIC_LOCK_PLAN_COUNT_INVALID")
    if any(item.get("disposition") not in ALLOWED for item in candidates + locks):
        blockers.append("DISPOSITION_INVALID")
    if any(not item.get("path") for item in candidates + locks):
        blockers.append("PATH_MISSING")
    if any(item.get("disposition") != "RETAIN_EVIDENCE_THEN_PLAN_ISOLATION" for item in locks):
        blockers.append("STATIC_LOCK_PROMOTION_FORBIDDEN")
    result = {
        "schema": "q4r3_exact25_r73b1_single_owner_plan_status_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "future_owner_count": plan.get("future_owner_count", 0),
        "writer_candidate_count": plan.get("writer_candidate_count", 0),
        "static_lock_count": plan.get("static_lock_count", 0),
        "planned_isolation_count": plan.get("planned_isolation_count", 0),
        "preserve_measurement_writer_count": plan.get("preserve_measurement_writer_count", 0),
        "preserve_read_only_consumer_count": plan.get("preserve_read_only_consumer_count", 0),
        "mutation_count": 0,
        "cleanup_applied": False,
        "next_stage": contract.get("next_stage"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
