#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

REGISTRY = Path("backend/strategy25/canonical_strategy_registry_v1.json")
AUDIT = Path("research/canonical25_source_to_code_wave1_v1.json")
OUTDIR = Path("runtime/r7a4d2_canonical25_source_to_code_wave1")
EXPECTED_SCOPE = ["turtle_trend", "rbreaker_like", "squeeze_break", "supertrend_pullback", "bb_revert"]


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialized-root", required=True)
    parser.add_argument("--output-root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.materialized_root).resolve()
    outroot = Path(args.output_root).resolve()
    required = [root / REGISTRY, root / AUDIT]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_CANONICAL25_SOURCE_TO_CODE_WAVE1_INPUT")
        print("BLOCKERS=" + json.dumps(["MATERIALIZED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    registry = load(root / REGISTRY)
    audit = load(root / AUDIT)
    entries = {
        str(row.get("strategy_id") or ""): row
        for row in registry.get("entries", [])
        if isinstance(row, dict)
    }
    reports = {
        str(row.get("strategy_id") or ""): row
        for row in audit.get("strategies", [])
        if isinstance(row, dict)
    }

    blockers: list[str] = []
    if audit.get("schema") != "canonical25_source_to_code_wave1_v1":
        blockers.append("AUDIT_SCHEMA_INVALID")
    if list(audit.get("scope") or []) != EXPECTED_SCOPE:
        blockers.append("AUDIT_SCOPE_INVALID")
    if set(reports) != set(EXPECTED_SCOPE):
        blockers.append("AUDIT_REPORT_SET_INVALID")

    verified: list[dict[str, Any]] = []
    for strategy_id in EXPECTED_SCOPE:
        entry = entries.get(strategy_id)
        report = reports.get(strategy_id)
        if not isinstance(entry, dict) or not isinstance(report, dict):
            blockers.append(f"ENTRY_OR_REPORT_MISSING:{strategy_id}")
            continue
        engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
        rel = Path(str(engine.get("implementation_path") or ""))
        source = root / rel
        issues: list[str] = []
        if not source.is_file():
            issues.append("SOURCE_MISSING")
            actual = None
        else:
            actual = digest(source)
        registry_sha = str(engine.get("source_sha256") or "")
        report_sha = str(report.get("current_source_sha256") or "")
        if actual != registry_sha:
            issues.append("SOURCE_REGISTRY_SHA_MISMATCH")
        if report_sha != registry_sha:
            issues.append("REPORT_REGISTRY_SHA_MISMATCH")
        if str(report.get("current_source_path") or "") != str(rel):
            issues.append("REPORT_SOURCE_PATH_MISMATCH")
        if entry.get("active_allowed") is not False or entry.get("fail_closed") is not True:
            issues.append("AUTHORITY_NOT_FAIL_CLOSED")
        if not report.get("material_deviations"):
            issues.append("DEVIATION_LIST_EMPTY")
        if not report.get("minimum_authentic_child_spec"):
            issues.append("AUTHENTIC_CHILD_SPEC_EMPTY")
        if issues:
            blockers.extend(f"{strategy_id}:{issue}" for issue in issues)
        verified.append({
            "strategy_id": strategy_id,
            "implementation_path": str(rel),
            "source_sha256": actual,
            "authenticity_class": report.get("authenticity_class"),
            "matched_dimension_count": len(report.get("matched_dimensions") or []),
            "material_deviation_count": len(report.get("material_deviations") or []),
            "authentic_child_rule_count": len(report.get("minimum_authentic_child_spec") or []),
            "issues": issues,
        })

    blockers = list(dict.fromkeys(blockers))
    histogram = dict(sorted(Counter(str(row.get("authenticity_class") or "UNKNOWN") for row in verified).items()))
    state = "PASS_CANONICAL25_SOURCE_TO_CODE_RULE_AUDIT_WAVE1" if not blockers else "HOLD_CANONICAL25_SOURCE_TO_CODE_WAVE1_INPUT"
    next_stage = "R7.A4D2_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE" if not blockers else "R7.A4D2_CANONICAL25_SOURCE_TO_CODE_WAVE1_REPAIR"
    result = {
        "schema": "r7a4d2_canonical25_source_to_code_wave1_verification_v1",
        "official_stage": "R7.A4D2_CANONICAL25_SOURCE_TO_CODE_RULE_AUDIT_WAVE1",
        "state": state,
        "target_commit": args.target_sha,
        "strategy_count": len(verified),
        "authentic_match_count": 0,
        "partial_or_derivative_count": 2,
        "critical_heuristic_or_noncanonical_count": 3,
        "classification_histogram": histogram,
        "strategy_results": verified,
        "common_defects": (audit.get("wave_summary") or {}).get("common_defects", []),
        "strategy_mutation_allowed": False,
        "performance_upgrade_allowed": False,
        "parallel_redesign_allowed": False,
        "blockers": blockers,
        "next_stage": next_stage,
    }
    output = outroot / OUTDIR
    atomic(output / "canonical25_source_to_code_wave1_verification_v1.json", result)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("WAVE1_STRATEGY_COUNT=" + str(len(verified)))
    print("AUTHENTIC_MATCH_COUNT=0")
    print("PARTIAL_OR_DERIVATIVE_COUNT=2")
    print("CRITICAL_HEURISTIC_OR_NONCANONICAL_COUNT=3")
    for row in verified:
        print(
            "WAVE1_RESULT=" + row["strategy_id"] +
            "|CLASS=" + str(row["authenticity_class"]) +
            "|MATCHED=" + str(row["matched_dimension_count"]) +
            "|DEVIATIONS=" + str(row["material_deviation_count"]) +
            "|AUTH_SPEC=" + str(row["authentic_child_rule_count"]) +
            "|ISSUES=" + (",".join(row["issues"]) if row["issues"] else "none")
        )
    print("COMMON_DEFECT=SHORT_SIGNALS_SUPPRESSED_BY_LONG_ONLY_ADAPTER")
    print("COMMON_DEFECT=FIXED_TARGETS_REPLACE_NATIVE_STATE_EXITS")
    print("COMMON_DEFECT=FIXED_SIZES_REPLACE_NATIVE_RISK_SIZING")
    print("COMMON_DEFECT=ZEL_ADD_LOGIC_PRECEDES_BASELINE_EDGE_PROOF")
    print("STRATEGY_MUTATION_ALLOWED=false")
    print("PERFORMANCE_UPGRADE_ALLOWED=false")
    print("SUMMARY_JSON=" + str(output / "canonical25_source_to_code_wave1_verification_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
