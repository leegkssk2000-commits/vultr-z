#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BAD_PARITY = {
    "MISMATCH",
    "UNTRACKED_DEPLOYED_SOURCE",
    "MISSING_DEPLOYED_SOURCE",
    "AMBIGUOUS_REPO_BASENAME",
}


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("INPUT_NOT_OBJECT")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_action(row: dict[str, Any]) -> str:
    parity = str(row.get("parity", ""))
    if parity == "UNTRACKED_DEPLOYED_SOURCE":
        return "IMPORT_OR_MAP_TO_CANONICAL_GIT_SOURCE"
    if parity == "MISMATCH":
        return "DIFF_DEPLOYED_VS_GIT_AND_SELECT_CANONICAL_SHA"
    if parity == "MISSING_DEPLOYED_SOURCE":
        return "RECOVER_REQUIRED_SOURCE_OR_RETIRE_UNIT"
    if parity == "AMBIGUOUS_REPO_BASENAME":
        return "PIN_EXACT_REPO_PATH_IN_RELEASE_MANIFEST"
    return "INSPECT"


def surface_action(field: str) -> str:
    if field in {"configured_writer_count", "active_writer_count", "writers"}:
        return "SEPARATE_CONFIGURED_REGISTRY_FROM_ACTIVE_AUTHORITY"
    if field in {"epoch", "closed", "pnl_r", "recent_rows", "winrate_pct", "ev_r", "last_close"}:
        return "BIND_ALL_RENDERERS_TO_ONE_TYPED_SNAPSHOT"
    if field in {"order", "exec", "runtime_active", "formal_ledger_bound"}:
        return "NORMALIZE_AUTHORITY_STATUS_SCHEMA"
    return "DEFINE_TYPED_FIELD_CONTRACT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(args.contract)
    data = read_json(args.input)

    audit_state = str(data.get("audit_execution", {}).get("state", ""))
    correction = data.get("audit_correction", {})
    correction_state = str(correction.get("state", ""))
    mutation_count = int(correction.get("mutation_count", data.get("audit_execution", {}).get("mutation_count", -1)) or 0)
    errors: list[str] = []
    if audit_state != "PASS":
        errors.append(f"BASE_AUDIT_NOT_PASS:{audit_state}")
    if correction_state != "PASS":
        errors.append(f"AUDIT_CORRECTION_NOT_PASS:{correction_state}")
    if mutation_count != 0:
        errors.append(f"BASE_MUTATION_COUNT_{mutation_count}")

    axes = data.get("axes", {}) if isinstance(data.get("axes"), dict) else {}
    lifecycle = axes.get("trade_lifecycle", {}) if isinstance(axes.get("trade_lifecycle"), dict) else {}
    display = axes.get("display_ledger_observability", {}) if isinstance(axes.get("display_ledger_observability"), dict) else {}

    source_gaps = [
        row for row in lifecycle.get("active_source_parity_gaps", [])
        if isinstance(row, dict) and str(row.get("parity")) in BAD_PARITY
    ]
    source_gap_plan = [
        {
            "unit": row.get("unit"),
            "source": row.get("source"),
            "repo_path": row.get("repo_path"),
            "parity": row.get("parity"),
            "repo_candidates": row.get("repo_candidates", []),
            "git_sha256": row.get("git_sha256"),
            "deployed_sha256": row.get("deployed_sha256"),
            "action": source_action(row),
        }
        for row in source_gaps
    ]

    surface_mismatches = [row for row in display.get("surface_mismatches", []) if isinstance(row, dict)]
    surface_plan = [
        {
            "field": row.get("field"),
            "values": row.get("values", {}),
            "action": surface_action(str(row.get("field", ""))),
        }
        for row in surface_mismatches
    ]

    axis_summary: dict[str, Any] = {}
    for name in contract.get("axis_order", []):
        axis = axes.get(name, {}) if isinstance(axes.get(name), dict) else {}
        axis_summary[name] = {
            "grade": axis.get("grade"),
            "blockers": list(axis.get("blockers", [])),
        }

    active_authority = lifecycle.get("active_authority_by_role", {})
    duplicate_roles = lifecycle.get("duplicate_active_authority_roles", {})
    start_candidates = lifecycle.get("shadow_start_candidates", [])
    git_parity = data.get("git_deployment_parity", {}) if isinstance(data.get("git_deployment_parity"), dict) else {}
    git_mismatches = list(git_parity.get("mismatches", []))
    duplicate_schemas = data.get("duplicate_production_schemas", {})

    priorities: list[dict[str, Any]] = []
    if source_gap_plan:
        priorities.append({"priority": 0, "work": "ACTIVE_APPLICATION_SOURCE_PROVENANCE", "count": len(source_gap_plan)})
    if duplicate_roles or len(start_candidates) != 1:
        priorities.append({"priority": 0, "work": "LIFECYCLE_SINGLE_AUTHORITY", "duplicate_roles": duplicate_roles, "start_candidates": start_candidates})
    if surface_plan:
        priorities.append({"priority": 1, "work": "DISPLAY_TYPED_SURFACE_PARITY", "count": len(surface_plan)})
    if git_mismatches:
        priorities.append({"priority": 2, "work": "GIT_DEPLOYMENT_MISMATCH_DIFF", "count": len(git_mismatches)})
    non_a_axes = [name for name, axis in axis_summary.items() if axis.get("grade") != "A"]
    if non_a_axes:
        priorities.append({"priority": 3, "work": "SEVEN_AXIS_S_GRADE_UPGRADE", "axes": non_a_axes})

    if source_gap_plan:
        next_stage = "R7.A1A_ACTIVE_SOURCE_PROVENANCE_PLAN"
    elif duplicate_roles or len(start_candidates) != 1:
        next_stage = "R7.A1B_LIFECYCLE_SINGLE_AUTHORITY_PLAN"
    elif surface_plan:
        next_stage = "R7.A1C_TYPED_SURFACE_PARITY_PLAN"
    else:
        next_stage = "R7.B_STRATEGY25_S_MATERIAL"

    plan_state = "PASS" if not errors else "HOLD"
    payload: dict[str, Any] = {
        "schema": "zos_r7a1_canonical_gap_authority_plan_status_v1",
        "official_stage": "R7.A1",
        "plan_execution": {
            "state": plan_state,
            "mutation_count": 0,
            "errors": errors,
            "base_audit_state": audit_state,
            "base_correction_state": correction_state,
        },
        "runtime_readiness": "HOLD",
        "axis_summary": axis_summary,
        "active_authority_by_role": active_authority,
        "duplicate_active_authority_roles": duplicate_roles,
        "shadow_start_candidates": start_candidates,
        "active_source_parity_gaps": source_gap_plan,
        "surface_mismatches": surface_plan,
        "git_deployment_mismatches": git_mismatches,
        "duplicate_production_schemas": duplicate_schemas,
        "priorities": priorities,
        "next_stage": next_stage,
        "evidence_paths": {"json": str(args.output), "markdown": str(args.report)},
    }
    write_json(args.output, payload)

    lines = [
        "# R7.A1 Canonical Gap and Authority Plan",
        "",
        f"- Plan execution: **{plan_state}**",
        "- Runtime readiness: **HOLD**",
        f"- Source parity gaps: **{len(source_gap_plan)}**",
        f"- Surface mismatches: **{len(surface_plan)}**",
        f"- Shadow start candidates: **{len(start_candidates)}**",
        f"- Duplicate active roles: **{len(duplicate_roles)}**",
        "",
        "## Seven axes",
        "",
        "| Axis | Grade | Blockers |",
        "|---|---:|---|",
    ]
    for name, axis in axis_summary.items():
        blockers = "; ".join(axis.get("blockers", [])) or "none"
        lines.append(f"| {name} | **{axis.get('grade')}** | {blockers} |")
    lines += ["", "## Active source parity gaps", ""]
    for row in source_gap_plan:
        lines.append(f"- `{row.get('unit')}` · `{row.get('source')}` · **{row.get('parity')}** · {row.get('action')}")
    lines += ["", "## Surface mismatches", ""]
    for row in surface_plan:
        lines.append(f"- `{row.get('field')}` · `{json.dumps(row.get('values'), sort_keys=True)}` · {row.get('action')}")
    lines += ["", "## Priority sequence", ""]
    for row in priorities:
        lines.append(f"- P{row.get('priority')} · {row.get('work')}")
    lines += ["", f"Next stage: **{next_stage}**", ""]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8")

    print("R7A1_CANONICAL_GAP_AUTHORITY_PLAN_COMPLETE")
    print(f"PLAN_EXECUTION_STATE={plan_state}")
    print("MUTATION_COUNT=0")
    print(f"SOURCE_PARITY_GAP_COUNT={len(source_gap_plan)}")
    for index, row in enumerate(source_gap_plan, 1):
        print(f"SOURCE_GAP_{index}={row.get('unit')}|{row.get('source')}|{row.get('parity')}|{row.get('action')}")
    print(f"SURFACE_MISMATCH_COUNT={len(surface_plan)}")
    for index, row in enumerate(surface_plan, 1):
        print(f"SURFACE_GAP_{index}={row.get('field')}|{json.dumps(row.get('values'), sort_keys=True)}|{row.get('action')}")
    print(f"SHADOW_START_CANDIDATES={len(start_candidates)}")
    print(f"DUPLICATE_ACTIVE_ROLES={len(duplicate_roles)}")
    print(f"GIT_DEPLOYMENT_MISMATCH_COUNT={len(git_mismatches)}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={args.output}")
    print(f"EVIDENCE_REPORT={args.report}")
    return 0 if plan_state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
