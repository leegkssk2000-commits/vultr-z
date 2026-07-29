from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.research.strategy11_shadow20_readonly_canary_v1 import (
    INPUT_SCHEMA,
    Shadow20CanaryError,
    evaluate,
)

OUT = Path("artifacts/strategy11_shadow20_readonly_canary_v1")
AUTHORITY = {**SAFETY, "runtime_bound": False}
MATERIAL_ALPHA = "material.alpha_combo.TIME54"
MATERIAL_TURTLE = "material.turtle_trend.TRAIL_ACT100_ATR200"
WEIGHTS = {MATERIAL_ALPHA: 0.8, MATERIAL_TURTLE: 0.2}
SHARED_LINEAGE = {
    "source_w1_run_id": "40000000077",
    "source_w1_manifest_sha": canonical_sha({"fixture": "shared-w1-manifest"}),
    "data_sha": canonical_sha({"fixture": "shared-nonoverlap-data"}),
    "window_sha": canonical_sha({"fixture": "shared-f1-f2-f3-w1-w2-w3-sealed-window"}),
    "evidence_manifest_sha": canonical_sha({"fixture": "shared-w1-w2-w3-new-sealed-evidence"}),
}
COMBINATION_SHA = canonical_sha({"members": ["alpha_combo", "turtle_trend"], "diagnostic_equal_weight": True})

POLICY = {
    "policy_id": "FIXTURE_ONLY_SHADOW20_POLICY",
    "required_cycle_count": 20,
    "max_cycle_gap_minutes": 30.0,
    "max_shadow_dd_pct": 8.0,
    "max_cost_overrun_pct": 20.0,
    "max_abs_weight_drift": 0.05,
    "max_abs_rolling_correlation": 0.85,
    "max_attribution_error_r": 1e-9,
    "min_worst_cycle_net_r": -0.75,
    "max_consecutive_negative_cycles": 4,
    "max_stale_cycles": 0,
    "max_source_parity_failures": 0,
    "max_display_integrity_failures": 0,
    "max_duplicate_cycle_ids": 0,
}


def fixture_sha(token: str) -> str:
    return canonical_sha({"fixture": token})


def source(kind: str, artifact: str, run_id: str, document: Any) -> dict[str, Any]:
    return {
        "source_kind": kind,
        "artifact": artifact,
        "run_id": run_id,
        "artifact_sha": canonical_sha(document),
        "document": document,
        "transform": "FIXTURE_ONLY",
        "inference_used": False,
        "private_fields_present": False,
        "stale": False,
    }


def preflight() -> dict[str, Any]:
    value = {
        "schema_version": "strategy11.source_bound_multicandidate_orchestrator.output.v1",
        "state": "PASS_SOURCE_BOUND_MULTICANDIDATE_PREFLIGHT",
        "candidate_count": 2,
        "eligible_candidate_count": 2,
        "classifications": {"alpha_combo": "CORE", "turtle_trend": "SYNTHESIS"},
        "selected_combination": ["alpha_combo", "turtle_trend"],
        "selected_combination_sha": COMBINATION_SHA,
        "target_risk_weights": WEIGHTS,
        "shared_lineage": SHARED_LINEAGE,
        "stage_shas": {
            "proposal": {"alpha_combo": fixture_sha("proposal-alpha"), "turtle_trend": fixture_sha("proposal-turtle")},
            "classification": {"alpha_combo": fixture_sha("class-alpha"), "turtle_trend": fixture_sha("class-turtle")},
            "correlation": fixture_sha("correlation"),
            "governor": fixture_sha("governor"),
            "attribution_history": fixture_sha("attribution-history"),
            "role_boundary": fixture_sha("role-boundary"),
            "model_risk": {"TIME54": fixture_sha("risk-alpha"), "TRAIL_ACT100_ATR200": fixture_sha("risk-turtle")},
        },
        "source_history_verified": True,
        "append_only_evidence": True,
        "validated_role_message_count": 8,
        "model_risk_states": ["PASS_MODEL_RISK_GOVERNANCE", "PASS_MODEL_RISK_GOVERNANCE"],
        "shadow_20c_ready": True,
        "shadow_canary_scope": "READ_ONLY_ORCHESTRATOR_PREFLIGHT_ONLY",
        "automatic_shadow_start": False,
        "runtime_bound": False,
        **SAFETY,
    }
    value["orchestrator_sha"] = canonical_sha(value)
    return value


