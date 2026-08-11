from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_AI_CONTROL_GATE_V1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PROTECTED_FILENAME_MARKERS = (
    "exact25-material-upgrade",
    "trade-methods-pre-shadow",
    "component",
    "interaction",
    "top3",
    "alpha-auto-validation",
    "w2-forward",
    "w3-durability",
)
EXEMPT_FILENAMES = {
    "zel-ai-research-control-hardening-v1.yml",
    "zel-ai-control-enforcement-v1.yml",
    "r7a4d-strategy11-component-attribution-v1.yml",
    "zel-alpha-lap-v2-contract-v1.yml",
    "zel-component-autonomy-v2.yml",
    "zel-data-b-replay-owner-policy-v1.yml",
    "zel-holdout-vault-seal-v1.yml",
    "zel-p0-runtime-e2e-closure-v1.yml",
    "zel-pre-shadow-full-hardening-v1.yml",
    # Production runtime CI verifies deterministic PAPER signal plumbing and has
    # no research candidate-selection authority. Do not route it through the
    # research AI proposal lineage gate merely because its PASS token contains
    # the word ALPHA.
    "zel-production-alpha-producer-v1.yml",
}
CONTROL_PLANE_ORCHESTRATORS = {
    "zel-ai-stage-authorization-broker-v1.yml",
    "zel-pre-shadow-dag-controller-v1.yml",
    "zel-pre-shadow-dag-extension-v1.yml",
}
REUSABLE_GATE_WORKFLOW = "zel-static-stage-reusable-v1.yml"


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def is_protected_workflow(path: Path, text: str) -> bool:
    name = path.name.lower()
    if path.name in EXEMPT_FILENAMES or path.name in CONTROL_PLANE_ORCHESTRATORS:
        return False
    if any(marker in name for marker in PROTECTED_FILENAME_MARKERS):
        return True
    content_markers = (
        "PASS_EXACT25_MATERIAL",
        "PASS_TRADE_METHOD",
        "PASS_COMPONENT_MAIN_EFFECT",
        "PASS_SELECTED_INTERACTION",
        "PASS_STRATEGY_TOP3",
        "PASS_ALPHA",
        "W2_FORWARD",
        "W3_DURABILITY",
    )
    return any(marker in text for marker in content_markers)


def direct_gate_wired(text: str) -> bool:
    verifier_tokens = (
        "zel_ai_control_gate_v1.py",
        "--proposal-receipt",
        "--stage-id",
        "--epoch-id",
        "--predecessor-receipt-sha256",
    )
    gate_identity = (
        "ZEL_AI_CONTROL_GATE_V1" in text
        or "ai_research_control_plane_v1/" in text
    )
    return gate_identity and all(token in text for token in verifier_tokens)


def workflow_gate_wired(text: str, reusable_gate_is_wired: bool) -> bool:
    if direct_gate_wired(text):
        return True
    delegated = (
        "uses: ./.github/workflows/zel-static-stage-reusable-v1.yml" in text
        and reusable_gate_is_wired
    )
    return delegated


