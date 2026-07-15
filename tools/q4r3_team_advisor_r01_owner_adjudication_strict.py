#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping, Sequence

BASE_PATH = Path(__file__).with_name("q4r3_team_advisor_r01_owner_adjudication.py")
spec = importlib.util.spec_from_file_location("q4r3_r01_base", BASE_PATH)
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def policy_pct(truth: Mapping[str, Any], component: str) -> float | None:
    surfaces = truth.get("policy_surface_coverage", {})
    row = surfaces.get(component) if isinstance(surfaces, Mapping) else None
    if not isinstance(row, Mapping):
        return None
    value = row.get("coverage_pct")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def adjudication_route(
    component: str,
    owner_state: Mapping[str, Any],
    candidate_rows: Sequence[Mapping[str, Any]],
    package_groups: Sequence[Mapping[str, Any]],
    active_scripts: Sequence[str],
    runtime_manifests: Sequence[Mapping[str, Any]],
    policy_surface_pct: float | None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    canonical = owner_state.get("canonical_owner") if isinstance(owner_state, Mapping) else None
    proven_count = int(owner_state.get("proven_owner_count") or 0) if isinstance(owner_state, Mapping) else 0
    if component == "Zico" and proven_count == 1 and isinstance(canonical, Mapping):
        owner_path = str(canonical.get("path") or "")
        tracked = bool(canonical.get("git", {}).get("tracked"))
        if owner_path.startswith("/") and not tracked:
            reasons.append("active owner is external to repository and must be mirrored before lock")
            return "MIRROR_ACTIVE_RUNTIME_TO_GIT", reasons
    if component in base.TEAM_COMPONENTS:
        assignments = [item for manifest in runtime_manifests for item in manifest.get("role_assignments", [])]
        component_name = component.removesuffix("Team")
        matching = [item for item in assignments if str(item.get("team_id") or "").lower() in {component.lower(), component_name.lower()}]
        if matching:
            reasons.append("active Team Lane source contains explicit organizational assignment evidence")
            return "RECOVER_TEAM_PACKAGE_FROM_ACTIVE_RUNTIME", reasons
        reasons.append("no canonical Team package or explicit role assignment was proven")
        return "CREATE_CANONICAL_TEAM_PACKAGE_AFTER_ASSIGNMENT_RECOVERY", reasons
    if component == "ZBot" and policy_surface_pct is not None and policy_surface_pct < 100.0:
        reasons.append(f"dual-provider policy surfaces incomplete: {policy_surface_pct}%")
        return "CONSOLIDATE_ZBOT_AND_BUILD_PROVIDER_POLICY_PACKAGE", reasons
    if component == "Lico":
        reasons.append("Lico is a multi-stage source/consumption pipeline and must become one package owner")
        return "CONSOLIDATE_LICO_PIPELINE_AND_ADD_SOURCE_CONSENSUS", reasons
    if component == "Zlice":
        reasons.append("Zlice implementation and UI consumers must be separated under an evidence-core owner")
        return "SPLIT_ZLICE_EVIDENCE_CORE_FROM_UI", reasons
    if len(package_groups) > 1 or len(candidate_rows) > 1:
        reasons.append(f"{len(candidate_rows)} file candidates across {len(package_groups)} package groups")
        return "PACKAGE_CONSOLIDATION_REQUIRED", reasons
    if len(candidate_rows) == 1:
        candidate = candidate_rows[0]
        if not candidate.get("git", {}).get("tracked") or not candidate.get("contract_version"):
            reasons.append("single implementation exists but lacks tracked contract/version proof")
            return "PROMOTE_EXISTING_SOURCE_TO_CANONICAL_PACKAGE", reasons
    if not candidate_rows and active_scripts:
        reasons.append("runtime source exists but was not accepted as canonical candidate")
        return "RECOVER_RUNTIME_SOURCE_TO_CANONICAL_PACKAGE", reasons
    reasons.append("no sufficient implementation evidence")
    return "CANONICAL_IMPLEMENTATION_MISSING", reasons


_original_build_report = base.build_report


def build_report(root: Path, truth: Mapping[str, Any], candidates_doc: Mapping[str, Any], units: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    report = _original_build_report(root, truth, candidates_doc, units)
    gate = truth.get("exit_gate", {}) if isinstance(truth.get("exit_gate"), Mapping) else {}
    inventory = truth.get("candidate_inventory", {}) if isinstance(truth.get("candidate_inventory"), Mapping) else {}
    report["r0_baseline"] = {
        "state": truth.get("state"),
        "verdict": truth.get("verdict"),
        "canonical_owner_count": gate.get("canonical_owner_count"),
        "duplicate_owner_count": gate.get("duplicate_owner_count"),
        "active_exec_mapping_pct": gate.get("active_exec_mapping_pct"),
        "complete_candidate_inventory_count": sum(len(value) for value in inventory.values() if isinstance(value, list)),
        "fix_queue_count": len(truth.get("fix_queue", [])) if isinstance(truth.get("fix_queue"), list) else None,
    }
    public_component_names = list(report.get("components", {}).keys())
    public_component_names.extend(str(item.get("component")) for item in report.get("fix_queue", []))
    report["canonical_name_violations"] = sorted({
        name for name in public_component_names if name in base.LEGACY_OUTPUT_NAMES
    })
    return report


base.policy_pct = policy_pct
base.adjudication_route = adjudication_route
base.build_report = build_report
assert base.policy_pct is policy_pct
assert base.adjudication_route is adjudication_route
assert base.build_report is build_report

for name in dir(base):
    if name.startswith("__") or name in {"policy_pct", "adjudication_route", "build_report", "main"}:
        continue
    globals()[name] = getattr(base, name)


def main() -> int:
    assert base.policy_pct is policy_pct
    assert base.adjudication_route is adjudication_route
    assert base.build_report is build_report
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
