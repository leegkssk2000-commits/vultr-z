from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_COMPOSITE_MODULE_FACTORY_V1"
OWNER_AUTHORITIES = ("RISK_OWNER", "ORDER_OWNER", "STATE_WRITER")


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


def normalized_modules(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = registry.get("modules")
    if not isinstance(rows, list):
        raise ValueError("MODULES_LIST_REQUIRED")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("MODULE_OBJECT_REQUIRED")
        module_id = str(raw.get("module_id") or "").strip()
        if not module_id or module_id in seen:
            raise ValueError(f"INVALID_OR_DUPLICATE_MODULE_ID:{module_id}")
        seen.add(module_id)
        row = {
            "module_id": module_id,
            "module_type": str(raw.get("module_type") or "UNKNOWN"),
            "inputs": sorted(set(str(x) for x in raw.get("inputs", []))),
            "outputs": sorted(set(str(x) for x in raw.get("outputs", []))),
            "depends_on": sorted(set(str(x) for x in raw.get("depends_on", []))),
            "authorities": sorted(set(str(x) for x in raw.get("authorities", []))),
            "latency_ms": float(raw.get("latency_ms") or 0.0),
            "cost_bps": float(raw.get("cost_bps") or 0.0),
            "enabled": bool(raw.get("enabled", True)),
            "immutable_child": bool(raw.get("immutable_child", True)),
            "source_sha256": str(raw.get("source_sha256") or ""),
        }
        if any(a not in OWNER_AUTHORITIES and a != "ADVISORY_ONLY" for a in row["authorities"]):
            raise ValueError(f"UNKNOWN_AUTHORITY:{module_id}")
        result.append(row)
    return sorted(result, key=lambda x: x["module_id"])


def has_cycle(modules: list[dict[str, Any]]) -> bool:
    ids = {m["module_id"] for m in modules}
    graph = {m["module_id"]: [d for d in m["depends_on"] if d in ids] for m in modules}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for nxt in graph[node]:
            if visit(nxt):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def compatibility_errors(children: list[dict[str, Any]], contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    policy = contract.get("compatibility") if isinstance(contract.get("compatibility"), dict) else {}
    ids = [c["module_id"] for c in children]
    if len(ids) != len(set(ids)):
        errors.append("DUPLICATE_CHILD")
    if any(not c["immutable_child"] for c in children):
        errors.append("MUTABLE_CHILD_FORBIDDEN")
    for authority in OWNER_AUTHORITIES:
        owners = [c["module_id"] for c in children if authority in c["authorities"]]
        if len(owners) > 1:
            errors.append(f"MULTIPLE_{authority}")
    if policy.get("circular_dependency_forbidden") is True and has_cycle(children):
        errors.append("CIRCULAR_DEPENDENCY")
    total_latency = sum(c["latency_ms"] for c in children)
    total_cost = sum(c["cost_bps"] for c in children)
    if total_latency > float(policy.get("maximum_total_latency_ms") or 1500):
        errors.append("LATENCY_BUDGET_EXCEEDED")
    if total_cost > float(policy.get("maximum_total_cost_bps") or 35.0):
        errors.append("COST_BUDGET_EXCEEDED")
    produced: set[str] = set()
    for index, child in enumerate(children):
        missing = [
            x for x in child["inputs"]
            if x not in produced and x not in {"MARKET_CONTEXT", "POSITION_CONTEXT", "RISK_CONTEXT"}
        ]
        if missing and index > 0:
            errors.append(f"UNSATISFIED_INPUT:{child['module_id']}:{','.join(missing)}")
        produced.update(child["outputs"])
    return sorted(set(errors))


def candidate_payload(children: list[dict[str, Any]], composite_type: str) -> dict[str, Any]:
    payload = {
        "composite_type": composite_type,
        "child_module_ids": [c["module_id"] for c in children],
        "child_source_sha256": [c["source_sha256"] for c in children],
        "total_latency_ms": round(sum(c["latency_ms"] for c in children), 6),
        "total_cost_bps": round(sum(c["cost_bps"] for c in children), 6),
        "authorities": sorted({a for c in children for a in c["authorities"]}),
        "activation_enabled": False,
        "economic_claim_allowed": False,
        "exact_replay_required": True,
    }
    payload["composite_id"] = "CMP_" + canonical_sha(payload)[:20].upper()
    payload["composite_sha256"] = canonical_sha(payload)
    return payload


def build_receipt(registry: Mapping[str, Any], contract: Mapping[str, Any], checkpoint_ref: str) -> dict[str, Any]:
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
    modules = normalized_modules(registry)
    enabled = [m for m in modules if m["enabled"]]
    generation = contract.get("generation_policy") if isinstance(contract.get("generation_policy"), dict) else {}
    initial = int(generation.get("initial_child_count") or 2)
    maximum = int(generation.get("maximum_child_count") or 3)
    cap = int(generation.get("maximum_composites_per_run") or 30)
    types = [str(x) for x in generation.get("allowed_composite_types", [])]
    if initial < 2 or maximum > 3 or initial > maximum:
        errors.append("INVALID_CHILD_BOUNDS")
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for count in range(initial, maximum + 1):
        for combo in itertools.permutations(enabled, count):
            children = list(combo)
            combo_errors = compatibility_errors(children, contract)
            for composite_type in types:
                payload = candidate_payload(children, composite_type)
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
    candidates = sorted(unique.values(), key=lambda x: x["composite_id"])[:cap]
    if not checkpoint_ref:
        errors.append("PRE_FACTORY_CHECKPOINT_MISSING")
    passed = not errors
    receipt: dict[str, Any] = {
        "schema_version": "zel.composite_module_factory.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_COMPOSITE_FACTORY_STATIC_READY" if passed else "HOLD_COMPOSITE_FACTORY",
        "pre_factory_checkpoint_ref": checkpoint_ref,
        "factory_enabled": False,
        "activation_enabled": False,
        "module_count": len(modules),
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "candidates": candidates,
        "rejected": rejected[:100],
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
                "module_id": "TREND_SIGNAL", "module_type": "STRATEGY",
                "inputs": ["MARKET_CONTEXT"], "outputs": ["SIGNAL_CANDIDATE"],
                "depends_on": [], "authorities": ["ADVISORY_ONLY"],
                "latency_ms": 25, "cost_bps": 0, "enabled": True,
                "immutable_child": True, "source_sha256": "a" * 64,
            },
            {
                "module_id": "LICO_COST_GATE", "module_type": "COST_GATE",
                "inputs": ["SIGNAL_CANDIDATE"], "outputs": ["COST_FILTERED_SIGNAL"],
                "depends_on": ["TREND_SIGNAL"], "authorities": ["ADVISORY_ONLY"],
                "latency_ms": 10, "cost_bps": 4, "enabled": True,
                "immutable_child": True, "source_sha256": "b" * 64,
            },
            {
                "module_id": "RISK_GOVERNOR", "module_type": "RISK",
                "inputs": ["COST_FILTERED_SIGNAL", "RISK_CONTEXT"], "outputs": ["RISK_DECISION"],
                "depends_on": ["LICO_COST_GATE"], "authorities": ["RISK_OWNER"],
                "latency_ms": 15, "cost_bps": 0, "enabled": True,
                "immutable_child": True, "source_sha256": "c" * 64,
            },
        ]
    }
    contract = {
        "schema_version": "zel.composite_module_factory.contract.v1",
        "factory_enabled": False,
        "generation_policy": {
            "initial_child_count": 2, "maximum_child_count": 3,
            "maximum_composites_per_run": 30,
            "allowed_composite_types": ["SEQUENTIAL_COMPOSITE"],
        },
        "compatibility": {
            "circular_dependency_forbidden": True,
            "maximum_total_latency_ms": 1500,
            "maximum_total_cost_bps": 35,
        },
        "safety": {"execution_authority": "NONE", "order_authority": "BLOCKED"},
    }
    return registry, contract


def self_test() -> None:
    registry, contract = fixture()
    receipt = build_receipt(registry, contract, "pre-composite-factory-v1-fixture")
    assert receipt["state"] == "PASS_COMPOSITE_FACTORY_STATIC_READY", receipt
    assert receipt["factory_enabled"] is False
    assert receipt["candidate_count"] >= 1
    assert all(c["activation_enabled"] is False for c in receipt["candidates"])
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
    receipt = build_receipt(load_object(args.registry), load_object(args.contract), args.checkpoint_ref)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "candidate_count": receipt["candidate_count"],
        "errors": receipt["errors"],
    }, sort_keys=True))
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
