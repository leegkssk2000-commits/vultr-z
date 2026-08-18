#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as v1

SCHEMA_VERSION = "zel.a1_alpha_proof_gate.v2"
PASS_STATE = v1.PASS_STATE
HOLD_STATE = v1.HOLD_STATE
AUTHORITY = dict(v1.AUTHORITY)
CANDIDATE_IDENTITY_FIELDS = (
    "candidate_id",
    "provider",
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


def canonical(value: Any) -> str:
    return v1.canonical(value)


def sha(value: Any) -> str:
    return v1.sha(value)


def read_json(path: Path) -> dict[str, Any]:
    return v1.read_json(path)


def identity_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    explicit = candidate.get("candidate_identity_payload")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    missing = [k for k in CANDIDATE_IDENTITY_FIELDS if k not in candidate]
    if missing:
        raise RuntimeError("CANDIDATE_IDENTITY_FIELDS_MISSING:" + ",".join(missing))
    return {k: candidate[k] for k in CANDIDATE_IDENTITY_FIELDS}


def evaluate_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    candidate = bundle.get("candidate")
    if not isinstance(candidate, Mapping):
        candidate = {}
    candidate_sha = str(candidate.get("candidate_sha256") or "")
    identity_failures: list[dict[str, str]] = []
    computed_candidate_sha = ""
    try:
        payload = identity_payload(candidate)
        computed_candidate_sha = sha(payload)
    except Exception as exc:
        identity_failures.append(v1._fail("CANDIDATE_IDENTITY_PAYLOAD_INVALID", str(exc)))
    if not candidate_sha:
        identity_failures.append(v1._fail("CANDIDATE_SHA_MISSING", "candidate.candidate_sha256 required"))
    elif computed_candidate_sha and candidate_sha != computed_candidate_sha:
        identity_failures.append(v1._fail("CANDIDATE_SHA_MISMATCH", f"declared={candidate_sha} computed={computed_candidate_sha}"))
    if candidate.get("research_only") is False:
        identity_failures.append(v1._fail("CANDIDATE_AUTHORITY_INVALID", "research_only cannot be false"))
    gates = [
        v1._gate("P-IDENTITY", not identity_failures, identity_failures, {"candidate_sha256": candidate_sha, "computed_candidate_sha256": computed_candidate_sha}),
        v1.evaluate_p0(bundle),
        v1.evaluate_p1(bundle),
        v1.evaluate_p2(bundle),
        v1.evaluate_p3(bundle),
        v1.evaluate_p4(bundle),
        v1.evaluate_p5(bundle),
        v1.evaluate_p6(bundle),
    ]
    all_pass = all(g["passed"] for g in gates)
    result = {
        "schema_version": SCHEMA_VERSION,
        "state": PASS_STATE if all_pass else HOLD_STATE,
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate_sha,
        "candidate_identity_sha256": computed_candidate_sha,
        "gates": gates,
        "p0_p6_passed": all_pass,
        "fresh_prospective_boundary_required": all_pass,
        "fresh_policy_config_source_sha_required": all_pass,
        "heavy_launch_allowed": False,
        "launch_authority_note": "PASS_ALPHA_PROOF only authorizes creation of a new frozen fresh prospective contract. It never itself launches, selects, promotes, or trades.",
        **AUTHORITY,
    }
    result["receipt_sha256"] = sha(result)
    return result


def assert_receipt(receipt: Mapping[str, Any], candidate_sha: str) -> None:
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("ALPHA_PROOF_SCHEMA_MISMATCH")
    if receipt.get("state") != PASS_STATE or receipt.get("p0_p6_passed") is not True:
        raise RuntimeError("ALPHA_PROOF_NOT_PASS")
    if str(receipt.get("candidate_sha256") or "") != candidate_sha:
        raise RuntimeError("ALPHA_PROOF_CANDIDATE_SHA_MISMATCH")
    if str(receipt.get("candidate_identity_sha256") or "") != candidate_sha:
        raise RuntimeError("ALPHA_PROOF_IDENTITY_SHA_MISMATCH")
    if receipt.get("selection_authority") is not False or receipt.get("promotion_authority") is not False:
        raise RuntimeError("ALPHA_PROOF_AUTHORITY_INVALID")
    if receipt.get("execution_authority") != "NONE" or receipt.get("order_authority") != "BLOCKED" or receipt.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("ALPHA_PROOF_EXECUTION_AUTHORITY_INVALID")
    if int(receipt.get("protected_mutations") or 0) != 0:
        raise RuntimeError("ALPHA_PROOF_PROTECTED_MUTATION")


def _fixture_bundle() -> dict[str, Any]:
    base = v1._fixture_bundle()
    core = {
        "candidate_id": "fixture:new_arch",
        "provider": "openai",
        "mode": "NEW_ARCHITECTURE",
        "strategy_id": "NEW",
        "architecture_family": "basis_dislocation_unwind_fixture",
        "changed_axis": "basis_dislocation_state",
        "mechanism": "temporary perp basis dislocation mean reverts when positioning pressure relaxes",
        "payer": "crowded leveraged perp positioning",
        "entry_event": "entry-time basis+OI dislocation",
        "direction_rule": "both",
        "native_horizon": "1h-4h",
        "regime_owner": "basis/funding crowding",
        "invalidation": "dislocation expands with confirming OI",
        "exit_logic": "close on basis normalization or invalidation",
        "time_stop_rationale": "funding/basis dislocations should normalize within a bounded multi-hour window",
        "turnover_cost_budget": "development-only move distribution must exceed verified cost under SSOT gate",
        "required_sources": ["ohlcv", "basis", "open_interest", "funding"],
        "evidence_ids": ["P1", "P2"],
        "expected_move_cost_multiple_target": 2.0,
        "falsification": "development and fresh prospective edge must exceed controls after realistic costs",
        "forbidden_changes": ["fees", "best-horizon selection", "post-outcome loss deletion"],
        "why_distinct": "positioning/basis mechanism distinct from short-horizon order-flow scalp",
    }
    base["candidate"] = {**core, "candidate_sha256": sha(core), "research_only": True, "score": 99.0, "alpha_proof_candidate_ready": True, "eligible_for_preregistration": False}
    return base


def self_test() -> int:
    good = _fixture_bundle()
    passed = evaluate_bundle(good)
    assert passed["state"] == PASS_STATE, passed
    assert passed["candidate_sha256"] == passed["candidate_identity_sha256"]
    assert_receipt(passed, good["candidate"]["candidate_sha256"])
    bad = json.loads(json.dumps(good))
    bad["candidate"]["score"] = -999.0
    unchanged = evaluate_bundle(bad)
    assert unchanged["state"] == PASS_STATE, unchanged
    assert unchanged["candidate_identity_sha256"] == good["candidate"]["candidate_sha256"]
    bad2 = json.loads(json.dumps(good))
    bad2["candidate"]["mechanism"] = "mutated mechanism"
    held = evaluate_bundle(bad2)
    assert held["state"] == HOLD_STATE
    assert any(f["code"] == "CANDIDATE_SHA_MISMATCH" for g in held["gates"] for f in g["failures"])
    print("PASS_A1_ALPHA_PROOF_GATE_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_alpha_proof_gate_v2.json"))
    ap.add_argument("--assert-receipt", type=Path)
    ap.add_argument("--candidate-sha")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.assert_receipt:
        if not args.candidate_sha:
            raise SystemExit("--candidate-sha required with --assert-receipt")
        assert_receipt(read_json(args.assert_receipt), args.candidate_sha)
        print("PASS_A1_ALPHA_PROOF_RECEIPT_ASSERT_V2")
        return 0
    if not args.bundle:
        raise SystemExit("--bundle is required")
    result = evaluate_bundle(read_json(args.bundle))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(canonical({"state": result["state"], "candidate_id": result["candidate_id"], "candidate_sha256": result["candidate_sha256"], "candidate_identity_sha256": result["candidate_identity_sha256"], "failed_gates": [g["gate"] for g in result["gates"] if not g["passed"]], "receipt_sha256": result["receipt_sha256"]}))
    return 0 if result["state"] == PASS_STATE else 2


if __name__ == "__main__":
    raise SystemExit(main())
