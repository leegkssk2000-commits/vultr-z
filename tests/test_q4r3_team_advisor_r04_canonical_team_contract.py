from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r04_validate_canonical_team_contract.py"
CONTRACT_PATH = ROOT / "config/q4r3_team_canonical_contract_v1.json"

spec = importlib.util.spec_from_file_location("r04", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def recovery() -> dict:
    return {
        "schema": "q4r3_team_advisor_r03_team_assignment_recovery_v1",
        "source_sha_parity_count": 2,
        "complete_explicit_assignment_count": 0,
        "next_route": "BUILD_CANONICAL_TEAM_CONTRACT_FROM_RECOVERED_EVIDENCE_WITHOUT_GUESSING",
    }


def test_contract_is_valid() -> None:
    blockers, summary = module.validate(load_contract(), recovery())
    assert blockers == []
    assert summary["team_count"] == 4
    assert summary["zbot_external_only"] is True


def test_exact_team_leads() -> None:
    teams = load_contract()["teams"]
    assert teams["AlphaTeam"]["main"] == "LBot"
    assert teams["BetaTeam"]["main"] == "MBot"
    assert teams["GammaTeam"]["main"] == "OBot"
    assert teams["DeltaTeam"]["main"] == "SBot"


def test_zbot_stays_external() -> None:
    value = load_contract()
    assert value["global_rules"]["zbot_is_team_bot"] is False
    assert value["global_rules"]["zbot_team_vote_allowed"] is False
    for row in value["teams"].values():
        assert row["external_proof_watcher"] == "ZBot"
        assert "ZBot" not in [row["main"], row["support"], *row["watchers"]]


def test_team_shape_and_helper() -> None:
    value = load_contract()
    for row in value["teams"].values():
        assert row["main"] != row["support"]
        assert len(row["watchers"]) == 2
        assert row["conditional_helpers"]
        assert row["helper_triggers"]
    assert value["global_rules"]["helper_extra_vote_allowed"] is False


def test_r04_is_design_only() -> None:
    value = load_contract()
    assert value["global_rules"]["runtime_activation_allowed"] is False
    assert value["global_rules"]["execution_authority"] == "none"
    assert value["activation_gates"]["runtime_binding_change_allowed_in_r04"] is False
