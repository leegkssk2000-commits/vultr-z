#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

TARGETS = {
    "break_and_continue": "ENTRY_FILTER_STRICTER_THAN_ADD",
    "rbreaker_like": "ONE_SHOT_EVENT_TO_ADD_CHAIN_GAP",
    "squeeze_break": "ONE_SHOT_EVENT_TO_ADD_CHAIN_GAP",
    "trend_ma_macd": "ONE_SHOT_EVENT_TO_ADD_CHAIN_GAP",
    "vwap_revert": "SIMULATION_ENTRY_EXECUTION_GAP",
}

STRATEGY_MARKERS = {
    "break_and_continue": ('why="bnc_long"', 'why="bnc_long_add"'),
    "rbreaker_like": ('why="rbr_breakout_long"', 'why="rbr_long_retest_add"'),
    "squeeze_break": ('why="squeeze_break_long"', 'why="squeeze_break_long_retest_add"'),
    "trend_ma_macd": ('why="trend_ma_macd_long_entry"', 'why="trend_ma_macd_long_scale_in"'),
    "vwap_revert": ('why="vwap_revert_long_entry"', 'why="vwap_revert_long_scale_in"'),
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def validate_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if evidence.get("state") != "HOLD_ENTRY_TRIGGER_REDESIGN_REQUIRED":
        errors.append("CAUSALITY_STATE_INVALID")
    if int(evidence.get("blocker_count", -1)) != 0:
        errors.append("CAUSALITY_BLOCKER_PRESENT")
    reports = {
        str(row.get("strategy_id") or ""): row
        for row in evidence.get("strategy_reports", [])
        if isinstance(row, dict)
    }
    if set(reports) != set(TARGETS):
        errors.append("TARGET_STRATEGY_SET_INVALID")
    for strategy_id, expected_class in TARGETS.items():
        report = reports.get(strategy_id, {})
        if report.get("classification") != expected_class:
            errors.append(f"CLASSIFICATION_INVALID:{strategy_id}")
    if sum(int(row.get("selected_flat_enter_count") or 0) for row in reports.values()) != 17:
        errors.append("SELECTED_FLAT_ENTER_COUNT_INVALID")
    if sum(int(row.get("selected_synthetic_add_count") or 0) for row in reports.values()) != 133:
        errors.append("SYNTHETIC_ADD_COUNT_INVALID")
    return errors


def validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = {
        str(row.get("strategy_id") or ""): row
        for row in registry.get("entries", [])
        if isinstance(row, dict)
    }
    for strategy_id in TARGETS:
        row = entries.get(strategy_id)
        if not isinstance(row, dict):
            errors.append(f"REGISTRY_ENTRY_MISSING:{strategy_id}")
            continue
        if str(row.get("strategy_role") or "").lower() != "standalone":
            errors.append(f"ROLE_NOT_STANDALONE:{strategy_id}")
        if str(row.get("execution_scope") or "") != "independent_entry_add_reduce_exit":
            errors.append(f"EXECUTION_SCOPE_INVALID:{strategy_id}")
    return errors


def validate_sources(source_root: Path) -> list[str]:
    errors: list[str] = []
    runner_path = source_root / "tools/r7a4d_historical_simulation_3600.py"
    runner = runner_path.read_text(encoding="utf-8")
    for marker in (
        "def simulate_scenario(",
        "segment_frames[segment_id] = sample",
        '"side": "",',
        '"add_count": 0,',
    ):
        if marker not in runner:
            errors.append(f"RUNNER_MARKER_MISSING:{marker}")
    for strategy_id, markers in STRATEGY_MARKERS.items():
        source_path = source_root / f"backend/strategies/{strategy_id}.py"
        source = source_path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                errors.append(f"STRATEGY_MARKER_MISSING:{strategy_id}:{marker}")
    return errors


def build_plan() -> dict[str, Any]:
    return {
        "schema": "r7a4d2_strategy_specific_entry_chain_plan_v1",
        "official_stage": "R7.A4D2_STRATEGY_SPECIFIC_ENTRY_CHAIN_PLAN",
        "state": "PASS_STRATEGY_SPECIFIC_ENTRY_CHAIN_PLAN",
        "mutation_group_count": 2,
        "simulation_preroll_plan": {
            "indicator_preroll_bars": 320,
            "evaluation_bars": 320,
            "files": [
                "backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json",
                "tools/r7a4d_historical_simulation_3600.py",
                "tests/test_r7a4d_historical_simulation_3600.py",
            ],
            "rules": [
                "load up to 320 bars before selected_start for indicator context",
                "start strategy decisions at evaluation_start only",
                "start fills costs pnl drawdown exposure and trade accounting at evaluation_start only",
                "keep every scenario flat at evaluation_start",
                "retain close-only signal and next-bar-or-later fill semantics",
                "report bars and exposure against the original 320 evaluation bars only",
            ],
        },
        "entry_lineage_plan": {
            "target_strategies": list(TARGETS),
            "strategy_files": [f"backend/strategies/{item}.py" for item in TARGETS],
            "shared_files": [
                "tools/r7a4d_historical_simulation_3600.py",
                "backend/strategy25/canonical_strategy_registry_v1.json",
                "tests/test_r7a4d_historical_simulation_3600.py",
            ],
            "position_fields": ["entry_strategy_id", "entry_event"],
            "rules": [
                "write entry_strategy_id and entry_event only after a valid executed enter",
                "preserve lineage through valid adds and partial reductions",
                "clear lineage on full close",
                "allow add only when entry_strategy_id equals the current strategy id",
                "allow add only when entry_event is one of that strategy's canonical enter reasons",
                "missing or foreign lineage fails closed to hold",
                "do not relax any entry threshold or market filter",
            ],
        },
        "verification_order": [
            "focused unit tests",
            "5 strategies x 24 segments baseline-cost targeted replay",
            "assert orphan_add_count equals zero",
            "assert vwap_revert selected-window executable trade count is positive",
            "assert canonical source-registry SHA parity",
            "rerun the full 3600 matrix from a new result directory",
            "advance to 2880 event replay only if active-only performance gates pass",
        ],
        "protected_scope": [
            "router",
            "service",
            "shadow",
            "paper",
            "live",
            "order_authority",
        ],
        "rollback": "atomic backup and restore of every changed source, registry, contract, and test file",
        "next_stage": "R7.A4D2_ENTRY_CHAIN_MINIMAL_PATCH",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--source-root", default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    source_root = Path(args.source_root).resolve() if args.source_root else root

    evidence_path = root / "runtime/r7a4d2_entry_trigger_chain_causality/entry_trigger_chain_causality_v1.json"
    registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    errors: list[str] = []
    try:
        errors.extend(validate_evidence(load_json(evidence_path)))
        errors.extend(validate_registry(load_json(registry_path)))
        errors.extend(validate_sources(source_root))
    except Exception as exc:
        errors.append(f"INPUT_OR_SOURCE_FAILED:{type(exc).__name__}:{exc}")

    if errors:
        print("STATE=HOLD_PLAN_INPUT_INVALID")
        print("BLOCKER_COUNT=" + str(len(errors)))
        print("BLOCKERS=" + json.dumps(errors, ensure_ascii=False))
        print("NEXT_STAGE=R7.A4D2_STRATEGY_SPECIFIC_ENTRY_CHAIN_PLAN")
        print("RC=2")
        return 2

    plan = build_plan()
    output = root / "runtime/r7a4d2_strategy_specific_entry_chain_plan/entry_chain_plan_v1.json"
    atomic_json(output, plan)
    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=0")
    print("MUTATION_GROUP_COUNT=2")
    print("INDICATOR_PREROLL_BARS=320")
    print("EVALUATION_BARS=320")
    print("LINEAGE_TARGET_STRATEGY_COUNT=5")
    print("ENTRY_THRESHOLD_RELAXATION_ALLOWED=false")
    print("FULL_3600_REEXECUTION_ALLOWED=false")
    print("SOURCE_VALIDATION_ROOT=" + str(source_root))
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
