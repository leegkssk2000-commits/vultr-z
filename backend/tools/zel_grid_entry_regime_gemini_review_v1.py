from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import zel_strategy_loss_attribution_gemini_v1 as gemini_base

VERSION = "ZEL_GRID_ENTRY_REGIME_GEMINI_REVIEW_V1"
SCHEMA = "zel.grid_entry_regime_gemini_review.receipt.v1"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def compact_metrics(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trade_count": value.get("trade_count"),
        "net_R": value.get("net_R"),
        "profit_factor": value.get("profit_factor"),
        "max_drawdown_R": value.get("max_drawdown_R"),
        "win_rate": value.get("win_rate"),
    }


def compact_profile(reconstruction: Mapping[str, Any]) -> dict[str, Any]:
    regimes = reconstruction.get("reconstructed_regime_metrics")
    windows = reconstruction.get("reconstructed_regime_window_metrics")
    if not isinstance(regimes, Mapping) or not isinstance(windows, Mapping):
        raise RuntimeError("RECONSTRUCTION_METRICS_MISSING")
    total_net = sum(float(row.get("net_R") or 0.0) for row in regimes.values() if isinstance(row, Mapping))
    total_trades = sum(int(row.get("trade_count") or 0) for row in regimes.values() if isinstance(row, Mapping))
    candidate_evidence: dict[str, Any] = {}
    for regime, row in sorted(regimes.items()):
        if not isinstance(row, Mapping):
            continue
        regime_net = float(row.get("net_R") or 0.0)
        regime_trades = int(row.get("trade_count") or 0)
        by_window: dict[str, Any] = {}
        for window in ("1m_w1", "1m_w2", "1m_w3"):
            value = windows.get(f"{regime}|{window}")
            by_window[window] = compact_metrics(value) if isinstance(value, Mapping) else {
                "trade_count": 0,
                "net_R": 0.0,
                "profit_factor": None,
                "max_drawdown_R": 0.0,
                "win_rate": None,
            }
        candidate_evidence[str(regime)] = {
            "include_only": compact_metrics(row),
            "exclude_regime_counterfactual": {
                "remaining_trade_count": total_trades - regime_trades,
                "remaining_net_R": total_net - regime_net,
                "delta_net_R": -regime_net,
                "trade_retention_pct": (total_trades - regime_trades) / max(total_trades, 1) * 100.0,
                "window_delta_net_R": {
                    window: -float(details.get("net_R") or 0.0)
                    for window, details in by_window.items()
                },
            },
            "by_window": by_window,
        }
    comparison = reconstruction.get("entry_range_vs_exit_neutral")
    if not isinstance(comparison, Mapping):
        comparison = {}
    entry_range = reconstruction.get("entry_range_metrics")
    exit_neutral = reconstruction.get("exit_neutral_metrics")
    return {
        "strategy_id": reconstruction.get("strategy_id"),
        "reconstruction_state": reconstruction.get("state"),
        "trade_count": reconstruction.get("trade_count"),
        "reconstructed_count": reconstruction.get("reconstructed_count"),
        "unmatched_count": reconstruction.get("unmatched_count"),
        "entry_regime_counts": reconstruction.get("reconstructed_regime_counts"),
        "total_net_R": total_net,
        "candidate_evidence": candidate_evidence,
        "legacy_exit_neutral_diagnostic": {
            "invalid_for_entry_filter": True,
            "entry_range_count": comparison.get("entry_range_count"),
            "exit_neutral_count": comparison.get("exit_neutral_count"),
            "intersection_count": comparison.get("intersection_count"),
            "jaccard": comparison.get("jaccard"),
            "entry_range_net_R": entry_range.get("net_R") if isinstance(entry_range, Mapping) else None,
            "exit_neutral_net_R": exit_neutral.get("net_R") if isinstance(exit_neutral, Mapping) else None,
        },
        "causal_contract": {
            "entry_prefix_only": True,
            "classifier_external_to_frozen_source": True,
            "context_owner_sha256": reconstruction.get("context_owner_sha256"),
            "regime_owner_sha256": reconstruction.get("regime_owner_sha256"),
            "single_axis_only": True,
            "w1_select_then_freeze_w2_w3": True,
            "selection_authority": False,
        },
    }


