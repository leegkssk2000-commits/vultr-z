from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "r7a3e3b_strategy25_git_persistence_closure.py"
SPEC = importlib.util.spec_from_file_location("r7a3e3b", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_safe_repo_path_rejects_traversal_and_absolute() -> None:
    assert mod.safe_repo_path("../../etc/passwd") is None
    assert mod.safe_repo_path("/etc/passwd") is None
    assert mod.safe_repo_path("backend\\strategies\\x.py") is None
    assert mod.safe_repo_path("./backend/strategies/x.py") == "backend/strategies/x.py"


def test_prior_gate_accepts_only_live_canonical_persistence_gap() -> None:
    status = {
        "state": "PASS_LIVE_CANONICAL",
        "blocker_count": 0,
        "strategy_count": 25,
        "source_count": 25,
        "callable_count": 25,
        "source_sha_parity_count": 25,
        "config_ref_count": 25,
        "config_resolved_count": 25,
        "unique_config_ref_count": 25,
        "receipt_contract_count": 25,
        "replay_contract_count": 25,
        "target_git_source_parity_count": 0,
        "target_git_registry_parity_count": 0,
        "target_git_config_parity_count": 0,
        "unique_config_file_count": 1,
        "persistence_gap_count": 27,
        "duplicate_binding_count": 0,
        "artifact_reference_count": 0,
        "active_entry_count": 0,
        "static_risk_count": 0,
        "mutation_count": 0,
        "next_stage": "R7.A3E3B_GIT_PERSISTENCE_CLOSURE",
    }
    proof = {"semantic_pass": True, "persistence_complete": False, "persistence_gap_count": 27}
    assert mod.prior_gate(status, proof, 25, 27)
    status["artifact_reference_count"] = 1
    assert not mod.prior_gate(status, proof, 25, 27)


def test_collect_persist_files_returns_exact_27(tmp_path: Path) -> None:
    config_repo = "backend/strategy25/canonical_strategy25_config_v1.json"
    registry_repo = "backend/strategy25/canonical_strategy_registry_v1.json"
    entries = []
    strategies = {}
    for index in range(25):
        strategy_id = f"strategy_{index:02d}"
        repo_path = f"backend/strategies/{strategy_id}.py"
        source = "def run():\n    return 1\n"
        source_path = tmp_path / repo_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(source, encoding="utf-8")
        entries.append({
            "strategy_id": strategy_id,
            "canonical_engine": {
                "implementation_path": repo_path,
                "callable": "run",
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            },
            "config_ref": f"{config_repo}#/strategies/{strategy_id}",
            "active_allowed": False,
            "fail_closed": True,
        })
        strategies[strategy_id] = {"enabled": False}
    write_json(tmp_path / registry_repo, {
        "schema": "canonical_strategy25_registry_v1",
        "fail_closed": True,
        "active_entry_count": 0,
        "entries": entries,
    })
    write_json(tmp_path / config_repo, {
        "schema": "canonical_strategy25_config_v1",
        "strategy_count": 25,
        "active_entry_count": 0,
        "fail_closed": True,
        "strategies": strategies,
    })
    contract = {
        "expected_strategy_count": 25,
        "expected_persist_file_count": 27,
        "registry_path": registry_repo,
        "canonical_config_path": config_repo,
        "allowed_source_prefixes": ["backend/strategies/"],
        "artifact_parts": ["runtime_results", "artifact", "snapshot"],
    }
    files, errors = mod.collect_persist_files(tmp_path, contract)
    assert errors == []
    assert len(files) == 27
    assert registry_repo in files
    assert config_repo in files


def test_collect_rejects_artifact_engine_path(tmp_path: Path) -> None:
    contract = {
        "expected_strategy_count": 1,
        "expected_persist_file_count": 3,
        "registry_path": "backend/strategy25/canonical_strategy_registry_v1.json",
        "canonical_config_path": "backend/strategy25/canonical_strategy25_config_v1.json",
        "allowed_source_prefixes": ["runtime_results/", "backend/strategies/"],
        "artifact_parts": ["runtime_results"],
    }
    write_json(tmp_path / contract["canonical_config_path"], {
        "schema": "canonical_strategy25_config_v1",
        "strategy_count": 1,
        "active_entry_count": 0,
        "fail_closed": True,
        "strategies": {"x": {}},
    })
    write_json(tmp_path / contract["registry_path"], {
        "schema": "canonical_strategy25_registry_v1",
        "fail_closed": True,
        "active_entry_count": 0,
        "entries": [{
            "strategy_id": "x",
            "canonical_engine": {
                "implementation_path": "runtime_results/x.py",
                "callable": "run",
                "source_sha256": "x",
            },
            "config_ref": f"{contract['canonical_config_path']}#/strategies/x",
            "active_allowed": False,
            "fail_closed": True,
        }],
    })
    files, errors = mod.collect_persist_files(tmp_path, contract)
    assert files == sorted([contract["registry_path"], contract["canonical_config_path"]])
    assert any(error.startswith("SOURCE_ARTIFACT_PATH:x") for error in errors)
