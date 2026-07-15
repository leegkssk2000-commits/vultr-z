#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

BASE_PATH = Path(__file__).with_name("q4r3_team_advisor_r0_canonical_truth_audit.py")
spec = importlib.util.spec_from_file_location("q4r3_r0_base", BASE_PATH)
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

_original_component_from_unit = base.component_from_unit
_original_analyze = base.analyze
GENERIC_TEAM_UNIT_TOKENS = ("team-lane", "team_lane", "teambot", "team-bot")
TEAM_COMPONENTS = ("AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam")


def component_from_unit(unit: str, aliases: Mapping[str, Any]) -> list[str]:
    result = set(_original_component_from_unit(unit, aliases))
    normalized_unit = unit.lower()
    if any(token in normalized_unit for token in GENERIC_TEAM_UNIT_TOKENS):
        result.update(TEAM_COMPONENTS)
    return sorted(result)


def relevant_unit_names(aliases: Mapping[str, Any]) -> list[str]:
    names: set[str] = set()
    for command in (
        ["systemctl", "list-unit-files", "--no-legend", "--no-pager"],
        ["systemctl", "list-units", "--all", "--no-legend", "--no-pager"],
    ):
        listing = base.run(command, timeout=30)
        for line in listing.stdout.splitlines():
            fields = line.split()
            if not fields:
                continue
            unit = fields[0]
            if component_from_unit(unit, aliases):
                names.add(unit)
    return sorted(names)


def owner_proof(candidate: Mapping[str, Any]) -> bool:
    evidence = set(candidate.get("identity_evidence", []))
    kind = candidate.get("owner_kind")
    if candidate.get("direct_order_calls") or candidate.get("sensitive_credential_access"):
        return False
    if kind in {"test_support", "ui_consumer", "service_wrapper"}:
        return False
    identity_proven = bool({"exact_path_identity", "structured_team_assignment"}.intersection(evidence))
    if "active_unit_binding" in evidence and identity_proven:
        return True
    if identity_proven and candidate.get("git", {}).get("tracked") and candidate.get("contract_version"):
        return True
    return False


def complete_candidate_inventory(args: Any, result: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    aliases = base.load_aliases(args.aliases)
    units = list(result.get("runtime", {}).get("units", []))
    bindings = base.active_bindings(units)
    unit_component_map: defaultdict[str, list[str]] = defaultdict(list)
    for record in units:
        if record.get("active_state") != "active":
            continue
        components = [base.canonical_component(value) for value in record.get("components", [])]
        for script in record.get("resolved_script_paths", []):
            unit_component_map[base.resolve_path(Path(script))].extend(components)
        for wrapper in record.get("wrapper_chains", []):
            for item in wrapper.get("chain", []):
                unit_component_map[base.resolve_path(Path(item))].extend(components)

    roots = base.canonical_roots(args.root, units)
    inventory: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in base.iter_text_files(roots):
        contaminated, _ = base.path_is_contaminated(path)
        if contaminated:
            continue
        text = base.read_small_text(path)
        if not text:
            continue
        components, identity = base.candidate_components(path, text, aliases, unit_component_map)
        if not components:
            continue
        order_calls, credentials = base.authority_evidence(path, text)
        lower = text.lower()
        common = {
            "path": base.resolve_path(path),
            "owner_kind": base.file_kind(path),
            "sha256": base.sha256(path),
            "contract_version": base.contract_version(text),
            "active_units": bindings.get(base.resolve_path(path), []),
            "direct_order_calls": order_calls,
            "sensitive_credential_access": credentials,
            "git": base.git_metadata(args.root, path),
            "zbot_surfaces": base.surface_hits(lower, base.ZBOT_SURFACES),
            "zico_surfaces": base.surface_hits(lower, base.ZICO_SURFACES),
            "lico_surfaces": base.surface_hits(lower, base.LICO_SURFACES),
        }
        for component in components:
            candidate = dict(common)
            candidate["component"] = component
            candidate["identity_evidence"] = identity.get(component, [])
            candidate["score"] = base.candidate_score(candidate)
            recommendation, recommendation_reason = base.classification(candidate)
            candidate["classification_recommendation"] = recommendation
            candidate["classification_reason"] = recommendation_reason
            inventory[component].append(candidate)
    return {
        component: sorted(values, key=lambda item: (-int(item["score"]), item["path"]))
        for component, values in sorted(inventory.items())
    }


def analyze(args: Any) -> dict[str, Any]:
    result = _original_analyze(args)
    inventory = complete_candidate_inventory(args, result)
    result["candidate_inventory"] = inventory
    for component in result.get("scope", []):
        values = inventory.get(component, [])
        result["owner_matrix"][component]["all_candidates"] = values
        result["owner_matrix"][component]["candidate_count"] = len(values)
        result["owner_matrix"][component]["top_candidates"] = values[:15]
    result["scan"]["complete_candidate_inventory_count"] = sum(len(values) for values in inventory.values())
    return result


# The base analyzer resolves these functions from its own module globals.
# Replace them explicitly and assert the bindings so namespace export order cannot shadow them.
base.component_from_unit = component_from_unit
base.relevant_unit_names = relevant_unit_names
base.owner_proof = owner_proof
base.analyze = analyze
assert base.component_from_unit is component_from_unit
assert base.relevant_unit_names is relevant_unit_names
assert base.owner_proof is owner_proof
assert base.analyze is analyze

# Re-export tested helpers while preserving strict overrides.
for name in dir(base):
    if name.startswith("__") or name in {"component_from_unit", "relevant_unit_names", "owner_proof", "analyze", "main"}:
        continue
    globals()[name] = getattr(base, name)


def main() -> int:
    assert base.component_from_unit is component_from_unit
    assert base.relevant_unit_names is relevant_unit_names
    assert base.owner_proof is owner_proof
    assert base.analyze is analyze
    args = base.build_parser().parse_args()
    result = analyze(args)
    base.atomic_json(args.output, result)
    base.atomic_json(args.units_output, result["runtime"]["units"])
    base.atomic_json(args.candidates_output, result["candidate_inventory"])
    print(json.dumps({
        "state": result["state"],
        "verdict": result["verdict"],
        "canonical_owner_count": result["exit_gate"]["canonical_owner_count"],
        "duplicate_owner_count": result["exit_gate"]["duplicate_owner_count"],
        "active_exec_mapping_pct": result["exit_gate"]["active_exec_mapping_pct"],
        "complete_candidate_inventory_count": result["scan"]["complete_candidate_inventory_count"],
        "fix_queue_count": len(result["fix_queue"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
