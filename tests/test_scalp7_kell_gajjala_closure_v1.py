"""Synthetic supplied-input lifecycle checks; genuine strategy probes/FULL=0."""

from copy import deepcopy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_kell_gajjala_closure_v1 as m
from backend.research.rebuild.scalp7_volume_contract_v1 import VERSION as VOLUME_VERSION

SYMBOL = "TEST-USDT"
BENCH = "BENCH-USDT"
START = 6 * m.HOUR
MANIFEST = {
    "data_kind": "SYNTHETIC_FIXTURE",
    "construction_reason": "Hand drawn ordered phases, causal callback/partial/gap counterexamples; not observed market history.",
}


def bars(values, minutes=15, start=START):
    rows = []
    for i, value in enumerate(values):
        o, high, low, close, *volume = value
        opened = start + i * minutes * m.MINUTE
        amount = volume[0] if volume else 100.0
        rows.append(
            {
                "open_ts_ms": opened,
                "close_ts_ms": opened + minutes * m.MINUTE,
                "available_ts_ms": opened + minutes * m.MINUTE,
                "segment_id": "fixture",
                "open": o,
                "high": high,
                "low": low,
                "close": close,
                "volume": amount,
                "volume_unit": "BASE",
                "source_base": amount,
                "source_base_available_ts_ms": opened + minutes * m.MINUTE,
            }
        )
    result = pd.DataFrame(rows)
    result.attrs.update(
        data_kind="SYNTHETIC_FIXTURE",
        fixture_label="SYNTHETIC_UNIT_TEST_ONLY",
        volume_units="BASE",
        source_revision_sha256="1" * 64,
        source_schema_sha256="2" * 64,
        source_unit_authority_sha256="3" * 64,
        volume_field_units={"source_base": "BASE"},
    )
    return result


def volume_binding():
    return {
        "schema": VOLUME_VERSION,
        "venue": "SYNTHETIC",
        "instrument": SYMBOL,
        "product": "SYNTHETIC",
        "base_asset": "TEST",
        "quote_asset": "USDT",
        "price_unit": "USDT",
        "source_revision_sha256": "1" * 64,
        "source_schema_sha256": "2" * 64,
        "source_unit_authority_sha256": "3" * 64,
        "source_unit_authority_locator": "synthetic fixture recipe",
        "evidence_kind": "SYNTHETIC_TEST_ONLY",
        "fields": {
            "base": {
                "value": "source_base",
                "available": "source_base_available_ts_ms",
                "unit": "BASE",
                "asset": "TEST",
                "observed": True,
            }
        },
    }


def config(model):
    level = 95 if model == m.KELL else 9
    own = bars(
        [
            (
                level + i * 0.001,
                level + 1 + i * 0.001,
                level - 1,
                level + 0.0005 + i * 0.001,
            )
            for i in range(30)
        ],
        minutes=60,
        start=0,
    )
    bench = bars([(level, level + 1, level - 1, level)] * 30, minutes=60, start=0)
    return {
        "tick_evidence": {
            SYMBOL: {
                "tick_size": 0.1 if model == m.KELL else 0.01,
                "unit": "QUOTE_PRICE_INCREMENT",
                "available_ts_ms": 0,
                "valid_from_ts_ms": 0,
                "valid_to_ts_ms": 100 * m.HOUR,
                "source_ref": "SYNTHETIC_PRICE_GRID_NOT_TRADES",
                "source_receipt_sha256": "a" * 64,
            }
        },
        "context_frames": {SYMBOL: own, BENCH: bench},
        "benchmark_symbol": BENCH,
        "volume_bindings": {SYMBOL: volume_binding()},
    }


def frame(model, managed=True):
    if model == m.KELL:
        values = [(100, 100.2, 99.8, 100)] * 30 + [
            (100, 110, 99, 105),
            (105, 107, 104, 106),
            (106, 108, 105, 107),
            (107, 107.5, 104, 105.5),
        ]
        tail = [
            (105.5, 110, 105, 109),
            (109, 110, 108.5, 109.5),
            (109.5, 110.5, 108, 110),
            (110, 111, 109, 110.5),
            (110.5, 115, 110, 114),
            (114, 115, 113, 114),
            (107, 108, 106, 107),
        ]
    else:
        values = [(10, 10.1, 9.9, 10)] * 30 + [
            (10, 14, 10, 13.8, 1000),
            (13.8, 13.9, 13, 13.2, 200),
            (13.2, 13.7, 13.1, 13.4, 200),
            (13.4, 14.2, 13.2, 14, 800),
        ]
        tail = [
            (14, 14.6, 13.9, 14.3),
            (14.3, 14.6, 14, 14.4),
            (14.4, 14.7, 13.8, 14.5),
            (14.5, 14.8, 14, 14.6),
            (14.6, 16, 14.5, 15.8),
            (15.8, 16, 15.4, 15.9),
            (13.7, 13.75, 13.6, 13.7),
        ]
    return bars(values + tail if managed else values)


