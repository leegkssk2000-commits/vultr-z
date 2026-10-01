"""Synthetic measurement chain only; no genuine history or economic FULL."""

import copy
from decimal import Decimal

import pytest

from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    MODEL,
    DetailExecutionAdapter,
)
from backend.research.rebuild.scalp7_measurement_repair_v1 import (
    MINUTE,
    adapt_segment_details,
    clock_coverage,
    continuous_contract,
    followup_admission,
    value_trusted_prefix,
    window_measurement_status,
)


def order():
    return {
        "identity": "synthetic",
        "position_episode_id": "synthetic:X:1",
        "symbol": "X",
        "rule_digest": "fixture",
        "timing_basis": "HISTORICAL_MODEL",
        "decision_tf_min": 15,
        "feature_available_ts_ms": 0,
        "order_submit_ts_ms": 0,
        "order_active_ts_ms": 0,
        "expires_ts_ms": 1800000,
        "qty_base": 2,
        "side": 1,
        "order_kind": "NEXT_OPEN",
        "protective_stop": 90,
    }


def bar(t=0, **updates):
    return {
        "symbol": "X",
        "open_ts_ms": t,
        "close_ts_ms": t + MINUTE,
        "available_ts_ms": t + MINUTE,
        "segment_id": "synthetic",
        "open": 100,
        "high": 102,
        "low": 98,
        "close": 101,
        **updates,
    }


def mark(t, price=100):
    return {
        "ts_ms": t,
        "prices": {
            "X": {
                "ts_ms": t,
                "price": price,
                "price_basis": "LAST_PRICE",
                "source_ref": "synthetic",
            }
        },
    }


def test_gap_held_owner_blocks_later_entry_and_withholds_terminal_nav():
    adapter = DetailExecutionAdapter(order(), fill_model=MODEL, fee_rate="0.001")
    adapter.process_detail_bar(bar())
    adapter.process_detail_bar(bar(2 * MINUTE))
    saved = {
        **adapter.finish(),
        "unresolved_from_ts_ms": 0,
        "unresolved_observed_ts_ms": MINUTE,
        "gap_resume_or_detection_ts_ms": 2 * MINUTE,
    }
    assert saved["state"] == "UNRESOLVED"
    assert saved["position"] is not None
    assert [r["effect"] for r in saved["ledger"]] == ["OPEN"]
    untouched = copy.deepcopy(saved)
    followup = followup_admission([saved], "X")
    assert not followup["allowed"] and followup["retained_owners"] == ["synthetic:X:1"]
    assert followup_admission([saved], "Y")["allowed"]
    valued = value_trusted_prefix(
        saved["ledger"],
        [mark(0), mark(2 * MINUTE, 110)],
        [saved],
        initial_cash=1000,
        start_ts_ms=0,
    )
    assert valued["account"]["valuation"]["curve"][-1]["equity_usdt"] == pytest.approx(
        999.8
    )
    assert (
        Decimal(
            valued["account"]["snapshots"][-1]["positions"][0]["remaining_qty_base"]
        )
        == 2
    )
    assert (
        valued["terminal_after_gap_nav"] is None
        and not valued["full_reference_nav_available"]
    )
    assert (
        valued["funding_status"] == "UNKNOWN_NOT_ZERO" and valued["new_full_runs"] == 0
    )
    assert saved == untouched


def test_contiguous_synthetic_exit_releases_owner_without_changing_rules():
    adapter = DetailExecutionAdapter(order(), fill_model=MODEL, fee_rate="0.001")
    adapter.process_detail_bar(bar())
    adapter.process_detail_bar(bar(MINUTE, low=89))
    saved = adapter.finish()
    assert saved["state"] == "CLOSED"
    assert [r["effect"] for r in saved["ledger"]] == ["OPEN", "CLOSE"]
    assert followup_admission([saved], "X")["allowed"]
    value = value_trusted_prefix(
        saved["ledger"],
        [mark(0), mark(MINUTE, 90), mark(2 * MINUTE, 90)],
        [saved],
        initial_cash=1000,
        start_ts_ms=0,
        expected_snapshot_times=[0, MINUTE, 2 * MINUTE],
    )
    assert value["terminal_after_gap_nav"] == pytest.approx(979.62)
    assert value["full_reference_nav_available"]


def test_cohort_boundary_is_separate_from_known_nav_and_internal_grid_hole():
    w = {"start_ts_ms": 0, "end_ts_ms": 2 * MINUTE}
    episodes = [
        {"entry_ts_ms": 0, "closed": True, "outcome_available_ts_ms": 3 * MINUTE}
    ]
    grid = [0, MINUTE, 2 * MINUTE]
    complete = window_measurement_status(
        w, [], grid, episodes, expected_snapshot_times=grid
    )
    assert not complete["cohort_complete"] and complete["cohort_crossing_count"] == 1
    assert complete["sampled_reference_nav_path_complete"]
    hole = window_measurement_status(
        w, [], [0, 2 * MINUTE], episodes, expected_snapshot_times=grid
    )
    assert not hole["sampled_reference_nav_path_complete"]
    assert hole["missing_expected_snapshot_count"] == 1
    assert not window_measurement_status(w, [], grid, episodes)[
        "sampled_reference_nav_path_complete"
    ]


