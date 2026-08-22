#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact
from backend.research.rebuild import a1_trend_rider_fresh_w123_audit_v1 as w123
from backend.research.rebuild import a1_trend_rider_momentum_ab_v1 as metric_helper
from backend.research.rebuild import a1_trend_rider_atr_expansion_frozen_w123_ab_v1 as template
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as child_policy

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
CHILD_POLICY = ROOT / "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py"
SCHEMA = "zel.a1_trend_rider_transition_freshness_frozen_w123_ab.v1"
BASELINE_IDENTITY = template.BASELINE_IDENTITY
AXIS = "TRANSITION_FRESHNESS_REENTRY_SUPPRESSION_ONLY"
FROZEN_OBSERVATION_RUN_ID = template.FROZEN_OBSERVATION_RUN_ID
FROZEN_BOUNDARY_UTC = template.FROZEN_BOUNDARY_UTC
FROZEN_LAST_POST_BOUNDARY_TS = template.FROZEN_LAST_POST_BOUNDARY_TS
EXPECTED_PARENT = dict(template.EXPECTED_PARENT)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _run_exact(out: Path, *, child: bool) -> dict[str, Any]:
    inventory = _read(INVENTORY)
    if child:
        ((inventory.get("strategies") or {}).get("trend_rider") or {})["policy_owner"] = str(CHILD_POLICY.relative_to(ROOT))
    with tempfile.TemporaryDirectory(prefix="trend_rider_transition_freshness_ab_") as td:
        inv = Path(td) / "inventory.json"
        inv.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        old_inventory = exact.v1.INVENTORY_PATH
        old_argv = sys.argv[:]
        try:
            exact.v1.INVENTORY_PATH = inv
            sys.argv = [old_argv[0], "--strategy-id", "trend_rider", "--out", str(out), "--terminal-replay"]
            exact.main()
        finally:
            exact.v1.INVENTORY_PATH = old_inventory
            sys.argv = old_argv
    return _read(out)


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (str(row.get("symbol")), int(row.get("signal_ts")), int(row.get("entry_ts")), str(row.get("side")))


