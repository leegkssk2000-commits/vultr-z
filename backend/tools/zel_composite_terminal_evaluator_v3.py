from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import zel_composite_terminal_evaluator_v1 as v1
import zel_composite_terminal_evaluator_v2 as v2

VERSION = "ZEL_COMPOSITE_TERMINAL_EVALUATOR_V3"
STAGE_IDS = ("W1_ABLATION", "W2_FORWARD", "W3_DURABILITY")


def load_receipt(path: Path, schema: str) -> dict[str, Any]:
    row = v1.load_json(path)
    if row.get("schema_version") != schema:
        raise RuntimeError(f"RECEIPT_SCHEMA_INVALID:{path}:{row.get('schema_version')}")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"RECEIPT_AUTHORITY_UNSAFE:{path}")
    if row.get("active_data_b_1m_mutated") is not False:
        raise RuntimeError(f"RECEIPT_DATA_B_MUTATION_UNSAFE:{path}")
    if row.get("runtime_registry_mutated") is not False:
        raise RuntimeError(f"RECEIPT_REGISTRY_MUTATION_UNSAFE:{path}")
    return row


def add_blocker(row: dict[str, Any], blocker: str) -> None:
    blockers = row.get("blockers") if isinstance(row.get("blockers"), list) else []
    blockers = sorted(set(str(value) for value in blockers) | {blocker})
    row["blockers"] = blockers
    row["state"] = "HOLD_COMPOSITE_COUNTERFACTUAL_NOT_EXECUTABLE"
    row["economic_superiority_claim_allowed"] = False
    row["selection_authority"] = False
    row["promotion_authority"] = False
    row["action"] = "hold"


def readiness_summary(
    skill: Mapping[str, Any],
    lico: Mapping[str, Any],
    method: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "skill": {
            "state": skill.get("state"),
            "skill_count": skill.get("skill_count"),
            "exact_replay_skill_count": skill.get("exact_replay_skill_count"),
            "parity_only_skill_count": skill.get("parity_only_skill_count"),
            "blocked_skill_count": skill.get("blocked_skill_count"),
            "receipt_sha256": skill.get("receipt_sha256"),
        },
        "lico": {
            "state": lico.get("state"),
            "trade_count": lico.get("trade_count"),
            "ready_trade_count": lico.get("ready_trade_count"),
            "blocked_trade_count": lico.get("blocked_trade_count"),
            "receipt_sha256": lico.get("receipt_sha256"),
        },
        "trade_method": {
            "state": method.get("state"),
            "trade_count": method.get("trade_count"),
            "pass_trade_count": method.get("pass_trade_count"),
            "blocked_trade_count": method.get("blocked_trade_count"),
            "r_delta_sum": method.get("r_delta_sum"),
            "receipt_sha256": method.get("receipt_sha256"),
        },
    }


def annotate(
    result: dict[str, Any],
    skill: Mapping[str, Any],
    lico: Mapping[str, Any],
    method: Mapping[str, Any],
) -> dict[str, Any]:
    skill_exact = int(skill.get("exact_replay_skill_count") or 0)
    lico_total = int(lico.get("trade_count") or 0)
    lico_ready = int(lico.get("ready_trade_count") or 0)
    method_total = int(method.get("trade_count") or 0)
    method_pass = int(method.get("pass_trade_count") or 0)
    blocker_counts: Counter[str] = Counter()

    stages = result.get("stages") if isinstance(result.get("stages"), dict) else {}
    for stage_id in STAGE_IDS:
        stage = stages.get(stage_id)
        if not isinstance(stage, dict):
            continue
        candidates = stage.get("candidate_results") if isinstance(stage.get("candidate_results"), list) else []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            children = set(str(value) for value in candidate.get("child_module_ids", []))
            if "SKILL_PROFILE" in children and skill_exact <= 0:
                add_blocker(candidate, "SKILL_COUNTERFACTUAL_EXACT_REPLAY_UNAVAILABLE")
            if "LICO" in children and (lico_total <= 0 or lico_ready < lico_total):
                add_blocker(candidate, "LICO_HISTORICAL_MIN_DATA_COVERAGE_INCOMPLETE")
            if "TRADE_METHOD" in children and (method_total <= 0 or method_pass < method_total):
                add_blocker(candidate, "TRADE_METHOD_HISTORICAL_COVERAGE_INCOMPLETE")
            for blocker in candidate.get("blockers") or []:
                blocker_counts[str(blocker)] += 1
        parity = sum(1 for row in candidates if isinstance(row, dict) and row.get("state") == "PASS_ZERO_DELTA_CONTEXT_PARITY")
        blocked = sum(1 for row in candidates if isinstance(row, dict) and str(row.get("state") or "").startswith("HOLD_"))
        stage["parity_control_count"] = parity
        stage["blocked_candidate_count"] = blocked
        stage["economic_survivor_count"] = 0
        stage["parallel_adapter_readiness_bound"] = True
        stage["receipt_sha256"] = v1.stable_sha({key: value for key, value in stage.items() if key != "receipt_sha256"})

    result["schema_version"] = "zel.composite.post_terminal_sequence.receipt.v3"
    result["version"] = VERSION
    result["parallel_adapter_readiness"] = readiness_summary(skill, lico, method)
    result["parallel_adapter_blocker_counts"] = dict(sorted(blocker_counts.items()))
    result["parallel_adapter_readiness_bound"] = True
    result["economic_survivor_count"] = 0
    result["incumbent_retained"] = True
    result["economic_superiority_claim_allowed"] = False
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["action"] = "hold"
    result["sequence_id"] = v1.stable_sha(
        {
            "prior_sequence_id": result.get("sequence_id"),
            "skill_receipt": skill.get("receipt_sha256"),
            "lico_receipt": lico.get("receipt_sha256"),
            "trade_method_receipt": method.get("receipt_sha256"),
        }
    )
    result["receipt_sha256"] = v1.stable_sha({key: value for key, value in result.items() if key != "receipt_sha256"})
    return result


