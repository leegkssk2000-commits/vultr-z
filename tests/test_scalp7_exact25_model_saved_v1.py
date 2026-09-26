"""Saved-only verifier regressions; never import the runner or open market data."""

from __future__ import annotations

import builtins
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/verify_scalp7_exact25_model_closure_v1.py"
SPEC = importlib.util.spec_from_file_location("exact25_saved_verifier", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)
CAMPAIGN = verifier.CAMPAIGN
REPORT = CAMPAIGN / "MODEL_CLOSURE.json"
REQUEST = CAMPAIGN / "PREPARED_EXECUTION_REQUEST.json"
SEAL = CAMPAIGN / "INPUT_SEAL.json"


def read(repo: Path, name: str | Path) -> dict[str, Any]:
    return json.loads((repo / name).read_text())


def write(repo: Path, name: str | Path, value: Any) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def reseal(repo: Path) -> None:
    seal = read(repo, SEAL)
    seal["hashes"] = {
        name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
        for name in seal["hashes"]
    }
    write(repo, SEAL, seal)


def save_request(repo: Path, request: dict[str, Any]) -> None:
    report = read(repo, REPORT)
    report["prepared_execution_request"] = copy.deepcopy(request)
    write(repo, REQUEST, request)
    write(repo, REPORT, report)


def freeze_path(label: str = "ST_CONTROL") -> Path:
    return CAMPAIGN / "freezes" / (label + ".json")


@pytest.fixture
def saved_repo(tmp_path: Path) -> Path:
    """Copy metadata/code only; INPUT_SEAL need not exist in the source checkout."""
    request = read(SOURCE, REQUEST)
    required = {str(name) for name in verifier.REQUIRED_SEAL}
    for identity in request["identities"]:
        name = identity["freeze_path"]
        required.add(name)
        frozen = read(SOURCE, name)
        required.update(frozen["code_closure"])
        required.update(frozen["loader_code_closure"])
    for name in sorted(required):
        source = SOURCE / name
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    write(
        tmp_path, SEAL, {"scope_key": verifier.SCOPE, "hashes": dict.fromkeys(required)}
    )
    reseal(tmp_path)
    return tmp_path


def rebind(repo: Path, label: str) -> None:
    """Forge consistent hashes so tests exercise semantics beyond file integrity."""
    name = freeze_path(label)
    frozen = read(repo, name)
    candidate = frozen["candidate_identity"]
    excluded = {
        "binding_sha256",
        "candidate_identity",
        "identity_key",
        "data_manifest",
        "cost",
        "windows",
    }
    candidate["rule_sha256"] = digest(
        {key: value for key, value in frozen.items() if key not in excluded}
    )
    candidate["cost_sha256"] = digest(frozen["cost"])
    candidate["window_sha256"] = digest(frozen["windows"])
    old_identity = frozen["identity_key"]
    frozen["identity_key"] = digest(
        {key: value for key, value in candidate.items() if key != "candidate_id"}
    )
    frozen["binding_sha256"] = digest(
        {key: value for key, value in frozen.items() if key != "binding_sha256"}
    )
    write(repo, name, frozen)
    request = read(repo, REQUEST)
    for identity in request["identities"]:
        if identity["label"] == label:
            identity["identity"] = frozen["identity_key"]
            identity["binding_sha256"] = frozen["binding_sha256"]
    save_request(repo, request)
    report = read(repo, REPORT)
    for row in report["rows"]:
        for identity in row["final_frozen_identities"]:
            if identity["identity"] == old_identity:
                identity["identity"] = frozen["identity_key"]
    write(repo, REPORT, report)
    reseal(repo)


def test_saved_evidence_passes_without_backend_imports_or_external_reads(
    saved_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import, original_open = builtins.__import__, Path.open
    opened = []

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        assert name.split(".")[0] not in {"backend", "numpy", "pandas"}
        return original_import(name, *args, **kwargs)

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        assert path.resolve().is_relative_to(saved_repo.resolve())
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(Path, "open", guarded_open)
    result = verifier.verify(saved_repo)
    assert result["status"] == "PASS"
    assert result["exact25_rows"] == 25
    assert result["prepared_identities"] == 5
    assert result["minimum_full_runs_requested_not_authorized"] == 5
    assert result["new_full_runs"] == result["real_history_probes"] == 0
    assert result["market_data_loaded"] is False
    assert opened


def test_required_seal_member_cannot_be_omitted(saved_repo: Path) -> None:
    seal = read(saved_repo, SEAL)
    del seal["hashes"][str(REPORT)]
    write(saved_repo, SEAL, seal)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


def test_sealed_file_byte_change_is_rejected(saved_repo: Path) -> None:
    path = saved_repo / REQUEST
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


def test_resealed_request_must_equal_report_copy(saved_repo: Path) -> None:
    request = read(saved_repo, REQUEST)
    request["future_minimum_for_remaining_exact25"] = 25
    write(saved_repo, REQUEST, request)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


def test_resealed_empty_identity_request_is_rejected(saved_repo: Path) -> None:
    request = read(saved_repo, REQUEST)
    request["identities"] = []
    request["minimum_full_runs"] = 0
    save_request(saved_repo, request)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


@pytest.mark.parametrize(
    "field,value",
    [
        ("authorized", True),
        ("new_budget_allocated", 5),
        ("minimum_full_runs", 4),
        ("new_full_runs_per_identity", 2),
        ("cost_2x_additional_full_runs", 1),
    ],
)
def test_resealed_unexpected_allocation_or_run_count_is_rejected(
    saved_repo: Path,
    field: str,
    value: Any,
) -> None:
    request = read(saved_repo, REQUEST)
    request[field] = value
    save_request(saved_repo, request)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


@pytest.mark.parametrize(
    "field,value",
    [
        ("label", "SIXTH_MODEL"),
        ("model_id", "UNDECLARED_MODEL"),
        ("strategy_id", "trend_rider"),
        ("baseline_id", "WRONG_PARENT"),
        ("changed_axis", "TWO_AXES"),
    ],
)
def test_resealed_identity_profile_mutation_is_rejected(
    saved_repo: Path,
    field: str,
    value: str,
) -> None:
    request = read(saved_repo, REQUEST)
    request["identities"][0][field] = value
    save_request(saved_repo, request)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "matched_pairs",
            [
                {
                    "parent": "ST_CONTROL",
                    "child": "NOISE_BASELINE",
                    "axis": "SUPERTREND_TRAILING_ONLY",
                }
            ],
        ),
        ("independent_baselines", ["ST_TRAIL"]),
        ("noise_is_not_matched_parent_child_improvement", False),
    ],
)
def test_resealed_pair_or_independent_baseline_change_is_rejected(
    saved_repo: Path,
    field: str,
    value: Any,
) -> None:
    request = read(saved_repo, REQUEST)
    request[field] = value
    save_request(saved_repo, request)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


