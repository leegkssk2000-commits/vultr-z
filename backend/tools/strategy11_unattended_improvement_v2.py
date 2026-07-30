from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "STRATEGY11_UNATTENDED_IMPROVEMENT_V2"
REPLAY_VERSION = "STRATEGY11_UNATTENDED_IMPROVEMENT_REPLAY_V2"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
FAMILY_MAP = {
    "alpha_combo": "hybrid",
    "anchor_vwap_trend": "trend_following",
    "bb_revert": "mean_reversion",
    "break_and_continue": "breakout_momentum",
    "ema_ribbon_scalp": "trend_following",
    "fvg_revert": "market_structure",
    "grid_rebalance": "mean_reversion",
    "keltner_trend": "trend_following",
    "liquidity_sweep": "market_structure",
    "mfi_rsi_div": "mean_reversion",
    "obv_trend": "trend_following",
    "pivot_reversal": "market_structure",
    "range_fade": "mean_reversion",
    "rbreaker_like": "breakout_momentum",
    "rsi_swing_fail": "mean_reversion",
    "scalp_snap": "hybrid",
    "session_bias": "session_volatility",
    "squeeze_break": "breakout_momentum",
    "sr_levels": "market_structure",
    "supertrend_pullback": "trend_following",
    "trend_ma_macd": "trend_following",
    "trend_rider": "trend_following",
    "turtle_trend": "breakout_momentum",
    "vol_spike_fade": "session_volatility",
    "vwap_revert": "mean_reversion",
}
STRATEGIES = tuple(FAMILY_MAP)
LANES = (
    "A_ENTRY_LIVENESS_REPAIR",
    "B_COVERAGE_EXPANSION",
    "C_DISCOVERY_OPTIMIZATION",
    "D_QUALITY_OPTIMIZATION",
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def now_utc(value: str | None) -> dt.datetime:
    return parse_utc(value) if value else dt.datetime.now(dt.timezone.utc)


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def safety_assert(payload: Mapping[str, Any], prefix: str) -> None:
    for key, expected in SAFETY.items():
        if payload.get(key) != expected:
            raise ValueError(f"{prefix}_SAFETY_MISMATCH:{key}")


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("authority") != "RESEARCH_ONLY_NO_PROMOTION":
        raise ValueError("POLICY_AUTHORITY_INVALID")
    if set(policy.get("lane_thresholds") or {}) != set(LANES):
        raise ValueError("POLICY_LANES_INVALID")
    if int(policy.get("selection_rules", {}).get("max_candidates_per_strategy_cycle") or 0) != 2:
        raise ValueError("POLICY_CANDIDATE_LIMIT_INVALID")
    universe = list(map(str, policy.get("universe_symbols") or []))
    if len(universe) < 5 or len(universe) != len(set(universe)):
        raise ValueError("POLICY_SYMBOL_UNIVERSE_INVALID")
    exit_ids = [str(row.get("candidate_id")) for row in policy.get("exit_candidates", []) if isinstance(row, Mapping)]
    if not exit_ids or len(exit_ids) != len(set(exit_ids)):
        raise ValueError("POLICY_EXIT_CANDIDATES_INVALID")
    safety_assert(policy, "POLICY")


def validate_gate_catalog(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    if catalog.get("authority") != "RESEARCH_ONLY_NO_PROMOTION":
        raise ValueError("CATALOG_AUTHORITY_INVALID")
    rows = [dict(row) for row in catalog.get("candidates", []) if isinstance(row, Mapping)]
    ids = [str(row.get("candidate_id")) for row in rows]
    if len(rows) < 50 or len(ids) != len(set(ids)):
        raise ValueError("CATALOG_COUNT_OR_DUPLICATE_INVALID")
    for row in rows:
        if row.get("kind") != "GATE" or row.get("causal") is not True:
            raise ValueError(f"CATALOG_KIND_OR_CAUSAL_INVALID:{row.get('candidate_id')}")
        if not set(map(str, row.get("compatible_families") or [])).issubset(set(FAMILY_MAP.values())):
            raise ValueError(f"CATALOG_FAMILY_INVALID:{row.get('candidate_id')}")
    safety_assert(catalog, "CATALOG")
    return rows


def lane_for_trade_count(trade_count: int) -> str:
    if trade_count <= 0:
        return LANES[0]
    if trade_count <= 4:
        return LANES[1]
    if trade_count <= 9:
        return LANES[2]
    return LANES[3]


def control_by_strategy(baseline: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    rows = baseline.get("rows")
    if not isinstance(rows, list):
        raise ValueError("BASELINE_ROWS_REQUIRED")
    for summary in rows:
        if not isinstance(summary, Mapping) or not summary.get("strategy_id"):
            continue
        control = next(
            (
                dict(row)
                for row in summary.get("variants", [])
                if isinstance(row, Mapping) and row.get("variant_id") == "NO_CHANGE_CONTROL"
            ),
            None,
        )
        if control is None:
            raise ValueError(f"BASELINE_CONTROL_MISSING:{summary.get('strategy_id')}")
        result[str(summary["strategy_id"])] = control
    missing = sorted(set(STRATEGIES) - set(result))
    if missing:
        raise ValueError(f"BASELINE_STRATEGIES_MISSING:{','.join(missing)}")
    return result


def empty_ledger(policy: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "version": VERSION,
        "state": "INITIALIZED",
        "policy_sha256": stable_sha(policy),
        "gate_catalog_sha256": stable_sha(catalog),
        "cycle_index": 0,
        "rows": [
            {
                "strategy_id": strategy_id,
                "family": FAMILY_MAP[strategy_id],
                "lane": None,
                "tested_candidates": [],
                "pass_candidates": [],
                "discovery_hold_candidates": [],
                "hold_candidates": [],
                "rejected_candidates": [],
                "incumbent_snapshot": None,
                "last_cycle": 0,
            }
            for strategy_id in STRATEGIES
        ],
        **SAFETY,
    }


def normalize_previous(
    path: Path | None,
    policy: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    if path is None or not path.exists():
        return empty_ledger(policy, catalog)
    value = read_json(path)
    rows = value.get("rows")
    if not isinstance(rows, list):
        return empty_ledger(policy, catalog)
    observed = {str(row.get("strategy_id")): dict(row) for row in rows if isinstance(row, Mapping)}
    normalized = empty_ledger(policy, catalog)
    normalized["cycle_index"] = int(value.get("cycle_index") or 0)
    normalized["rows"] = []
    for strategy_id in STRATEGIES:
        row = observed.get(strategy_id, {})
        tested = list(row.get("tested_candidates") or [])
        normalized["rows"].append({
            "strategy_id": strategy_id,
            "family": FAMILY_MAP[strategy_id],
            "lane": row.get("lane"),
            "tested_candidates": tested,
            "pass_candidates": list(row.get("pass_candidates") or []),
            "discovery_hold_candidates": list(row.get("discovery_hold_candidates") or []),
            "hold_candidates": list(row.get("hold_candidates") or []),
            "rejected_candidates": list(row.get("rejected_candidates") or []),
            "incumbent_snapshot": row.get("incumbent_snapshot"),
            "last_cycle": int(row.get("last_cycle") or 0),
        })
    return normalized


def tested_ids(row: Mapping[str, Any]) -> set[str]:
    output: set[str] = set()
    for item in row.get("tested_candidates", []) or []:
        if isinstance(item, Mapping):
            output.add(str(item.get("candidate_id")))
        else:
            output.add(str(item))
    return output


def control_snapshot(control: Mapping[str, Any]) -> dict[str, Any]:
    config = dict(control.get("candidate_config") or {})
    return {
        "trade_count": int(control.get("trade_count") or 0),
        "win_rate_pct": control.get("win_rate_pct"),
        "net_return_pct_sum": control.get("net_return_pct_sum"),
        "net_profit_factor": control.get("net_profit_factor"),
        "payoff_ratio": control.get("payoff_ratio"),
        "max_drawdown_pct": control.get("max_drawdown_pct"),
        "positive_fresh_windows_pct": control.get("positive_fresh_windows_pct"),
        "candidate_config_sha256": control.get("candidate_config_sha256") or stable_sha(config),
        "candidate_config": config,
    }


def make_spec(
    *,
    candidate_id: str,
    kind: str,
    axis: str,
    lane: str,
    hypothesis: str,
    priority: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    spec = {
        "candidate_id": candidate_id,
        "kind": kind,
        "axis": axis,
        "lane": lane,
        "hypothesis": hypothesis,
        "priority": int(priority),
        **dict(payload),
    }
    spec["candidate_spec_sha256"] = stable_sha(spec)
    return spec


def dynamic_coverage_candidates(
    strategy_id: str,
    family: str,
    lane: str,
    control: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    config = dict(control.get("candidate_config") or {})
    gate = dict(config.get("gate") or {})
    surgery = config.get("surgery")
    symbols = tuple(map(str, config.get("symbols") or []))
    universe = tuple(map(str, policy.get("universe_symbols") or []))
    rows: list[dict[str, Any]] = []
    if set(symbols) != set(universe):
        rows.append(make_spec(
            candidate_id="COVERAGE_SYMBOL_ALL5",
            kind="SYMBOL_SET",
            axis="SYMBOL_COVERAGE",
            lane=lane,
            hypothesis="Expand the bounded OHLCV universe before adding another entry filter.",
            priority=10,
            payload={"symbols": list(universe)},
        ))
    if isinstance(surgery, Mapping):
        rows.append(make_spec(
            candidate_id="LIVENESS_DISABLE_SURGERY",
            kind="SURGERY_DISABLE",
            axis="SURGERY_BLOCKER",
            lane=lane,
            hypothesis="Test whether the existing post-signal surgery is suppressing otherwise valid entries.",
            priority=20,
            payload={},
        ))
    required = tuple(map(str, gate.get("required") or []))
    if required:
        rows.append(make_spec(
            candidate_id="LIVENESS_NO_EXTERNAL_GATE",
            kind="GATE",
            axis="ENTRY_CONTEXT_RELAX",
            lane=lane,
            hypothesis="Remove only the external context gate while preserving the canonical strategy and exit.",
            priority=30,
            payload={
                "gate": {
                    "gate_id": "BASE_LIVENESS",
                    "family": family,
                    "required": [],
                    "forbidden": [],
                    "description": "Lane A/B liveness probe: no external context gate",
                }
            },
        ))
    return rows


def gate_candidate_spec(candidate: Mapping[str, Any], family: str, lane: str) -> dict[str, Any]:
    candidate_id = str(candidate["candidate_id"])
    return make_spec(
        candidate_id=candidate_id,
        kind="GATE",
        axis=str(candidate["axis"]),
        lane=lane,
        hypothesis=f"Test {candidate.get('indicator_family')} as one isolated context axis.",
        priority=int(candidate.get("priority") or 999),
        payload={
            "gate": {
                "gate_id": candidate_id,
                "family": family,
                "required": list(candidate.get("required") or []),
                "forbidden": list(candidate.get("forbidden") or []),
                "description": (
                    f"{candidate.get('indicator_family')} bounded causal probe; "
                    f"components={','.join(map(str, candidate.get('components') or []))}"
                ),
            },
            "indicator_family": candidate.get("indicator_family"),
            "components": list(candidate.get("components") or []),
            "catalog_candidate_sha256": stable_sha(candidate),
        },
    )


def exit_candidate_specs(
    lane: str,
    control: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    base_exit = dict((control.get("candidate_config") or {}).get("exit") or {})
    rows: list[dict[str, Any]] = []
    for source in policy.get("exit_candidates", []) or []:
        if not isinstance(source, Mapping):
            continue
        changes = dict(source.get("changes") or {})
        if changes and all(base_exit.get(key) == value for key, value in changes.items()):
            continue
        rows.append(make_spec(
            candidate_id=str(source["candidate_id"]),
            kind="EXIT",
            axis=str(source.get("axis") or "EXIT_SHAPE"),
            lane=lane,
            hypothesis="Improve realized loss/payoff shape without reducing entry opportunity.",
            priority=int(source.get("priority") or 999),
            payload={"changes": changes},
        ))
    return rows


def choose_distinct(
    strategy_id: str,
    cycle: int,
    candidates: Iterable[dict[str, Any]],
    already_tested: set[str],
    max_count: int,
    axis_priority: list[str],
) -> list[dict[str, Any]]:
    pool = [row for row in candidates if str(row["candidate_id"]) not in already_tested]
    if not pool:
        return []
    axis_rank = {axis: index for index, axis in enumerate(axis_priority)}
    pool.sort(key=lambda row: (
        axis_rank.get(str(row["axis"]), len(axis_rank) + 1),
        int(row.get("priority") or 999),
        str(row["candidate_id"]),
    ))
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in pool:
        key = (axis_rank.get(str(row["axis"]), len(axis_rank) + 1), int(row.get("priority") or 999))
        grouped.setdefault(key, []).append(row)
    ordered: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group = grouped[key]
        offset = int(hashlib.sha256(f"{strategy_id}:{cycle}:{key}".encode()).hexdigest()[:8], 16) % len(group)
        ordered.extend(group[offset:] + group[:offset])
    selected: list[dict[str, Any]] = []
    axes: set[str] = set()
    for row in ordered:
        axis = str(row["axis"])
        if axis in axes:
            continue
        selected.append(row)
        axes.add(axis)
        if len(selected) >= max_count:
            break
    return selected


def lane_d_is_repair(control: Mapping[str, Any]) -> bool:
    return metric(control.get("net_return_pct_sum")) <= 0.0 or metric(control.get("net_profit_factor")) < 1.0


def candidate_pool(
    strategy_id: str,
    control: Mapping[str, Any],
    lane: str,
    gate_catalog: list[dict[str, Any]],
    policy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str], str]:
    family = FAMILY_MAP[strategy_id]
    coverage = dynamic_coverage_candidates(strategy_id, family, lane, control, policy)
    exits = exit_candidate_specs(lane, control, policy)
    gates = [
        gate_candidate_spec(row, family, lane)
        for row in gate_catalog
        if family in set(map(str, row.get("compatible_families") or []))
    ]
    rules = policy["selection_rules"]
    if lane == LANES[0]:
        pool = coverage
        priority = list(map(str, rules["lane_a_priority"]))
    elif lane == LANES[1]:
        pool = coverage + exits
        priority = list(map(str, rules["lane_b_priority"]))
    elif lane == LANES[2]:
        pool = coverage + exits + gates
        priority = list(map(str, rules["lane_c_priority"]))
    else:
        pool = exits + gates + coverage
        priority = list(map(str, rules["lane_d_repair_priority" if lane_d_is_repair(control) else "lane_d_positive_priority"]))
    config = dict(control.get("candidate_config") or {})
    gate = dict(config.get("gate") or {})
    if lane == LANES[0] and not coverage:
        diagnosis = "INTERNAL_SIGNAL_DORMANT_NO_SAFE_EXTERNAL_RELAXATION"
    elif int(control.get("trade_count") or 0) == 0 and not gate.get("required"):
        diagnosis = "INTERNAL_TRIGGER_OR_REGIME_DORMANT"
    elif int(control.get("trade_count") or 0) <= 4:
        diagnosis = "LOW_ENTRY_COVERAGE"
    elif lane == LANES[2]:
        diagnosis = "INSUFFICIENT_SAMPLE_FOR_STRICT_PARETO"
    else:
        diagnosis = "QUALITY_OR_LOSS_SHAPE_OPTIMIZATION"
    return pool, priority, diagnosis


def build_plan(args: argparse.Namespace) -> int:
    policy = read_json(Path(args.policy).resolve())
    catalog = read_json(Path(args.catalog).resolve())
    baseline = read_json(Path(args.baseline_final).resolve())
    validate_policy(policy)
    gate_catalog = validate_gate_catalog(catalog)
    controls = control_by_strategy(baseline)
    previous = normalize_previous(Path(args.previous_ledger).resolve() if args.previous_ledger else None, policy, catalog)
    cutoff = parse_utc(str(policy["continue_until_utc"]))
    current = now_utc(args.now_utc)
    cycle = int(previous.get("cycle_index") or 0) + 1
    previous_rows = {str(row["strategy_id"]): row for row in previous["rows"]}
    max_count = int(policy["selection_rules"]["max_candidates_per_strategy_cycle"])

    plan_rows: list[dict[str, Any]] = []
    lane_counts = {lane: 0 for lane in LANES}
    no_action: list[dict[str, Any]] = []
    lineage_changes: list[dict[str, Any]] = []
    if current < cutoff:
        for strategy_id in STRATEGIES:
            control = controls[strategy_id]
            lane = lane_for_trade_count(int(control.get("trade_count") or 0))
            lane_counts[lane] += 1
            prior_row = previous_rows[strategy_id]
            snapshot = control_snapshot(control)
            prior_snapshot = prior_row.get("incumbent_snapshot") if isinstance(prior_row.get("incumbent_snapshot"), Mapping) else None
            if prior_snapshot and prior_snapshot.get("candidate_config_sha256") != snapshot["candidate_config_sha256"]:
                lineage_changes.append({
                    "strategy_id": strategy_id,
                    "previous_candidate_config_sha256": prior_snapshot.get("candidate_config_sha256"),
                    "current_candidate_config_sha256": snapshot["candidate_config_sha256"],
                })
            pool, priority, diagnosis = candidate_pool(strategy_id, control, lane, gate_catalog, policy)
            selected = choose_distinct(
                strategy_id,
                cycle,
                pool,
                tested_ids(prior_row),
                max_count,
                priority,
            )
            if not selected:
                no_action.append({"strategy_id": strategy_id, "lane": lane, "diagnosis": diagnosis})
                continue
            plan_rows.append({
                "strategy_id": strategy_id,
                "strategy_alias": strategy_id,
                "family": FAMILY_MAP[strategy_id],
                "lane": lane,
                "diagnosis": diagnosis,
                "incumbent": snapshot,
                "candidate_ids": [str(row["candidate_id"]) for row in selected],
                "candidate_specs": {str(row["candidate_id"]): row for row in selected},
                "cycle_index": cycle,
                "selection_reason": "TRADE_COUNT_LANE_AWARE_CAUSAL_SEARCH",
                "falsification_test": (
                    "A/B parity, duplicate=0, lane-specific liveness/coverage/discovery/quality gates, "
                    "observed and 2x-cost/P95-funding/+1-bar stress."
                ),
                "promotion_authority": False,
            })

    state = "COMPLETE_CUTOFF_NO_NEW_REPLAY" if current >= cutoff else (
        "HOLD_INCUMBENT_LINEAGE_CHANGE" if lineage_changes else (
            "PASS_UNATTENDED_IMPROVEMENT_PLAN" if plan_rows else "COMPLETE_NO_SAFE_UNTESTED_AXIS"
        )
    )
    plan = {
        "schema_version": "2.0",
        "version": VERSION,
        "state": state,
        "cycle_index": cycle,
        "generated_at_utc": current.isoformat().replace("+00:00", "Z"),
        "continue_until_utc": cutoff.isoformat().replace("+00:00", "Z"),
        "policy_sha256": stable_sha(policy),
        "gate_catalog_sha256": stable_sha(catalog),
        "baseline_final_sha256": stable_sha(baseline),
        "strategy_count_total": len(STRATEGIES),
        "active_strategy_count": len(plan_rows),
        "candidate_count": sum(len(row["candidate_ids"]) for row in plan_rows),
        "active_strategy_ids": [row["strategy_id"] for row in plan_rows],
        "lane_counts": lane_counts,
        "no_action": no_action,
        "incumbent_lineage_changes": lineage_changes,
        "rows": plan_rows,
        "blind_cartesian_product_used": False,
        "max_candidates_per_strategy_cycle": max_count,
        "next": "LANE_AWARE_REPLAY_AND_LEDGER_UPDATE" if state == "PASS_UNATTENDED_IMPROVEMENT_PLAN" else "HOLD_OR_WAIT",
        **SAFETY,
    }
    previous["state"] = "PLAN_READY" if state == "PASS_UNATTENDED_IMPROVEMENT_PLAN" else state
    previous["cycle_index"] = cycle
    previous["policy_sha256"] = stable_sha(policy)
    previous["gate_catalog_sha256"] = stable_sha(catalog)
    previous["baseline_final_sha256"] = stable_sha(baseline)
    previous["last_plan_sha256"] = stable_sha(plan)
    previous["last_generated_at_utc"] = plan["generated_at_utc"]
    previous.update(SAFETY)

    coverage = {
        "schema_version": "2.0",
        "version": VERSION,
        "state": state,
        "lane_counts": lane_counts,
        "active_strategy_count": len(plan_rows),
        "scheduled_candidate_count": plan["candidate_count"],
        "tested_strategy_candidate_pairs": sum(len(tested_ids(row)) for row in previous["rows"]),
        "no_action_count": len(no_action),
        "incumbent_lineage_change_count": len(lineage_changes),
        "gate_only_search": False,
        "entry_liveness_repair_enabled": True,
        "coverage_expansion_enabled": True,
        "exit_optimization_enabled": True,
        "context_gate_optimization_enabled": True,
        **SAFETY,
    }
    out = Path(args.out).resolve()
    write_json(out / "plan.json", plan)
    write_json(out / "search_ledger.json", previous)
    write_json(out / "coverage.json", coverage)
    print(json.dumps({
        "state": state,
        "cycle": cycle,
        "strategies": len(plan_rows),
        "candidates": plan["candidate_count"],
        "lane_counts": lane_counts,
        "lineage_changes": len(lineage_changes),
    }, sort_keys=True))
    return 0 if not lineage_changes else 3


def hard_risk_ok(variant: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    normal = variant.get("loss_metrics") if isinstance(variant.get("loss_metrics"), Mapping) else {}
    stress = variant.get("stress_2x_p95_plus_one", {})
    stress_loss = stress.get("loss_metrics") if isinstance(stress, Mapping) and isinstance(stress.get("loss_metrics"), Mapping) else {}
    normal_worst = metric(normal.get("normal_worst_net_loss_R", normal.get("worst_net_loss_R")), -math.inf)
    stress_worst = metric(stress_loss.get("normal_worst_net_loss_R", stress_loss.get("worst_net_loss_R")), -math.inf)
    rules = policy["classification"]
    return (
        normal_worst >= float(rules["normal_worst_net_loss_R_min"])
        and stress_worst >= float(rules["stress_worst_net_loss_R_min"])
        and int(normal.get("loss_cap_breach_count") or 0) == 0
        and int(stress_loss.get("loss_cap_breach_count") or 0) == 0
    )


def deltas(variant: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, float]:
    return {
        "trade_count": metric(variant.get("trade_count")) - metric(control.get("trade_count")),
        "net": metric(variant.get("net_return_pct_sum")) - metric(control.get("net_return_pct_sum")),
        "pf": metric(variant.get("net_profit_factor")) - metric(control.get("net_profit_factor")),
        "payoff": metric(variant.get("payoff_ratio")) - metric(control.get("payoff_ratio")),
        "dd": metric(variant.get("max_drawdown_pct")) - metric(control.get("max_drawdown_pct")),
    }


def improved_primary(delta: Mapping[str, float]) -> int:
    return sum(delta[key] > 0.0 for key in ("net", "pf", "payoff")) + int(delta["dd"] < 0.0)


def improvement_score(lane: str, variant: Mapping[str, Any], control: Mapping[str, Any]) -> float:
    delta = deltas(variant, control)
    if lane in LANES[:2]:
        return delta["trade_count"] * 10.0 + delta["net"] + max(0.0, -delta["dd"])
    return delta["net"] + 0.75 * delta["pf"] + 0.5 * delta["payoff"] - 0.75 * max(0.0, delta["dd"])


def classify_variant(
    lane: str,
    variant: Mapping[str, Any],
    control: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    parity = variant.get("parity") if isinstance(variant.get("parity"), Mapping) else {}
    if parity.get("state") != "PASS" or int(parity.get("duplicate_trade_count") or 0) != 0:
        return "HOLD_PARITY_OR_DUPLICATE", {"hard_risk_ok": False}
    trade_count = int(variant.get("trade_count") or 0)
    control_trades = int(control.get("trade_count") or 0)
    delta = deltas(variant, control)
    primary = improved_primary(delta)
    risk_ok = hard_risk_ok(variant, policy)
    windows = metric(variant.get("positive_fresh_windows_pct"))
    ladder = variant.get("ladder_check") if isinstance(variant.get("ladder_check"), Mapping) else {}
    retention = metric(ladder.get("trade_retention_pct"), trade_count / max(1, control_trades) * 100.0)
    details = {
        "hard_risk_ok": risk_ok,
        "deltas": delta,
        "improved_primary_metrics": primary,
        "trade_retention_pct": retention,
        "positive_fresh_windows_pct": windows,
        "retest_required_on_new_data": True,
    }
    rules = policy["classification"]
    if lane == LANES[0]:
        if trade_count == 0:
            return "HOLD_LIVENESS_ZERO_TRADES", details
        if not risk_ok:
            return "REJECT_LIVENESS_RISK", details
        if windows >= float(rules["lane_a_positive_windows_pct_min"]):
            return "PASS_LIVENESS_REPAIR_RESEARCH", details
        return "HOLD_LIVENESS_RESTORED_WEAK_BREADTH", details
    if lane == LANES[1]:
        if not risk_ok:
            return "REJECT_COVERAGE_RISK", details
        if trade_count <= control_trades:
            return "HOLD_COVERAGE_NO_GAIN", details
        if (
            trade_count >= int(rules["lane_b_target_trade_count"])
            and trade_count - control_trades >= int(rules["lane_b_min_trade_gain"])
            and delta["net"] >= -float(rules["lane_b_max_net_degradation_pct_points"])
        ):
            return "PASS_COVERAGE_EXPANSION_RESEARCH", details
        return "HOLD_COVERAGE_IMPROVED", details
    if lane == LANES[2]:
        if trade_count == 0:
            return "REJECT_DISCOVERY_ZERO_TRADES", details
        if not risk_ok:
            return "REJECT_DISCOVERY_RISK", details
        if trade_count >= int(rules["lane_c_quality_trade_count"]) and ladder.get("research_pass") is True:
            return "PASS_DISCOVERY_TO_QUALITY_RESEARCH", details
        if primary >= int(rules["lane_c_improved_primary_metrics_min"]):
            return "HOLD_DISCOVERY_IMPROVED", details
        return "HOLD_DISCOVERY_NO_EDGE", details
    if trade_count == 0:
        return "REJECT_QUALITY_ZERO_TRADES", details
    if ladder.get("research_pass") is True:
        return "PASS_QUALITY_RESEARCH", details
    if not risk_ok:
        return "REJECT_QUALITY_RISK", details
    if retention < 50.0:
        return "REJECT_QUALITY_RETENTION", details
    if (
        primary >= int(rules["lane_d_near_pareto_improved_metrics_min"])
        and retention >= float(rules["lane_d_near_pareto_retention_pct_min"])
        and delta["net"] >= -float(rules["lane_d_near_pareto_max_net_degradation_pct_points"])
    ):
        return "HOLD_QUALITY_NEAR_PARETO", details
    return "HOLD_QUALITY_NO_EDGE", details


def find_strategy_summaries(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in root.rglob("summary.json"):
        try:
            row = read_json(path)
        except Exception:
            continue
        if row.get("version") == REPLAY_VERSION and row.get("strategy_id"):
            result[str(row["strategy_id"])] = row
    return result


def bucket_for(status: str) -> str:
    if status.startswith("PASS_"):
        return "pass_candidates"
    if status.startswith("REJECT_"):
        return "rejected_candidates"
    if "IMPROVED" in status or "NEAR_PARETO" in status or "RESTORED" in status:
        return "discovery_hold_candidates"
    return "hold_candidates"


def update_ledger(args: argparse.Namespace) -> int:
    policy = read_json(Path(args.policy).resolve())
    validate_policy(policy)
    plan = read_json(Path(args.plan).resolve())
    ledger = read_json(Path(args.ledger).resolve())
    summaries = find_strategy_summaries(Path(args.replay_root).resolve())
    rows_by_id = {str(row["strategy_id"]): row for row in ledger["rows"]}
    tested_rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    survivors: list[dict[str, Any]] = []
    improved_holds: list[dict[str, Any]] = []
    lane_transitions: list[dict[str, Any]] = []

    for plan_row in plan.get("rows", []):
        strategy_id = str(plan_row["strategy_id"])
        summary = summaries.get(strategy_id)
        if summary is None:
            missing.append({"strategy_id": strategy_id, "reason": "REPLAY_SUMMARY_MISSING"})
            continue
        variants = {
            str(row.get("variant_id")): row
            for row in summary.get("variants", [])
            if isinstance(row, Mapping)
        }
        control = variants.get("NO_CHANGE_CONTROL")
        if control is None:
            missing.append({"strategy_id": strategy_id, "reason": "CONTROL_VARIANT_MISSING"})
            continue
        lane = str(plan_row["lane"])
        ledger_row = rows_by_id[strategy_id]
        ledger_row["lane"] = lane
        ledger_row["incumbent_snapshot"] = control_snapshot(control)
        observed_ids = tested_ids(ledger_row)
        for candidate_id in plan_row["candidate_ids"]:
            candidate_id = str(candidate_id)
            variant = variants.get(candidate_id)
            if variant is None:
                missing.append({"strategy_id": strategy_id, "candidate_id": candidate_id, "reason": "VARIANT_MISSING"})
                continue
            status, classification = classify_variant(lane, variant, control, policy)
            spec = plan_row["candidate_specs"][candidate_id]
            next_lane = lane_for_trade_count(int(variant.get("trade_count") or 0))
            record = {
                "cycle_index": int(plan["cycle_index"]),
                "strategy_id": strategy_id,
                "lane": lane,
                "next_lane_if_selected": next_lane,
                "candidate_id": candidate_id,
                "candidate_spec_sha256": spec["candidate_spec_sha256"],
                "axis": spec["axis"],
                "kind": spec["kind"],
                "status": status,
                "improvement_score": improvement_score(lane, variant, control),
                "trade_count": int(variant.get("trade_count") or 0),
                "win_rate_pct": variant.get("win_rate_pct"),
                "net_return_pct_sum": variant.get("net_return_pct_sum"),
                "net_profit_factor": variant.get("net_profit_factor"),
                "payoff_ratio": variant.get("payoff_ratio"),
                "max_drawdown_pct": variant.get("max_drawdown_pct"),
                "positive_fresh_windows_pct": variant.get("positive_fresh_windows_pct"),
                "control": control_snapshot(control),
                "classification": classification,
                "ladder_check": variant.get("ladder_check"),
                "candidate_config_sha256": variant.get("candidate_config_sha256"),
            }
            if candidate_id not in observed_ids:
                ledger_row["tested_candidates"].append(record)
                observed_ids.add(candidate_id)
            bucket = bucket_for(status)
            if candidate_id not in set(map(str, ledger_row[bucket])):
                ledger_row[bucket].append(candidate_id)
            ledger_row["last_cycle"] = int(plan["cycle_index"])
            tested_rows.append(record)
            if status.startswith("PASS_"):
                survivors.append(record)
            elif bucket == "discovery_hold_candidates":
                improved_holds.append(record)
            if next_lane != lane and not status.startswith("REJECT_"):
                lane_transitions.append({
                    "strategy_id": strategy_id,
                    "candidate_id": candidate_id,
                    "from_lane": lane,
                    "to_lane": next_lane,
                    "status": status,
                })

    rank_key = lambda row: (
        metric(row.get("improvement_score"), -math.inf),
        metric(row.get("net_return_pct_sum"), -math.inf),
        metric(row.get("net_profit_factor"), -math.inf),
        -metric(row.get("max_drawdown_pct"), math.inf),
    )
    survivors.sort(key=rank_key, reverse=True)
    improved_holds.sort(key=rank_key, reverse=True)
    ledger["state"] = "PASS_UNATTENDED_IMPROVEMENT_CYCLE" if not missing else "HOLD_INCOMPLETE_REPLAY"
    ledger["cycle_index"] = int(plan["cycle_index"])
    ledger["last_cycle_tested_count"] = len(tested_rows)
    ledger["last_cycle_missing_count"] = len(missing)
    ledger["last_cycle_survivor_count"] = len(survivors)
    ledger["last_cycle_improved_hold_count"] = len(improved_holds)
    ledger["last_cycle_plan_sha256"] = stable_sha(plan)
    ledger.update(SAFETY)

    all_tested = [
        item for row in ledger["rows"] for item in row.get("tested_candidates", [])
        if isinstance(item, Mapping)
    ]
    status_counts: dict[str, int] = {}
    lane_counts: dict[str, int] = {}
    for row in all_tested:
        status = str(row.get("status"))
        lane = str(row.get("lane"))
        status_counts[status] = status_counts.get(status, 0) + 1
        lane_counts[lane] = lane_counts.get(lane, 0) + 1

    top_candidates = sorted(survivors + improved_holds, key=rank_key, reverse=True)[:10]
    final = {
        "schema_version": "2.0",
        "version": VERSION,
        "state": ledger["state"],
        "cycle_index": int(plan["cycle_index"]),
        "tested_count_this_cycle": len(tested_rows),
        "missing_count": len(missing),
        "research_survivor_count": len(survivors),
        "improved_hold_count": len(improved_holds),
        "top_research_survivors": survivors[:5],
        "top_improved_holds": improved_holds[:10],
        "top_improvement_candidates": top_candidates,
        "lane_transitions": lane_transitions,
        "missing": missing,
        "status_counts_cumulative": status_counts,
        "lane_test_counts_cumulative": lane_counts,
        "tested_strategy_candidate_pairs_cumulative": len(all_tested),
        "continue_until_utc": plan["continue_until_utc"],
        "w1_confirmation_required": True,
        "canonical_mutated": False,
        "registry_mutated": False,
        "next": "NEXT_LANE_AWARE_CAUSAL_CYCLE" if not missing else "RETRY_MISSING_ONLY",
        **SAFETY,
    }
    out = Path(args.out).resolve()
    write_json(out / "search_ledger.json", ledger)
    write_json(out / "final.json", final)
    write_json(out / "cycle_results.json", {
        "state": final["state"],
        "rows": tested_rows,
        "missing": missing,
        "lane_transitions": lane_transitions,
        **SAFETY,
    })
    print(json.dumps({
        "state": final["state"],
        "tested": len(tested_rows),
        "survivors": len(survivors),
        "improved_holds": len(improved_holds),
        "missing": len(missing),
    }, sort_keys=True))
    return 0 if not missing else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("plan", "update"), required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--catalog")
    parser.add_argument("--baseline-final")
    parser.add_argument("--previous-ledger")
    parser.add_argument("--now-utc")
    parser.add_argument("--plan")
    parser.add_argument("--ledger")
    parser.add_argument("--replay-root")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.mode == "plan":
        if not args.catalog or not args.baseline_final:
            raise SystemExit("--catalog --baseline-final required")
        return build_plan(args)
    if not all((args.plan, args.ledger, args.replay_root)):
        raise SystemExit("--plan --ledger --replay-root required")
    return update_ledger(args)


if __name__ == "__main__":
    raise SystemExit(main())
