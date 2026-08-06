#!/usr/bin/env python3
"""Deterministically validate the ZEL Scalp profitability-first design receipt.

Research/static only. This script never reads trading credentials, places orders, or
mutates canonical/runtime/Shadow/Paper/Live state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = {
    "schema_version",
    "state",
    "supersedes",
    "input_receipts",
    "selected_architecture",
    "decision_time_features",
    "order_lifecycle",
    "risk_and_sizing",
    "all_in_cost_contract",
    "bounded_generation_1_search",
    "data_split_contract",
    "falsification",
    "rejected_alternatives",
    "implementation_authority",
}

SURVIVOR_METRICS = {"Net R", "PF", "expectancy", "payoff"}


def canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fail(message: str) -> None:
    raise ValueError(message)


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_TOP_LEVEL - payload.keys())
    if missing:
        fail(f"missing top-level fields: {missing}")

    if payload["schema_version"] != "zel.scalp.design_selection_receipt.v1":
        fail("unexpected schema_version")
    if payload["state"] != "PASS_DESIGN_SELECTED_IMPLEMENTATION_ALLOWED_RESEARCH_ONLY":
        fail("design receipt is not sealed PASS")

    supersedes = payload["supersedes"]
    if supersedes.get("strategy_id") != "scalp_snap":
        fail("failed inherited strategy identity is not fixed")
    if supersedes.get("disposition") != "ECONOMIC_FAIL_FROZEN":
        fail("failed inherited strategy is not frozen")
    if supersedes.get("same_family_repair_allowed") is not False:
        fail("same-family repair must remain blocked")
    terminal = supersedes.get("terminal_reference", {})
    if terminal.get("survivor_count") != 0:
        fail("terminal inherited survivor_count must be zero")
    if float(terminal.get("best_retention_valid_net_R", 0.0)) >= 0:
        fail("terminal failure evidence unexpectedly non-negative")

    selected = payload["selected_architecture"]
    if selected.get("strategy_id") != "intraday_pullback_reclaim_v1":
        fail("unexpected selected strategy_id")
    if selected.get("family") != "trend_continuation_pullback_reclaim":
        fail("unexpected selected family")
    if selected.get("market") != "BingX USDT-M perpetual futures":
        fail("market must remain BingX USDT-M")
    if selected.get("direction_policy") != "LONG_PRIMARY_SHORT_SEPARATE_CONSERVATIVE_ABLATION":
        fail("direction policy changed")

    features = payload["decision_time_features"]
    forbidden = set(features.get("forbidden", []))
    required_forbidden_fragments = {
        "future MFE/MAE",
        "same-bar hindsight entry",
        "future event labels",
        "assumed maker fill",
        "synthetic L2/order-flow history",
        "forward-filled missing candles",
    }
    if forbidden != required_forbidden_fragments:
        fail("forbidden-information contract changed")

    lifecycle = payload["order_lifecycle"]
    if "next eligible bar" not in lifecycle.get("entry_timing", ""):
        fail("entry timing is not conservative next-bar")
    if lifecycle.get("breakeven") != "disabled in generation 1 unless tested later as a distinct causal exit axis":
        fail("breakeven must remain disabled in generation 1")
    if lifecycle.get("partial_trailing") != "disabled in generation 1; standalone later only after base edge is positive":
        fail("partial/trailing must remain disabled in generation 1")

    risk = payload["risk_and_sizing"]
    if risk.get("research_position_size") != "normalized 1R only":
        fail("research sizing must remain normalized 1R")
    if risk.get("production_sizing_authority") is not False:
        fail("production sizing authority must remain false")
    if int(risk.get("max_open_positions", 0)) != 1:
        fail("max_open_positions must remain one")

    costs = payload["all_in_cost_contract"]
    baseline_cost = float(costs.get("baseline_all_in_cost_pct", 0.0))
    component_sum = sum(float(v) for v in costs.get("components_pct", {}).values())
    if abs(baseline_cost - component_sum) > 1e-12:
        fail("all-in cost does not equal component sum")
    required_stress = {"2x_all_in_cost", "P95_funding", "plus_one_bar_entry", "wider_slippage_by_regime"}
    if set(costs.get("stress", [])) != required_stress:
        fail("required execution stresses changed")
    if costs.get("mark_last_separation_required") is not True:
        fail("mark/last separation must remain required")

    search = payload["bounded_generation_1_search"]
    budget = int(search.get("trial_budget_max", 0))
    if budget <= 0 or budget > 48:
        fail("trial budget must be in 1..48")
    dims = search.get("dimensions", {})
    required_dims = {
        "regime_lookback_15m_bars",
        "directional_efficiency_min",
        "impulse_atr_multiple",
        "pullback_fraction",
        "reclaim_confirmation",
        "stop_atr_multiple",
        "target_R",
        "max_hold_bars",
        "expected_move_to_cost_min",
    }
    if set(dims) != required_dims:
        fail("generation-1 search dimensions changed")
    objective = search.get("W1_selection_objective", "")
    if not all(metric in objective for metric in SURVIVOR_METRICS):
        fail("W1 objective omits a required survivor metric")
    if "freeze" not in search.get("W2_W3_policy", ""):
        fail("W2/W3 freeze policy missing")

    splits = payload["data_split_contract"]
    if splits.get("W1") != "selection only":
        fail("W1 must remain selection-only")
    if "frozen OOS" not in splits.get("W2", "") or "frozen OOS" not in splits.get("W3", ""):
        fail("W2/W3 must remain frozen OOS")
    if splits.get("split_sha_required_before_replay") is not True:
        fail("split SHA requirement missing")
    if splits.get("purge_embargo_required") is not True:
        fail("purge/embargo requirement missing")
    if splits.get("trial_ledger_required") is not True:
        fail("trial ledger requirement missing")

    falsification = payload["falsification"]
    if falsification.get("no_relative_improvement_credit") is not True:
        fail("relative loss reduction must not receive credit")
    if int(falsification.get("maximum_generations_same_family_same_data_sha", 0)) != 2:
        fail("same-family generation cap changed")
    if len(falsification.get("economic_fail_if", [])) < 7:
        fail("falsification contract incomplete")

    authority = payload["implementation_authority"]
    if authority.get("new_research_candidate_code_allowed") is not True:
        fail("research implementation is not authorized")
    forbidden_authorities = [
        "canonical_mutation_allowed",
        "registry_mutation_allowed",
        "runtime_mutation_allowed",
        "shadow_allowed",
        "paper_allowed",
        "live_allowed",
        "selection_authority",
        "promotion_authority",
    ]
    for key in forbidden_authorities:
        if authority.get(key) is not False:
            fail(f"{key} must remain false")
    if authority.get("execution_authority") != "NONE":
        fail("execution authority must remain NONE")
    if authority.get("order_authority") != "BLOCKED":
        fail("order authority must remain BLOCKED")
    if authority.get("action") != "route_change":
        fail("action must remain route_change")

    return {
        "state": "PASS",
        "schema_version": payload["schema_version"],
        "strategy_id": selected["strategy_id"],
        "selected_family": selected["family"],
        "trial_budget_max": budget,
        "all_in_cost_pct": baseline_cost,
        "receipt_sha256": canonical_sha256(payload),
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "route_change",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--receipt",
        default="backend/research/zel_scalp_design_selection_receipt_v1.json",
        type=Path,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        payload = json.loads(args.receipt.read_text(encoding="utf-8"))
        result = validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"state": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