def make_cycles(count: int = 20) -> list[dict[str, Any]]:
    start = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
    gross_values = [0.20, 0.15, -0.18, 0.25, 0.10, -0.12, 0.22, 0.18, -0.20, 0.30,
                    0.12, -0.10, 0.24, 0.16, -0.14, 0.21, 0.19, -0.16, 0.28, 0.17]
    cycles: list[dict[str, Any]] = []
    equity = 0.0
    peak = 0.0
    for index in range(count):
        gross = gross_values[index]
        fee = 0.005
        slippage = 0.004
        funding = 0.001
        net = round(gross - fee - slippage - funding, 10)
        equity += net
        peak = max(peak, equity)
        dd_r = abs(min(equity - peak, 0.0))
        observed_alpha = 0.8 + (0.01 if index % 2 == 0 else -0.01)
        observed = {MATERIAL_ALPHA: observed_alpha, MATERIAL_TURTLE: 1.0 - observed_alpha}
        cycle = {
            "cycle_id": f"shadow20.fixture.{index + 1:02d}",
            "event_ts": (start + timedelta(minutes=15 * index)).isoformat().replace("+00:00", "Z"),
            "source_w1_manifest_sha": SHARED_LINEAGE["source_w1_manifest_sha"],
            "data_sha": SHARED_LINEAGE["data_sha"],
            "window_sha": SHARED_LINEAGE["window_sha"],
            "evidence_manifest_sha": SHARED_LINEAGE["evidence_manifest_sha"],
            "selected_combination_sha": COMBINATION_SHA,
            "target_weights": WEIGHTS,
            "observed_weights": observed,
            "material_net_pnl_r": {
                MATERIAL_ALPHA: round(net * 0.8, 10),
                MATERIAL_TURTLE: round(net - round(net * 0.8, 10), 10),
            },
            "gross_pnl_r": gross,
            "fee_r": fee,
            "slippage_r": slippage,
            "funding_r": funding,
            "net_pnl_r": net,
            "cumulative_dd_pct": round(dd_r * 2.0, 10),
            "cost_overrun_pct": 4.0 + index * 0.1,
            "rolling_correlation": 0.35 + (index % 3) * 0.05,
            "source_parity_pass": True,
            "display_integrity_pass": True,
            "stale": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        }
        cycle["cycle_sha"] = canonical_sha(cycle)
        cycles.append(cycle)
    return cycles