def audit_workflows(workflows_root: Path) -> dict[str, Any]:
    paths = sorted([*workflows_root.glob("*.yml"), *workflows_root.glob("*.yaml")])
    texts = {path.name: path.read_text(encoding="utf-8", errors="ignore") for path in paths}
    reusable_text = texts.get(REUSABLE_GATE_WORKFLOW, "")
    reusable_gate_is_wired = direct_gate_wired(reusable_text)

    protected: list[str] = []
    unguarded: list[str] = []
    delegated: list[str] = []
    for path in paths:
        text = texts[path.name]
        if not is_protected_workflow(path, text):
            continue
        protected.append(path.name)
        if "uses: ./.github/workflows/zel-static-stage-reusable-v1.yml" in text:
            delegated.append(path.name)
        if not workflow_gate_wired(text, reusable_gate_is_wired):
            unguarded.append(path.name)
    return {
        "schema_version": "zel.ai.control_enforcement.audit.v1",
        "state": "PASS_ALL_PROTECTED_WORKFLOWS_GUARDED" if not unguarded else "HOLD_UNGUARDED_AI_WORKFLOWS",
        "protected_workflow_count": len(protected),
        "protected_workflows": protected,
        "delegated_workflows": delegated,
        "reusable_gate_workflow": REUSABLE_GATE_WORKFLOW,
        "reusable_gate_is_wired": reusable_gate_is_wired,
        "control_plane_orchestrators": sorted(CONTROL_PLANE_ORCHESTRATORS),
        "unguarded_workflows": unguarded,
        "runtime_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def validate_gate_receipt(
    policy: Mapping[str, Any],
    proposal: Mapping[str, Any],
    stage_id: str,
    epoch_id: str,
    predecessor_sha: str,
) -> dict[str, Any]:
    errors: list[str] = []
    expected_policy_sha = canonical_sha(policy)
    if policy.get("schema_version") != "zel.ai.research_control_plane.v1":
        errors.append("POLICY_SCHEMA")
    if proposal.get("schema_version") != "zel.ai.research_control_plane.receipt.v1":
        errors.append("PROPOSAL_SCHEMA")
    if proposal.get("state") != "PASS_AI_RESEARCH_CONTROL_PLANE":
        errors.append("PROPOSAL_NOT_PASS")
    if proposal.get("policy_sha256") != expected_policy_sha:
        errors.append("POLICY_SHA_MISMATCH")
    if proposal.get("blind_holdout_access_granted") is not False:
        errors.append("HOLDOUT_ACCESS_GRANTED")
    if proposal.get("runtime_mutated") is not False:
        errors.append("RUNTIME_MUTATED")
    if proposal.get("selection_authority") is not False:
        errors.append("SELECTION_AUTHORITY")
    if proposal.get("promotion_authority") is not False:
        errors.append("PROMOTION_AUTHORITY")
    if proposal.get("execution_authority") != "NONE":
        errors.append("EXECUTION_AUTHORITY")
    if proposal.get("order_authority") != "BLOCKED":
        errors.append("ORDER_AUTHORITY")
    rows = proposal.get("proposal_results")
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) and row.get("pass") is True for row in rows):
        errors.append("PROPOSAL_RESULTS")
    if not SHA_RE.fullmatch(predecessor_sha):
        errors.append("PREDECESSOR_SHA")
    meta = proposal.get("gate_context")
    if not isinstance(meta, dict):
        errors.append("GATE_CONTEXT_MISSING")
    else:
        if meta.get("stage_id") != stage_id:
            errors.append("STAGE_MISMATCH")
        if meta.get("epoch_id") != epoch_id:
            errors.append("EPOCH_MISMATCH")
        if meta.get("predecessor_receipt_sha256") != predecessor_sha:
            errors.append("PREDECESSOR_MISMATCH")
    if proposal.get("predecessor_receipt_sha256") not in (None, predecessor_sha):
        errors.append("TOP_LEVEL_PREDECESSOR_MISMATCH")
    claim_tier = str(proposal.get("claim_tier") or "")
    if claim_tier.startswith("STAGE_AUTHORIZATION"):
        if proposal.get("economic_claim_allowed") is not False:
            errors.append("STAGE_AUTH_ECONOMIC_CLAIM")
        if proposal.get("candidate_execution_allowed") is not False:
            errors.append("STAGE_AUTH_CANDIDATE_EXECUTION")
    claimed_receipt_sha = proposal.get("receipt_sha256")
    if claimed_receipt_sha is not None:
        unsigned = dict(proposal)
        unsigned.pop("receipt_sha256", None)
        if claimed_receipt_sha != canonical_sha(unsigned):
            errors.append("RECEIPT_SHA_MISMATCH")
    result = {
        "schema_version": "zel.ai.control_gate.receipt.v1",
        "version": VERSION,
        "state": "PASS_AI_CONTROL_GATE" if not errors else "HOLD_AI_CONTROL_GATE",
        "stage_id": stage_id,
        "epoch_id": epoch_id,
        "predecessor_receipt_sha256": predecessor_sha,
        "policy_sha256": expected_policy_sha,
        "proposal_receipt_sha256": canonical_sha(proposal),
        "errors": sorted(set(errors)),
        "runtime_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    return result


def self_test() -> None:
    sha = "a" * 64
    policy = {"schema_version": "zel.ai.research_control_plane.v1"}
    proposal = {
        "schema_version": "zel.ai.research_control_plane.receipt.v1",
        "state": "PASS_AI_RESEARCH_CONTROL_PLANE",
        "policy_sha256": canonical_sha(policy),
        "blind_holdout_access_granted": False,
        "runtime_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "proposal_results": [{"pass": True}],
        "gate_context": {
            "stage_id": "EXACT25_LIVENESS_AND_REPAIR",
            "epoch_id": "e1",
            "predecessor_receipt_sha256": sha,
        },
    }
    passed = validate_gate_receipt(policy, proposal, "EXACT25_LIVENESS_AND_REPAIR", "e1", sha)
    assert passed["state"] == "PASS_AI_CONTROL_GATE", passed
    bad = dict(proposal)
    bad.pop("gate_context")
    held = validate_gate_receipt(policy, bad, "EXACT25_LIVENESS_AND_REPAIR", "e1", sha)
    assert held["state"] == "HOLD_AI_CONTROL_GATE", held
    assert "GATE_CONTEXT_MISSING" in held["errors"], held
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        direct = "ZEL_AI_CONTROL_GATE_V1 zel_ai_control_gate_v1.py --proposal-receipt --stage-id --epoch-id --predecessor-receipt-sha256"
        reusable = root / REUSABLE_GATE_WORKFLOW
        reusable.write_text(direct + " W2_FORWARD W3_DURABILITY", encoding="utf-8")
        (root / "zel-exact25-material-upgrade-loop-v1.yml").write_text(direct, encoding="utf-8")
        (root / "zel-w2-forward-v1.yml").write_text(
            "uses: ./.github/workflows/zel-static-stage-reusable-v1.yml",
            encoding="utf-8",
        )
        (root / "zel-ai-stage-authorization-broker-v1.yml").write_text("W2_FORWARD", encoding="utf-8")
        (root / "zel-production-alpha-producer-v1.yml").write_text("PASS_ALPHA_PRODUCER_PIPELINE_AUDIT", encoding="utf-8")
        audit = audit_workflows(root)
        assert audit["state"].startswith("PASS"), audit
        assert audit["reusable_gate_is_wired"] is True, audit
        assert "zel-w2-forward-v1.yml" in audit["delegated_workflows"], audit
        assert "zel-ai-stage-authorization-broker-v1.yml" not in audit["protected_workflows"], audit
        assert "zel-production-alpha-producer-v1.yml" not in audit["protected_workflows"], audit
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=False)
    audit = sub.add_parser("audit-workflows")
    audit.add_argument("--workflows-root", type=Path, required=True)
    audit.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--policy", type=Path, required=True)
    verify.add_argument("--proposal-receipt", type=Path, required=True)
    verify.add_argument("--stage-id", required=True)
    verify.add_argument("--epoch-id", required=True)
    verify.add_argument("--predecessor-receipt-sha256", required=True)
    verify.add_argument("--out", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.command == "audit-workflows":
        result = audit_workflows(args.workflows_root)
    elif args.command == "verify":
        result = validate_gate_receipt(load_object(args.policy), load_object(args.proposal_receipt), args.stage_id, args.epoch_id, args.predecessor_receipt_sha256)
    else:
        parser.error("command required")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "errors": result.get("errors", []), "unguarded": result.get("unguarded_workflows", [])}, sort_keys=True))
    return 0 if result["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
