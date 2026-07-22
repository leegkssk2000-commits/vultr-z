#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REGISTRY = Path("backend/strategy25/canonical_strategy_registry_v1.json")
PLAN = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json")
OUTPUT = Path("runtime/r7a4d2_short_four_way_lineage_selective_rebaseline_audit/audit_v1.json")
EXPECTED_STRATEGY_COUNT = 11
EXPECTED_LANE_COUNT = 25


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def target_file_sha(root: Path, target_sha: str, rel: str) -> tuple[bool, str | None, str | None]:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{target_sha}:{rel}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return False, None, proc.stderr.decode("utf-8", errors="replace").strip()
    return True, sha256_bytes(proc.stdout), None


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def classify(row: dict[str, Any]) -> str:
    actual = row.get("actual_sha256")
    registry = row.get("registry_sha256")
    target = row.get("target_commit_sha256")
    plan_values = row.get("execution_plan_sha256_values") or []
    plan = plan_values[0] if len(plan_values) == 1 else None

    if row.get("binding_consistent") is not True:
        return "BINDING_DIVERGENCE"
    if row.get("actual_exists") is not True:
        return "ACTUAL_FILE_MISSING"
    if row.get("target_exists") is not True:
        return "TARGET_FILE_MISSING"
    if len(plan_values) != 1:
        return "MULTIPLE_OR_MISSING_PLAN_SHA"
    if actual == registry == target == plan:
        return "CLEAN_FOUR_WAY_LINEAGE"
    if actual == registry and target == plan and actual != target:
        return "ACTUAL_REGISTRY_AHEAD_OF_TARGET_AND_PLAN"
    if actual == registry == target and plan != actual:
        return "EXECUTION_PLAN_STALE_ONLY"
    if actual == registry == plan and target != actual:
        return "TARGET_COMMIT_STALE_ONLY"
    if actual == target == plan and registry != actual:
        return "REGISTRY_STALE_ONLY"
    if actual != registry:
        return "ACTUAL_REGISTRY_AUTHORITY_CONFLICT"
    return "MULTI_SOURCE_LINEAGE_DIVERGENCE"


def action_for(classification: str) -> str:
    if classification == "CLEAN_FOUR_WAY_LINEAGE":
        return "PRESERVE_EXISTING_EVIDENCE"
    if classification == "ACTUAL_REGISTRY_AHEAD_OF_TARGET_AND_PLAN":
        return "SNAPSHOT_CANONICAL_SOURCE_THEN_REBUILD_PLAN_AND_SELECTIVE_RERUN"
    if classification == "EXECUTION_PLAN_STALE_ONLY":
        return "REBUILD_PLAN_AND_SELECTIVE_RERUN"
    if classification == "TARGET_COMMIT_STALE_ONLY":
        return "RECOMMIT_CANONICAL_SOURCE_THEN_SELECTIVE_RERUN"
    if classification == "REGISTRY_STALE_ONLY":
        return "REGISTRY_AUTHORITY_REVIEW_REQUIRED"
    if classification in {"ACTUAL_REGISTRY_AUTHORITY_CONFLICT", "BINDING_DIVERGENCE", "MULTI_SOURCE_LINEAGE_DIVERGENCE"}:
        return "SOURCE_AUTHORITY_AUDIT_REQUIRED"
    return "FAIL_CLOSED_MANUAL_LINEAGE_REPAIR_REQUIRED"


