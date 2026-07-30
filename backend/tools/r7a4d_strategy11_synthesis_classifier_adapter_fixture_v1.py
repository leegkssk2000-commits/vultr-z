from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.research.strategy11_synthesis_classifier_adapter_v1 import (
    SynthesisClassifierAdapterError,
    adapt_and_classify,
    canonical_sha,
    validate_context,
)
from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY
from backend.research.strategy11_synthesis_sealer_v1 import seal_synthesis
from backend.tools.r7a4d_strategy11_synthesis_sealer_fixture_v1 import fixture_input as sealer_fixture_input

OUT = Path("artifacts/strategy11_synthesis_classifier_adapter_v1")


def expect_failure(code: str, fn) -> str:
    try:
        fn()
    except SynthesisClassifierAdapterError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def source_trade(index: int, net_r: float, regime: str) -> dict:
    core = {
        "trade_id": f"synthesis-fixture-trade-{index:02d}",
        "timestamp": f"2026-08-{index + 1:02d}T00:00:00Z",
        "net_r": net_r,
        "symbol": "BTCUSDT" if index % 2 == 0 else "ETHUSDT",
        "regime": regime,
    }
    return {**core, "source_row_sha": canonical_sha(core)}


def context() -> dict:
    trades = [
        source_trade(0, 0.45, "UPTREND"),
        source_trade(1, -0.30, "RANGE"),
        source_trade(2, 0.55, "UPTREND"),
        source_trade(3, -0.25, "HIGH_VOL"),
        source_trade(4, 0.70, "UPTREND"),
        source_trade(5, 0.35, "RANGE"),
        source_trade(6, -0.20, "HIGH_VOL"),
        source_trade(7, 0.60, "UPTREND"),
        source_trade(8, 0.30, "RANGE"),
        source_trade(9, -0.15, "HIGH_VOL"),
        source_trade(10, 0.50, "UPTREND"),
        source_trade(11, 0.25, "RANGE"),
        source_trade(12, -0.20, "HIGH_VOL"),
        source_trade(13, 0.65, "UPTREND"),
        source_trade(14, 0.40, "RANGE"),
        source_trade(15, -0.25, "HIGH_VOL"),
    ]
    return {
        "schema_version": "strategy11.synthesis_classifier_context.v1",
        "artifact": "fixture/synthesis/new_sealed/context.json",
        "run_id": "fixture-new-sealed-run-1",
        "producer": {
            "team_lane": "ALPHA",
            "role": "RESEARCH",
            "independent_proposal": True,
        },
        "market": {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframe": "15m",
            "side": "LONG",
            "regime": "MIXED",
            "session": "ALL",
        },
        "confidence": {
            "score": 0.82,
            "uncertainty": 0.18,
            "sample_quality": "HIGH",
            "oos_windows": 3,
        },
        "cost_envelope": {
            "fee_bps": 5.0,
            "slippage_bps": 4.0,
            "funding_8h_pct": 0.01,
            "latency_ms": 250.0,
            "stress_multiplier": 2.0,
            "capacity_notional_usdt": 5000.0,
        },
        "edge_projection": {
            "win_rate_pct": 62.5,
            "net_pct": 4.2,
            "retention_pct": 85.0,
        },
        "risk_context": {
            "max_drawdown_pct": 2.4,
            "joint_tail_budget_pct": 3.5,
            "max_exposure_pct": 20.0,
        },
        "statistics": {
            "trade_quota_pass": True,
            "regime_coverage_pass": True,
            "dsr_pass": True,
            "bh_fdr_pass": True,
            "independent_edge_pass": False,
            "synthesis_eligible": True,
            "symbol_concentration_pct": 56.25,
            "window_concentration_pct": 40.0,
            "regime_concentration_pct": 43.75,
        },
        "lineage": {
            "strategy_source_sha": "a" * 64,
            "data_epoch": "fixture-new-sealed-epoch-1",
        },
        "reason_codes": ["FACTORIAL_INTERACTION_PASS", "COMPONENT_ATTRIBUTION_PASS", "NEW_SEALED_PASS"],
        "metadata": {
            "fixture_only": True,
            "production_authority": False,
            "source_projection_bound": True,
        },
        "source_ledger": trades,
    }


def classifier_policy() -> dict:
    return {
        "policy_id": "FIXTURE_SYNTHESIS_CLASSIFIER_POLICY_NOT_PRODUCTION_AUTHORITY",
        "min_trades": 10,
        "min_positive_window_ratio": 0.5,
        "min_retention_pct": 70.0,
        "min_profit_factor": 1.1,
        "min_net_pct": 0.1,
        "max_drawdown_pct": 10.0,
        "min_worst_loss_r": -0.75,
        "min_stress_worst_loss_r": -0.75,
        "min_confidence_core": 0.8,
        "max_uncertainty_core": 0.25,
        "max_symbol_concentration_core_pct": 50.0,
        "max_window_concentration_core_pct": 50.0,
        "max_regime_concentration_core_pct": 50.0,
        "max_concentration_synthesis_pct": 80.0,
    }


