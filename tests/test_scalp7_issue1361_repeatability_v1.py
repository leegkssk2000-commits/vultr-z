from __future__ import annotations

import hashlib

import pytest

from ops import issue1361_repeatability_v1 as repeat


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
    repeat.check_forward(forward_contract(receipt), receipt)
    for field, value in (
        ("start_ms", repeat._ms("2026-10-06T03:31:00Z")),
        ("source_verified", False),
        ("clock_profile", "MODELED_BAR_CLOSE"),
        ("outcome_used_to_choose_start", True),
    ):
        row = forward_contract(receipt)
        row[field] = value
        with pytest.raises(repeat.AdmissionError):
            repeat.check_forward(row, receipt)


def test_forward_start_cannot_self_assert_an_earlier_freeze() -> None:
    receipt = freeze_receipt()
    row = forward_contract(receipt)
    row["start_ms"] = repeat._ms("2026-10-06T02:30:00Z")
    row["end_ms"] = row["start_ms"] + 90 * repeat.DAY_MS
    row["protocol_frozen_ms"] = 0
    with pytest.raises(repeat.AdmissionError, match="NOT_PROSPECTIVE"):
        repeat.check_forward(row, receipt)
    tampered = dict(receipt, frozen_at_ms=0)
    with pytest.raises(repeat.AdmissionError, match="RECEIPT_IDENTITY"):
        repeat.check_forward(row, tampered)


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
