from __future__ import annotations

import hashlib
import base64
import json
from pathlib import Path

import pytest

from ops import issue1361_repeatability_v1 as repeat


def test_source_inventory_one_shot_recovery_is_master_bound_and_non_economic() -> None:
    workflow = Path(
        ".github/workflows/issue1361-repeatability-v1.yml"
    ).read_text()
    token = "[issue1361-source-inventory-once-20261006T0202Z-a90ab50]"
    assert "github.ref == 'refs/heads/master'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "github.event_name == 'push'" in workflow
    assert token in workflow
    assert "ref: 4a114e56b3f5ec50efe3de606684da20b91d5a9a" in workflow
    assert "persist-credentials: false" in workflow
    assert "4dadc6748122038fe2f46c375030ca8622e48555451d06bd6e3fd89b066f532e" in workflow

    receipt = json.loads(Path(
        "research/campaigns/scalp7_20261006/"
        "issue1361_repeatability_v1/SOURCE_INVENTORY_DISPATCH_RECOVERY.json"
    ).read_text())
    assert receipt["one_shot_merge_token"] == token
    assert receipt["reviewed_inventory_source_head"] == (
        "4a114e56b3f5ec50efe3de606684da20b91d5a9a"
    )
    assert receipt["reviewed_inventory_executable_sha256"] == (
        "4dadc6748122038fe2f46c375030ca8622e48555451d06bd6e3fd89b066f532e"
    )
    assert receipt["economic_jobs_opened"] == 0
    assert receipt["economic_claims_created"] == 0
    assert receipt["services_or_collectors_changed"] == 0
    assert receipt["schedules_changed"] == 0


def test_fit_artifact_job_is_single_file_descendant_and_non_economic() -> None:
    workflow = Path(".github/workflows/issue1361-repeatability-v1.yml").read_text()
    token = "[issue1361-fit-artifact-once-20261006T1230Z-3f2d71a]"
    repair_token = "[issue1361-fit-artifact-repair1-once-20261006T1310Z-6d9a1c4]"
    repair2_token = "[issue1361-fit-artifact-repair2-once-20261006T1330Z-c82ef51]"
    churn_token = "[issue1361-fit-artifact-merge-churn-once-20261006T1345Z-3aa4d8e]"
    assert token in workflow
    assert repair_token in workflow
    assert repair2_token in workflow
    assert churn_token in workflow
    block = workflow.split("  source-fit-artifact:", 1)[1].split("  history-economic-batch:", 1)[0]
    assert "['git', 'diff', '--name-status', '--no-renames', parent, head]" in block
    assert "['git', 'rev-list', parent, '--', str(activation_path)]" in block
    assert "['git', 'diff-tree'" not in block
    assert "changed != ['A\\t' + str(activation_path)]" in block
    assert "FIT_ACTIVATION_NOT_NEW_SINGLE_FILE" in block
    assert "FIT_ACTIVATION_PATH_ALREADY_IN_HISTORY" in block
    assert "fetch-depth: 0" in block
    assert "git checkout --detach '${{ steps.activation.outputs.source_head }}'" in block
    assert "persist-credentials: false" in block
    assert "python -m ops.issue1361_history_v1 prepare" in block
    assert "python ops/issue1361_history_v1.py prepare" not in block
    assert "FIT_ARTIFACT_ACTIVATION_REPAIR1.json" in block
    assert "FIT_ARTIFACT_ACTIVATION_REPAIR2.json" in block
    assert "FIT_ARTIFACT_ACTIVATION_MERGE_CHURN.json" in block
    assert "FIT_ACTIVATION_TOKEN_AMBIGUOUS_OR_MISSING" in block
    assert "['git', 'merge-base', '--is-ancestor', source_head, parent]" in block
    assert "FIT_ACTIVATION_SOURCE_HEAD_INVALID" in block
    assert "FIT_ACTIVATION_SOURCE_NOT_PARENT_ANCESTOR" in block
    assert "handle.write(f'source_head={source_head}\\n')" in block
    assert "'source_head': parent" not in block
    assert "'source_head': approved_source" in block
    assert "7d0f8d5efb6e539ad093e53e019c6d05715f2738" in block
    assert "9b6cfb0aa644978fb08e34c37d1d9c23d81b010d" in block
    assert "4165d7b6c1d66696b4cdd627495262876ff6d378" in block
    assert "13d5a9c1753db9cc899f8d419031d5ddb220fb05" in block
    assert "test_period_signal_generation': 0" in block
    assert "test_period_model_replays': 0" in block
    assert "'H_claimed': 0" in block
    assert "'economic_runs': 0" in block
    assert "scalp7_positive_lanes_v2" not in block
    assert "issue1361_history_batch_v1.py" not in block
    assert "workflow_dispatch" not in block.split("jobs:", 1)[0]