def test_uniform_common_segments_adapt_without_prices_or_boundary_fabrication():
    rows = [bar(i * MINUTE) for i in [0, 1, 4, 5, 6]]
    cov = clock_coverage("X", (r["open_ts_ms"] for r in rows), 0, 7 * MINUTE)
    contract = continuous_contract(
        [cov],
        [{"path": "synthetic", "sha256": "a" * 64}],
        warmup_ms=MINUTE,
        decision_minutes=1,
    )
    assert [
        (r["raw_start_ts_ms"], r["raw_end_ts_ms"]) for r in contract["segments"]
    ] == [(0, 2 * MINUTE), (4 * MINUTE, 7 * MINUTE)]
    assert all(r["eligible_by_data_only"] for r in contract["segments"])
    assert contract["strategy_or_profit_used_for_selection"] is False
    before = copy.deepcopy(rows)
    adapted = adapt_segment_details(rows, contract, "common_contiguous_2", "X")
    assert [r["open"] for r in adapted] == [100] * 3
    assert [r["open_ts_ms"] for r in adapted] == [4 * MINUTE, 5 * MINUTE, 6 * MINUTE]
    assert all(r["segment_id"].startswith("measurement:") for r in adapted)
    assert rows == before
    with pytest.raises(ValueError, match="CONTINUOUS_SEGMENT"):
        adapt_segment_details(rows[:-1], contract, "common_contiguous_2", "X")
    tampered = copy.deepcopy(contract)
    tampered["segments"][0]["raw_end_ts_ms"] = 7 * MINUTE
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        adapt_segment_details(rows, tampered, "common_contiguous_1", "X")


@pytest.mark.parametrize("stamps", [[0, 0], [MINUTE, 0], [1], [False]])
def test_invalid_minute_clock_fails_closed(stamps):
    with pytest.raises(ValueError):
        clock_coverage("X", stamps, 0, 2 * MINUTE)


def test_actual_unchanged_sr_callers_run_all_synthetic_segments_independently():
    import pandas as pd
    from backend.research.rebuild.scalp7_measurement_compare_v1 import (
        run_synthetic_comparison,
    )

    tf = 30 * MINUTE
    values = [(100, 110, 90, 100)] * 48 + [
        (100, 112, 99, 111),
        (111, 113, 109, 112),
        (112, 113, 107, 108),
        (108, 108, 108, 108),
    ]
    rows = []
    offsets = [0, 4 * 86400000]
    for offset in offsets:
        for i, (opened, high, low, close) in enumerate(values):
            for j in range(30):
                c = close if j == 29 else opened
                rows.append(
                    bar(
                        offset + i * tf + j * MINUTE,
                        open=opened,
                        high=high if j == 0 else max(opened, c),
                        low=low if j == 0 else min(opened, c),
                        close=c,
                        volume=1,
                    )
                )
    frame = pd.DataFrame(rows)
    frame.attrs = {"data_kind": "SYNTHETIC_FIXTURE", "source_rows_are_genuine": False}
    end = offsets[-1] + 52 * tf
    coverage = clock_coverage("X", [r["open_ts_ms"] for r in rows], 0, end)
    contract = continuous_contract(
        [coverage],
        [{"path": "SYNTHETIC:box_retest", "sha256": "b" * 64}],
        warmup_ms=48 * tf,
        decision_minutes=30,
    )
    cost = {
        "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
        "per_side_rates": {"X": 0.0001},
        "funding_status": "UNKNOWN_NOT_ZERO",
    }
    output = run_synthetic_comparison(
        contract, {"X": frame}, fixture_label="SYNTHETIC_UNIT_TEST_ONLY", cost=cost
    )
    assert len(output["segments"]) == 2 and output["new_full_runs"] == 0
    assert output["whole_period_nav"] is None and output["rules_changed"] is False
    for offset, pair in zip(offsets, output["segments"].values()):
        for label, result in pair.items():
            ledger = result["execution"]["ledger"]
            assert len(ledger) == 2
            assert (
                ledger[0]["ts_ms"]
                == offset + (49 if label == "SR_CONTROL" else 50) * tf
            )
            assert ledger[-1]["fill_price"] == "108.0"
            assert result["unknown_execution_count"] == 0
            curve = result["cost_scenarios"]["1x"]["account"]["valuation"]["curve"]
            assert curve[0]["equity_usdt"] == 10000
            assert result["cost_scenarios"]["1x"]["windows"][0]["T_resolved"] == 1
            assert result["full_execution_performed"] is False
    with pytest.raises(PermissionError):
        run_synthetic_comparison(
            contract, {"X": frame}, fixture_label="GENUINE_RAW_HISTORY", cost=cost
        )
    frame.attrs["source_rows_are_genuine"] = True
    with pytest.raises(PermissionError):
        run_synthetic_comparison(
            contract, {"X": frame}, fixture_label="SYNTHETIC_UNIT_TEST_ONLY", cost=cost
        )


