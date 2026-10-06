from __future__ import annotations

from backend.research.rebuild.issue1377_saved_ledger_audit_v1 import build


def test_keltner_saved_partition_and_cost_crossing_are_exact() -> None:
    value = build()["keltner"]
    assert value["rolling_count"] == 109
    assert value["classes"] == {
        "original_1x_losses": 44,
        "positive_1x_to_nonpositive_2x": 27,
        "positive_2x_survivors": 38,
    }
    assert value["transition_summary"]["exact_fee_be_plus_2bps_count"] == 23
    assert value["transition_summary"]["reason"] == {
        "HG_FROZEN_5BAR_MFE_SCRATCH": 2,
        "MAX_HOLD_NEXT_OPEN": 1,
        "STOP_FIRST": 24,
    }


def test_transition_rows_do_not_relabel_posthoc_outcomes_as_entry_facts() -> None:
    rows = build()["keltner"]["transition_trades"]
    assert len(rows) == 27
    assert all(set(row) == {"trade_id", "entry_observables", "posthoc_outcome"} for row in rows)
    assert all("reason" not in row["entry_observables"] for row in rows)
    assert all("mfe_R" not in row["entry_observables"] for row in rows)
    assert all("reason" in row["posthoc_outcome"] for row in rows)


def test_keltner_child_is_not_invented_from_forbidden_exit_retune() -> None:
    value = build()["keltner"]
    assert value["candidate_disposition"] == "NO_K_CHILD_SELECTED"
    assert "forbidden BE/SL/TP" in value["reason"]


def test_non_k_contract_is_one_axis_and_result_independent() -> None:
    contract = build()["non_k_selection"]["contract"]
    assert contract["identity"] == "mr_cross_sectional_contraction_cost2_gate_30m_v1"
    assert contract["changed_axis"] == (
        "ENTRY_QUALITY_OBSERVED_FIRST_CONTRACTION_VS_EXACT_PAIR_COST2"
    )
    assert contract["outcome_blind_threshold"] == (
        "EXACT_DIMENSIONALLY_MATCHED_COST2_NOT_FITTED_MULTIPLE"
    )
    assert contract["development_window"]["start_ms"] == 1_768_262_400_000
    assert contract["development_window"]["end_ms_exclusive"] == 1_781_654_400_000


def test_seven_lane_table_keeps_other_owner_and_input_holds() -> None:
    rows = {row["lane"]: row for row in build()["lane_table"]}
    assert len(rows) == 7
    assert rows["Trend Rider"]["work"] == "OTHER_OWNER_LEDGER_HANDOFF_ONLY"
    assert rows["Micro EDGE15m"]["state"] == "SOURCE_EXECUTION_HOLD"

