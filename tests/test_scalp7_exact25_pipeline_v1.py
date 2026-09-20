"""Actual source-producer/adapter/valuation integration on tiny invented bars."""

import copy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_indicators_v1 as producer
from backend.research.rebuild import scalp7_exact25_pipeline_v1 as pipeline


def example():
    rows = []
    for i, close in enumerate([10, 10, 9, 11, 12, 13]):
        rows.append(
            dict(
                open_ts_ms=i * 900000,
                close_ts_ms=(i + 1) * 900000,
                available_ts_ms=(i + 1) * 900000,
                segment_id="fixture",
                open=close,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                volume=10,
            )
        )
    rows[2].update(open=8.8, high=9.1, low=8, close=9)
    frame = pd.DataFrame(rows)
    config = dict(
        timeframe_min=15,
        mode_id="BBIII_ALERT_CONFIRM_EXPLICIT_V1",
        volume_unit="base",
        price_type="last",
        bb_length=3,
        bb_multiplier=1.0,
        ii_period=1,
        ii_version="ROLLING_NORMALIZED_HLC_VOLUME_V1",
        confirmation="CLOSE_BEYOND_ALERT_EXTREME",
        alert_expiry_bars=3,
        invalidation="ALERT_EXTREME",
    )
    completion = dict(
        origin="DECLARED_HYPOTHESIS",
        hypothesis_id="TEST_FIXTURE_BB_COMPLETION_ONLY",
        rationale="Invented source-caller accounting exercise, not a selected economic candidate",
        version="v1",
        usage="FIXTURE_INTEGRATION_ONLY",
        exact_source_reproduction=False,
        identity="bb_fixture_only_not_baseline",
        qty_base="2",
        fill_model=pipeline.MODEL,
        fee_rate="0.001",
        activation_policy="FEATURE_AVAILABLE_EXACT_MINUTE",
        missing_order_kind="NEXT_OPEN",
        missing_stop={"policy": "EXPLICIT_FIXTURE_PRICE", "price": 10},
        missing_expiry={"policy": "AFTER_ACTIVATION_MINUTES", "minutes": 30},
        lifecycle={"policy": "EXIT_AFTER_COMPLETE_DECISION_BARS", "bars": 1},
    )
    detail = []
    for i in range(16):
        t = 3600000 + i * 60000
        p = 12 if i < 15 else 13
        detail.append(
            dict(
                symbol="TEST",
                open_ts_ms=t,
                close_ts_ms=t + 60000,
                available_ts_ms=t + 60000,
                segment_id="fixture",
                open=p,
                high=p + 0.2,
                low=p - 0.2,
                close=p,
            )
        )
    prices = [
        {
            "ts_ms": t,
            "prices": {
                "TEST": {
                    "ts_ms": t,
                    "price": p,
                    "price_basis": "MARK_PRICE",
                    "source_ref": "synthetic_case_mark",
                }
            },
        }
        for t, p in [(3600000, 12), (4500000, 13)]
    ]
    return {
        "frames": {"TEST": frame},
        "config": config,
        "completion": completion,
        "detail_frames": {"TEST": pd.DataFrame(detail)},
        "price_snapshots": prices,
    }


def bind(case):
    produced = producer.evaluate("bb_revert", case["frames"], case["config"])
    return pipeline.freeze_binding(
        "bb_revert", case["config"], produced["rules"], case["completion"]
    )


def run(case, binding=None, **overrides):
    binding = bind(case) if binding is None else binding
    options = dict(
        expected_binding_sha256=binding["binding_sha256"],
        input_manifest={
            "data_kind": "SYNTHETIC_FIXTURE",
            "case_id": "BB_source_to_account",
            "construction_reason": "Hand-built BB alert, later confirmation, explicit fixture exit",
        },
        initial_cash_usdt=1000,
        start_ts_ms=3600000,
        price_basis="MARK_PRICE",
    )
    options.update(overrides)
    return pipeline.run_synthetic_pipeline(
        binding,
        case["frames"],
        case["config"],
        case["detail_frames"],
        case["price_snapshots"],
        **options
    )


def test_registry_dispatches_all_original25_and_no_mr_micro_substitution():
    registry = pipeline.registry()
    assert len(registry) == 25 and set(registry) == set(pipeline.EXACT25)
    assert not ({"micro", "mr", "cross_sectional_mr"} & registry.keys())
    assert all(len(row["producer_sha256"]) == 64 for row in registry.values())
    assert all(not row["complete_strategy"] for row in registry.values())
    assert len({row["caller"] for row in registry.values()}) == 5


