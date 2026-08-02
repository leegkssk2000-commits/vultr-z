from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import zel_strategy_loss_attribution_gemini_v1 as gemini_base

VERSION = "ZEL_GRID_NEUTRAL_LINEAGE_GEMINI_REVIEW_V1"
SCHEMA = "zel.grid_neutral.lineage_gemini_review.receipt.v1"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("AUDIT_NOT_OBJECT")
    return value


def compact_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": row.get("path"),
        "sha256": row.get("sha256"),
        "static_no_lookahead": row.get("static_no_lookahead"),
        "unsafe_pattern_counts": row.get("unsafe_pattern_counts"),
        "causal_pattern_counts": row.get("causal_pattern_counts"),
        "regime_match_line_numbers": [
            item.get("line")
            for item in row.get("regime_matches", [])
            if isinstance(item, Mapping)
        ][:20],
    }


def compact_audit(audit: Mapping[str, Any]) -> dict[str, Any]:
    ledger = audit.get("trade_ledger") if isinstance(audit.get("trade_ledger"), Mapping) else {}
    return {
        "audit_state": audit.get("state"),
        "strategy_id": audit.get("strategy_id"),
        "counts": {
            "strategy_source_paths": audit.get("strategy_source_count"),
            "canonical_strategy_source": audit.get("canonical_strategy_source_count"),
            "unique_strategy_source_sha": audit.get("unique_strategy_source_sha_count"),
            "mirror_strategy_source": audit.get("mirror_strategy_source_count"),
            "canonical_binding_reference": audit.get("canonical_binding_reference_count"),
            "registry_reference": audit.get("registry_reference_count"),
            "replay_reference": audit.get("replay_reference_count"),
            "regime_candidate": audit.get("regime_candidate_count"),
            "static_no_lookahead_regime_candidate": audit.get("static_no_lookahead_regime_candidate_count"),
        },
        "source_identity": {
            "canonical_path": audit.get("canonical_strategy_source_path"),
            "canonical_sha256": audit.get("canonical_strategy_source_sha256"),
            "active_owner_unique": audit.get("active_owner_unique"),
            "all_mirrors_content_identical": audit.get("all_mirrors_content_identical"),
        },
        "blockers": audit.get("blockers"),
        "strategy_sources": [
            {
                "path": row.get("path"),
                "sha256": row.get("sha256"),
                "roles": row.get("roles"),
            }
            for row in audit.get("strategy_sources", [])
            if isinstance(row, Mapping)
        ],
        "registry_references": [
            {
                "path": row.get("path"),
                "sha256": row.get("sha256"),
                "roles": row.get("roles"),
            }
            for row in audit.get("registry_references", [])[:20]
            if isinstance(row, Mapping)
        ],
        "replay_references": [
            {
                "path": row.get("path"),
                "sha256": row.get("sha256"),
                "roles": row.get("roles"),
            }
            for row in audit.get("replay_references", [])[:30]
            if isinstance(row, Mapping)
        ],
        "regime_candidates": [
            compact_candidate(row)
            for row in audit.get("regime_derivation_candidates", [])[:40]
            if isinstance(row, Mapping)
        ],
        "ledger": {
            "trade_count": ledger.get("trade_count"),
            "neutral_trade_count": ledger.get("neutral_trade_count"),
            "net_R": ledger.get("net_R"),
            "neutral_net_R": ledger.get("neutral_net_R"),
            "regime_counts": ledger.get("regime_counts"),
            "window_regime_counts": ledger.get("window_regime_counts"),
            "missing_entry_timestamp_count": ledger.get("missing_entry_timestamp_count"),
        },
        "source_level_replay_allowed_by_static_audit": audit.get("source_level_replay_allowed"),
    }


def causal_prompt(profile: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "causal_assessment": "...",
        "confirmed_facts": ["..."],
        "unproven_assumptions": ["..."],
        "lookahead_risks": [{"risk": "...", "severity": "LOW|MEDIUM|HIGH", "required_proof": "..."}],
        "source_replay_preconditions": ["..."],
        "recommended_action": "STAGE_TMP_FORK|RESOLVE_LINEAGE|BLOCK",
    }
    return (
        "You are a senior quantitative research auditor. Review only the anonymized structural facts below. "
        "The proposed change is a NEW grid_rebalance fork that accepts entries only when the replay regime is neutral. "
        "Do not treat a static scan as proof of causality. Distinguish source identity, registry binding, replay ownership, "
        "regime timestamp availability and lookahead risk. Never recommend production, shadow, paper or live execution. "
        "Return strict JSON only.\n\n"
        f"AUDIT_PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def red_team_prompt(profile: Mapping[str, Any], causal_review: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "decision": "STAGE_TMP_FORK|RESOLVE_LINEAGE|BLOCK",
        "fatal_blockers": ["..."],
        "false_positive_paths": ["..."],
        "minimum_exact_tests": ["..."],
        "parity_targets": {
            "total_trades": 248,
            "w1_trades": 133,
            "w2_trades": 66,
            "w3_trades": 49,
            "net_R": 64.92212329597572
        },
        "why": "...",
    }
    return (
        "You are the independent red-team. Attempt to falsify the causal review and the neutral-only fork. "
        "Reject any plan that gates on a regime label computed after entry, changes incumbent source, uses ledger filtering as source parity, "
        "or lacks exact event-ID subset proof. The fork may only be staged under /tmp with no authority. Return strict JSON only.\n\n"
        f"AUDIT_PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"CAUSAL_REVIEW={json.dumps(causal_review, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    audit = read_object(args.audit)
    policy = read_object(args.policy)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    models = [str(value) for value in policy["models"]]
    profile = compact_audit(audit)
    model1, causal = gemini_base.call_gemini(
        api_key,
        models,
        causal_prompt(profile),
        int(policy["max_output_tokens"]),
        float(policy["temperature"]),
    )
    model2, red_team = gemini_base.call_gemini(
        api_key,
        models,
        red_team_prompt(profile, causal),
        int(policy["max_output_tokens"]),
        float(policy["temperature"]),
    )
    decision = str(red_team.get("decision") or "RESOLVE_LINEAGE")
    stage_allowed = (
        audit.get("source_level_replay_allowed") is True
        and str(causal.get("status")) == "PASS"
        and str(red_team.get("status")) == "PASS"
        and decision == "STAGE_TMP_FORK"
    )
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_NEUTRAL_LINEAGE_GEMINI_READY_FOR_TMP_FORK" if stage_allowed else "HOLD_GRID_NEUTRAL_LINEAGE_GEMINI_REVIEW",
        "audit_receipt_sha256": audit.get("receipt_sha256"),
        "profile_sha256": gemini_base.stable_sha(profile),
        "gemini_call_count": 2,
        "models_used": [model1, model2],
        "causal_review": causal,
        "red_team": red_team,
        "tmp_fork_stage_allowed": stage_allowed,
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
        "next": "STAGE_TMP_GRID_NEUTRAL_FORK" if stage_allowed else "RESOLVE_LINEAGE_BLOCKERS",
    }
    receipt["receipt_sha256"] = gemini_base.stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "models": receipt["models_used"],
        "tmp_fork_stage_allowed": stage_allowed,
        "decision": decision,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
