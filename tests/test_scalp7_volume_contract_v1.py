"""Synthetic admission, dimensions, field clocks and existing-formula integration."""

import copy
import math

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_volume_contract_v1 as mod

STEP = 900_000
SYMBOL = "TEST-USDT"


def fixture(close=None, *, quote=True):
    close = close or [10.0, 12.0, 11.0, 13.0, 9.0, 12.0, 8.0, 10.0]
    frame = pd.DataFrame(
        {
            "open_ts_ms": [i * STEP for i in range(len(close))],
            "close_ts_ms": [(i + 1) * STEP for i in range(len(close))],
            "available_ts_ms": [(i + 1) * STEP for i in range(len(close))],
            "segment_id": ["a"] * len(close),
            "open": close,
            "high": [x + 2 for x in close],
            "low": [x - 2 for x in close],
            "close": close,
            "source_base": [float(i + 1) for i in range(len(close))],
            "source_base_available_ts_ms": [(i + 1) * STEP for i in range(len(close))],
        }
    )
    binding = {
        "schema": mod.VERSION,
        "venue": "SYNTHETIC",
        "instrument": SYMBOL,
        "product": "SYNTHETIC",
        "base_asset": "TEST",
        "quote_asset": "USDT",
        "price_unit": "USDT",
        "evidence_kind": "SYNTHETIC_TEST_ONLY",
        "source_revision_sha256": "1" * 64,
        "source_schema_sha256": "2" * 64,
        "source_unit_authority_sha256": "3" * 64,
        "source_unit_authority_locator": "Synthetic fixture recipe, no real source",
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
    frame.attrs = {
        "data_kind": "SYNTHETIC_FIXTURE",
        "fixture_label": "SYNTHETIC_UNIT_TEST_ONLY",
        "volume_units": "BASE_AND_QUOTE" if quote else "BASE",
        **{key: value for key, value in binding.items() if key.endswith("_sha256")},
        "volume_field_units": {"source_base": "BASE"},
    }
    if quote:
        frame["source_quote"] = frame["source_base"] * frame["close"]
        frame["source_quote_available_ts_ms"] = frame["close_ts_ms"]
        binding["fields"]["quote"] = {
            "value": "source_quote",
            "available": "source_quote_available_ts_ms",
            "unit": "QUOTE",
            "asset": "USDT",
            "observed": True,
        }
        frame.attrs["volume_field_units"]["source_quote"] = "QUOTE"
    return frame, binding


def config(strategy, **overrides):
    result = {
        "timeframe_min": 15,
        "mode_id": (
            mod.indicators.MODES[strategy][0]
            if strategy in mod.INDICATORS
            else mod.reference.MODES[strategy][0]
        ),
        "price_type": "last",
    }
    if strategy == "bb_revert":
        result.update(
            bb_length=3,
            bb_multiplier=1.0,
            ii_period=1,
            ii_version="ROLLING_NORMALIZED_HLC_VOLUME_V1",
            confirmation="CLOSE_BEYOND_ALERT_EXTREME",
            alert_expiry_bars=3,
            invalidation="ALERT_EXTREME",
        )
    elif strategy == "mfi_rsi_div":
        result.update(oscillator_period=3, pivot_left=1, pivot_right=1)
    elif strategy in mod.VWAPS:
        result.update(
            anchor_event_ts_ms=0,
            anchor_known_ts_ms=STEP,
            anchor_id="fixture",
            volume_basis="BASE_QUOTE_SUMS",
            source_clock="SYNTHETIC_BAR_CLOSE",
            hypothesis_id="SYNTHETIC_VOLUME_ADAPTER_CASE",
            rationale="Synthetic known inputs only; not market/source strategy",
        )
    result.update(overrides)
    return result


def run(strategy, frame, binding, **overrides):
    return mod.evaluate_volume_component(
        strategy, {SYMBOL: frame}, config(strategy, **overrides), {SYMBOL: binding}
    )


@pytest.mark.parametrize("strategy", mod.STRATEGIES)
def test_existing_components_are_reused_after_common_admission(strategy):
    frame, binding = fixture()
    original = frame.copy(deep=True)
    before_binding = copy.deepcopy(binding)
    result = run(strategy, frame, binding)
    assert result["status"] == "COMPONENT_INPUT_ADMITTED_ECONOMICS_NOT_RUN"
    assert result["components"]
    assert result["economic_runs"] == 0
    assert not result["complete_strategy"] and not result["new_full_authority"]
    assert result["order"] == result["live"] == "BLOCKED"
    pd.testing.assert_frame_equal(frame, original)
    assert binding == before_binding


@pytest.mark.parametrize("strategy", mod.STRATEGIES)
def test_unknown_actual_canonical_volume_cannot_be_upgraded_by_config(strategy):
    frame, binding = fixture()
    frame.attrs["data_kind"] = "GENUINE_RAW_HISTORY"
    frame.attrs["volume_units"] = "UNKNOWN"
    binding["evidence_kind"] = "HASH_BOUND_SOURCE_SCHEMA"
    frame["volume"] = frame["source_base"]
    result = run(strategy, frame, binding)
    assert result["status"] == "BLOCKED_VOLUME_INPUT_CONTRACT"
    assert result["per_symbol"][SYMBOL]["error"] == "UNPROVEN_CANONICAL_VOLUME_UNITS"
    assert not result["components"] and not result["intents"]


@pytest.mark.parametrize(
    "key",
    ["source_revision_sha256", "source_schema_sha256", "source_unit_authority_sha256"],
)
def test_binding_must_match_exact_retained_revision_schema_and_unit_authority(key):
    frame, binding = fixture()
    binding[key] = "4" * 64
    with pytest.raises(ValueError, match="EVIDENCE_BINDING_MISMATCH"):
        mod.admit_observed_base_frame(SYMBOL, frame, binding)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("unit", "DIMENSION_MISMATCH"),
        ("asset", "DIMENSION_MISMATCH"),
        ("observed", "SYNTHESIZED_VOLUME_FORBIDDEN"),
        ("units_attr", "SOURCE_FIELD_UNIT_BINDING_MISMATCH"),
        ("clock", "PREMATURE_BASE"),
        ("negative", "NEGATIVE"),
        ("nan", "INVALID_VOLUME_VALUE"),
        ("mixed", "MIXED_SOURCE_VOLUME_UNITS"),
        ("label", "MIXED_SOURCE_VOLUME_UNITS"),
    ],
)
def test_dimensions_observation_and_row_clocks_are_not_assumed(mutation, error):
    frame, binding = fixture()
    field = binding["fields"]["base"]
    if mutation == "unit":
        field["unit"] = "QUOTE"
    elif mutation == "asset":
        field["asset"] = "USDT"
    elif mutation == "observed":
        field["observed"] = False
    elif mutation == "units_attr":
        frame.attrs["volume_field_units"]["source_base"] = "UNKNOWN"
    elif mutation == "clock":
        frame.loc[1, "source_base_available_ts_ms"] = STEP
    elif mutation == "negative":
        frame.loc[1, "source_base"] = -1
    elif mutation == "nan":
        frame.loc[1, "source_base"] = math.nan
    elif mutation == "mixed":
        frame["volume_unit"] = ["base", "quote"] + ["base"] * (len(frame) - 2)
    else:
        field["unit_field"] = "raw_unit"
        frame["raw_unit"] = "BASE"
        frame.loc[2, "raw_unit"] = "QUOTE"
    with pytest.raises(ValueError, match=error):
        mod.admit_observed_base_frame(SYMBOL, frame, binding)


