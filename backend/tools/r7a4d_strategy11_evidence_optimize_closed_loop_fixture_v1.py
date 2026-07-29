from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.research.strategy11_evidence_optimize_closed_loop_v1 import (
    INPUT_SCHEMA,
    OptimizeClosedLoopError,
    evaluate,
)

VERSION = "R7A4D_STRATEGY11_EVIDENCE_OPTIMIZE_CLOSED_LOOP_FIXTURE_V1"
AUTHORITY = {**SAFETY, "runtime_bound": False, "advisory_enabled": False}


def sha(label: str) -> str:
    return canonical_sha({"fixture": label})


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def policy() -> dict[str, Any]:
    return {
        "policy_id": "strategy11-evidence-optimize-closed-loop-fixture-v1",
        "min_event_sample_count": 20,
        "max_axis_generations_per_data_epoch": 2,
        "required_observer_burnin_cycles": 100,
        "unknown_taxonomy_rate_limit": 0.05,
        "entry_early_first3_mae_r": 0.60,
        "entry_late_pre_entry_mfe_r": 0.70,
        "entry_late_remaining_mfe_r": 0.20,
        "stop_tight_post_stop_mfe_r": 0.50,
        "stop_wide_distance_r": 1.20,
        "breakeven_activation_r": 0.75,
        "mfe_giveback_activation_r": 0.75,
        "target_undershoot_post_exit_mfe_r": 0.50,
        "time_exposure_bars": 20,
        "time_exposure_max_mfe_r": 0.25,
        "fingerprint_min_count": 5,
        "fingerprint_min_share": 0.20,
        "fingerprint_priority": [
            "MFE_GIVEBACK",
            "BREAKEVEN_MISSED",
            "STOP_TOO_TIGHT",
            "STOP_TOO_WIDE",
            "ENTRY_TOO_LATE",
            "ENTRY_TOO_EARLY",
            "TIME_EXPOSURE",
            "TARGET_UNDERSHOOT",
            "REGIME_MISMATCH",
            "VOLATILITY_MISMATCH",
            "VOLUME_FLOW_MISMATCH",
            "SESSION_CONCENTRATION",
            "SYMBOL_CONCENTRATION",
            "NO_SIGNAL",
        ],
        "candidate_catalog": {
            "MFE_GIVEBACK": [
                {
                    "candidate_id": "MFE_TRAIL_ACT075_ATR075",
                    "axis": "MFE_TRAILING",
                    "parameters": {"activation_r": 0.75, "distance_atr": 0.75},
                    "why": "Repeated source-bound MFE giveback cluster; preserve control and replay one bounded trailing axis.",
                },
                {
                    "candidate_id": "BE075_AFTER_MFE_GIVEBACK",
                    "axis": "BREAKEVEN",
                    "parameters": {"activation_r": 0.75, "offset_r": 0.0},
                    "why": "Fallback single-axis breakeven candidate after the trailing generation is exhausted.",
                },
            ],
            "ENTRY_TOO_LATE": [
                {
                    "candidate_id": "ENTRY_CONTEXT_RECLAIM_CONFIRMATION",
                    "axis": "ENTRY_CONTEXT_GATE",
                    "parameters": {"confirmation_catalog_id": "RECLAIM_CONFIRMATION_1"},
                    "why": "Entry occurs after most pre-entry excursion; test one bounded context confirmation definition.",
                }
            ],
            "ENTRY_TOO_EARLY": [
                {
                    "candidate_id": "CANDLE_STRUCTURE_PULLBACK_CONFIRMATION",
                    "axis": "CANDLE_STRUCTURE_GATE",
                    "parameters": {"confirmation_catalog_id": "PULLBACK_CONFIRMATION_1"},
                    "why": "First-three-bar adverse excursion clusters indicate premature entry timing.",
                }
            ],
            "STOP_TOO_TIGHT": [
                {
                    "candidate_id": "STOP_STRUCTURE_BUFFER_1",
                    "axis": "STOP",
                    "parameters": {"stop_catalog_id": "STRUCTURE_BUFFER_1"},
                    "why": "Post-stop favorable excursion cluster supports one bounded structure-buffer replay.",
                }
            ],
            "STOP_TOO_WIDE": [
                {
                    "candidate_id": "STOP_ATR_CAP_1",
                    "axis": "STOP",
                    "parameters": {"stop_catalog_id": "ATR_CAP_1"},
                    "why": "Losses are concentrated in oversized stop-distance events.",
                }
            ],
            "BREAKEVEN_MISSED": [
                {
                    "candidate_id": "BE075",
                    "axis": "BREAKEVEN",
                    "parameters": {"activation_r": 0.75, "offset_r": 0.0},
                    "why": "Trades reached the fixed MFE activation and later closed negative.",
                }
            ],
            "TIME_EXPOSURE": [
                {
                    "candidate_id": "TIME_STOP_20",
                    "axis": "TIME_STOP",
                    "parameters": {"bars": 20},
                    "why": "Long-held low-MFE loss cluster supports one bounded time-stop replay.",
                }
            ],
            "TARGET_UNDERSHOOT": [
                {
                    "candidate_id": "TARGET_RUNNER_SPLIT_1",
                    "axis": "TARGET",
                    "parameters": {"target_catalog_id": "RUNNER_SPLIT_1"},
                    "why": "Post-exit favorable excursion indicates target truncation.",
                }
            ],
            "REGIME_MISMATCH": [
                {
                    "candidate_id": "REGIME_ALIGNMENT_1",
                    "axis": "TREND_REGIME_GATE",
                    "parameters": {"regime_catalog_id": "ALIGNMENT_1"},
                    "why": "Failure-learning recurrence identifies a regime mismatch cluster.",
                }
            ],
            "VOLATILITY_MISMATCH": [
                {
                    "candidate_id": "VOLATILITY_CONTEXT_1",
                    "axis": "VOLATILITY_GATE",
                    "parameters": {"volatility_catalog_id": "CONTEXT_1"},
                    "why": "Execution-economics recurrence supports one bounded volatility context axis.",
                }
            ],
            "SESSION_CONCENTRATION": [
                {
                    "candidate_id": "SESSION_EXCLUSION_1",
                    "axis": "SESSION_GATE",
                    "parameters": {"session_catalog_id": "EXCLUDE_DOMINANT_LOSS_SESSION_1"},
                    "why": "Losses are concentrated in one source-bound session/window.",
                }
            ],
            "SYMBOL_CONCENTRATION": [
                {
                    "candidate_id": "SYMBOL_EXCLUSION_1",
                    "axis": "SYMBOL_EXCLUSION",
                    "parameters": {"symbol_catalog_id": "EXCLUDE_DOMINANT_LOSS_SYMBOL_1"},
                    "why": "Losses are concentrated in one source-bound symbol.",
                }
            ],
            "NO_SIGNAL": [
                {
                    "candidate_id": "ENTRY_CONTEXT_SIGNAL_RECOVERY_1",
                    "axis": "ENTRY_CONTEXT_GATE",
                    "parameters": {"entry_catalog_id": "SIGNAL_RECOVERY_1"},
                    "why": "Failure-learning reports repeated entry absence; test one bounded context axis only.",
                }
            ],
        },
    }


