#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7 as v7
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil
from backend.research.prep import strategy_material_grade_v1 as material

SCHEMA = "zel.a1_top5_evolutionary_synthesis.v7_1"
TERMINAL_DEV_STATES = {"PASS_DEVELOPMENT_ECONOMICS", "FAIL_DEVELOPMENT_ECONOMICS", "FAIL_INSUFFICIENT_EVENTS"}


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _extract_attempted(prior: Mapping[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}

    def add(sid: Any, rows: Any) -> None:
        if not sid or not isinstance(rows, list):
            return
        bucket = out.setdefault(str(sid), set())
        bucket.update(str(x) for x in rows if str(x))

    root = prior.get("economic_attempted_axes")
    if isinstance(root, Mapping):
        for sid, rows in root.items():
            add(sid, rows)

    by_strategy = prior.get("by_strategy")
    if isinstance(by_strategy, Mapping):
        for sid, raw in by_strategy.items():
            if not isinstance(raw, Mapping):
                continue
            add(sid, raw.get("economic_attempted_axes"))
            add(sid, raw.get("economically_tested_axes_this_run"))

    for raw in prior.get("candidate_donor_attribution") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = raw.get("host_strategy_id")
        axis = raw.get("changed_axis")
        if sid and axis:
            out.setdefault(str(sid), set()).add(str(axis))
    return out


def _prior_attempted_fixed() -> dict[str, set[str]]:
    prior = v7._read(v7.LATEST)
    return _extract_attempted(prior)


def _build_nursery_queue(material_result: Mapping[str, Any], active_hosts: set[str]) -> list[dict[str, Any]]:
    grade_rank = {"B": 0, "C": 1, "D": 2, "A": 3, "S": 4, "HOLD": 5}
    allowed_dispositions = {"SYNTHESIS_UPGRADE", "SYNTHESIS_EXPERIMENTAL", "DISCARD_PENDING_ABLATION"}
    rows: list[dict[str, Any]] = []
    for raw in material_result.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        if not sid or sid in active_hosts:
            continue
        disposition = str(raw.get("material_disposition") or "")
        if disposition not in allowed_dispositions:
            continue
        quality = raw.get("quality") if isinstance(raw.get("quality"), Mapping) else {}
        rows.append({
            "strategy_id": sid,
            "material_grade": raw.get("material_grade"),
            "material_disposition": disposition,
            "upgrade_axis": raw.get("upgrade_axis"),
            "target_grade": raw.get("target_grade"),
            "structural_diversity_prior": raw.get("structural_diversity_prior"),
            "completed_trades": quality.get("completed_trades"),
            "positive_gross": quality.get("positive_gross"),
            "positive_net": quality.get("positive_net"),
            "net_expectancy_bps": quality.get("net_expectancy_bps"),
            "risk_efficiency_net_pnl_over_dd": quality.get("risk_efficiency_net_pnl_over_dd"),
            "nursery_rule": "UPGRADE_MATERIAL_FIRST_THEN_REENTER_AS_DONOR;NO_NUMERIC_THRESHOLD_COPY",
        })

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        grade = str(row.get("material_grade") or "HOLD")
        positive_gross = bool(row.get("positive_gross"))
        diversity = float(row.get("structural_diversity_prior") or 0.0)
        trades = int(row.get("completed_trades") or 0)
        return (grade_rank.get(grade, 9), 0 if positive_gross else 1, -diversity, -trades, str(row.get("strategy_id")))

    rows.sort(key=key)
    return rows[:10]


def _host_exhaustion_routes(result: Mapping[str, Any]) -> dict[str, str]:
    routes: dict[str, str] = {}
    by_strategy = result.get("by_strategy")
    if not isinstance(by_strategy, Mapping):
        return routes
    for sid, raw in by_strategy.items():
        if not isinstance(raw, Mapping):
            continue
        passes = int(raw.get("development_economic_pass_count") or 0)
        remaining = int(raw.get("remaining_axis_count") or 0)
        if passes > 0:
            routes[str(sid)] = "INDEPENDENT_OOS_WALK_FORWARD_STRESS"
        elif remaining <= 0:
            routes[str(sid)] = "DONOR_NURSERY_UPGRADE_OR_NEW_EXTERNAL_MECHANISM"
        else:
            routes[str(sid)] = "CONTINUE_UNTRIED_DISTINCT_DONOR_AXIS"
    return routes


def _material_index(material_result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("strategy_id")): row
        for row in (material_result.get("rows") or [])
        if isinstance(row, Mapping) and row.get("strategy_id")
    }


