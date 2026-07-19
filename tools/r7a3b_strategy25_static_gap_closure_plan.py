#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprints(paths: Iterable[str]) -> dict[str, str | None]:
    return {path: sha256_file(Path(path)) for path in paths}


def prior_a3_valid(value: dict[str, Any], expected_count: int) -> bool:
    return (
        value.get("official_stage") == "R7.A3"
        and value.get("state") == "PASS"
        and int(value.get("blocker_count", -1)) == 0
        and int(value.get("strategy_count", -1)) == expected_count
        and int(value.get("implementation_count", -1)) == expected_count
        and int(value.get("protected_change_count", -1)) == 0
        and int(value.get("runtime_mutation_count", -1)) == 0
        and value.get("next_stage") == "R7.A3B_STRATEGY25_STATIC_GAP_CLOSURE"
    )


def normalize_strategy_rows(value: Any, expected_count: int) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    if not isinstance(value, list):
        return [], ["STRATEGY_ROWS_NOT_LIST"]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            blockers.append("STRATEGY_ROW_NOT_OBJECT")
            continue
        strategy_id = str(raw.get("strategy_id", "")).strip()
        if not strategy_id:
            blockers.append("STRATEGY_ID_MISSING")
            continue
        if strategy_id in seen:
            blockers.append(f"DUPLICATE_STRATEGY_ID:{strategy_id}")
            continue
        seen.add(strategy_id)
        missing_raw = raw.get("missing", [])
        missing = sorted({str(item) for item in missing_raw}) if isinstance(missing_raw, list) else []
        row = dict(raw)
        row["strategy_id"] = strategy_id
        row["missing"] = missing
        row["implementation_refs"] = sorted({str(x) for x in raw.get("implementation_refs", []) if str(x)})
        row["test_refs"] = sorted({str(x) for x in raw.get("test_refs", []) if str(x)})
        rows.append(row)
    rows.sort(key=lambda row: row["strategy_id"])
    if len(rows) != expected_count:
        blockers.append(f"STRATEGY_ROW_COUNT_{len(rows)}_NE_{expected_count}")
    return rows, blockers