def payload(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    cycle_document = {"cycles": cycles}
    return {
        "schema_version": INPUT_SCHEMA,
        "preflight": preflight(),
        "cycle_source": source("SHADOW_READ_ONLY_CYCLE_LEDGER", "fixture-shadow20-cycle-ledger", "fixture-shadow20", cycle_document),
        "policy_source": source("FIXTURE_POLICY", "fixture-shadow20-policy", "fixture-policy", POLICY),
        "authority": AUTHORITY,
    }


def rehash_cycle_source(value: dict[str, Any]) -> None:
    value["cycle_source"]["artifact_sha"] = canonical_sha(value["cycle_source"]["document"])


def rehash_cycle(value: dict[str, Any], index: int) -> None:
    cycle = value["cycle_source"]["document"]["cycles"][index]
    cycle["cycle_sha"] = canonical_sha({key: child for key, child in cycle.items() if key != "cycle_sha"})
    rehash_cycle_source(value)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    passed = evaluate(payload(make_cycles()))
    assert passed["state"] == "PASS_SHADOW20_READ_ONLY_CANARY", passed
    assert passed["cycle_count"] == 20
    assert passed["shadow_20c_complete"] is True
    assert passed["shadow_200c_allowed"] is True
    assert passed["automatic_shadow_start"] is False
    assert passed["real_shadow_started"] is False

    incomplete = evaluate(payload(make_cycles(19)))
    assert incomplete["state"] == "HOLD_SHADOW20_READ_ONLY_CANARY", incomplete
    assert "CYCLE_COUNT_INCOMPLETE" in incomplete["reason_codes"]
    assert incomplete["shadow_200c_allowed"] is False

    dd_breach_payload = payload(make_cycles())
    dd_breach_payload["cycle_source"]["document"]["cycles"][10]["cumulative_dd_pct"] = 9.0
    rehash_cycle(dd_breach_payload, 10)
    dd_breach = evaluate(dd_breach_payload)
    assert dd_breach["state"] == "ROLLBACK_SHADOW20_READ_ONLY_CANARY", dd_breach
    assert "SHADOW_DD_BREACH" in dd_breach["reason_codes"]

    weight_drift_payload = payload(make_cycles())
    cycle = weight_drift_payload["cycle_source"]["document"]["cycles"][5]
    cycle["observed_weights"] = {MATERIAL_ALPHA: 0.65, MATERIAL_TURTLE: 0.35}
    rehash_cycle(weight_drift_payload, 5)
    weight_drift = evaluate(weight_drift_payload)
    assert weight_drift["state"] == "HOLD_SHADOW20_READ_ONLY_CANARY", weight_drift
    assert "WEIGHT_DRIFT" in weight_drift["reason_codes"]

    parity_payload = payload(make_cycles())
    parity_payload["cycle_source"]["document"]["cycles"][7]["source_parity_pass"] = False
    rehash_cycle(parity_payload, 7)
    parity = evaluate(parity_payload)
    assert parity["state"] == "HOLD_SHADOW20_READ_ONLY_CANARY", parity
    assert "SOURCE_PARITY_FAILURE" in parity["reason_codes"]

    negative_cases: list[str] = []

    lineage_payload = payload(make_cycles())
    lineage_payload["cycle_source"]["document"]["cycles"][3]["data_sha"] = fixture_sha("wrong-cycle-data")
    rehash_cycle(lineage_payload, 3)
    try:
        evaluate(lineage_payload)
    except Shadow20CanaryError as exc:
        assert str(exc).startswith("CYCLE_DATA_SHA_MISMATCH"), exc
        negative_cases.append("CYCLE_DATA_SHA_MISMATCH")
    else:
        raise AssertionError("cycle lineage mismatch accepted")

    cycle_tamper_payload = payload(make_cycles())
    cycle_tamper_payload["cycle_source"]["document"]["cycles"][4]["gross_pnl_r"] += 1.0
    rehash_cycle_source(cycle_tamper_payload)
    try:
        evaluate(cycle_tamper_payload)
    except Shadow20CanaryError as exc:
        assert str(exc).startswith("CYCLE_SHA_MISMATCH"), exc
        negative_cases.append("CYCLE_SHA_MISMATCH")
    else:
        raise AssertionError("cycle SHA tamper accepted")

    execution_payload = payload(make_cycles())
    execution_payload["cycle_source"]["document"]["cycles"][2]["execution_allowed"] = True
    rehash_cycle(execution_payload, 2)
    try:
        evaluate(execution_payload)
    except Shadow20CanaryError as exc:
        assert str(exc).startswith("CYCLE_EXECUTION_FORBIDDEN"), exc
        negative_cases.append("CYCLE_EXECUTION_FORBIDDEN")
    else:
        raise AssertionError("cycle execution authority accepted")

    preflight_tamper_payload = payload(make_cycles())
    preflight_tamper_payload["preflight"]["target_risk_weights"][MATERIAL_ALPHA] = 0.7
    preflight_tamper_payload["preflight"]["target_risk_weights"][MATERIAL_TURTLE] = 0.3
    try:
        evaluate(preflight_tamper_payload)
    except Shadow20CanaryError as exc:
        assert str(exc) == "PREFLIGHT_SHA_MISMATCH", exc
        negative_cases.append("PREFLIGHT_SHA_MISMATCH")
    else:
        raise AssertionError("preflight tamper accepted")

    summary = {
        "schema_version": "strategy11.shadow20_readonly_canary_fixture.v1",
        "state": "PASS_SHADOW20_READ_ONLY_CANARY_FIXTURES",
        "pass_state": passed["state"],
        "cycle_count": passed["cycle_count"],
        "pass_metrics": passed["metrics"],
        "incomplete_state": incomplete["state"],
        "dd_breach_state": dd_breach["state"],
        "weight_drift_state": weight_drift["state"],
        "parity_failure_state": parity["state"],
        "negative_cases_passed": negative_cases,
        "shadow_200c_allowed": passed["shadow_200c_allowed"],
        "automatic_shadow_start": passed["automatic_shadow_start"],
        "real_shadow_started": passed["real_shadow_started"],
        "fixture_only": True,
        "production_threshold_authority": False,
        "next": "SHADOW_200C_READ_ONLY_ACCUMULATION",
        "runtime_bound": False,
        **SAFETY,
    }
    summary["fixture_sha"] = canonical_sha(summary)

    outputs = {
        "summary.json": summary,
        "pass.json": passed,
        "incomplete_hold.json": incomplete,
        "dd_rollback.json": dd_breach,
        "weight_drift_hold.json": weight_drift,
        "source_parity_hold.json": parity,
    }
    for name, value in outputs.items():
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"], "net=", summary["pass_metrics"]["total_net_pnl_r"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
