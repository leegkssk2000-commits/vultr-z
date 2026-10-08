"""Synthetic clock/lifecycle fixtures; no archive or economic campaign access."""
import copy

import pandas as pd
import pytest

from ops import issue1388_inverted_execution_v1 as adapter
from ops.issue1388_inverted_hammer_v1 import inverted_hammer_flags

H = adapter.HOUR
SYMBOL = "BTC-USDT"


def bars(count=200):
    return [{"open_ts_ms": i * H, "close_ts_ms": (i + 1) * H,
             "available_ts_ms": (i + 1) * H, "segment_id": "A",
             "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
            for i in range(count)]


def run(rows, entries=(160,), *, funding=(), start=150 * H, end=None, cost=14.0):
    flags = [i in entries for i in range(len(rows))]
    decisions = adapter.bind_inverted_decisions(rows, flags)
    return adapter.replay_inverted_hammer(SYMBOL, rows, decisions, funding,
        start_ms=start, end_ms=rows[-1]["close_ts_ms"] if end is None else end,
        roundtrip_cost_bps=cost)


def settlement(at, rate, mark=100.0):
    return {"symbol": SYMBOL, "fundingTime": at * H, "fundingRate": rate, "markPrice": mark}


def source_bars(count=210):
    rows = bars(count)
    for i, row in enumerate(rows):
        close = 1000.0 - i
        row.update(open=close + 2, high=close + 3, low=close - 1, close=close)
    rows[160].update(open=840.0, high=841.25, low=840.0, close=840.25)
    return rows


def test_fixed_24h_from_execution_not_signal_close_and_exact_open_price():
    rows = bars()
    rows[160]["available_ts_ms"] = 163 * H + 1
    rows[188].update(open=103.0, high=104.0, low=99.0)
    result = run(rows)
    trade = result["trades"][0]
    assert trade["entry_ts_ms"] == 164 * H
    assert trade["exit_due_ts_ms"] == trade["exit_ts_ms"] == 188 * H
    assert trade["exit_price"] == 103.0
    assert trade["gross_bps"] == pytest.approx(300.0)
    assert trade["net_bps"] == pytest.approx(286.0)
    assert result["paid_trading_cost_bps"] == result["closed_trading_cost_bps"] == 14.0
    assert result["open_entry_cost_bps"] == 0.0


def test_no_sl_tp_intrabar_or_candle_close_exit():
    rows = bars()
    for i in range(162, 185):
        rows[i].update(high=1000.0, low=1.0, close=1.0)
    rows[185].update(open=110.0, high=111.0, close=101.0)
    trade = run(rows)["trades"][0]
    assert trade["exit_ts_ms"] == 185 * H and trade["exit_price"] == 110.0
    assert trade["exit_reason"] == "NEXT_AVAILABLE_OPEN_FIXED24H"
    assert trade["exit_time_kind"] == "OBSERVED_OPEN"


def test_occupied_and_pending_signals_are_not_future_requeued():
    rows = bars()
    rows[160]["available_ts_ms"] = 162 * H + 1
    rows[161]["available_ts_ms"] = 164 * H
    result = run(rows, entries=(160, 161, 165, 184, 187))
    assert result["pending_entry_rejections"] == 1
    assert result["occupied_rejections"] == 2
    assert result["signals"] == 5
    assert len(result["trades"]) == 1
    assert result["trades"][0]["exit_ts_ms"] == 187 * H
    assert result["open_position"]["signal_open_ts_ms"] == 187 * H
    assert result["open_position"]["entry_ts_ms"] == 188 * H


@pytest.mark.parametrize("count", [185, 186])
def test_no_end_forced_fill_and_entry_half_cost_separate(count):
    result = run(bars(count), entries=(161,))
    assert result["trades"] == []
    assert result["open_position"]["entry_ts_ms"] == 162 * H
    assert result["open_position"]["exit_due_ts_ms"] == 186 * H
    assert result["unresolved_end"] == 1
    assert result["disposition"] == "BLOCKED_TERMINAL_UNRESOLVED"
    assert result["paid_trading_cost_bps"] == result["open_entry_cost_bps"] == 7.0
    assert result["closed_trading_cost_bps"] == 0.0


def test_exact_end_due_is_not_available_execution_and_funding_end_exclusive():
    result = run(bars(185), funding=(settlement(184, .001), settlement(185, .002)))
    assert result["trades"] == []
    assert result["open_position"]["funding_bps_to_end_exclusive"] == pytest.approx(10.0)
    assert result["open_position"]["funding_settlements"] == 1


def test_end_signal_is_not_order_and_prestart_signal_not_reused():
    result = run(bars(170), entries=(149, 169))
    assert result["signals"] == 0
    assert result["orders"] == [] and result["pending_entry"] is None
    assert result["unresolved_end"] == 0


def test_late_final_signal_remains_unpaid_pending():
    rows = bars(170)
    rows[168]["available_ts_ms"] = 170 * H + 1
    result = run(rows, entries=(168,))
    assert result["pending_entry"]["signal_open_ts_ms"] == 168 * H
    assert result["orders"] == [] and result["paid_trading_cost_bps"] == 0.0
    assert result["unresolved_end"] == 1


@pytest.mark.parametrize("at", [162, 185])
@pytest.mark.parametrize("kind", ["missing", "segment"])
def test_occupied_gap_is_quarantined_before_due_open(at, kind):
    rows = bars()
    if kind == "missing":
        del rows[at]
        expected = (at + 1) * H
    else:
        rows[at]["segment_id"] = "B"
        expected = at * H
    result = run(rows)
    assert result["trades"] == []
    assert result["gap_quarantine"]["gap_ts_ms"] == expected
    assert result["open_position"]["entry_ts_ms"] == 161 * H
    assert result["open_position"]["funding_bps_to_end_exclusive"] is None
    assert result["disposition"] == "BLOCKED_SOURCE_GAP"
    assert result["open_entry_cost_bps"] == 7.0


def test_pending_gap_does_not_invent_entry_and_closed_trade_survives_later_gap():
    rows = bars()
    rows[160]["available_ts_ms"] = 164 * H
    del rows[162]
    result = run(rows)
    assert result["gap_quarantine"] is not None and result["orders"] == []
    rows = bars(220)
    rows[189]["segment_id"] = "B"
    result = run(rows, entries=(160, 188))
    assert len(result["trades"]) == 1
    assert result["trades"][0]["exit_ts_ms"] == 185 * H
    assert result["gap_quarantine"]["pending_entry"]["signal_open_ts_ms"] == 188 * H
    assert result["paid_trading_cost_bps"] == 14.0


def test_funding_signed_marks_and_conservative_entry_exit_boundaries():
    funding = [settlement(161, -.001), settlement(161 + .5, -.001)]
    # Exact integer millisecond settlement clocks need not be hourly aligned.
    funding[1]["fundingTime"] = 161 * H + H // 2
    funding += [settlement(162, .001, 200), settlement(185, -.001), settlement(200, .1)]
    first = run(bars(), funding=funding)
    trade = first["trades"][0]
    assert trade["funding_bps"] == pytest.approx(10.0)
    assert trade["funding_settlements"] == 2
    assert trade["net_bps"] == pytest.approx(-24.0)
    positive = run(bars(), funding=[settlement(161, .001), settlement(185, .001)])
    assert positive["trades"][0]["funding_bps"] == pytest.approx(20.0)
    assert positive["trades"][0]["funding_settlements"] == 2
    stress = run(bars(), funding=funding, cost=28.0)
    assert stress["trades"][0]["funding_bps"] == trade["funding_bps"]
    assert stress["trades"][0]["net_bps"] == pytest.approx(-38.0)


def test_missing_funding_preserves_gross_but_cannot_supply_net():
    result = run(bars(), funding=None)
    assert result["trades"][0]["gross_bps"] == 0.0
    assert result["trades"][0]["funding_bps"] is None
    assert result["trades"][0]["net_bps"] is None
    assert result["disposition"] == "BLOCKED_MISSING_FUNDING"


def test_no_future_dependency_or_edited_decision_binding():
    rows = bars()
    rows[20]["available_ts_ms"] = 170 * H
    with pytest.raises(adapter.DraftError, match="DEPENDENCY_UNAVAILABLE"):
        adapter.bind_inverted_decisions(rows, [i == 160 for i in range(len(rows))])
    rows = bars()
    bound = adapter.bind_inverted_decisions(rows, [i == 160 for i in range(len(rows))])
    bound[160]["signal_available_ts_ms"] -= H
    with pytest.raises(adapter.DraftError, match="CLOCK_BINDING"):
        adapter.replay_inverted_hammer(SYMBOL, rows, bound, [], start_ms=150 * H, end_ms=200 * H, roundtrip_cost_bps=14.0)


@pytest.mark.parametrize("flag", [True, 1, "true"])
def test_no_warmup_bypass_or_truthy_flags(flag):
    rows = bars()
    flags = [False] * len(rows)
    flags[148] = flag
    with pytest.raises(adapter.DraftError, match="WARMUP_REQUIRED|STRICT_SOURCE"):
        adapter.bind_inverted_decisions(rows, flags)


def test_reused_segment_label_does_not_restore_rolling_history():
    rows = bars()
    rows[159]["segment_id"] = "B"
    with pytest.raises(adapter.DraftError, match="WARMUP_REQUIRED"):
        run(rows)


@pytest.mark.parametrize("change", ["fractional_clock", "boolean_cost", "nan_price", "wrong_funding_symbol", "duplicate_funding"])
def test_malformed_inputs_fail_closed(change):
    rows, funding, cost = bars(), [], 14.0
    if change == "fractional_clock":
        rows[3]["available_ts_ms"] += .5
    elif change == "boolean_cost":
        cost = True
    elif change == "nan_price":
        rows[165]["open"] = float("nan")
    elif change == "wrong_funding_symbol":
        funding = [{**settlement(170, .001), "symbol": "ETH-USDT"}]
    else:
        funding = [settlement(170, .001)] * 2
    with pytest.raises(adapter.DraftError):
        run(rows, funding=funding, cost=cost)


def test_real_frozen_source_flags_feed_causal_lifecycle_without_mutation():
    rows = source_bars()
    original = copy.deepcopy(rows)
    flags = inverted_hammer_flags(pd.DataFrame(rows)).tolist()
    assert flags[160] and sum(flags) == 1
    bound = adapter.bind_inverted_decisions(rows, flags)
    result = adapter.replay_inverted_hammer(SYMBOL, rows, bound, [], start_ms=150 * H,
                                          end_ms=210 * H, roundtrip_cost_bps=14.0)
    assert rows == original
    assert len(result["trades"]) == 1
    assert result["trades"][0]["entry_price"] == rows[161]["open"]
    assert result["trades"][0]["exit_price"] == rows[185]["open"]
    assert result["source_profits_reproduced"] is False


def test_independent_interval_audit_cannot_call_replay(monkeypatch):
    from ops.issue1388_inverted_audit_v1 import audit_inverted_hammer
    rows = source_bars()
    bound = adapter.bind_inverted_decisions(rows, inverted_hammer_flags(pd.DataFrame(rows)).tolist())
    result = adapter.replay_inverted_hammer(SYMBOL, rows, bound, [], start_ms=150 * H,
                                          end_ms=210 * H, roundtrip_cost_bps=14.0)
    def forbidden(*args, **kwargs):
        pytest.fail("AUDIT_MUST_NOT_REPLAY_EXECUTOR")
    monkeypatch.setattr(adapter, "replay_inverted_hammer", forbidden)
    audit = audit_inverted_hammer(SYMBOL, rows, bound, [], start_ms=150 * H, end_ms=210 * H,
                                  roundtrip_cost_bps=14.0, saved=result)
    assert audit["closed_trades"] == 1 and audit["source_flags_recomputed"] is True
    assert audit["lifecycle_replay_called"] is False


@pytest.mark.parametrize("tamper", ["net", "due", "order", "dropped_trade", "entry", "decision"])
def test_independent_audit_rejects_rehashed_outer_payload_tampering(tamper):
    import hashlib
    import json
    from ops.issue1388_inverted_audit_v1 import AuditError, audit_inverted_hammer
    rows = source_bars()
    bound = adapter.bind_inverted_decisions(rows, inverted_hammer_flags(pd.DataFrame(rows)).tolist())
    result = adapter.replay_inverted_hammer(SYMBOL, rows, bound, [], start_ms=150 * H,
                                          end_ms=210 * H, roundtrip_cost_bps=14.0)
    if tamper == "net":
        result["trades"][0]["net_bps"] += 1
    elif tamper == "due":
        result["trades"][0]["exit_due_ts_ms"] += H
    elif tamper == "order":
        result["orders"][0]["quantity"] = 2
    elif tamper == "dropped_trade":
        result["trades"].clear()
    elif tamper == "entry":
        result["trades"][0]["entry_ts_ms"] -= H
    else:
        bound[160]["entry"] = False
    # An internally self-consistent outer digest cannot repair source/lifecycle.
    assert hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    with pytest.raises(AuditError):
        audit_inverted_hammer(SYMBOL, rows, bound, [], start_ms=150 * H, end_ms=210 * H,
                              roundtrip_cost_bps=14.0, saved=result)
