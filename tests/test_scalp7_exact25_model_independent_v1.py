"""Independent source/model/portfolio checks using newly constructed toy prices."""

from decimal import Decimal

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_model_runner_v1 as runner
from backend.research.rebuild import scalp7_exact25_session_models_v1 as session

MINUTE = 60_000
TF = 30 * MINUTE
DAY = session.DAY
START = 14 * DAY


def flat_context(close=100):
    rows = []
    for index in range(14 * 48):
        rows.append(
            dict(
                open_ts_ms=index * TF,
                close_ts_ms=(index + 1) * TF,
                available_ts_ms=(index + 1) * TF,
                segment_id="independent",
                open=100,
                high=max(100, close),
                low=min(100, close),
                close=close,
                volume=0,
            )
        )
    return pd.DataFrame(rows)


def minute_path():
    rows = []
    previous = 100
    for index in range(1441):
        if index < 29:
            close = 100
        elif index < 59:
            close = 101
        elif index < 89:
            close = 99
        else:
            close = 98
        rows.append(
            dict(
                open_ts_ms=START + index * MINUTE,
                close_ts_ms=START + (index + 1) * MINUTE,
                available_ts_ms=START + (index + 1) * MINUTE,
                segment_id="independent",
                open=previous,
                high=max(previous, close),
                low=min(previous, close),
                close=close,
                volume=0,
            )
        )
        previous = close
    return pd.DataFrame(rows)


def aggregate(minutes):
    rows = []
    # The extra UTC-boundary minute is execution detail, not a complete new day.
    for offset in range(0, 1440, 30):
        values = minutes.iloc[offset : offset + 30]
        if (
            len(values) != 30
            or values.open_ts_ms.iloc[-1] - values.open_ts_ms.iloc[0] != 29 * MINUTE
        ):
            continue
        rows.append(
            dict(
                open_ts_ms=int(values.open_ts_ms.iloc[0]),
                close_ts_ms=int(values.close_ts_ms.iloc[-1]),
                available_ts_ms=int(values.available_ts_ms.iloc[-1]),
                segment_id="independent",
                open=float(values.open.iloc[0]),
                high=float(values.high.max()),
                low=float(values.low.min()),
                close=float(values.close.iloc[-1]),
                volume=0,
            )
        )
    return pd.DataFrame(rows)