def run(output: Path) -> dict[str, Any]:
    cache: dict[str, dict[str, Any]] = {}
    original_fetch = exact.v1.fetch_execution_snapshot

    def cached_fetch(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
        if symbol not in cache:
            cache[symbol] = copy.deepcopy(original_fetch(symbol, authority))
        return copy.deepcopy(cache[symbol])

    output.parent.mkdir(parents=True, exist_ok=True)
    parent_path = output.parent / "trend_rider_parent_current_receipt.json"
    child_path = output.parent / "trend_rider_transition_freshness_child_current_receipt.json"
    old_fetch = exact.v1.fetch_execution_snapshot
    try:
        exact.v1.fetch_execution_snapshot = cached_fetch
        parent_current = _run_exact(parent_path, child=False)
        child_current = _run_exact(child_path, child=True)
    finally:
        exact.v1.fetch_execution_snapshot = old_fetch

    parent_frozen = template._freeze_parent(parent_current)
    child_frozen = template._freeze_child(parent_frozen, child_current)
    parent_audit = w123.run(parent_frozen)
    child_audit = w123.run(child_frozen)
    p = parent_audit["aggregate"]
    c = child_audit["aggregate"]
    invariant = child_policy.invariant_receipt()
    parent_anchor_match = template._matches_expected(p)
    parent_ids = {_identity(x) for x in parent_frozen["trades"]}
    child_ids = {_identity(x) for x in child_frozen["trades"]}

    direct_integrity = {
        "frozen_observation_run_id": FROZEN_OBSERVATION_RUN_ID,
        "frozen_parent_metrics_exact_match": parent_anchor_match,
        "same_boundary": parent_current.get("boundary_utc") == child_current.get("boundary_utc") == FROZEN_BOUNDARY_UTC,
        "same_config_sha": parent_current.get("config_sha") == child_current.get("config_sha"),
        "same_source": parent_current.get("source") == child_current.get("source"),
        "same_execution_snapshots": parent_current.get("execution_snapshots") == child_current.get("execution_snapshots"),
        "same_cost_authority_sha256": parent_current.get("cost_authority_sha256") == child_current.get("cost_authority_sha256"),
        "parent_policy_is_canonical": str(parent_current.get("policy_path") or "") == "backend/research/rebuild/trend_policy_batch_v1.py",
        "child_policy_is_transition_freshness_only": str(child_current.get("policy_path") or "") == str(CHILD_POLICY.relative_to(ROOT)),
        "child_is_subset_of_frozen_parent": child_ids.issubset(parent_ids),
        "config_values_identical": invariant["config_values_identical"],
        "config_sha_identical": invariant["config_sha_identical"],
        "one_axis_only": invariant["one_axis_only"],
        "numeric_threshold_sweep": invariant["numeric_threshold_sweep"],
        "best_horizon_selection": invariant["best_horizon_selection"],
        "post_outcome_trade_deletion": invariant["post_outcome_trade_deletion"],
        "uses_post_outcome_data": invariant["uses_post_outcome_data"],
        "existing_parent_one_entry_per_transition": invariant["existing_parent_one_entry_per_transition"],
        "existing_parent_duplicate_transition_forbidden": invariant["existing_parent_duplicate_transition_forbidden"],
    }
    excluded_false_keys = {
        "frozen_observation_run_id", "numeric_threshold_sweep", "best_horizon_selection",
        "post_outcome_trade_deletion", "uses_post_outcome_data",
    }
    direct_ab = bool(
        parent_anchor_match
        and all(bool(v) for k, v in direct_integrity.items() if k not in excluded_false_keys)
        and direct_integrity["numeric_threshold_sweep"] is False
        and direct_integrity["best_horizon_selection"] is False
        and direct_integrity["post_outcome_trade_deletion"] is False
        and direct_integrity["uses_post_outcome_data"] is False
    )

    retention = (float(c.get("trades") or 0) / float(p.get("trades") or 1) * 100.0
                 if float(p.get("trades") or 0) > 0 else None)
    deltas = {
        "win_rate": metric_helper._metric_delta(p, c, "win_rate"),
        "net_expectancy_bps": metric_helper._metric_delta(p, c, "net_expectancy_bps"),
        "net_pnl_bps": metric_helper._metric_delta(p, c, "net_pnl_bps"),
        "profit_factor": metric_helper._metric_delta(p, c, "profit_factor"),
        "payoff": metric_helper._metric_delta(p, c, "payoff"),
        "drawdown_bps": metric_helper._metric_delta(p, c, "drawdown_bps", lower_better=True),
        "trades": metric_helper._metric_delta(p, c, "trades"),
        "trade_retention_pct": {
            "parent": 100.0,
            "child": retention,
            "delta_child_minus_parent": None if retention is None else retention - 100.0,
            "improvement": None,
            "lower_is_better": False,
        },
    }
    expectancy_improved = metric_helper._gt(c, p, "net_expectancy_bps")
    robustness_improved = bool(
        metric_helper._gt(c, p, "profit_factor")
        or metric_helper._gt(c, p, "payoff")
        or metric_helper._lt(c, p, "drawdown_bps")
    )
    child_positive_economics = bool(child_audit.get("economics_gate_pass"))
    retention_gate = bool(retention is not None and retention >= 60.0)
    screen_pass = bool(direct_ab and expectancy_improved and robustness_improved and child_positive_economics and retention_gate)

    if not parent_anchor_match:
        state = "HOLD_FROZEN_PARENT_W123_AUTHORITY_MISMATCH"
    elif not direct_ab:
        state = "HOLD_TRANSITION_FRESHNESS_FROZEN_W123_DIRECT_AB_INTEGRITY"
    elif screen_pass:
        state = "PASS_TRANSITION_FRESHNESS_FROZEN_W123_DEVELOPMENT_SCREEN_PENDING_H4_H5"
    elif not retention_gate:
        state = "FAIL_TRANSITION_FRESHNESS_FROZEN_W123_RETENTION_BELOW_60PCT"
    else:
        state = "FAIL_TRANSITION_FRESHNESS_FROZEN_W123_DEVELOPMENT_SCREEN"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "frozen_observation_authority": {
            "run_id": FROZEN_OBSERVATION_RUN_ID,
            "boundary_utc": FROZEN_BOUNDARY_UTC,
            "last_post_boundary_ts": FROZEN_LAST_POST_BOUNDARY_TS,
            "expected_parent": EXPECTED_PARENT,
        },
        "external_evidence_ids": list(child_policy.EXTERNAL_EVIDENCE_IDS),
        "parameter_provenance": child_policy.PARAMETER_PROVENANCE,
        "context_transform": child_policy.CONTEXT_TRANSFORM,
        "parent_w123": parent_audit,
        "child_w123": child_audit,
        "metric_deltas": deltas,
        "trade_retention_pct": retention,
        "direct_same_frozen_original_fresh_w123_parent_child_ab_receipt_present": direct_ab,
        "direct_integrity": direct_integrity,
        "development_screen": {
            "parent_anchor_match": parent_anchor_match,
            "child_w123_economics_gate_pass": child_positive_economics,
            "net_expectancy_improved": expectancy_improved,
            "robustness_improved_pf_or_payoff_or_drawdown": robustness_improved,
            "retention_at_least_60pct": retention_gate,
            "pass": screen_pass,
        },
        "numeric_development_delta_vs_59pct_baseline_claim_allowed": bool(direct_ab),
        "survivor_improvement_claim_allowed": False,
        "next_if_pass": "H4_NEGATIVE_CONTROLS_THEN_H5_FRAGILITY_THEN_A2_COST_REVALIDATION_THEN_A3_FRESH_DURABILITY",
        "next_if_fail": "REENTRY_CLUSTER_ATTRIBUTION_THEN_DISTINCT_CAUSAL_AXIS",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = metric_helper._sha(result)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    inv = child_policy.invariant_receipt()
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["changed_axis"] == AXIS
    assert inv["existing_parent_one_entry_per_transition"] is True
    assert inv["numeric_threshold_sweep"] is False
    assert inv["uses_post_outcome_data"] is False
    assert EXPECTED_PARENT["trades"] == 22
    assert math.isclose(float(EXPECTED_PARENT["win_rate"]), 13 / 22, rel_tol=0.0, abs_tol=1e-15)
    print("PASS_A1_TREND_RIDER_TRANSITION_FRESHNESS_FROZEN_W123_AB_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_transition_freshness_frozen_w123_ab_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "parent": r["parent_w123"]["aggregate"],
        "child": r["child_w123"]["aggregate"],
        "deltas": r["metric_deltas"],
        "retention_pct": r["trade_retention_pct"],
        "screen_pass": r["development_screen"]["pass"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
