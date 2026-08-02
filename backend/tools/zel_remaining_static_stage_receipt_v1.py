from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_REMAINING_STATIC_STAGE_RECEIPT_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def safe_authority(row: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if row.get("execution_authority") not in (None, "NONE"):
        errors.append("EXECUTION_AUTHORITY_NOT_NONE")
    if row.get("order_authority") not in (None, "BLOCKED"):
        errors.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if row.get("promotion_authority") is True:
        errors.append("PROMOTION_AUTHORITY_TRUE")
    if row.get("selection_authority") is True:
        errors.append("SELECTION_AUTHORITY_TRUE")
    if row.get("live_enabled") is True or row.get("live_allowed") is True:
        errors.append("LIVE_ENABLED_TRUE")
    return errors


def base_receipt(
    stage_id: str,
    state: str,
    predecessor: Mapping[str, Any],
    predecessor_sha256: str,
    source_run_id: str,
    errors: list[str],
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": "zel.remaining_static_stage.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "stage_id": stage_id,
        "state": state,
        "source_run_id": str(source_run_id),
        "predecessor_state": predecessor.get("state"),
        "predecessor_receipt_sha256": predecessor_sha256,
        "errors": sorted(set(errors)),
        "retryable": bool(errors),
        "economic_claim_allowed": False,
        "performance_ranking_allowed": False,
        "candidate_execution_allowed": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "active_data_b_1m_mutated": False,
        "shadow_started": False,
        "shadow_start_allowed": False,
        "paper_started": False,
        "paper_start_allowed": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    return receipt


def normalize_bundle_id(row: Mapping[str, Any], index: int) -> str:
    for key in ("bundle_id", "id", "candidate_id", "name"):
        value = row.get(key)
        if value:
            return str(value)
    return f"bundle_{index + 1}"


def build_alpha(
    config: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    predecessor_sha256: str,
    source_run_id: str,
) -> dict[str, Any]:
    errors = safe_authority(predecessor)
    if predecessor.get("state") != config.get("predecessor_state"):
        errors.append("PREDECESSOR_NOT_PASS")
    raw = predecessor.get("bundles")
    if not isinstance(raw, list):
        raw = predecessor.get("bundle_set")
    if not isinstance(raw, list) or not raw:
        errors.append("STRUCTURAL_BUNDLES_MISSING")
        raw = []
    max_items = int(config.get("max_items", 3))
    challengers: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:max_items]):
        if not isinstance(item, dict):
            continue
        challengers.append({
            "challenger_id": normalize_bundle_id(item, index),
            "source_bundle_index": index,
            "source_bundle_sha256": canonical_sha(item),
            "role": "CONTROL" if index == 0 else "STRUCTURAL_CHALLENGER",
            "economic_rank": None,
            "eligible_for_w2_evaluation": True,
        })
    if not challengers:
        errors.append("NO_REGISTERABLE_CHALLENGERS")
    state = str(config.get("pass_state")) if not errors else str(config.get("hold_state"))
    receipt = base_receipt("ALPHA_LAP_CHALLENGERS", state, predecessor, predecessor_sha256, source_run_id, errors)
    receipt.update({
        "challenger_count": len(challengers),
        "max_challenger_count": max_items,
        "challengers": challengers,
        "registration_only": True,
        "w2_evaluation_started": False,
        "w3_evaluation_started": False,
    })
    return receipt


def build_evidence_stage(
    stage_id: str,
    config: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    predecessor_sha256: str,
    evidence_path: Path | None,
    source_run_id: str,
) -> dict[str, Any]:
    errors = safe_authority(predecessor)
    if predecessor.get("state") != config.get("predecessor_state"):
        errors.append("PREDECESSOR_NOT_PASS")
    evidence: dict[str, Any] | None = None
    evidence_sha256: str | None = None
    if evidence_path is None or not evidence_path.is_file():
        errors.append("STANDARD_EVIDENCE_MISSING")
    else:
        try:
            evidence = load_object(evidence_path)
            evidence_sha256 = file_sha(evidence_path)
            errors.extend(f"EVIDENCE_{item}" for item in safe_authority(evidence))
            allowed = set(str(item) for item in config.get("evidence_states", []))
            if str(evidence.get("state")) not in allowed:
                errors.append("EVIDENCE_STATE_NOT_PASS")
            if evidence.get("sealed_final_holdout_accessed") is True:
                errors.append("FINAL_HOLDOUT_ACCESSED_EARLY")
            if evidence.get("promotion_authority") is True:
                errors.append("EVIDENCE_PROMOTION_AUTHORITY_TRUE")
        except Exception as exc:
            errors.append(f"EVIDENCE_PARSE_ERROR:{type(exc).__name__}")
    state = str(config.get("pass_state")) if not errors else str(config.get("hold_state"))
    receipt = base_receipt(stage_id, state, predecessor, predecessor_sha256, source_run_id, errors)
    receipt.update({
        "evidence_required": True,
        "evidence_path": str(evidence_path) if evidence_path else None,
        "evidence_receipt_sha256": evidence_sha256,
        "evidence_state": evidence.get("state") if evidence else None,
        "evidence_summary": (
            evidence.get("summary")
            or evidence.get("stats")
            or evidence.get("metrics")
            or evidence.get("result")
        ) if evidence else None,
        "sealed_final_holdout_accessed": False,
    })
    if stage_id == "W2_FORWARD":
        receipt.update({"w2_complete": not errors, "w3_started": False})
    elif stage_id == "W3_DURABILITY":
        receipt.update({"w3_complete": not errors, "portfolio_started": False})
    elif stage_id == "PORTFOLIO_JOINT_RISK":
        receipt.update({"portfolio_joint_risk_complete": not errors, "rollback_started": False})
    return receipt


