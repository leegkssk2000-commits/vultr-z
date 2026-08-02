from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_COMPONENT_MAIN_EFFECT_RECEIPT_V1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def safe_authority(row: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if row.get("execution_authority") not in (None, "NONE"):
        errors.append("EXECUTION_AUTHORITY_NOT_NONE")
    if row.get("order_authority") not in (None, "BLOCKED"):
        errors.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if row.get("promotion_authority") is True:
        errors.append("PROMOTION_AUTHORITY_TRUE")
    if row.get("live_enabled") is True or row.get("live_allowed") is True:
        errors.append("LIVE_ENABLED_TRUE")
    return errors


def interaction_summary(claim_gate: Mapping[str, Any]) -> dict[str, Any]:
    source = claim_gate.get("interaction_audit")
    source = source if isinstance(source, dict) else {}
    return {
        "method": source.get("method"),
        "tested_order_count": int(source.get("tested_order_count") or 0),
        "canonical_order": list(source.get("canonical_order") or []),
        "net_spread_pct_points": source.get("net_spread_pct_points"),
        "applied_set_count": int(source.get("applied_set_count") or 0),
        "order_stable": source.get("order_stable") is True,
        "threshold_pct_points": source.get("threshold_pct_points"),
    }


def build_receipt(
    final: Mapping[str, Any],
    audit: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    predecessor_sha256: str,
    source_run_id: str,
    active_axis_count: int,
    axis_ai_gate_result: str,
    gemini_required: bool,
    gemini_result: str,
) -> dict[str, Any]:
    errors: list[str] = []
    errors.extend(f"FINAL_{item}" for item in safe_authority(final))
    errors.extend(f"PREDECESSOR_{item}" for item in safe_authority(predecessor))

    if not str(predecessor.get("state") or "").startswith("PASS_"):
        errors.append("PREDECESSOR_NOT_PASS")
    if final.get("structure_state") != "PASS_COMPONENT_STRUCTURE":
        errors.append("COMPONENT_STRUCTURE_NOT_PASS")
    if audit.get("state") != "PASS_COMPONENT_PIPELINE_AUDIT_V2":
        errors.append("COMPONENT_PIPELINE_AUDIT_NOT_PASS")
    if final.get("shadow_start_allowed") is not False:
        errors.append("SHADOW_BOUNDARY_NOT_FALSE")
    if final.get("paper_allowed") not in (None, False):
        errors.append("PAPER_BOUNDARY_NOT_FALSE")
    if final.get("runtime_bound") not in (None, False):
        errors.append("RUNTIME_BOUND_TRUE")
    if not isinstance(final.get("component_attribution"), dict):
        errors.append("COMPONENT_ATTRIBUTION_MISSING")
    result_sha = str(final.get("result_sha256") or "")
    if not SHA_RE.fullmatch(result_sha):
        errors.append("COMPONENT_RESULT_SHA_INVALID")
    if not SHA_RE.fullmatch(predecessor_sha256):
        errors.append("PREDECESSOR_SHA_INVALID")

    claim_gate = final.get("claim_gate") if isinstance(final.get("claim_gate"), dict) else {}
    eligibility = final.get("axis_review_eligibility")
    eligibility = eligibility if isinstance(eligibility, dict) else {}
    eligible_axis_ids = sorted(str(axis) for axis, eligible in eligibility.items() if eligible is True)
    ai_review_complete = (
        (active_axis_count <= 0 or axis_ai_gate_result == "success")
        and (not gemini_required or gemini_result == "success")
    )
    interactions = interaction_summary(claim_gate)
    receipt: dict[str, Any] = {
        "schema_version": "zel.component_main_effect.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_COMPONENT_MAIN_EFFECT_COMPLETE" if not errors else "HOLD_COMPONENT_MAIN_EFFECT",
        "stage_id": "COMPONENT_MAIN_EFFECT",
        "source_workflow": "ZEL Component Main Effect V1",
        "source_run_id": str(source_run_id),
        "predecessor_stage_id": "TRADE_METHOD_COVERAGE",
        "predecessor_receipt_sha256": predecessor_sha256,
        "component_result_sha256": result_sha or None,
        "component_data_fingerprint": final.get("data_fingerprint"),
        "component_epoch": final.get("epoch"),
        "source_state": final.get("state"),
        "structure_state": final.get("structure_state"),
        "claim_tier": claim_gate.get("claim_tier"),
        "source_performance_claim_allowed": final.get("performance_claim_allowed") is True,
        "economic_claim_allowed": False,
        "component_main_effect_complete": not errors,
        "selected_interactions_allowed": not errors,
        "eligible_axis_ids": eligible_axis_ids,
        "eligible_axis_count": len(eligible_axis_ids),
        "interaction_audit": interactions,
        "active_axis_count": int(active_axis_count),
        "axis_ai_gate_result": axis_ai_gate_result,
        "gemini_required": bool(gemini_required),
        "gemini_result": gemini_result,
        "ai_review_complete": ai_review_complete,
        "ai_review_deferred_to_selected_interactions": not ai_review_complete,
        "component_attribution_present": isinstance(final.get("component_attribution"), dict),
        "errors": errors,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = canonical_sha(receipt)
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    final = load_object(args.final)
    audit = load_object(args.audit)
    predecessor = load_object(args.predecessor)
    receipt = build_receipt(
        final=final,
        audit=audit,
        predecessor=predecessor,
        predecessor_sha256=file_sha(args.predecessor),
        source_run_id=args.source_run_id,
        active_axis_count=args.active_axis_count,
        axis_ai_gate_result=args.axis_ai_gate_result,
        gemini_required=args.gemini_required,
        gemini_result=args.gemini_result,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def self_test() -> None:
    predecessor = {
        "state": "PASS_TRADE_METHOD_COVERAGE_COMPLETE",
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "promotion_authority": False,
    }
    final = {
        "state": "HYPOTHESIS_ONLY_HOLD",
        "structure_state": "PASS_COMPONENT_STRUCTURE",
        "shadow_start_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "runtime_bound": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "promotion_authority": False,
        "component_attribution": {"BOT_POLICY": {"material": True}},
        "axis_review_eligibility": {"BOT_POLICY": True, "TEAM_POLICY": True, "SKILL_PROFILE": False},
        "result_sha256": "a" * 64,
        "data_fingerprint": "b" * 64,
        "epoch": 1,
        "performance_claim_allowed": False,
        "claim_gate": {
            "claim_tier": "HYPOTHESIS_ONLY",
            "interaction_audit": {
                "method": "ALL_PERMUTATIONS_OF_APPLIED_COMPONENTS",
                "tested_order_count": 2,
                "canonical_order": ["TEAM", "ZBOT"],
                "net_spread_pct_points": 0.03,
                "applied_set_count": 1,
                "order_stable": True,
                "threshold_pct_points": 0.2,
            },
        },
    }
    audit = {"state": "PASS_COMPONENT_PIPELINE_AUDIT_V2"}
    passed = build_receipt(final, audit, predecessor, "c" * 64, "123", 2, "deferred", True, "deferred")
    assert passed["state"] == "PASS_COMPONENT_MAIN_EFFECT_COMPLETE", passed
    assert passed["economic_claim_allowed"] is False
    assert passed["selected_interactions_allowed"] is True
    assert passed["ai_review_deferred_to_selected_interactions"] is True
    assert passed["eligible_axis_ids"] == ["BOT_POLICY", "TEAM_POLICY"], passed
    assert passed["interaction_audit"]["order_stable"] is True, passed

    held = build_receipt(final, {"state": "HOLD_PIPELINE_AUDIT"}, predecessor, "c" * 64, "124", 0, "skipped", False, "skipped")
    assert held["state"] == "HOLD_COMPONENT_MAIN_EFFECT", held
    assert "COMPONENT_PIPELINE_AUDIT_NOT_PASS" in held["errors"]
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--predecessor", type=Path)
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--active-axis-count", type=int, default=0)
    parser.add_argument("--axis-ai-gate-result", default="skipped")
    parser.add_argument("--gemini-required", action="store_true")
    parser.add_argument("--gemini-result", default="skipped")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.final or not args.audit or not args.predecessor or not args.out:
        parser.error("final, audit, predecessor and out are required")
    receipt = run(args)
    print(json.dumps({
        "state": receipt["state"],
        "errors": receipt["errors"],
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
