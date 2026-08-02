from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_SELECTED_INTERACTIONS_V1"


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
    component: Mapping[str, Any],
    contract: Mapping[str, Any],
    component_file_sha256: str,
    source_run_id: str,
) -> dict[str, Any]:
    errors: list[str] = []
    errors.extend(authority_errors(component))
    if component.get("state") != "PASS_COMPONENT_MAIN_EFFECT_COMPLETE":
        errors.append("COMPONENT_MAIN_EFFECT_NOT_PASS")
    if component.get("selected_interactions_allowed") is not True:
        errors.append("SELECTED_INTERACTIONS_NOT_ALLOWED")
    if contract.get("schema_version") != "zel.selected_interactions.contract.v1":
        errors.append("CONTRACT_SCHEMA")
    if contract.get("stage_id") != "SELECTED_INTERACTIONS":
        errors.append("CONTRACT_STAGE")

    policy = contract.get("selection_policy")
    policy = policy if isinstance(policy, dict) else {}
    axes = component.get(str(policy.get("source_axis_field") or "eligible_axis_ids"))
    if not isinstance(axes, list) or not all(isinstance(axis, str) and axis for axis in axes):
        axes = []
        errors.append("ELIGIBLE_AXIS_IDS_INVALID")
    axes = sorted(set(axes))
    max_axes = int(policy.get("maximum_axis_count") or 4)
    if len(axes) > max_axes:
        errors.append("ELIGIBLE_AXIS_COUNT_EXCEEDED")
    interaction_audit = component.get("interaction_audit")
    interaction_audit = interaction_audit if isinstance(interaction_audit, dict) else {}
    if policy.get("order_stability_required") is True and interaction_audit.get("order_stable") is not True:
        errors.append("ORDER_STABILITY_NOT_PROVED")

    combination_size = int(policy.get("combination_size") or 2)
    maximum = int(policy.get("maximum_interaction_count") or 6)
    pairs = list(itertools.combinations(axes, combination_size)) if len(axes) >= combination_size else []
    if len(pairs) > maximum:
        errors.append("INTERACTION_COUNT_EXCEEDED")
        pairs = pairs[:maximum]
    if not pairs and policy.get("empty_selection_is_valid") is not True:
        errors.append("EMPTY_SELECTION_FORBIDDEN")

    interactions = []
    for left, right in pairs:
        payload = {
            "axes": [left, right],
            "component_data_fingerprint": component.get("component_data_fingerprint"),
            "component_result_sha256": component.get("component_result_sha256"),
            "selection_method": "DETERMINISTIC_PAIRWISE_MATERIAL_AXES",
            "future_exact_replay_required": policy.get("future_exact_replay_required") is True,
            "economic_claim_allowed": False,
        }
        interactions.append({
            "interaction_id": f"{left}__X__{right}",
            "interaction_sha256": canonical_sha(payload),
            **payload,
        })

    passed = not errors
    receipt: dict[str, Any] = {
        "schema_version": "zel.selected_interactions.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_SELECTED_INTERACTIONS_COMPLETE" if passed else "HOLD_SELECTED_INTERACTIONS",
        "stage_id": "SELECTED_INTERACTIONS",
        "source_workflow": "ZEL Selected Interactions V1",
        "source_run_id": str(source_run_id),
        "predecessor_stage_id": "COMPONENT_MAIN_EFFECT",
        "predecessor_receipt_sha256": component_file_sha256,
        "component_receipt_claimed_sha256": component.get("receipt_sha256"),
        "component_data_fingerprint": component.get("component_data_fingerprint"),
        "eligible_axis_ids": axes,
        "selected_interaction_count": len(interactions),
        "selected_interactions": interactions,
        "order_stability": {
            "order_stable": interaction_audit.get("order_stable") is True,
            "tested_order_count": interaction_audit.get("tested_order_count"),
            "net_spread_pct_points": interaction_audit.get("net_spread_pct_points"),
            "threshold_pct_points": interaction_audit.get("threshold_pct_points"),
            "canonical_order": list(interaction_audit.get("canonical_order") or []),
        },
        "empty_selection_valid": policy.get("empty_selection_is_valid") is True,
        "strategy_top3_bundles_allowed": passed,
        "economic_claim_allowed": False,
        "future_exact_replay_required": policy.get("future_exact_replay_required") is True,
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


def run(component_path: Path, contract_path: Path, out: Path, source_run_id: str) -> dict[str, Any]:
    receipt = build_receipt(
        load_object(component_path),
        load_object(contract_path),
        file_sha(component_path),
        source_run_id,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    component = {
        "state": "PASS_COMPONENT_MAIN_EFFECT_COMPLETE",
        "selected_interactions_allowed": True,
        "eligible_axis_ids": ["BOT_POLICY", "TEAM_POLICY", "SKILL_PROFILE"],
        "interaction_audit": {
            "order_stable": True,
            "tested_order_count": 6,
            "net_spread_pct_points": 0.05,
            "threshold_pct_points": 0.2,
            "canonical_order": ["TEAM", "SKILL", "ZBOT"],
        },
        "component_data_fingerprint": "a" * 64,
        "component_result_sha256": "b" * 64,
        "receipt_sha256": "c" * 64,
        "live_enabled": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    contract = {
        "schema_version": "zel.selected_interactions.contract.v1",
        "stage_id": "SELECTED_INTERACTIONS",
        "selection_policy": {
            "source_axis_field": "eligible_axis_ids",
            "combination_size": 2,
            "maximum_axis_count": 4,
            "maximum_interaction_count": 6,
            "order_stability_required": True,
            "empty_selection_is_valid": True,
            "future_exact_replay_required": True,
        },
    }
    return component, contract


def self_test() -> None:
    component, contract = fixture()
    passed = build_receipt(component, contract, "d" * 64, "123")
    assert passed["state"] == "PASS_SELECTED_INTERACTIONS_COMPLETE", passed
    assert passed["selected_interaction_count"] == 3, passed
    assert passed["strategy_top3_bundles_allowed"] is True
    assert passed["economic_claim_allowed"] is False

    unstable = dict(component)
    unstable["interaction_audit"] = {"order_stable": False}
    held = build_receipt(unstable, contract, "d" * 64, "124")
    assert held["state"] == "HOLD_SELECTED_INTERACTIONS", held
    assert "ORDER_STABILITY_NOT_PROVED" in held["errors"]

    empty = dict(component)
    empty["eligible_axis_ids"] = []
    empty_pass = build_receipt(empty, contract, "d" * 64, "125")
    assert empty_pass["state"] == "PASS_SELECTED_INTERACTIONS_COMPLETE", empty_pass
    assert empty_pass["selected_interaction_count"] == 0
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.component or not args.contract or not args.out:
        parser.error("component, contract and out are required")
    receipt = run(args.component, args.contract, args.out, args.source_run_id)
    print(json.dumps({
        "state": receipt["state"],
        "interaction_count": receipt["selected_interaction_count"],
        "errors": receipt["errors"],
    }, sort_keys=True))
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
