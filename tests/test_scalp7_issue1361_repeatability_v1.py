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


def forward_contract() -> dict:
    frozen = repeat._ms("2026-10-06T03:00:00Z")
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
        "protocol_frozen_ms": frozen,
        "start_ms": start,
        "end_ms": start + 90 * repeat.DAY_MS,
    }


def test_forward_requires_prospective_utc30m_and_real_receipts() -> None:
    repeat.check_forward(forward_contract())
    for field, value in (
        ("start_ms", repeat._ms("2026-10-06T03:31:00Z")),
        ("source_verified", False),
        ("clock_profile", "MODELED_BAR_CLOSE"),
        ("outcome_used_to_choose_start", True),
    ):
        row = forward_contract()
        row[field] = value
        with pytest.raises(repeat.AdmissionError):
            repeat.check_forward(row)


def test_inventory_distinguishes_missing_match_and_mismatch(tmp_path) -> None:
    expected = {
        "a/MANIFEST.json": hashlib.sha256(b"a").hexdigest(),
        "b/MANIFEST.json": hashlib.sha256(b"b").hexdigest(),
    }
    (tmp_path / "a").mkdir()
    (tmp_path / "a/MANIFEST.json").write_bytes(b"a")
    result = repeat.inventory_source(tmp_path, expected)
    assert [row["state"] for row in result["entries"]] == [
        "AVAILABLE_HASH_MATCH", "MISSING"
    ]
    assert result["history_input_state"] == "INPUT_NOT_READY"
    (tmp_path / "b").mkdir()
    (tmp_path / "b/MANIFEST.json").write_bytes(b"wrong")
    assert repeat.inventory_source(tmp_path, expected)["entries"][1]["state"] == "HASH_MISMATCH"


def test_inventory_ready_only_when_every_hash_matches(tmp_path) -> None:
    expected = {}
    for name, body in (("a", b"a"), ("b", b"b"), ("c", b"c")):
        path = tmp_path / name / "MANIFEST.json"
        path.parent.mkdir()
        path.write_bytes(body)
        expected[f"{name}/MANIFEST.json"] = hashlib.sha256(body).hexdigest()
    result = repeat.inventory_source(tmp_path, expected)
    assert result["history_input_state"] == "READY"
    assert result["network_actions"] == result["service_actions"] == 0


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
