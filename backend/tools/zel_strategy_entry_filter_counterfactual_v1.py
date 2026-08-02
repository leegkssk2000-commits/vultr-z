from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import zel_strategy_loss_attribution_gemini_v1 as attribution

VERSION = "ZEL_STRATEGY_ENTRY_FILTER_COUNTERFACTUAL_V1"
SCHEMA = "zel.strategy_entry_filter_counterfactual.receipt.v1"
ALLOWED_AXES = {"regime", "hour_bucket", "symbol", "side"}
ALLOWED_OPERATIONS = {"exclude", "include"}


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def apply_rule(
    rows: Sequence[Mapping[str, Any]],
    axis: str,
    operation: str,
    values: set[str],
) -> list[Mapping[str, Any]]:
    if operation == "exclude":
        return [row for row in rows if str(row.get(axis) or "unknown") not in values]
    return [row for row in rows if str(row.get(axis) or "unknown") in values]


def delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_pf = attribution.finite_number(base.get("profit_factor"))
    candidate_pf = attribution.finite_number(candidate.get("profit_factor"))
    return {
        "delta_net_R": float(candidate.get("net_R") or 0.0) - float(base.get("net_R") or 0.0),
        "delta_max_drawdown_R": float(candidate.get("max_drawdown_R") or 0.0)
        - float(base.get("max_drawdown_R") or 0.0),
        "delta_profit_factor": candidate_pf - base_pf
        if candidate_pf is not None and base_pf is not None
        else None,
        "trade_retention_pct": float(candidate.get("trade_count") or 0)
        / max(float(base.get("trade_count") or 0), 1.0)
        * 100.0,
    }


def evaluate_requirements(
    requirements: Mapping[str, Any],
    total_candidate: Mapping[str, Any],
    total_delta: Mapping[str, Any],
    windows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, actual: Any, limit: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "actual": actual, "limit": limit})

    if "min_total_delta_net_R" in requirements:
        limit = float(requirements["min_total_delta_net_R"])
        actual = float(total_delta["delta_net_R"])
        check("min_total_delta_net_R", actual >= limit, actual, limit)
    if "min_total_retention_pct" in requirements:
        limit = float(requirements["min_total_retention_pct"])
        actual = float(total_delta["trade_retention_pct"])
        check("min_total_retention_pct", actual >= limit, actual, limit)
    if "min_total_profit_factor" in requirements:
        limit = float(requirements["min_total_profit_factor"])
        actual = attribution.finite_number(total_candidate.get("profit_factor"))
        check("min_total_profit_factor", actual is not None and actual >= limit, actual, limit)
    if requirements.get("require_positive_delta_all_windows"):
        actual = {
            window: float(value["delta"]["delta_net_R"])
            for window, value in windows.items()
        }
        check(
            "require_positive_delta_all_windows",
            bool(actual) and all(value > 0 for value in actual.values()),
            actual,
            ">0 each",
        )
    if requirements.get("require_nonworse_drawdown_all_windows"):
        actual = {
            window: float(value["delta"]["delta_max_drawdown_R"])
            for window, value in windows.items()
        }
        check(
            "require_nonworse_drawdown_all_windows",
            bool(actual) and all(value >= 0 for value in actual.values()),
            actual,
            ">=0 each",
        )
    if "require_positive_delta_windows" in requirements:
        targets = [str(value) for value in requirements["require_positive_delta_windows"]]
        actual = {
            window: float(windows.get(window, {}).get("delta", {}).get("delta_net_R", float("-inf")))
            for window in targets
        }
        check(
            "require_positive_delta_windows",
            all(value > 0 for value in actual.values()),
            actual,
            ">0 each requested window",
        )
    if "min_window_candidate_trades" in requirements:
        limit = int(requirements["min_window_candidate_trades"])
        actual = {
            window: int(value["candidate"]["trade_count"])
            for window, value in windows.items()
        }
        check(
            "min_window_candidate_trades",
            bool(actual) and all(value >= limit for value in actual.values()),
            actual,
            limit,
        )
    return {
        "passed": bool(checks) and all(row["passed"] for row in checks),
        "checks": checks,
    }


