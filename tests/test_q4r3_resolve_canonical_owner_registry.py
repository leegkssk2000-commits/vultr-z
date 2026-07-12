from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_resolve_canonical_owner_registry.py"
    spec = importlib.util.spec_from_file_location("q4r3_resolve_canonical_owner_registry_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def owner_item(index: int) -> dict:
    strategy = f"strategy_{index:02d}"
    return {
        "strategy": strategy,
        "verdict": "PROPOSED_OWNER_CONFIDENT",
        "proposed_owner": f"backend/strategies/{strategy}.py",
        "proposed_owner_kind": "canonical",
        "proposed_owner_sha256": f"sha-{index}",
        "confidence": 0.95,
        "alternatives": [],
    }


def test_false_exact_registries_are_rejected() -> None:
    matrix = {
        "owners": [owner_item(index) for index in range(25)],
        "registry_audit": {
            "verdict": "MULTIPLE_EXACT_25_REGISTRY_CANDIDATES",
            "exact_coverage_files": [
                "backend/trade_methods/policy.py",
                "backend/trade_methods/profiles.py",
                "data/strategy_registry_latest.json",
            ],
            "files": [
                {"path": "backend/trade_methods/policy.py", "coverage_count": 25, "coverage_pct": 100.0, "sha256": "a"},
                {"path": "backend/trade_methods/profiles.py", "coverage_count": 25, "coverage_pct": 100.0, "sha256": "b"},
                {"path": "data/strategy_registry_latest.json", "coverage_count": 25, "coverage_pct": 100.0, "sha256": "c"},
            ],
        },
    }
    result = MODULE.resolve(matrix)
    assert result["resolved_owner_count"] == 25
    assert result["unresolved_owner_count"] == 0
    assert result["verdict"] == "CANONICAL_25_OWNER_MANIFEST_READY_REGISTRY_AUTHORITY_ABSENT"
    assert result["registry_resolution"]["authoritative_candidate"] is None
    assert len(result["registry_resolution"]["false_exact_candidates_rejected"]) == 3


def test_one_structural_registry_candidate_is_retained() -> None:
    matrix = {
        "owners": [owner_item(index) for index in range(25)],
        "registry_audit": {
            "verdict": "SINGLE_EXACT_25_REGISTRY_CANDIDATE",
            "exact_coverage_files": ["backend/canonical_strategy_registry.json"],
            "files": [
                {"path": "backend/canonical_strategy_registry.json", "coverage_count": 25, "coverage_pct": 100.0, "sha256": "x"}
            ],
        },
    }
    result = MODULE.resolve(matrix)
    assert result["verdict"] == "CANONICAL_25_OWNER_MANIFEST_READY_WITH_REGISTRY_CANDIDATE"
    assert result["registry_resolution"]["authoritative_candidate"] == "backend/canonical_strategy_registry.json"


def test_unresolved_owner_blocks_manifest_completion() -> None:
    owners = [owner_item(index) for index in range(25)]
    owners[-1]["verdict"] = "NO_SPECIALIZED_DIRECT_OWNER"
    owners[-1]["proposed_owner"] = None
    owners[-1]["proposed_owner_sha256"] = None
    result = MODULE.resolve({"owners": owners, "registry_audit": {"files": []}})
    assert result["verdict"] == "CANONICAL_OWNER_MANIFEST_INCOMPLETE"
    assert result["unresolved_owner_count"] == 1
