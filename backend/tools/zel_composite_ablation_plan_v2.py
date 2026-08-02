from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import zel_composite_ablation_plan_v1 as v1

VERSION = "ZEL_COMPOSITE_ABLATION_PLAN_V2"
MODULE_SPECS = (
    ("STRATEGY_SIGNAL", "EXECUTABLE_REPLAY", True, "STRATEGY", ()),
    ("TRADE_METHOD", "EXECUTABLE_REPLAY", True, "METHOD", ("STRATEGY_SIGNAL",)),
    ("SKILL_PROFILE", "EXECUTABLE_REPLAY", True, "SKILL", ("STRATEGY_SIGNAL",)),
    ("LBOT", "STATIC_ROLE_CONTEXT", True, "TEAM_BOT", ()),
    ("MBOT", "STATIC_ROLE_CONTEXT", True, "TEAM_BOT", ()),
    ("OBOT", "STATIC_ROLE_CONTEXT", True, "TEAM_BOT", ()),
    ("SBOT", "STATIC_ROLE_CONTEXT", True, "TEAM_BOT", ()),
    ("ZBOT", "ADVISORY_PROJECTION", True, "ADVISOR", ()),
    ("LICO", "EXECUTABLE_REPLAY", True, "EXECUTION_COST_CRITIC", ("STRATEGY_SIGNAL",)),
    ("ZICO", "RUNTIME_OBSERVER_ONLY", False, "CONTROL_ADVISOR", ()),
    ("ZLICE", "LINEAGE_AUDITOR", True, "LINEAGE", ()),
    ("PORTFOLIO_GOVERNOR", "POST_SCORE_RISK_GOVERNOR", False, "RISK", ()),
)


def build(factory: dict[str, Any], contract: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    result = v1.build(factory, contract, registry)
    result["version"] = VERSION
    result["schema_version"] = "zel.composite.ablation_order_plan.receipt.v2"
    result["receipt_sha256"] = v1.stable_sha(result)
    return result


def fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    adapters = []
    registry_modules = []
    for module_id, mode, w2, module_type, dependencies in MODULE_SPECS:
        adapters.append(
            {
                "module_id": module_id,
                "node_mode": mode,
                "w2_eligible": w2,
                "w3_eligible": w2,
                "direct_alpha_claim_allowed": module_id
                in {"STRATEGY_SIGNAL", "TRADE_METHOD", "SKILL_PROFILE"},
            }
        )
        registry_modules.append(
            {
                "module_id": module_id,
                "depends_on": list(dependencies),
                "module_type": module_type,
            }
        )
    contract = {
        "schema_version": "zel.composite.adapter_contract.v1",
        "adapters": adapters,
    }
    registry = {"modules": registry_modules}
    factory = {
        "state": "PASS_COMPOSITE_FACTORY_V3_BALANCED_STATIC_READY",
        "candidate_count": 3,
        "receipt_sha256": "f" * 64,
        "candidates": [
            {
                "composite_id": "C1",
                "composite_sha256": "1" * 64,
                "composite_type": "SEQUENTIAL_COMPOSITE",
                "child_module_ids": ["STRATEGY_SIGNAL", "TRADE_METHOD"],
            },
            {
                "composite_id": "C2",
                "composite_sha256": "2" * 64,
                "composite_type": "CONTEXT_ROUTER",
                "child_module_ids": ["LBOT", "STRATEGY_SIGNAL"],
            },
            {
                "composite_id": "C3",
                "composite_sha256": "3" * 64,
                "composite_type": "ADVISORY_COUNCIL",
                "child_module_ids": ["ZICO", "STRATEGY_SIGNAL"],
            },
        ],
    }
    return factory, contract, registry


def self_test() -> None:
    factory, contract, registry = fixture()
    row = build(factory, contract, registry)
    assert row["state"] == "PASS_COMPOSITE_ABLATION_ORDER_PLAN", row
    assert row["candidate_count"] == 3, row
    assert row["w2_eligible_candidate_count"] == 2, row
    assert row["w3_eligible_candidate_count"] == 2, row
    assert row["candidate_class_counts"] == {
        "STRUCTURAL_ONLY_RUNTIME_OBSERVER": 1,
        "W2_CONTEXT_PARITY_ONLY": 1,
        "W2_ECONOMIC_REPLAY_ELIGIBLE": 1,
    }, row
    assert row["leave_one_out_variant_count"] == 6, row
    assert row["valid_order_permutation_count"] == 1, row
    assert row["rejected_order_permutation_count"] == 1, row
    assert row["terminal_required_before_execution"] is True, row
    assert row["terminal_pass_observed"] is False, row
    assert row["exact_replay_started"] is False, row
    assert row["execution_authority"] == "NONE", row
    assert row["order_authority"] == "BLOCKED", row
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
    print(
        json.dumps(
            {
                "state": row["state"],
                "candidates": row["candidate_count"],
                "classes": row["candidate_class_counts"],
                "w2_eligible": row["w2_eligible_candidate_count"],
                "loo": row["leave_one_out_variant_count"],
                "valid_orders": row["valid_order_permutation_count"],
                "errors": row["errors"],
            },
            sort_keys=True,
        )
    )
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
