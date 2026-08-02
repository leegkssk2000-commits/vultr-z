from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_STRATEGY_TOP3_BUNDLES_V1"


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


def authority_errors(row: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if row.get("execution_authority") != "NONE":
        errors.append("EXECUTION_AUTHORITY_NOT_NONE")
    if row.get("order_authority") != "BLOCKED":
        errors.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if row.get("promotion_authority") is not False:
        errors.append("PROMOTION_AUTHORITY_NOT_FALSE")
    if row.get("live_enabled") is not False:
        errors.append("LIVE_ENABLED_NOT_FALSE")
    return errors


def build_receipt(
    selected: Mapping[str, Any],
    contract: Mapping[str, Any],
    predecessor_sha256: str,
    source_run_id: str,
) -> dict[str, Any]:
    errors = authority_errors(selected)
    if selected.get("state") != "PASS_SELECTED_INTERACTIONS_COMPLETE":
        errors.append("SELECTED_INTERACTIONS_NOT_PASS")
    if selected.get("strategy_top3_bundles_allowed") is not True:
        errors.append("TOP3_BUNDLES_NOT_ALLOWED")
    if contract.get("schema_version") != "zel.strategy_top3_bundles.contract.v1":
        errors.append("CONTRACT_SCHEMA")
    if contract.get("stage_id") != "STRATEGY_TOP3_BUNDLES":
        errors.append("CONTRACT_STAGE")

    policy = contract.get("bundle_policy")
    policy = policy if isinstance(policy, dict) else {}
    maximum = int(policy.get("maximum_bundle_count") or 3)
    interaction_maximum = int(policy.get("maximum_interaction_bundles") or 2)
    interactions = selected.get("selected_interactions")
    if not isinstance(interactions, list) or not all(isinstance(row, dict) for row in interactions):
        interactions = []
        errors.append("SELECTED_INTERACTIONS_LIST_INVALID")
    interactions = sorted(interactions, key=lambda row: str(row.get("interaction_id") or ""))

    bundles: list[dict[str, Any]] = []
    if policy.get("control_bundle_required") is True:
        payload = {
            "bundle_type": "CONTROL_COMPONENT_MAIN_EFFECT",
            "axes": list(selected.get("eligible_axis_ids") or []),
            "interaction_ids": [],
            "rank_basis": "STRUCTURAL_CONTROL_FIRST_NOT_PERFORMANCE",
            "future_exact_replay_required": policy.get("future_exact_replay_required") is True,
            "economic_claim_allowed": False,
        }
        bundles.append({
            "bundle_id": "BUNDLE_CONTROL_COMPONENT_MAIN_EFFECT",
            "bundle_sha256": canonical_sha(payload),
            **payload,
        })

    for row in interactions[:interaction_maximum]:
        interaction_id = str(row.get("interaction_id") or "")
        if not interaction_id:
            errors.append("INTERACTION_ID_MISSING")
            continue
        payload = {
            "bundle_type": "SELECTED_INTERACTION_HYPOTHESIS",
            "axes": list(row.get("axes") or []),
            "interaction_ids": [interaction_id],
            "rank_basis": "INTERACTION_ID_ASC_NOT_PERFORMANCE",
            "future_exact_replay_required": policy.get("future_exact_replay_required") is True,
            "economic_claim_allowed": False,
        }
        bundles.append({
            "bundle_id": f"BUNDLE_{interaction_id}",
            "bundle_sha256": canonical_sha(payload),
            **payload,
        })

    if len(bundles) > maximum:
        errors.append("BUNDLE_COUNT_EXCEEDED")
        bundles = bundles[:maximum]
    for index, bundle in enumerate(bundles, start=1):
        bundle["structural_order"] = index
    if not bundles:
        errors.append("NO_BUNDLES_CREATED")

    passed = not errors
    receipt: dict[str, Any] = {
        "schema_version": "zel.strategy_top3_bundles.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_STRATEGY_TOP3_BUNDLES_COMPLETE" if passed else "HOLD_STRATEGY_TOP3_BUNDLES",
        "stage_id": "STRATEGY_TOP3_BUNDLES",
        "source_workflow": "ZEL Strategy Top3 Bundles V1",
        "source_run_id": str(source_run_id),
        "predecessor_stage_id": "SELECTED_INTERACTIONS",
        "predecessor_receipt_sha256": predecessor_sha256,
        "selected_interactions_claimed_sha256": selected.get("receipt_sha256"),
        "bundle_count": len(bundles),
        "bundles": bundles,
        "ordering": policy.get("ordering"),
        "performance_ranking_used": False,
        "performance_ranking_forbidden": policy.get("performance_ranking_forbidden") is True,
        "alpha_lap_challengers_allowed": passed,
        "future_exact_replay_required": policy.get("future_exact_replay_required") is True,
        "economic_claim_allowed": False,
        "errors": sorted(set(errors)),
        "active_data_b_1m_mutated": False,
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


def run(selected_path: Path, contract_path: Path, out: Path, source_run_id: str) -> dict[str, Any]:
    receipt = build_receipt(
        load_object(selected_path),
        load_object(contract_path),
        file_sha(selected_path),
        source_run_id,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    selected = {
        "state": "PASS_SELECTED_INTERACTIONS_COMPLETE",
        "strategy_top3_bundles_allowed": True,
        "eligible_axis_ids": ["BOT_POLICY", "TEAM_POLICY", "SKILL_PROFILE"],
        "selected_interactions": [
            {"interaction_id": "BOT_POLICY__X__TEAM_POLICY", "axes": ["BOT_POLICY", "TEAM_POLICY"]},
            {"interaction_id": "BOT_POLICY__X__SKILL_PROFILE", "axes": ["BOT_POLICY", "SKILL_PROFILE"]},
            {"interaction_id": "SKILL_PROFILE__X__TEAM_POLICY", "axes": ["SKILL_PROFILE", "TEAM_POLICY"]}
        ],
        "receipt_sha256": "a" * 64,
        "live_enabled": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED"
    }
    contract = {
        "schema_version": "zel.strategy_top3_bundles.contract.v1",
        "stage_id": "STRATEGY_TOP3_BUNDLES",
        "bundle_policy": {
            "maximum_bundle_count": 3,
            "control_bundle_required": True,
            "maximum_interaction_bundles": 2,
            "ordering": "CONTROL_THEN_INTERACTION_ID_ASC",
            "performance_ranking_forbidden": True,
            "future_exact_replay_required": True
        }
    }
    return selected, contract


def self_test() -> None:
    selected, contract = fixture()
    passed = build_receipt(selected, contract, "b" * 64, "123")
    assert passed["state"] == "PASS_STRATEGY_TOP3_BUNDLES_COMPLETE", passed
    assert passed["bundle_count"] == 3, passed
    assert passed["bundles"][0]["bundle_type"] == "CONTROL_COMPONENT_MAIN_EFFECT", passed
    assert passed["performance_ranking_used"] is False
    assert passed["alpha_lap_challengers_allowed"] is True

    unsafe = dict(selected)
    unsafe["promotion_authority"] = True
    held = build_receipt(unsafe, contract, "b" * 64, "124")
    assert held["state"] == "HOLD_STRATEGY_TOP3_BUNDLES", held
    assert "PROMOTION_AUTHORITY_NOT_FALSE" in held["errors"]
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected-interactions", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.selected_interactions or not args.contract or not args.out:
        parser.error("selected-interactions, contract and out are required")
    receipt = run(args.selected_interactions, args.contract, args.out, args.source_run_id)
    print(json.dumps({
        "state": receipt["state"],
        "bundle_count": receipt["bundle_count"],
        "errors": receipt["errors"]
    }, sort_keys=True))
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