def minute_details(decisions):
    values = []
    for row in decisions.to_dict("records"):
        last = row["open"]
        for i in range(15):
            close = row["open"] + (row["close"] - row["open"]) * (i + 1) / 15
            high = row["high"] if i == 5 else max(last, close)
            low = row["low"] if i == 10 else min(last, close)
            values.append((last, high, low, close, row["volume"] / 15))
            last = close
    return bars(values, minutes=1)


def compile_one(model, data=None, cfg=None):
    return m.compile_model(
        model,
        {SYMBOL: frame(model, False) if data is None else data},
        config(model) if cfg is None else cfg,
    )


def run_one(model, data=None, details=None, cfg=None):
    data = frame(model) if data is None else data
    details = minute_details(data) if details is None else details
    return m.run_fixture(
        model,
        {SYMBOL: data},
        {SYMBOL: details},
        config(model) if cfg is None else cfg,
        fixture_manifest=MANIFEST,
    )


def test_two_lineages_three_aliases_and_source_rules_are_separate():
    assert m.ALIASES["break_and_continue"] == m.ALIASES["scalp_snap"]
    assert len(m.catalog()) == 2
    for model in m.MODEL_IDS:
        assert {row["origin"] for row in m.rules(model)} == {
            "SOURCE_DIRECT",
            "EXISTING_FROZEN",
            "DECLARED_HYPOTHESIS",
        }
        assert not m.catalog()[model]["source_exact"]
        assert m.catalog()[model]["genuine_economic_readiness"].startswith("BLOCKED")


@pytest.mark.parametrize("model", m.MODEL_IDS)
def test_actual_frozen_producer_selection_formation_entry_plan(model):
    r = compile_one(model)
    assert len(r["plans"]) == 1
    p = r["plans"][0]
    assert p["setup_ts_ms"] < p["feature_available_ts_ms"] < p["order_active_ts_ms"]
    assert p["selection"]["context_available_ts_ms"] <= p["setup_ts_ms"]
    assert p["source_intent_sha256"] and p["producer_rule_digest"]
    assert p["protective_stop"] < p["reference_entry_price"]
    assert not r["genuine_execution_ready"] and r["new_full_runs"] == 0
    if model == m.KELL:
        assert p["order_kind"] == "STOP_MARKET"
        assert any(e.get("kind") == "EMA_CROSS_WATCH_ONLY" for e in r["events"])
        assert any(e.get("kind") == "CONFIRMED_SWING_PIVOT" for e in r["events"])
    else:
        assert p["order_kind"] == "NEXT_OPEN"
        assert "VARIANT" in p["entry_variant"]
        assert any(e.get("kind") == "SMALL_FLAG" for e in r["events"])


def test_kell_watch_alone_is_not_an_entry_or_full_method():
    r = compile_one(m.KELL, frame(m.KELL, False).iloc[:31])
    assert not r["plans"]
    assert any(e.get("kind") == "EMA_CROSS_WATCH_ONLY" for e in r["events"])


@pytest.mark.parametrize("model", m.MODEL_IDS)
def test_future_suffix_does_not_repaint_existing_candidate(model):
    prefix = compile_one(model)["plans"]
    data = frame(model)
    data.loc[len(data) - 1, ["high", "close"]] = [999, 999]
    observed = compile_one(model, data)["plans"]
    assert observed[: len(prefix)] == prefix


@pytest.mark.parametrize("mutation", ["missing", "late", "misaligned", "weak"])
def test_selection_requires_available_support_and_relative_strength(mutation):
    cfg = config(m.KELL)
    if mutation == "missing":
        del cfg["context_frames"][BENCH]
    elif mutation == "late":
        cfg["context_frames"][SYMBOL]["available_ts_ms"] += 100 * m.HOUR
    elif mutation == "misaligned":
        # Last benchmark bar is unavailable at origin, leaving an older clock.
        origin = frame(m.KELL).iloc[30]["available_ts_ms"]
        bench = cfg["context_frames"][BENCH]
        latest = bench[bench["close_ts_ms"] <= origin].index[-1]
        bench.loc[latest:, "available_ts_ms"] += 100 * m.HOUR
    else:
        f = cfg["context_frames"][SYMBOL]
        f["open"] = 95
        f["close"] = 95
    assert not compile_one(m.KELL, cfg=cfg)["plans"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("available_ts_ms", 100 * m.HOUR),
        ("valid_from_ts_ms", 100 * m.HOUR),
        ("valid_to_ts_ms", 1),
    ],
)
def test_price_grid_receipt_is_point_in_time_not_trade_tape(key, value):
    cfg = config(m.KELL)
    cfg["tick_evidence"][SYMBOL][key] = value
    assert not compile_one(m.KELL, cfg=cfg)["plans"]