def auditor_prompt(profile: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "legacy_exit_neutral_rejected": True,
        "causal_findings": ["..."],
        "regime_only_fork_valid": False,
        "recommended_next_test": "TEST_TREND_STRENGTH_SINGLE_AXIS|TEST_DIRECTIONAL_ROUTER_SINGLE_AXIS|RETIRE_GRID_REBALANCE|NEED_MORE_CAUSAL_EVIDENCE",
        "why": "...",
        "minimum_nonoverlap_gates": ["..."],
        "falsification_conditions": ["..."],
    }
    return (
        "You are a senior quantitative causal auditor. Review only the aggregate entry-time evidence. "
        "The old exit-neutral subset was computed at close and is forbidden as an entry-filter claim. "
        "All recommendations remain research-only, single-axis, W1-selected and frozen before W2/W3. "
        "Never recommend production, shadow, paper, live, selection or promotion. Return strict JSON only.\n\n"
        f"PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def designer_prompt(profile: Mapping[str, Any], audit: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "proposal": "TEST_TREND_STRENGTH_SINGLE_AXIS|TEST_DIRECTIONAL_ROUTER_SINGLE_AXIS|RETIRE_GRID_REBALANCE|NEED_MORE_CAUSAL_EVIDENCE",
        "single_axis_definition": "...",
        "w1_candidate_construction": ["..."],
        "frozen_w2_w3_test": ["..."],
        "retention_and_power_constraints": ["..."],
        "failure_rule": "...",
        "why_not_regime_only": "...",
    }
    return (
        "You are a systematic strategy designer. Select at most one next research axis. "
        "Do not choose a numeric threshold from these aggregates; thresholds must be generated only from W1 quantiles "
        "and frozen before W2/W3. Reject the legacy close-time neutral subset. Return strict JSON only.\n\n"
        f"PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"AUDITOR={json.dumps(audit, ensure_ascii=False, sort_keys=True)}\n"
        f"SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def red_team_prompt(profile: Mapping[str, Any], audit: Mapping[str, Any], design: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "decision": "TEST_TREND_STRENGTH_SINGLE_AXIS|TEST_DIRECTIONAL_ROUTER_SINGLE_AXIS|RETIRE_GRID_REBALANCE|NEED_MORE_CAUSAL_EVIDENCE",
        "legacy_exit_neutral_rejected": True,
        "fatal_blockers": ["..."],
        "overfit_paths": ["..."],
        "required_exact_tests": ["..."],
        "why": "...",
    }
    return (
        "You are the independent quantitative red-team. Falsify the audit and design. HOLD if the plan uses close-time regime, "
        "selects with W2/W3, combines axes, ignores all-negative entry-regime evidence, or claims edge before fixed non-overlap validation. "
        "Return one allowed decision and strict JSON only.\n\n"
        f"PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"AUDITOR={json.dumps(audit, ensure_ascii=False, sort_keys=True)}\n"
        f"DESIGNER={json.dumps(design, ensure_ascii=False, sort_keys=True)}\n"
        f"SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconstruction", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reconstruction = read_object(args.reconstruction)
    policy = read_object(args.policy)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    if reconstruction.get("state") != "PASS_GRID_ENTRY_REGIME_RECONSTRUCTED":
        raise RuntimeError("RECONSTRUCTION_NOT_PASS")
    if int(reconstruction.get("trade_count") or 0) != int(policy["expected_trade_count"]):
        raise RuntimeError("TRADE_COUNT_MISMATCH")
    if reconstruction.get("context_owner_sha256") != policy["expected_context_owner_sha256"]:
        raise RuntimeError("CONTEXT_OWNER_SHA_MISMATCH")
    if reconstruction.get("regime_owner_sha256") != policy["expected_regime_owner_sha256"]:
        raise RuntimeError("REGIME_OWNER_SHA_MISMATCH")
    if reconstruction.get("reconstructed_regime_counts") != policy["expected_regime_counts"]:
        raise RuntimeError("REGIME_COUNT_MISMATCH")

    profile = compact_profile(reconstruction)
    models = [str(value) for value in policy["models"]]
    tokens = int(policy["max_output_tokens"])
    temperature = float(policy["temperature"])
    model1, audit = gemini_base.call_gemini(api_key, models, auditor_prompt(profile), tokens, temperature)
    model2, design = gemini_base.call_gemini(api_key, models, designer_prompt(profile, audit), tokens, temperature)
    model3, red_team = gemini_base.call_gemini(api_key, models, red_team_prompt(profile, audit, design), tokens, temperature)

    allowed = set(str(value) for value in policy["allowed_next_tests"])
    audit_decision = str(audit.get("recommended_next_test") or "NEED_MORE_CAUSAL_EVIDENCE")
    design_decision = str(design.get("proposal") or "NEED_MORE_CAUSAL_EVIDENCE")
    red_decision = str(red_team.get("decision") or "NEED_MORE_CAUSAL_EVIDENCE")
    consensus = (
        audit_decision == design_decision == red_decision
        and red_decision in allowed
        and str(audit.get("status")) == "PASS"
        and str(design.get("status")) == "PASS"
        and str(red_team.get("status")) == "PASS"
        and audit.get("legacy_exit_neutral_rejected") is True
        and red_team.get("legacy_exit_neutral_rejected") is True
    )
    selected = red_decision if consensus else "NEED_MORE_CAUSAL_EVIDENCE"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_ENTRY_REGIME_GEMINI_CONSENSUS" if consensus else "HOLD_GRID_ENTRY_REGIME_GEMINI_NO_CONSENSUS",
        "reconstruction_receipt_sha256": reconstruction.get("receipt_sha256"),
        "profile_sha256": gemini_base.stable_sha(profile),
        "gemini_call_count": 3,
        "models_used": [model1, model2, model3],
        "auditor": audit,
        "designer": design,
        "red_team": red_team,
        "decision_trace": {
            "auditor": audit_decision,
            "designer": design_decision,
            "red_team": red_decision,
            "consensus": consensus,
            "selected_next_test": selected,
        },
        "legacy_exit_neutral_rejected": True,
        "legacy_grid_neutral_fork_retired": True,
        "next_research_allowed": consensus,
        "raw_code_sent": False,
        "raw_trades_sent": False,
        "raw_event_ids_sent": False,
        "credentials_sent": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": selected,
    }
    receipt["receipt_sha256"] = gemini_base.stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "models": receipt["models_used"], "decision_trace": receipt["decision_trace"], "next": receipt["next"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
