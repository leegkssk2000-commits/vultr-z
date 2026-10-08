"""Source-pinned artificial fill regression; no market data or candidate economics.

Run: python source_fixture_1388/reproduce_structural_execution.py
The small corrected transition is a proposed adapter contract, not an implemented
ZEL adapter, donor profit replication, signal census, or economic execution.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
PIN = "ff0a35653d811d031ab56a1791869fc5f1cd3244ba55fdf225e94a412d905e4a"
assert hashlib.sha256((ROOT / "donor_engine.py").read_bytes()).hexdigest() == PIN
assert hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest() == "f55690dc0053e865ec88925bf02bcc62e580c6c60c1658326110fc10bb162bf9"
spec = importlib.util.spec_from_file_location("pinned_donor_engine", ROOT / "donor_engine.py")
donor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = donor
spec.loader.exec_module(donor)


def donor_exit(direction, trail=None):
    """Three fictional candles. Inspect fill only; never report synthetic PnL."""
    o = np.array([100., 100., 90. if direction == 1 else 110.])
    h = np.array([101., 104., 94. if direction == 1 else 114.])
    l = np.array([99., 96., 86. if direction == 1 else 106.])
    c = np.array([100., 100., 90. if direction == 1 else 110.])
    engine = donor.CausalBacktestEngine(taker_fee_bps=0, slippage_bps=0)
    # Avoid invoking the source aggregate performance estimator.
    engine._compute_metrics = lambda *args: args[-1]
    trades = engine.execute_stream(
        "ARTIFICIAL", "ARTIFICIAL", "1h", "FIXTURE_ONLY", o, h, l, c,
        np.array([0, 3600, 7200]),
        [{"bar_index": 0, "direction": direction,
          "stop_price": 95. if direction == 1 else 105.,
          "target_price": 125. if direction == 1 else 75.}],
        {3600: trail} if trail is not None else None,
    )
    assert len(trades) == 1
    trade = trades[0]
    return {"exit_price": trade.exit_px, "exit_ts": trade.exit_ts,
            "reason": trade.exit_reason}


def proposed_stop_transition(direction, current_stop, open_price, high, low,
                             known_before_open_trails):
    """Protective structural levels tagged by position side; adverse gap at open.

    Trail values must already be observed before this open, from completed MTF
    bars. This fixture does not certify timestamps or implement their producer.
    A protective level crossed at the next open triggers a market stop at open;
    ordinary intrabar stop crossings fill at the level. Costs belong downstream.
    """
    if direction not in (-1, 1) or not low <= open_price <= high:
        raise ValueError("invalid artificial bar/side")
    trail = known_before_open_trails.get(direction)
    if trail is not None:
        current_stop = max(current_stop, trail) if direction == 1 else min(current_stop, trail)
    if direction == 1 and open_price <= current_stop:
        return current_stop, open_price, "ADVERSE_OPEN_OR_ALREADY_TRIGGERED_STOP"
    if direction == -1 and open_price >= current_stop:
        return current_stop, open_price, "ADVERSE_OPEN_OR_ALREADY_TRIGGERED_STOP"
    if low <= current_stop <= high:
        return current_stop, current_stop, "INTRABAR_STOP"
    return current_stop, None, "NO_STOP_FILL"


def main():
    checks = []

    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append({"name": name, "actual": actual, "expected": expected, "pass": True})

    long_bad = donor_exit(1, 115.)
    short_bad = donor_exit(-1, 85.)
    long_gap = donor_exit(1)
    short_gap = donor_exit(-1)
    check("source_long_opposing_high_fill_above_bar_high", long_bad["exit_price"], 115.)
    check("source_short_opposing_low_fill_below_bar_low", short_bad["exit_price"], 85.)
    check("source_long_gap_fills_old_stop_above_bar_high", long_gap["exit_price"], 95.)
    check("source_short_gap_fills_old_stop_below_bar_low", short_gap["exit_price"], 105.)
    check("corrected_long_ignores_opposing_high", proposed_stop_transition(1, 95., 100., 104., 96., {-1: 115.}), (95., None, "NO_STOP_FILL"))
    check("corrected_short_ignores_opposing_low", proposed_stop_transition(-1, 105., 100., 104., 96., {1: 85.}), (105., None, "NO_STOP_FILL"))
    check("corrected_long_adverse_gap_uses_open", proposed_stop_transition(1, 95., 90., 94., 86., {}), (95., 90., "ADVERSE_OPEN_OR_ALREADY_TRIGGERED_STOP"))
    check("corrected_short_adverse_gap_uses_open", proposed_stop_transition(-1, 105., 110., 114., 106., {}), (105., 110., "ADVERSE_OPEN_OR_ALREADY_TRIGGERED_STOP"))
    check("own_long_trail_crossed_at_open_uses_open", proposed_stop_transition(1, 95., 100., 104., 96., {1: 102.}), (102., 100., "ADVERSE_OPEN_OR_ALREADY_TRIGGERED_STOP"))
    check("own_short_trail_crossed_at_open_uses_open", proposed_stop_transition(-1, 105., 100., 104., 96., {-1: 98.}), (98., 100., "ADVERSE_OPEN_OR_ALREADY_TRIGGERED_STOP"))
    check("long_intrabar_valid_protection", proposed_stop_transition(1, 95., 100., 104., 96., {1: 98.}), (98., 98., "INTRABAR_STOP"))
    check("short_intrabar_valid_protection", proposed_stop_transition(-1, 105., 100., 104., 96., {-1: 102.}), (102., 102., "INTRABAR_STOP"))
    check("long_never_loosen_stop", proposed_stop_transition(1, 98., 100., 104., 99., {1: 90.}), (98., None, "NO_STOP_FILL"))
    check("short_never_loosen_stop", proposed_stop_transition(-1, 102., 100., 101., 96., {-1: 110.}), (102., None, "NO_STOP_FILL"))
    result = {
        "schema": "ISSUE1388_STRUCTURAL_SOURCE_FILL_ARTIFICIAL_REGRESSION_V1",
        "source_version": "4097bb35c25c0996ff2a34e82b6cdde0b59734f3",
        "source_engine_sha256": PIN,
        "disposition": "DONOR_EXECUTION_DEFECT_REPRODUCED_ADAPTER_TRANSITION_DRAFT_TESTED_NOT_ECONOMIC_READY",
        "checks": checks, "checks_passed": len(checks),
        "synthetic_source_observations": {"long_opposite_level": long_bad,
            "short_opposite_level": short_bad, "long_gap": long_gap, "short_gap": short_gap},
        "market_data_read": False, "signal_census": False,
        "economic_screen_consumed": 0, "full_consumed": 0,
        "reported_economic_metrics": None, "ZEL_adapter_implemented": False,
        "source_profit_claim_reproduced": False, "ready": False,
        "remaining": ["old structural/SR failure dedup", "source-native SET3 rule and past-only input coverage binding",
                      "minimal common adapter and causal producer timestamps", "artificial integration/review/exact CI",
                      "source-exact no-PnL density preflight before any cheap screen"],
        "order_authority": "BLOCKED", "exchange_order_submitted": False,
    }
    (ROOT / "REGRESSION_RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"checks_passed": len(checks), "ready": False, "economic_consumed": 0,
                      "result_sha256": hashlib.sha256((ROOT / "REGRESSION_RESULT.json").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
