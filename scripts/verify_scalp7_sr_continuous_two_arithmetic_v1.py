#!/usr/bin/env python3
"""Independently audit saved SR fills and marks; no market replay or DB writes."""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import runpy
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/verify_scalp7_exact25_five_arithmetic_v1.py"
core = runpy.run_path(str(HELPER))
Audit = core["Audit"]
number = core["number"]
D = Decimal
ZERO = D(0)
LABELS = ("SR_CONTROL", "SR_RETEST")
IDENTITIES = {
    "SR_CONTROL": "08e02370c96bd0c65ced1bb3f65bcb19099665c1b0a487a4226a3bfc49c53200",
    "SR_RETEST": "6ccad0c2e6939d801a2a216661213414edd46db79f31ae3f017125afbd348b70",
}
QTY_POLICY_SOURCE = "backend/research/rebuild/scalp7_exact25_reference_models_v1.py"
QTY_POLICY_SOURCE_SHA256 = (
    "340e219fbf97a95f25b0414f588a12429f3978f05c7fbdd1108e30c68696c6d3"
)
# PR1346's frozen create_order uses this literal; saved orders cannot redefine it.
FROZEN_QTY_POLICY = {
    "risk_fraction": 0.0025,
    "notional_fraction": 0.10,
    "capital_unit": "USDT",
    "quantity_unit": "BASE",
    "gap_notional_policy": "REJECT_ABOVE_RESERVED_NOTIONAL",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def load(path: Path) -> tuple[dict[str, Any], bytes, bytes]:
    stored = path.read_bytes()
    raw = gzip.decompress(stored) if path.suffix == ".gz" else stored
    return json.loads(raw), raw, stored


def sample_grid(segment: dict[str, Any], decision_minutes: int) -> list[int]:
    start, end = segment["raw_start_ts_ms"], segment["evaluation_end_ts_ms"]
    step = decision_minutes * 60_000
    first = -(-start // step) * step
    return sorted({start, end, *range(first, end + 1, step)})


def episode_keys(executions: list[dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    """Use the common fixed prior-day box, side and session, never trade index."""
    answer = {}
    for execution in executions:
        order = execution.get("order")
        if not order:
            continue
        episode = order["position_episode_id"]
        if episode in answer:
            raise ValueError("DUPLICATE_EPISODE_ORDER")
        answer[episode] = (
            order["symbol"],
            order["side"],
            order["signal"]["reference_id"],
            order["session_end_ms"],
            number(order["reference_edge"]),
        )
    return answer


def frozen_quantity_policy(
    binding: dict[str, Any], check: Any, prefix: str
) -> dict[str, Any]:
    """Authenticate the frozen producer literal without importing its code."""
    check.equal(
        prefix + ".quantity_policy.producer_binding",
        binding.get("code_closure", {}).get(QTY_POLICY_SOURCE),
        QTY_POLICY_SOURCE_SHA256,
    )
    raw = (ROOT / QTY_POLICY_SOURCE).read_bytes()
    check.equal(
        prefix + ".quantity_policy.producer_source_sha256",
        hashlib.sha256(raw).hexdigest(),
        QTY_POLICY_SOURCE_SHA256,
    )
    literals = [
        ast.literal_eval(node.value)
        for node in ast.parse(raw).body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "QTY_POLICY"
    ]
    if len(literals) != 1:
        raise ValueError("EXACT_FROZEN_QUANTITY_POLICY_LITERAL_REQUIRED")
    check.equal(
        prefix + ".quantity_policy.producer_literal", literals[0], FROZEN_QTY_POLICY
    )
    return dict(FROZEN_QTY_POLICY)


def validate_fills(
    executed: dict[str, Any], binding: dict[str, Any], check: Any, prefix: str
) -> None:
    policy = frozen_quantity_policy(binding, check, prefix)
    orders = {
        e["order"]["position_episode_id"]: e["order"]
        for e in executed["executions"]
        if e.get("order")
    }
    for episode, order in orders.items():
        check.equal(
            prefix + ".quantity_policy.frozen_literal." + episode,
            order.get("qty_policy"),
            policy,
        )
        capital = number(order["reserved_notional_usdt"]) / number(
            policy["notional_fraction"]
        )
        risk = number(order["side"]) * (
            number(order["reference_entry_price"]) - number(order["protective_stop"])
        )
        if risk <= 0 or capital <= 0:
            raise ValueError("NONPOSITIVE_SAVED_ORDER_RISK_OR_CAPITAL")
        quantity = min(
            capital * number(policy["risk_fraction"]) / risk,
            capital
            * number(policy["notional_fraction"])
            / number(order["reference_entry_price"]),
        )
        check.equal(prefix + ".quantity_policy." + episode, order["qty_base"], quantity)
        check.equal(
            prefix + ".planned_stop_risk." + episode,
            order["planned_stop_risk_usdt"],
            quantity * risk,
        )
        check.equal(
            prefix + ".order_identity." + episode,
            order["identity"],
            binding["identity_key"],
        )
    for index, row in enumerate(executed["ledger"]):
        rate = number(binding["cost"]["per_side_rates"][row["symbol"]])
        if rate < 0:
            raise ValueError("NEGATIVE_FROZEN_COST_RATE")
        fee = number(row["qty_base"]) * number(row["fill_price"]) * rate
        check.equal(f"{prefix}.fill[{index}].fee", row["fee_usdt"], fee)
        check.equal(
            f"{prefix}.fill[{index}].quantity_unit",
            row.get("quantity_unit", "BASE"),
            "BASE",
        )
        check.equal(
            f"{prefix}.fill[{index}].cash_unit", row.get("cash_unit", "USDT"), "USDT"
        )
        order = orders.get(row["position_episode_id"])
        check.equal(f"{prefix}.fill[{index}].order_present", order is not None, True)
        if order is not None and row["effect"] == "OPEN":
            check.equal(
                f"{prefix}.fill[{index}].open_qty", row["qty_base"], order["qty_base"]
            )


def dd_interval(curve: list[dict[str, Any]], initial: Any, start: int, end: int) -> Any:
    samples = [row for row in curve if start <= row["ts_ms"] < end]
    if not samples:
        return None
    prior = [row for row in curve if row["ts_ms"] < start]
    peak = number(prior[-1]["equity_usdt"]) if prior else number(initial)
    maximum = ZERO
    for row in samples:
        equity = number(row["equity_usdt"])
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, D(100) * (peak - equity) / peak)
    return maximum


def audit_child(
    result: dict[str, Any],
    binding: dict[str, Any],
    segment: dict[str, Any],
    contract: dict[str, Any],
    check: Any,
    prefix: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    check.equal(prefix + ".identity", result["identity_key"], binding["identity_key"])
    check.equal(
        prefix + ".binding", result["binding_sha256"], binding["binding_sha256"]
    )
    check.equal(prefix + ".fresh_T", result["fresh_T"], 0)
    executed = result["execution"]
    ledger = executed["ledger"]
    unknown = [
        e
        for e in executed["executions"]
        if e.get("state", e.get("status")) == "UNRESOLVED"
        or e.get("unresolved") is True
    ]
    check.equal(
        prefix + ".unknown_count", result["unknown_execution_count"], len(unknown)
    )
    validate_fills(executed, binding, check, prefix)
    keys = episode_keys(executed["executions"])
    grid = sample_grid(segment, contract["decision_minutes"])
    cutoff = min(
        (e.get("unresolved_observed_ts_ms", 0) for e in unknown), default=2**63 - 1
    )
    expected_marks = [stamp for stamp in grid if stamp < cutoff]
    evaluations = [
        w for w in binding["windows"] if w["kind"] not in {"CONTEXT", "TRAIN"}
    ]
    check.equal(prefix + ".one_evaluation_window", len(evaluations), 1)
    window = evaluations[0]
    start, end = window["start_ts_ms"], window["end_ts_ms"]
    output, compact = {}, {}
    for multiplier in (1, 2):
        label = str(multiplier) + "x"
        stored = result["cost_scenarios"][label]
        episodes = core["rebuild_episodes"](ledger, multiplier)
        saved_episodes = {e["episode_id"]: e for e in stored["episodes"]}
        check.equal(
            prefix + "." + label + ".episode_ids",
            sorted(saved_episodes),
            sorted(e["episode_id"] for e in episodes),
        )
        for item in episodes:
            for key, value in item.items():
                if key != "basis_remaining":
                    check.equal(
                        f"{prefix}.{label}.episode.{item['episode_id']}.{key}",
                        saved_episodes.get(item["episode_id"], {}).get(key),
                        value,
                    )
        account = stored["account"]
        observed_marks = (
            [] if account is None else [s["ts_ms"] for s in account["snapshots"]]
        )
        check.equal(
            prefix + "." + label + ".snapshot_grid_prefix",
            observed_marks,
            expected_marks,
        )
        if account is not None:
            for index, sample in enumerate(account["snapshots"]):
                check.equal(
                    f"{prefix}.{label}.mark[{index}].universe",
                    sorted(sample["prices"]),
                    sorted(contract["symbols"]),
                )
                for symbol, quote in sample["prices"].items():
                    check.equal(
                        f"{prefix}.{label}.mark[{index}].{symbol}.ts",
                        quote["ts_ms"],
                        sample["ts_ms"],
                    )
                    check.equal(
                        f"{prefix}.{label}.mark[{index}].{symbol}.basis",
                        quote["price_basis"],
                        "LAST_PRICE",
                    )
                    if number(quote["price"]) <= 0:
                        raise ValueError("NONPOSITIVE_RECORDED_LAST_PRICE")
        curve = core["rebuild_account"](
            account, ledger, binding["initial_cash_usdt"], multiplier, check
        )
        cohort = [
            e
            for e in episodes
            if start <= e["entry_ts_ms"] < end
            and e["closed"]
            and e["outcome_available_ts_ms"] < end
        ]
        crossing = [
            e
            for e in episodes
            if start <= e["entry_ts_ms"] < end
            and (not e["closed"] or e["outcome_available_ts_ms"] >= end)
        ]
        carried = [
            e
            for e in episodes
            if e["entry_ts_ms"] < start
            and (not e["closed"] or e["outcome_available_ts_ms"] >= start)
        ]
        affected = [e for e in unknown if e.get("unresolved_from_ts_ms", 0) < end]
        complete = not (crossing or carried or affected)
        metrics = core["cohort_stats"](cohort)
        metrics.update(
            {
                "T_per_day_resolved": D(len(cohort)) * D(86_400_000) / D(end - start),
                "cross_boundary_or_open_count": len(crossing),
                "carry_in_count": len(carried),
                "complete_window": complete,
                "net_complete_reference_usdt": (
                    metrics["net_resolved_reference_usdt"] if complete else None
                ),
                "actual_historical_net_usdt": None,
                "funding_status": "UNKNOWN_NOT_ZERO",
                "DD_pct": (
                    dd_interval(curve, binding["initial_cash_usdt"], start, end)
                    if complete
                    else None
                ),
            }
        )
        check.equal(
            prefix + "." + label + ".one_saved_window", len(stored["windows"]), 1
        )
        saved_window = stored["windows"][0]
        for key, value in {**window, **metrics}.items():
            if key != "cost_resolved_reference_usdt":
                check.equal(
                    prefix + "." + label + ".window." + key,
                    saved_window.get(key),
                    value,
                )
        expected_status = (
            "REFERENCE_COST_LAST_PRICE_NAV_FUNDING_UNKNOWN"
            + ("_PREFIX_ONLY" if unknown else "")
            if expected_marks
            else "UNRESOLVED_EXECUTION_PREVENTS_COMPLETE_ACCOUNT_CURVE"
        )
        check.equal(
            prefix + "." + label + ".account_status",
            stored["account_status"],
            expected_status,
        )
        nav_complete = observed_marks == grid
        eval_grid_complete = all(
            stamp in observed_marks for stamp in grid if start <= stamp <= end
        )
        sampled_dd = max((p["drawdown_pct"] for p in curve), default=None)
        output[label] = {
            "window": window,
            "metrics": {**metrics, "unknown_affected_count": len(affected)},
            "nav": {
                "price_basis": "LAST_PRICE",
                "expected_sample_count": len(grid),
                "observed_sample_count": len(observed_marks),
                "missing_sample_count": len(grid) - len(observed_marks),
                "whole_segment_sample_grid_complete": nav_complete,
                "evaluation_sample_grid_complete": eval_grid_complete,
                "full_segment_sampled_DD_pct": sampled_dd if nav_complete else None,
                "prefix_sampled_DD_pct": sampled_dd if not nav_complete else None,
                "evaluation_terminal_inclusive_sampled_DD_pct": (
                    dd_interval(curve, binding["initial_cash_usdt"], start, end + 1)
                    if eval_grid_complete
                    else None
                ),
                "frozen_window_DD_endpoint": "EXCLUSIVE_EVALUATION_END",
                "end_research_equity_usdt": (
                    curve[-1]["equity_usdt"] if nav_complete and curve else None
                ),
                "funding_status": "UNKNOWN_NOT_ZERO",
            },
            "all_fill_cost_reference_usdt": sum(
                (number(r["fee_usdt"]) * multiplier for r in ledger), ZERO
            ),
            "open_episode_count": sum(not e["closed"] for e in episodes),
            "unknown_execution_count": len(unknown),
            "ledger_rows": len(ledger),
        }
        compact[label] = {
            "cohort": cohort,
            "keys": keys,
            "complete": complete,
            "episodes": episodes,
            "execution_states": {
                e["order"]["position_episode_id"]: (
                    e.get("state", e.get("status")),
                    e.get("unresolved") is True,
                )
                for e in executed["executions"]
                if e.get("order")
            },
        }
    a1, a2 = (result["cost_scenarios"][k]["account"] for k in ("1x", "2x"))
    check.equal(
        prefix + ".cost2x.identical_marks",
        None if a2 is None else [(s["ts_ms"], s["prices"]) for s in a2["snapshots"]],
        None if a1 is None else [(s["ts_ms"], s["prices"]) for s in a1["snapshots"]],
    )
    return {"identity_key": binding["identity_key"], "cost_scenarios": output}, compact


def winner_diagnostics(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Classify saved admitted child evidence on resolved parent winners only."""
    parent_groups: dict[tuple[Any, ...], list[str]] = {}
    child_groups: dict[tuple[Any, ...], list[str]] = {}
    for source, groups in ((parent, parent_groups), (child, child_groups)):
        for episode, key in source["keys"].items():
            groups.setdefault(key, []).append(episode)
    ambiguous_admitted = [
        {
            "arm": arm,
            "opportunity_key": list(key),
            "admitted_episode_ids": sorted(episodes),
        }
        for arm, groups in (
            ("SR_CONTROL", parent_groups),
            ("SR_RETEST", child_groups),
        )
        for key, episodes in groups.items()
        if len(episodes) > 1
    ]
    child_episodes = {e["episode_id"]: e for e in child["episodes"]}
    child_closed = {e["episode_id"]: e for e in child["cohort"]}
    winners = [e for e in parent["cohort"] if e["net_reference_usdt"] > 0]
    counts = {
        key: 0
        for key in (
            "CHILD_CLOSED_POSITIVE",
            "CHILD_CLOSED_NEGATIVE",
            "CHILD_CLOSED_ZERO",
            "CHILD_OPEN_OR_UNRESOLVED",
            "CHILD_BOUNDARY_EXCLUDED_CLOSED",
            "CHILD_ADMITTED_NO_FILL_TERMINAL",
            "CHILD_ADMITTED_NO_FILL_UNKNOWN_STATUS",
            "NO_SAVED_ADMITTED_CHILD_ORDER",
            "AMBIGUOUS_PARENT_OPPORTUNITY",
            "AMBIGUOUS_CHILD_OPPORTUNITY",
        )
    }
    rows = []
    for winner in winners:
        parent_episode = winner["episode_id"]
        key = parent["keys"][parent_episode]
        parent_ids, child_ids = parent_groups[key], child_groups.get(key, [])
        child_net = None
        if len(parent_ids) > 1:
            category = "AMBIGUOUS_PARENT_OPPORTUNITY"
        elif len(child_ids) > 1:
            category = "AMBIGUOUS_CHILD_OPPORTUNITY"
        elif not child_ids:
            category = "NO_SAVED_ADMITTED_CHILD_ORDER"
        else:
            child_id = child_ids[0]
            episode = child_episodes.get(child_id)
            state, unresolved = child["execution_states"][child_id]
            if (
                state == "UNRESOLVED"
                or unresolved
                or (episode and not episode["closed"])
            ):
                category = "CHILD_OPEN_OR_UNRESOLVED"
            elif child_id in child_closed:
                child_net = child_closed[child_id]["net_reference_usdt"]
                category = (
                    "CHILD_CLOSED_POSITIVE"
                    if child_net > 0
                    else (
                        "CHILD_CLOSED_NEGATIVE"
                        if child_net < 0
                        else "CHILD_CLOSED_ZERO"
                    )
                )
            elif episode:
                category = "CHILD_BOUNDARY_EXCLUDED_CLOSED"
            elif state in {"CANCELLED", "EXPIRED", "CLOSED"}:
                category = "CHILD_ADMITTED_NO_FILL_TERMINAL"
            else:
                category = "CHILD_ADMITTED_NO_FILL_UNKNOWN_STATUS"
        counts[category] += 1
        rows.append(
            {
                "opportunity_key": list(key),
                "parent_resolved_winner_episode_id": parent_episode,
                "parent_admitted_episode_ids": parent_ids,
                "parent_resolved_winner_net_usdt": winner["net_reference_usdt"],
                "child_admitted_episode_ids": child_ids,
                "child_category": category,
                "child_resolved_cohort_net_usdt": child_net,
            }
        )
    ambiguous = (
        counts["AMBIGUOUS_PARENT_OPPORTUNITY"] + counts["AMBIGUOUS_CHILD_OPPORTUNITY"]
    )
    return {
        "basis": "RESOLVED_PARENT_WINNERS_ONLY_NOT_COMPLETE_WINDOW_RETENTION",
        "parent_resolved_winner_count": len(winners),
        "parent_resolved_winner_net_usdt": sum(
            (e["net_reference_usdt"] for e in winners), ZERO
        ),
        "category_counts": counts,
        "ambiguous_parent_winner_match_count": ambiguous,
        "ambiguous_admitted_opportunity_count": len(ambiguous_admitted),
        "ambiguous_admitted_opportunities": ambiguous_admitted,
        "ambiguity_scope": "ALL_SAVED_ADMITTED_OPPORTUNITIES_IN_BOTH_ARMS",
        "opportunities": rows,
        "absence_means": "NO_SAVED_ADMITTED_CHILD_ORDER_OR_EPISODE_NOT_PROOF_NO_SOURCE_SIGNAL",
        "open_unknown_and_boundary_excluded_child_values": None,
    }


def winner_damage(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    diagnostics = winner_diagnostics(parent, child)
    complete = parent["complete"] and child["complete"]
    available = complete and diagnostics["ambiguous_admitted_opportunity_count"] == 0
    return {
        "complete_pair_window": complete,
        "complete_window_metrics": (
            _complete_winner_metrics(parent, child) if available else None
        ),
        "closed_cohort_diagnostics": diagnostics,
        "unknown_reason": (
            None
            if available
            else (
                "INCOMPLETE_PAIR_WINDOW"
                if not complete
                else "AMBIGUOUS_CAUSAL_OPPORTUNITY"
            )
        ),
    }


def _complete_winner_metrics(parent: dict[str, Any], child: dict[str, Any]) -> Any:
    if not parent["complete"] or not child["complete"]:
        return None
    mapped = []
    for source in (parent, child):
        group = {}
        for episode in source["cohort"]:
            key = source["keys"][episode["episode_id"]]
            if key in group:
                raise ValueError("DUPLICATE_FIXED_REFERENCE_OPPORTUNITY")
            group[key] = episode["net_reference_usdt"]
        mapped.append(group)
    control, retest = mapped
    winners = {key: net for key, net in control.items() if net > 0}
    gain = sum(winners.values(), ZERO)
    observations = [retest.get(key, ZERO) for key in winners]
    retest_net = sum(observations, ZERO)
    return {
        "matching_basis": "SYMBOL_SIDE_CAUSAL_REFERENCE_ID_SESSION_END_PRIOR_DAY_BOX_EDGE",
        "not_an_identical_entry_claim": True,
        "parent_winners": len(winners),
        "child_positive_same_setup": sum(net > 0 for net in observations),
        "child_negative_same_setup": sum(net < 0 for net in observations),
        "child_zero_same_setup": sum(
            retest[key] == 0 for key in winners if key in retest
        ),
        "child_absent_same_setup": sum(key not in retest for key in winners),
        "parent_winner_net_usdt": gain,
        "child_net_on_parent_winning_setups_usdt": retest_net,
        "winner_net_delta_usdt": retest_net - gain,
        "positive_winner_profit_retention_pct": (
            D(100) * sum((max(ZERO, net) for net in observations), ZERO) / gain
            if gain
            else None
        ),
        "absent_retreats_are_opportunity_absence_not_observed_zero_trades": True,
    }


def audit_pair(
    results: dict[str, dict[str, Any]], bindings: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    check = Audit()
    first_contract = bindings["SR_CONTROL"]["continuous_contract"]
    eligible = {
        s["segment_id"]: s
        for s in first_contract["segments"]
        if s["eligible_by_data_only"]
    }
    check.equal("exact_two_segments", len(eligible), 2)
    segments: dict[str, Any] = {
        sid: {"models": {}, "winner_damage": {}} for sid in eligible
    }
    compact: dict[str, Any] = {}
    for label in LABELS:
        binding, result = bindings[label], results[label]
        check.equal(
            label + ".frozen_identity", binding["identity_key"], IDENTITIES[label]
        )
        check.equal(
            label + ".identity", result["identity_key"], binding["identity_key"]
        )
        check.equal(
            label + ".binding", result["binding_sha256"], binding["binding_sha256"]
        )
        check.equal(
            label + ".binding_content_hash",
            binding["binding_sha256"],
            digest({k: v for k, v in binding.items() if k != "binding_sha256"}),
        )
        check.equal(
            label + ".schema",
            result["schema"],
            "scalp7.measurement.segment_comparison_result.v1",
        )
        check.equal(label + ".one_full", result["full_execution_count"], 1)
        check.equal(label + ".performed", result["full_execution_performed"], True)
        check.equal(label + ".whole_nav", result["whole_period_nav"], None)
        check.equal(
            label + ".aggregation", result["cross_segment_nav_aggregation"], "FORBIDDEN"
        )
        check.equal(label + ".funding", result["funding_status"], "UNKNOWN_NOT_ZERO")
        check.equal(
            label + ".authority",
            result["authority"],
            {"live": "BLOCKED", "order": "BLOCKED", "promotion": False},
        )
        check.equal(label + ".contract", binding["continuous_contract"], first_contract)
        check.equal(
            label + ".result_segments", sorted(result["segments"]), sorted(eligible)
        )
        check.equal(
            label + ".binding_segments",
            sorted(binding["segment_bindings"]),
            sorted(eligible),
        )
        compact[label] = {}
        for sid, segment in eligible.items():
            audited, small = audit_child(
                result["segments"][sid],
                binding["segment_bindings"][sid],
                segment,
                first_contract,
                check,
                label + "." + sid,
            )
            segments[sid]["models"][label] = audited
            compact[label][sid] = small
    for sid in eligible:
        for scenario in ("1x", "2x"):
            segments[sid]["winner_damage"][scenario] = winner_damage(
                compact["SR_CONTROL"][sid][scenario],
                compact["SR_RETEST"][sid][scenario],
            )
    return {
        "schema": "g4.sr_continuous_two.independent_saved_arithmetic.v1",
        "status": "PASS" if check.error_count == 0 else "FAIL",
        "check_count": check.checks,
        "error_count": check.error_count,
        "errors": check.errors,
        "segments": segments,
        "completed_identity_count": 2,
        "observed_original_full_count": sum(
            results[label]["full_execution_count"] for label in LABELS
        ),
        "new_full_runs": 0,
        "market_data_loaded": False,
        "model_or_loader_imported": False,
        "funding_status": "UNKNOWN_NOT_ZERO",
        "whole_period_nav": None,
        "cross_segment_nav_aggregation": "FORBIDDEN",
        "profitability_pass": False,
        "g4_complete": False,
        "original25_complete": False,
        "limits": [
            "Saved fills and saved LAST prices only; not an independent market replay.",
            "Each segment is a separate flat research account; no continuous twelve-month equity or DD.",
            "Funding excluded; actual historical account Net remains unknown, never assumed zero.",
            "LAST-price DD is sampled, not intrabar, liquidation, mark-price or live account DD.",
            "Incomplete cohorts retain null complete-window Net/DD and null winner damage.",
            "Missing matched retest setup is opportunity absence, not an observed zero-return trade.",
            "Any duplicate admitted causal opportunity in either arm blocks complete winner metrics; all episode IDs remain recorded.",
        ],
    }


def substantive(report: dict[str, Any]) -> dict[str, Any]:
    result = {k: v for k, v in report.items() if k != "inputs"}
    result["inputs"] = {
        key: (
            {
                field: value
                for field, value in item.items()
                if field not in {"result_path", "result_storage_sha256", "freeze_path"}
            }
            if isinstance(item, dict)
            else item
        )
        for key, item in report["inputs"].items()
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for label in ("control", "retest"):
        parser.add_argument("--" + label + "-result", required=True, type=Path)
        parser.add_argument("--" + label + "-freeze", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-report", type=Path)
    args = parser.parse_args()
    bindings, results, inputs = {}, {}, {}
    for label, short in zip(LABELS, ("control", "retest")):
        path = getattr(args, short + "_result")
        freeze = getattr(args, short + "_freeze")
        results[label], raw, stored = load(path)
        bindings[label] = json.loads(freeze.read_text())
        inputs[label] = {
            "result_path": str(path.resolve()),
            "result_sha256": hashlib.sha256(raw).hexdigest(),
            "result_storage_sha256": hashlib.sha256(stored).hexdigest(),
            "freeze_path": str(freeze.resolve()),
            "freeze_sha256": sha(freeze),
        }
    report = audit_pair(results, bindings)
    report["inputs"] = {
        **inputs,
        "verifier_sha256": sha(Path(__file__)),
        "helper_sha256": sha(HELPER),
    }
    payload = (
        json.dumps(
            report, sort_keys=True, indent=2, allow_nan=False, default=core["serial"]
        )
        + "\n"
    )
    normalized = json.loads(payload)
    if args.expected_report is not None:
        if substantive(normalized) != substantive(
            json.loads(args.expected_report.read_text())
        ):
            raise ValueError("SAVED_ARITHMETIC_SUBSTANTIVE_PARITY_MISMATCH")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and args.output.read_text() != payload:
        raise FileExistsError("AUDIT_EXISTS_WITH_DIFFERENT_CONTENT")
    if not args.output.exists():
        with args.output.open("x") as handle:
            handle.write(payload)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "check_count", "error_count", "new_full_runs")
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
