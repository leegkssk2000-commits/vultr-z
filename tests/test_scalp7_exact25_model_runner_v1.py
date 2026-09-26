"""Synthetic complete-model integration and pre-loader budget boundary checks."""

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_indicator_models_v1 as indicator
from backend.research.rebuild import scalp7_exact25_model_runner_v1 as runner
from backend.research.rebuild.economic7_campaign_registry_v1 import (
    CampaignLedger,
    CandidateIdentity,
)

MODULE = indicator.__name__
MINUTE = 60000
TF = 30 * MINUTE


def raw_inputs(*, gap=False, missing_activation=False):
    prices = [(100, 101, 99, 100)] * 10 + [
        (100, 111, 100, 110),
        (110, 115, 109, 114),
        (114, 114, 108, 111),
        (111, 116, 110, 115),
    ]
    frames = pd.DataFrame(
        [
            dict(
                open_ts_ms=i * TF,
                close_ts_ms=(i + 1) * TF,
                available_ts_ms=(i + 1) * TF,
                segment_id="fixture",
                open=o,
                high=h,
                low=low,
                close=c,
            )
            for i, (o, h, low, c) in enumerate(prices)
        ]
    )
    minutes = [
        dict(
            open_ts_ms=i * MINUTE,
            close_ts_ms=(i + 1) * MINUTE,
            available_ts_ms=(i + 1) * MINUTE,
            segment_id="fixture",
            open=100,
            high=101,
            low=99,
            close=100,
        )
        for i in range(420)
    ]
    minutes.append(
        dict(
            open_ts_ms=420 * MINUTE,
            close_ts_ms=421 * MINUTE,
            available_ts_ms=421 * MINUTE,
            segment_id="fixture",
            open=115,
            high=116,
            low=114 if gap else 107,
            close=115 if gap else 110,
        )
    )
    if gap:
        minutes.append(
            dict(
                open_ts_ms=422 * MINUTE,
                close_ts_ms=423 * MINUTE,
                available_ts_ms=423 * MINUTE,
                segment_id="after-gap",
                open=115,
                high=116,
                low=114,
                close=115,
            )
        )
    if missing_activation:
        minutes[-1]["open_ts_ms"] += MINUTE
        minutes[-1]["close_ts_ms"] += MINUTE
        minutes[-1]["available_ts_ms"] += MINUTE
    last = minutes[-1]["close_ts_ms"]
    return {
        "frames": {"X": frames},
        "detail_frames": {"X": pd.DataFrame(minutes)},
        "price_snapshots": [
            {"ts_ms": 0, "prices": {}},
            {
                "ts_ms": last,
                "prices": {
                    "X": {
                        "ts_ms": last,
                        "price": minutes[-1]["close"],
                        "price_basis": "LAST_PRICE",
                        "source_ref": "synthetic",
                    }
                },
            },
        ],
    }


def freeze(*, genuine=False, windows=None):
    return runner.freeze_model(
        model_module=MODULE,
        model_id=indicator.CONTROL,
        strategy_id="supertrend_pullback",
        baseline_id="synthetic-control",
        changed_axis="STRUCTURAL_CONTROL",
        config=indicator.CONFIG,
        data_manifest={
            "data_kind": "GENUINE_RAW_HISTORY" if genuine else "SYNTHETIC_FIXTURE",
            "symbols": ["X"],
            "construction_reason": "Raw flip-pullback-reclaim plus known stop minute",
        },
        cost={
            "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
            "per_side_rates": {"X": 0.0001},
            "funding_status": "UNKNOWN_NOT_ZERO",
        },
        windows=windows
        or [
            {
                "name": "validation",
                "kind": "VALIDATION",
                "start_ts_ms": 0,
                "end_ts_ms": 430 * MINUTE,
            }
        ],
        initial_cash_usdt=10000,
    )