def candidate_state(
    gemini_gate: Mapping[str, Any],
    ssot_gate: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
) -> tuple[str, str]:
    if not gemini_gate.get("passed"):
        return "REJECT_GEMINI_HYPOTHESIS_FALSIFIED", "block"
    if not ssot_gate.get("passed"):
        return "HOLD_POLICY_CONFLICT", "hold"
    net_r = float(candidate_metrics.get("net_R") or 0.0)
    profit_factor = attribution.finite_number(candidate_metrics.get("profit_factor"))
    if net_r > 0 and profit_factor is not None and profit_factor > 1.0:
        return "PASS_LEDGER_COUNTERFACTUAL_POSITIVE_EDGE_TO_SOURCE_REPLAY", "hold"
    return "PASS_LEDGER_COUNTERFACTUAL_LOSS_REDUCTION_ONLY", "hold"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy = read_object(args.policy)
    queue = read_object(args.queue)
    summary = read_object(args.summary)
    rows = attribution.read_trades(args.trades)
    expected_trade_count = int(policy["expected_trade_count"])
    if len(rows) != expected_trade_count:
        raise RuntimeError(f"TRADE_COUNT_MISMATCH:{len(rows)}")
    if summary.get("state") != "PASS_ATTRIBUTION_AND_GEMINI_IMPROVEMENT_QUEUE_READY":
        raise RuntimeError("UPSTREAM_SUMMARY_NOT_PASS")
    if summary.get("attribution_receipt_sha256") != policy["expected_attribution_receipt_sha256"]:
        raise RuntimeError("ATTRIBUTION_RECEIPT_SHA_MISMATCH")
    queue_items = queue.get("items")
    if not isinstance(queue_items, list) or len(queue_items) != int(policy["expected_queue_item_count"]):
        raise RuntimeError("QUEUE_ITEM_COUNT_MISMATCH")
    queue_by_strategy = {
        str(item.get("strategy_id")): item
        for item in queue_items
        if isinstance(item, Mapping) and item.get("strategy_id")
    }

    windows = [str(value) for value in policy["windows"]]
    ssot_requirements = dict(policy["ssot_gate"])
    ssot_requirements["min_total_retention_pct"] = float(
        policy["ssot_gate"]["min_total_retention_pct"]
    )
    results: list[dict[str, Any]] = []
    accepted_rules: list[dict[str, Any]] = []

    for candidate in policy["candidates"]:
        strategy_id = str(candidate["strategy_id"])
        queue_item = queue_by_strategy.get(strategy_id)
        if not queue_item:
            raise RuntimeError(f"QUEUE_STRATEGY_MISSING:{strategy_id}")
        if queue_item.get("change_type") != "entry_filter":
            raise RuntimeError(f"QUEUE_CHANGE_TYPE_INVALID:{strategy_id}")
        axis = str(candidate["axis"])
        operation = str(candidate["operation"])
        values = {str(value) for value in candidate["values"]}
        if axis not in ALLOWED_AXES or operation not in ALLOWED_OPERATIONS or not values:
            raise RuntimeError(f"CANDIDATE_RULE_INVALID:{candidate['candidate_id']}")

        strategy_rows = [row for row in rows if row.get("strategy_id") == strategy_id]
        if not strategy_rows:
            raise RuntimeError(f"CANDIDATE_STRATEGY_ZERO_TRADE:{strategy_id}")
        filtered_rows = apply_rule(strategy_rows, axis, operation, values)
        removed_rows = [row for row in strategy_rows if row not in filtered_rows]
        base_metrics = attribution.metrics(strategy_rows)
        filtered_metrics = attribution.metrics(filtered_rows)
        removed_metrics = attribution.metrics(removed_rows)
        total_delta = delta(base_metrics, filtered_metrics)

        by_window: dict[str, Any] = {}
        for window in windows:
            base_window_rows = [row for row in strategy_rows if row.get("window_id") == window]
            candidate_window_rows = apply_rule(base_window_rows, axis, operation, values)
            removed_window_rows = [row for row in base_window_rows if row not in candidate_window_rows]
            base_window = attribution.metrics(base_window_rows)
            candidate_window = attribution.metrics(candidate_window_rows)
            by_window[window] = {
                "base": base_window,
                "candidate": candidate_window,
                "removed": attribution.metrics(removed_window_rows),
                "delta": delta(base_window, candidate_window),
            }

        gemini_gate = evaluate_requirements(
            candidate["gemini_requirements"], filtered_metrics, total_delta, by_window
        )
        ssot_gate = evaluate_requirements(
            ssot_requirements, filtered_metrics, total_delta, by_window
        )
        state, action = candidate_state(gemini_gate, ssot_gate, filtered_metrics)
        row = {
            "candidate_id": candidate["candidate_id"],
            "strategy_id": strategy_id,
            "alias": queue_item.get("alias"),
            "rule": {
                "axis": axis,
                "operation": operation,
                "values": sorted(values),
            },
            "gemini_approval_reason": queue_item.get("approval_reason"),
            "gemini_falsification_test": queue_item.get("falsification_test"),
            "state": state,
            "base": base_metrics,
            "candidate": filtered_metrics,
            "removed": removed_metrics,
            "delta": total_delta,
            "by_window": by_window,
            "gemini_gate": gemini_gate,
            "ssot_gate": ssot_gate,
            "source_replay_required": state.startswith("PASS_"),
            "production_applied": False,
            "canonical_mutated": False,
            "runtime_mutated": False,
            "formal_ledger_mutated": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": action,
        }
        results.append(row)
        if state.startswith("PASS_"):
            accepted_rules.append(row)

    accepted_strategy_ids = {row["strategy_id"] for row in accepted_rules}
    portfolio_rows = []
    for row in rows:
        matched = next(
            (candidate for candidate in accepted_rules if candidate["strategy_id"] == row["strategy_id"]),
            None,
        )
        if not matched:
            portfolio_rows.append(row)
            continue
        rule = matched["rule"]
        if apply_rule([row], rule["axis"], rule["operation"], set(rule["values"])):
            portfolio_rows.append(row)
    portfolio_base = attribution.metrics(rows)
    portfolio_candidate = attribution.metrics(portfolio_rows)
    portfolio = {
        "accepted_strategy_ids": sorted(accepted_strategy_ids),
        "base": portfolio_base,
        "candidate": portfolio_candidate,
        "delta": delta(portfolio_base, portfolio_candidate),
        "economic_superiority_claim_allowed": False,
        "portfolio_selection_allowed": False,
    }

    states = {row["state"] for row in results}
    final_state = (
        "PASS_ENTRY_FILTER_COUNTERFACTUAL_COMPLETE_WITH_POLICY_CONFLICTS"
        if "HOLD_POLICY_CONFLICT" in states
        else "PASS_ENTRY_FILTER_COUNTERFACTUAL_COMPLETE"
    )
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": final_state,
        "trade_count": len(rows),
        "candidate_count": len(results),
        "pass_count": sum(row["state"].startswith("PASS_") for row in results),
        "policy_conflict_count": sum(row["state"] == "HOLD_POLICY_CONFLICT" for row in results),
        "rejected_count": sum(row["state"].startswith("REJECT_") for row in results),
        "upstream_summary_sha256": file_sha(args.summary),
        "upstream_queue_sha256": file_sha(args.queue),
        "policy_sha256": file_sha(args.policy),
        "candidates": results,
        "portfolio_counterfactual": portfolio,
        "raw_trade_data_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "SOURCE_LEVEL_EXACT_REPLAY_FOR_PASS_CANDIDATES_AND_ADJUDICATE_POLICY_CONFLICTS",
    }
    receipt["receipt_sha256"] = attribution.stable_sha(receipt)
    args.out.mkdir(parents=True, exist_ok=True)
    attribution.atomic_json(args.out / "latest.json", receipt)
    for row in results:
        attribution.atomic_json(args.out / f"{row['candidate_id']}.json", row)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
