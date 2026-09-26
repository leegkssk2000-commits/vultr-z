"""Compare frozen same-condition pairs; never run or select a candidate."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

PAIR_AXES = {
    "SUPERTREND_TRAILING_ONLY": "SETUP_CLOCK",
    "SR_BREAKOUT_VS_LATER_RETEST": "FIXED_DAY_REFERENCE",
}
METRICS = (
    "T_resolved",
    "WR_resolved_pct",
    "gross_resolved_usdt",
    "net_resolved_reference_usdt",
    "net_per_trade_resolved_reference_usdt",
    "PF_resolved_reference",
    "DD_pct",
    "MaxLS_resolved",
)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("NUMERIC_METRIC_REQUIRED")
    if not math.isfinite(float(value)):
        raise ValueError("NONFINITE_METRIC")
    return float(value)


def _setup_orders(result: Mapping[str, Any], mode: str) -> dict[str, tuple[Any, ...]]:
    found = {}
    for execution in result["execution"]["executions"]:
        order = execution.get("order")
        if not order:
            continue
        episode = order["position_episode_id"]
        if episode in found:
            raise ValueError("DUPLICATE_EXECUTION_EPISODE")
        key: tuple[Any, ...]
        if mode == "SETUP_CLOCK":
            key = (order["symbol"], order["side"], order["setup_ts_ms"])
        else:
            key = (
                order["symbol"],
                order["side"],
                order["session_end_ms"],
                order["reference_edge"],
            )
        if isinstance(order["side"], bool) or order["side"] not in (-1, 1):
            raise ValueError("INVALID_SETUP_SIDE")
        found[episode] = key
    return found


def _closed(
    episodes: list[dict[str, Any]], start: int, end: int
) -> list[dict[str, Any]]:
    return [
        row
        for row in episodes
        if row["closed"]
        and start <= row["entry_ts_ms"] < end
        and row["outcome_available_ts_ms"] < end
    ]


def _unique(
    rows: list[dict[str, Any]], setups: Mapping[str, tuple[Any, ...]]
) -> dict[tuple[Any, ...], dict[str, Any]]:
    found = {}
    for row in rows:
        if row["episode_id"] not in setups:
            raise ValueError("EPISODE_SETUP_ORDER_MISSING")
        key = setups[row["episode_id"]]
        if key in found:
            raise ValueError("AMBIGUOUS_SAME_SETUP_MULTIPLE_EPISODES")
        _number(row["net_reference_usdt"])
        found[key] = row
    return found


def _window_map(
    rows: list[dict[str, Any]], binding: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    expected = {
        r["name"]: r
        for r in binding["windows"]
        if r["kind"] not in {"CONTEXT", "TRAIN"}
    }
    found = {}
    for row in rows:
        name = row["name"]
        if name in found:
            raise ValueError("DUPLICATE_WINDOW_RESULT")
        if name not in expected:
            raise ValueError("WINDOW_OUTSIDE_FROZEN_BINDING")
        if any(
            row[k] != expected[name][k] for k in ("kind", "start_ts_ms", "end_ts_ms")
        ):
            raise ValueError("WINDOW_BOUNDARY_MISMATCH")
        if type(row["complete_window"]) is not bool:
            raise ValueError("EXPLICIT_BOOLEAN_WINDOW_COMPLETENESS_REQUIRED")
        found[name] = row
    if found.keys() != expected.keys():
        raise ValueError("WINDOW_RESULT_SET_DIFFERS")
    return found


def compare_matched(
    parent: Mapping[str, Any],
    child: Mapping[str, Any],
    parent_binding: Mapping[str, Any],
    child_binding: Mapping[str, Any],
    *,
    axis: str,
) -> dict[str, Any]:
    """Measured reference-cost deltas and winner damage; never adoption."""
    if axis not in PAIR_AXES:
        raise ValueError("EXPLICIT_MATCHED_AXIS_REQUIRED")
    for key in (
        "data_manifest",
        "cost",
        "windows",
        "initial_cash_usdt",
        "capital_policy",
        "gap_policy",
        "price_basis",
        "execution_mode",
        "config",
        "model_module",
        "compiler",
        "code_closure",
        "environment",
    ):
        if parent_binding[key] != child_binding[key]:
            raise ValueError("MATCHED_CONDITION_DIFFERS:" + key)
    if parent_binding["strategy_id"] != child_binding["strategy_id"]:
        raise ValueError("MATCHED_STRATEGY_REQUIRED")
    if child_binding["baseline_id"] != parent_binding["model_id"]:
        raise ValueError("CHILD_MUST_BIND_ACTUAL_CONTROL_MODEL")
    if child_binding["model_id"] == parent_binding["model_id"]:
        raise ValueError("DISTINCT_CHILD_MODEL_REQUIRED")
    for result, binding in ((parent, parent_binding), (child, child_binding)):
        if result["identity_key"] != binding["identity_key"]:
            raise ValueError("RESULT_IDENTITY_MISMATCH")
        if result["binding_sha256"] != binding["binding_sha256"]:
            raise ValueError("RESULT_FREEZE_MISMATCH")
    pkeys = _setup_orders(parent, PAIR_AXES[axis])
    ckeys = _setup_orders(child, PAIR_AXES[axis])
    scenarios = {}
    for scenario in ("1x", "2x"):
        ps = parent["cost_scenarios"][scenario]
        cs = child["cost_scenarios"][scenario]
        pwin = _window_map(ps["windows"], parent_binding)
        cwin = _window_map(cs["windows"], child_binding)
        comparisons = []
        for name, pw in pwin.items():
            cw = cwin[name]
            complete = pw["complete_window"] and cw["complete_window"]
            values = {}
            for metric in METRICS:
                p, c = pw[metric], cw[metric]
                delta = None
                if p is not None:
                    _number(p)
                if c is not None:
                    _number(c)
                if p is not None and c is not None:
                    delta = c - p
                values[metric] = {"parent": p, "child": c, "delta": delta}
            winner_damage = None
            if complete:
                pr = _unique(
                    _closed(ps["episodes"], pw["start_ts_ms"], pw["end_ts_ms"]), pkeys
                )
                cr = _unique(
                    _closed(cs["episodes"], cw["start_ts_ms"], cw["end_ts_ms"]), ckeys
                )
                winners = {
                    key: row for key, row in pr.items() if row["net_reference_usdt"] > 0
                }
                parent_profit = sum(
                    row["net_reference_usdt"] for row in winners.values()
                )
                matched = [
                    cr[key]["net_reference_usdt"] if key in cr else 0.0
                    for key in winners
                ]
                winner_damage = {
                    "matching_basis": PAIR_AXES[axis],
                    "parent_winners": len(winners),
                    "child_positive_same_setup": sum(value > 0 for value in matched),
                    "child_negative_same_setup": sum(value < 0 for value in matched),
                    "child_zero_same_setup": sum(
                        cr[key]["net_reference_usdt"] == 0
                        for key in winners
                        if key in cr
                    ),
                    "child_absent_same_setup": sum(key not in cr for key in winners),
                    "parent_winner_net_usdt": parent_profit,
                    "child_net_on_parent_winning_setups_usdt": sum(matched),
                    "winner_net_delta_usdt": sum(matched) - parent_profit,
                    "positive_winner_profit_retention_pct": (
                        100 * sum(max(0.0, value) for value in matched) / parent_profit
                        if parent_profit
                        else None
                    ),
                    "not_an_identical_entry_claim": axis
                    == "SR_BREAKOUT_VS_LATER_RETEST",
                }
            joint = None
            if complete and all(
                values[key]["delta"] is not None
                for key in (
                    "T_resolved",
                    "WR_resolved_pct",
                    "net_resolved_reference_usdt",
                    "DD_pct",
                )
            ):
                joint = (
                    values["T_resolved"]["delta"] > 0
                    and values["WR_resolved_pct"]["delta"] > 0
                    and values["net_resolved_reference_usdt"]["delta"] > 0
                    and values["DD_pct"]["delta"] < 0
                )
            comparisons.append(
                {
                    "name": name,
                    "kind": pw["kind"],
                    "complete_pair_window": complete,
                    "metrics": values,
                    "winner_damage": winner_damage,
                    "strict_T_WR_Net_up_DD_down": joint,
                    "incomplete_resolved_subset_is_not_total_performance": not complete,
                }
            )
        scenarios[scenario] = comparisons
    return {
        "schema": "scalp7.exact25.model_comparison.v1",
        "axis": axis,
        "parent_identity": parent["identity_key"],
        "child_identity": child["identity_key"],
        "cost_scenarios": scenarios,
        "actual_historical_net": None,
        "funding_status": "UNKNOWN_NOT_ZERO",
        "formal_promotion": "BLOCKED",
        "authority": copy.deepcopy(parent["authority"]),
    }