def test_fit_artifact_transfer_is_read_only_and_not_published() -> None:
    workflow = Path(".github/workflows/issue1361-repeatability-v1.yml").read_text()
    block = workflow.split("  source-fit-artifact:", 1)[1].split("  history-economic-batch:", 1)[0]
    assert "tar -C /home/z/z/runtime/economic7_campaign_20260915 -czf -" in block
    assert "UNSAFE_SOURCE_ARCHIVE_MEMBER" in block
    assert "SOURCE_ARCHIVE_BOUND_EXCEEDED" in block
    assert "rm -f ~/.ssh/vps_key \"$RUNNER_TEMP/issue1361-source.tar.gz\"" in block
    upload = block.split("- uses: actions/upload-artifact@v4", 1)[1]
    assert "FIT_MANIFEST.json" in upload
    assert "SOURCE_FIT_RECEIPT.json" in upload
    assert "issue1361-source.tar.gz" not in upload
    assert "issue1361-source/" not in upload
    assert "'source_transport': 'EXISTING_SSH_READ_ONLY'" in block
    assert "'market_data_requests': 0" in block
    assert "archive.read_bytes()" not in block
    assert "handle.read(1024 * 1024)" in block
    assert "test ! -e \"$stage\"" in block
    assert "issue1361-ephemeral-source-stage" in block
    assert "--source-root /home/z/z/runtime/economic7_campaign_20260915" in block
    assert "sudo rm -rf -- \"$stage\"" in block
    assert "systemctl" not in block


def test_history_batch_is_one_shot_claimed_and_global_heavy() -> None:
    workflow = Path(".github/workflows/issue1361-repeatability-v1.yml").read_text()
    block = workflow.split("  history-economic-batch:", 1)[1]
    assert "[issue1361-history-batch-once-20261006T1420Z-f18d2c7]" in block
    assert "github.run_attempt == 1" in block.split("needs: contract-tests", 1)[0]
    assert "'M\\t.github/workflows/issue1361-repeatability-v1.yml'" in block
    assert "'A\\t' + str(path)" in block
    assert "'M\\ttests/test_scalp7_issue1361_repeatability_v1.py'" in block
    assert "HISTORY_ACTIVATION_CHANGED_PATH_PROFILE" in block
    assert "git checkout --detach '${{ steps.activation.outputs.reviewed_source_sha }}'" in block
    assert "group: a1-global-heavy-economic-evaluator-v1" in block
    assert "cancel-in-progress: false" in block
    assert "actions: read" in workflow
    assert "source != approval.get('reviewed_source_sha')" in block
    assert "value.get('approval_commit_sha') != approval.get('approval_commit_sha')" in block
    assert "HISTORY_APPROVAL_COMMIT_NOT_PINNED" in block
    assert "value.get('claim_commit_sha') != claim.get('claim_commit_sha')" in block
    assert "HISTORY_CLAIM_COMMIT_NOT_PINNED" in block
    assert "HISTORY_APPROVAL.json" in block
    assert "HISTORY_CLAIM.json" in block
    assert "claim_loader=lambda: claim" in block
    assert "approval_loader=lambda: approval" in block
    assert "HISTORY_ARTIFACT_NOT_APPROVED" in block
    assert "issue1361_history_batch_v1" in block
    assert "fit_artifact_id': 11419311671" in block
    assert "a39e65afc4c7557a4864a4a0192b6278cdba51a051969b684f20c97da4f73d1f" in block
    assert "research-approvals/issue1361-history-20261006-v1" in block
    assert "research-execution-claims/issue1361-history-20261006-v1" in block
    upload = block.rsplit("- uses: actions/upload-artifact@v4", 1)[1]
    assert "if: always()" in upload.split("with:", 1)[0]
    assert "${{ runner.temp }}/H_RESULTS" in upload
    assert "systemctl" not in block