def events(source_sha: str, strategy_id: str = "trend_ma_macd") -> list[dict[str, Any]]:
    rows = []
    for index in range(30):
        if index < 12:
            pnl_r = -0.25
            mfe_r = 1.05
            mae_r = 0.42
            pre_entry_mfe_r = 0.10
            first3_mfe_r = 0.28
            first3_mae_r = 0.32
            stop_distance_r = 0.70
            post_stop_mfe_r = 0.20
            post_exit_mfe_r = 0.10
            bars_held = 12
            exit_reason = "STOP"
        elif index < 18:
            pnl_r = -0.10
            mfe_r = 0.88
            mae_r = 0.34
            pre_entry_mfe_r = 0.78
            first3_mfe_r = 0.08
            first3_mae_r = 0.25
            stop_distance_r = 0.65
            post_stop_mfe_r = 0.10
            post_exit_mfe_r = 0.05
            bars_held = 10
            exit_reason = "STOP"
        else:
            pnl_r = 1.20
            mfe_r = 1.45
            mae_r = 0.20
            pre_entry_mfe_r = 0.12
            first3_mfe_r = 0.55
            first3_mae_r = 0.18
            stop_distance_r = 0.68
            post_stop_mfe_r = 0.0
            post_exit_mfe_r = 0.20
            bars_held = 11
            exit_reason = "TARGET"
        rows.append({
            "event_id": f"fixture-event-{index:03d}",
            "event_ts": f"2026-07-{1 + index // 4:02d}T{index % 24:02d}:00:00Z",
            "strategy_id": strategy_id,
            "symbol": "BTCUSDT" if index % 3 else "ETHUSDT",
            "regime": "TREND" if index % 2 else "RANGE",
            "window_id": f"F{1 + index % 3}",
            "side": "LONG",
            "pnl_r": pnl_r,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "pre_entry_mfe_r": pre_entry_mfe_r,
            "first3_mfe_r": first3_mfe_r,
            "first3_mae_r": first3_mae_r,
            "stop_distance_r": stop_distance_r,
            "post_stop_mfe_r": post_stop_mfe_r,
            "post_exit_mfe_r": post_exit_mfe_r,
            "bars_to_mfe_peak": 7,
            "bars_held": bars_held,
            "exit_reason": exit_reason,
            "source_sha": source_sha,
            "feature_lineage_sha": sha(f"feature-lineage-{index}"),
        })
    return rows


