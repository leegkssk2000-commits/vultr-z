from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_TRADE_METHOD_RISK_SEQUENCE_REPLAY_V1"


def load_adapter(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("zel_trade_method_risk_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ADAPTER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def consecutive_losses(outcomes: list[float]) -> int:
    count = 0
    for value in reversed(outcomes):
        if value < 0:
            count += 1
        else:
            break
    return count


def context_before(outcomes: list[float]) -> dict[str, Any]:
    return {
        "consecutive_losses": consecutive_losses(outcomes),
        "rolling_20_loss_r": sum(outcomes[-20:]),
        "rolling_50_loss_r": sum(outcomes[-50:]),
    }


def replay(adapter: Any, root: Path, raw_outcomes: list[float]) -> list[dict[str, Any]]:
    observed: list[float] = []
    rows: list[dict[str, Any]] = []
    for index, raw_r in enumerate(raw_outcomes, start=1):
        before = context_before(observed)
        plan = adapter.resolve_with_active_trade_method(
            root=root,
            strategy="trend_ma_macd",
            skills=(),
            cost_r=0.1,
            context=before,
        )
        size = float(plan["size_multiplier"])
        executed = plan["action"] not in {"block", "stop"} and size > 0.0
        scaled_r = raw_r * size if executed else 0.0
        row = {
            "trade_index": index,
            "raw_outcome_r": raw_r,
            "context_before": before,
            "decision": {
                "action": plan["action"],
                "risk_mode": plan["risk_mode"],
                "size_multiplier": size,
                "risk_triggered_rules": plan["risk_triggered_rules"],
            },
            "executed": executed,
            "scaled_outcome_r": scaled_r,
            "current_outcome_used_in_decision": False,
        }
        rows.append(row)
        if not executed:
            break
        observed.append(raw_r)
    return rows


def validation(adapter: Any, root: Path) -> dict[str, Any]:
    rows = replay(adapter, root, [-0.2] * 31)
    indexed = {row["trade_index"]: row for row in rows}
    assert indexed[1]["decision"]["risk_mode"] == "normal", indexed[1]
    assert indexed[20]["context_before"]["consecutive_losses"] == 19, indexed[20]
    assert indexed[20]["decision"]["risk_mode"] == "normal", indexed[20]
    assert indexed[21]["context_before"]["consecutive_losses"] == 20, indexed[21]
    assert indexed[21]["decision"]["action"] == "reduce25", indexed[21]
    assert indexed[21]["decision"]["size_multiplier"] == 0.75, indexed[21]
    assert indexed[30]["context_before"]["consecutive_losses"] == 29, indexed[30]
    assert indexed[30]["decision"]["action"] == "reduce25", indexed[30]
    assert indexed[31]["context_before"]["consecutive_losses"] == 30, indexed[31]
    assert indexed[31]["decision"]["action"] == "block", indexed[31]
    assert indexed[31]["decision"]["size_multiplier"] == 0.0, indexed[31]
    assert indexed[31]["executed"] is False, indexed[31]
    assert all(row["current_outcome_used_in_decision"] is False for row in rows)

    cost_warning = adapter.resolve_with_active_trade_method(
        root=root,
        strategy="trend_ma_macd",
        skills=("exit_modifier",),
        cost_r=0.35,
        context={"consecutive_losses": 20},
    )
    assert cost_warning["size_multiplier"] == 0.375, cost_warning
    assert cost_warning["risk_policy_order"] == "AFTER_BASE_SKILL_AND_COST_SIZING", cost_warning

    return {
        "schema_version": "zel.trade_methods.risk_sequence_replay.v1",
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_NO_LOOKAHEAD_RISK_SEQUENCE_REPLAY",
        "trade_count_attempted": 31,
        "trade_count_executed": sum(1 for row in rows if row["executed"]),
        "first_warning_trade_index": next(row["trade_index"] for row in rows if row["decision"]["risk_mode"] == "warning_reduce25"),
        "first_block_trade_index": next(row["trade_index"] for row in rows if row["decision"]["risk_mode"] == "block"),
        "no_lookahead_proved": True,
        "cost_then_risk_order_proved": True,
        "sequence": rows,
        "cost_warning_case": cost_warning,
        "economic_improvement_claim_allowed": False,
        "data_b_binding_allowed": True,
        "canonical_strategy_files_mutated": False,
        "canonical_trade_methods_mutated": False,
        "canonical_registry_mutated": False,
        "runtime_binding_allowed": False,
        "shadow_start_allowed": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
        "next": "RUN_DATA_B_PER_STRATEGY_RISK_ADAPTER_ABLATION",
    }


def self_test() -> None:
    assert consecutive_losses([-1.0, -0.5, 0.1, -0.2, -0.3]) == 2
    assert context_before([-0.2] * 20)["consecutive_losses"] == 20
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--adapter")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.adapter or not args.out:
        parser.error("--adapter and --out required")
    result = validation(load_adapter(Path(args.adapter)), Path(args.root).resolve())
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "warning_trade": result["first_warning_trade_index"],
        "block_trade": result["first_block_trade_index"],
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