def self_test() -> int:
    base = {
        "binding_consistent": True,
        "actual_exists": True,
        "target_exists": True,
        "execution_plan_sha256_values": ["a"],
    }
    assert classify({**base, "actual_sha256": "a", "registry_sha256": "a", "target_commit_sha256": "a"}) == "CLEAN_FOUR_WAY_LINEAGE"
    assert classify({**base, "actual_sha256": "b", "registry_sha256": "b", "target_commit_sha256": "a"}) == "ACTUAL_REGISTRY_AHEAD_OF_TARGET_AND_PLAN"
    assert classify({**base, "actual_sha256": "a", "registry_sha256": "a", "target_commit_sha256": "a", "execution_plan_sha256_values": ["b"]}) == "EXECUTION_PLAN_STALE_ONLY"
    print("STATE=PASS_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=False, default="SELF_TEST")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    registry_path = root / REGISTRY
    plan_path = root / PLAN
    blockers: list[str] = []
    for path in (registry_path, plan_path):
        if not path.is_file():
            blockers.append(f"REQUIRED_INPUT_MISSING:{path}")
    if subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{args.target_sha}^{{commit}}"], check=False).returncode != 0:
        blockers.append("TARGET_COMMIT_INVALID")
    if blockers:
        print("STATE=HOLD_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    registry = load_json(registry_path)
    plan = load_json(plan_path)
    entries = {
        str(row.get("strategy_id")): row
        for row in registry.get("entries", [])
        if isinstance(row, dict) and row.get("strategy_id")
    }
    strategy_lanes = [
        row for row in plan.get("strategy_lanes", [])
        if isinstance(row, dict) and row.get("strategy_id")
    ]
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lane in strategy_lanes:
        by_strategy[str(lane["strategy_id"])].append(lane)

    if len(by_strategy) != EXPECTED_STRATEGY_COUNT:
        blockers.append(f"STRATEGY_COUNT_INVALID:{len(by_strategy)}")
    if len(strategy_lanes) != EXPECTED_LANE_COUNT:
        blockers.append(f"LANE_COUNT_INVALID:{len(strategy_lanes)}")

    rows: list[dict[str, Any]] = []
    for strategy_id in sorted(by_strategy):
        lanes = sorted(by_strategy[strategy_id], key=lambda row: str(row.get("lane_id")))
        entry = entries.get(strategy_id)
        if not isinstance(entry, dict):
            blockers.append(f"REGISTRY_ENTRY_MISSING:{strategy_id}")
            continue
        engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
        rel = str(engine.get("implementation_path") or "")
        callable_name = str(engine.get("callable") or "")
        actual_path = root / rel
        actual_exists = actual_path.is_file()
        actual_sha = sha256_file(actual_path) if actual_exists else None
        registry_sha = str(engine.get("source_sha256") or "") or None
        target_exists, target_sha, target_error = target_file_sha(root, args.target_sha, rel)

        plan_paths = sorted({str(row.get("implementation_path") or "") for row in lanes})
        plan_callables = sorted({str(row.get("callable") or "") for row in lanes})
        plan_shas = sorted({str(row.get("source_sha256") or "") for row in lanes if row.get("source_sha256")})
        lane_ids = [str(row.get("lane_id")) for row in lanes]
        timeframes = sorted({str(row.get("timeframe")) for row in lanes})
        binding_consistent = plan_paths == [rel] and plan_callables == [callable_name]

        row = {
            "strategy_id": strategy_id,
            "family": str(lanes[0].get("family") or ""),
            "lane_ids": lane_ids,
            "lane_count": len(lane_ids),
            "timeframes": timeframes,
            "implementation_path": rel,
            "callable": callable_name,
            "actual_exists": actual_exists,
            "actual_sha256": actual_sha,
            "registry_sha256": registry_sha,
            "target_exists": target_exists,
            "target_commit_sha256": target_sha,
            "target_error": target_error,
            "execution_plan_paths": plan_paths,
            "execution_plan_callables": plan_callables,
            "execution_plan_sha256_values": plan_shas,
            "binding_consistent": binding_consistent,
        }
        row["classification"] = classify(row)
        row["required_action"] = action_for(str(row["classification"]))
        row["existing_evidence_reusable"] = row["classification"] == "CLEAN_FOUR_WAY_LINEAGE"
        row["selective_rebaseline_required"] = row["classification"] != "CLEAN_FOUR_WAY_LINEAGE"
        rows.append(row)

    authority_conflicts = [
        row for row in rows
        if row["classification"] in {
            "ACTUAL_REGISTRY_AUTHORITY_CONFLICT", "REGISTRY_STALE_ONLY", "BINDING_DIVERGENCE",
            "MULTI_SOURCE_LINEAGE_DIVERGENCE", "ACTUAL_FILE_MISSING", "TARGET_FILE_MISSING",
            "MULTIPLE_OR_MISSING_PLAN_SHA",
        }
    ]
    rebaseline_rows = [row for row in rows if row["selective_rebaseline_required"]]
    preserve_rows = [row for row in rows if row["existing_evidence_reusable"]]
    classification_histogram = dict(sorted(Counter(str(row["classification"]) for row in rows).items()))
    affected_lane_ids = sorted(lane_id for row in rebaseline_rows for lane_id in row["lane_ids"])
    preserved_lane_ids = sorted(lane_id for row in preserve_rows for lane_id in row["lane_ids"])

    if blockers:
        print("STATE=HOLD_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    if authority_conflicts:
        next_stage = "R7.A4D2_SHORT_SOURCE_AUTHORITY_CONFLICT_RESOLUTION_PLAN"
        selective_rebaseline_allowed = False
    elif rebaseline_rows:
        next_stage = "R7.A4D2_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_AND_REBASELINE_PLAN"
        selective_rebaseline_allowed = True
    else:
        next_stage = "R7.A4D2_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_RETRY"
        selective_rebaseline_allowed = False

    output = {
        "schema": "r7a4d2_short_four_way_lineage_selective_rebaseline_audit_v1",
        "state": "PASS_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT",
        "target_sha": args.target_sha,
        "strategy_count": len(rows),
        "strategy_lane_count": len(strategy_lanes),
        "classification_histogram": classification_histogram,
        "clean_strategy_count": len(preserve_rows),
        "rebaseline_strategy_count": len(rebaseline_rows),
        "authority_conflict_strategy_count": len(authority_conflicts),
        "preserved_lane_count": len(preserved_lane_ids),
        "affected_lane_count": len(affected_lane_ids),
        "preserved_lane_ids": preserved_lane_ids,
        "affected_lane_ids": affected_lane_ids,
        "rebaseline_strategy_ids": [row["strategy_id"] for row in rebaseline_rows],
        "authority_conflict_strategy_ids": [row["strategy_id"] for row in authority_conflicts],
        "selective_rebaseline_allowed": selective_rebaseline_allowed,
        "full_864_reexecution_required": False,
        "strategy_rows": rows,
        "next_stage": next_stage,
        "blocker_count": 0,
        "blockers": [],
    }
    atomic_json(root / OUTPUT, output)

    print("STATE=PASS_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT")
    print("BLOCKER_COUNT=0")
    print("STRATEGY_COUNT=" + str(len(rows)))
    print("STRATEGY_LANE_COUNT=" + str(len(strategy_lanes)))
    print("CLASSIFICATION_HISTOGRAM=" + json.dumps(classification_histogram, sort_keys=True))
    print("CLEAN_STRATEGY_COUNT=" + str(len(preserve_rows)))
    print("REBASELINE_STRATEGY_COUNT=" + str(len(rebaseline_rows)))
    print("AUTHORITY_CONFLICT_STRATEGY_COUNT=" + str(len(authority_conflicts)))
    print("PRESERVED_LANE_COUNT=" + str(len(preserved_lane_ids)))
    print("AFFECTED_LANE_COUNT=" + str(len(affected_lane_ids)))
    print("REBASELINE_STRATEGY_IDS=" + json.dumps(output["rebaseline_strategy_ids"]))
    print("AFFECTED_LANE_IDS=" + json.dumps(affected_lane_ids))
    print("SELECTIVE_REBASELINE_ALLOWED=" + str(selective_rebaseline_allowed).lower())
    print("FULL_864_REEXECUTION_REQUIRED=false")
    print("AUDIT_JSON=" + str(root / OUTPUT))
    print("NEXT_STAGE=" + next_stage)
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
