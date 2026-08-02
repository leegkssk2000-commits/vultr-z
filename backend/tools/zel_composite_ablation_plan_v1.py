from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_COMPOSITE_ABLATION_PLAN_V1"
UNORDERED_TYPES = {"CONTEXT_ROUTER", "ADVISORY_COUNCIL"}
ORDERED_TYPES = {"SEQUENTIAL_COMPOSITE"}
ECONOMIC_TRANSFORM_MODES = {"EXECUTABLE_REPLAY"}
PARITY_ONLY_MODES = {"STATIC_ROLE_CONTEXT", "ADVISORY_PROJECTION", "LINEAGE_AUDITOR"}
STRUCTURAL_ONLY_MODES = {"RUNTIME_OBSERVER_ONLY"}
POST_SCORE_MODES = {"POST_SCORE_RISK_GOVERNOR"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def adapter_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = contract.get("adapters") if isinstance(contract.get("adapters"), list) else []
    return {str(row.get("module_id") or ""): row for row in rows if isinstance(row, dict)}


def registry_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = registry.get("modules") if isinstance(registry.get("modules"), list) else []
    return {str(row.get("module_id") or ""): row for row in rows if isinstance(row, dict)}


def valid_order(order: tuple[str, ...], registry: dict[str, dict[str, Any]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    positions = {module_id: index for index, module_id in enumerate(order)}
    for module_id in order:
        row = registry.get(module_id, {})
        for dependency in row.get("depends_on", []):
            dependency = str(dependency)
            if dependency in positions and positions[dependency] >= positions[module_id]:
                errors.append(f"DEPENDENCY_NOT_PRIOR:{module_id}:{dependency}")
    if "STRATEGY_SIGNAL" in positions:
        for module_id in order:
            if module_id == "STRATEGY_SIGNAL":
                continue
            module_type = str(registry.get(module_id, {}).get("module_type") or "")
            if module_type in {"METHOD", "SKILL", "EXECUTION_COST_CRITIC"} and positions[module_id] < positions["STRATEGY_SIGNAL"]:
                errors.append(f"TRANSFORM_BEFORE_SIGNAL:{module_id}")
    return not errors, sorted(set(errors))


def classify_children(children: list[str], adapters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = sorted(module_id for module_id in children if module_id not in adapters)
    modes = {module_id: str(adapters.get(module_id, {}).get("node_mode") or "MISSING") for module_id in children}
    post_score = sorted(module_id for module_id, mode in modes.items() if mode in POST_SCORE_MODES)
    structural_only = sorted(module_id for module_id, mode in modes.items() if mode in STRUCTURAL_ONLY_MODES)
    parity_only = sorted(module_id for module_id, mode in modes.items() if mode in PARITY_ONLY_MODES)
    economic_transforms = sorted(module_id for module_id, mode in modes.items() if mode in ECONOMIC_TRANSFORM_MODES and module_id != "STRATEGY_SIGNAL")
    has_base = "STRATEGY_SIGNAL" in children
    w2_blockers: list[str] = []
    if missing:
        w2_blockers.append("ADAPTER_MISSING")
    if not has_base:
        w2_blockers.append("BASE_SIGNAL_MISSING")
    if structural_only:
        w2_blockers.append("RUNTIME_OBSERVER_STRUCTURAL_ONLY")
    if post_score:
        w2_blockers.append("POST_SCORE_MODULE_INSIDE_CANDIDATE")
    if any(not bool(adapters.get(module_id, {}).get("w2_eligible")) for module_id in children if module_id in adapters):
        w2_blockers.append("W2_INELIGIBLE_MODULE")
    w2_eligible = not w2_blockers
    if not w2_eligible:
        if post_score:
            candidate_class = "POST_W3_OR_STRUCTURAL_ONLY"
        elif structural_only:
            candidate_class = "STRUCTURAL_ONLY_RUNTIME_OBSERVER"
        elif not has_base:
            candidate_class = "STRUCTURAL_ONLY_NO_BASE_SIGNAL"
        else:
            candidate_class = "STRUCTURAL_ONLY_CONTRACT_BLOCKED"
    elif economic_transforms:
        candidate_class = "W2_ECONOMIC_REPLAY_ELIGIBLE"
    else:
        candidate_class = "W2_CONTEXT_PARITY_ONLY"
    direct_alpha_nodes = sorted(
        module_id
        for module_id in children
        if bool(adapters.get(module_id, {}).get("direct_alpha_claim_allowed"))
    )
    forbidden_direct_alpha_nodes = sorted(set(children) - set(direct_alpha_nodes))
    return {
        "candidate_class": candidate_class,
        "w2_eligible": w2_eligible,
        "w3_eligible": w2_eligible and all(bool(adapters.get(module_id, {}).get("w3_eligible")) for module_id in children),
        "has_base_signal": has_base,
        "node_modes": modes,
        "economic_transform_nodes": economic_transforms,
        "parity_only_nodes": parity_only,
        "structural_only_nodes": structural_only,
        "post_score_nodes": post_score,
        "direct_alpha_claim_nodes": direct_alpha_nodes,
        "direct_alpha_claim_forbidden_nodes": forbidden_direct_alpha_nodes,
        "w2_blockers": sorted(set(w2_blockers)),
    }


def leave_one_out(children: list[str], adapters: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for index, removed in enumerate(children):
        retained = children[:index] + children[index + 1 :]
        classification = classify_children(retained, adapters)
        payload = {
            "variant_kind": "LEAVE_ONE_CHILD_OUT",
            "removed_module_id": removed,
            "retained_child_module_ids": retained,
            "classification": classification,
        }
        payload["variant_sha256"] = stable_sha(payload)
        variants.append(payload)
    return variants


def order_permutations(
    children: list[str],
    composite_type: str,
    registry: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if composite_type in UNORDERED_TYPES:
        return [], []
    if composite_type not in ORDERED_TYPES:
        return [], [{"order": children, "errors": [f"UNKNOWN_COMPOSITE_TYPE:{composite_type}"]}]
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    original = tuple(children)
    for order in itertools.permutations(children):
        valid, errors = valid_order(order, registry)
        row = {
            "order": list(order),
            "is_original_order": order == original,
            "order_sha256": stable_sha({"order": list(order), "composite_type": composite_type}),
        }
        if valid:
            accepted.append(row)
        else:
            rejected.append({**row, "errors": errors})
    accepted.sort(key=lambda row: (not row["is_original_order"], row["order"]))
    rejected.sort(key=lambda row: row["order"])
    return accepted, rejected


def build(factory: dict[str, Any], contract: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if factory.get("state") != "PASS_COMPOSITE_FACTORY_V3_BALANCED_STATIC_READY":
        errors.append("FACTORY_STATE_NOT_PASS")
    if contract.get("schema_version") != "zel.composite.adapter_contract.v1":
        errors.append("ADAPTER_CONTRACT_SCHEMA_INVALID")
    adapters = adapter_map(contract)
    modules = registry_map(registry)
    if len(adapters) != 12:
        errors.append("ADAPTER_COUNT_NOT_12")
    if len(modules) != 12:
        errors.append("REGISTRY_MODULE_COUNT_NOT_12")
    plans: list[dict[str, Any]] = []
    candidates = factory.get("candidates") if isinstance(factory.get("candidates"), list) else []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        children = [str(value) for value in candidate.get("child_module_ids", [])]
        classification = classify_children(children, adapters)
        accepted_orders, rejected_orders = order_permutations(
            children,
            str(candidate.get("composite_type") or ""),
            modules,
        )
        plan = {
            "composite_id": candidate.get("composite_id"),
            "composite_sha256": candidate.get("composite_sha256"),
            "composite_type": candidate.get("composite_type"),
            "child_module_ids": children,
            "child_count": len(children),
            "classification": classification,
            "leave_one_out_variants": leave_one_out(children, adapters),
            "valid_order_permutations": accepted_orders,
            "rejected_order_permutations": rejected_orders,
            "valid_order_permutation_count": len(accepted_orders),
            "rejected_order_permutation_count": len(rejected_orders),
            "exact_replay_started": False,
            "w2_started": False,
            "w3_started": False,
            "selection_authority": False,
            "promotion_authority": False,
        }
        plan["plan_sha256"] = stable_sha(plan)
        plans.append(plan)
    plans.sort(key=lambda row: str(row.get("composite_id") or ""))
    class_counts = dict(sorted(Counter(row["classification"]["candidate_class"] for row in plans).items()))
    w2_candidates = [row["composite_id"] for row in plans if row["classification"]["w2_eligible"]]
    w3_candidates = [row["composite_id"] for row in plans if row["classification"]["w3_eligible"]]
    if len(plans) != int(factory.get("candidate_count") or 0):
        errors.append("CANDIDATE_COUNT_MISMATCH")
    if not plans:
        errors.append("NO_CANDIDATES")
    state = "PASS_COMPOSITE_ABLATION_ORDER_PLAN" if not errors else "HOLD_COMPOSITE_ABLATION_ORDER_PLAN"
    result: dict[str, Any] = {
        "schema_version": "zel.composite.ablation_order_plan.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "factory_receipt_sha256": factory.get("receipt_sha256"),
        "adapter_contract_sha256": stable_sha(contract),
        "pinned_registry_sha256": stable_sha(registry),
        "candidate_count": len(plans),
        "candidate_class_counts": class_counts,
        "w2_eligible_candidate_count": len(w2_candidates),
        "w3_eligible_candidate_count": len(w3_candidates),
        "w2_eligible_composite_ids": w2_candidates,
        "w3_eligible_composite_ids": w3_candidates,
        "leave_one_out_variant_count": sum(len(row["leave_one_out_variants"]) for row in plans),
        "valid_order_permutation_count": sum(row["valid_order_permutation_count"] for row in plans),
        "rejected_order_permutation_count": sum(row["rejected_order_permutation_count"] for row in plans),
        "plans": plans,
        "errors": sorted(set(errors)),
        "terminal_required_before_execution": True,
        "terminal_pass_observed": False,
        "economic_claim_allowed": False,
        "exact_replay_started": False,
        "w2_started": False,
        "w3_started": False,
        "portfolio_joint_risk_started": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> None:
    adapters = []
    for module_id, mode, w2 in (
        ("STRATEGY_SIGNAL", "EXECUTABLE_REPLAY", True),
        ("TRADE_METHOD", "EXECUTABLE_REPLAY", True),
        ("LBOT", "STATIC_ROLE_CONTEXT", True),
        ("ZICO", "RUNTIME_OBSERVER_ONLY", False),
        ("PORTFOLIO_GOVERNOR", "POST_SCORE_RISK_GOVERNOR", False),
    ):
        adapters.append({
            "module_id": module_id,
            "node_mode": mode,
            "w2_eligible": w2,
            "w3_eligible": w2,
            "direct_alpha_claim_allowed": module_id in {"STRATEGY_SIGNAL", "TRADE_METHOD"},
        })
    contract = {"schema_version": "zel.composite.adapter_contract.v1", "adapters": adapters}
    registry = {"modules": [
        {"module_id": "STRATEGY_SIGNAL", "depends_on": [], "module_type": "STRATEGY"},
        {"module_id": "TRADE_METHOD", "depends_on": ["STRATEGY_SIGNAL"], "module_type": "METHOD"},
        {"module_id": "LBOT", "depends_on": [], "module_type": "TEAM_BOT"},
        {"module_id": "ZICO", "depends_on": [], "module_type": "CONTROL_ADVISOR"},
        {"module_id": "PORTFOLIO_GOVERNOR", "depends_on": [], "module_type": "RISK"},
    ]}
    factory = {
        "state": "PASS_COMPOSITE_FACTORY_V3_BALANCED_STATIC_READY",
        "candidate_count": 3,
        "receipt_sha256": "f" * 64,
        "candidates": [
            {"composite_id": "C1", "composite_sha256": "1" * 64, "composite_type": "SEQUENTIAL_COMPOSITE", "child_module_ids": ["STRATEGY_SIGNAL", "TRADE_METHOD"]},
            {"composite_id": "C2", "composite_sha256": "2" * 64, "composite_type": "CONTEXT_ROUTER", "child_module_ids": ["LBOT", "STRATEGY_SIGNAL"]},
            {"composite_id": "C3", "composite_sha256": "3" * 64, "composite_type": "ADVISORY_COUNCIL", "child_module_ids": ["ZICO", "STRATEGY_SIGNAL"]},
        ],
    }
    row = build(factory, contract, registry)
    assert row["state"] == "PASS_COMPOSITE_ABLATION_ORDER_PLAN", row
    assert row["w2_eligible_candidate_count"] == 2, row
    assert row["candidate_class_counts"]["STRUCTURAL_ONLY_RUNTIME_OBSERVER"] == 1, row
    assert row["valid_order_permutation_count"] == 1, row
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factory", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.factory or not args.contract or not args.registry or not args.out:
        parser.error("factory, contract, registry and out are required")
    row = build(
        json.loads(args.factory.read_text(encoding="utf-8")),
        json.loads(args.contract.read_text(encoding="utf-8")),
        json.loads(args.registry.read_text(encoding="utf-8")),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": row["state"],
        "candidates": row["candidate_count"],
        "classes": row["candidate_class_counts"],
        "w2_eligible": row["w2_eligible_candidate_count"],
        "loo": row["leave_one_out_variant_count"],
        "valid_orders": row["valid_order_permutation_count"],
        "errors": row["errors"],
    }, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
