"""Saved-seal tampering checks; no market data or economic replay."""

import hashlib
from pathlib import Path

import pytest

from scripts.verify_scalp7_exact25_implementation_v1 import verify_file_seal


def test_saved_seal_checks_exact_bytes(tmp_path):
    file = tmp_path / "fixture.txt"
    file.write_text("saved fixture")
    seal = {"fixture.txt": hashlib.sha256(file.read_bytes()).hexdigest()}
    verify_file_seal(tmp_path, seal, {"fixture.txt"})
    file.write_text("tampered fixture")
    with pytest.raises(ValueError, match="HASH_DRIFT"):
        verify_file_seal(tmp_path, seal, {"fixture.txt"})


def test_omitted_required_dependency_fails(tmp_path):
    with pytest.raises(ValueError, match="MISSING_REQUIRED_MEMBER"):
        verify_file_seal(tmp_path, {}, {"actual_producer.py"})


@pytest.mark.parametrize("name", ["../outside", "/absolute/path"])
def test_no_external_paths(tmp_path, name):
    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        verify_file_seal(tmp_path, {name: "x"}, set())


def test_missing_file_rejected(tmp_path):
    with pytest.raises(ValueError, match="MISSING_OR_EXTERNAL"):
        verify_file_seal(tmp_path, {"missing": "x"}, set())


def test_external_symlink_rejected(tmp_path):
    link = tmp_path / "outside"
    link.symlink_to(Path(__file__).resolve())
    with pytest.raises(ValueError, match="MISSING_OR_EXTERNAL"):
        verify_file_seal(tmp_path, {"outside": "x"}, set())


def test_import_closure_is_hash_first_without_import(tmp_path):
    from scripts.verify_scalp7_exact25_implementation_v1 import local_dependencies

    folder = tmp_path / "backend/research/rebuild"
    folder.mkdir(parents=True)
    producer = folder / "producer.py"
    producer.write_text("from backend.research.rebuild import dependency\n")
    dependency = folder / "dependency.py"
    dependency.write_text("raise RuntimeError('MUST_NOT_IMPORT')\n")
    closure = local_dependencies(tmp_path, {str(producer.relative_to(tmp_path))})
    assert str(dependency.relative_to(tmp_path)) in closure


@pytest.fixture
def saved_claims():
    import json
    from scripts.verify_scalp7_exact25_implementation_v1 import CAMPAIGN

    root = Path(__file__).resolve().parents[1]
    return json.loads((root / CAMPAIGN / "EXACT25_IMPLEMENTATION.json").read_text())


def test_saved_coverage_zero_economics_claims(saved_claims):
    from scripts.verify_scalp7_exact25_implementation_v1 import verify_coverage_claims

    verify_coverage_claims(saved_claims)


def test_coverage_duplicate_row_rejected(saved_claims):
    from scripts.verify_scalp7_exact25_implementation_v1 import verify_coverage_claims

    saved_claims["rows"].append(dict(saved_claims["rows"][0]))
    with pytest.raises(ValueError, match="EXACT25_MEMBERSHIP"):
        verify_coverage_claims(saved_claims)


@pytest.mark.parametrize("target", ["new_full_runs", "ready_new_baselines"])
def test_coverage_alias_drift_rejected(saved_claims, target):
    from scripts.verify_scalp7_exact25_implementation_v1 import verify_coverage_claims

    nested = "coverage" if target == "new_full_runs" else "execution_readiness"
    saved_claims[nested][target] = 1
    with pytest.raises(ValueError, match="STATUS_DRIFT"):
        verify_coverage_claims(saved_claims)


@pytest.mark.parametrize("value", [False, 0.0])
def test_economic_count_boolean_or_float_is_not_integer_count(saved_claims, value):
    from scripts.verify_scalp7_exact25_implementation_v1 import verify_coverage_claims

    saved_claims["new_full_runs"] = value
    with pytest.raises(ValueError, match="COVERAGE_STATUS_DRIFT"):
        verify_coverage_claims(saved_claims)


@pytest.mark.parametrize(
    "field", ["economics_ready", "full_original_strategy_complete"]
)
def test_row_completeness_promotion_rejected(saved_claims, field):
    from scripts.verify_scalp7_exact25_implementation_v1 import verify_coverage_claims

    saved_claims["rows"][0][field] = True
    with pytest.raises(ValueError, match="ROW_UNSUPPORTED_COMPLETENESS"):
        verify_coverage_claims(saved_claims)


def test_fabricated_metric_without_run_rejected(saved_claims):
    from scripts.verify_scalp7_exact25_implementation_v1 import verify_coverage_claims

    saved_claims["rows"][0]["new_economics"]["Net"] = 10.0
    with pytest.raises(ValueError, match="ROW_FABRICATED_ECONOMIC_VALUES"):
        verify_coverage_claims(saved_claims)