def test_actual_raw_producer_order_fill_account_and_cost_stress():
    binding = freeze()
    result = runner.run_fixture(
        binding, raw_inputs(), expected_binding_sha256=binding["binding_sha256"]
    )
    base = result["cost_scenarios"]["1x"]["windows"][0]
    stress = result["cost_scenarios"]["2x"]["windows"][0]
    assert base["T_resolved"] == 1 and base["WR_resolved_pct"] == 0
    assert base["gross_resolved_usdt"] == pytest.approx(-25)
    assert (
        stress["net_resolved_reference_usdt"]
        < base["net_resolved_reference_usdt"]
        < -25
    )
    assert base["DD_pct"] > 0
    assert base["actual_historical_net_usdt"] is None
    assert result["unknown_execution_count"] == 0
    assert result["full_execution_performed"] is False
    assert result["authority"]["live"] == "BLOCKED"
    assert len(result["execution"]["ledger"]) == 2


def test_gap_preserves_unknown_ownership_and_withholds_complete_net():
    binding = freeze()
    result = runner.run_fixture(
        binding, raw_inputs(gap=True), expected_binding_sha256=binding["binding_sha256"]
    )
    window = result["cost_scenarios"]["1x"]["windows"][0]
    assert result["unknown_execution_count"] == 1
    assert window["net_complete_reference_usdt"] is None
    assert window["cross_boundary_or_open_count"] == 1
    assert len(result["execution"]["ledger"]) == 1


def test_missing_activation_is_not_replayed_at_later_open():
    binding = freeze()
    result = runner.run_fixture(
        binding,
        raw_inputs(missing_activation=True),
        expected_binding_sha256=binding["binding_sha256"],
    )
    assert result["unknown_execution_count"] == 1
    assert result["execution"]["ledger"] == []


def test_real_history_cannot_enter_fixture_path():
    binding = freeze(genuine=True)
    with pytest.raises(PermissionError, match="PREEXISTING"):
        runner.run_fixture(
            binding, raw_inputs(), expected_binding_sha256=binding["binding_sha256"]
        )


def test_missing_budget_fails_before_any_data_or_producer(tmp_path, monkeypatch):
    binding = freeze(genuine=True)
    called = []
    monkeypatch.setattr(runner, "verify_binding", lambda *a: called.append("producer"))
    with pytest.raises(PermissionError, match="ALLOCATION_ABSENT"):
        runner.run_authorized(
            binding,
            expected_binding_sha256=binding["binding_sha256"],
            registry_path=tmp_path / "absent.sqlite",
            scope="new",
            owner="Work",
            output_path=tmp_path / "result.json",
        )
    assert called == []
    assert not (tmp_path / "absent.sqlite").exists()


def allocated(tmp_path, binding, *, budget=1, approved=True):
    path = tmp_path / "registry.sqlite"
    ledger = CampaignLedger(path)
    ledger.create_scope(
        "fixture-scope",
        "Work",
        1,
        budget,
        {
            "approval_ref": "SYNTHETIC_TEST_NOT_USER_AUTHORITY",
            "new_full_authorized": approved,
        },
    )
    identity = CandidateIdentity(**binding["candidate_identity"])
    ledger.reserve("fixture-scope", "Work", identity)
    return path, ledger, identity


def test_admission_requires_exact_reserved_identity_and_explicit_approval(tmp_path):
    binding = freeze(genuine=True)
    path, _, _ = allocated(tmp_path, binding, approved=False)
    with pytest.raises(PermissionError, match="APPROVAL_RECEIPT"):
        runner.admission(
            binding, registry_path=path, scope="fixture-scope", owner="Work"
        )


def test_spent_budget_and_existing_execution_cannot_be_replayed(tmp_path):
    binding = freeze(genuine=True)
    path, ledger, identity = allocated(tmp_path, binding)
    assert runner.admission(
        binding, registry_path=path, scope="fixture-scope", owner="Work"
    )
    assert ledger.start(identity.key, "Work")
    ledger.finish(identity.key, "Work", "COMPLETED", {"synthetic": True})
    with pytest.raises(PermissionError, match="RECOVERED_NOT_REPEATED"):
        runner.admission(
            binding, registry_path=path, scope="fixture-scope", owner="Work"
        )


def test_zero_execution_allocation_is_not_permission(tmp_path):
    binding = freeze(genuine=True)
    path, _, _ = allocated(tmp_path, binding, budget=0)
    with pytest.raises(PermissionError, match="BUDGET_EXHAUSTED"):
        runner.admission(
            binding, registry_path=path, scope="fixture-scope", owner="Work"
        )