def test_sparse_prefix_cannot_claim_full_nav_without_expected_samples():
    value = value_trusted_prefix(
        [],
        [mark(0), mark(2 * MINUTE)],
        [],
        initial_cash=1000,
        start_ts_ms=0,
        expected_snapshot_times=[0, MINUTE, 2 * MINUTE],
    )
    assert not value["full_reference_nav_available"]
    assert value["terminal_after_gap_nav"] is None
    assert value["missing_expected_snapshot_count"] == 1


def test_future_genuine_gateway_fails_before_loader_without_exact_allocation(
    tmp_path, monkeypatch
):
    from backend.research.rebuild import scalp7_measurement_compare_v1 as comparison

    def forbidden(*args, **kwargs):
        pytest.fail("Producer or freeze reached before required allocation")

    monkeypatch.setattr(comparison, "freeze_comparison", forbidden)
    registry = tmp_path / "absent.sqlite3"
    with pytest.raises(PermissionError, match="ALLOCATION_ABSENT"):
        comparison.run_authorized_comparison(
            {"identity_key": "not-allocated"},
            expected_binding_sha256="a" * 64,
            registry_path=str(registry),
            scope="synthetic-no-budget",
            owner="test",
            output_path=str(tmp_path / "never-created.json"),
        )
    assert not registry.exists() and not (tmp_path / "never-created.json").exists()


def test_saved_nav_dd_survives_cohort_boundary_but_not_missing_price_path():
    from backend.research.rebuild.scalp7_measurement_repair_v1 import sampled_nav_dd

    window = {"start_ts_ms": 0, "end_ts_ms": 2 * MINUTE}
    curve = [
        {"ts_ms": t, "equity_usdt": v}
        for t, v in [(0, 100), (MINUTE, 80), (2 * MINUTE, 90)]
    ]
    episodes = [{"entry_ts_ms": 0, "closed": False, "outcome_available_ts_ms": None}]
    grid = [0, MINUTE, 2 * MINUTE]
    assert (
        sampled_nav_dd(curve, window, [], episodes, expected_snapshot_times=grid) == 20
    )
    assert (
        sampled_nav_dd(curve[::2], window, [], episodes, expected_snapshot_times=grid)
        is None
    )
    unknown = [
        {
            "state": "UNRESOLVED",
            "unresolved_from_ts_ms": 0,
            "unresolved_observed_ts_ms": MINUTE,
        }
    ]
    assert (
        sampled_nav_dd(curve, window, unknown, episodes, expected_snapshot_times=grid)
        is None
    )


@pytest.mark.parametrize("change", ["delayed", "mark", "symbol"])
def test_segment_adapter_does_not_relabel_late_clock_or_wrong_price_basis(change):
    import pandas as pd
    from backend.research.rebuild.scalp7_measurement_compare_v1 import segment_inputs

    rows = [bar(i * MINUTE, volume=1) for i in range(30)]
    coverage = clock_coverage("X", [r["open_ts_ms"] for r in rows], 0, 30 * MINUTE)
    contract = continuous_contract(
        [coverage],
        [{"path": "SYNTHETIC:clock", "sha256": "a" * 64}],
        warmup_ms=0,
        decision_minutes=30,
    )
    if change == "delayed":
        rows[0]["available_ts_ms"] += MINUTE
    elif change == "mark":
        rows[0]["price_basis"] = "MARK_PRICE"
    else:
        rows[0]["symbol"] = "Y"
    with pytest.raises(ValueError):
        segment_inputs({"X": pd.DataFrame(rows)}, contract, "common_contiguous_1")


def test_synthetic_comparison_hard_cap_precedes_any_producer():
    import pandas as pd
    from backend.research.rebuild.scalp7_measurement_compare_v1 import (
        run_synthetic_comparison,
    )

    with pytest.raises(PermissionError, match="BOUNDED_SYNTHETIC"):
        run_synthetic_comparison(
            {},
            {"X": pd.DataFrame({"x": range(5001)})},
            fixture_label="SYNTHETIC_UNIT_TEST_ONLY",
            cost={},
        )


def test_checkpoint_persists_file_then_directory_and_never_overwrites(
    tmp_path, monkeypatch
):
    import json
    import os
    import stat
    from backend.research.rebuild import scalp7_measurement_compare_v1 as comparison

    synced = []
    real_fsync = os.fsync

    def observed_fsync(fd):
        synced.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        real_fsync(fd)

    monkeypatch.setattr(comparison.os, "fsync", observed_fsync)
    checkpoint = tmp_path / "synthetic.checkpoint.json"
    comparison._save_durable_exclusive(
        checkpoint, {"fixture": True, "new_full_runs": 0}
    )
    assert synced == ["file", "directory"]
    assert json.loads(checkpoint.read_text()) == {"fixture": True, "new_full_runs": 0}
    before = checkpoint.read_bytes()
    with pytest.raises(FileExistsError):
        comparison._save_durable_exclusive(checkpoint, {"replacement": True})
    assert checkpoint.read_bytes() == before
    assert synced == ["file", "directory"]