def observer(observer_type: str, source_sha: str) -> dict[str, Any]:
    if observer_type == "ML_LIGHT":
        state = "PASS_ML_LIGHT_OBSERVATION"
        payload = {
            "evaluation_scores": [
                {"event_id": f"fixture-event-{index:03d}", "score": 0.80 if index < 18 else 0.20}
                for index in range(30)
            ],
            "calibration": {"brier_score": 0.08, "ece_score": 0.04},
            "drift": {"max_feature_psi": 0.03},
        }
    else:
        state = "PASS_FAILURE_LEARNING_OBSERVATION"
        payload = {
            "hypotheses": [
                {
                    "category": "EXIT_OR_RISK_SHAPE",
                    "sample_count": 12,
                    "hypothesis": "OBSERVE_EXIT_OR_RISK_SHAPE_RECURRENCE",
                    "authority": "OBSERVATION_ONLY",
                }
            ],
            "calibration": {"unknown_rate": 0.0},
            "drift": {"max_recurrence_delta_abs": 0.05},
        }
    normalized = {
        "state": state,
        "observer_type": observer_type,
        "source_sha": source_sha,
        "model_sha": sha(f"{observer_type}-model"),
        "config_sha": sha(f"{observer_type}-config"),
        "training_data_sha": sha(f"{observer_type}-training"),
        "feature_lineage_sha": sha(f"{observer_type}-feature-lineage"),
        "observer_manifest_sha": sha(f"{observer_type}-manifest"),
        "capabilities": ["READ_EVIDENCE", "EMIT_OBSERVATION", "EMIT_CALIBRATION", "REQUEST_HOLD"],
        "authority": copy.deepcopy(AUTHORITY),
        "payload": payload,
    }
    return normalized


