#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping

BASE_PATH = Path(__file__).with_name("q4r3_team_advisor_r0_canonical_truth_audit.py")
spec = importlib.util.spec_from_file_location("q4r3_r0_base", BASE_PATH)
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

_original_component_from_unit = base.component_from_unit
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


# The base analyzer resolves these functions from its own module globals.
# Replace them explicitly and assert the bindings so later namespace exports cannot shadow them.
base.component_from_unit = component_from_unit
base.relevant_unit_names = relevant_unit_names
base.owner_proof = owner_proof
assert base.component_from_unit is component_from_unit
assert base.relevant_unit_names is relevant_unit_names
assert base.owner_proof is owner_proof

# Re-export tested helpers while preserving strict overrides.
for name in dir(base):
    if name.startswith("__") or name in {"component_from_unit", "relevant_unit_names", "owner_proof", "main"}:
        continue
    globals()[name] = getattr(base, name)


def main() -> int:
    assert base.component_from_unit is component_from_unit
    assert base.relevant_unit_names is relevant_unit_names
    assert base.owner_proof is owner_proof
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
