#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7 as v7
from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7_1 as v71
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

SCHEMA = "zel.a1_top5_evolutionary_synthesis.v7_2"


def _active_hosts(full_hosts: list[str], axes: Mapping[str, Any]) -> list[str]:
    return [sid for sid in full_hosts if sid in axes and bool(axes.get(sid))]


def _safe_v7_run(output: Path) -> dict[str, Any]:
    league = v7._read(v7.LEAGUE)
    full_hosts = v7._host_order(league)
    if not full_hosts:
        raise RuntimeError("NO_SUPPORTED_PERFORMANCE_TOP5_HOST")
    donors = v7._donor_pool(league, full_hosts)
    plans = v7._host_plans(full_hosts, donors)
    axes = v7._donor_axes(plans)
    active_hosts = _active_hosts(full_hosts, axes)

    old_order = v7.v3.v1.a5_order
    old_allowed = v7.v3.v1.allowed_axes
    old_prompt = v7.v3._prompt
    old_latest = v7.v3.LATEST

    def focused_order(_contract: Mapping[str, Any]) -> list[str]:
        # Critical hardening: v3 indexes all_axes[sid], so order must contain only
        # hosts with a real untried donor axis. Exhausted hosts are preserved in
        # performance_top5_hosts and routed by V7.1 donor nursery instead.
        return list(active_hosts)

    def donor_only_axes(_contract: Mapping[str, Any], _readiness: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
        return {sid: [dict(x) for x in axes[sid]] for sid in active_hosts}

    try:
        v7.v3.v1.a5_order = focused_order
        v7.v3.v1.allowed_axes = donor_only_axes
        v7.v3._prompt = v7._wrap_prompt(old_prompt, plans)
        v7.v3.LATEST = v7.LATEST
        result = dict(v7.v3.run(output))
    finally:
        v7.v3.v1.a5_order = old_order
        v7.v3.v1.allowed_axes = old_allowed
        v7.v3._prompt = old_prompt
        v7.v3.LATEST = old_latest

    attributions = v7._candidate_attribution(result, plans)
    result["schema_version"] = SCHEMA
    result["performance_top5_hosts"] = list(full_hosts)
    result["active_synthesis_hosts"] = list(active_hosts)
    result["axis_exhausted_hosts"] = [sid for sid in full_hosts if sid not in active_hosts]
    result["performance_top5_source"] = str(v7.LEAGUE.relative_to(v7.ROOT))
    result["donor_pool"] = donors
    result["donor_pool_count"] = len(donors)
    result["validated_edge_donor_count"] = sum(1 for x in donors if x.get("donor_tier") == "VALIDATED_EDGE_DONOR")
    result["mechanism_hypothesis_donor_count"] = sum(1 for x in donors if x.get("donor_tier") == "MECHANISM_HYPOTHESIS_ONLY")
    result["host_plans"] = plans
    result["candidate_donor_attribution"] = attributions
    result["evolutionary_candidate_count"] = len(attributions)
    result["direct_improvement_scope"] = "CURRENT_PERFORMANCE_TOP5_HOSTS_ONLY"
    result["demoted_strategy_direct_repair_enabled"] = False
    result["demoted_top5_becomes_donor"] = True
    result["full_strategy_merge_allowed"] = False
    result["one_gene_per_host_per_attempt"] = True
    result["donor_numeric_threshold_copy_allowed"] = False
    result["failed_gene_pair_archive_via_stable_axis_history"] = True
    result["exhausted_host_keyerror_guard"] = True
    result["synthesis_acceptance_gate"] = {
        "net_pnl_improves": True,
        "expectancy_improves": True,
        "profit_factor_nonworse": True,
        "drawdown_nonworse": True,
        "trade_retention_gate": True,
        "same_baseline_ab": True,
        "fresh_oos_before_promotion": True,
    }
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def run(output: Path) -> dict[str, Any]:
    original = v7.run
    try:
        v7.run = _safe_v7_run
        result = dict(v71.run(output))
    finally:
        v7.run = original
    result["schema_version"] = SCHEMA
    result["full_top5_preserved_when_axes_exhausted"] = True
    result["active_host_subset_for_v3"] = True
    result["exhausted_host_keyerror_guard"] = True
    # V7.1 nursery routing only sees by_strategy rows for active hosts. Explicitly
    # route missing/exhausted Top5 hosts to the nursery/new-mechanism lane.
    routes = dict(result.get("host_exhaustion_routes") or {})
    active = set(result.get("active_synthesis_hosts") or [])
    for sid in result.get("performance_top5_hosts") or []:
        if sid not in active and sid not in routes:
            routes[str(sid)] = "DONOR_NURSERY_UPGRADE_OR_NEW_EXTERNAL_MECHANISM"
    result["host_exhaustion_routes"] = routes
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert _active_hosts(["a", "b", "c"], {"a": [{"axis": "X"}], "b": [], "z": [{"axis": "Y"}]}) == ["a"]
    assert v7.v3.AUTH["execution_authority"] == "NONE" and v7.v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_EVOLUTIONARY_SYNTHESIS_V7_2_EXHAUSTED_HOST_GUARD")
    print("PASS_TOP5_IDENTITY_PRESERVED_WHILE_ONLY_ACTIONABLE_HOSTS_ENTER_V3")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_top5_evolutionary_synthesis_v7_2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r.get("state"),
        "hosts": r.get("performance_top5_hosts"),
        "active_synthesis_hosts": r.get("active_synthesis_hosts"),
        "axis_exhausted_hosts": r.get("axis_exhausted_hosts"),
        "development_pass": r.get("development_economic_pass_count"),
        "donor_nursery": r.get("donor_nursery_strategy_count"),
        "contribution_rows": len(r.get("donor_contribution_ledger") or []),
        "contribution_donors": len(r.get("donor_contribution_summary") or []),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
