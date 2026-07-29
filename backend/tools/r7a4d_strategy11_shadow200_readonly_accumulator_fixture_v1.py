from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.research.strategy11_shadow200_readonly_accumulator_v1 import (
    INPUT_SCHEMA,
    Shadow200AccumulatorError,
    accumulate,
)

OUT = Path("artifacts/strategy11_shadow200_readonly_accumulator_v1")
AUTHORITY = {**SAFETY, "runtime_bound": False}
SHARED_LINEAGE = {
    "source_w1_manifest_sha": "a" * 64,
    "data_sha": "b" * 64,
    "window_sha": "c" * 64,
    "evidence_manifest_sha": "d" * 64,
}
COMBINATION_SHA = "e" * 64
TARGET_WEIGHTS_SHA = "f" * 64


def policy() -> dict:
    return {
        "policy_id": "FIXTURE_SHADOW200_POLICY_NOT_PRODUCTION_AUTHORITY",
        "required_segment_count": 10,
        "required_cycle_count": 200,
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
            "mfe_sample_count": 200,
            "mae_sample_count": 200,
            "fee_sample_count": 200,
            "slippage_sample_count": 200,
            "latency_sample_count": 200,
            "symbol_count": 5,
            "regime_count": 4,
            "side_count": 2,
        },
    }


def segment(index: int) -> dict:
    payload = {
        "state": "PASS_SHADOW20_READ_ONLY_CANARY",
        "shadow_200c_allowed": True,
        "selected_combination_sha": COMBINATION_SHA,
        "target_weights_sha": TARGET_WEIGHTS_SHA,
        "shared_lineage": copy.deepcopy(SHARED_LINEAGE),
        "metrics": {
            "total_net_r": 0.22 + (index * 0.01),
            "total_cost_r": 0.02,
            "max_shadow_dd_pct": 0.45 + (index * 0.02),
            "max_cost_overrun_pct": 5.0 + (index * 0.2),
            "max_abs_weight_drift": 0.01,
            "max_abs_rolling_correlation": 0.42 + (index * 0.01),
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
    start = index * 20 + 1
    return {
        "segment_id": f"shadow20.segment.{index + 1:02d}",
        "start_cycle": start,
        "end_cycle": start + 19,
        "cycle_count": 20,
        "run_id": str(900000 + index),
        "head_sha": "1" * 64,
        "artifact_sha": canonical_sha({"segment": index, "kind": "SHADOW20_ARTIFACT"}),
        "payload": payload,
        "payload_sha": canonical_sha(payload),
    }


def valid_input() -> dict:
    return {
        "schema_version": INPUT_SCHEMA,
        "segments": [segment(index) for index in range(10)],
        "midcheck": midcheck(),
        "policy": policy(),
        "authority": copy.deepcopy(AUTHORITY),
    }


def expect_error(name: str, payload: dict, code: str) -> dict:
    try:
        accumulate(payload)
    except Shadow200AccumulatorError as exc:
        assert code in str(exc), (name, code, str(exc))
        return {"case": name, "status": "PASS_REJECTED", "expected_code": code, "error": str(exc)}
    raise AssertionError(f"{name}: expected {code}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    passed = accumulate(valid_input())
    assert passed["state"] == "PASS_SHADOW200_READ_ONLY_ACCUMULATION", passed
    assert passed["segment_count"] == 10 and passed["cycle_count"] == 200
    assert passed["shadow_300c_allowed"] is True
    assert passed["automatic_shadow_start"] is False and passed["real_shadow_started"] is False
    assert passed["metrics"]["total_net_r"] > 0

    incomplete_payload = valid_input()
    incomplete_payload["segments"] = incomplete_payload["segments"][:-1]
    incomplete = accumulate(incomplete_payload)
    assert incomplete["state"] == "HOLD_SHADOW200_INCOMPLETE"
    assert incomplete["shadow_300c_allowed"] is False

    dd_payload = valid_input()
    dd_payload["segments"][6]["payload"]["metrics"]["max_shadow_dd_pct"] = 8.0
    dd_payload["segments"][6]["payload_sha"] = canonical_sha(dd_payload["segments"][6]["payload"])
    rollback = accumulate(dd_payload)
    assert rollback["state"] == "ROLLBACK_SHADOW200_READ_ONLY"
    assert "SHADOW_DD_BREACH" in rollback["blocker_codes"]

    midcheck_payload = valid_input()
    midcheck_payload["midcheck"]["chaos_e2e_pass"] = False
    midcheck_reject = expect_error("midcheck_failure", midcheck_payload, "MIDCHECK_NOT_PASS")

    lineage_payload = valid_input()
    lineage_payload["segments"][4]["payload"]["shared_lineage"]["data_sha"] = "9" * 64
    lineage_payload["segments"][4]["payload_sha"] = canonical_sha(lineage_payload["segments"][4]["payload"])
    lineage_reject = expect_error("lineage_mismatch", lineage_payload, "SEGMENT_LINEAGE_MISMATCH")

    overlap_payload = valid_input()
    overlap_payload["segments"][5]["start_cycle"] = 100
    overlap_payload["segments"][5]["end_cycle"] = 119
    overlap_reject = expect_error("segment_overlap", overlap_payload, "SEGMENT_GAP_OR_OVERLAP")

    tamper_payload = valid_input()
    tamper_payload["segments"][0]["payload"]["metrics"]["total_net_r"] = 99.0
    tamper_reject = expect_error("payload_tamper", tamper_payload, "SEGMENT_PAYLOAD_SHA_MISMATCH")

    (OUT / "pass.json").write_text(json.dumps(passed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold_incomplete.json").write_text(json.dumps(incomplete, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "rollback_dd.json").write_text(json.dumps(rollback, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    negatives = [midcheck_reject, lineage_reject, overlap_reject, tamper_reject]
    (OUT / "negative_fixtures.json").write_text(json.dumps(negatives, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "state": "PASS_SHADOW200_READ_ONLY_ACCUMULATOR_FIXTURES",
        "pass_state": passed["state"],
        "hold_state": incomplete["state"],
        "rollback_state": rollback["state"],
        "segment_count": passed["segment_count"],
        "cycle_count": passed["cycle_count"],
        "negative_fixture_count": len(negatives),
        "midcheck_count": 12,
        "shadow_300c_allowed_fixture": True,
        "automatic_shadow_start": False,
        "real_shadow_started": False,
        "fixture_only": True,
        "production_threshold_authority": False,
        "runtime_bound": False,
        "next": "REAL_SOURCE_BOUND_SHADOW20_SEGMENTS_THEN_SHADOW300_READ_ONLY_ACCUMULATION",
        **SAFETY,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
