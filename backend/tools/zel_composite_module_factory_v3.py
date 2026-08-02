from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import zel_composite_module_factory_v2 as v2

VERSION = "ZEL_COMPOSITE_MODULE_FACTORY_V3_BALANCED"
UNORDERED_TYPES = {"CONTEXT_ROUTER", "ADVISORY_COUNCIL"}
ORDERED_TYPES = {"SEQUENTIAL_COMPOSITE"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def ordered_children(
    modules: list[dict[str, Any]], count: int, composite_type: str
) -> Iterable[tuple[dict[str, Any], ...]]:
    if composite_type in ORDERED_TYPES:
        yield from itertools.permutations(modules, count)
        return
    if composite_type in UNORDERED_TYPES:
        yield from itertools.combinations(modules, count)
        return
    raise ValueError(f"UNKNOWN_COMPOSITE_TYPE:{composite_type}")


def generate_pool(
    modules: list[dict[str, Any]], contract: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    generation = contract.get("generation_policy") if isinstance(contract.get("generation_policy"), dict) else {}
    initial = int(generation.get("initial_child_count") or 2)
    maximum = int(generation.get("maximum_child_count") or 3)
    types = [str(x) for x in generation.get("allowed_composite_types", [])]
    accepted: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    symmetric_removed = 0

    for composite_type in sorted(types):
        for count in range(initial, maximum + 1):
            for combo in ordered_children(modules, count, composite_type):
                children = list(combo)
                payload = v2.candidate_payload(children, composite_type)
                payload["child_count"] = count
                payload["selection_bucket"] = f"{composite_type}:{count}"
                errors = v2.compatibility_errors(children, composite_type, contract)
                if errors:
                    rejected.append({
                        "candidate_sha256": payload["composite_sha256"],
                        "child_module_ids": payload["child_module_ids"],
                        "child_count": count,
                        "composite_type": composite_type,
                        "errors": errors,
                    })
                    continue
                accepted[payload["composite_sha256"]] = payload
                if composite_type in UNORDERED_TYPES:
                    symmetric_removed += math.factorial(count) - 1
    return (
        sorted(accepted.values(), key=lambda row: (row["selection_bucket"], row["composite_id"])),
        sorted(rejected, key=lambda row: (
            row["composite_type"], row["child_count"], row["child_module_ids"]
        )),
        symmetric_removed,
    )


def balanced_select(pool: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pool:
        buckets[row["selection_bucket"]].append(row)
    keys = sorted(buckets)
    selected: list[dict[str, Any]] = []
    cursor = {key: 0 for key in keys}
    while len(selected) < cap:
        advanced = False
        for key in keys:
            index = cursor[key]
            if index >= len(buckets[key]):
                continue
            selected.append(buckets[key][index])
            cursor[key] += 1
            advanced = True
            if len(selected) >= cap:
                break
        if not advanced:
            break
    return sorted(selected, key=lambda row: row["composite_id"])


def distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = defaultdict(int)
    by_child_count: dict[str, int] = defaultdict(int)
    by_bucket: dict[str, int] = defaultdict(int)
    for row in rows:
        by_type[row["composite_type"]] += 1
        by_child_count[str(row["child_count"])] += 1
        by_bucket[row["selection_bucket"]] += 1
    return {
        "by_type": dict(sorted(by_type.items())),
        "by_child_count": dict(sorted(by_child_count.items())),
        "by_bucket": dict(sorted(by_bucket.items())),
    }


def build_receipt(
    registry: Mapping[str, Any], contract: Mapping[str, Any], checkpoint_ref: str
) -> dict[str, Any]:
    errors: list[str] = []
    if contract.get("schema_version") != "zel.composite_module_factory.contract.v1":
        errors.append("CONTRACT_SCHEMA")
    if contract.get("factory_enabled") is not False:
        errors.append("FACTORY_MUST_DEFAULT_DISABLED")
    if not checkpoint_ref:
        errors.append("PRE_FACTORY_CHECKPOINT_MISSING")
    safety = contract.get("safety") if isinstance(contract.get("safety"), dict) else {}
    if safety.get("execution_authority") != "NONE":
        errors.append("EXECUTION_AUTHORITY_NOT_NONE")
    if safety.get("order_authority") != "BLOCKED":
        errors.append("ORDER_AUTHORITY_NOT_BLOCKED")

    modules = v2.normalize_modules(registry)
    enabled = [row for row in modules if row["enabled"]]
    generation = contract.get("generation_policy") if isinstance(contract.get("generation_policy"), dict) else {}
    cap = int(generation.get("maximum_composites_per_run") or 30)
    pool, rejected, symmetric_removed = generate_pool(enabled, contract)
    selected = balanced_select(pool, cap)
    selected_distribution = distribution(selected)
    pool_distribution = distribution(pool)

    expected_types = set(str(x) for x in generation.get("allowed_composite_types", []))
    missing_selected_types = sorted(expected_types - set(selected_distribution["by_type"]))
    if missing_selected_types:
        errors.append("MISSING_SELECTED_TYPES:" + ",".join(missing_selected_types))
    child_counts = set(selected_distribution["by_child_count"])
    if not {"2", "3"}.issubset(child_counts):
        errors.append("CHILD_COUNT_COVERAGE_MISSING")

    unordered_seen: set[tuple[str, tuple[str, ...]]] = set()
    symmetric_duplicates = 0
    for row in selected:
        if row["composite_type"] not in UNORDERED_TYPES:
            continue
        key = (row["composite_type"], tuple(sorted(row["child_module_ids"])))
        if key in unordered_seen:
            symmetric_duplicates += 1
        unordered_seen.add(key)
    if symmetric_duplicates:
        errors.append("SYMMETRIC_DUPLICATES_SELECTED")

    placeholder_count = sum(1 for row in modules if len(set(row["source_sha256"])) == 1)
    state = "PASS_COMPOSITE_FACTORY_V3_BALANCED_STATIC_READY" if not errors else "HOLD_COMPOSITE_FACTORY_V3"
    receipt: dict[str, Any] = {
        "schema_version": "zel.composite_module_factory.receipt.v3",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "pre_factory_checkpoint_ref": checkpoint_ref,
        "factory_enabled": False,
        "activation_enabled": False,
        "module_count": len(modules),
        "candidate_pool_count": len(pool),
        "candidate_count": len(selected),
        "rejected_count": len(rejected),
        "symmetric_duplicate_selected_count": symmetric_duplicates,
        "symmetric_permutation_candidates_removed": symmetric_removed,
        "pool_distribution": pool_distribution,
        "selected_distribution": selected_distribution,
        "candidates": selected,
        "rejected_sample": rejected[:200],
        "placeholder_source_sha_count": placeholder_count,
        "source_rebinding_required_before_activation": placeholder_count > 0,
        "true_fusion_performed": False,
        "performance_ranking_used": False,
        "economic_claim_allowed": False,
        "exact_replay_required": True,
        "w2_required": True,
        "w3_required": True,
        "portfolio_joint_risk_required": True,
        "rollback": {
            "available": bool(checkpoint_ref),
            "target_ref": checkpoint_ref,
            "activation_checkpoint_required": True,
            "master_force_reset_forbidden": True,
            "action": "rollback",
        },
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


def self_test() -> None:
    registry, contract = v2.fixture()
    receipt = build_receipt(registry, contract, "pre-composite-factory-v1-fixture")
    assert receipt["state"] == "PASS_COMPOSITE_FACTORY_V3_BALANCED_STATIC_READY", receipt
    assert receipt["symmetric_duplicate_selected_count"] == 0, receipt
    assert set(receipt["selected_distribution"]["by_type"]) == {
        "SEQUENTIAL_COMPOSITE", "CONTEXT_ROUTER", "ADVISORY_COUNCIL"
    }, receipt
    assert {"2", "3"}.issubset(receipt["selected_distribution"]["by_child_count"]), receipt
    assert receipt["factory_enabled"] is False and receipt["activation_enabled"] is False
    assert receipt["execution_authority"] == "NONE"
    assert receipt["order_authority"] == "BLOCKED"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--checkpoint-ref", default="")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.registry or not args.contract or not args.out:
        parser.error("registry, contract and out are required")
    receipt = build_receipt(
        v2.load_object(args.registry), v2.load_object(args.contract), args.checkpoint_ref
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "pool": receipt["candidate_pool_count"],
        "selected": receipt["candidate_count"],
        "rejected": receipt["rejected_count"],
        "symmetric_removed": receipt["symmetric_permutation_candidates_removed"],
        "distribution": receipt["selected_distribution"],
        "errors": receipt["errors"],
    }, sort_keys=True))
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
