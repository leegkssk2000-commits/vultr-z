from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_adaptive_execution_contract_v1 import (
    AdaptiveExecutionContractError,
    evaluate_preview,
    stable_sha,
)

VERSION = "STRATEGY11_ADAPTIVE_EXECUTION_FIXTURE_V1"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def base_request(policy_sha: str) -> dict[str, Any]:
    return {
        "intent_id": "intent.strategy11.alpha.time54.0001",
        "client_order_id": "s11-alpha-time54-0001",
        "symbol": "BTCUSDT",
        "exchange": "BINGX",
        "side": "long",
        "stop_owner": "STRATEGY_PRIMARY_STOP",
        "requested_qty": 1.0,
        "requested_notional": 2000.0,
        "equity": 10000.0,
        "leverage": 10.0,
        "current_exposure_pct": 5.0,
        "requested_exposure_pct": 10.0,
        "liq_buffer_pct": 28.0,
        "spread_bps": 4.0,
        "slippage_bps": 3.0,
        "fee_bps": 5.0,
        "funding_8h_pct": 0.01,
        "latency_ms": 250.0,
        "data_age_ms": 900.0,
        "depth_notional": 100000.0,
        "now_ms": 2000,
        "reduce_only": False,
        "fill_history": [
            {"state": "NEW", "filled_qty": 0.0, "ts_ms": 1000}
        ],
        "source_binding": {
            "source_sha": "1" * 64,
            "data_sha": "2" * 64,
            "candidate_sha": "3" * 64,
            "policy_sha": policy_sha,
            "run_id": "fixture-run-adaptive-001",
            "artifact_id": "fixture-artifact-adaptive-001",
        },
    }


def expect_error(name: str, fn: Any, expected_prefix: str) -> dict[str, Any]:
    try:
        fn()
    except AdaptiveExecutionContractError as exc:
        message = str(exc)
        if not message.startswith(expected_prefix):
            raise AssertionError(f"{name}:{message}:{expected_prefix}") from exc
        return {"name": name, "state": "PASS_EXPECTED_ERROR", "error": message}
    raise AssertionError(f"{name}:EXPECTED_ERROR_NOT_RAISED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    request = base_request(str(policy["policy_sha"]))

    passed = evaluate_preview(request, policy)
    assert passed["state"] == "PASS_ADAPTIVE_EXECUTION_PREVIEW"
    assert passed["action"] == "hold"
    assert passed["blockers"] == []
    assert passed["metrics"]["next_step"] == "SHADOW_EXECUTION_SIMULATION_ONLY"
    assert passed["metrics"]["total_cost_bps"] == 11.0
    assert passed["metrics"]["depth_participation_pct"] == 2.0

    duplicate = evaluate_preview(
        request,
        policy,
        seen_intent_ids={request["intent_id"]},
        seen_client_order_ids={request["client_order_id"]},
    )
    assert duplicate["state"] == "HOLD_ADAPTIVE_EXECUTION_PREVIEW"
    assert duplicate["blockers"] == ["DUPLICATE_CLIENT_ORDER_ID", "DUPLICATE_INTENT_ID"]

    partial_request = deepcopy(request)
    partial_request["intent_id"] = "intent.strategy11.alpha.time54.0002"
    partial_request["client_order_id"] = "s11-alpha-time54-0002"
    partial_request["now_ms"] = 70000
    partial_request["fill_history"] = [
        {"state": "NEW", "filled_qty": 0.0, "ts_ms": 1000},
        {"state": "SENT", "filled_qty": 0.0, "ts_ms": 2000},
        {"state": "PARTIAL", "filled_qty": 0.4, "ts_ms": 3000},
    ]
    partial = evaluate_preview(partial_request, policy)
    assert partial["state"] == "HOLD_ADAPTIVE_EXECUTION_PREVIEW"
    assert partial["blockers"] == ["FILL_HEARTBEAT_STALE", "PARTIAL_FILL_RECONCILIATION_REQUIRED"]

    breached_request = deepcopy(request)
    breached_request["intent_id"] = "intent.strategy11.alpha.time54.0003"
    breached_request["client_order_id"] = "s11-alpha-time54-0003"
    breached_request.update({
        "leverage": 25.0,
        "current_exposure_pct": 20.0,
        "requested_exposure_pct": 10.0,
        "liq_buffer_pct": 5.0,
        "spread_bps": 20.0,
        "slippage_bps": 15.0,
        "latency_ms": 2000.0,
        "data_age_ms": 6000.0,
        "depth_notional": 15000.0,
        "stop_owner": "UNOWNED_STOP",
    })
    breached = evaluate_preview(breached_request, policy)
    expected = {
        "EXPOSURE_LIMIT", "LEVERAGE_LIMIT", "LIQ_BUFFER_LIMIT", "LIQUIDITY_CAPACITY_LIMIT",
        "SLIPPAGE_LIMIT", "SPREAD_LIMIT", "STALE_DATA", "STOP_OWNER_INVALID",
        "TOTAL_COST_LIMIT", "LATENCY_LIMIT",
    }
    assert expected.issubset(set(breached["blockers"])), breached["blockers"]

    transition_request = deepcopy(request)
    transition_request["fill_history"] = [
        {"state": "NEW", "filled_qty": 0.0, "ts_ms": 1000},
        {"state": "SENT", "filled_qty": 0.0, "ts_ms": 1500},
        {"state": "FILLED", "filled_qty": 1.0, "ts_ms": 2000},
        {"state": "ACK", "filled_qty": 1.0, "ts_ms": 3000},
    ]
    transition_error = expect_error(
        "EVENT_AFTER_TERMINAL",
        lambda: evaluate_preview(transition_request, policy),
        "INVALID_FILL_TRANSITION:FILLED->ACK",
    )

    tampered_policy = deepcopy(policy)
    tampered_policy["max_leverage"] = 100.0
    policy_error = expect_error(
        "POLICY_SHA_TAMPER",
        lambda: evaluate_preview(request, tampered_policy),
        "POLICY_SHA_MISMATCH",
    )

    summary = {
        "schema_version": "strategy11.adaptive_execution_fixture.v1",
        "version": VERSION,
        "state": "PASS_ADAPTIVE_EXECUTION_CONTRACT_FIXTURES",
        "policy_sha": policy["policy_sha"],
        "case_count": 6,
        "pass_preview": passed,
        "duplicate_hold": duplicate,
        "partial_fill_hold": partial,
        "risk_cost_hold": breached,
        "negative_cases": [transition_error, policy_error],
        "runtime_activation_allowed": False,
        "order_submission_allowed": False,
        "automatic_live_enable": False,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    summary["fixture_sha"] = stable_sha(summary)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "summary.json", summary)
    atomic_json(args.out / "pass_preview.json", passed)
    atomic_json(args.out / "partial_fill_hold.json", partial)
    atomic_json(args.out / "risk_cost_hold.json", breached)
    print(summary["state"], summary["case_count"], passed["metrics"]["total_cost_bps"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
