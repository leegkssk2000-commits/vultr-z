"""Saved-only publication attacks: no strategy or historical price execution."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/verify_scalp7_measurement_exact25_closure_v1.py"
)
SPEC = importlib.util.spec_from_file_location("measurement_saved_guard", SCRIPT)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


@pytest.fixture
def published(tmp_path):
    guard.git(tmp_path, "init", "--quiet")
    artifact = tmp_path / "evidence.json"
    artifact.write_text('{"saved": 1}\n')
    seal = tmp_path / "INPUT_SEAL.json"
    seal.write_text(
        json.dumps({"covered_files": {"evidence.json": guard.sha_file(artifact)}})
    )
    guard.git(tmp_path, "add", ".")
    guard.git(
        tmp_path,
        "-c",
        "user.name=Guard Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "published",
    )
    commit = guard.git(tmp_path, "rev-parse", "HEAD").decode().strip()
    trusted = guard.git(tmp_path, "show", commit + ":INPUT_SEAL.json")
    return tmp_path, artifact, seal, trusted


def test_saved_baseline_and_coordinated_reseal_attack(published):
    repo, artifact, seal, trusted = published
    assert (
        guard.check_published(repo, trusted, Path("INPUT_SEAL.json"), "covered_files")
        == 1
    )
    artifact.write_text('{"saved": 999}\n')
    seal.write_text(
        json.dumps({"covered_files": {"evidence.json": guard.sha_file(artifact)}})
    )
    with pytest.raises(ValueError, match="PUBLISHED_SEAL_REPLACED"):
        guard.check_published(repo, trusted, Path("INPUT_SEAL.json"), "covered_files")


def test_result_only_tampering(published):
    repo, artifact, _, trusted = published
    artifact.write_bytes(b"forged")
    with pytest.raises(ValueError, match="HASH_CHANGED"):
        guard.check_published(repo, trusted, Path("INPUT_SEAL.json"), "covered_files")


@pytest.mark.parametrize("value", ["HEAD", "master", "0" * 40, "bad; command"])
def test_mutable_or_invalid_git_reference_rejected(published, value):
    with pytest.raises(ValueError, match="EXPLICIT_NONZERO_COMMIT_REQUIRED"):
        guard.explicit_commit(published[0], value)


@pytest.mark.parametrize(
    "name", ["../evidence.json", "/etc/passwd", "sub/../evidence.json"]
)
def test_seal_path_escape_rejected(published, name):
    with pytest.raises(ValueError, match="UNSAFE_OR_MISSING_FILE"):
        guard.local_file(published[0], name)


def test_symlink_rejected(published):
    repo, artifact, _, _ = published
    (repo / "link").symlink_to(artifact)
    with pytest.raises(ValueError, match="UNSAFE_OR_MISSING_FILE"):
        guard.local_file(repo, "link")


@pytest.fixture
def summary():
    return {
        "scope_key": guard.SCOPE,
        "new_full_runs": 0,
        "genuine_history_strategy_probes": 0,
        "original25_complete": False,
        "g4_complete": False,
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("new_full_runs", 1),
        ("genuine_history_strategy_probes", 1),
        ("new_full_runs", False),
        ("original25_complete", True),
        ("g4_complete", True),
    ],
)
def test_no_full_scope_and_completion_claim(summary, key, value):
    guard.check_summary(summary)
    summary[key] = value
    with pytest.raises(ValueError):
        guard.check_summary(summary)


def test_live_authority_blocked(summary):
    summary["authority"]["live"] = "AUTHORIZED"
    with pytest.raises(ValueError, match="UNAUTHORIZED_AUTHORITY"):
        guard.check_summary(summary)


@pytest.fixture
def batch(summary):
    rows = [
        {
            "label": label + "_CONTINUOUS_SEGMENTS_V1",
            "identity_key": label + "_changed_data",
            "changed_axis": "DATA_CONTINUITY_AND_INDEPENDENT_CAPITAL_ONLY",
            "data_sha256": "a" * 64,
            "cost_sha256": "b" * 64,
            "period_sha256": "c" * 64,
            "required_new_full_runs": 1,
            "prior_control_reusable": False,
        }
        for label in ("SR_CONTROL", "SR_RETEST")
    ]
    return {
        "scope_key": guard.SCOPE,
        "new_full_authorized": 0,
        "minimum_new_full_runs": 2,
        "prepared_identities": rows,
        "authority": summary["authority"],
        "evaluation_mode": "INDEPENDENT_CONTINUOUS_SEGMENTS_NOT_WHOLE_ACCOUNT",
    }


def test_next_batch_is_prepared_without_granting_execution(batch):
    guard.check_next_batch(batch)
    batch["new_full_authorized"] = 2
    with pytest.raises(ValueError, match="NEXT_BATCH_NOT_AUTHORIZED"):
        guard.check_next_batch(batch)


def test_changed_data_cannot_reuse_old_control(batch):
    batch["prepared_identities"][0]["prior_control_reusable"] = True
    with pytest.raises(ValueError, match="OLD_CONTROL_REUSED"):
        guard.check_next_batch(batch)


def test_duplicate_or_inaccurate_minimum(batch):
    batch["minimum_new_full_runs"] = 1
    with pytest.raises(ValueError, match="MINIMUM_FULL_COUNT"):
        guard.check_next_batch(batch)
    batch["minimum_new_full_runs"] = 2
    batch["prepared_identities"][1]["identity_key"] = batch["prepared_identities"][0][
        "identity_key"
    ]
    with pytest.raises(ValueError, match="DUPLICATE_IDENTITY"):
        guard.check_next_batch(batch)


def test_independent_segments_cannot_claim_whole_account(batch):
    batch["evaluation_mode"] = "WHOLE_ACCOUNT"
    with pytest.raises(ValueError, match="FALSE_WHOLE_ACCOUNT"):
        guard.check_next_batch(batch)


def test_existing_backend_change_rejected(published, monkeypatch):
    repo, _, _, _ = published
    backend = repo / "backend/existing.py"
    backend.parent.mkdir()
    backend.write_text("original = True\n")
    guard.git(repo, "add", ".")
    guard.git(
        repo,
        "-c",
        "user.name=Guard Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "existing backend",
    )
    monkeypatch.setattr(
        guard, "PREDECESSOR", guard.git(repo, "rev-parse", "HEAD").decode().strip()
    )
    assert guard.preserve_backend(repo) == []
    backend.write_text("changed = True\n")
    with pytest.raises(ValueError, match="UNEXPECTED_BACKEND_CHANGE"):
        guard.preserve_backend(repo)


def test_ignored_backend_addition_cannot_escape_review(published, monkeypatch):
    repo, _, _, _ = published
    monkeypatch.setattr(
        guard, "PREDECESSOR", guard.git(repo, "rev-parse", "HEAD").decode().strip()
    )
    (repo / ".gitignore").write_text("backend/\n")
    unexpected = repo / "backend/hidden.py"
    unexpected.parent.mkdir()
    unexpected.write_text("unreviewed = True\n")
    with pytest.raises(ValueError, match="UNEXPECTED_BACKEND_CHANGE"):
        guard.preserve_backend(repo)


@pytest.mark.parametrize(
    "tamper", ["remove_interval", "relabel_parent", "profit_selection", "omit_symbol"]
)
def test_rehashed_continuous_contract_still_rejects_semantic_tampering(tamper):
    from backend.research.rebuild.scalp7_measurement_repair_v1 import (
        continuous_contract,
    )

    day = 86_400_000
    coverage = [
        {
            "symbol": symbol,
            "continuous_spans": [
                {"start_ts_ms": 0, "end_ts_ms": 100 * day},
                {"start_ts_ms": 101 * day, "end_ts_ms": 210 * day},
            ],
        }
        for symbol in sorted(guard.SYMBOLS)
    ]
    obj = continuous_contract(coverage, [{"path": "synthetic", "sha256": "a" * 64}])
    guard.check_continuous_contract(obj)
    if tamper == "remove_interval":
        obj["segments"].pop()
    elif tamper == "relabel_parent":
        obj["segments"][0]["initial_state"] = "OLD_POSITION_CLOSED"
    elif tamper == "omit_symbol":
        obj["coverage"].pop()
    else:
        obj["strategy_or_profit_used_for_selection"] = True
    obj.pop("contract_sha256")
    obj["contract_sha256"] = guard.hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ValueError):
        guard.check_continuous_contract(obj)


def test_unrelated_candidate_and_rule_retune_rejected(batch):
    batch["prepared_identities"][0]["label"] = "UNRELATED"
    with pytest.raises(ValueError, match="EXACT_TWO_SR_IDENTITIES_REQUIRED"):
        guard.check_next_batch(batch)
    batch["prepared_identities"][0]["label"] = "SR_CONTROL_CONTINUOUS_SEGMENTS_V1"
    batch["prepared_identities"][0]["changed_axis"] = "RULE_RETUNE"
    with pytest.raises(ValueError, match="UNAPPROVED_CHANGED_AXIS"):
        guard.check_next_batch(batch)


def test_rehashed_child_strategy_retune_rejected(monkeypatch):
    repo = SCRIPT.parents[1]
    batch = guard.read_json(repo, "NEXT_ECONOMIC_BATCH.json")
    frozen = guard.read_json(repo, "next_freezes/SR_CONTROL.json")
    child = next(iter(frozen["segment_bindings"].values()))
    child["config"]["undeclared_parameter"] = 999
    child["binding_sha256"] = guard.canonical_digest(
        {k: v for k, v in child.items() if k != "binding_sha256"}
    )
    frozen["binding_sha256"] = guard.canonical_digest(
        {k: v for k, v in frozen.items() if k != "binding_sha256"}
    )
    original = guard.read_json
    monkeypatch.setattr(
        guard,
        "read_json",
        lambda root, name: (
            frozen if name == "next_freezes/SR_CONTROL.json" else original(root, name)
        ),
    )
    with pytest.raises(ValueError, match="UNAPPROVED_MODEL_OR_COST_CHANGE"):
        guard.check_next_freezes(repo, batch)


def test_reviewed_artifact_tampering_rejected(tmp_path):
    folder = tmp_path / guard.CAMPAIGN
    folder.mkdir(parents=True)
    paths = [
        folder / name
        for name in (
            "FINAL_REPORT.md",
            "COVERAGE.json",
            "COVERAGE.md",
            "NEXT_ECONOMIC_BATCH.json",
            "VALIDATION.json",
            "WORK_NEXT.txt",
        )
    ]
    for path in paths:
        path.write_text("reviewed bytes\n")
    review = {
        "artifact_sha256": {
            str(path.relative_to(tmp_path)): guard.sha_file(path) for path in paths
        }
    }
    guard.check_review_artifacts(tmp_path, review)
    (folder / "COVERAGE.json").write_text("changed after review\n")
    with pytest.raises(ValueError, match="HASH_CHANGED"):
        guard.check_review_artifacts(tmp_path, review)