def test_binding_catches_config_tamper_before_producer():
    binding = freeze()
    expected = binding["binding_sha256"]
    binding["config"]["timeframe_min"] = 15
    with pytest.raises(ValueError, match="PINNED_BINDING"):
        runner.run_fixture(binding, raw_inputs(), expected_binding_sha256=expected)


def test_future_rolling_unknown_does_not_poison_resolved_validation():
    binding = freeze(
        windows=[
            {
                "name": "validation",
                "kind": "VALIDATION",
                "start_ts_ms": 0,
                "end_ts_ms": 100 * MINUTE,
            },
            {
                "name": "rolling",
                "kind": "ROLLING",
                "start_ts_ms": 100 * MINUTE,
                "end_ts_ms": 200 * MINUTE,
            },
        ]
    )
    execution = {
        "ledger": [],
        "executions": [
            {
                "state": "UNRESOLVED",
                "unresolved_from_ts_ms": 150 * MINUTE,
                "unresolved_observed_ts_ms": 151 * MINUTE,
            }
        ],
        "statuses": [],
    }
    result = runner.summarize(execution, binding, {"price_snapshots": []})
    validation, rolling = result["cost_scenarios"]["1x"]["windows"]
    assert validation["complete_window"]
    assert not rolling["complete_window"]


@pytest.mark.parametrize(
    "bad",
    [
        [
            {
                "name": "a",
                "kind": "VALIDATION",
                "start_ts_ms": 0,
                "end_ts_ms": 2 * MINUTE,
            },
            {
                "name": "b",
                "kind": "ROLLING",
                "start_ts_ms": MINUTE,
                "end_ts_ms": 3 * MINUTE,
            },
        ],
        [
            {
                "name": "a",
                "kind": "VALIDATION",
                "start_ts_ms": 1,
                "end_ts_ms": 2 * MINUTE,
            }
        ],
    ],
)
def test_window_boundaries_cannot_mix(bad):
    with pytest.raises(ValueError, match="WINDOW"):
        freeze(windows=bad)


def test_transitive_closure_binds_source_engine_account_and_registry():
    binding = freeze()
    names = list(binding["code_closure"])
    for expected in (
        "scalp7_exact25_execution_v1.py",
        "scalp7_exact25_indicators_v1.py",
        "scalp7_implementation_contract_v1.py",
        "economic7_campaign_registry_v1.py",
    ):
        assert any(name.endswith(expected) for name in names)
    assert all(not name.startswith("/") for name in names)


def test_actual_entry_gap_does_not_increase_reserved_risk():
    inputs = raw_inputs()
    detail = inputs["detail_frames"]["X"]
    detail.loc[detail.index[-1], ["open", "high", "low", "close"]] = [
        116,
        117,
        114,
        116,
    ]
    binding = freeze()
    result = runner.run_fixture(
        binding, inputs, expected_binding_sha256=binding["binding_sha256"]
    )
    assert result["execution"]["ledger"] == []
    assert result["execution"]["executions"][0]["state"] == "CANCELLED"


def test_funding_unknown_cannot_be_silently_changed_to_zero():
    binding = freeze()
    kwargs = {
        k: binding[k]
        for k in (
            "model_module",
            "model_id",
            "strategy_id",
            "baseline_id",
            "changed_axis",
            "config",
            "data_manifest",
            "cost",
            "windows",
            "initial_cash_usdt",
        )
    }
    kwargs["cost"] = {**kwargs["cost"], "funding_status": "ZERO"}
    with pytest.raises(ValueError, match="UNCERTAINTY"):
        runner.freeze_model(**kwargs)


def test_identity_payload_cannot_reuse_reservation_after_rehash():
    binding = freeze()
    binding["windows"][0]["end_ts_ms"] += MINUTE
    binding["binding_sha256"] = runner.digest(
        {k: v for k, v in binding.items() if k != "binding_sha256"}
    )
    with pytest.raises(ValueError, match="IDENTITY_PAYLOAD"):
        runner.verify_binding(binding, binding["binding_sha256"])