def ledger(source_sha: str, data_sha: str, window_sha: str) -> dict[str, Any]:
    return {
        "strategy_id": "trend_ma_macd",
        "incumbent_candidate_sha": sha("trend-ma-macd-incumbent"),
        "tested_axes": ["ENTRY_CONTEXT_GATE"],
        "axis_generation_count": {"ENTRY_CONTEXT_GATE": 1, "MFE_TRAILING": 0, "BREAKEVEN": 0},
        "parameter_bounds": {
            "MFE_TRAILING": {"activation_r": [0.50, 1.00], "distance_atr": [0.50, 1.00]},
            "BREAKEVEN": {"activation_r": [0.50, 1.00]},
        },
        "tested_combinations": [],
        "remaining_axes": [
            "CANDLE_STRUCTURE_GATE",
            "TREND_REGIME_GATE",
            "VOLATILITY_GATE",
            "VOLUME_FLOW_GATE",
            "MOMENTUM_GATE",
            "SESSION_GATE",
            "SYMBOL_EXCLUSION",
            "STOP",
            "TARGET",
            "BREAKEVEN",
            "PARTIAL",
            "MFE_TRAILING",
            "TIME_STOP",
        ],
        "next_axis": "MFE_TRAILING",
        "new_data_epoch": 1,
        "W1_epoch": 0,
        "sealed_epoch": 0,
        "input_sha": sha("ledger-input"),
        "source_sha": source_sha,
        "data_sha": data_sha,
        "window_sha": window_sha,
        "prompt_sha": sha("ledger-prompt"),
        "response_sha": sha("ledger-response"),
        "authority": copy.deepcopy(AUTHORITY),
    }


def evidence(runtime_ready: bool) -> dict[str, Any]:
    source_sha = sha("source")
    stage_states = {
        "DISCOVERY": "PASS_W1_NONOVERLAP" if runtime_ready else "PASS_F1_F2_F3_IMMUTABLE",
        "W1": "PASS" if runtime_ready else "WAIT_DATA",
        "W2": "PASS" if runtime_ready else "WAIT_DATA",
        "W3": "PASS" if runtime_ready else "WAIT_DATA",
        "NEW_SEALED": "PASS" if runtime_ready else "WAIT_DATA",
        "SHADOW300": "PASS_SHADOW300_READ_ONLY_COMPLETION" if runtime_ready else "WAIT_SHADOW300",
        "OBSERVER_GATE": "PASS_OBSERVER_ONLY_GATE" if runtime_ready else "WAIT_OBSERVER_GATE",
        "HUMAN_GOVERNANCE": "PASS_HUMAN_GOVERNANCE_PREFLIGHT" if runtime_ready else "WAIT_HUMAN_GOVERNANCE",
    }
    return {
        "source_sha": source_sha,
        "strategy_source_sha": sha("strategy-source"),
        "data_sha": sha("data"),
        "window_sha": sha("window"),
        "manifest_sha": sha("manifest"),
        "head_sha": sha("head"),
        "observer_bundle_sha": sha("observer-bundle"),
        "shadow300_completion_sha": sha("shadow300-completion"),
        "human_governance_decision_sha": sha("human-governance"),
        "stage_states": stage_states,
        "observer_burnin_cycles": 100 if runtime_ready else 0,
        "observer_source_parity_failures": 0,
        "observer_drift_breaches": 0,
        "observer_calibration_breaches": 0,
        "unknown_taxonomy_rate": 0.0,
    }


def request(runtime_ready: bool) -> dict[str, Any]:
    ev = evidence(runtime_ready)
    return {
        "schema_version": INPUT_SCHEMA,
        "authority": copy.deepcopy(AUTHORITY),
        "policy": policy(),
        "evidence": ev,
        "search_ledger": ledger(ev["source_sha"], ev["data_sha"], ev["window_sha"]),
        "observers": {
            "ML_LIGHT": observer("ML_LIGHT", ev["source_sha"]),
            "FAILURE_LEARNING": observer("FAILURE_LEARNING", ev["source_sha"]),
        },
        "events": events(ev["source_sha"]),
    }


