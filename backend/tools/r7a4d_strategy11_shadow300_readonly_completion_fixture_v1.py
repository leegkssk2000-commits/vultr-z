from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.research.strategy11_shadow200_readonly_accumulator_v1 import INPUT_SCHEMA as INPUT200, accumulate
from backend.research.strategy11_shadow300_readonly_completion_v1 import (
    INPUT_SCHEMA,
    Shadow300CompletionError,
    complete,
)

OUT = Path("artifacts/strategy11_shadow300_readonly_completion_v1")
AUTHORITY = {**SAFETY, "runtime_bound": False}
LINEAGE = {
    "source_w1_manifest_sha": "a" * 64,
    "data_sha": "b" * 64,
    "window_sha": "c" * 64,
    "evidence_manifest_sha": "d" * 64,
}
COMBINATION_SHA = "e" * 64
TARGET_WEIGHTS_SHA = "f" * 64


def shadow20_segment(index: int, start_cycle: int) -> dict:
    payload = {
        "state": "PASS_SHADOW20_READ_ONLY_CANARY",
        "shadow_200c_allowed": True,
        "selected_combination_sha": COMBINATION_SHA,
        "target_weights_sha": TARGET_WEIGHTS_SHA,
        "shared_lineage": copy.deepcopy(LINEAGE),
        "metrics": {
            "total_net_r": 0.20 + index * 0.01,
            "total_cost_r": 0.02,
            "max_shadow_dd_pct": 0.50 + index * 0.01,
            "max_cost_overrun_pct": 5.0 + index * 0.1,
            "max_abs_weight_drift": 0.01,
            "max_abs_rolling_correlation": 0.40 + index * 0.01,
            "max_attribution_error_r": 0.0,
            "stale_cycles": 0,
            "source_parity_failures": 0,
            "display_integrity_failures": 0,
            "lineage_failures": 0,
            "chaos_e2e_failures": 0,
        },
        "runtime_bound": False,
        "real_shadow_started": False,
        **SAFETY,
    }
    return {
        "segment_id": f"shadow20.segment.{start_cycle:03d}",
        "start_cycle": start_cycle,
        "end_cycle": start_cycle + 19,
        "cycle_count": 20,
        "run_id": str(800000 + start_cycle),
        "head_sha": "1" * 64,
        "artifact_sha": canonical_sha({"start_cycle": start_cycle, "kind": "SHADOW20"}),
        "payload": payload,
        "payload_sha": canonical_sha(payload),
    }


def midcheck() -> dict:
    return {
        "source_parity_pass": True,
        "a_c_mirroring_pass": True,
        "policy_abcd_shadow_pass": True,
        "bad_context_filter_pass": True,
        "cooldown_pass": True,
        "pre_entry_lineage_pass": True,
        "mfe_mae_complete": True,
        "fee_slippage_latency_complete": True,
        "dd_exposure_pass": True,
        "symbol_regime_side_complete": True,
        "display_integrity_pass": True,
        "chaos_e2e_pass": True,
        "policy_abcd_results": {"A": "PASS", "B": "PASS", "C": "PASS", "D": "PASS"},
        "coverage_metrics": {
            "mfe_sample_count": 200, "mae_sample_count": 200, "fee_sample_count": 200,
            "slippage_sample_count": 200, "latency_sample_count": 200,
            "symbol_count": 5, "regime_count": 4, "side_count": 2,
        },
    }


def policy200() -> dict:
    return {
        "policy_id": "FIXTURE_SHADOW200_POLICY",
        "required_segment_count": 10, "required_cycle_count": 200,
        "max_shadow_dd_pct": 4.0, "max_cost_overrun_pct": 20.0,
        "max_abs_weight_drift": 0.05, "max_abs_rolling_correlation": 0.85,
        "max_attribution_error_r": 1e-8, "min_total_net_r": 0.0,
        "max_stale_cycles": 0, "max_source_parity_failures": 0,
        "max_display_integrity_failures": 0, "max_lineage_failures": 0,
        "max_chaos_e2e_failures": 0,
    }


def base200() -> dict:
    payload = {
        "schema_version": INPUT200,
        "segments": [shadow20_segment(i, i * 20 + 1) for i in range(10)],
        "midcheck": midcheck(),
        "policy": policy200(),
        "authority": copy.deepcopy(AUTHORITY),
    }
    result = accumulate(payload)
    assert result["state"] == "PASS_SHADOW200_READ_ONLY_ACCUMULATION"
    return result


def final_review() -> dict:
    return {
        "source_parity_pass": True,
        "strategy_config_unchanged": True,
        "portfolio_policy_unchanged": True,
        "material_seals_unchanged": True,
        "role_boundaries_pass": True,
        "attribution_complete": True,
        "model_risk_pass": True,
        "display_integrity_pass": True,
        "chaos_e2e_pass": True,
        "rollback_drill_pass": True,
        "failure_learning_disconnected": True,
        "ml_light_disconnected": True,
        "paper_live_order_blocked": True,
        "evidence_stages": {"W1": "PASS", "W2": "PASS", "W3": "PASS", "NEW_SEALED": "PASS"},
        "error_budget_used": 1,
        "error_budget_limit": 20,
    }