def test_history_is_exact_three_past_only_90d_fit_30d_test() -> None:
    rows = repeat.planned_history()
    repeat.check_history(rows)
    assert [row["id"] for row in rows] == ["H1", "H2", "H3"]
    assert all(row["fit_end_ms"] == row["test_start_ms"] for row in rows)


@pytest.mark.parametrize("field", ["fit_start_ms", "fit_end_ms", "test_end_ms"])
def test_history_rejects_date_drift(field: str) -> None:
    rows = repeat.planned_history()
    rows[0][field] += repeat.DAY_MS
    with pytest.raises(repeat.AdmissionError, match="FROZEN_FIELD_MISMATCH"):
        repeat.check_history(rows)


def test_history_rejects_fresh_label_and_invented_receipt_clock() -> None:
    rows = repeat.planned_history()
    rows[0]["classification"] = "FRESH_OOS"
    with pytest.raises(repeat.AdmissionError, match="NOT_BE_LABELLED_FRESH"):
        repeat.check_history(rows)
    rows = repeat.planned_history()
    rows[0]["clock_profile"] = "RECORDED_RECEIPT"
    with pytest.raises(repeat.AdmissionError, match="SEMANTICS_INVENTED"):
        repeat.check_history(rows)


def test_history_rejects_future_fit_source() -> None:
    rows = repeat.planned_history()
    rows[1]["fit_source_end_ms"] = rows[1]["test_start_ms"] + 1
    with pytest.raises(repeat.AdmissionError, match="FUTURE_FIT_INPUT"):
        repeat.check_history(rows)


def freeze_receipt() -> dict:
    return {
        "schema": "scalp7.issue1361.forward_freeze.v1",
        "issue": 1361,
        "protocol_sha256": repeat.PROTOCOL_SHA256,
        "rule_sha256": repeat.RULE_SHA256,
        "source_binding_sha256": "1" * 64,
        "source_verified": True,
        "receipt_cursor_persistent": True,
        "frozen_at_ms": repeat._ms("2026-10-06T03:00:00Z"),
    }


def forward_contract(receipt: dict) -> dict:
    start = repeat._ms("2026-10-06T03:30:00Z")
    return {
        "fit_end_ms": repeat._ms("2026-09-15T00:00:00Z"),
        "duration_days": 90,
        "report_days": [30, 60, 90],
        "clock_profile": "RECORDED_RECEIPT",
        "source_verified": True,
        "receipt_cursor_persistent": True,
        "carry_in_positions": False,
        "outcome_used_to_choose_start": False,
        "freeze_receipt_sha256": repeat.canonical_sha(receipt),
        "start_ms": start,
        "end_ms": start + 90 * repeat.DAY_MS,
    }


def test_forward_requires_prospective_utc30m_and_real_receipts() -> None:
    receipt = freeze_receipt()
    trusted = repeat.canonical_sha(receipt)
    repeat.check_forward(forward_contract(receipt), receipt, trusted)
    for field, value in (
        ("start_ms", repeat._ms("2026-10-06T03:31:00Z")),
        ("source_verified", False),
        ("clock_profile", "MODELED_BAR_CLOSE"),
        ("outcome_used_to_choose_start", True),
    ):
        row = forward_contract(receipt)
        row[field] = value
        with pytest.raises(repeat.AdmissionError):
            repeat.check_forward(row, receipt, trusted)