def test_resealed_binding_content_edit_is_rejected(saved_repo: Path) -> None:
    frozen = read(saved_repo, freeze_path())
    frozen["initial_cash_usdt"] += 1
    write(saved_repo, freeze_path(), frozen)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


def test_resealed_forged_candidate_hash_is_rejected(saved_repo: Path) -> None:
    frozen = read(saved_repo, freeze_path())
    frozen["candidate_identity"]["rule_sha256"] = "a" * 64
    frozen["identity_key"] = digest(
        {
            key: value
            for key, value in frozen["candidate_identity"].items()
            if key != "candidate_id"
        }
    )
    frozen["binding_sha256"] = digest(
        {key: value for key, value in frozen.items() if key != "binding_sha256"}
    )
    write(saved_repo, freeze_path(), frozen)
    request = read(saved_repo, REQUEST)
    request["identities"][0]["identity"] = frozen["identity_key"]
    request["identities"][0]["binding_sha256"] = frozen["binding_sha256"]
    save_request(saved_repo, request)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


@pytest.mark.parametrize("closure", ["code_closure", "loader_code_closure"])
def test_rebound_empty_code_or_loader_closure_is_rejected(
    saved_repo: Path,
    closure: str,
) -> None:
    frozen = read(saved_repo, freeze_path())
    frozen[closure] = {}
    write(saved_repo, freeze_path(), frozen)
    rebind(saved_repo, "ST_CONTROL")
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


@pytest.mark.parametrize(
    "closure,direct",
    [
        ("code_closure", "model_module"),
        ("loader_code_closure", "loader_module"),
        ("code_closure", "runner"),
        ("loader_code_closure", "runner"),
    ],
)
def test_rebound_missing_direct_closure_member_is_rejected(
    saved_repo: Path,
    closure: str,
    direct: str,
) -> None:
    frozen = read(saved_repo, freeze_path())
    module = {
        "model_module": frozen["model_module"],
        "loader_module": frozen["data_manifest"]["loader"]["module"],
        "runner": "backend.research.rebuild.scalp7_exact25_model_runner_v1",
    }[direct]
    del frozen[closure][module.replace(".", "/") + ".py"]
    write(saved_repo, freeze_path(), frozen)
    rebind(saved_repo, "ST_CONTROL")
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


def test_declared_closure_hash_must_match_seal(saved_repo: Path) -> None:
    frozen = read(saved_repo, freeze_path())
    dependency = next(iter(frozen["code_closure"]))
    path = saved_repo / dependency
    path.write_bytes(path.read_bytes() + b"\n# altered dependency\n")
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


@pytest.mark.parametrize("field", ["initial_cash_usdt", "cost", "windows", "config"])
def test_rebound_pair_cannot_change_shared_execution_inputs(
    saved_repo: Path,
    field: str,
) -> None:
    label = "ST_TRAIL"
    frozen = read(saved_repo, freeze_path(label))
    if field == "initial_cash_usdt":
        frozen[field] += 100
    elif field == "cost":
        frozen[field]["per_side_rates"]["BTC-USDT"] *= 2
    elif field == "config":
        frozen[field]["price_type"] = "mark"
    else:
        frozen[field][0]["start_ts_ms"] += 60000
    write(saved_repo, freeze_path(label), frozen)
    rebind(saved_repo, label)
    expected = (
        "MATCHED_PAIR_CONTRACT_MISMATCH"
        if field == "config"
        else "PREPARED_CONTRACT_MISMATCH"
    )
    with pytest.raises(ValueError, match=expected):
        verifier.verify(saved_repo)


def test_resealed_exact25_row_removal_is_rejected(saved_repo: Path) -> None:
    report = read(saved_repo, REPORT)
    report["rows"].pop()
    write(saved_repo, REPORT, report)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


@pytest.mark.parametrize(
    "field,value",
    [
        ("new_full_runs", 1),
        ("real_history_probes", 1),
        ("original_full_strategy_certifications", 1),
        ("new_A_promotions", 1),
        ("fusion_allowed", True),
        ("prepared_unique_identities", 0),
    ],
)
def test_resealed_unearned_execution_or_certification_is_rejected(
    saved_repo: Path,
    field: str,
    value: Any,
) -> None:
    report = read(saved_repo, REPORT)
    report[field] = value
    write(saved_repo, REPORT, report)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)


def test_resealed_per_id_economics_is_rejected(saved_repo: Path) -> None:
    report = read(saved_repo, REPORT)
    report["rows"][0]["new_economics"] = {"net": 1}
    write(saved_repo, REPORT, report)
    reseal(saved_repo)
    with pytest.raises(ValueError):
        verifier.verify(saved_repo)
