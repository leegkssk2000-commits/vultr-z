from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_exact25_staged_active_apply.py"
    spec = importlib.util.spec_from_file_location("q4r3_exact25_staged_active_apply_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def strategy_source(strategy_id: str, marker: str = "active") -> str:
    return (
        f"STRATEGY_ID = {strategy_id!r}\n"
        f"MARKER = {marker!r}\n"
        "def strategy(df=None, state=None, risk_action='hold'):\n"
        "    return {'action': 'hold', 'size': 0.0}\n"
    )


def prepare_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    active_root = tmp_path / "active"
    candidate_root = tmp_path / "candidate"
    runtime_root = tmp_path / "runtime"
    active_strategy_root = active_root / "backend" / "strategies"
    candidate_strategy_root = candidate_root / MODULE.SOURCE_REL
    active_strategy_root.mkdir(parents=True)
    candidate_strategy_root.mkdir(parents=True)

    candidate_entries = []
    recovery = {}
    for strategy_id in MODULE.EXPECTED_25:
        active_path = active_strategy_root / f"{strategy_id}.py"
        if strategy_id not in MODULE.RECOVERED_TWO:
            active_path.write_text(strategy_source(strategy_id, "active"), encoding="utf-8")
        candidate_path = candidate_strategy_root / f"{strategy_id}.py"
        candidate_path.write_text(strategy_source(strategy_id, "candidate"), encoding="utf-8")
        candidate_entries.append(
            {
                "strategy_id": strategy_id,
                "entry_contract_version": "q4r3.strategy.signal.v1",
                "risk_writer_contract_version": "q4r3.forward_r.writer.v1",
                "source_decision_refs": [f"source:{strategy_id}"],
            }
        )
        if strategy_id in MODULE.RECOVERED_TWO:
            recovery[strategy_id] = {"candidate_sha256": MODULE.sha256_file(candidate_path)}

    manifest = {
        "strategy_count": 25,
        "dynamic_fallback_allowed": False,
        "strategies": candidate_entries,
    }
    MODULE.atomic_json(candidate_root / MODULE.MANIFEST_REL, manifest)
    result = {
        "status": "PASS_Q4R3_EXACT25_CANDIDATE_PACKAGE_BUILD",
        "verdict": "EXACT25_CANDIDATE_PACKAGE_READY_FOR_STAGED_ACTIVE_APPLY",
        "exact_25": True,
        "all_sources_present": True,
        "recovered_two_present": True,
        "contract_pass_count": 25,
        "contract_gap_count": 0,
        "recovery_decisions": recovery,
    }
    MODULE.atomic_json(candidate_root / MODULE.RESULT_REL, result)
    return active_root, candidate_root, runtime_root


def test_candidate_gate_rejects_contract_gap(tmp_path: Path) -> None:
    _active, candidate, _runtime = prepare_fixture(tmp_path)
    path = candidate / MODULE.RESULT_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["contract_gap_count"] = 1
    MODULE.atomic_json(path, payload)
    with pytest.raises(RuntimeError, match="CANDIDATE_GATE_FAILED"):
        MODULE.validate_candidate(candidate)


def test_apply_stages_two_files_and_disabled_exact25_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, candidate, runtime = prepare_fixture(tmp_path)
    publish = tmp_path / "published" / "result.json"
    monkeypatch.setenv("Q4R3_ALLOW_ACTIVE_APPLY", MODULE.APPLY_TOKEN)
    result = MODULE.apply_transaction(active, candidate, runtime, publish, "candidate-commit")

    assert result["status"] == "PASS_Q4R3_EXACT25_STAGED_ACTIVE_APPLY"
    assert result["runtime_registry_bound"] is False
    assert result["rollback_available"] is True
    for strategy_id in MODULE.RECOVERED_TWO:
        path = active / "backend" / "strategies" / f"{strategy_id}.py"
        assert "candidate" in path.read_text(encoding="utf-8")

    manifest = json.loads((active / MODULE.ACTIVE_MANIFEST_REL).read_text(encoding="utf-8"))
    assert manifest["strategy_count"] == 25
    assert manifest["dynamic_fallback_allowed"] is False
    assert manifest["runtime_binding_status"] == "NOT_BOUND_STAGED_ACTIVE"
    assert manifest["activation_allowed"] is False
    assert all(entry["enabled_for_shadow"] is False for entry in manifest["strategies"])
    assert all(entry["enabled_for_paper"] is False for entry in manifest["strategies"])
    assert all(entry["enabled_for_live"] is False for entry in manifest["strategies"])
    assert publish.is_file()


def test_failure_after_first_copy_rolls_back_to_absence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, candidate, runtime = prepare_fixture(tmp_path)
    publish = tmp_path / "published" / "result.json"
    monkeypatch.setenv("Q4R3_ALLOW_ACTIVE_APPLY", MODULE.APPLY_TOKEN)
    with pytest.raises(RuntimeError, match="INJECTED_FAILURE_AFTER_STEP:1"):
        MODULE.apply_transaction(active, candidate, runtime, publish, "candidate-commit", fail_after=1)

    for strategy_id in MODULE.RECOVERED_TWO:
        assert not (active / "backend" / "strategies" / f"{strategy_id}.py").exists()
    assert not (active / MODULE.ACTIVE_MANIFEST_REL).exists()


def test_failure_restores_preexisting_targets_byte_for_byte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, candidate, runtime = prepare_fixture(tmp_path)
    old_files = {}
    for strategy_id in MODULE.RECOVERED_TWO:
        path = active / "backend" / "strategies" / f"{strategy_id}.py"
        path.write_text(strategy_source(strategy_id, "old"), encoding="utf-8")
        old_files[strategy_id] = path.read_bytes()
    manifest_path = active / MODULE.ACTIVE_MANIFEST_REL
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"old": true}\n', encoding="utf-8")
    old_manifest = manifest_path.read_bytes()

    monkeypatch.setenv("Q4R3_ALLOW_ACTIVE_APPLY", MODULE.APPLY_TOKEN)
    with pytest.raises(RuntimeError, match="INJECTED_FAILURE_AFTER_STEP:2"):
        MODULE.apply_transaction(active, candidate, runtime, tmp_path / "publish.json", "candidate-commit", fail_after=2)

    for strategy_id, expected in old_files.items():
        assert (active / "backend" / "strategies" / f"{strategy_id}.py").read_bytes() == expected
    assert manifest_path.read_bytes() == old_manifest


