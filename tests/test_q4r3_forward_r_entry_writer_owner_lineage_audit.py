from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_forward_r_entry_writer_owner_lineage_audit.py"
    spec = importlib.util.spec_from_file_location("q4r3_entry_writer_owner_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_external_dependencies_are_excluded() -> None:
    assert MODULE.is_repo_owned_path(Path("/home/z/z/backend/.venv/lib/python3.11/site-packages/ccxt/a.py")) is False
    assert MODULE.is_repo_owned_path(Path("/home/z/z/node_modules/pkg/index.py")) is False


def test_repo_code_and_systemd_units_are_allowed() -> None:
    assert MODULE.is_repo_owned_path(Path("/home/z/z/backend/journal.py")) is True
    assert MODULE.is_repo_owned_path(Path("/etc/systemd/system/zel-writer.service")) is True


def test_diagnostic_matching_is_boundary_aware() -> None:
    assert MODULE.is_diagnostic_path(Path("/home/z/z/tests/test_writer.py")) is True
    assert MODULE.is_diagnostic_path(Path("/home/z/z/tools/q4r3_route_a_probe.py")) is True
    assert MODULE.is_diagnostic_path(Path("/home/z/z/backend/latest_writer.py")) is False


def test_authoritative_open_sources_use_exact_paths() -> None:
    source = {
        "authoritative_files": [
            {"path": "/home/z/z/runtime/paper_order_ledger_state.json", "open_rows": 4},
            {"path": "/home/z/z/runtime/h87_shadow_closed_ledger_latest.json", "open_rows": 0},
        ]
    }
    audit = {
        "files": [
            {"path": "/home/z/z/runtime/paper_order_ledger_state.json", "open_contract_rows": 7},
            {"path": "/home/z/z/runtime/h87_shadow_closed_ledger_latest.json", "open_contract_rows": 0},
        ]
    }
    rows = MODULE.authoritative_open_sources(source, audit)
    assert rows == [{"path": "/home/z/z/runtime/paper_order_ledger_state.json", "basename": "paper_order_ledger_state.json", "open_rows": 7}]


def test_decision_requires_runtime_trace_when_sources_have_no_owner() -> None:
    lineage = {
        "dominant_single_entry_owner": False,
        "dominant_entry_owner": None,
        "unresolved_authoritative_sources": ["paper_order_ledger_state.json"],
        "dominant_open_row_coverage_pct": 0.0,
        "external_dependency_paths_excluded": True,
    }
    audit = {"formula_ready_unique_ids": 0, "explicit_risk_rows": 0}
    prior = {"prior_stable_id_join_rate_pct": 82.068}
    decision = MODULE.decide(lineage, audit, prior)
    assert decision["verdict"] == "ENTRY_WRITER_OWNER_NOT_FOUND_RUNTIME_WRITE_TRACE_REQUIRED"


def test_decision_allows_atomic_entry_contract_only_for_dominant_owner() -> None:
    lineage = {
        "dominant_single_entry_owner": True,
        "dominant_entry_owner": {"path": "/home/z/z/backend/entry_writer.py"},
        "unresolved_authoritative_sources": [],
        "dominant_open_row_coverage_pct": 90.0,
        "external_dependency_paths_excluded": True,
    }
    audit = {"formula_ready_unique_ids": 0, "explicit_risk_rows": 0}
    prior = {"prior_stable_id_join_rate_pct": 82.068}
    decision = MODULE.decide(lineage, audit, prior)
    assert decision["verdict"] == "ENTRY_OWNER_CONFIRMED_MULTI_FIELD_PERSISTENCE_CANARY_READY"
    assert decision["next_action"] == "PATCH_ENTRY_PRICE_STOP_SIZE_AND_INITIAL_RISK_AS_ATOMIC_ENTRY_CONTRACT_CANARY"
