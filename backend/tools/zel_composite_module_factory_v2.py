from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_COMPOSITE_MODULE_FACTORY_V2"
OWNER_AUTHORITIES = ("RISK_OWNER", "ORDER_OWNER", "STATE_WRITER")
GLOBAL_CONTEXT_INPUTS = {"MARKET_CONTEXT", "POSITION_CONTEXT", "RISK_CONTEXT"}
ALLOWED_TYPES = {"SEQUENTIAL_COMPOSITE", "CONTEXT_ROUTER", "ADVISORY_COUNCIL"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def normalize_modules(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_rows = registry.get("modules")
    if not isinstance(raw_rows, list):
        raise ValueError("MODULES_LIST_REQUIRED")
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ValueError("MODULE_OBJECT_REQUIRED")
        module_id = str(raw.get("module_id") or "").strip()
        if not module_id or module_id in seen:
            raise ValueError(f"INVALID_OR_DUPLICATE_MODULE_ID:{module_id}")
        seen.add(module_id)
        authorities = sorted(set(str(x) for x in raw.get("authorities", [])))
        unknown = [x for x in authorities if x not in OWNER_AUTHORITIES and x != "ADVISORY_ONLY"]
        if unknown:
            raise ValueError(f"UNKNOWN_AUTHORITY:{module_id}:{','.join(unknown)}")
        source_sha = str(raw.get("source_sha256") or "")
        if len(source_sha) != 64:
            raise ValueError(f"SOURCE_SHA_LENGTH:{module_id}")
        rows.append({
            "module_id": module_id,
            "module_type": str(raw.get("module_type") or "UNKNOWN"),
            "inputs": sorted(set(str(x) for x in raw.get("inputs", []))),
            "outputs": sorted(set(str(x) for x in raw.get("outputs", []))),
            "depends_on": sorted(set(str(x) for x in raw.get("depends_on", []))),
            "authorities": authorities,
            "latency_ms": float(raw.get("latency_ms") or 0.0),
            "cost_bps": float(raw.get("cost_bps") or 0.0),
            "enabled": bool(raw.get("enabled", True)),
            "immutable_child": bool(raw.get("immutable_child", True)),
            "source_sha256": source_sha,
        })
    return sorted(rows, key=lambda row: row["module_id"])


def common_errors(children: list[dict[str, Any]], contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    ids = [row["module_id"] for row in children]
    if len(ids) != len(set(ids)):
        errors.append("DUPLICATE_CHILD")
    if any(not row["immutable_child"] for row in children):
        errors.append("MUTABLE_CHILD_FORBIDDEN")
    for authority in OWNER_AUTHORITIES:
        owners = [row["module_id"] for row in children if authority in row["authorities"]]
        if len(owners) > 1:
            errors.append(f"MULTIPLE_{authority}")
    policy = contract.get("compatibility") if isinstance(contract.get("compatibility"), dict) else {}
    if sum(row["latency_ms"] for row in children) > float(policy.get("maximum_total_latency_ms") or 1500):
        errors.append("LATENCY_BUDGET_EXCEEDED")
    if sum(row["cost_bps"] for row in children) > float(policy.get("maximum_total_cost_bps") or 35):
        errors.append("COST_BUDGET_EXCEEDED")
    return errors


def sequential_errors(children: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    produced: set[str] = set()
    prior_ids: set[str] = set()
    for index, child in enumerate(children):
        inputs = set(child["inputs"])
        non_context = inputs - GLOBAL_CONTEXT_INPUTS
        unresolved = non_context - produced
        if unresolved:
            errors.append(f"UNSATISFIED_INPUT:{child['module_id']}:{','.join(sorted(unresolved))}")
        if index > 0 and not (inputs & produced):
            errors.append(f"NO_UPSTREAM_DATAFLOW:{child['module_id']}")
        missing_dependencies = set(child["depends_on"]) - prior_ids
        if missing_dependencies:
            errors.append(
                f"DEPENDENCY_NOT_PRIOR:{child['module_id']}:{','.join(sorted(missing_dependencies))}"
            )
        produced.update(child["outputs"])
        prior_ids.add(child["module_id"])
    return errors


def router_errors(children: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for child in children:
        inputs = set(child["inputs"])
        if not inputs or not inputs.issubset(GLOBAL_CONTEXT_INPUTS):
            errors.append(f"ROUTER_CHILD_REQUIRES_DERIVED_INPUT:{child['module_id']}")
        if child["depends_on"]:
            errors.append(f"ROUTER_CHILD_DEPENDENCY_FORBIDDEN:{child['module_id']}")
    return errors


def council_errors(children: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for child in children:
        if child["authorities"] != ["ADVISORY_ONLY"]:
            errors.append(f"COUNCIL_NON_ADVISORY_CHILD:{child['module_id']}")
        inputs = set(child["inputs"])
        if not inputs or not inputs.issubset(GLOBAL_CONTEXT_INPUTS):
            errors.append(f"COUNCIL_CHILD_REQUIRES_DERIVED_INPUT:{child['module_id']}")
        if child["depends_on"]:
            errors.append(f"COUNCIL_CHILD_DEPENDENCY_FORBIDDEN:{child['module_id']}")
    return errors


def compatibility_errors(
    children: list[dict[str, Any]], composite_type: str, contract: Mapping[str, Any]
) -> list[str]:
    errors = common_errors(children, contract)
    if composite_type == "SEQUENTIAL_COMPOSITE":
        errors.extend(sequential_errors(children))
    elif composite_type == "CONTEXT_ROUTER":
        errors.extend(router_errors(children))
    elif composite_type == "ADVISORY_COUNCIL":
        errors.extend(council_errors(children))
    else:
        errors.append(f"UNKNOWN_COMPOSITE_TYPE:{composite_type}")
    return sorted(set(errors))


def candidate_payload(children: list[dict[str, Any]], composite_type: str) -> dict[str, Any]:
    payload = {
        "composite_type": composite_type,
        "child_module_ids": [row["module_id"] for row in children],
        "child_source_sha256": [row["source_sha256"] for row in children],
        "total_latency_ms": round(sum(row["latency_ms"] for row in children), 6),
        "total_cost_bps": round(sum(row["cost_bps"] for row in children), 6),
        "authorities": sorted({x for row in children for x in row["authorities"]}),
        "activation_enabled": False,
        "economic_claim_allowed": False,
        "exact_replay_required": True,
    }
    payload["composite_id"] = "CMP2_" + canonical_sha(payload)[:20].upper()
    payload["composite_sha256"] = canonical_sha(payload)
    return payload


def build_receipt(
    registry: Mapping[str, Any], contract: Mapping[str, Any], checkpoint_ref: str
) -> dict[str, Any]:
    errors: list[str] = []
    if contract.get("schema_version") != "zel.composite_module_factory.contract.v1":
        errors.append("CONTRACT_SCHEMA")
    if contract.get("factory_enabled") is not False:
        errors.append("FACTORY_MUST_DEFAULT_DISABLED")
    safety = contract.get("safety") if isinstance(contract.get("safety"), dict) else {}
    if safety.get("execution_authority") != "NONE":
        errors.append("EXECUTION_AUTHORITY_NOT_NONE")
    if safety.get("order_authority") != "BLOCKED":
        errors.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if not checkpoint_ref:
        errors.append("PRE_FACTORY_CHECKPOINT_MISSING")

    modules = normalize_modules(registry)
    enabled = [row for row in modules if row["enabled"]]
    generation = contract.get("generation_policy") if isinstance(contract.get("generation_policy"), dict) else {}
    initial = int(generation.get("initial_child_count") or 2)
    maximum = int(generation.get("maximum_child_count") or 3)
    cap = int(generation.get("maximum_composites_per_run") or 30)
    composite_types = [str(x) for x in generation.get("allowed_composite_types", [])]
    if initial < 2 or maximum > 3 or initial > maximum:
        errors.append("INVALID_CHILD_BOUNDS")
    if not composite_types or any(x not in ALLOWED_TYPES for x in composite_types):
        errors.append("INVALID_COMPOSITE_TYPES")

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for count in range(initial, maximum + 1):
        for combo in itertools.permutations(enabled, count):
            children = list(combo)
            for composite_type in composite_types:
                payload = candidate_payload(children, composite_type)
                combo_errors = compatibility_errors(children, composite_type, contract)
                if combo_errors:
                    rejected.append({
                        "candidate_sha256": payload["composite_sha256"],
                        "child_module_ids": payload["child_module_ids"],
                        "composite_type": composite_type,
                        "errors": combo_errors,
                    })
                else:
                    candidates.append(payload)
            if len(candidates) >= cap:
                break
        if len(candidates) >= cap:
            break
    unique = {row["composite_sha256"]: row for row in candidates}
    candidates = sorted(unique.values(), key=lambda row: row["composite_id"])[:cap]

    invalid_first_child_count = 0
    for candidate in candidates:
        first_id = candidate["child_module_ids"][0]
        first = next(row for row in enabled if row["module_id"] == first_id)
        if set(first["inputs"]) - GLOBAL_CONTEXT_INPUTS:
            invalid_first_child_count += 1
    if invalid_first_child_count:
        errors.append("VALID_CANDIDATE_HAS_UNSATISFIED_FIRST_CHILD")

    placeholder_sha_count = sum(
        1 for row in modules if len(set(row["source_sha256"])) == 1
    )
    passed = not errors
    receipt: dict[str, Any] = {
        "schema_version": "zel.composite_module_factory.receipt.v2",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_COMPOSITE_FACTORY_V2_STATIC_READY" if passed else "HOLD_COMPOSITE_FACTORY_V2",
        "pre_factory_checkpoint_ref": checkpoint_ref,
        "factory_enabled": False,
        "activation_enabled": False,
        "module_count": len(modules),
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "invalid_first_child_count": invalid_first_child_count,
        "placeholder_source_sha_count": placeholder_sha_count,
        "source_rebinding_required_before_activation": placeholder_sha_count > 0,
        "candidates": candidates,
        "rejected": rejected[:200],
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


def fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    registry = {
        "modules": [
            {
                "module_id": "SIGNAL", "module_type": "STRATEGY",
                "inputs": ["MARKET_CONTEXT"], "outputs": ["SIGNAL_CANDIDATE"],
                "depends_on": [], "authorities": ["ADVISORY_ONLY"],
                "latency_ms": 10, "cost_bps": 0, "enabled": True,
                "immutable_child": True, "source_sha256": "a" * 64,
            },
            {
                "module_id": "LICO", "module_type": "COST",
                "inputs": ["SIGNAL_CANDIDATE"], "outputs": ["COST_FILTERED_SIGNAL"],
                "depends_on": ["SIGNAL"], "authorities": ["ADVISORY_ONLY"],
                "latency_ms": 10, "cost_bps": 4, "enabled": True,
                "immutable_child": True, "source_sha256": "b" * 64,
            },
            {
                "module_id": "OBSERVER", "module_type": "TEAM_BOT",
                "inputs": ["MARKET_CONTEXT"], "outputs": ["OBSERVATION_CONTEXT"],
                "depends_on": [], "authorities": ["ADVISORY_ONLY"],
                "latency_ms": 5, "cost_bps": 0, "enabled": True,
                "immutable_child": True, "source_sha256": "c" * 64,
            },
        ]
    }
    contract = {
        "schema_version": "zel.composite_module_factory.contract.v1",
        "factory_enabled": False,
        "generation_policy": {
            "initial_child_count": 2,
            "maximum_child_count": 3,
            "maximum_composites_per_run": 30,
            "allowed_composite_types": sorted(ALLOWED_TYPES),
        },
        "compatibility": {
            "maximum_total_latency_ms": 1500,
            "maximum_total_cost_bps": 35,
        },
        "safety": {"execution_authority": "NONE", "order_authority": "BLOCKED"},
    }
    return registry, contract


def self_test() -> None:
    registry, contract = fixture()
    modules = normalize_modules(registry)
    by_id = {row["module_id"]: row for row in modules}
    assert compatibility_errors([by_id["LICO"], by_id["SIGNAL"]], "SEQUENTIAL_COMPOSITE", contract)
    assert not compatibility_errors([by_id["SIGNAL"], by_id["LICO"]], "SEQUENTIAL_COMPOSITE", contract)
    assert compatibility_errors([by_id["SIGNAL"], by_id["LICO"]], "CONTEXT_ROUTER", contract)
    assert not compatibility_errors([by_id["SIGNAL"], by_id["OBSERVER"]], "ADVISORY_COUNCIL", contract)
    receipt = build_receipt(registry, contract, "pre-composite-factory-v1-fixture")
    assert receipt["state"] == "PASS_COMPOSITE_FACTORY_V2_STATIC_READY", receipt
    assert receipt["invalid_first_child_count"] == 0, receipt
    assert all(row["activation_enabled"] is False for row in receipt["candidates"])
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
        load_object(args.registry), load_object(args.contract), args.checkpoint_ref
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "candidate_count": receipt["candidate_count"],
        "rejected_count": receipt["rejected_count"],
        "errors": receipt["errors"],
    }, sort_keys=True))
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