def test_apply_requires_explicit_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, candidate, runtime = prepare_fixture(tmp_path)
    monkeypatch.delenv("Q4R3_ALLOW_ACTIVE_APPLY", raising=False)
    with pytest.raises(RuntimeError, match="ACTIVE_APPLY_TOKEN_MISSING"):
        MODULE.apply_transaction(active, candidate, runtime, tmp_path / "publish.json", "candidate-commit")


def test_manual_rollback_restores_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, candidate, runtime = prepare_fixture(tmp_path)
    old_path = active / "backend" / "strategies" / "ema_ribbon_scalp.py"
    old_path.write_text(strategy_source("ema_ribbon_scalp", "old"), encoding="utf-8")
    old_bytes = old_path.read_bytes()

    monkeypatch.setenv("Q4R3_ALLOW_ACTIVE_APPLY", MODULE.APPLY_TOKEN)
    result = MODULE.apply_transaction(active, candidate, runtime, tmp_path / "publish.json", "candidate-commit")
    assert old_path.read_bytes() != old_bytes

    monkeypatch.setenv("Q4R3_ALLOW_ROLLBACK", MODULE.ROLLBACK_TOKEN)
    rollback = MODULE.rollback_transaction(active, runtime, Path(result["backup_dir"]))
    assert rollback["status"] == "PASS_Q4R3_EXACT25_STAGED_ACTIVE_ROLLBACK"
    assert old_path.read_bytes() == old_bytes
    assert not (active / "backend" / "strategies" / "vol_spike_fade.py").exists()
    assert not (active / MODULE.ACTIVE_MANIFEST_REL).exists()