def fixture_input() -> dict:
    sealer_input = sealer_fixture_input()
    sealer_result = seal_synthesis(sealer_input)
    ctx = validate_context(context())
    policy = classifier_policy()
    return {
        "schema_version": "strategy11.synthesis_classifier_adapter.input.v1",
        "sealer_input": sealer_input,
        "sealer_result": sealer_result,
        "context": ctx,
        "context_sha": canonical_sha(ctx),
        "classifier_policy": policy,
        "classifier_policy_sha": canonical_sha(policy),
        "authority": dict(SAFETY),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = fixture_input()
    passed = adapt_and_classify(payload)
    assert passed["state"] == "PASS_SYNTHESIS_CLASSIFIER_ADAPTER"
    assert passed["classification"]["classification"] == "SYNTHESIS"
    assert passed["next"] == "ENSEMBLE_CORRELATION_ANALYZER"
    assert passed["proposal"]["metadata"]["synthesis_seal_sha"] == passed["synthesis_seal_sha"]
    assert passed["proposal"]["candidate_sha"] == passed["candidate_sha"]
    assert passed["classifier_evidence"]["stages"] == {
        "w1": "PASS",
        "w2": "PASS",
        "w3": "PASS",
        "new_sealed": "PASS",
    }
    assert passed["classifier_evidence"]["independent_edge_pass"] is False
    assert passed["classifier_evidence"]["synthesis_eligible"] is True
    assert len(passed["source_ledger"]) == 16
    for key, expected in SAFETY.items():
        assert passed[key] == expected

    context_tamper = fixture_input()
    context_tamper["context"]["edge_projection"]["net_pct"] = 99.0
    expect_failure("CONTEXT_SHA_MISMATCH", lambda: adapt_and_classify(context_tamper))

    policy_tamper = fixture_input()
    policy_tamper["classifier_policy"]["min_net_pct"] = -999.0
    expect_failure("CLASSIFIER_POLICY_SHA_MISMATCH", lambda: adapt_and_classify(policy_tamper))

    sealer_tamper = fixture_input()
    sealer_tamper["sealer_result"]["sealer_sha"] = "f" * 64
    expect_failure("SEALER_RESULT_RECONCILIATION_MISMATCH", lambda: adapt_and_classify(sealer_tamper))

    hold_payload = fixture_input()
    hold_payload["context"]["statistics"]["synthesis_eligible"] = False
    hold_payload["context"] = validate_context(hold_payload["context"])
    hold_payload["context_sha"] = canonical_sha(hold_payload["context"])
    held = adapt_and_classify(hold_payload)
    assert held["state"] == "HOLD_SYNTHESIS_CLASSIFIER_ADAPTER"
    assert held["classification"]["classification"] == "HOLD"

    core_payload = fixture_input()
    core_payload["context"]["statistics"]["independent_edge_pass"] = True
    core_payload["context"]["statistics"]["symbol_concentration_pct"] = 40.0
    core_payload["context"]["statistics"]["window_concentration_pct"] = 40.0
    core_payload["context"]["statistics"]["regime_concentration_pct"] = 40.0
    core_payload["context"] = validate_context(core_payload["context"])
    core_payload["context_sha"] = canonical_sha(core_payload["context"])
    expect_failure("SYNTHESIS_SEAL_CLASSIFIED_CORE", lambda: adapt_and_classify(core_payload))

    reject_payload = fixture_input()
    reject_payload["context"]["edge_projection"]["net_pct"] = -5.0
    reject_payload["context"] = validate_context(reject_payload["context"])
    reject_payload["context_sha"] = canonical_sha(reject_payload["context"])
    rejected = adapt_and_classify(reject_payload)
    assert rejected["state"] == "REJECT_SYNTHESIS_CLASSIFIER_ADAPTER"
    assert rejected["classification"]["classification"] == "REJECT"

    (OUT / "input.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "pass.json").write_text(json.dumps(passed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold.json").write_text(json.dumps(held, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "reject.json").write_text(json.dumps(rejected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "state": "PASS_SYNTHESIS_CLASSIFIER_ADAPTER_FIXTURE",
        "adapter_sha": passed["adapter_sha"],
        "classification": passed["classification"]["classification"],
        "fixture_only": True,
        "production_authority": False,
        **SAFETY,
    }
    (OUT / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
