import copy
import base64
import hashlib
import json

import pytest

from ops import issue1361_history_batch_v1 as batch
from ops import issue1361_history_v1 as prep
from ops import issue1361_repeatability_v1 as scope
from tests.test_issue1361_history_v1 import manifest as fit_manifest


def approval(manifest):
    return {
        "schema": "zel.issue1361.history_approval.v1",
        "issue": 1361,
        "state": "APPROVED_RETROSPECTIVE_H_ONLY",
        "approval_ref": batch.APPROVAL_REF,
        "approval_commit_sha": "b" * 40,
        "classification": scope.CLASSIFICATION,
        "reviewed_source_sha": "c" * 40,
        "fit_artifact_id": 11419311671,
        "fit_artifact_digest": "sha256:" + "d" * 64,
        "fit_receipt_sha256": "e" * 64,
        "manifest_sha256": manifest["manifest_sha256"],
        "source_inventory_sha256": scope.SOURCE_INVENTORY_SHA256,
        "protocol_sha256": scope.PROTOCOL_SHA256,
        "rule_sha256": scope.RULE_SHA256,
        "cost_sha256": scope.COST_SHA256,
        "runtime_sha256": manifest["runtime_sha256"],
        "trusted_fit_sha256": {row["id"]: row["fit"]["sha256"] for row in manifest["fits"]},
        "trusted_coverage_sha256": manifest["coverage_sha256"],
        "instance_ids": sorted(row["instance_id"] for row in manifest["instances"]),
        "max_instances": 6,
        "order_authority": "BLOCKED",
    }


