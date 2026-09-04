#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha

SCHEMA = "zel.g5a.alpha_proof_preflight.v1"
AUTHORITY = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}

# Architecture-factory candidate_sha256 is intentionally preserved as source
# lineage. Alpha Proof gets a new proof-candidate identity because its gate
# requires research_only to be part of the hashed candidate object.
PROOF_CANDIDATE_FIELDS = (
    "candidate_id",
    "mode",
    "strategy_id",
    "architecture_family",
    "changed_axis",
    "mechanism",
    "payer",
    "entry_event",
    "direction_rule",
    "native_horizon",
    "regime_owner",
    "invalidation",
    "exit_logic",
    "time_stop_rationale",
    "turnover_cost_budget",
    "required_sources",
    "evidence_ids",
    "expected_move_cost_multiple_target",
    "falsification",
    "forbidden_changes",
    "why_distinct",
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _authority_ok(receipt: Mapping[str, Any]) -> bool:
    return (
        receipt.get("selection_authority") is False
        and receipt.get("promotion_authority") is False
        and receipt.get("execution_authority") == "NONE"
        and receipt.get("order_authority") == "BLOCKED"
        and receipt.get("live_trade_authority") == "BLOCKED"
        and receipt.get("exchange_order_submitted") is False
        and int(receipt.get("protected_mutations") or 0) == 0
    )


def _proof_candidate(source: Mapping[str, Any]) -> dict[str, Any]:
    core = {k: source.get(k) for k in PROOF_CANDIDATE_FIELDS}
    core["research_only"] = True
    core["source_architecture_candidate_sha256"] = str(source.get("candidate_sha256") or "")
    core["candidate_sha256"] = alpha.sha(core)
    return core


def _provider_reviews(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    reviews = source.get("cross_reviews")
    if not isinstance(reviews, Mapping):
        return []
    out: list[dict[str, Any]] = []
    for provider, raw in sorted(reviews.items()):
        if not isinstance(raw, Mapping):
            continue
        out.append({
            "provider": str(provider),
            "successful": raw.get("successful") is True,
            "decision": str(raw.get("decision") or ""),
            "model": raw.get("model"),
            "input_sha": raw.get("input_sha"),
            "prompt_sha": raw.get("prompt_sha"),
            "response_sha": raw.get("response_sha"),
            "resolved_by_evidence": raw.get("resolved_by_evidence") is True,
        })
    return out


def build_partial_bundle(source: Mapping[str, Any]) -> dict[str, Any]:
    """Map only source-bound facts; never synthesize missing P0-P6 evidence."""
    return {
        "candidate": _proof_candidate(source),
        "multi_ai_adversarial_review": {
            # No controller review is invented. The gate must HOLD until a real
            # source-bound review SHA exists.
            "controller_review_sha": "",
            "provider_reviews": _provider_reviews(source),
        },
    }


def evaluate(factory_receipt: Mapping[str, Any]) -> dict[str, Any]:
    if not _authority_ok(factory_receipt):
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_G5A_AUTHORITY_INVARIANT",
            "action": "hold",
            "source_candidate_id": None,
            "source_architecture_candidate_sha256": None,
            "alpha_proof_state": None,
            "failed_gates": ["AUTHORITY_INVARIANT"],
            "deterministic_replay_authorized": False,
            "g5b_fresh_boundary_created": False,
            "next": "RESTORE_G5A_AUTHORITY_BOUNDARY",
            **AUTHORITY,
        }
        result["receipt_sha256"] = alpha.sha(result)
        return result

    source = factory_receipt.get("next_experiment_candidate")
    if not isinstance(source, Mapping):
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_G5A_NO_ALPHA_PROOF_INPUT",
            "action": "hold",
            "source_candidate_id": None,
            "source_architecture_candidate_sha256": None,
            "alpha_proof_state": None,
            "failed_gates": ["NO_CANDIDATE"],
            "deterministic_replay_authorized": False,
            "g5b_fresh_boundary_created": False,
            "next": "WAIT_FOR_SOURCE_READY_G5A_CANDIDATE",
            **AUTHORITY,
        }
        result["receipt_sha256"] = alpha.sha(result)
        return result

    bundle = build_partial_bundle(source)
    proof = alpha.evaluate_bundle(bundle)
    failed = [str(g.get("gate")) for g in proof.get("gates") or [] if g.get("passed") is not True]
    proof_pass = proof.get("state") == alpha.PASS_STATE and proof.get("p0_p6_passed") is True

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_G5A_ALPHA_PROOF_READY_FOR_DETERMINISTIC_REPLAY" if proof_pass else "HOLD_G5A_ALPHA_PROOF_INCOMPLETE",
        "action": "hold",
        "source_candidate_id": source.get("candidate_id"),
        "source_architecture_candidate_sha256": source.get("candidate_sha256"),
        "source_review_quorum_flag": source.get("eligible_for_preregistration") is True,
        "source_mechanism_first_guard_pass": source.get("mechanism_first_guard_pass") is True,
        "source_preflight_state": source.get("source_preflight_state"),
        "alpha_proof_candidate_sha256": proof.get("candidate_sha256"),
        "alpha_proof_state": proof.get("state"),
        "alpha_proof_receipt_sha256": proof.get("receipt_sha256"),
        "failed_gates": failed,
        "deterministic_replay_authorized": proof_pass,
        "deterministic_replay_requirements": {
            "base_replay": True,
            "realistic_costs": True,
            "cost_2x": True,
            "purged_oos": True,
            "numeric_threshold_sweep": False,
            "best_horizon_cherry_pick": False,
        },
        # G5B starts only after G5A deterministic development economics survive;
        # Alpha Proof alone never creates T=0.
        "g5b_fresh_boundary_created": False,
        "g5b_entry_authorized": False,
        "boundary_note": "architecture review quorum is hypothesis-review credit only; it is not Alpha-Proof PASS and cannot authorize deterministic replay",
        "next": "RUN_DETERMINISTIC_REPLAY_BASE_COST2X_PURGED_OOS" if proof_pass else "COMPLETE_SOURCE_BOUND_ALPHA_PROOF_P0_P6",
        "alpha_proof_receipt": proof,
        **AUTHORITY,
    }
    result["receipt_sha256"] = alpha.sha(result)
    return result