def _league_index(league: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("strategy_id")): row
        for row in (league.get("rows") or [])
        if isinstance(row, Mapping) and row.get("strategy_id")
    }


def _dev_rows(receipt: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for key in ("initial_development_economics", "second_step_development_economics"):
        block = receipt.get(key)
        if not isinstance(block, Mapping):
            continue
        for row in block.get("rows") or []:
            if isinstance(row, Mapping) and row.get("candidate_id"):
                out[str(row["candidate_id"])] = row
    return out


def _metric_snapshot(raw: Mapping[str, Any] | None, *, development: bool) -> dict[str, float | int | None]:
    if not raw:
        return {
            "trades": None,
            "net_pnl_bps": None,
            "net_expectancy_bps": None,
            "profit_factor": None,
            "drawdown_bps": None,
            "win_rate": None,
        }
    metrics = raw.get("metrics") if development and isinstance(raw.get("metrics"), Mapping) else v7._metrics(raw)
    trades = metrics.get("trades") if development else metrics.get("completed_trades")
    if trades is None:
        trades = metrics.get("completed_trades") if development else metrics.get("trades")
    try:
        trade_value: int | None = int(trades) if trades is not None else None
    except (TypeError, ValueError):
        trade_value = None
    return {
        "trades": trade_value,
        "net_pnl_bps": _finite(metrics.get("net_pnl_bps")),
        "net_expectancy_bps": _finite(metrics.get("net_expectancy_bps")),
        "profit_factor": _finite(metrics.get("profit_factor")),
        "drawdown_bps": _finite(metrics.get("drawdown_bps")),
        "win_rate": _finite(metrics.get("win_rate")),
    }


def _delta(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, float | int | None]:
    def sub(key: str) -> float | None:
        a = _finite(child.get(key)); b = _finite(parent.get(key))
        return (a - b) if a is not None and b is not None else None

    p_trades = parent.get("trades"); c_trades = child.get("trades")
    trade_delta = int(c_trades) - int(p_trades) if isinstance(c_trades, int) and isinstance(p_trades, int) else None
    wr = sub("win_rate")
    parent_dd = _finite(parent.get("drawdown_bps")); child_dd = _finite(child.get("drawdown_bps"))
    return {
        "trades_delta": trade_delta,
        "net_pnl_delta_bps": sub("net_pnl_bps"),
        "net_expectancy_delta_bps_per_trade": sub("net_expectancy_bps"),
        "profit_factor_delta": sub("profit_factor"),
        "drawdown_improvement_bps": (parent_dd - child_dd) if parent_dd is not None and child_dd is not None else None,
        "win_rate_delta_pp": (wr * 100.0) if wr is not None else None,
    }


def _effect_channels(delta: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    definitions = [
        ("NET_PNL", "net_pnl_delta_bps", "bps", 1.0),
        ("EXPECTANCY", "net_expectancy_delta_bps_per_trade", "bps/trade", 1.0),
        ("PROFIT_FACTOR", "profit_factor_delta", "ratio", 1.0),
        ("DRAWDOWN", "drawdown_improvement_bps", "bps", 1.0),
        ("WIN_RATE", "win_rate_delta_pp", "pp", 1.0),
        ("SAMPLE_DENSITY", "trades_delta", "trades", 1.0),
    ]
    helped: list[dict[str, Any]] = []
    hurt: list[dict[str, Any]] = []
    for channel, key, unit, direction in definitions:
        value = _finite(delta.get(key))
        if value is None or value == 0:
            continue
        row = {"channel": channel, "metric": key, "delta": value, "unit": unit}
        (helped if value * direction > 0 else hurt).append(row)
    return helped, hurt


def _same_baseline_verified(candidate: Mapping[str, Any], dev: Mapping[str, Any]) -> bool:
    keys = ("same_baseline_ab_verified", "same_baseline_ab_pass", "exact_parent_ab_verified")
    return any(candidate.get(k) is True or dev.get(k) is True for k in keys)


def _build_contribution_rows(
    receipt: Mapping[str, Any],
    league: Mapping[str, Any],
    material_result: Mapping[str, Any],
    *,
    source_receipt: str,
) -> list[dict[str, Any]]:
    hosts = _league_index(league)
    materials = _material_index(material_result)
    dev_rows = _dev_rows(receipt)
    candidates: dict[str, Mapping[str, Any]] = {}
    for key in ("initial_candidates", "second_step_candidates"):
        for row in receipt.get(key) or []:
            if isinstance(row, Mapping) and row.get("candidate_id"):
                candidates[str(row["candidate_id"])] = row

    out: list[dict[str, Any]] = []
    for attr in receipt.get("candidate_donor_attribution") or []:
        if not isinstance(attr, Mapping):
            continue
        cid = str(attr.get("candidate_id") or "")
        host = str(attr.get("host_strategy_id") or "")
        donor = str(attr.get("donor_strategy_id") or "")
        if not cid or not host or not donor:
            continue
        candidate = candidates.get(cid) or {}
        dev = dev_rows.get(cid) or {}
        parent_metrics = _metric_snapshot(hosts.get(host), development=False)
        child_metrics = _metric_snapshot(dev, development=True)
        observed_delta = _delta(parent_metrics, child_metrics)
        helped, hurt = _effect_channels(observed_delta)
        same_baseline = _same_baseline_verified(candidate, dev)
        terminal = str(dev.get("state") or "") in TERMINAL_DEV_STATES
        passed = bool(dev.get("economic_pass"))
        mat = materials.get(donor) or {}
        quality = mat.get("quality") if isinstance(mat.get("quality"), Mapping) else {}
        confidence = (
            "CAUSAL_MARGINAL_READY" if same_baseline and terminal else
            "DEVELOPMENT_ECONOMIC_SIGNAL" if terminal else
            "NOT_ECONOMICALLY_EVALUATED"
        )
        out.append({
            "candidate_id": cid,
            "host_strategy_id": host,
            "donor_strategy_id": donor,
            "donor_gene": attr.get("donor_gene"),
            "donor_tier": attr.get("donor_tier"),
            "changed_axis": attr.get("changed_axis"),
            "development_state": dev.get("state"),
            "development_economic_pass": passed,
            "terminal_economic_evaluation": terminal,
            "parent_reference_metrics": parent_metrics,
            "child_development_metrics": child_metrics,
            "observed_delta": observed_delta,
            "helped_channels": helped,
            "hurt_channels": hurt,
            "helped_channel_count": len(helped),
            "hurt_channel_count": len(hurt),
            "same_baseline_ab_verified": same_baseline,
            "causal_marginal_claim_allowed": bool(same_baseline and terminal),
            "delta_validity": "CAUSAL_ONE_AXIS_ABLATION" if same_baseline else "DIRECTIONAL_CROSS_SCOPE_ONLY_UNTIL_SAME_BASELINE_AB",
            "confidence": confidence,
            "donor_material_grade": mat.get("material_grade"),
            "donor_material_disposition": mat.get("material_disposition"),
            "donor_material_upgrade_axis": mat.get("upgrade_axis"),
            "donor_standalone_quality": {
                "completed_trades": quality.get("completed_trades"),
                "positive_gross": quality.get("positive_gross"),
                "positive_net": quality.get("positive_net"),
                "net_expectancy_bps": quality.get("net_expectancy_bps"),
                "risk_efficiency_net_pnl_over_dd": quality.get("risk_efficiency_net_pnl_over_dd"),
            },
            "source_receipt": source_receipt,
            "promotion_ready": False,
        })
    return out


def _merge_contribution_ledger(*blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for block in blocks:
        for row in block:
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("candidate_id") or "")
            if key:
                merged[key] = dict(row)
    return [merged[k] for k in sorted(merged)]


def _aggregate_donor_contribution(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in ledger:
        donor = str(row.get("donor_strategy_id") or "")
        gene = str(row.get("donor_gene") or "")
        if donor:
            groups.setdefault((donor, gene), []).append(row)

    def avg(rows: list[dict[str, Any]], key: str) -> float | None:
        values = [_finite((x.get("observed_delta") or {}).get(key)) for x in rows]
        clean = [x for x in values if x is not None]
        return sum(clean) / len(clean) if clean else None

    out: list[dict[str, Any]] = []
    for (donor, gene), rows in groups.items():
        terminal = [x for x in rows if x.get("terminal_economic_evaluation")]
        passes = [x for x in terminal if x.get("development_economic_pass")]
        causal = [x for x in terminal if x.get("causal_marginal_claim_allowed")]
        channels: dict[str, dict[str, int]] = {}
        for row in rows:
            for bucket, label in ((row.get("helped_channels") or [], "help"), (row.get("hurt_channels") or [], "hurt")):
                for item in bucket:
                    name = str(item.get("channel") or "")
                    if not name:
                        continue
                    channels.setdefault(name, {"help": 0, "hurt": 0})[label] += 1
        pass_rate = (len(passes) / len(terminal)) if terminal else None
        route = "KEEP_DONOR_AND_VALIDATE_OOS" if passes else "NURSERY_UPGRADE_OR_DISTINCT_HOST_TEST"
        out.append({
            "donor_strategy_id": donor,
            "donor_gene": gene,
            "attempt_count": len(rows),
            "terminal_attempt_count": len(terminal),
            "development_pass_count": len(passes),
            "development_pass_rate": pass_rate,
            "causal_marginal_confirmed_count": len(causal),
            "host_count": len({str(x.get("host_strategy_id") or "") for x in rows}),
            "effect_channel_counts": channels,
            "average_observed_delta_directional_only": {
                "net_pnl_delta_bps": avg(rows, "net_pnl_delta_bps"),
                "net_expectancy_delta_bps_per_trade": avg(rows, "net_expectancy_delta_bps_per_trade"),
                "profit_factor_delta": avg(rows, "profit_factor_delta"),
                "drawdown_improvement_bps": avg(rows, "drawdown_improvement_bps"),
                "win_rate_delta_pp": avg(rows, "win_rate_delta_pp"),
                "trades_delta": avg(rows, "trades_delta"),
            },
            "material_grade": next((x.get("donor_material_grade") for x in reversed(rows) if x.get("donor_material_grade")), None),
            "material_disposition": next((x.get("donor_material_disposition") for x in reversed(rows) if x.get("donor_material_disposition")), None),
            "next_route": route,
            "numeric_delta_is_causal_only_when_same_baseline_ab_verified": True,
        })
    out.sort(key=lambda x: (-int(x["development_pass_count"]), -int(x["terminal_attempt_count"]), str(x["donor_strategy_id"])))
    return out


def run(output: Path) -> dict[str, Any]:
    prior_receipt = v7._read(v7.LATEST)
    original = v7._prior_attempted
    try:
        v7._prior_attempted = _prior_attempted_fixed
        result = dict(v7.run(output))
    finally:
        v7._prior_attempted = original

    attempted = _extract_attempted(prior_receipt)
    active_hosts = {str(x) for x in (result.get("active_strategy_ids") or result.get("performance_top5_hosts") or []) if str(x)}
    material_result = material.evaluate(
        material.read(material.LEDGER),
        material.read(material.INVENTORY),
        material.read(material.SSOT),
    )
    nursery = _build_nursery_queue(material_result, active_hosts)
    league = v7._read(v7.LEAGUE)
    prior_rows = _build_contribution_rows(
        prior_receipt,
        league,
        material_result,
        source_receipt=str(prior_receipt.get("receipt_sha256") or "PRIOR_UNSEALED"),
    ) if prior_receipt else []
    existing_ledger = [dict(x) for x in (prior_receipt.get("donor_contribution_ledger") or []) if isinstance(x, Mapping)]
    current_rows = _build_contribution_rows(
        result,
        league,
        material_result,
        source_receipt="CURRENT_RUN_PRE_RECEIPT",
    )
    contribution_ledger = _merge_contribution_ledger(existing_ledger, prior_rows, current_rows)
    donor_summary = _aggregate_donor_contribution(contribution_ledger)

    result["schema_version"] = SCHEMA
    result["stable_donor_host_attempt_history"] = True
    result["prior_attempted_gene_pairs"] = {sid: sorted(rows) for sid, rows in sorted(attempted.items())}
    result["failed_gene_pair_retest_same_axis_allowed"] = False
    result["synthesis_mode"] = "TOP5_HOST_EVOLUTION_PLUS_DONOR_NURSERY"
    result["donor_nursery_enabled"] = True
    result["donor_nursery_strategy_count"] = len(nursery)
    result["donor_nursery_queue"] = nursery
    result["host_exhaustion_routes"] = _host_exhaustion_routes(result)
    result["donor_contribution_attribution_enabled"] = True
    result["donor_contribution_method"] = "ONE_AXIS_DONOR_GENE_ATTRIBUTION_WITH_STABLE_HISTORY"
    result["donor_contribution_ledger"] = contribution_ledger
    result["donor_contribution_summary"] = donor_summary
    result["donor_contribution_policy"] = {
        "report_how_material_helped": True,
        "report_raw_magnitude_by_metric": True,
        "track_net_pnl_bps": True,
        "track_expectancy_bps_per_trade": True,
        "track_profit_factor": True,
        "track_drawdown_bps": True,
        "track_win_rate_percentage_points": True,
        "track_sample_density_trades": True,
        "stable_history_across_runs": True,
        "cross_scope_delta_is_directional_only": True,
        "same_baseline_ab_required_for_causal_marginal_claim": True,
        "development_pass_is_not_survivor": True,
        "fresh_oos_required_before_promotion": True,
    }
    result["nursery_policy"] = {
        "abandon_synthesis": False,
        "blind_recombination_after_axis_exhaustion": False,
        "grow_demoted_material_before_reuse": True,
        "proven_positive_marginal_donor_can_reenter_immediately": True,
        "final_discard_requires_marginal_nonpositive_dd_nonimproving_and_redundant": True,
        "numeric_threshold_copy_allowed": False,
        "whole_strategy_merge_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    sample = {
        "by_strategy": {
            "trend_rider": {
                "economic_attempted_axes": ["DONOR__A__X__ONLY"],
                "economically_tested_axes_this_run": ["DONOR__B__Y__ONLY"],
            }
        },
        "candidate_donor_attribution": [
            {"host_strategy_id": "break_and_continue", "changed_axis": "DONOR__C__Z__ONLY"}
        ],
    }
    got = _extract_attempted(sample)
    assert got["trend_rider"] == {"DONOR__A__X__ONLY", "DONOR__B__Y__ONLY"}, got
    assert got["break_and_continue"] == {"DONOR__C__Z__ONLY"}, got

    nursery = _build_nursery_queue({"rows": [
        {"strategy_id": "weak_b", "material_grade": "B", "material_disposition": "SYNTHESIS_UPGRADE", "upgrade_axis": "COST", "target_grade": "A", "structural_diversity_prior": 0.5, "quality": {"completed_trades": 8, "positive_gross": True, "positive_net": False}},
        {"strategy_id": "weak_d", "material_grade": "D", "material_disposition": "DISCARD_PENDING_ABLATION", "upgrade_axis": "RECOMBINE", "target_grade": "B", "structural_diversity_prior": 1.0, "quality": {"completed_trades": 20, "positive_gross": False, "positive_net": False}},
        {"strategy_id": "active", "material_grade": "B", "material_disposition": "SYNTHESIS_UPGRADE", "upgrade_axis": "COST", "target_grade": "A", "structural_diversity_prior": 1.0, "quality": {"completed_trades": 9, "positive_gross": True, "positive_net": False}},
    ]}, {"active"})
    assert [x["strategy_id"] for x in nursery] == ["weak_b", "weak_d"], nursery

    routes = _host_exhaustion_routes({"by_strategy": {
        "passer": {"development_economic_pass_count": 1, "remaining_axis_count": 0},
        "spent": {"development_economic_pass_count": 0, "remaining_axis_count": 0},
        "open": {"development_economic_pass_count": 0, "remaining_axis_count": 2},
    }})
    assert routes["passer"] == "INDEPENDENT_OOS_WALK_FORWARD_STRESS"
    assert routes["spent"] == "DONOR_NURSERY_UPGRADE_OR_NEW_EXTERNAL_MECHANISM"
    assert routes["open"] == "CONTINUE_UNTRIED_DISTINCT_DONOR_AXIS"

    parent = {"trades": 20, "net_pnl_bps": 100.0, "net_expectancy_bps": 5.0, "profit_factor": 1.5, "drawdown_bps": 80.0, "win_rate": 0.50}
    child = {"trades": 24, "net_pnl_bps": 160.0, "net_expectancy_bps": 7.0, "profit_factor": 1.7, "drawdown_bps": 60.0, "win_rate": 0.625}
    effect = _delta(parent, child)
    assert effect["trades_delta"] == 4
    assert effect["net_pnl_delta_bps"] == 60.0
    assert effect["drawdown_improvement_bps"] == 20.0
    assert effect["win_rate_delta_pp"] == 12.5
    helped, hurt = _effect_channels(effect)
    assert len(helped) == 6 and not hurt

    summary = _aggregate_donor_contribution([{
        "donor_strategy_id": "alpha_combo", "donor_gene": "multi_factor_confirmation",
        "host_strategy_id": "supertrend_pullback", "terminal_economic_evaluation": True,
        "development_economic_pass": True, "causal_marginal_claim_allowed": False,
        "helped_channels": [{"channel": "NET_PNL"}], "hurt_channels": [],
        "observed_delta": effect, "donor_material_grade": "C", "donor_material_disposition": "SYNTHESIS_EXPERIMENTAL",
    }])
    assert summary[0]["development_pass_count"] == 1
    assert summary[0]["next_route"] == "KEEP_DONOR_AND_VALIDATE_OOS"
    assert summary[0]["causal_marginal_confirmed_count"] == 0

    assert v7.v3.AUTH["execution_authority"] == "NONE" and v7.v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_EVOLUTIONARY_SYNTHESIS_V7_1_ATTEMPT_MEMORY_SELF_TEST")
    print("PASS_FAILED_DONOR_HOST_PAIR_WILL_ADVANCE_NOT_REPEAT")
    print("PASS_DONOR_NURSERY_ROUTE_AFTER_AXIS_EXHAUSTION")
    print("PASS_DONOR_MATERIAL_CONTRIBUTION_ATTRIBUTION_LEDGER")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_top5_evolutionary_synthesis_v7_1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r.get("state"),
        "hosts": r.get("performance_top5_hosts"),
        "donors": r.get("donor_pool_count"),
        "validated_donors": r.get("validated_edge_donor_count"),
        "candidates": r.get("evolutionary_candidate_count"),
        "development_pass": r.get("development_economic_pass_count"),
        "donor_nursery": r.get("donor_nursery_strategy_count"),
        "contribution_rows": len(r.get("donor_contribution_ledger") or []),
        "contribution_donors": len(r.get("donor_contribution_summary") or []),
        "paid": r.get("paid_request_count"),
        "stable_attempt_history": r.get("stable_donor_host_attempt_history"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