def test_forward_start_cannot_self_assert_an_earlier_freeze() -> None:
    receipt = freeze_receipt()
    row = forward_contract(receipt)
    row["start_ms"] = repeat._ms("2026-10-06T02:30:00Z")
    row["end_ms"] = row["start_ms"] + 90 * repeat.DAY_MS
    row["protocol_frozen_ms"] = 0
    with pytest.raises(repeat.AdmissionError, match="FIRST_POST_FREEZE"):
        repeat.check_forward(row, receipt, repeat.canonical_sha(receipt))
    tampered = dict(receipt, frozen_at_ms=0)
    with pytest.raises(repeat.AdmissionError, match="RECEIPT_IDENTITY"):
        repeat.check_forward(row, tampered, repeat.canonical_sha(receipt))


def test_forward_requires_exact_first_boundary_and_external_trusted_digest() -> None:
    receipt = freeze_receipt()
    row = forward_contract(receipt)
    row["start_ms"] += repeat.HALF_HOUR_MS
    row["end_ms"] += repeat.HALF_HOUR_MS
    with pytest.raises(repeat.AdmissionError, match="FIRST_POST_FREEZE"):
        repeat.check_forward(row, receipt, repeat.canonical_sha(receipt))
    with pytest.raises(repeat.AdmissionError, match="TRUSTED_CLAIM"):
        repeat.check_forward(forward_contract(receipt), receipt, "2" * 64)


def test_forward_freeze_is_loaded_from_fixed_permanent_claim_ref() -> None:
    receipt = freeze_receipt()
    receipt_raw = json.dumps(receipt).encode()
    receipt_blob = repeat._git_blob(receipt_raw)
    claim = {
        "schema": "scalp7.issue1361.forward_claim.v1",
        "issue": 1361,
        "state": "RESERVED_NONRETRYABLE",
        "claim_ref": repeat.FORWARD_CLAIM_REF,
        "protocol_sha256": repeat.PROTOCOL_SHA256,
        "rule_sha256": repeat.RULE_SHA256,
        "freeze_blob_sha": receipt_blob,
        "freeze_receipt_sha256": repeat.canonical_sha(receipt),
        "source_binding_sha256": receipt["source_binding_sha256"],
        "independent_approval_commit_sha": "a" * 40,
    }
    claim_raw = json.dumps(claim).encode()
    claim_blob = repeat._git_blob(claim_raw)
    objects = {
        "/git/ref/heads/research-execution-claims/issue1361-forward-20261006-v1": {
            "ref": repeat.FORWARD_CLAIM_REF,
            "object": {"type": "commit", "sha": "b" * 40},
        },
        "/git/commits/" + "b" * 40: {"tree": {"sha": "c" * 40}},
        "/git/trees/" + "c" * 40: {"tree": [
            {"path": "CLAIM.json", "type": "blob", "sha": claim_blob},
            {"path": "FREEZE.json", "type": "blob", "sha": receipt_blob},
        ]},
        "/git/blobs/" + claim_blob: {
            "encoding": "base64", "content": base64.b64encode(claim_raw).decode()
        },
        "/git/blobs/" + receipt_blob: {
            "encoding": "base64", "content": base64.b64encode(receipt_raw).decode()
        },
    }

    def api(method: str, route: str) -> dict:
        assert method == "GET"
        return objects[route]

    loaded, trusted = repeat.verified_forward_freeze(api)
    assert loaded == receipt
    repeat.check_forward(forward_contract(receipt), loaded, trusted)


def test_history_rejects_strategy_instance_substitution() -> None:
    rows = repeat.planned_history()
    rows[2]["instances"] = ["SOME_OTHER_STRATEGY"]
    with pytest.raises(repeat.AdmissionError, match="instances"):
        repeat.check_history(rows)


