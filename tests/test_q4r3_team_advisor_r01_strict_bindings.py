from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r01_owner_adjudication_strict.py"
spec = importlib.util.spec_from_file_location("r01_strict", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_bindings() -> None:
    assert module.base.policy_pct is module.policy_pct
    assert module.base.adjudication_route is module.adjudication_route
    assert module.base.build_report is module.build_report


def test_r0_policy_schema() -> None:
    truth = {"policy_surface_coverage": {"ZBot": {"coverage_pct": 15.3846}}}
    assert module.policy_pct(truth, "ZBot") == 15.3846


def test_zico_owner_schema() -> None:
    state = {
        "canonical_owner": {"path": "/external/zico/adapter.py", "git": {"tracked": False}},
        "proven_owner_count": 1,
    }
    route, _ = module.adjudication_route("Zico", state, [], [], ["/external/zico/adapter.py"], [], 44.4444)
    assert route == "MIRROR_ACTIVE_RUNTIME_TO_GIT"


def test_exit_gate_baseline() -> None:
    truth = {
        "state": "HOLD",
        "verdict": "R0_CANONICAL_TRUTH_UNRESOLVED",
        "exit_gate": {"canonical_owner_count": 1, "duplicate_owner_count": 0, "active_exec_mapping_pct": 100.0},
        "candidate_inventory": {"LBot": [{}, {}], "Zico": [{}]},
        "owner_matrix": {},
        "fix_queue": [{}, {}],
    }
    report = module.build_report(Path("/tmp/r01-empty"), truth, {}, [])
    assert report["r0_baseline"]["canonical_owner_count"] == 1
    assert report["r0_baseline"]["complete_candidate_inventory_count"] == 3
    assert report["r0_baseline"]["fix_queue_count"] == 2
