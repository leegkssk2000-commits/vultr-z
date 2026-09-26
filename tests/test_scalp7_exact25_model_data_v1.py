"""Synthetic on-disk fixtures only; no genuine history or economic execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_model_data_v1 as data

M = 60_000


def rows(count=90, missing=()):
    return pd.DataFrame(
        [
            {
                "timestamp_ms": i * M,
                "open": 100 + i,
                "high": 102 + i,
                "low": 99 + i,
                "close": 101 + i,
                "volume": i + 1,
            }
            for i in range(count)
            if i not in missing
        ]
    )


def artifact(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture(tmp_path, frames=None, tf=30):
    frames = frames or {"BTC-USDT": rows()}
    artifacts = {}
    for symbol, frame in frames.items():
        path = tmp_path / (symbol + ".csv")
        frame.to_csv(path, index=False)
        artifacts[symbol] = artifact(path)
    return {
        "schema": data.SCHEMA,
        "data_kind": "SYNTHETIC_FIXTURE",
        "fixture_label": "SYNTHETIC_UNIT_TEST_ONLY",
        "symbols": list(frames),
        "timeframe_min": tf,
        "minute_artifacts": artifacts,
        "artifacts": list(artifacts.values()),
        "volume_units": "UNKNOWN",
        "synthetic_fill": False,
        "price_basis": "LAST_PRICE",
        "fresh_evidence": False,
        "snapshot_policy": data.SNAPSHOT_POLICY,
        "segment_id_policy": data.SEGMENT_POLICY,
        "availability_basis": "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY",
    }


def test_exact_ohlc_volume_clock_and_unknown_units(tmp_path):
    manifest = fixture(tmp_path)
    result = data.load(manifest, {})
    frame, detail = result["frames"]["BTC-USDT"], result["detail_frames"]["BTC-USDT"]
    assert frame["open_ts_ms"].tolist() == [0, 30 * M, 60 * M]
    assert frame.iloc[0][["open", "high", "low", "close", "volume"]].tolist() == [
        100,
        131,
        99,
        130,
        sum(range(1, 31)),
    ]
    assert frame["available_ts_ms"].equals(frame["close_ts_ms"])
    assert detail["available_ts_ms"].equals(detail["open_ts_ms"] + M)
    assert len(detail) == 90 and frame.attrs["volume_units"] == "UNKNOWN"
    assert frame.attrs["source_rows_are_genuine"] is False
    assert detail.attrs["fresh_evidence"] is False
    assert result["price_snapshots"][-1]["prices"]["BTC-USDT"]["price"] == 190
    assert (
        "SYNTHETIC_FIXTURE:"
        in result["price_snapshots"][-1]["prices"]["BTC-USDT"]["source_ref"]
    )


def test_missing_minute_omits_bucket_resets_segments_and_never_carries_price(tmp_path):
    manifest = fixture(tmp_path, {"BTC-USDT": rows(missing=(59,)), "ETH-USDT": rows()})
    result = data.load(manifest, {"symbols": ["BTC-USDT", "ETH-USDT"]})
    frame = result["frames"]["BTC-USDT"]
    assert frame["open_ts_ms"].tolist() == [0, 60 * M]
    assert frame["canonical_segment_id"].tolist() == [0, 1]
    assert frame["segment_id"].tolist() == ["canonical:0", "canonical:1"]
    assert frame.attrs["incomplete_buckets"] == [30 * M]
    assert len(result["detail_frames"]["BTC-USDT"]) == 89
    assert result["detail_frames"]["BTC-USDT"].iloc[-1]["segment_id"] == "canonical:1"
    snapshot = next(x for x in result["price_snapshots"] if x["ts_ms"] == 60 * M)
    assert snapshot["prices"]["BTC-USDT"]["price"] == 160
    assert snapshot["prices"]["ETH-USDT"]["price"] == 160


def test_all_symbols_missing_snapshot_retains_empty_prices(tmp_path):
    result = data.load(fixture(tmp_path, {"BTC-USDT": rows(missing=(60,))}), {})
    snapshot = next(x for x in result["price_snapshots"] if x["ts_ms"] == 60 * M)
    assert snapshot["prices"] == {}


def test_15m_is_supported_without_new_inferred_candles(tmp_path):
    result = data.load(fixture(tmp_path, tf=15), {})
    assert len(result["frames"]["BTC-USDT"]) == 6
    assert result["frames"]["BTC-USDT"].attrs["timeframe_minutes"] == 15


def test_hash_failure_before_csv_read(tmp_path, monkeypatch):
    manifest = fixture(tmp_path)
    Path(manifest["artifacts"][0]["path"]).write_text("tampered\n")
    monkeypatch.setattr(
        pd, "read_csv", lambda *a, **k: pytest.fail("CSV opened before hash gate")
    )
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        data.load(manifest, {})


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("schema", "bad", "SCHEMA"),
        ("volume_units", "base", "UNIT_UPGRADE"),
        ("synthetic_fill", True, "GAP_FILL"),
        ("price_basis", "MARK_PRICE", "MARK_PRICE"),
        ("symbols", ["BTC-USDT", "BTC-USDT"], "SYMBOLS"),
        ("symbols", ["SPY"], "SYMBOLS"),
        ("timeframe_min", True, "15M_OR_30M"),
        ("timeframe_min", 60, "15M_OR_30M"),
        ("fixture_label", "", "FIXTURE_LABEL"),
        ("fresh_evidence", True, "FRESH_CLAIM"),
        ("availability_basis", "ACTUAL_RECEIPTS", "RECEIPT_CLOCK"),
        ("snapshot_policy", "CLOSE_BEFORE_OPEN", "SNAPSHOT_POLICY"),
        ("segment_id_policy", "COERCE_WITHOUT_BINDING", "SEGMENT_ID_POLICY"),
    ],
)
def test_contract_rejects_false_authority_and_scope(tmp_path, field, value, error):
    manifest = fixture(tmp_path)
    manifest[field] = value
    with pytest.raises(ValueError, match=error):
        data.load(manifest, {})


@pytest.mark.parametrize(
    "change", ["duplicate", "reverse", "fraction", "bad_ohlc", "negative_volume"]
)
def test_invalid_raw_minute_sequence_rejected(tmp_path, change):
    frame = rows()
    if change == "duplicate":
        frame.loc[1, "timestamp_ms"] = 0
    elif change == "reverse":
        frame = frame.iloc[::-1]
    elif change == "fraction":
        frame["timestamp_ms"] = frame["timestamp_ms"].astype(float)
        frame.loc[1, "timestamp_ms"] += 0.5
    elif change == "bad_ohlc":
        frame.loc[1, "high"] = 1
    else:
        frame.loc[1, "volume"] = -1
    with pytest.raises(data.source.SourceDataError):
        data.load(fixture(tmp_path, {"BTC-USDT": frame}), {})


def test_config_cannot_select_different_instrument(tmp_path):
    manifest = fixture(tmp_path)
    with pytest.raises(ValueError, match="CONFIG_SYMBOL"):
        data.load(manifest, {"symbol": "ETH-USDT"})
    with pytest.raises(ValueError, match="CONFIG_UNIVERSE"):
        data.load(manifest, {"symbols": ["BTC-USDT", "ETH-USDT"]})


def test_fixture_file_must_also_be_independently_pinned(tmp_path):
    manifest = fixture(tmp_path, {"BTC-USDT": rows(), "ETH-USDT": rows()})
    manifest["artifacts"] = manifest["artifacts"][1:]
    with pytest.raises(ValueError, match="MISSING_INPUT_ARTIFACT"):
        data.load(manifest, {})


def test_future_price_change_does_not_change_earlier_snapshots(tmp_path):
    frame = rows()
    first = data.load(fixture(tmp_path, {"BTC-USDT": frame}), {})
    frame.loc[frame["timestamp_ms"] >= 60 * M, ["open", "high", "low", "close"]] += 500
    second = data.load(fixture(tmp_path, {"BTC-USDT": frame}), {})
    assert [x["prices"]["BTC-USDT"]["price"] for x in first["price_snapshots"][:2]] == [
        x["prices"]["BTC-USDT"]["price"] for x in second["price_snapshots"][:2]
    ]
    assert (
        first["frames"]["BTC-USDT"]
        .iloc[:2]
        .equals(second["frames"]["BTC-USDT"].iloc[:2])
    )


def test_genuine_inventory_mismatch_stops_before_minute_load(tmp_path, monkeypatch):
    path = tmp_path / "SYNTHETIC_METADATA.json"
    path.write_text("{}\n")
    item = artifact(path)
    monkeypatch.setattr(data, "INVENTORY_SHA256", item["sha256"])
    monkeypatch.setattr(data.source, "_inventory", lambda *a: {"different": "hash"})
    monkeypatch.setattr(
        data.source, "_load_verified_minutes", lambda *a: pytest.fail("minute load")
    )
    with pytest.raises(ValueError, match="INVENTORY_CHANGED"):
        data._genuine(
            {"canonical_root": str(tmp_path), "source_inventory": item},
            {str(path): item["sha256"]},
        )


def test_metadata_builder_never_invokes_price_loader(tmp_path, monkeypatch):
    root, witness = tmp_path / "root", tmp_path / "witness"
    root.mkdir()
    witness.mkdir()
    inventory = tmp_path / "SYNTHETIC_METADATA.json"
    inventory.write_text("{}\n")
    manifest_path = root / "MANIFEST.json"
    manifest_path.write_text("{}\n")
    monkeypatch.setattr(data, "INVENTORY_SHA256", artifact(inventory)["sha256"])
    monkeypatch.setattr(
        data.source,
        "MANIFEST_HASHES",
        {"MANIFEST.json": artifact(manifest_path)["sha256"]},
    )
    monkeypatch.setattr(data.source, "SYMBOLS", ("BTC-USDT",))
    for phase in ("first", "closed"):
        body = witness / (phase + ".body")
        body.write_text("{}\n")
        receipt = {"body_path": body.name, "body_sha256": artifact(body)["sha256"]}
        (witness / f"BTC-USDT_live_1m_{phase}.receipt.json").write_text(
            json.dumps(receipt)
        )
    monkeypatch.setattr(
        data.source, "_load_verified_minutes", lambda *a: pytest.fail("minute load")
    )
    monkeypatch.setattr(
        data.source, "verify_time_witness", lambda *a: pytest.fail("time price load")
    )
    result = data.canonical_manifest(
        canonical_root=root,
        source_inventory_path=inventory,
        time_authority_directory=witness,
        symbols=["BTC-USDT"],
    )
    assert len(result["artifacts"]) == 6
    assert len(result["time_authority"]["files"]) == 4
    assert result["volume_units"] == "UNKNOWN"
    assert result["fresh_evidence"] is False


def test_traversal_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="PATH_ESCAPE"):
        data._within(tmp_path, "../outside")


def test_boundary_mark_uses_post_fill_open_not_stale_prior_close(tmp_path):
    frame = rows()
    frame.loc[30, ["open", "high", "low", "close"]] = [150, 152, 149, 151]
    result = data.load(fixture(tmp_path, {"BTC-USDT": frame}), {})
    snap = next(x for x in result["price_snapshots"] if x["ts_ms"] == 30 * M)
    price = snap["prices"]["BTC-USDT"]
    assert price["price"] == 150 and price["price"] != frame.iloc[29]["close"]
    assert price["price_event_phase"] == "OPEN_AFTER_BOUNDARY_FILLS"
    assert price["price_available_ts_ms"] == 31 * M
    terminal = result["price_snapshots"][-1]["prices"]["BTC-USDT"]
    assert terminal["price_event_phase"] == "TERMINAL_CLOSE_WITHOUT_LATER_OPEN"
    assert terminal["price"] == frame.iloc[-1]["close"]


def test_missing_symbol_grid_open_not_replaced_by_available_preceding_close(tmp_path):
    result = data.load(
        fixture(tmp_path, {"BTC-USDT": rows(missing=(60,)), "ETH-USDT": rows()}), {}
    )
    snap = next(x for x in result["price_snapshots"] if x["ts_ms"] == 60 * M)
    assert "BTC-USDT" not in snap["prices"]
    assert snap["prices"]["ETH-USDT"]["price"] == 160


@pytest.mark.parametrize("model_name", ["CONTROL", "TRAIL"])
def test_file_loader_to_frozen_model_runner_uses_same_causal_prices(
    tmp_path, model_name
):
    from backend.research.rebuild import scalp7_exact25_indicator_models_v1 as model
    from backend.research.rebuild import scalp7_exact25_model_runner_v1 as runner

    bars = [(100, 101, 99, 100)] * 10 + [
        (100, 111, 100, 110),
        (110, 115, 109, 114),
        (114, 114, 108, 111),
        (111, 116, 110, 115),
    ]
    minute_rows = []
    for i, (opened, high, low, closed) in enumerate(bars):
        for j in range(30):
            closing = closed if j == 29 else opened
            minute_rows.append(
                {
                    "timestamp_ms": (i * 30 + j) * M,
                    "open": opened,
                    "high": high if j == 0 else max(opened, closing),
                    "low": low if j == 0 else min(opened, closing),
                    "close": closing,
                    "volume": 1,
                }
            )
    minute_rows.append(
        {
            "timestamp_ms": 420 * M,
            "open": 115,
            "high": 116,
            "low": 107,
            "close": 110,
            "volume": 1,
        }
    )
    manifest = fixture(tmp_path, {"BTC-USDT": pd.DataFrame(minute_rows)})
    manifest["construction_reason"] = (
        "Synthetic file-backed flip/pullback/reclaim then known stop minute"
    )
    manifest["loader"] = {"module": data.__name__, "function": "load"}
    binding = runner.freeze_model(
        model_module=model.__name__,
        model_id=getattr(model, model_name),
        strategy_id="supertrend_pullback",
        baseline_id="SYNTHETIC_CONTROL",
        changed_axis="SYNTHETIC_INTEGRATION_ONLY",
        config=model.CONFIG,
        data_manifest=manifest,
        cost={
            "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
            "per_side_rates": {"BTC-USDT": 0.0001},
            "funding_status": "UNKNOWN_NOT_ZERO",
        },
        windows=[
            {
                "name": "synthetic_validation",
                "kind": "VALIDATION",
                "start_ts_ms": 0,
                "end_ts_ms": 430 * M,
            }
        ],
        initial_cash_usdt=10000,
    )
    inputs = data.load(manifest, model.CONFIG)
    result = runner.run_fixture(
        binding, inputs, expected_binding_sha256=binding["binding_sha256"]
    )
    report = result["cost_scenarios"]["1x"]["windows"][0]
    assert report["T_resolved"] == 1
    assert report["gross_resolved_usdt"] == pytest.approx(-25)
    assert report["net_resolved_reference_usdt"] < -25
    assert (
        result["cost_scenarios"]["2x"]["windows"][0]["net_resolved_reference_usdt"]
        < report["net_resolved_reference_usdt"]
    )
    assert result["full_execution_performed"] is False
    assert result["data_kind"] == "SYNTHETIC_FIXTURE"


def test_multiple_raw_gaps_share_execution_segment_with_complete_decision_bar(tmp_path):
    result = data.load(fixture(tmp_path, {"BTC-USDT": rows(150, missing=(59, 61))}), {})
    frame, detail = result["frames"]["BTC-USDT"], result["detail_frames"]["BTC-USDT"]
    decision = frame.loc[frame.open_ts_ms == 90 * M].iloc[0]
    minute = detail.loc[detail.open_ts_ms == 90 * M].iloc[0]
    assert decision["canonical_segment_id"] == 1
    assert minute["canonical_segment_id"] == 2
    assert (
        decision["execution_segment_number"] == minute["execution_segment_number"] == 2
    )
    assert decision["segment_id"] == minute["segment_id"] == "canonical:2"
    assert len(detail) == 148


@pytest.mark.parametrize("invalid", [True, 1.5, float("nan"), -1, "0"])
def test_execution_segment_adapter_rejects_unsupported_ids(invalid):
    with pytest.raises(ValueError, match="INVALID_CANONICAL_EXECUTION_SEGMENT"):
        data._adapt_segments(pd.DataFrame({"segment_id": [0]}), [invalid])


def expand_bars(values, final_open=None):
    minute_rows = []
    for i, (opened, high, low, closed) in enumerate(values):
        for j in range(30):
            closing = closed if j == 29 else opened
            minute_rows.append(
                {
                    "timestamp_ms": (i * 30 + j) * M,
                    "open": opened,
                    "high": high if j == 0 else max(opened, closing),
                    "low": low if j == 0 else min(opened, closing),
                    "close": closing,
                    "volume": 0,
                }
            )
    if final_open is not None:
        minute_rows.append(
            {
                "timestamp_ms": len(values) * 30 * M,
                "open": final_open,
                "high": final_open,
                "low": final_open,
                "close": final_open,
                "volume": 0,
            }
        )
    return pd.DataFrame(minute_rows)


def run_loaded_fixture(
    manifest,
    module,
    model_id,
    strategy,
    config,
    end,
    *,
    compiler="compile_model",
    execution_mode="DETAIL_CONDITIONAL",
    windows=None,
    initial=10000,
):
    from backend.research.rebuild import scalp7_exact25_model_runner_v1 as runner

    manifest["construction_reason"] = (
        "Explicit synthetic file-to-producer-to-order-to-NAV regression"
    )
    manifest["loader"] = {"module": data.__name__, "function": "load"}
    binding = runner.freeze_model(
        model_module=module.__name__,
        model_id=model_id,
        strategy_id=strategy,
        baseline_id="SYNTHETIC_INPUT_INTEGRATION",
        changed_axis="SYNTHETIC_ONLY",
        config=config,
        data_manifest=manifest,
        cost={
            "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
            "per_side_rates": {s: 0.0001 for s in manifest["symbols"]},
            "funding_status": "UNKNOWN_NOT_ZERO",
        },
        windows=windows
        or [
            {
                "name": "fixture_validation",
                "kind": "VALIDATION",
                "start_ts_ms": 0,
                "end_ts_ms": end,
            }
        ],
        initial_cash_usdt=initial,
        compiler=compiler,
        execution_mode=execution_mode,
    )
    inputs = data.load(manifest, config)
    for symbol, frame in inputs["frames"].items():
        assert frame.attrs["volume_units"] == "UNKNOWN"
        assert (frame.price_type == "last").all()
        assert all(isinstance(value, str) for value in frame.segment_id)
        assert pd.api.types.is_integer_dtype(frame.canonical_segment_id)
        detail = inputs["detail_frames"][symbol]
        mapping = detail.set_index("open_ts_ms").segment_id
        assert frame.segment_id.tolist() == mapping.reindex(frame.open_ts_ms).tolist()
    result = runner.run_fixture(
        binding, inputs, expected_binding_sha256=binding["binding_sha256"]
    )
    assert result["full_execution_performed"] is False
    assert result["data_kind"] == "SYNTHETIC_FIXTURE"
    return result


@pytest.mark.parametrize("model_name", ["SR_CONTROL", "SR"])
def test_file_loader_to_each_sr_model_entry_failure_exit_and_nav(tmp_path, model_name):
    from backend.research.rebuild import scalp7_exact25_reference_models_v1 as model

    bars = [(100, 110, 90, 100)] * 48 + [
        (100, 112, 99, 111),
        (111, 113, 109, 112),
        (112, 113, 107, 108),
    ]
    manifest = fixture(tmp_path, {"BTC-USDT": expand_bars(bars, final_open=108)})
    result = run_loaded_fixture(
        manifest, model, getattr(model, model_name), "sr_levels", {}, 1532 * M
    )
    report = result["cost_scenarios"]["1x"]["windows"][0]
    assert report["T_resolved"] == 1
    assert result["unknown_execution_count"] == 0
    ledger = result["execution"]["ledger"]
    assert [row["effect"] for row in ledger] == ["OPEN", "CLOSE"]
    assert ledger[0]["ts_ms"] == (1470 if model_name == "SR_CONTROL" else 1500) * M
    assert ledger[1]["ts_ms"] == 1530 * M
    assert report["gross_resolved_usdt"] < 0
    assert report["net_resolved_reference_usdt"] < report["gross_resolved_usdt"]
    assert report["DD_pct"] > 0


def test_file_loader_to_noise_six_sleeves_reversal_eod_and_nav(tmp_path):
    from backend.research.rebuild import scalp7_exact25_session_models_v1 as model

    day = 1440 * M
    bars = [(100, 100, 100, 100)] * (15 * 48)
    bars[14 * 48] = (100, 101, 100, 101)
    bars[14 * 48 + 1] = (100, 100, 99, 99)
    minutes = expand_bars(bars, final_open=100)
    symbols = list(model.CANONICAL_SYMBOLS)
    manifest = fixture(tmp_path, {symbol: minutes for symbol in symbols})
    windows = [
        {
            "name": "fixture_context",
            "kind": "CONTEXT",
            "start_ts_ms": 0,
            "end_ts_ms": 14 * day,
        },
        {
            "name": "fixture_validation",
            "kind": "VALIDATION",
            "start_ts_ms": 14 * day,
            "end_ts_ms": 15 * day + 2 * M,
        },
    ]
    result = run_loaded_fixture(
        manifest,
        model,
        model.PORTFOLIO_MODEL_ID,
        "trend_rider",
        model.noise_portfolio_config(symbols),
        15 * day + 2 * M,
        compiler="noise_portfolio_schedule",
        execution_mode="SESSION_TARGET",
        windows=windows,
        initial=60000,
    )
    report = result["cost_scenarios"]["1x"]["windows"][0]
    assert report["T_resolved"] == 12 and report["gross_resolved_usdt"] == 0
    assert report["net_resolved_reference_usdt"] == pytest.approx(-24)
    assert result["cost_scenarios"]["2x"]["windows"][0][
        "net_resolved_reference_usdt"
    ] == pytest.approx(-48)
    assert result["unknown_execution_count"] == 0 and report["complete_window"]
    assert len(result["execution"]["executions"]) == 6
    assert all(
        e["unclosed_position"] is None for e in result["execution"]["executions"]
    )