def test_inventory_distinguishes_missing_match_and_mismatch(tmp_path) -> None:
    expected = {
        "a/MANIFEST.json": hashlib.sha256(b"a").hexdigest(),
        "b/MANIFEST.json": hashlib.sha256(b"b").hexdigest(),
    }
    (tmp_path / "a").mkdir()
    (tmp_path / "a/MANIFEST.json").write_bytes(b"a")
    result = repeat.inventory_source(tmp_path, expected, "0" * 64)
    assert [row["state"] for row in result["entries"]] == [
        "AVAILABLE_HASH_MATCH", "MISSING"
    ]
    assert result["history_input_state"] == "INPUT_NOT_READY"
    (tmp_path / "b").mkdir()
    (tmp_path / "b/MANIFEST.json").write_bytes(b"wrong")
    assert repeat.inventory_source(tmp_path, expected, "0" * 64)["entries"][1]["state"] == "HASH_MISMATCH"


def test_inventory_ready_only_when_every_hash_matches(tmp_path) -> None:
    expected = {}
    for name, body in (("a", b"a"), ("b", b"b"), ("c", b"c")):
        path = tmp_path / name / "MANIFEST.json"
        path.parent.mkdir()
        path.write_bytes(body)
        expected[f"{name}/MANIFEST.json"] = hashlib.sha256(body).hexdigest()
    inventory = repeat.full_archive_inventory(tmp_path, expected)
    result = repeat.inventory_source(
        tmp_path, expected, repeat.archive_inventory_sha256(inventory)
    )
    assert result["history_input_state"] == "READY"
    assert result["network_actions"] == result["service_actions"] == 0


def test_inventory_rejects_missing_or_corrupt_archive_member(tmp_path) -> None:
    manifests = {}
    for segment, body in (
        ("canonical_12m", b"12m"),
        ("canonical_gapday_prefix", b"gap"),
        ("canonical_postgap_20260213", b"post"),
    ):
        path = tmp_path / segment / "MANIFEST.json"
        path.parent.mkdir()
        path.write_bytes(body)
        manifests[f"{segment}/MANIFEST.json"] = hashlib.sha256(body).hexdigest()
    body = tmp_path / "canonical_12m/requests/BTC.body"
    body.parent.mkdir()
    body.write_bytes(b"preserved")
    expected_inventory = repeat.full_archive_inventory(tmp_path, manifests)
    expected_sha = repeat.archive_inventory_sha256(expected_inventory)
    assert repeat.inventory_source(tmp_path, manifests, expected_sha)["history_input_state"] == "READY"
    body.write_bytes(b"corrupt")
    result = repeat.inventory_source(tmp_path, manifests, expected_sha)
    assert result["history_input_state"] == "INPUT_NOT_READY"
    assert result["full_inventory_state"] == "HASH_MISMATCH"


def test_inventory_rejects_matching_non_regular_entry(tmp_path) -> None:
    manifests = {}
    for segment, body in (
        ("canonical_12m", b"12m"),
        ("canonical_gapday_prefix", b"gap"),
        ("canonical_postgap_20260213", b"post"),
    ):
        path = tmp_path / segment / "MANIFEST.json"
        path.parent.mkdir()
        path.write_bytes(body)
        manifests[f"{segment}/MANIFEST.json"] = hashlib.sha256(body).hexdigest()
    expected = repeat.archive_inventory_sha256(
        repeat.full_archive_inventory(tmp_path, manifests)
    )
    non_file = tmp_path / "canonical_12m/requests/stale.body"
    non_file.mkdir(parents=True)
    result = repeat.inventory_source(tmp_path, manifests, expected)
    assert result["history_input_state"] == "INPUT_NOT_READY"
    assert result["full_inventory_sha256"] is None
    assert result["full_inventory_error"].startswith("SOURCE_INVENTORY_NON_REGULAR:")


def test_protocol_preserves_scope_cost_and_no_economic_authority() -> None:
    row = repeat.protocol()
    assert row["allocation"] == {
        "history_max_full": 6,
        "forward_model_streams": 2,
        "total_validation_instances": 8,
        "issue1358_budget_untouched": True,
    }
    assert row["strategy"]["new_rule_candidates"] == 0
    assert row["cost"]["funding_mark_nav_unknown_not_zero"] is True
    assert row["authority"] == "METADATA_ONLY_NO_SIGNAL_NO_FIT_NO_ECONOMIC_CLAIM"