def inputs(gap=False):
    detail = minute_path()
    frames = pd.concat([flat_context(), aggregate(detail)], ignore_index=True)
    by_symbol = {"X": detail.copy(), "Y": detail.copy()}
    source_frames = {"X": frames.copy(), "Y": frames.copy()}
    if gap:
        by_symbol["X"] = by_symbol["X"].drop(index=500)
        # A source bar containing a missing minute is also removed, not filled.
        source_frames["X"] = source_frames["X"].drop(index=14 * 48 + 500 // 30)
    return {
        "frames": source_frames,
        "detail_frames": by_symbol,
        "price_snapshots": [
            {"ts_ms": START, "prices": {}},
            {
                "ts_ms": 15 * DAY + MINUTE,
                "prices": {
                    symbol: {
                        "ts_ms": 15 * DAY + MINUTE,
                        "price": 98,
                        "price_basis": "LAST_PRICE",
                        "source_ref": "independent_toy",
                    }
                    for symbol in by_symbol
                },
            },
        ],
    }


def binding(windows=None):
    return runner.freeze_model(
        model_module=session.__name__,
        model_id=session.PORTFOLIO_MODEL_ID,
        strategy_id="trend_rider",
        baseline_id="independent-synthetic-session",
        changed_axis="NONE_INDEPENDENT_WIRING_TEST",
        config=session.noise_portfolio_config(["X", "Y"]),
        data_manifest={
            "data_kind": "SYNTHETIC_FIXTURE",
            "construction_reason": "Independent two-day timing and cash arithmetic fixture",
        },
        cost={
            "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
            "per_side_rates": {"X": 0.0001, "Y": 0.0001},
            "funding_status": "UNKNOWN_NOT_ZERO",
        },
        windows=windows
        or [
            {
                "name": "validation",
                "kind": "VALIDATION",
                "start_ts_ms": START,
                "end_ts_ms": 15 * DAY + 2 * MINUTE,
            }
        ],
        initial_cash_usdt=1000,
        compiler="noise_portfolio_schedule",
        execution_mode="SESSION_TARGET",
    )


def replay(gap=False, windows=None):
    frozen = binding(windows)
    return runner.run_fixture(
        frozen, inputs(gap), expected_binding_sha256=frozen["binding_sha256"]
    )


def test_source_negative_lower_band_is_valid_crypto_adaptation_geometry():
    context = flat_context(close=250)
    current = pd.DataFrame(
        [
            dict(
                open_ts_ms=START,
                close_ts_ms=START + TF,
                available_ts_ms=START + TF,
                segment_id="independent",
                open=100,
                high=700,
                low=100,
                close=700,
                volume=0,
            )
        ]
    )
    rows = session.noise_schedule(
        {"X": pd.concat([context, current], ignore_index=True)},
        session.noise_config("X"),
    )
    assert rows[-1]["upper"] == 625
    assert rows[-1]["lower"] == -50
    model = session.SessionTargetModel(session.noise_config("X"), 1000)
    order = model.on_decision(rows[-1])[0]
    assert order["side"] == 1 and Decimal(order["qty_base"]) == 10


def test_explicit_mark_price_cannot_be_used_as_last_price_input():
    frame = pd.concat([flat_context(), aggregate(minute_path())], ignore_index=True)
    frame["price_type"] = "mark"
    with pytest.raises(ValueError, match="PRICE"):
        session.noise_schedule({"X": frame}, session.noise_config("X"))


def test_portfolio_reversal_requires_ack_and_uses_source_session_quantity():
    report = replay()
    ledger = report["execution"]["ledger"]
    for symbol in ("X", "Y"):
        rows = [r for r in ledger if r["symbol"] == symbol]
        assert [r["effect"] for r in rows] == ["OPEN", "CLOSE", "OPEN", "CLOSE"]
        assert [r["side"] for r in rows] == [1, 1, -1, -1]
        assert all(Decimal(r["qty_base"]) == 5 for r in rows)
        assert (
            rows[2]["ts_ms"] == rows[1]["available_ts_ms"] == rows[1]["ts_ms"] + MINUTE
        )
        assert rows[-1]["ts_ms"] == 15 * DAY
    window = report["cost_scenarios"]["1x"]["windows"][0]
    # Per sleeve: 5*(99-101) - 5*(98-99) = -5 gross, fee0.1985.
    assert window["T_resolved"] == 4
    assert window["gross_resolved_usdt"] == pytest.approx(-10)
    assert window["net_resolved_reference_usdt"] == pytest.approx(-10.397)
    assert window["actual_historical_net_usdt"] is None
    assert window["funding_status"] == "UNKNOWN_NOT_ZERO"
    assert report["unknown_execution_count"] == 0


def test_one_symbol_gap_never_donates_cash_or_stops_healthy_owned_sleeve():
    report = replay(gap=True)
    ledger = report["execution"]["ledger"]
    bad = [r for r in ledger if r["symbol"] == "X"]
    healthy = [r for r in ledger if r["symbol"] == "Y"]
    assert len(bad) == 3
    assert len(healthy) == 4 and healthy[-1]["ts_ms"] == 15 * DAY
    assert all(Decimal(r["qty_base"]) == 5 for r in healthy)
    assert report["unknown_execution_count"] == 1
    assert (
        report["cost_scenarios"]["1x"]["windows"][0]["net_complete_reference_usdt"]
        is None
    )


def test_later_session_gap_does_not_relabel_earlier_empty_window_as_incomplete():
    windows = [
        {
            "name": "validation",
            "kind": "VALIDATION",
            "start_ts_ms": 13 * DAY,
            "end_ts_ms": START,
        },
        {
            "name": "rolling",
            "kind": "ROLLING",
            "start_ts_ms": START,
            "end_ts_ms": 15 * DAY + 2 * MINUTE,
        },
    ]
    report = replay(gap=True, windows=windows)
    validation, rolling = report["cost_scenarios"]["1x"]["windows"]
    assert validation["complete_window"] and validation["T_resolved"] == 0
    assert not rolling["complete_window"]
    assert report["fresh_T"] == 0