def test_noise_six_sleeves_actual_producer_decisions_fills_and_eod():
    from backend.research.rebuild import scalp7_exact25_session_models_v1 as noise

    symbols = noise.CANONICAL_SYMBOLS
    source, detail = [], []
    for i in range(15 * 48):
        stamp = i * TF
        close = 101 if i == 14 * 48 else 99 if i == 14 * 48 + 1 else 100
        source.append(
            dict(
                open_ts_ms=stamp,
                close_ts_ms=stamp + TF,
                available_ts_ms=stamp + TF,
                segment_id="fixture",
                open=100,
                high=max(100, close),
                low=min(100, close),
                close=close,
                volume=0,
            )
        )
        for minute in range(30):
            opened = stamp + minute * MINUTE
            value = close if minute == 29 else 100
            detail.append(
                dict(
                    open_ts_ms=opened,
                    close_ts_ms=opened + MINUTE,
                    available_ts_ms=opened + MINUTE,
                    segment_id="fixture",
                    open=100,
                    high=max(100, value),
                    low=min(100, value),
                    close=value,
                )
            )
    end = 15 * 86400000
    detail.append(
        dict(
            open_ts_ms=end,
            close_ts_ms=end + MINUTE,
            available_ts_ms=end + MINUTE,
            segment_id="fixture",
            open=100,
            high=100,
            low=100,
            close=100,
        )
    )
    inputs = {
        "frames": {s: pd.DataFrame(source) for s in symbols},
        "detail_frames": {s: pd.DataFrame(detail) for s in symbols},
        "price_snapshots": [
            {"ts_ms": 0, "prices": {}},
            {
                "ts_ms": end + MINUTE,
                "prices": {
                    s: {
                        "ts_ms": end + MINUTE,
                        "price": 100,
                        "price_basis": "LAST_PRICE",
                        "source_ref": "synthetic",
                    }
                    for s in symbols
                },
            },
        ],
    }
    config = noise.noise_portfolio_config(symbols)
    binding = runner.freeze_model(
        model_module=noise.__name__,
        model_id=noise.MODEL_ID,
        strategy_id="break_and_continue",
        baseline_id="declared-source-adaptation",
        changed_axis="SOURCE_COMPLETE_BASELINE",
        config=config,
        data_manifest={
            "data_kind": "SYNTHETIC_FIXTURE",
            "construction_reason": "Six identical independently funded sleeves",
        },
        cost={
            "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
            "per_side_rates": {s: 0.0001 * (i + 1) for i, s in enumerate(symbols)},
            "funding_status": "UNKNOWN_NOT_ZERO",
        },
        windows=[
            {
                "name": "context",
                "kind": "CONTEXT",
                "start_ts_ms": 0,
                "end_ts_ms": 14 * 86400000,
            },
            {
                "name": "validation",
                "kind": "VALIDATION",
                "start_ts_ms": 14 * 86400000,
                "end_ts_ms": end + 2 * MINUTE,
            },
        ],
        initial_cash_usdt=60000,
        compiler="noise_portfolio_schedule",
        execution_mode="SESSION_TARGET",
    )
    result = runner.run_fixture(
        binding, inputs, expected_binding_sha256=binding["binding_sha256"]
    )
    assert result["unknown_execution_count"] == 0
    one = result["cost_scenarios"]["1x"]["windows"][0]
    two = result["cost_scenarios"]["2x"]["windows"][0]
    assert one["T_resolved"] == 12
    assert one["gross_resolved_usdt"] == 0
    assert two["net_resolved_reference_usdt"] == pytest.approx(
        2 * one["net_resolved_reference_usdt"]
    )
    assert one["complete_window"]
    assert len(result["execution"]["executions"]) == 6
    assert all(
        e["unclosed_position"] is None for e in result["execution"]["executions"]
    )