def test_true_avwap_requires_observed_quote_and_does_not_synthesize_it():
    frame, binding = fixture(quote=False)
    frame["volume_quote"] = frame["source_base"] * frame["close"]
    result = run("anchor_vwap_trend", frame, binding)
    assert not result["components"]
    assert result["per_symbol"][SYMBOL]["error"] == "MISSING_OBSERVED_QUOTE_VOLUME"
    proxy = run("anchor_vwap_trend", frame, binding, volume_basis="HLC3_BASE_PROXY")
    assert proxy["components"]
    assert all(not row["trade_vwap_claim"] for row in proxy["components"])
    adapted = mod.adapt_volume_frame(
        SYMBOL, frame, binding, "anchor_vwap_trend", volume_basis="HLC3_BASE_PROXY"
    )
    assert "volume_quote" not in adapted
    assert not adapted.attrs["volume_fields_synthesized"]


def test_observed_avwap_hand_arithmetic_differs_from_disclosed_hlc3_proxy():
    frame, binding = fixture()
    frame.loc[0, ["source_base", "source_quote"]] = [1.0, 9.0]
    frame.loc[1, ["source_base", "source_quote"]] = [3.0, 33.0]
    true = run("anchor_vwap_trend", frame, binding)["components"]
    proxy = run("anchor_vwap_trend", frame, binding, volume_basis="HLC3_BASE_PROXY")[
        "components"
    ]
    assert true[1]["value"] == pytest.approx(42 / 4)
    assert proxy[1]["value"] == pytest.approx(46 / 4)
    assert true[1]["trade_vwap_claim"] and not proxy[1]["trade_vwap_claim"]


