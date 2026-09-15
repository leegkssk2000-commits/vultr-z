from backend.research.rebuild.a1_scalp7_squeeze_be1r_lifecycle_v1 import (
    apply_be1r_long,
)


def test_be_stop_activates_only_after_witness_bar() -> None:
    result = apply_be1r_long(
        entry_price=100.0,
        risk_price=2.0,
        cost_bps=20.0,
        original_exit_price=96.0,
        original_exit_ts=4,
        bars=[
            {"ts_ms": 1, "high": 102.5, "low": 99.0},
            {"ts_ms": 2, "high": 101.0, "low": 100.1},
        ],
    )
    assert result.exit_ts == 2
    assert result.reason == "BE1R_FEE_ADJUSTED_STOP"
    assert abs(result.net_bps) < 1e-9


def test_same_bar_low_does_not_assume_intrabar_order() -> None:
    result = apply_be1r_long(
        entry_price=100.0,
        risk_price=2.0,
        cost_bps=20.0,
        original_exit_price=103.0,
        original_exit_ts=2,
        bars=[{"ts_ms": 1, "high": 102.5, "low": 99.0}],
    )
    assert result.reason == "ORIGINAL_EXIT"
    assert result.armed_1r is True
