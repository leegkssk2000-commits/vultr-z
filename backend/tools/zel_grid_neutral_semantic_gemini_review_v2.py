from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import zel_strategy_loss_attribution_gemini_v1 as gemini_base

VERSION = "ZEL_GRID_NEUTRAL_SEMANTIC_GEMINI_REVIEW_V2"
SCHEMA = "zel.grid_neutral.semantic_gemini_review.receipt.v2"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def compact_profile(
    audit: Mapping[str, Any],
    authority: Mapping[str, Any],
    reconstruction: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "strategy_id": reconstruction.get("strategy_id"),
        "source_lineage": {
            "audit_state": audit.get("state"),
            "source_authority_state": authority.get("state"),
            "active_owner_unique": audit.get("active_owner_unique"),
            "all_mirrors_content_identical": audit.get("all_mirrors_content_identical"),
            "canonical_source_sha256": audit.get("canonical_strategy_source_sha256"),
            "engine_sha256": reconstruction.get("engine_sha256"),
            "context_owner_sha256": reconstruction.get("context_owner_sha256"),
            "regime_owner_sha256": reconstruction.get("regime_owner_sha256"),
        },
        "semantic_correction": {
            "ledger_top_level_regime_semantics": "EXIT_FEATURE_REGIME",
            "entry_regime_reconstruction_method": "FROZEN_1M_PREFIX_THROUGH_ENTRY_BAR_PLUS_MARKET_CONTEXT_COMPUTE_AND_DERIVE_REGIME",
            "trade_count": reconstruction.get("trade_count"),
            "reconstructed_count": reconstruction.get("reconstructed_count"),
            "unmatched_count": reconstruction.get("unmatched_count"),
            "regime_counts": reconstruction.get("reconstructed_regime_counts"),
            "entry_range_metrics": reconstruction.get("entry_range_metrics"),
            "exit_neutral_metrics": reconstruction.get("exit_neutral_metrics"),
            "entry_range_vs_exit_neutral": reconstruction.get("entry_range_vs_exit_neutral"),
            "window_metrics": {
                key: value
                for key, value in reconstruction.get("reconstructed_regime_window_metrics", {}).items()
                if str(key).startswith("range|")
            },
        },
        "policy": {
            "required_decision": policy.get("required_decision"),
            "entry_range_reference": policy.get("entry_range_reference"),
            "exit_regime_neutral_reference": policy.get("exit_regime_neutral_reference"),
        },
        "safety": {
            "canonical_mutated": False,
            "runtime_mutated": False,
            "formal_ledger_mutated": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        },
    }


def causal_prompt(profile: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "semantic_conclusion": "EXIT_REGIME_FILTER_INVALID_AS_ENTRY_POLICY|ENTRY_RANGE_EDGE_VALID|UNRESOLVED",
        "confirmed_facts": ["..."],
        "fatal_method_errors": ["..."],
        "economic_assessment": "...",
        "recommended_action": "BLOCK_NEUTRAL_ENTRY_FORK|HOLD_FOR_MORE_EVIDENCE|ALLOW_TMP_FORK",
    }
    return (
        "You are a senior quantitative causal auditor. The previous candidate filtered trades using a top-level ledger regime. "
        "The corrected structural evidence proves that field was written from EXIT features. Entry regimes were reconstructed from each immutable 1m prefix through its entry bar using the identified market-context and derive-regime owners. "
        "Evaluate whether the original neutral-only entry fork remains valid. A profitable EXIT-regime subset is not an entry policy. "
        "Do not recommend Shadow, Paper, Live, promotion or canonical changes. Return strict JSON only.\n\n"
        f"PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def red_team_prompt(profile: Mapping[str, Any], causal: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "decision": "BLOCK_NEUTRAL_ENTRY_FORK|HOLD_FOR_MORE_EVIDENCE|ALLOW_TMP_FORK",
        "fatal_blockers": ["..."],
        "false_positive_mechanism": "...",
        "minimum_future_test": "...",
        "why": "...",
    }
    return (
        "You are the independent red-team. Attempt to falsify the corrected conclusion. "
        "ALLOW_TMP_FORK is forbidden unless the ENTRY-time regime candidate itself has positive net R, profit factor above 1, nonzero W1/W2/W3 samples and no semantic mismatch. "
        "The EXIT-neutral cohort must not be treated as causal entry evidence. Return strict JSON only.\n\n"
        f"PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"CAUSAL_REVIEW={json.dumps(causal, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--reconstruction", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    audit = read_object(args.audit)
    authority = read_object(args.authority)
    reconstruction = read_object(args.reconstruction)
    policy = read_object(args.policy)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    models = [str(value) for value in policy["models"]]
    profile = compact_profile(audit, authority, reconstruction, policy)
    model1, causal = gemini_base.call_gemini(
        api_key, models, causal_prompt(profile), int(policy["max_output_tokens"]), float(policy["temperature"])
    )
    model2, red_team = gemini_base.call_gemini(
        api_key, models, red_team_prompt(profile, causal), int(policy["max_output_tokens"]), float(policy["temperature"])
    )

    entry = reconstruction.get("entry_range_metrics") if isinstance(reconstruction.get("entry_range_metrics"), Mapping) else {}
    windows = reconstruction.get("reconstructed_regime_window_metrics") if isinstance(reconstruction.get("reconstructed_regime_window_metrics"), Mapping) else {}
    economic_gate = (
        float(entry.get("net_R") or 0.0) > 0.0
        and float(entry.get("profit_factor") or 0.0) > 1.0
        and all(int((windows.get(f"range|1m_w{index}") or {}).get("trade_count") or 0) > 0 for index in (1, 2, 3))
    )
    decision = str(red_team.get("decision") or "HOLD_FOR_MORE_EVIDENCE")
    allow = (
        economic_gate
        and str(causal.get("status")) == "PASS"
        and str(red_team.get("status")) == "PASS"
        and decision == "ALLOW_TMP_FORK"
    )
    blocked = not allow
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_NEUTRAL_SEMANTIC_CORRECTION_FORK_BLOCKED" if blocked else "PASS_GRID_NEUTRAL_ENTRY_FORK_READY_FOR_TMP",
        "audit_receipt_sha256": audit.get("receipt_sha256"),
        "authority_receipt_sha256": authority.get("receipt_sha256"),
        "reconstruction_receipt_sha256": reconstruction.get("receipt_sha256"),
        "profile_sha256": gemini_base.stable_sha(profile),
        "gemini_call_count": 2,
        "models_used": [model1, model2],
        "causal_review": causal,
        "red_team": red_team,
        "economic_gate_pass": economic_gate,
        "tmp_fork_stage_allowed": allow,
        "fork_blocked": blocked,
        "raw_code_sent": False,
        "raw_trades_sent": False,
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
        "next": "REJECT_GRID_NEUTRAL_ENTRY_FORK_AND_RETURN_TO_STRATEGY_LOSS_QUEUE" if blocked else "STAGE_TMP_GRID_NEUTRAL_ENTRY_FORK",
    }
    receipt["receipt_sha256"] = gemini_base.stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "models": receipt["models_used"],
        "decision": decision,
        "economic_gate_pass": economic_gate,
        "tmp_fork_stage_allowed": allow,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
