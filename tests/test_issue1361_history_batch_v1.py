import copy
import json

import pytest

from ops import issue1361_history_batch_v1 as batch
from ops import issue1361_history_v1 as prep
from ops import issue1361_repeatability_v1 as scope
from tests.test_issue1361_history_v1 import manifest as fit_manifest


def claim(manifest):
    return {
        "schema": "zel.issue1361.history_claim.v1",
        "issue": 1361,
        "state": "RESERVED_NONRETRYABLE",
        "claim_ref": prep.HISTORY_CLAIM_REF,
        "claim_commit_sha": "a" * 40,
        "independent_approval_commit_sha": "b" * 40,
        "manifest_sha256": manifest["manifest_sha256"],
        "source_inventory_sha256": scope.SOURCE_INVENTORY_SHA256,
        "protocol_sha256": scope.PROTOCOL_SHA256,
        "rule_sha256": scope.RULE_SHA256,
        "cost_sha256": scope.COST_SHA256,
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
    batch.validate_claim(good, manifest)
    changed = copy.deepcopy(good)
    changed["instance_ids"].pop()
    with pytest.raises(batch.HistoryBatchError, match="CLAIM_BINDING"):
        batch.validate_claim(changed, manifest)
    forged = copy.deepcopy(manifest)
    forged["costs_bps"][scope.SYMBOLS[0]] += 1
    forged["manifest_sha256"] = prep.canonical_sha256(
        {k: v for k, v in forged.items() if k != "manifest_sha256"}
    )
    with pytest.raises(batch.HistoryBatchError, match="CLAIM_BINDING|FROZEN_COST"):
        batch.validate_claim(good, forged)


def test_one_invocation_runs_h1_h2_h3_saves_and_audits_before_next(tmp_path, monkeypatch):
    manifest = fit_manifest()
    approval = claim(manifest)
    manifest_path, claim_path = tmp_path / "FIT.json", tmp_path / "CLAIM.json"
    manifest_path.write_text(json.dumps(manifest))
    claim_path.write_text(json.dumps(approval))
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
        tmp_path, manifest_path, claim_path, out, market_loader=loader, instance_runner=runner
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