def genuine_fixture_binding(tmp_path, monkeypatch):
    from backend.research.rebuild import scalp7_exact25_model_data_v1 as data

    def synthetic_loader(manifest, config):
        assert manifest["test_only"] is True
        return raw_inputs()

    monkeypatch.setattr(data, "load", synthetic_loader)
    artifact = tmp_path / "synthetic-source.txt"
    artifact.write_text("Synthetic loader test. No genuine market records.")
    binding = freeze(genuine=True)
    kwargs = {
        k: binding[k]
        for k in (
            "model_module",
            "model_id",
            "strategy_id",
            "baseline_id",
            "changed_axis",
            "config",
            "data_manifest",
            "cost",
            "windows",
            "initial_cash_usdt",
        )
    }
    kwargs["data_manifest"] = {
        "data_kind": "GENUINE_RAW_HISTORY",
        "symbols": ["X"],
        "test_only": True,
        "artifacts": [{"path": str(artifact), "sha256": runner._sha(artifact)}],
        "loader": {"module": data.__name__, "function": "load"},
    }
    return runner.freeze_model(**kwargs), artifact


def test_authorized_boundary_atomically_saves_result_before_completed_receipt(
    tmp_path, monkeypatch
):
    binding, _ = genuine_fixture_binding(tmp_path, monkeypatch)
    path, ledger, _ = allocated(tmp_path, binding)
    output = tmp_path / "result.json"
    result = runner.run_authorized(
        binding,
        expected_binding_sha256=binding["binding_sha256"],
        registry_path=path,
        scope="fixture-scope",
        owner="Work",
        output_path=output,
    )
    assert output.is_file() and result["full_execution_performed"]
    import sqlite3
    import json

    with sqlite3.connect(path) as db:
        state, receipt_json = db.execute(
            "SELECT state, result_json FROM claims"
        ).fetchone()
        assert state == "COMPLETED"
        receipt = json.loads(receipt_json)
    assert receipt["result_file_sha256"] == runner._sha(output)
    assert receipt["result_path"] == str(output)
    assert not output.with_suffix(".json.partial").exists()


def test_changed_input_fails_before_budget_start_or_loader(tmp_path, monkeypatch):
    binding, artifact = genuine_fixture_binding(tmp_path, monkeypatch)
    path, _, _ = allocated(tmp_path, binding)
    artifact.write_text("Changed")
    with pytest.raises(ValueError, match="INPUT_ARTIFACT_CHANGED"):
        runner.run_authorized(
            binding,
            expected_binding_sha256=binding["binding_sha256"],
            registry_path=path,
            scope="fixture-scope",
            owner="Work",
            output_path=tmp_path / "result.json",
        )
    assert runner.admission(
        binding, registry_path=path, scope="fixture-scope", owner="Work"
    )


def test_changed_loader_callable_is_rejected_without_data_read(tmp_path, monkeypatch):
    from backend.research.rebuild import scalp7_exact25_model_data_v1 as data

    binding, _ = genuine_fixture_binding(tmp_path, monkeypatch)
    path, _, _ = allocated(tmp_path, binding)

    def changed_loader(manifest, config):
        raise AssertionError("Must never execute")

    monkeypatch.setattr(data, "load", changed_loader)
    with pytest.raises(ValueError, match="IDENTITY_PAYLOAD|LOADER_CALLABLE"):
        runner.run_authorized(
            binding,
            expected_binding_sha256=binding["binding_sha256"],
            registry_path=path,
            scope="fixture-scope",
            owner="Work",
            output_path=tmp_path / "result.json",
        )


def test_missing_symbol_cost_has_no_default_rate():
    binding = freeze()
    binding["cost"]["per_side_rates"] = {"DIFFERENT": 0.0001}
    with pytest.raises(ValueError, match="SYMBOL_COST_MISSING"):
        runner._fee(binding, "X")