def policy300() -> dict:
    return {
        "policy_id": "FIXTURE_SHADOW300_POLICY_NOT_PRODUCTION_AUTHORITY",
        "required_total_cycles": 300,
        "max_shadow_dd_pct": 4.0,
        "max_cost_overrun_pct": 20.0,
        "max_abs_weight_drift": 0.05,
        "max_abs_rolling_correlation": 0.85,
        "max_attribution_error_r": 1e-8,
        "min_total_net_r": 0.0,
        "max_stale_cycles": 0,
        "max_source_parity_failures": 0,
        "max_display_integrity_failures": 0,
        "max_lineage_failures": 0,
        "max_chaos_e2e_failures": 0,
        "max_error_budget_ratio": 0.20,
    }


def valid_input() -> dict:
    return {
        "schema_version": INPUT_SCHEMA,
        "base_200": base200(),
        "continuation_segments": [shadow20_segment(10 + i, 201 + i * 20) for i in range(5)],
        "final_review": final_review(),
        "policy": policy300(),
        "authority": copy.deepcopy(AUTHORITY),
    }


def expect_error(name: str, payload: dict, code: str) -> dict:
    try:
        complete(payload)
    except Shadow300CompletionError as exc:
        assert code in str(exc), (name, code, str(exc))
        return {"case": name, "status": "PASS_REJECTED", "expected_code": code, "error": str(exc)}
    raise AssertionError(f"{name}: expected {code}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    passed = complete(valid_input())
    assert passed["state"] == "PASS_SHADOW300_READ_ONLY_COMPLETION"
    assert passed["cycle_count"] == 300
    assert passed["ml_light_observer_gate_allowed"] is True
    assert passed["failure_learning_observer_gate_allowed"] is True
    assert passed["paper_30d_allowed"] is False

    incomplete_payload = valid_input()
    incomplete_payload["continuation_segments"] = incomplete_payload["continuation_segments"][:-1]
    incomplete = complete(incomplete_payload)
    assert incomplete["state"] == "HOLD_SHADOW300_INCOMPLETE"

    dd_payload = valid_input()
    dd_payload["continuation_segments"][2]["payload"]["metrics"]["max_shadow_dd_pct"] = 9.0
    dd_payload["continuation_segments"][2]["payload_sha"] = canonical_sha(dd_payload["continuation_segments"][2]["payload"])
    rollback = complete(dd_payload)
    assert rollback["state"] == "ROLLBACK_SHADOW300_READ_ONLY"
    assert "SHADOW_DD_BREACH" in rollback["blocker_codes"]

    check_payload = valid_input()
    check_payload["final_review"]["ml_light_disconnected"] = False
    check_reject = expect_error("premature_ml_light", check_payload, "FINAL_CHECK_NOT_PASS")

    lineage_payload = valid_input()
    lineage_payload["continuation_segments"][1]["payload"]["shared_lineage"]["data_sha"] = "9" * 64
    lineage_payload["continuation_segments"][1]["payload_sha"] = canonical_sha(lineage_payload["continuation_segments"][1]["payload"])
    lineage_reject = expect_error("lineage_mismatch", lineage_payload, "CONTINUATION_LINEAGE_MISMATCH")

    base_payload = valid_input()
    base_payload["base_200"]["metrics"]["total_net_r"] = 999.0
    base_reject = expect_error("base_200_tamper", base_payload, "BASE_200_SHA_MISMATCH")

    gap_payload = valid_input()
    gap_payload["continuation_segments"][3]["start_cycle"] = 262
    gap_payload["continuation_segments"][3]["end_cycle"] = 281
    gap_reject = expect_error("continuation_gap", gap_payload, "CONTINUATION_GAP_OR_OVERLAP")

    (OUT / "pass.json").write_text(json.dumps(passed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold_incomplete.json").write_text(json.dumps(incomplete, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "rollback_dd.json").write_text(json.dumps(rollback, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    negatives = [check_reject, lineage_reject, base_reject, gap_reject]
    (OUT / "negative_fixtures.json").write_text(json.dumps(negatives, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "state": "PASS_SHADOW300_READ_ONLY_COMPLETION_FIXTURES",
        "pass_state": passed["state"],
        "hold_state": incomplete["state"],
        "rollback_state": rollback["state"],
        "cycle_count": passed["cycle_count"],
        "negative_fixture_count": len(negatives),
        "ml_light_observer_gate_allowed_fixture": True,
        "failure_learning_observer_gate_allowed_fixture": True,
        "paper_30d_allowed": False,
        "automatic_shadow_start": False,
        "real_shadow_started": False,
        "production_threshold_authority": False,
        "runtime_bound": False,
        "next": "ML_LIGHT_AND_FAILURE_LEARNING_OBSERVER_ONLY_GATE_THEN_30D_PAPER_CANARY",
        **SAFETY,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