def derive_plan(rows: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    required = [str(key) for key in contract.get("required_evidence", [])]
    shared_keys = {str(key) for key in contract.get("shared_gap_keys", [])}
    per_keys = {str(key) for key in contract.get("per_strategy_gap_keys", [])}
    n = len(rows)
    gap_counts: Counter[str] = Counter()
    strategies_by_gap: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for gap in row.get("missing", []):
            gap_counts[gap] += 1
            strategies_by_gap[gap].append(row["strategy_id"])

    # A shared contract is allowed only when a real common caller can later be proven.
    # Here we merely identify high-coverage candidates; no evidence is granted.
    threshold = max(1, (n * 4 + 4) // 5)  # ceil(80%)
    shared_gap_candidates = sorted(
        key for key in shared_keys if gap_counts.get(key, 0) >= threshold
    )
    per_strategy_gap_ids = sorted({
        row["strategy_id"]
        for row in rows
        if any(gap in per_keys for gap in row.get("missing", []))
    })
    missing_test_ids = sorted(
        row["strategy_id"] for row in rows if "tests" in row.get("missing", [])
    )
    tested_ids = sorted(
        row["strategy_id"] for row in rows if "tests" not in row.get("missing", [])
    )

    uncovered_required = sorted(set(required) - set(gap_counts) - {
        key for key in required if all(key not in row.get("missing", []) for row in rows)
    })

    has_shared = bool(shared_gap_candidates)
    has_per = bool(per_strategy_gap_ids)
    if has_shared and has_per:
        closure_mode = "MIXED"
        next_stage = str(contract.get("next_stage_on_mixed_gap"))
    elif has_shared:
        closure_mode = "SHARED"
        next_stage = str(contract.get("next_stage_on_shared_gap"))
    elif has_per or any(gap_counts.values()):
        closure_mode = "PER_STRATEGY"
        next_stage = str(contract.get("next_stage_on_per_strategy_gap"))
    else:
        closure_mode = "NO_GAP"
        next_stage = str(contract.get("next_stage_on_no_gap"))

    per_strategy = []
    for row in rows:
        per_strategy.append({
            "strategy_id": row["strategy_id"],
            "current_grade": row.get("grade"),
            "missing": row.get("missing", []),
            "implementation_refs": row.get("implementation_refs", []),
            "test_refs": row.get("test_refs", []),
            "closure_class": (
                "TEST_AND_INTERFACE"
                if any(gap in per_keys for gap in row.get("missing", []))
                else "SHARED_EVIDENCE_ONLY"
                if any(gap in shared_keys for gap in row.get("missing", []))
                else "NONE"
            ),
        })

    return {
        "closure_mode": closure_mode,
        "next_stage": next_stage,
        "gap_counts": dict(sorted(gap_counts.items())),
        "strategies_by_gap": {key: sorted(value) for key, value in sorted(strategies_by_gap.items())},
        "shared_gap_threshold_count": threshold,
        "shared_gap_candidates": shared_gap_candidates,
        "per_strategy_gap_ids": per_strategy_gap_ids,
        "missing_test_strategy_ids": missing_test_ids,
        "tested_strategy_ids": tested_ids,
        "missing_test_count": len(missing_test_ids),
        "tested_count": len(tested_ids),
        "uncovered_required_keys": uncovered_required,
        "closure_batches": [
            {
                "batch": 1,
                "name": "real_entrypoint_test_closure",
                "strategy_ids": missing_test_ids,
                "rule": "parameterized tests must resolve each real implementation entrypoint; identifier-only tests are forbidden",
            },
            {
                "batch": 2,
                "name": "shared_runtime_evidence_contract",
                "evidence_keys": shared_gap_candidates,
                "rule": "shared evidence may be credited only after actual common caller and receipt emission are proven",
            },
            {
                "batch": 3,
                "name": "remaining_per_strategy_interface_closure",
                "strategy_ids": per_strategy_gap_ids,
                "rule": "add no strategy logic; close only missing interface/test/receipt evidence with exact source SHA",
            },
        ],
        "strategies": per_strategy,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected_count = int(contract.get("expected_strategy_count", 25))
    prior_path = root / str(contract.get("prior_a3_status_path"))
    status_path = root / str(contract.get("status_path"))
    protected_paths = [str(path) for path in contract.get("protected_paths", [])]
    before = fingerprints(protected_paths)

    blockers: list[str] = []
    prior = load_json(prior_path)
    if not prior_a3_valid(prior, expected_count):
        blockers.append("PRIOR_A3_INVALID")

    rows, row_blockers = normalize_strategy_rows(prior.get("strategies"), expected_count)
    blockers.extend(row_blockers)
    plan = derive_plan(rows, contract) if rows else {
        "closure_mode": "UNKNOWN",
        "next_stage": "R7.A3B_DIAGNOSE",
        "gap_counts": {},
        "strategies_by_gap": {},
        "shared_gap_candidates": [],
        "per_strategy_gap_ids": [],
        "missing_test_strategy_ids": [],
        "missing_test_count": 0,
        "tested_count": 0,
        "closure_batches": [],
        "strategies": [],
    }

    after = fingerprints(protected_paths)
    protected_changes = [
        {"path": path, "before": before.get(path), "after": after.get(path)}
        for path in protected_paths
        if before.get(path) != after.get(path)
    ]
    if protected_changes:
        blockers.append("PROTECTED_PATH_CHANGED")

    state = "PASS" if not blockers else "HOLD"
    next_stage = plan.get("next_stage") if state == "PASS" else "R7.A3B_DIAGNOSE"
    payload = {
        "schema": "r7a3b_strategy25_static_gap_closure_plan_status_v1",
        "official_stage": "R7.A3B",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "read_only": True,
        "prior_a3_valid": prior_a3_valid(prior, expected_count),
        "strategy_count": len(rows),
        "prior_tested_count": prior.get("tested_count"),
        "prior_static_s_ready_count": prior.get("static_s_ready_count"),
        "performance_s_promoted_count": 0,
        "plan": plan,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "runtime_mutation_count": 0,
        "selection_funnel": contract.get("selection_funnel", {}),
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)

    print("R7A3B_STRATEGY25_STATIC_GAP_CLOSURE_PLAN_COMPLETE")
    for key, value in (
        ("STATE", state),
        ("BLOCKER_COUNT", len(blockers)),
        ("BLOCKERS", json.dumps(blockers, ensure_ascii=False)),
        ("PRIOR_A3_VALID", str(prior_a3_valid(prior, expected_count)).lower()),
        ("STRATEGY_COUNT", len(rows)),
        ("CLOSURE_MODE", plan.get("closure_mode")),
        ("MISSING_TEST_COUNT", plan.get("missing_test_count")),
        ("SHARED_GAP_CANDIDATES", json.dumps(plan.get("shared_gap_candidates", []), ensure_ascii=False)),
        ("GAP_COUNTS", json.dumps(plan.get("gap_counts", {}), ensure_ascii=False, sort_keys=True)),
        ("PERFORMANCE_S_PROMOTED_COUNT", 0),
        ("PROTECTED_CHANGE_COUNT", len(protected_changes)),
        ("RUNTIME_MUTATION_COUNT", 0),
        ("NEXT_STAGE", next_stage),
        ("EVIDENCE_JSON", str(status_path)),
        ("RC", 0 if state == "PASS" else 2),
    ):
        print(f"{key}={value}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