def run(inp: Path, out: Path) -> dict[str, Any]:
    result = evaluate(_read(inp))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def _fixture() -> dict[str, Any]:
    source = {
        "candidate_id": "MA001",
        "candidate_sha256": "source-sha",
        "mode": "NEW_ARCHITECTURE",
        "strategy_id": "NEW",
        "architecture_family": "momentum_session_amplifier",
        "changed_axis": "none",
        "mechanism": "session overlap concentrates directional participation",
        "payer": "directional liquidity takers",
        "entry_event": "session-aware directional breakout",
        "direction_rule": "both rule",
        "native_horizon": "multi-session",
        "regime_owner": "US/EU overlap",
        "invalidation": "continuation disappears",
        "exit_logic": "session-context negation",
        "time_stop_rationale": "session-cycle risk",
        "turnover_cost_budget": "move should dominate cost",
        "required_sources": ["ohlcv", "volume"],
        "evidence_ids": ["F1", "F14", "F15"],
        "expected_move_cost_multiple_target": 2.0,
        "falsification": "kill on fresh after-cost failure",
        "forbidden_changes": ["fees", "best-horizon selection"],
        "why_distinct": "multi-session continuation",
        "eligible_for_preregistration": True,
        "mechanism_first_guard_pass": True,
        "source_preflight_state": "READY_COMMON",
        "cross_reviews": {
            "groq": {"successful": True, "decision": "PASS_TO_REPLAY", "model": "g", "input_sha": "i1", "prompt_sha": "p1", "response_sha": "r1"},
            "workers_ai": {"successful": True, "decision": "PASS_TO_REPLAY", "model": "w", "input_sha": "i2", "prompt_sha": "p2", "response_sha": "r2"},
            "openai": {"successful": True, "decision": "HOLD", "model": "o", "input_sha": None, "prompt_sha": None, "response_sha": None},
        },
    }
    return {"next_experiment_candidate": source, **AUTHORITY}


def self_test() -> int:
    result = evaluate(_fixture())
    assert result["state"] == "HOLD_G5A_ALPHA_PROOF_INCOMPLETE", result
    assert result["deterministic_replay_authorized"] is False
    assert result["g5b_fresh_boundary_created"] is False
    assert "P-IDENTITY" not in result["failed_gates"], result["failed_gates"]
    for gate in ("P0_PRIMARY_EVIDENCE", "P1_FEATURE_CAUSAL_MAP", "P2_NUMERIC_PARAMETER_PROVENANCE", "P3_EMPIRICAL_MOVE_VS_COST", "P4_NEGATIVE_CONTROLS_ABLATION", "P5_MULTI_AI_ADVERSARIAL_REVIEW", "P6_SOURCE_IMPLEMENTATION_REALITY"):
        assert gate in result["failed_gates"], result["failed_gates"]
    assert result["source_review_quorum_flag"] is True
    assert result["source_architecture_candidate_sha256"] == "source-sha"
    print("PASS_G5A_ALPHA_PROOF_PREFLIGHT_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/g5a_alpha_proof_preflight_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.input is None:
        raise SystemExit("--input is required")
    result = run(args.input, args.output)
    print(json.dumps({
        "state": result.get("state"),
        "candidate": result.get("source_candidate_id"),
        "alpha_proof_state": result.get("alpha_proof_state"),
        "failed_gates": result.get("failed_gates"),
        "replay_authorized": result.get("deterministic_replay_authorized"),
        "g5b_entered": result.get("g5b_entry_authorized"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