def test_raw_bbiii_intent_to_model_fills_to_account_arithmetic():
    result = run(example())
    assert result["producer"]["intents"][0]["feature_available_ts_ms"] == 3600000
    fills = result["fill_ledger"]
    assert [(f["effect"], f["ts_ms"], float(f["fill_price"])) for f in fills] == [
        ("OPEN", 3600000, 12),
        ("CLOSE", 4500000, 13),
    ]
    assert all(f["execution_evidence"] == "MODEL_NOT_OBSERVED" for f in fills)
    assert result["account"]["valuation"]["curve"][-1]["equity_usdt"] == pytest.approx(
        1001.95
    )
    assert result["account"]["snapshots"][-1]["realized_gross_cum_usdt"] == "2.0"
    assert result["account"]["snapshots"][-1]["fees_cum_usdt"] == "0.0500"
    assert result["configured_research_execution"]
    assert not result["complete_source_strategy"]
    assert not result["candidate_ready_for_full"]
    assert result["new_full_executions"] == 0
    assert result["source_limitations_preserved"] == result["producer"]["limitations"]
    assert result["authority"]["order"] == result["authority"]["live"] == "BLOCKED"


def test_source_intent_remains_blocked_without_declared_completion():
    case = example()
    case["completion"] = None
    result = run(case)
    assert result["fill_ledger"] == [] and not result["executions"]
    assert (
        result["intent_dispositions"][0]["reason"] == "NO_DECLARED_EXECUTION_COMPLETION"
    )
    assert result["account"]["valuation"]["curve"][-1]["equity_usdt"] == 1000


@pytest.mark.parametrize(
    "field",
    [
        "qty_base",
        "missing_stop",
        "missing_expiry",
        "lifecycle",
        "fee_rate",
        "missing_order_kind",
    ],
)
def test_missing_execution_choice_never_gets_default(field):
    case = example()
    del case["completion"][field]
    result = run(case)
    assert not result["fill_ledger"]
    assert result["intent_dispositions"][0]["status"] == "BLOCKED_INCOMPLETE_EXECUTION"


@pytest.mark.parametrize("tamper", ["rules", "config", "completion", "code"])
def test_externally_pinned_binding_rejects_tampering(tamper):
    case = example()
    binding = bind(case)
    if tamper == "rules":
        binding["source_rules"][0]["expression"] = "changed"
    elif tamper == "config":
        binding["config"]["timeframe_min"] = 30
    elif tamper == "completion":
        binding["completion"]["missing_stop"]["price"] = 1
    else:
        binding["code_closure"][binding["producer_path"]] = "0" * 64
    with pytest.raises(ValueError, match="PINNED_BINDING"):
        run(case, binding)


def test_rehashed_untrusted_binding_does_not_match_external_expected_digest():
    case = example()
    binding = bind(case)
    pinned = binding["binding_sha256"]
    binding["completion"]["qty_base"] = "200"
    binding["binding_sha256"] = pipeline.digest(
        {k: v for k, v in binding.items() if k != "binding_sha256"}
    )
    with pytest.raises(ValueError, match="PINNED_BINDING"):
        run(case, binding, expected_binding_sha256=pinned)


def test_runtime_config_change_rejected_before_producer():
    case = example()
    binding = bind(case)
    case["config"]["bb_multiplier"] = 4
    with pytest.raises(ValueError, match="CONFIG_BINDING"):
        run(case, binding)


def test_different_valid_rules_do_not_certify_actual_producer():
    case = example()
    produced = producer.evaluate("bb_revert", case["frames"], case["config"])
    produced["rules"][0][
        "expression"
    ] = "A valid metadata row but a different implementation"
    binding = pipeline.freeze_binding(
        "bb_revert", case["config"], produced["rules"], case["completion"]
    )
    with pytest.raises(ValueError, match="ACTUAL_CALLER_RULES"):
        run(case, binding)


def test_monkeypatched_producer_callable_rejected(monkeypatch):
    case = example()
    binding = bind(case)
    monkeypatch.setattr(producer, "evaluate", lambda *a: {})
    with pytest.raises(ValueError, match="PRODUCER_CALLABLE_CHANGED"):
        run(case, binding)


def test_gap_keeps_unresolved_position_and_unrealized_account():
    case = example()
    case["detail_frames"]["TEST"] = case["detail_frames"]["TEST"].drop(index=3)
    result = run(case)
    assert result["intent_dispositions"][0]["status"] == "UNRESOLVED"
    assert len(result["fill_ledger"]) == 1
    assert result["account"]["unclosed_position_episodes"]
    assert result["account"]["snapshots"][-1]["realized_gross_cum_usdt"] == "0"