def evaluate(
    terminal_root: Path,
    plan_path: Path,
    contract_path: Path,
    source_root: Path,
    method_behavior_path: Path,
    skill_adapter_path: Path,
    lico_mapper_path: Path,
    trade_method_adapter_path: Path,
) -> dict[str, Any]:
    skill = load_receipt(skill_adapter_path, "zel.skill_counterfactual.adapter.receipt.v1")
    lico = load_receipt(lico_mapper_path, "zel.lico.historical_min_data_mapper.receipt.v1")
    method = load_receipt(trade_method_adapter_path, "zel.trade_method.historical_adapter.receipt.v1")
    result = v2.evaluate(
        terminal_root,
        plan_path,
        contract_path,
        source_root,
        method_behavior_path,
    )
    return annotate(result, skill, lico, method)


def self_test() -> None:
    base = {
        "schema_version": "old",
        "version": "old",
        "sequence_id": "old-sequence",
        "stages": {
            stage_id: {
                "candidate_results": [
                    {"child_module_ids": ["STRATEGY_SIGNAL", "SKILL_PROFILE"], "state": "HOLD_COMPOSITE_COUNTERFACTUAL_NOT_EXECUTABLE", "blockers": []},
                    {"child_module_ids": ["STRATEGY_SIGNAL", "LBOT"], "state": "PASS_ZERO_DELTA_CONTEXT_PARITY", "blockers": []},
                ]
            }
            for stage_id in STAGE_IDS
        },
    }
    skill = {"exact_replay_skill_count": 0, "receipt_sha256": "s", "state": "HOLD", "skill_count": 1, "parity_only_skill_count": 0, "blocked_skill_count": 1}
    lico = {"trade_count": 2, "ready_trade_count": 0, "blocked_trade_count": 2, "receipt_sha256": "l", "state": "HOLD"}
    method = {"trade_count": 2, "pass_trade_count": 0, "blocked_trade_count": 2, "receipt_sha256": "m", "state": "HOLD", "r_delta_sum": 0.0}
    row = annotate(base, skill, lico, method)
    assert row["version"] == VERSION, row
    assert row["stages"]["W1_ABLATION"]["parity_control_count"] == 1, row
    blockers = row["stages"]["W1_ABLATION"]["candidate_results"][0]["blockers"]
    assert "SKILL_COUNTERFACTUAL_EXACT_REPLAY_UNAVAILABLE" in blockers, blockers
    assert row["economic_survivor_count"] == 0, row
    assert row["execution_authority"] == "NONE" and row["order_authority"] == "BLOCKED", row
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--method-behavior", type=Path)
    parser.add_argument("--skill-adapter", type=Path)
    parser.add_argument("--lico-mapper", type=Path)
    parser.add_argument("--trade-method-adapter", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (
        args.terminal_root, args.plan, args.contract, args.source_root, args.method_behavior,
        args.skill_adapter, args.lico_mapper, args.trade_method_adapter, args.out_dir,
    )
    if any(value is None for value in required):
        parser.error("all terminal, plan, contract, source, behavior and adapter paths are required")
    result = evaluate(
        args.terminal_root.resolve(),
        args.plan.resolve(),
        args.contract.resolve(),
        args.source_root.resolve(),
        args.method_behavior.resolve(),
        args.skill_adapter.resolve(),
        args.lico_mapper.resolve(),
        args.trade_method_adapter.resolve(),
    )
    v1.write_outputs(args.out_dir.resolve(), result)
    print(json.dumps({
        "state": result["state"],
        "version": result["version"],
        "sequence_id": result["sequence_id"],
        "trades": result["closed_trade_count"],
        "economic_survivors": result["economic_survivor_count"],
        "adapter_blockers": result["parallel_adapter_blocker_counts"],
        "incumbent_retained": result["incumbent_retained"],
    }, sort_keys=True))
    return 0 if result["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