def test_quote_cannot_alias_base_column_or_use_wrong_currency():
    frame, binding = fixture()
    binding["fields"]["quote"]["value"] = "source_base"
    with pytest.raises(ValueError, match="FIELD_ALIAS_FORBIDDEN"):
        mod.adapt_volume_frame(
            SYMBOL, frame, binding, "anchor_vwap_trend", volume_basis="BASE_QUOTE_SUMS"
        )
    binding["fields"]["quote"]["value"] = "source_quote"
    binding["fields"]["quote"]["asset"] = "BTC"
    with pytest.raises(ValueError, match="DIMENSION_MISMATCH"):
        mod.adapt_volume_frame(
            SYMBOL, frame, binding, "anchor_vwap_trend", volume_basis="BASE_QUOTE_SUMS"
        )


@pytest.mark.parametrize("strategy", mod.STRATEGIES)
def test_required_volume_delivery_delays_all_dependent_components(strategy):
    frame, binding = fixture()
    field = (
        "source_quote_available_ts_ms"
        if strategy in mod.VWAPS
        else "source_base_available_ts_ms"
    )
    frame.loc[1, field] = 10 * STEP
    result = run(strategy, frame, binding)
    components = result["components"]
    assert components
    assert (
        all(
            row["available_ts_ms"] >= 10 * STEP
            for row in components
            if row.get("bar_open_ts_ms", row.get("anchor_event_ts_ms", 0)) >= STEP
        )
        if strategy not in mod.VWAPS
        else all(row["available_ts_ms"] >= 10 * STEP for row in components[1:])
    )
    adapted = mod.adapt_volume_frame(
        SYMBOL,
        frame,
        binding,
        strategy,
        volume_basis="BASE_QUOTE_SUMS" if strategy in mod.VWAPS else None,
    )
    assert list(adapted["available_ts_ms"])[1:] == [10 * STEP] * (len(frame) - 1)


def test_unrequired_quote_clock_does_not_delay_base_components():
    frame, binding = fixture()
    frame.loc[0, "source_quote_available_ts_ms"] = 99 * STEP
    result = run("obv_trend", frame, binding)
    assert result["components"][0]["available_ts_ms"] == STEP


def test_base_obv_hand_arithmetic_and_physical_gap_reset():
    frame, binding = fixture([10.0, 11.0, 11.0, 9.0])
    frame["source_base"] = [5.0, 7.0, 100.0, 4.0]
    assert [x["obv"] for x in run("obv_trend", frame, binding)["components"]] == [
        0.0,
        7.0,
        7.0,
        3.0,
    ]
    frame.loc[
        2:,
        ["open_ts_ms", "close_ts_ms", "available_ts_ms", "source_base_available_ts_ms"],
    ] += STEP
    result = run("obv_trend", frame, binding)
    assert [x["obv"] for x in result["components"]] == [0.0, 7.0, 0.0, -4.0]


def test_avwap_does_not_bridge_missing_prices_with_volume_clock_repair():
    frame, binding = fixture()
    clock_fields = [
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "source_base_available_ts_ms",
        "source_quote_available_ts_ms",
    ]
    frame.loc[2:, clock_fields] += STEP
    result = run("anchor_vwap_trend", frame, binding)
    assert len(result["components"]) == 2
    assert any(x["event"] == "ANCHOR_CUMULATION_GAP_BLOCKED" for x in result["events"])


@pytest.mark.parametrize("strategy", mod.STRATEGIES)
def test_prefix_causality_and_future_field_mutation(strategy):
    frame, binding = fixture([100 + math.sin(i / 2) * 5 for i in range(80)])
    prefix = run(strategy, frame.iloc[:50], binding)
    full = run(strategy, frame, binding)
    mutated = frame.copy(deep=True)
    mutated.loc[50:, ["open", "high", "low", "close"]] *= 2
    mutated.loc[50:, "source_base"] *= 2
    mutated.loc[50:, "source_quote"] *= 4
    future = run(strategy, mutated, binding)
    for key in ("components", "events", "intents"):
        assert prefix[key] == [
            x for x in full[key] if x["available_ts_ms"] <= 50 * STEP
        ]
        assert prefix[key] == [
            x for x in future[key] if x["available_ts_ms"] <= 50 * STEP
        ]


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"volume_unit": "quote"}, "CALLER_VOLUME_UNIT_CONFLICT"),
        ({"price_type": "mark"}, "CALLER_PRICE_TYPE_CONFLICT"),
    ],
)
def test_caller_conflicting_dimension_or_price_cannot_be_silently_rewritten(
    overrides, error
):
    frame, binding = fixture()
    result = run("obv_trend", frame, binding, **overrides)
    assert result["per_symbol"][SYMBOL]["error"] == error
    assert not result["components"]