def test_missing_detail_retains_intent_blocker():
    case = example()
    case["detail_frames"] = {}
    result = run(case)
    assert result["intent_dispositions"][0]["status"] == "BLOCKED_MISSING_DETAIL_SOURCE"
    assert not result["fill_ledger"]


def test_mark_missing_never_substitutes_ohlc():
    case = example()
    case["price_snapshots"][0]["prices"] = {}
    with pytest.raises(ValueError, match="PRICE_MISSING"):
        run(case)


def test_real_history_declaration_rejected():
    with pytest.raises(ValueError, match="REAL_HISTORY_EXECUTION_NOT_AUTHORIZED"):
        run(example(), input_manifest={"data_kind": "REAL_HISTORY"})


def test_inclusive_source_close_not_backdated_or_silently_normalized():
    case = example()
    binding = bind(case)
    case["frames"]["TEST"].loc[0, "close_ts_ms"] -= 1
    with pytest.raises(ValueError, match="EXCLUSIVE_CANONICAL"):
        run(case, binding)


def test_declared_fixture_cap_is_enforced():
    case = example()
    case["detail_frames"]["TEST"] = pd.concat([case["detail_frames"]["TEST"]] * 129)
    with pytest.raises(ValueError, match="FIXTURE_CAP"):
        run(case)


def test_input_fingerprint_changes_without_claiming_freshness():
    a = example()
    b = copy.deepcopy(a)
    b["price_snapshots"][-1]["prices"]["TEST"]["price"] = 13.1
    ra, rb = run(a), run(b)
    assert ra["integration_input_sha256"] != rb["integration_input_sha256"]
    assert ra["new_full_executions"] == rb["new_full_executions"] == 0


def test_fixture_completion_cannot_claim_exact_source_reproduction():
    case = example()
    case["completion"]["exact_source_reproduction"] = True
    with pytest.raises(ValueError, match="NOT_SOURCE_REPRODUCTION"):
        bind(case)


def test_same_ms_ledger_preserves_causal_close_then_open_despite_lexical_ids():
    rows = [
        {
            "ts_ms": 1,
            "symbol": "TEST",
            "fill_id": "model:episode:2:1",
            "effect": "CLOSE",
        },
        {
            "ts_ms": 1,
            "symbol": "TEST",
            "fill_id": "model:episode:10:0",
            "effect": "OPEN",
        },
    ]
    assert pipeline.chronological_ledger(rows) == rows
    assert rows[0]["fill_id"] > rows[1]["fill_id"]


def test_capital_component_dispatch_without_fake_ohlc():
    from backend.research.rebuild import scalp7_exact25_capital_v1 as capital

    config = {
        "timeframe_min": 15,
        "component_signals": [],
        "weights": {"host": 1},
        "decision_ts_ms": 0,
        "available_risk_fraction": 0.1,
    }
    produced = capital.evaluate("alpha_combo", {}, config)
    binding = pipeline.freeze_binding("alpha_combo", config, produced["rules"])
    result = pipeline.evaluate_bound(
        binding, {}, config, expected_binding_sha256=binding["binding_sha256"]
    )
    assert result["producer"]["intents"] == []
    assert not result["complete_source_strategy"]


def test_environment_versions_are_part_of_binding(monkeypatch):
    case = example()
    binding = bind(case)
    changed = {**pipeline.environment_versions(), "pandas": "different"}
    monkeypatch.setattr(pipeline, "environment_versions", lambda: changed)
    with pytest.raises(ValueError, match="RUNTIME_ENVIRONMENT_CHANGED"):
        run(case, binding)


def test_gap_on_decision_boundary_preserves_unresolved_without_callback():
    case = example()
    case["detail_frames"]["TEST"] = case["detail_frames"]["TEST"].drop(index=13)
    result = run(case)
    assert result["intent_dispositions"][0]["status"] == "UNRESOLVED"
    assert len(result["fill_ledger"]) == 1
    assert result["executions"][0]["position"]["hold_bars"] == 0


def test_callable_digest_survives_identical_source_at_different_checkout(
    tmp_path, monkeypatch
):
    import inspect
    import types
    from pathlib import Path

    original = producer.evaluate
    expected = pipeline._callable_digest("bb_revert")
    copied = tmp_path / "same_producer.py"
    copied.write_text(Path(inspect.getsourcefile(original)).read_text())
    relocated = types.FunctionType(
        original.__code__.replace(co_filename=str(copied)), original.__globals__
    )
    monkeypatch.setattr(producer, "evaluate", relocated)
    assert pipeline._callable_digest("bb_revert") == expected
