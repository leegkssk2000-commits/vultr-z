from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import zel_composite_terminal_evaluator_v1 as ev1
import zel_composite_terminal_evaluator_v3 as ev3

VERSION = "ZEL_COMPOSITE_TERMINAL_V3_ACCEPTANCE_HARNESS_V1"
WINDOWS = ("1m_w1", "1m_w2", "1m_w3")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def strategy_ids() -> list[str]:
    return [f"fixture_strategy_{index:02d}" for index in range(1, 26)]


def build_trades(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_index, strategy_id in enumerate(strategy_ids(), start=1):
        for window_index, window_id in enumerate(WINDOWS, start=1):
            day = strategy_index
            hour = window_index
            realized = 1.0 if (strategy_index + window_index) % 3 else -0.5
            rows.append(
                {
                    "event_id": f"{strategy_id}.{window_id}",
                    "strategy_id": strategy_id,
                    "strategy": strategy_id,
                    "symbol": "BTCUSDT" if strategy_index % 2 else "ETHUSDT",
                    "side": "long" if strategy_index % 4 else "short",
                    "entry_ts": f"2026-01-{day:02d}T0{hour}:00:00Z",
                    "exit_ts": f"2026-01-{day:02d}T0{hour}:30:00Z",
                    "entry_price": 100.0 + strategy_index,
                    "exit_price": 100.0 + strategy_index + realized,
                    "realized_R": realized,
                    "realized_R_including_funding_estimate": realized - 0.01,
                    "MFE_R": max(realized, 0.25) + 0.2,
                    "MAE_R": min(realized, -0.1) - 0.1,
                    "time_exposure_min": 30.0,
                    "regime": "trend" if strategy_index % 2 else "range",
                    "window_id": window_id,
                    "data_interval": "1m",
                    "initial_risk_usdt": 10.0,
                    "fee": 0.02,
                    "slippage": 0.01,
                    "funding_pnl_estimate_usdt": -0.01,
                }
            )
    trades_path = root / "trades.jsonl.gz"
    with gzip.open(trades_path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return rows


def build_terminal(root: Path) -> list[dict[str, Any]]:
    rows = build_trades(root)
    report = {
        "schema_version": "zel.historical_oos_exact25_replay.report.v2",
        "version": "ZEL_HISTORICAL_OOS_EXACT25_REPLAY_V2",
        "state": "PASS",
        "interval": "1m",
        "replay": {
            "strategy_count_completed": 25,
            "strategy_failure_count": 0,
            "closed_trade_count": len(rows),
            "strategy_call_count": 25,
            "error_count": 0,
        },
        "canonical_runtime": {
            "producer_pid_unchanged": True,
            "writer_pid_unchanged": True,
            "formal_ledger": {"prefix_unchanged": True},
        },
        "source": {"strategy_tree_unchanged": True},
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    terminal = {
        "schema_version": "zel.historical_oos_exact25_replay.terminal.v2",
        "state": "PASS",
        "runtime_safe": True,
        "strategy_count_completed": 25,
        "strategy_failure_count": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    progress = {
        "state": "PASS",
        "completed_units": 25,
        "total_units": 25,
        "error_count": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    write_json(root / "report.json", report)
    write_json(root / "terminal_receipt.json", terminal)
    write_json(root / "progress.json", progress)
    write_json(root / "summary.json", {"state": "PASS", "closed_trade_count": len(rows)})
    (root / "scoreboard.csv").write_text("strategy_id,window_id,net_R\n", encoding="utf-8")
    manifest = {
        "schema_version": "zel.historical_oos_exact25_replay.artifact_manifest.v2",
        "terminal_complete": True,
        "atomic_publication": True,
        "artifacts": [
            {"path": "report.json", "sha256": sha256_path(root / "report.json")},
            {"path": "trades.jsonl.gz", "sha256": sha256_path(root / "trades.jsonl.gz")},
        ],
    }
    write_json(root / "artifact_manifest.json", manifest)
    return rows


def build_plan(path: Path) -> dict[str, Any]:
    plans: list[dict[str, Any]] = []
    for index in range(1, 31):
        children = ["STRATEGY_SIGNAL", "LBOT"] if index <= 6 else ["STRATEGY_SIGNAL", "SKILL_PROFILE"]
        candidate_class = "W2_CONTEXT_PARITY_ONLY" if index <= 6 else "W2_ECONOMIC_REPLAY_ELIGIBLE"
        classification = {
            "candidate_class": candidate_class,
            "w2_eligible": True,
            "w3_eligible": True,
            "has_base_signal": True,
            "node_modes": {},
            "economic_transform_nodes": ["SKILL_PROFILE"] if index > 6 else [],
            "parity_only_nodes": ["LBOT"] if index <= 6 else [],
            "structural_only_nodes": [],
            "post_score_nodes": [],
            "direct_alpha_claim_nodes": ["STRATEGY_SIGNAL"],
            "direct_alpha_claim_forbidden_nodes": [children[-1]],
            "w2_blockers": [],
        }
        plan = {
            "composite_id": f"FIXTURE_C{index:02d}",
            "composite_sha256": stable_sha({"index": index, "children": children}),
            "composite_type": "CONTEXT_ROUTER" if index <= 6 else "SEQUENTIAL_COMPOSITE",
            "child_module_ids": children,
            "child_count": len(children),
            "classification": classification,
            "leave_one_out_variants": [],
            "valid_order_permutations": [],
            "rejected_order_permutations": [],
            "valid_order_permutation_count": 0,
            "rejected_order_permutation_count": 0,
            "exact_replay_started": False,
            "w2_started": False,
            "w3_started": False,
            "selection_authority": False,
            "promotion_authority": False,
        }
        plan["plan_sha256"] = stable_sha(plan)
        plans.append(plan)
    result = {
        "schema_version": "zel.composite.ablation_order_plan.receipt.v2",
        "version": "ZEL_COMPOSITE_ABLATION_PLAN_V2",
        "state": "PASS_COMPOSITE_ABLATION_ORDER_PLAN",
        "candidate_count": 30,
        "plans": plans,
        "terminal_required_before_execution": True,
        "terminal_pass_observed": False,
        "economic_claim_allowed": False,
        "exact_replay_started": False,
        "w2_started": False,
        "w3_started": False,
        "portfolio_joint_risk_started": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    write_json(path, result)
    return result


def build_method_behavior(path: Path) -> dict[str, Any]:
    rows = [
        {
            "strategy_id": strategy_id,
            "decision": "WATCH_COMBO",
            "action": "hold",
            "registry_enabled": False,
            "size_multiplier": 0.0,
            "target_r": "policy",
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "paper_execution_allowed": False,
            "live_execution_allowed": False,
        }
        for strategy_id in strategy_ids()
    ]
    result = {
        "schema_version": "zel.trade_method.runtime_behavior.receipt.v1",
        "version": "ZEL_TRADE_METHOD_RUNTIME_BEHAVIOR_V1",
        "state": "PASS_TRADE_METHOD_DISABLED_HOLD_BEHAVIOR",
        "strategy_count": 25,
        "enabled_strategy_count": 0,
        "unsafe_strategy_count": 0,
        "distinct_behavior_count": 25,
        "rows": rows,
        "errors": [],
        "credentials_read": False,
        "network_requested": False,
        "writes_requested": False,
        "active_data_b_1m_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    write_json(path, result)
    return result


def base_adapter_receipt(schema: str, version: str, state: str) -> dict[str, Any]:
    return {
        "schema_version": schema,
        "version": version,
        "state": state,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def build_adapter_receipts(root: Path, trade_count: int) -> tuple[Path, Path, Path]:
    skill = base_adapter_receipt(
        "zel.skill_counterfactual.adapter.receipt.v1",
        "ZEL_SKILL_COUNTERFACTUAL_ADAPTER_V1",
        "HOLD_SKILL_COUNTERFACTUAL_PARTIAL_OR_BLOCKED",
    )
    skill.update({
        "skill_count": 1,
        "exact_replay_skill_count": 0,
        "parity_only_skill_count": 0,
        "blocked_skill_count": 1,
        "exact_replay_skill_ids": [],
        "parity_only_skill_ids": [],
        "blocked_skill_ids": ["SK_POS_TRAILING_STOP"],
        "skills": [],
    })
    lico = base_adapter_receipt(
        "zel.lico.historical_min_data_mapper.receipt.v1",
        "ZEL_LICO_HISTORICAL_MIN_DATA_MAPPER_V1",
        "HOLD_LICO_HISTORICAL_MIN_DATA_DATASET",
    )
    lico.update({
        "trade_count": trade_count,
        "ready_trade_count": 0,
        "blocked_trade_count": trade_count,
        "missing_counts": {"pos_pct": trade_count},
        "source_gap_counts": {"pos_pct": trade_count},
        "rows": [],
    })
    method = base_adapter_receipt(
        "zel.trade_method.historical_adapter.receipt.v1",
        "ZEL_TRADE_METHOD_HISTORICAL_ADAPTER_V1_1",
        "HOLD_TRADE_METHOD_HISTORICAL_ADAPTER",
    )
    method.update({
        "trade_count": trade_count,
        "pass_trade_count": 0,
        "blocked_trade_count": trade_count,
        "state_counts": {"HOLD_TRADE_METHOD_HISTORICAL_COUNTERFACTUAL": trade_count},
        "blocker_counts": {"registry_disabled_and_zero_size": trade_count},
        "rows": [],
        "r_delta_sum": 0.0,
    })
    for value in (skill, lico, method):
        value["receipt_sha256"] = stable_sha(value)
    skill_path = root / "skill_adapter.json"
    lico_path = root / "lico_mapper.json"
    method_path = root / "trade_method_adapter.json"
    write_json(skill_path, skill)
    write_json(lico_path, lico)
    write_json(method_path, method)
    return skill_path, lico_path, method_path


def run_harness(source_root: Path, out_dir: Path) -> dict[str, Any]:
    work = out_dir / "fixture"
    terminal_root = work / "terminal"
    terminal_root.mkdir(parents=True, exist_ok=True)
    rows = build_terminal(terminal_root)
    plan_path = work / "ablation_plan.json"
    build_plan(plan_path)
    behavior_path = work / "method_behavior.json"
    build_method_behavior(behavior_path)
    skill_path, lico_path, method_path = build_adapter_receipts(work, len(rows))
    evaluation_dir = out_dir / "evaluation"
    result = ev3.evaluate(
        terminal_root,
        plan_path,
        source_root / "backend/research/zel_composite_adapter_contract_v1.json",
        source_root,
        behavior_path,
        skill_path,
        lico_path,
        method_path,
    )
    ev1.write_outputs(evaluation_dir, result)
    assert result["state"] == "PASS_COMPOSITE_POST_TERMINAL_SEQUENCE_COMPLETE_RETAIN_INCUMBENT", result
    assert result["version"] == "ZEL_COMPOSITE_TERMINAL_EVALUATOR_V3", result
    assert result["strategy_count_completed"] == 25, result
    assert result["closed_trade_count"] == 75, result
    assert result["window_trade_counts"] == {"1m_w1": 25, "1m_w2": 25, "1m_w3": 25}, result
    assert result["economic_survivor_count"] == 0, result
    assert result["incumbent_retained"] is True, result
    assert result["parallel_adapter_readiness_bound"] is True, result
    assert result["execution_authority"] == "NONE" and result["order_authority"] == "BLOCKED", result
    summary = {
        "schema_version": "zel.composite.terminal_v3_acceptance_harness.receipt.v1",
        "version": VERSION,
        "state": "PASS_COMPOSITE_TERMINAL_V3_ACCEPTANCE_HARNESS",
        "strategy_count": 25,
        "window_count": 3,
        "closed_trade_count": 75,
        "candidate_count": 30,
        "w1_state": result["stages"]["W1_ABLATION"]["state"],
        "w2_state": result["stages"]["W2_FORWARD"]["state"],
        "w3_state": result["stages"]["W3_DURABILITY"]["state"],
        "joint_risk_state": result["stages"]["PORTFOLIO_JOINT_RISK"]["state"],
        "economic_survivor_count": 0,
        "incumbent_retained": True,
        "fixture_only": True,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    summary["receipt_sha256"] = stable_sha(summary)
    write_json(out_dir / "acceptance_receipt.json", summary)
    return summary


def self_test() -> None:
    source_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="zel-terminal-v3-harness.") as temp:
        summary = run_harness(source_root, Path(temp))
    assert summary["state"] == "PASS_COMPOSITE_TERMINAL_V3_ACCEPTANCE_HARNESS", summary
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.source_root or not args.out_dir:
        parser.error("source-root and out-dir are required")
    summary = run_harness(args.source_root.resolve(), args.out_dir.resolve())
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