def claim(manifest):
    approved = approval(manifest)
    return {
        "schema": "zel.issue1361.history_claim.v1",
        "issue": 1361,
        "state": "RESERVED_NONRETRYABLE",
        "claim_ref": prep.HISTORY_CLAIM_REF,
        "claim_commit_sha": "a" * 40,
        "independent_approval_commit_sha": approved["approval_commit_sha"],
        "reviewed_source_sha": approved["reviewed_source_sha"],
        "fit_artifact_id": approved["fit_artifact_id"],
        "fit_artifact_digest": approved["fit_artifact_digest"],
        "fit_receipt_sha256": approved["fit_receipt_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "source_inventory_sha256": scope.SOURCE_INVENTORY_SHA256,
        "protocol_sha256": scope.PROTOCOL_SHA256,
        "rule_sha256": scope.RULE_SHA256,
        "cost_sha256": scope.COST_SHA256,
        "runtime_sha256": manifest["runtime_sha256"],
        "trusted_fit_sha256": {row["id"]: row["fit"]["sha256"] for row in manifest["fits"]},
        "trusted_coverage_sha256": manifest["coverage_sha256"],
        "instance_ids": sorted(row["instance_id"] for row in manifest["instances"]),
        "max_instances": 6,
        "economic_instances": 6,
        "global_heavy_group": "a1-global-heavy-economic-evaluator-v1",
        "global_heavy_exclusive": True,
        "order_authority": "BLOCKED",
    }


def fake_result(identity, fold):
    from backend.research.rebuild import scalp7_metrics_v2 as metrics

    result = {
        "schema": batch.RESULT_SCHEMA,
        "fold_id": fold["id"],
        "identity": identity,
        "model": batch.IDENTITY_MODEL[identity],
        "classification": scope.CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "cost_1x": metrics.summarize([], fold["test_start_ms"], fold["test_end_ms"], 1),
        "cost_2x": metrics.summarize([], fold["test_start_ms"], fold["test_end_ms"], 2),
        "census": {"signals": 0, "completed": 0, "unresolved": 0},
        "trades": [],
        "unresolved": [],
        "order_authority": "BLOCKED",
        "fresh_oos": False,
    }
    result["result_sha256"] = batch.sha256(result)
    return result


def test_claim_rejects_rehashed_manifest_or_unapproved_instance(monkeypatch):
    manifest = fit_manifest()
    monkeypatch.setattr(prep, "validate_runtime", lambda: prep.RUNTIME_PROFILE)
    good = claim(manifest)
    approved = approval(manifest)
    batch.validate_claim(good, manifest, approved)
    changed = copy.deepcopy(good)
    changed["instance_ids"].pop()
    with pytest.raises(batch.HistoryBatchError, match="CLAIM_BINDING"):
        batch.validate_claim(changed, manifest, approved)
    forged = copy.deepcopy(manifest)
    forged["costs_bps"][scope.SYMBOLS[0]] += 1
    forged["manifest_sha256"] = prep.canonical_sha256(
        {k: v for k, v in forged.items() if k != "manifest_sha256"}
    )
    with pytest.raises(batch.HistoryBatchError, match="APPROVAL_BINDING|CLAIM_BINDING|FROZEN_COST"):
        batch.validate_claim(good, forged, approved)


def test_claim_rejects_unpublished_or_rebound_approval(monkeypatch):
    manifest = fit_manifest()
    monkeypatch.setattr(prep, "validate_runtime", lambda: prep.RUNTIME_PROFILE)
    approved = approval(manifest)
    good = claim(manifest)
    rebound = copy.deepcopy(approved)
    rebound["fit_artifact_id"] += 1
    with pytest.raises(batch.HistoryBatchError, match="APPROVAL_BINDING|CLAIM_BINDING"):
        batch.validate_claim(good, manifest, rebound)
    forged = copy.deepcopy(good)
    forged["independent_approval_commit_sha"] = "f" * 40
    with pytest.raises(batch.HistoryBatchError, match="CLAIM_OR_APPROVAL"):
        batch.validate_claim(forged, manifest, approved)


def test_one_invocation_runs_h1_h2_h3_saves_and_audits_before_next(tmp_path, monkeypatch):
    manifest = fit_manifest()
    approved_claim = claim(manifest)
    approved = approval(manifest)
    manifest_path = tmp_path / "FIT.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(prep, "validate_runtime", lambda: prep.RUNTIME_PROFILE)
    calls = []

    def loader(source_root, supplied):
        calls.append(("INPUT_AND_FIT_FROZEN", supplied["manifest_sha256"]))
        return {"fixture": True}

    def runner(*, identity, fold, market, costs):
        assert market == {"fixture": True}
        assert costs == prep.FROZEN_COSTS_BPS
        calls.append((fold["id"], identity))
        return fake_result(identity, fold)

    out = tmp_path / "out"
    result = batch.execute_batch(
        tmp_path,
        manifest_path,
        out,
        claim_loader=lambda: approved_claim,
        approval_loader=lambda: approved,
        market_loader=loader,
        instance_runner=runner,
    )
    assert [row[0] for row in calls[1:]] == ["H1", "H1", "H2", "H2", "H3", "H3"]
    assert result["economic_instances"] == 6
    assert result["state"] == "COMPLETE_SIX_RETROSPECTIVE_INSTANCES"
    for fold in ("H1", "H2", "H3"):
        for model in batch.IDENTITY_MODEL.values():
            assert json.loads((out / fold / model / "AUDIT.json").read_text())["state"] == "PASS_SAVED_RESULT_AND_ACCOUNTING"


def test_saved_result_tamper_is_rejected(tmp_path):
    fold = scope.planned_history()[0]
    value = fake_result(prep.PARENT, fold)
    path = tmp_path / "RESULT.json"
    path.write_text(json.dumps(value))
    assert batch.audit_saved_result(path)["state"] == "PASS_SAVED_RESULT_AND_ACCOUNTING"
    value["cost_1x"]["T"] = 99
    path.write_text(json.dumps(value))
    with pytest.raises(batch.HistoryBatchError, match="SAVED_RESULT_HASH"):
        batch.audit_saved_result(path)


def test_claim_is_read_from_fixed_ref_and_git_blob_not_caller_file():
    content = {"schema": "zel.issue1361.history_claim.v1", "state": "RESERVED_NONRETRYABLE"}
    raw = json.dumps(content).encode()
    blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    commit_sha = "c" * 40
    routes = {
        "/git/ref/" + prep.HISTORY_CLAIM_REF.removeprefix("refs/"): {
            "ref": prep.HISTORY_CLAIM_REF,
            "object": {"type": "commit", "sha": commit_sha},
        },
        "/git/commits/" + commit_sha: {"tree": {"sha": "d" * 40}, "parents": []},
        "/git/trees/" + "d" * 40: {
            "tree": [{"path": "CLAIM.json", "type": "blob", "sha": blob_sha}]
        },
        "/git/blobs/" + blob_sha: {
            "encoding": "base64",
            "content": base64.b64encode(raw).decode(),
        },
    }

    def api(method, route):
        assert method == "GET"
        return routes[route]

    assert batch.verified_claim(api) == {**content, "claim_commit_sha": commit_sha}
    routes["/git/blobs/" + blob_sha]["content"] = base64.b64encode(raw + b" ").decode()
    with pytest.raises(batch.HistoryBatchError, match="CLAIM_BLOB_HASH"):
        batch.verified_claim(api)