def build_rollback(
    config: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    predecessor_path: Path,
    predecessor_sha256: str,
    source_run_id: str,
) -> dict[str, Any]:
    errors = safe_authority(predecessor)
    if predecessor.get("state") != config.get("predecessor_state"):
        errors.append("PREDECESSOR_NOT_PASS")
    source_digest = predecessor_sha256
    restored_digest: str | None = None
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        backup = root / "backup.json"
        restored = root / "restored.json"
        shutil.copy2(predecessor_path, backup)
        restored.write_text("simulated-damage\n", encoding="utf-8")
        shutil.copy2(backup, restored)
        restored_digest = file_sha(restored)
    if restored_digest != source_digest:
        errors.append("ROLLBACK_DIGEST_MISMATCH")
    state = str(config.get("pass_state")) if not errors else str(config.get("hold_state"))
    receipt = base_receipt("ROLLBACK_REHEARSAL", state, predecessor, predecessor_sha256, source_run_id, errors)
    receipt.update({
        "rehearsal_scope": "TEMPORARY_RECEIPT_COPY_ONLY",
        "source_digest": source_digest,
        "restored_digest": restored_digest,
        "digest_match": restored_digest == source_digest,
        "production_files_touched": 0,
        "rollback_rehearsal_complete": not errors,
    })
    return receipt