@pytest.mark.parametrize("model_choice", ["SR_CONTROL", "SR"])
def test_sr_complete_raw_path_preserves_entry_axis_and_failure_exit(model_choice):
    from backend.research.rebuild import scalp7_exact25_reference_models_v1 as reference

    values = [(100, 110, 90, 100)] * 48 + [
        (100, 112, 99, 111),
        (111, 113, 109, 112),
        (112, 113, 107, 108),
    ]
    frames, detail = [], []
    for i, (opened_price, high, low, close) in enumerate(values):
        stamp = i * TF
        frames.append(
            dict(
                open_ts_ms=stamp,
                close_ts_ms=stamp + TF,
                available_ts_ms=stamp + TF,
                segment_id="fixture",
                open=opened_price,
                high=high,
                low=low,
                close=close,
            )
        )
        for j in range(30):
            minute = stamp + j * MINUTE
            c = close if j == 29 else opened_price
            detail.append(
                dict(
                    open_ts_ms=minute,
                    close_ts_ms=minute + MINUTE,
                    available_ts_ms=minute + MINUTE,
                    segment_id="fixture",
                    open=opened_price,
                    high=high if j == 0 else max(opened_price, c),
                    low=low if j == 0 else min(opened_price, c),
                    close=c,
                )
            )
    end = 51 * TF
    detail.append(
        dict(
            open_ts_ms=end,
            close_ts_ms=end + MINUTE,
            available_ts_ms=end + MINUTE,
            segment_id="fixture",
            open=108,
            high=108,
            low=108,
            close=108,
        )
    )
    inputs = {
        "frames": {"X": pd.DataFrame(frames)},
        "detail_frames": {"X": pd.DataFrame(detail)},
        "price_snapshots": [
            {"ts_ms": 0, "prices": {}},
            {
                "ts_ms": end + MINUTE,
                "prices": {
                    "X": {
                        "ts_ms": end + MINUTE,
                        "price": 108,
                        "price_basis": "LAST_PRICE",
                        "source_ref": "synthetic",
                    }
                },
            },
        ],
    }
    binding = runner.freeze_model(
        model_module=reference.__name__,
        model_id=getattr(reference, model_choice),
        strategy_id="sr_levels",
        baseline_id="source-box",
        changed_axis=model_choice,
        config={},
        data_manifest={
            "data_kind": "SYNTHETIC_FIXTURE",
            "construction_reason": "Prior day box followed by breakout retest failure",
        },
        cost={
            "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
            "per_side_rates": {"X": 0.0001},
            "funding_status": "UNKNOWN_NOT_ZERO",
        },
        windows=[
            {
                "name": "validation",
                "kind": "VALIDATION",
                "start_ts_ms": 0,
                "end_ts_ms": end + 2 * MINUTE,
            }
        ],
        initial_cash_usdt=10000,
    )
    result = runner.run_fixture(
        binding, inputs, expected_binding_sha256=binding["binding_sha256"]
    )
    assert result["unknown_execution_count"] == 0
    rows = result["execution"]["ledger"]
    assert len(rows) == 2
    assert rows[0]["ts_ms"] == (49 if model_choice == "SR_CONTROL" else 50) * TF
    assert rows[-1]["fill_price"] == "108.0"
    assert result["cost_scenarios"]["1x"]["windows"][0]["T_resolved"] == 1


def test_data_relocation_changes_locator_binding_not_experiment_identity():
    binding = freeze()
    kwargs = {
        k: binding[k]
        for k in (
            "model_module",
            "model_id",
            "strategy_id",
            "baseline_id",
            "changed_axis",
            "config",
            "data_manifest",
            "cost",
            "windows",
            "initial_cash_usdt",
        )
    }
    kwargs["data_manifest"] = {
        **kwargs["data_manifest"],
        "canonical_root": "/checkout/one",
        "artifacts": [{"path": "/checkout/one/input.json", "sha256": "a" * 64}],
    }
    first = runner.freeze_model(**kwargs)
    kwargs["data_manifest"]["canonical_root"] = "/relocated/two"
    kwargs["data_manifest"]["artifacts"][0]["path"] = "/relocated/two/input.json"
    second = runner.freeze_model(**kwargs)
    assert first["identity_key"] == second["identity_key"]
    assert first["binding_sha256"] != second["binding_sha256"]


def test_gap_account_prefix_ends_at_first_missing_minute_not_resume():
    inputs = raw_inputs(gap=True)
    inputs["price_snapshots"].insert(1, {"ts_ms": 422 * MINUTE, "prices": {}})
    binding = freeze()
    result = runner.run_fixture(
        binding, inputs, expected_binding_sha256=binding["binding_sha256"]
    )
    execution = result["execution"]["executions"][0]
    assert execution["unresolved_observed_ts_ms"] == 421 * MINUTE
    assert execution["gap_resume_or_detection_ts_ms"] == 422 * MINUTE
    assert (
        result["cost_scenarios"]["1x"]["account"]["valuation"]["curve"][-1]["ts_ms"]
        == 0
    )