def test_missing_binding_block_does_not_prevent_independent_valid_symbol():
    frame, binding = fixture()
    result = mod.evaluate_volume_component(
        "obv_trend",
        {SYMBOL: frame, "OTHER-USDT": frame},
        config("obv_trend"),
        {SYMBOL: binding},
    )
    assert result["status"] == "MIXED_COMPONENT_AND_BLOCKED_INPUT"
    assert result["components"] and not result["per_symbol"]["OTHER-USDT"]["components"]


@pytest.mark.parametrize("source", ["row", "attrs", "basis", "binding"])
def test_explicit_source_mark_price_cannot_be_relabelled_as_last(source):
    frame, binding = fixture()
    if source == "row":
        frame["price_type"] = "mark"
    elif source == "attrs":
        frame.attrs["price_type"] = "mark"
    elif source == "basis":
        frame.attrs["price_basis"] = "MARK_PRICE"
    else:
        binding["price_type"] = "mark"
    result = run("obv_trend", frame, binding)
    assert result["status"] == "BLOCKED_VOLUME_INPUT_CONTRACT"
    assert "SOURCE_PRICE_" in result["per_symbol"][SYMBOL]["error"]
    assert not result["components"]


def symbol_fixture(symbol, *, quote=True):
    frame, binding = fixture(quote=quote)
    binding["instrument"] = symbol
    binding["base_asset"] = symbol.removesuffix("-USDT")
    binding["fields"]["base"]["asset"] = binding["base_asset"]
    return frame, binding


@pytest.mark.parametrize("strategy", mod.VWAPS)
def test_per_symbol_only_heterogeneous_bases_reach_frozen_components(strategy):
    true_symbol, proxy_symbol = "QUOTE-USDT", "PROXY-USDT"
    true_frame, true_binding = symbol_fixture(true_symbol)
    proxy_frame, proxy_binding = symbol_fixture(proxy_symbol, quote=False)
    true_frame.loc[:1, "source_base"] = [1.0, 3.0]
    true_frame.loc[:1, "source_quote"] = [9.0, 33.0]
    proxy_frame.loc[:1, "source_base"] = [1.0, 3.0]
    proxy_frame["volume_quote"] = 999999.0  # Not an observed quote field.
    true_frame.loc[1, "source_quote_available_ts_ms"] = 10 * STEP
    renames = {
        name: name.replace("source_", "quote_symbol_")
        for name in true_frame.columns
        if name.startswith("source_")
    }
    true_frame.rename(columns=renames, inplace=True)
    for field in true_binding["fields"].values():
        field["value"] = renames[field["value"]]
        field["available"] = renames[field["available"]]
    true_frame.attrs["volume_field_units"] = {
        renames[name]: unit
        for name, unit in true_frame.attrs["volume_field_units"].items()
    }
    inputs = {true_symbol: true_frame, proxy_symbol: proxy_frame}
    before = {symbol: frame.copy(deep=True) for symbol, frame in inputs.items()}
    bindings = {true_symbol: true_binding, proxy_symbol: proxy_binding}
    settings = config(strategy)
    settings.pop("volume_basis")
    settings["symbol_configs"] = {
        true_symbol: {"volume_basis": "BASE_QUOTE_SUMS"},
        proxy_symbol: {"volume_basis": "HLC3_BASE_PROXY"},
    }
    before_config = copy.deepcopy(settings)
    result = mod.evaluate_volume_component(strategy, inputs, settings, bindings)
    assert result["status"] == "COMPONENT_INPUT_ADMITTED_ECONOMICS_NOT_RUN"
    true = result["per_symbol"][true_symbol]["components"]
    proxy = result["per_symbol"][proxy_symbol]["components"]
    assert true[1]["value"] == pytest.approx(42 / 4)
    assert proxy[1]["value"] == pytest.approx(46 / 4)
    assert true[1]["available_ts_ms"] == 10 * STEP
    assert proxy[1]["available_ts_ms"] == 2 * STEP
    assert all(row["trade_vwap_claim"] for row in true)
    assert all(not row["trade_vwap_claim"] for row in proxy)
    assert {row["symbol"] for row in true} == {true_symbol}
    assert {row["symbol"] for row in proxy} == {proxy_symbol}
    assert result["requirements"]["volume_basis"] == "PER_SYMBOL"
    assert result["per_symbol_requirements"][true_symbol][
        "required_observed_units"
    ] == ["BASE", "QUOTE"]
    assert result["per_symbol_requirements"][proxy_symbol][
        "required_observed_units"
    ] == ["BASE"]
    assert result["economic_runs"] == 0 and not result["new_full_authority"]
    assert settings == before_config
    for symbol, frame in inputs.items():
        pd.testing.assert_frame_equal(frame, before[symbol])