def load_dag_module(tool_path: Path):
    spec = importlib.util.spec_from_file_location("zel_pre_shadow_receipt_dag_v1", tool_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("DAG_MODULE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_release_from_summary(
    config: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    predecessor_sha256: str,
    dag: Mapping[str, Any],
    source_run_id: str,
) -> dict[str, Any]:
    errors = safe_authority(predecessor)
    if predecessor.get("state") != config.get("predecessor_state"):
        errors.append("PREDECESSOR_NOT_PASS")
    required = int(config.get("required_prior_stage_count", 12))
    if dag.get("passed_stage_count") != required:
        errors.append("PRIOR_STAGE_COUNT_NOT_12")
    if dag.get("first_blocked_stage") != "PRE_SHADOW_RELEASE":
        errors.append("DAG_NOT_BLOCKED_AT_RELEASE")
    if dag.get("eligible_next_stage") != "PRE_SHADOW_RELEASE":
        errors.append("RELEASE_NOT_ELIGIBLE")
    if dag.get("execution_authority") != "NONE" or dag.get("order_authority") != "BLOCKED":
        errors.append("DAG_AUTHORITY_BOUNDARY_FAILED")
    state = str(config.get("pass_state")) if not errors else str(config.get("hold_state"))
    receipt = base_receipt("PRE_SHADOW_RELEASE", state, predecessor, predecessor_sha256, source_run_id, errors)
    receipt.update({
        "prior_stage_count_required": required,
        "prior_stage_count_passed": dag.get("passed_stage_count"),
        "prior_stage_ids": dag.get("passed_stages", []),
        "lineage_policy": dag.get("lineage_policy"),
        "dispatch_policy": dag.get("dispatch_policy"),
        "pre_shadow_release_complete": not errors,
        "shadow_start_allowed": False,
        "requires_final_dag_binding": True,
    })
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_object(args.contract)
    stages = contract.get("stages")
    if not isinstance(stages, dict) or args.stage_id not in stages:
        raise ValueError(f"UNKNOWN_STAGE:{args.stage_id}")
    config = stages[args.stage_id]
    if not isinstance(config, dict):
        raise ValueError("INVALID_STAGE_CONFIG")
    predecessor = load_object(args.predecessor)
    predecessor_sha256 = file_sha(args.predecessor)

    if args.stage_id == "ALPHA_LAP_CHALLENGERS":
        receipt = build_alpha(config, predecessor, predecessor_sha256, args.source_run_id)
    elif args.stage_id in {"W2_FORWARD", "W3_DURABILITY", "PORTFOLIO_JOINT_RISK"}:
        receipt = build_evidence_stage(
            args.stage_id,
            config,
            predecessor,
            predecessor_sha256,
            args.evidence,
            args.source_run_id,
        )
    elif args.stage_id == "ROLLBACK_REHEARSAL":
        receipt = build_rollback(
            config,
            predecessor,
            args.predecessor,
            predecessor_sha256,
            args.source_run_id,
        )
    elif args.stage_id == "PRE_SHADOW_RELEASE":
        if args.results_root is None or args.dag_tool is None:
            raise ValueError("RESULTS_ROOT_AND_DAG_TOOL_REQUIRED")
        module = load_dag_module(args.dag_tool)
        dag = module.evaluate(args.results_root)
        receipt = build_release_from_summary(
            config,
            predecessor,
            predecessor_sha256,
            dag,
            args.source_run_id,
        )
    else:
        raise ValueError(f"UNIMPLEMENTED_STAGE:{args.stage_id}")

    receipt["receipt_sha256"] = canonical_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def self_test() -> None:
    contract = {
        "stages": {
            "ALPHA_LAP_CHALLENGERS": {
                "predecessor_state": "PASS_STRATEGY_TOP3_BUNDLES_COMPLETE",
                "pass_state": "PASS_ALPHA_LAP_CHALLENGERS_REGISTERED",
                "hold_state": "HOLD_ALPHA",
                "max_items": 3,
            },
            "W2_FORWARD": {
                "predecessor_state": "PASS_ALPHA_LAP_CHALLENGERS_REGISTERED",
                "pass_state": "PASS_W2_FORWARD",
                "hold_state": "HOLD_W2",
                "evidence_states": ["PASS_W2_ALPHA_CONFIRMATION"],
            },
            "ROLLBACK_REHEARSAL": {
                "predecessor_state": "PASS_PORTFOLIO_JOINT_RISK",
                "pass_state": "PASS_ROLLBACK_REHEARSAL",
                "hold_state": "HOLD_ROLLBACK",
            },
            "PRE_SHADOW_RELEASE": {
                "predecessor_state": "PASS_ROLLBACK_REHEARSAL",
                "pass_state": "PASS_PRE_SHADOW_RELEASE",
                "hold_state": "HOLD_RELEASE",
                "required_prior_stage_count": 12,
            },
        }
    }
    top3 = {
        "state": "PASS_STRATEGY_TOP3_BUNDLES_COMPLETE",
        "bundles": [{"bundle_id": "control"}, {"bundle_id": "x1"}],
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "promotion_authority": False,
    }
    alpha = build_alpha(contract["stages"]["ALPHA_LAP_CHALLENGERS"], top3, "a" * 64, "1")
    assert alpha["state"] == "PASS_ALPHA_LAP_CHALLENGERS_REGISTERED", alpha
    assert alpha["challenger_count"] == 2

    w2_pre = {
        "state": "PASS_ALPHA_LAP_CHALLENGERS_REGISTERED",
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "promotion_authority": False,
    }
    held = build_evidence_stage("W2_FORWARD", contract["stages"]["W2_FORWARD"], w2_pre, "b" * 64, None, "2")
    assert held["state"] == "HOLD_W2", held

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        evidence_path = root / "w2.json"
        evidence_path.write_text(json.dumps({
            "state": "PASS_W2_ALPHA_CONFIRMATION",
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "promotion_authority": False,
        }), encoding="utf-8")
        passed = build_evidence_stage("W2_FORWARD", contract["stages"]["W2_FORWARD"], w2_pre, "b" * 64, evidence_path, "3")
        assert passed["state"] == "PASS_W2_FORWARD", passed

        predecessor_path = root / "portfolio.json"
        predecessor_path.write_text(json.dumps({
            "state": "PASS_PORTFOLIO_JOINT_RISK",
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "promotion_authority": False,
        }), encoding="utf-8")
        predecessor = load_object(predecessor_path)
        rollback = build_rollback(
            contract["stages"]["ROLLBACK_REHEARSAL"],
            predecessor,
            predecessor_path,
            file_sha(predecessor_path),
            "4",
        )
        assert rollback["state"] == "PASS_ROLLBACK_REHEARSAL", rollback

    release = build_release_from_summary(
        contract["stages"]["PRE_SHADOW_RELEASE"],
        {
            "state": "PASS_ROLLBACK_REHEARSAL",
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "promotion_authority": False,
        },
        "c" * 64,
        {
            "passed_stage_count": 12,
            "passed_stages": [f"s{i}" for i in range(12)],
            "first_blocked_stage": "PRE_SHADOW_RELEASE",
            "eligible_next_stage": "PRE_SHADOW_RELEASE",
            "lineage_policy": "CURRENT_PREDECESSOR_AND_STAGE_RECEIPT_SHA_REQUIRED",
            "dispatch_policy": "ONE_ORDERED_STAGE_AT_A_TIME",
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        },
        "5",
    )
    assert release["state"] == "PASS_PRE_SHADOW_RELEASE", release
    assert release["shadow_start_allowed"] is False
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--stage-id")
    parser.add_argument("--predecessor", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--results-root", type=Path)
    parser.add_argument("--dag-tool", type=Path)
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.contract or not args.stage_id or not args.predecessor or not args.out:
        parser.error("contract, stage-id, predecessor and out are required")
    receipt = run(args)
    print(json.dumps({
        "state": receipt["state"],
        "stage_id": receipt["stage_id"],
        "errors": receipt["errors"],
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