def test_genuine_frame_provenance_cannot_be_relabelled_fixture():
    inputs = raw_inputs()
    inputs["frames"]["X"].attrs["source_rows_are_genuine"] = True
    binding = freeze()
    with pytest.raises(PermissionError, match="GENUINE_LOADER_PROVENANCE"):
        runner.run_fixture(
            binding, inputs, expected_binding_sha256=binding["binding_sha256"]
        )


@pytest.mark.parametrize("family", ["indicator", "reference", "structure"])
def test_ten_thousand_bar_callback_prefix_and_frozen_bound_are_equivalent(family):
    from backend.research.rebuild import scalp7_exact25_reference_models_v1 as reference
    from backend.research.rebuild import scalp7_exact25_structure_models_v1 as structure

    rows = [
        {
            "open_ts_ms": i * TF,
            "close_ts_ms": (i + 1) * TF,
            "available_ts_ms": (i + 1) * TF,
            "segment_id": "fixture",
            "high": 120,
            "low": 110,
            "close": 115,
            "st_available_ts_ms": (i + 1) * TF,
            "st_direction": 1,
            "st_line": 109,
        }
        for i in range(10000)
    ]
    rows[-2]["low"] = 108
    module, model_id, limit = {
        "indicator": (indicator, indicator.TRAIL, 1),
        "reference": (reference, reference.SR, 1),
        "structure": (structure, structure.MODEL_ID, 3),
    }[family]
    signal = {
        "model_id": model_id,
        "scheduled_exit_ts_ms": 10001 * TF,
        "reference_edge": 100,
        "liquidation_decision_close_ms": 10001 * TF,
        "lifecycle_id": structure.LIFECYCLE_ID,
        "tick_size": 0.1,
    }
    position = {
        "signal": signal,
        "side": 1,
        "stop_price": 90,
        "entry_price": 100,
        "entry_ts_ms": 0,
    }
    policy = runner.callback_history_policy(module.__name__, model_id)
    bounded = runner._callback_history(rows, len(rows) - 1, policy)
    assert len(bounded) == limit
    assert module.exit_update(position, rows[-1], rows) == module.exit_update(
        position, rows[-1], bounded
    )


@pytest.mark.parametrize("rates", [{"OTHER": 0.0001}, {"X": 0.0001, "OTHER": 0.0001}])
def test_genuine_cost_universe_is_rejected_at_freeze_before_budget(rates):
    binding = freeze(genuine=True)
    kwargs = {
        k: binding[k]
        for k in (
            "model_module",
            "model_id",
            "strategy_id",
            "baseline_id",
            "changed_axis",
            "config",
            "data_manifest",
            "cost",
            "windows",
            "initial_cash_usdt",
        )
    }
    kwargs["cost"] = {**kwargs["cost"], "per_side_rates": rates}
    with pytest.raises(ValueError, match="COST_UNIVERSE_MISMATCH"):
        runner.freeze_model(**kwargs)


def test_result_created_during_replay_cannot_be_overwritten(tmp_path, monkeypatch):
    """A second publisher must not destroy an already durable result path."""
    binding, _ = genuine_fixture_binding(tmp_path, monkeypatch)
    path, _, _ = allocated(tmp_path, binding)
    output = tmp_path / "result.json"
    existing = b'{"owner": "concurrent-publication"}'
    original = runner._replay

    def publish_during_replay(bound, inputs, module):
        result = original(bound, inputs, module)
        output.write_bytes(existing)
        return result

    monkeypatch.setattr(runner, "_replay", publish_during_replay)
    with pytest.raises(FileExistsError):
        runner.run_authorized(
            binding,
            expected_binding_sha256=binding["binding_sha256"],
            registry_path=path,
            scope="fixture-scope",
            owner="Work",
            output_path=output,
        )
    assert output.read_bytes() == existing
    import sqlite3

    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state FROM claims").fetchone()[0] == "FAILED"
        assert (
            db.execute("SELECT count(*) FROM events WHERE event='STARTED'").fetchone()[
                0
            ]
            == 1
        )
