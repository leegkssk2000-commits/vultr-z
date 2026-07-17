#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CORE_RUNTIME_MARKERS = (
    "zico-ceo-canonical-adapter",
    "q4r3-exact25-shadow-producer",
    "zel-alimi-paper-control-api-w208",
)


def text_of(record: dict[str, Any]) -> str:
    parts = [str(record.get("path", "")), str(record.get("classification", ""))]
    for hit in record.get("hits", []):
        if isinstance(hit, dict):
            parts.append(str(hit.get("text", "")))
            parts.extend(str(term) for term in hit.get("terms", []))
    return " ".join(parts).lower()


def unit_key(record: dict[str, Any]) -> str:
    return Path(str(record.get("path", ""))).name


def canonicalize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: dict[str, dict[str, Any]] = {}
    for record in records:
        key = unit_key(record)
        if not key:
            continue
        current = chosen.get(key)
        path = str(record.get("path", ""))
        direct = "/multi-user.target.wants/" not in path
        if current is None:
            chosen[key] = record
            continue
        current_direct = "/multi-user.target.wants/" not in str(current.get("path", ""))
        if direct and not current_direct:
            chosen[key] = record
    return [chosen[key] for key in sorted(chosen)]


def disposition(record: dict[str, Any], rules: dict[str, Any], *, static_lock: bool = False) -> tuple[str, list[str]]:
    text = text_of(record)
    if static_lock:
        return str(rules["static_lock_disposition"]), ["STATIC_DISPLAY_LOCK"]
    measurement = [str(item).lower() for item in rules.get("measurement_writer_markers", [])]
    consumer = [str(item).lower() for item in rules.get("read_only_consumer_markers", [])]
    legacy = [str(item).lower() for item in rules.get("legacy_display_markers", [])]
    if any(marker in text for marker in measurement):
        return "PRESERVE_MEASUREMENT_WRITER", [marker for marker in measurement if marker in text]
    if any(marker in text for marker in consumer):
        return "PRESERVE_READ_ONLY_CONSUMER", [marker for marker in consumer if marker in text]
    if any(marker in text for marker in CORE_RUNTIME_MARKERS):
        return "PRESERVE_CORE_RUNTIME", [marker for marker in CORE_RUNTIME_MARKERS if marker in text]
    matched = [marker for marker in legacy if marker in text]
    if matched:
        return "PLAN_ISOLATION_BEFORE_NEW_EPOCH", matched
    return "REVIEW_REQUIRED", ["NO_LEGACY_DISPLAY_MARKER"]


def dedupe_paths(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for record in records:
        path = str(record.get("path", ""))
        if path and path not in seen:
            seen.add(path)
            output.append(record)
    return output


def build(contract: dict[str, Any], status: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if status.get("state") != "PASS" or status.get("blocker_count") != 0:
        blockers.append("R73B0_NOT_PASS")
    if status.get("cleanup_applied") is not False:
        blockers.append("R73B0_ALREADY_MUTATED")
    groups = inventory.get("groups")
    if not isinstance(groups, dict):
        blockers.append("R73B0_INVENTORY_MISSING")
        groups = {}
    raw_candidates = [item for item in groups.get("writer_candidates", []) if isinstance(item, dict)]
    if len(dedupe_paths(raw_candidates)) != int(status.get("writer_candidate_count", -1)):
        blockers.append("RAW_WRITER_CANDIDATE_COUNT_MISMATCH")
    candidates = canonicalize(raw_candidates)
    locks = dedupe_paths([item for item in groups.get("static_lock_hits", []) if isinstance(item, dict)])
    rules = contract.get("rules", {})
    candidate_plan = []
    for record in candidates:
        action, reasons = disposition(record, rules)
        candidate_plan.append({
            "unit": unit_key(record),
            "path": record.get("path"),
            "source_classification": record.get("classification"),
            "active_name_match": bool(record.get("active_name_match")),
            "disposition": action,
            "reason_markers": reasons,
        })
    lock_plan = []
    for record in locks:
        action, reasons = disposition(record, rules, static_lock=True)
        lock_plan.append({
            "unit": unit_key(record),
            "path": record.get("path"),
            "source_classification": record.get("classification"),
            "active_name_match": bool(record.get("active_name_match")),
            "disposition": action,
            "reason_markers": reasons,
        })
    if len(lock_plan) != int(status.get("static_lock_count", -1)):
        blockers.append("STATIC_LOCK_COUNT_MISMATCH")
    if any(item["disposition"] == "REVIEW_REQUIRED" for item in candidate_plan):
        blockers.append("UNRESOLVED_CANONICAL_UNIT")
    if any(item["disposition"] == "PLAN_ISOLATION_BEFORE_NEW_EPOCH" and item["disposition"] == "PRESERVE_CORE_RUNTIME" for item in candidate_plan):
        blockers.append("CORE_RUNTIME_CLASSIFICATION_CONFLICT")
    future_owner = dict(contract.get("future_owner", {}))
    if future_owner.get("writer_count") != 1 or future_owner.get("enabled_now") is not False:
        blockers.append("FUTURE_OWNER_CONTRACT_INVALID")
    return {
        "schema": "q4r3_exact25_r73b1_single_owner_plan_v2",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "mutation_count": 0,
        "cleanup_applied": False,
        "future_owner": future_owner,
        "future_owner_count": 1 if future_owner else 0,
        "raw_writer_candidate_count": len(dedupe_paths(raw_candidates)),
        "canonical_writer_unit_count": len(candidate_plan),
        "writer_candidate_count": len(candidate_plan),
        "static_lock_count": len(lock_plan),
        "preserve_core_runtime_count": sum(item["disposition"] == "PRESERVE_CORE_RUNTIME" for item in candidate_plan),
        "preserve_measurement_writer_count": sum(item["disposition"] == "PRESERVE_MEASUREMENT_WRITER" for item in candidate_plan),
        "preserve_read_only_consumer_count": sum(item["disposition"] == "PRESERVE_READ_ONLY_CONSUMER" for item in candidate_plan),
        "planned_isolation_count": sum(item["disposition"] == "PLAN_ISOLATION_BEFORE_NEW_EPOCH" for item in candidate_plan),
        "static_lock_plan_count": len(lock_plan),
        "writer_candidates": candidate_plan,
        "static_locks": lock_plan,
        "active_units": groups.get("active_units", []),
        "active_timers": groups.get("active_timers", []),
        "next_stage": contract.get("next_stage"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        json.loads(args.contract.read_text(encoding="utf-8")),
        json.loads(args.status.read_text(encoding="utf-8")),
        json.loads(args.inventory.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "state", "blocker_count", "raw_writer_candidate_count", "canonical_writer_unit_count",
        "preserve_core_runtime_count", "planned_isolation_count", "static_lock_count", "mutation_count"
    )}, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