@pytest.mark.parametrize("strategy", mod.VWAPS)
@pytest.mark.parametrize("default_basis", ["BASE_QUOTE_SUMS", "HLC3_BASE_PROXY"])
def test_top_level_basis_is_default_and_symbol_override_wins(strategy, default_basis):
    default_symbol, override_symbol = "DEFAULT-USDT", "OVERRIDE-USDT"
    alternate = (
        "HLC3_BASE_PROXY" if default_basis == "BASE_QUOTE_SUMS" else "BASE_QUOTE_SUMS"
    )
    frames, bindings = {}, {}
    for symbol, basis in (
        (default_symbol, default_basis),
        (override_symbol, alternate),
    ):
        frames[symbol], bindings[symbol] = symbol_fixture(
            symbol, quote=basis == "BASE_QUOTE_SUMS"
        )
    settings = config(
        strategy,
        volume_basis=default_basis,
        symbol_configs={override_symbol: {"volume_basis": alternate}},
    )
    result = mod.evaluate_volume_component(strategy, frames, settings, bindings)
    assert result["status"] == "COMPONENT_INPUT_ADMITTED_ECONOMICS_NOT_RUN"
    for symbol, basis in (
        (default_symbol, default_basis),
        (override_symbol, alternate),
    ):
        own = result["per_symbol"][symbol]
        assert own["components"]
        assert all(
            row["trade_vwap_claim"] == (basis == "BASE_QUOTE_SUMS")
            for row in own["components"]
        )
        assert result["per_symbol_requirements"][symbol]["volume_basis"] == basis


@pytest.mark.parametrize("strategy", mod.VWAPS)
@pytest.mark.parametrize(
    "failure,error",
    [
        ("quote_absent", "MISSING_OBSERVED_QUOTE_VOLUME"),
        ("unknown_unit", "UNPROVEN_CANONICAL_VOLUME_UNITS"),
        ("missing_basis", "EXPLICIT_VOLUME_BASIS_REQUIRED"),
    ],
)
def test_per_symbol_basis_failures_cannot_borrow_other_symbol_authority(
    strategy, failure, error
):
    good, bad = "GOOD-USDT", "BAD-USDT"
    good_frame, good_binding = symbol_fixture(good, quote=False)
    bad_frame, bad_binding = symbol_fixture(bad, quote=False)
    bad_frame["volume_quote"] = bad_frame["source_base"] * bad_frame["close"]
    if failure == "unknown_unit":
        bad_frame.attrs["volume_units"] = "UNKNOWN"
    settings = config(strategy)
    settings.pop("volume_basis")
    settings["symbol_configs"] = {good: {"volume_basis": "HLC3_BASE_PROXY"}}
    if failure != "missing_basis":
        settings["symbol_configs"][bad] = {"volume_basis": "BASE_QUOTE_SUMS"}
    result = mod.evaluate_volume_component(
        strategy,
        {good: good_frame, bad: bad_frame},
        settings,
        {good: good_binding, bad: bad_binding},
    )
    assert result["status"] == "MIXED_COMPONENT_AND_BLOCKED_INPUT"
    assert result["per_symbol"][good]["components"]
    assert result["per_symbol"][bad]["status"] == "BLOCKED_VOLUME_INPUT_CONTRACT"
    assert result["per_symbol"][bad]["error"] == error
    assert not result["per_symbol"][bad]["components"]
    assert not result["per_symbol"][bad]["intents"]
    assert {row["symbol"] for row in result["components"]} == {good}
    assert all(not row["trade_vwap_claim"] for row in result["components"])
    assert result["per_symbol_requirements"][good]["volume_basis"] == "HLC3_BASE_PROXY"
    if failure == "missing_basis":
        assert result["per_symbol_requirements"][bad] is None
