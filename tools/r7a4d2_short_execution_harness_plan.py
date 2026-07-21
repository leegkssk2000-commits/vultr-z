#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any


PRIOR_PROOF = Path(
    "runtime/r7a4d2_entry_chain_minimal_patch_verify/entry_chain_patch_proof_v1.json"
)
SEMANTIC_PROOF = Path(
    "runtime/r7a4d_semantic_parity_audit/semantic_parity_audit_v1.json"
)
OUTPUT_PATH = Path(
    "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json"
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def validate_entry_chain_proof(proof: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    exact = {
        "state": "PASS_ENTRY_CHAIN_MINIMAL_PATCH",
        "blocker_count": 0,
        "targeted_scenario_count": 120,
        "completed_scenario_count": 120,
        "failed_scenario_count": 0,
        "orphan_add_block_count": 0,
        "evaluation_bar_invalid_count": 0,
        "source_registry_parity": True,
    }
    for key, expected in exact.items():
        if proof.get(key) != expected:
            errors.append(f"ENTRY_CHAIN_PROOF_INVALID:{key}:{proof.get(key)}:{expected}")
    if int((proof.get("strategy_trade_counts") or {}).get("vwap_revert", 0)) <= 0:
        errors.append("VWAP_REVERT_TRADE_NOT_POSITIVE")
    if proof.get("side_effect_attempts") not in ([], None):
        errors.append("ENTRY_CHAIN_SIDE_EFFECT_PRESENT")
    if proof.get("mutation_paths") not in ([], None):
        errors.append("ENTRY_CHAIN_MUTATION_PRESENT")
    return errors


def short_targets(semantic: dict[str, Any]) -> tuple[list[str], int, list[str]]:
    errors: list[str] = []
    reports = [row for row in semantic.get("strategy_reports", []) if isinstance(row, dict)]
    targets = sorted(
        str(row.get("strategy_id") or "")
        for row in reports
        if int(row.get("short_downgrade_count") or 0) > 0 and row.get("strategy_id")
    )
    downgrade_count = sum(int(row.get("short_downgrade_count") or 0) for row in reports)
    if int(semantic.get("strategy_count") or 0) != 25:
        errors.append("SEMANTIC_STRATEGY_COUNT_INVALID")
    if int(semantic.get("adapter_error_count") or 0) != 0:
        errors.append("SEMANTIC_ADAPTER_ERROR_PRESENT")
    if int(semantic.get("direct_payload_mismatch_count") or 0) != 0:
        errors.append("SEMANTIC_DIRECT_PAYLOAD_MISMATCH_PRESENT")
    if int(semantic.get("long_mapping_mismatch_count") or 0) != 0:
        errors.append("SEMANTIC_LONG_MAPPING_MISMATCH_PRESENT")
    if len(targets) != int(semantic.get("short_scope_gap_strategy_count") or -1):
        errors.append("SHORT_TARGET_COUNT_MISMATCH")
    if not targets or downgrade_count <= 0:
        errors.append("SHORT_SCOPE_EVIDENCE_EMPTY")
    return targets, downgrade_count, errors


def validate_runner_source(source: str) -> list[str]:
    required = (
        "short_shadow_signal_count",
        'if kind in {"enter", "add"}:',
        'if intent == "enter_long":',
        'elif intent == "reduce"',
        'elif intent == "exit_long"',
        'stop_hit = low_price <= float(position["stop"])',
        'tp_hit = high_price >= float(position["tp"])',
    )
    return [f"RUNNER_MARKER_MISSING:{marker}" for marker in required if marker not in source]


def build_plan(targets: list[str], downgrade_count: int) -> dict[str, Any]:
    return {
        "schema": "r7a4d2_short_execution_harness_plan_v1",
        "official_stage": "R7.A4D2_SHORT_EXECUTION_HARNESS_PLAN",
        "state": "PASS_SHORT_EXECUTION_HARNESS_PLAN",
        "short_target_strategy_count": len(targets),
        "short_target_strategy_ids": targets,
        "observed_short_downgrade_count": downgrade_count,
        "mutation_scope": {
            "temporary_historical_runner_only": True,
            "production_adapter_mutation_allowed": False,
            "strategy_source_mutation_allowed": False,
            "registry_mutation_allowed": False,
            "config_mutation_allowed": False,
            "router_mutation_allowed": False,
            "service_mutation_allowed": False,
            "shadow_start_allowed": False,
            "paper_live_order_allowed": False,
        },
        "signal_interpretation": {
            "long": "retain current canonical intent path unchanged",
            "short": (
                "when decision ok is true, canonical intent is hold because the adapter is long-only, "
                "and legacy_signal side is short with action enter/add/reduce/exit/close, "
                "the simulation-only interpreter may execute that legacy action"
            ),
            "fail_closed": [
                "reject short action when decision ok is false",
                "reject short action when canonical intent is block",
                "reject unknown side or action",
                "forbid hedge, flip, and simultaneous long/short positions",
            ],
        },
        "short_state_machine": {
            "position_side": "short",
            "entry_fill": "open_price * (1 - slippage_rate)",
            "exit_fill": "open_price * (1 + slippage_rate)",
            "entry_geometry": "tp < fill < stop and quantity > 0",
            "gross_pnl": "quantity * (average_entry / exit_fill - 1)",
            "risk_capital_pct": "quantity * (stop - fill) / fill * 100",
            "stop_hit": "bar_high >= stop",
            "take_profit_hit": "bar_low <= tp",
            "collision_policy": "STOP_FIRST_CONSERVATIVE",
            "stop_exit_price": "max(open_price, stop)",
            "take_profit_exit_price": "min(open_price, tp)",
            "mfe_pct": "average_entry / bar_low - 1",
            "mae_pct": "average_entry / bar_high - 1",
            "funding": "apply configured non-negative stress funding as a cost on both sides",
            "add": "same-side only and same-strategy executed-entry lineage required",
            "reduce_exit": "buy back requested quantity or full remaining quantity",
            "full_close": "clear side, quantity, stop, tp, add_count, and entry lineage",
        },
        "preserved_contracts": {
            "indicator_preroll_bars": 320,
            "evaluation_bars": 320,
            "signal_at_bar_close": True,
            "fill_before_next_bar_allowed": False,
            "entry_threshold_relaxation_allowed": False,
            "long_result_regression_allowed": False,
        },
        "targeted_verification": {
            "scenario_count": 600,
            "formula": "25 strategies x 24 segments x baseline cost x canonical timing",
            "required": [
                "completed_scenario_count equals 600",
                "failed_scenario_count equals 0",
                "short_enter_signal_count greater than 0",
                "short_closed_trade_count greater than 0",
                "short_invalid_geometry_count equals 0",
                "short_orphan_add_block_count equals 0",
                "long_regression_mismatch_count equals 0",
                "evaluation_bar_invalid_count equals 0",
                "source_registry_parity is true",
                "side_effect_attempt_count equals 0",
                "mutation_path_count equals 0",
            ],
        },
        "sequence_after_patch": [
            "run 600-scenario dual-side targeted verification",
            "diagnose eight no-trigger strategies against broader market coverage",
            "freeze the corrected runner and contract",
            "rerun the full 3600 matrix in a new result directory",
            "advance to 2880 event replay only after active-only performance gates pass",
        ],
        "next_stage": "R7.A4D2_SHORT_EXECUTION_HARNESS_MINIMAL_PATCH",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--source-root", default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    source_root = Path(args.source_root).resolve() if args.source_root else root

    errors: list[str] = []
    try:
        entry_proof = load_json(root / PRIOR_PROOF)
        semantic = load_json(root / SEMANTIC_PROOF)
        errors.extend(validate_entry_chain_proof(entry_proof))
        targets, downgrade_count, semantic_errors = short_targets(semantic)
        errors.extend(semantic_errors)
        runner_source = (source_root / "tools/r7a4d_historical_simulation_3600.py").read_text(
            encoding="utf-8"
        )
        errors.extend(validate_runner_source(runner_source))
    except Exception as exc:
        targets = []
        downgrade_count = 0
        errors.append(f"PLAN_INPUT_FAILED:{type(exc).__name__}:{exc}")

    if errors:
        print("STATE=HOLD_SHORT_EXECUTION_HARNESS_PLAN")
        print("BLOCKER_COUNT=" + str(len(errors)))
        print("BLOCKERS=" + json.dumps(errors, ensure_ascii=False))
        print("NEXT_STAGE=R7.A4D2_SHORT_EXECUTION_HARNESS_PLAN")
        print("RC=2")
        return 2

    plan = build_plan(targets, downgrade_count)
    output = root / OUTPUT_PATH
    atomic_json(output, plan)
    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=0")
    print("SHORT_TARGET_STRATEGY_COUNT=" + str(len(targets)))
    print("SHORT_TARGET_STRATEGY_IDS=" + json.dumps(targets, ensure_ascii=False))
    print("OBSERVED_SHORT_DOWNGRADE_COUNT=" + str(downgrade_count))
    print("TARGETED_VERIFICATION_SCENARIO_COUNT=600")
    print("PRODUCTION_ADAPTER_MUTATION_ALLOWED=false")
    print("FULL_3600_REEXECUTION_ALLOWED=false")
    print("EVENT_REPLAY_2880_ALLOWED=false")
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