def expect_error(payload: dict[str, Any], code: str) -> str:
    try:
        evaluate(payload)
    except OptimizeClosedLoopError as exc:
        message = str(exc)
        if not message.startswith(code):
            raise AssertionError((code, message)) from exc
        return message
    raise AssertionError(f"EXPECTED_ERROR:{code}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pre_runtime_request = request(False)
    pre_runtime = evaluate(pre_runtime_request)
    assert pre_runtime["state"] == "PASS_RESEARCH_OPTIMIZE_CLOSED_LOOP_PLAN"
    assert pre_runtime["selected_fingerprint"]["fingerprint"] == "MFE_GIVEBACK"
    assert pre_runtime["next_candidate_proposal"]["candidate_id"] == "MFE_TRAIL_ACT075_ATR075"
    assert pre_runtime["next_candidate_proposal"]["axis"] == "MFE_TRAILING"
    assert pre_runtime["candidate_count"] == 1
    assert pre_runtime["runtime_bridge"]["state"] == "WAIT_REAL_SHADOW300_AND_100C_BURNIN"
    assert pre_runtime["runtime_bridge"]["runtime_observer_bridge_allowed"] is False

    runtime_request = request(True)
    runtime_ready = evaluate(runtime_request)
    assert runtime_ready["state"] == "PASS_READ_ONLY_RUNTIME_OBSERVER_BRIDGE_READY"
    assert runtime_ready["runtime_bridge"]["state"] == "READY_READ_ONLY_OBSERVER_BRIDGE"
    assert runtime_ready["runtime_bridge"]["runtime_observer_bridge_allowed"] is True
    assert runtime_ready["runtime_bridge"]["strategy_write_allowed"] is False
    assert runtime_ready["runtime_bridge"]["threshold_write_allowed"] is False
    assert runtime_ready["runtime_bridge"]["portfolio_weight_write_allowed"] is False
    assert runtime_ready["runtime_bridge"]["ledger_write_allowed"] is False
    assert runtime_ready["runtime_bridge"]["paper_live_order_allowed"] is False
    assert runtime_ready["live_activation_allowed"] is False
    assert runtime_ready["order_submission_allowed"] is False

    exhausted_request = request(False)
    exhausted_request["search_ledger"]["axis_generation_count"].update({"MFE_TRAILING": 2, "BREAKEVEN": 2, "PARTIAL": 2})
    exhausted = evaluate(exhausted_request)
    assert exhausted["state"] == "WAIT_NEW_EVIDENCE"
    assert exhausted["next_candidate_proposal"] is None
    assert exhausted["incumbent_retained"] is True

    duplicate_request = request(False)
    duplicate_request["events"][1]["event_id"] = duplicate_request["events"][0]["event_id"]
    duplicate_error = expect_error(duplicate_request, "DUPLICATE_EVENT_ID")

    unsafe_request = request(False)
    unsafe_request["authority"]["execution_allowed"] = True
    unsafe_error = expect_error(unsafe_request, "AUTHORITY_MISMATCH")

    multi_axis_request = request(False)
    multi_axis_request["policy"]["candidate_catalog"]["MFE_GIVEBACK"][0]["axis"] = "TARGET"
    multi_axis_error = expect_error(multi_axis_request, "CATALOG_AXIS_INVALID")

    summary = {
        "schema_version": "strategy11.evidence_optimize_closed_loop.fixture.summary.v1",
        "version": VERSION,
        "state": "PASS_EVIDENCE_OPTIMIZE_CLOSED_LOOP_FIXTURE",
        "pre_runtime_state": pre_runtime["state"],
        "runtime_ready_state": runtime_ready["state"],
        "exhausted_state": exhausted["state"],
        "selected_fingerprint": pre_runtime["selected_fingerprint"]["fingerprint"],
        "selected_candidate_id": pre_runtime["next_candidate_proposal"]["candidate_id"],
        "selected_axis": pre_runtime["next_candidate_proposal"]["axis"],
        "negative_errors": [duplicate_error, unsafe_error, multi_axis_error],
        "fixture_only": True,
        "real_strategy_artifact_consumed": False,
        "runtime_bound": False,
        "live_activation_allowed": False,
        "order_submission_allowed": False,
        "next": "SOURCE_BOUND_REAL_GENERATION_ARTIFACT_ADAPTER_THEN_REAL_SHADOW300_100C_BURNIN",
        **SAFETY,
    }
    summary["fixture_sha"] = canonical_sha(summary)

    atomic_json(args.out / "pre_runtime.json", pre_runtime)
    atomic_json(args.out / "runtime_ready.json", runtime_ready)
    atomic_json(args.out / "exhausted.json", exhausted)
    atomic_json(args.out / "summary.json", summary)
    print(summary["state"], summary["selected_fingerprint"], summary["selected_candidate_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
