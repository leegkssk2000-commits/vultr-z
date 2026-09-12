from backend.research.rebuild.top5_pre_g5_tooling_v1 import (
    closed_t_accounting,
    collector_integrity,
    fail_attribution,
    g5b_successor_template,
    preregister_accelerator,
)


def sample_rows():
    return [
        {"trade_id": "a", "status": "CLOSED", "symbol": "BTC-USDT", "regime": "trend", "exit_ts": 1, "gross_bps": 100.0, "cost_bps": 10.0, "net_bps": 90.0, "exposure_symbol_days": 1.0},
        {"trade_id": "b", "status": "CLOSED", "symbol": "ETH-USDT", "regime": "range", "exit_ts": 2, "gross_bps": -40.0, "cost_bps": 10.0, "net_bps": -50.0, "exposure_symbol_days": 2.0},
    ]


def test_accelerator_is_separate_outcome_blind_cohort():
    out = preregister_accelerator(
        lane="TrendRider Unified",
        official_boundary_ms=100,
        accelerator_boundary_ms=300,
        snapshot_observed_ms=200,
        top_n=2,
        ranked_snapshot=[
            {"symbol": "ETH-USDT", "quote_volume": 50},
            {"symbol": "BTC-USDT", "quote_volume": 100},
            {"symbol": "SOL-USDT", "quote_volume": 25},
        ],
    )
    assert out["symbols"] == ["BTC-USDT", "ETH-USDT"]
    assert out["formal_credit_isolated"] is True
    assert out["merge_into_official_cohort"] is False
    assert out["official_cohort_mutated"] is False


def test_accelerator_rejects_result_directed_fields_and_old_boundary():
    try:
        preregister_accelerator(
            lane="x",
            official_boundary_ms=100,
            accelerator_boundary_ms=100,
            snapshot_observed_ms=50,
            ranked_snapshot=[{"symbol": "BTC-USDT", "quote_volume": 1}],
        )
        assert False
    except ValueError as exc:
        assert "BOUNDARY" in str(exc)
    try:
        preregister_accelerator(
            lane="x",
            official_boundary_ms=100,
            accelerator_boundary_ms=200,
            snapshot_observed_ms=50,
            ranked_snapshot=[{"symbol": "BTC-USDT", "quote_volume": 1, "pnl": 9}],
        )
        assert False
    except ValueError as exc:
        assert "OUTCOME_FIELD" in str(exc)


def test_closed_accounting_waits_for_terminal_threshold_authority():
    out = closed_t_accounting(
        sample_rows(),
        threshold_authority=None,
        parent_digest="p",
        rule_digest="r",
        source_digest="s",
        cost_digest="c",
    )
    assert out["rows_T"] == 2
    assert out["net_bps"] == 40
    assert out["cost2_net_bps"] == 20
    assert out["expectancy_bps_per_T"] == 20
    assert out["pf"] == 1.8
    assert out["payoff"] == 1.8
    assert out["marked_dd_bps"] == 50
    assert out["state"] == "ACCOUNTED_WAIT_AUTHORITY"
    assert out["terminal_pass"] is False
    assert out["formal_credit_granted"] is False


def test_closed_accounting_rejects_open_or_censored_rows():
    rows = sample_rows()
    rows[0]["status"] = "OPEN"
    try:
        closed_t_accounting(rows, threshold_authority="ssot", parent_digest="p", rule_digest="r", source_digest="s", cost_digest="c")
        assert False
    except ValueError as exc:
        assert "FINALIZED_CLOSED" in str(exc)


def test_g5b_template_requires_explicit_g5a_pass_and_later_boundary():
    try:
        g5b_successor_template(lane="x", g5a_terminal_pass=False, g5a_terminal_observed_ms=100, g5b_boundary_ms=200, parent_digest="p", rule_digest="r", source_digest="s", cost_digest="c")
        assert False
    except ValueError as exc:
        assert "G5B_FORBIDDEN" in str(exc)
    try:
        g5b_successor_template(lane="x", g5a_terminal_pass=True, g5a_terminal_observed_ms=200, g5b_boundary_ms=200, parent_digest="p", rule_digest="r", source_digest="s", cost_digest="c")
        assert False
    except ValueError as exc:
        assert "BOUNDARY_MUST_BE_LATER" in str(exc)
    out = g5b_successor_template(lane="x", g5a_terminal_pass=True, g5a_terminal_observed_ms=200, g5b_boundary_ms=201, parent_digest="p", rule_digest="r", source_digest="s", cost_digest="c")
    assert out["reuse_g5a_credit"] is False
    assert out["formal_credit"] == 0


def test_fail_attribution_is_diagnostic_only():
    row = {**sample_rows()[1], "diagnostic_tags": ["LOSS_TAIL", "REGIME"]}
    out = fail_attribution([row])
    assert out["diagnostic_only"] is True
    assert out["fresh_rows_may_select_candidate"] is False
    assert out["candidate"] is None
    assert out["categories"]["LOSS_TAIL"]["rows"] == 1


def test_integrity_blocks_stale_drift_open_and_gap_without_repair():
    rows = sample_rows()
    rows[1]["status"] = "OPEN"
    out = collector_integrity(
        rows=rows,
        cursor_ms=0,
        now_ms=1000,
        stale_after_ms=10,
        expected_parent_digest="p",
        expected_rule_digest="r",
        expected_source_digest="s",
        expected_cost_digest="c",
        state_parent_digest="wrong",
        state_rule_digest="r",
        state_source_digest="s",
        state_cost_digest="c",
        expected_bar_interval_ms=100,
        observed_bar_open_ms=[0, 100, 300],
    )
    assert out["state"] == "BLOCKED"
    assert "STALE_CURSOR" in out["blockers"]
    assert "PARENT_DIGEST_DRIFT" in out["blockers"]
    assert "OPEN_OR_CENSORED_ROWS" in out["blockers"]
    assert "SOURCE_BAR_GAP" in out["blockers"]
    assert out["synthetic_repair"] is False
    assert out["backfill"] is False


def test_integrity_passes_clean_exact_identity():
    out = collector_integrity(
        rows=sample_rows(),
        cursor_ms=900,
        now_ms=1000,
        stale_after_ms=200,
        expected_parent_digest="p",
        expected_rule_digest="r",
        expected_source_digest="s",
        expected_cost_digest="c",
        state_parent_digest="p",
        state_rule_digest="r",
        state_source_digest="s",
        state_cost_digest="c",
    )
    assert out["state"] == "PASS"
    assert out["formal_credit_mutated"] is False
