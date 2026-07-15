from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r0_canonical_truth_audit_strict.py"
ALIASES_PATH = ROOT / "backend/config/q4r3_r0_candidate_aliases_v1.json"

spec = importlib.util.spec_from_file_location("r0_strict", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ALIASES = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))


def test_all_strict_bindings_reach_base_analyzer() -> None:
    assert module.base.owner_proof is module.owner_proof
    assert module.base.component_from_unit is module.component_from_unit
    assert module.base.relevant_unit_names is module.relevant_unit_names


def test_generic_team_lane_unit_discovers_all_teams() -> None:
    components = module.component_from_unit("zel-legendary-team-lane-w179.service", ALIASES)
    assert components == ["AlphaTeam", "BetaTeam", "DeltaTeam", "GammaTeam"]


def test_generic_team_lane_does_not_prove_owner_without_structured_identity() -> None:
    candidate = {
        "identity_evidence": ["active_unit_binding"],
        "owner_kind": "runtime_core",
        "direct_order_calls": [],
        "sensitive_credential_access": [],
        "git": {"tracked": False},
        "contract_version": None,
    }
    assert module.owner_proof(candidate) is False


def test_generic_team_lane_can_prove_owner_with_explicit_assignment() -> None:
    candidate = {
        "identity_evidence": ["active_unit_binding", "structured_team_assignment"],
        "owner_kind": "runtime_core",
        "direct_order_calls": [],
        "sensitive_credential_access": [],
        "git": {"tracked": False},
        "contract_version": None,
    }
    assert module.owner_proof(candidate) is True