def test_tick_count_cannot_replace_price_grid():
    cfg = config(m.KELL)
    cfg["tick_evidence"][SYMBOL]["unit"] = "TRADE_COUNT"
    with pytest.raises(ValueError, match="PRICE_GRID"):
        compile_one(m.KELL, cfg=cfg)


def test_gajjala_requires_actual_unit_bound_base_volume_not_just_label():
    data = frame(m.GAJJALA, False)
    data.attrs["volume_units"] = "UNKNOWN"
    r = compile_one(m.GAJJALA, data)
    assert not r["plans"]
    assert any(e["kind"] == "BLOCKED_VOLUME_CONTRACT" for e in r["events"])
    cfg = config(m.GAJJALA)
    cfg["volume_bindings"] = {}
    assert not compile_one(m.GAJJALA, cfg=cfg)["plans"]


def test_failed_flag_cannot_reenter_on_a_simple_bounce_without_new_impulse():
    data = frame(m.GAJJALA, False)
    data.loc[31, ["low", "close"]] = [11.0, 11.1]
    assert not compile_one(m.GAJJALA, data)["plans"]


@pytest.mark.parametrize("model", m.MODEL_IDS)
def test_actual_detail_engine_partial_receipts_and_account_end_to_end(model):
    r = run_one(model)
    assert len(r["compiled"]["plans"]) == 1
    assert len(r["executions"]) == 1
    assert r["executions"][0]["state"] == "CLOSED"
    assert [row["effect"] for row in r["ledger"]] == ["OPEN", "CLOSE", "CLOSE"]
    opening, part, final = r["ledger"]
    assert float(part["qty_base"]) == pytest.approx(float(opening["qty_base"]) * 0.3)
    assert float(final["qty_base"]) == pytest.approx(float(opening["qty_base"]) * 0.7)
    assert len({row["position_episode_id"] for row in r["ledger"]}) == 1
    gross = sum(
        float(row["qty_base"])
        * (float(row["fill_price"]) - float(opening["fill_price"]))
        for row in (part, final)
    )
    fees = sum(float(row["fee_usdt"]) for row in r["ledger"])
    last = r["account"]["valuation"]["curve"][-1]
    assert last["equity_usdt"] == pytest.approx(10000 + gross - fees)
    assert r["full_execution_performed"] is False and r["new_full_runs"] == 0
    assert all(row["execution_evidence"] == "MODEL_NOT_OBSERVED" for row in r["ledger"])


@pytest.mark.parametrize("model", m.MODEL_IDS)
def test_gap_before_scheduled_partial_preserves_unknown_and_no_synthetic_exit(model):
    data = frame(model)
    complete = run_one(model)
    partial_ts = next(
        row["ts_ms"]
        for row in complete["ledger"]
        if str(row["fill_id"]).startswith("partial:")
    )
    details = minute_details(data)
    details = details[details["open_ts_ms"] != partial_ts].copy()
    r = run_one(model, data, details)
    assert r["executions"][0]["state"] == "UNRESOLVED"
    assert not any(str(row["fill_id"]).startswith("partial:") for row in r["ledger"])
    assert r["account_prefix_only"] and not r["complete_account_claim"]
    assert r["executions"][0]["pending_management"] is not None


def test_future_management_bar_cannot_move_stop_or_request_a_partial():
    r = compile_one(m.KELL)
    signal = r["plans"][0]
    b = frame(m.KELL).assign(symbol=SYMBOL).to_dict("records")[-3:]
    position = {
        "signal": signal,
        "side": 1,
        "entry_ts_ms": b[0]["open_ts_ms"],
        "entry_price": 108,
        "stop_price": 100,
    }
    with pytest.raises(ValueError, match="FUTURE"):
        m.management_update(position, b[-2], b, {})
    nofuture = b[:-1]
    future = deepcopy(nofuture)
    future[0]["available_ts_ms"] = future[-1]["available_ts_ms"] + 1
    with pytest.raises(ValueError, match="FUTURE"):
        m.management_update(position, future[-1], future, {})


def test_open_terminal_ownership_is_not_forced_flat_or_zero():
    data = frame(m.KELL).iloc[:-1].copy()
    r = run_one(m.KELL, data)
    assert r["executions"][0]["state"] == "UNRESOLVED"
    assert r["account_prefix_only"]
    assert r["executions"][0]["position"] is not None


