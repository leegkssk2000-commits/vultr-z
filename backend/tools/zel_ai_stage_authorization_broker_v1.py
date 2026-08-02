from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_AI_STAGE_AUTHORIZATION_BROKER_V1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def safe_stage_slug(stage_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", stage_id.lower()).strip("_")


def stage_map(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = contract.get("stages")
    if not isinstance(rows, list):
        raise ValueError("STAGES_REQUIRED")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("stage_id"):
            raise ValueError("INVALID_STAGE_ROW")
        stage_id = str(row["stage_id"])
        if stage_id in result:
            raise ValueError(f"DUPLICATE_STAGE:{stage_id}")
        result[stage_id] = dict(row)
    return result


def predecessor_is_safe(row: Mapping[str, Any]) -> bool:
    state = str(row.get("state") or row.get("verdict") or "")
    return (
        (state.startswith("PASS") or state.endswith("COMPLETE"))
        and row.get("promotion_authority") is not True
        and row.get("execution_authority") in (None, "NONE")
        and row.get("order_authority") in (None, "BLOCKED")
        and row.get("live_enabled") is not True
    )


def existing_authorization_is_current(results_root: Path, stage_id: str, predecessor_sha: str) -> bool:
    path = (
        results_root
        / "runtime_results/zel/ai_research_control_plane_v1"
        / safe_stage_slug(stage_id)
        / "latest.json"
    )
    if not path.is_file():
        return False
    try:
        row = load_object(path)
    except Exception:
        return False
    context = row.get("gate_context") or {}
    gate_stage = stage_id if stage_id != "EXACT25_CHILD_PROBE" else "EXACT25_LIVENESS_AND_REPAIR"
    return (
        row.get("state") == "PASS_AI_RESEARCH_CONTROL_PLANE"
        and context.get("predecessor_receipt_sha256") == predecessor_sha
        and context.get("stage_id") == gate_stage
    )


def choose_stage(
    contract: Mapping[str, Any],
    results_root: Path,
    requested: str | None,
) -> tuple[dict[str, Any] | None, str]:
    stages = stage_map(contract)
    if requested:
        if requested not in stages:
            return None, "HOLD_STAGE_NOT_ALLOWLISTED"
        return stages[requested], "PASS_MANUAL_STAGE_SELECTED"

    for stage_id, row in stages.items():
        if row.get("auto_dispatch") is not True:
            continue
        predecessor_path = results_root / str(row["predecessor_path"])
        if not predecessor_path.is_file():
            continue
        try:
            predecessor = load_object(predecessor_path)
        except Exception:
            continue
        if not predecessor_is_safe(predecessor):
            continue
        predecessor_sha = file_sha(predecessor_path)
        if existing_authorization_is_current(results_root, stage_id, predecessor_sha):
            continue
        return row, "PASS_AUTO_STAGE_SELECTED"
    return None, "HOLD_NO_ELIGIBLE_STAGE"


def build_receipt(
    policy: Mapping[str, Any],
    contract: Mapping[str, Any],
    stage: Mapping[str, Any],
    predecessor_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    predecessor = load_object(predecessor_path)
    manifest = load_object(manifest_path)
    errors: list[str] = []
    if policy.get("schema_version") != "zel.ai.research_control_plane.v1":
        errors.append("POLICY_SCHEMA")
    if contract.get("schema_version") != "zel.ai.stage_authorization_broker.v1":
        errors.append("BROKER_CONTRACT_SCHEMA")
    if not predecessor_is_safe(predecessor):
        errors.append("PREDECESSOR_NOT_SAFE_PASS")

    predecessor_sha = file_sha(predecessor_path)
    manifest_sha = file_sha(manifest_path)
    policy_sha = canonical_sha(policy)
    stage_id = str(stage["stage_id"])
    gate_stage_id = str(stage.get("gate_stage_id") or stage_id)
    epoch_id = f"{safe_stage_slug(stage_id)}-{predecessor_sha[:16]}"
    plan = {
        "stage_id": stage_id,
        "gate_stage_id": gate_stage_id,
        "changed_axis": stage["changed_axis"],
        "predecessor_receipt_sha256": predecessor_sha,
        "manifest_sha256": manifest_sha,
        "target_workflow": stage["target_workflow"],
        "economic_claim_allowed": False,
        "candidate_execution_allowed": False,
    }
    candidate_sha = canonical_sha(plan)
    proposal = {
        "proposal_id": f"stage-auth-{candidate_sha[:20]}",
        "epoch_id": epoch_id,
        "role": "LINEAGE_AUDITOR",
        "provider": "deterministic",
        "model": VERSION,
        "prompt_sha256": canonical_sha({
            "instruction": "authorize one bounded research stage from immutable lineage only",
            "stage_id": stage_id,
            "claim_tier": contract["claim_tier"],
        }),
        "context_sha256": canonical_sha({
            "predecessor": predecessor,
            "manifest": manifest,
            "plan": plan,
        }),
        "source_data_sha256": predecessor_sha,
        "parent_variant_sha256": manifest_sha,
        "candidate_sha256": candidate_sha,
        "changed_axis": str(stage["changed_axis"]),
        "hypothesis": "Permit one bounded research stage without economic or execution authority.",
        "expected_failure_mode": "Missing, unsafe or stale lineage must fail closed before dispatch.",
        "created_at": now_iso(),
        "duplicate_group_id": f"{stage_id}:{predecessor_sha}",
        "claim_tier": contract["claim_tier"],
        "economic_claim_allowed": False,
        "candidate_execution_allowed": False,
    }
    sha_fields = (
        "prompt_sha256",
        "context_sha256",
        "source_data_sha256",
        "parent_variant_sha256",
        "candidate_sha256",
    )
    if not all(SHA_RE.fullmatch(str(proposal[key])) for key in sha_fields):
        errors.append("PROPOSAL_SHA_FORMAT")

    result: dict[str, Any] = {
        "schema_version": "zel.ai.research_control_plane.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_AI_RESEARCH_CONTROL_PLANE" if not errors else "HOLD_AI_RESEARCH_CONTROL_PLANE",
        "claim_tier": contract["claim_tier"],
        "policy_sha256": policy_sha,
        "broker_contract_sha256": canonical_sha(contract),
        "predecessor_receipt_sha256": predecessor_sha,
        "manifest_sha256": manifest_sha,
        "proposal_count": 1,
        "proposal_results": [{
            "proposal_id": proposal["proposal_id"],
            "pass": not errors,
            "errors": errors,
            "candidate_sha256": candidate_sha,
            "claim_tier": contract["claim_tier"],
            "economic_claim_allowed": False,
        }],
        "proposal": proposal,
        "gate_context": {
            "stage_id": gate_stage_id,
            "broker_stage_id": stage_id,
            "epoch_id": epoch_id,
            "predecessor_receipt_sha256": predecessor_sha,
            "manifest_sha256": manifest_sha,
            "target_workflow": stage["target_workflow"],
        },
        "ai_scoreboard": [],
        "blind_holdout_access_granted": False,
        "economic_claim_allowed": False,
        "candidate_execution_allowed": False,
        "runtime_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = canonical_sha(result)
    return result


def status_base(state: str) -> dict[str, Any]:
    return {
        "schema_version": "zel.ai.stage_authorization_broker.status.v1",
        "generated_at": now_iso(),
        "state": state,
        "ready": False,
        "runtime_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def run(
    contract_path: Path,
    policy_path: Path,
    results_root: Path,
    control_root: Path,
    requested_stage: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    contract = load_object(contract_path)
    policy = load_object(policy_path)
    stage, selection_state = choose_stage(contract, results_root, requested_stage)
    if stage is None:
        return None, status_base(selection_state)

    predecessor_path = results_root / str(stage["predecessor_path"])
    manifest_path = control_root / str(stage["manifest_path"])
    missing = []
    if not predecessor_path.is_file():
        missing.append("PREDECESSOR_MISSING")
    if not manifest_path.is_file():
        missing.append("MANIFEST_MISSING")
    if missing:
        status = status_base("HOLD_STAGE_INPUT_MISSING")
        status.update({"stage_id": stage["stage_id"], "errors": missing})
        return None, status

    receipt = build_receipt(policy, contract, stage, predecessor_path, manifest_path)
    ready = receipt["state"] == "PASS_AI_RESEARCH_CONTROL_PLANE"
    status = status_base("PASS_STAGE_AUTHORIZATION_READY" if ready else "HOLD_STAGE_AUTHORIZATION")
    status.update({
        "selection_state": selection_state,
        "stage_id": stage["stage_id"],
        "gate_stage_id": receipt["gate_context"]["stage_id"],
        "target_workflow": stage["target_workflow"],
        "auto_dispatch": stage.get("auto_dispatch") is True,
        "ready": ready,
        "receipt_sha256": receipt["receipt_sha256"],
        "predecessor_receipt_sha256": receipt["predecessor_receipt_sha256"],
    })
    return receipt, status


def self_test() -> None:
    policy = {"schema_version": "zel.ai.research_control_plane.v1"}
    contract = {
        "schema_version": "zel.ai.stage_authorization_broker.v1",
        "claim_tier": "STAGE_AUTHORIZATION_NO_ECONOMIC_CLAIM",
        "stages": [{
            "stage_id": "EXACT25_LIVENESS_AND_REPAIR",
            "predecessor_path": "runtime_results/pred.json",
            "manifest_path": "manifest.json",
            "target_workflow": "target.yml",
            "auto_dispatch": True,
            "changed_axis": "DIAGNOSIS",
        }],
    }
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        results = root / "results"
        control = root / "control"
        (results / "runtime_results").mkdir(parents=True)
        control.mkdir()
        predecessor_path = results / "runtime_results/pred.json"
        predecessor_path.write_text(json.dumps({
            "state": "PASS_PREDECESSOR",
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }), encoding="utf-8")
        (control / "manifest.json").write_text(
            json.dumps({"schema_version": "fixture.v1"}),
            encoding="utf-8",
        )
        contract_path = root / "contract.json"
        policy_path = root / "policy.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        policy_path.write_text(json.dumps(policy), encoding="utf-8")

        receipt, status = run(contract_path, policy_path, results, control, None)
        assert receipt and status["state"] == "PASS_STAGE_AUTHORIZATION_READY", status
        assert receipt["economic_claim_allowed"] is False
        assert receipt["gate_context"]["stage_id"] == "EXACT25_LIVENESS_AND_REPAIR"
        assert receipt["policy_sha256"] == canonical_sha(policy)

        predecessor_path.write_text(json.dumps({
            "state": "WAIT_DATA_B_15M_AND_1M_TERMINAL",
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }), encoding="utf-8")
        blocked_receipt, blocked_status = run(contract_path, policy_path, results, control, None)
        assert blocked_receipt is None, blocked_receipt
        assert blocked_status["state"] == "HOLD_NO_ELIGIBLE_STAGE", blocked_status
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--results-root", type=Path)
    parser.add_argument("--control-root", type=Path)
    parser.add_argument("--stage-id")
    parser.add_argument("--receipt-out", type=Path)
    parser.add_argument("--status-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (args.contract, args.policy, args.results_root, args.control_root, args.status_out)
    if not all(required):
        parser.error("contract, policy, results-root, control-root and status-out are required")
    receipt, status = run(
        args.contract,
        args.policy,
        args.results_root,
        args.control_root,
        args.stage_id or None,
    )
    args.status_out.parent.mkdir(parents=True, exist_ok=True)
    args.status_out.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if receipt is not None:
        if args.receipt_out is None:
            parser.error("receipt-out required when a stage is eligible")
        args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": status["state"],
        "ready": status["ready"],
        "stage_id": status.get("stage_id"),
        "target_workflow": status.get("target_workflow"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