def test_genuine_history_and_unknown_provenance_never_enter_fixture_caller():
    data = frame(m.KELL)
    data.attrs["data_kind"] = "GENUINE_RAW_HISTORY"
    with pytest.raises(PermissionError, match="GENUINE_OR_UNDECLARED"):
        run_one(m.KELL, data)


def test_frozen_research_choices_cannot_be_retuned_silently():
    cfg = config(m.KELL)
    cfg["take_profit_r"] = 2
    with pytest.raises(ValueError, match="UNREGISTERED"):
        compile_one(m.KELL, cfg=cfg)


@pytest.mark.parametrize("model", m.MODEL_IDS)
def test_protective_gap_open_precedes_scheduled_partial(model):
    data = frame(model)
    complete = run_one(model)
    partial_ts = next(
        row["ts_ms"]
        for row in complete["ledger"]
        if str(row["fill_id"]).startswith("partial:")
    )
    details = minute_details(data)
    index = details[details["open_ts_ms"] == partial_ts].index[0]
    price = complete["compiled"]["plans"][0]["protective_stop"] * 0.9
    details.loc[index, ["open", "high", "low", "close"]] = [price, price, price, price]
    r = run_one(model, data, details)
    assert r["executions"][0]["state"] == "CLOSED"
    assert not any(str(row["fill_id"]).startswith("partial:") for row in r["ledger"])
    opening, closing = r["ledger"]
    assert float(closing["qty_base"]) == pytest.approx(float(opening["qty_base"]))
    assert float(closing["fill_price"]) == pytest.approx(price)


def test_adverse_entry_gap_cannot_overspend_finite_notional_reservation():
    data = frame(m.KELL)
    plan = compile_one(m.KELL, data)["plans"][0]
    details = minute_details(data)
    index = details[details["open_ts_ms"] == plan["order_active_ts_ms"]].index[0]
    price = plan["reference_entry_price"] * 10
    details.loc[index, ["open", "high", "low", "close"]] = [price, price, price, price]
    r = run_one(m.KELL, data, details)
    assert r["executions"][0]["state"] == "CANCELLED"
    assert not r["ledger"]
    assert r["account"]["valuation"]["curve"][-1]["equity_usdt"] == 10000


@pytest.mark.parametrize("model", m.MODEL_IDS)
@pytest.mark.parametrize("target", ["decision", "detail"])
def test_delayed_clock_cannot_silently_skip_management(model, target):
    data = frame(model)
    details = minute_details(data)
    chosen = data if target == "decision" else details
    chosen["available_ts_ms"] += 2 * m.MINUTE
    with pytest.raises(ValueError, match="BAR_CLOSE_MODEL_CLOCK_REQUIRED"):
        run_one(model, data, details)


@pytest.mark.parametrize("target", ["decision", "detail", "context"])
@pytest.mark.parametrize("location", ["attrs", "row"])
def test_mark_price_cannot_masquerade_as_last_price(target, location):
    data, cfg = frame(m.KELL), config(m.KELL)
    details = minute_details(data)
    chosen = {
        "decision": data,
        "detail": details,
        "context": cfg["context_frames"][SYMBOL],
    }[target]
    if location == "attrs":
        chosen.attrs["price_basis"] = "MARK_PRICE"
    else:
        chosen["source_price_type"] = "mark"
    with pytest.raises(ValueError, match="SOURCE_PRICE_BASIS_CONFLICT"):
        run_one(m.KELL, data, details, cfg)


def test_submission_cannot_spend_capital_freed_after_its_known_time(monkeypatch):
    data = frame(m.KELL)
    first = run_one(m.KELL, data)
    exit_known = first["ledger"][-1]["available_ts_ms"]
    compiled = compile_one(m.KELL, data)
    second = deepcopy(compiled["plans"][0])
    second.update(
        order_active_ts_ms=exit_known,
        order_submit_ts_ms=exit_known - m.MINUTE,
        feature_available_ts_ms=exit_known - m.MINUTE,
        setup_ts_ms=exit_known - 2 * m.MINUTE,
        expires_ts_ms=exit_known + 2 * m.TF,
    )
    compiled["plans"].append(second)
    monkeypatch.setattr(m, "compile_model", lambda *args: compiled)
    result = run_one(m.KELL, data)
    assert len(result["executions"]) == 1
    assert result["ledger"] == first["ledger"]
    assert result["statuses"][-1]["status"] == "BLOCKED_EXISTING_OR_UNKNOWN_OWNERSHIP"
