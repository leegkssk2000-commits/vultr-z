#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact
from backend.research.rebuild import a1_trend_rider_fresh_w123_audit_v1 as w123
from backend.research.rebuild import a1_trend_rider_momentum_ab_v1 as v1
from backend.research.rebuild import trend_rider_momentum_child_policy_v1 as child_policy

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
CHILD_POLICY = ROOT / "backend/research/rebuild/trend_rider_momentum_child_policy_v1.py"
SCHEMA = "zel.a1_trend_rider_momentum_frozen_w123_ab.v2"
BASELINE_IDENTITY = "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
AXIS = "MOMENTUM_CONFIRMATION_OWNER_ONLY"

# Immutable observation authority from successful run 32436283144 / issue 566 comment 5364074212.
FROZEN_OBSERVATION_RUN_ID = 32436283144
FROZEN_BOUNDARY_UTC = "2026-08-16T18:45:01Z"
FROZEN_LAST_POST_BOUNDARY_TS = 1787274000000
EXPECTED_PARENT = {
    "trades": 22,
    "win_rate": 0.5909090909090909,
    "net_pnl_bps": 16509.276493685335,
    "net_expectancy_bps": 750.4216588038788,
    "profit_factor": 29.24609724094979,
    "payoff": 20.247298089888314,
    "drawdown_bps": 474.30214106823223,
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _run_exact(out: Path, *, child: bool) -> dict[str, Any]:
    inventory = _read(INVENTORY)
    if child:
        row = ((inventory.get("strategies") or {}).get("trend_rider") or {})
        row["policy_owner"] = str(CHILD_POLICY.relative_to(ROOT))
    with tempfile.TemporaryDirectory(prefix="trend_rider_frozen_w123_ab_") as td:
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
    return (
        str(row.get("symbol")),
        int(row.get("signal_ts")),
        int(row.get("entry_ts")),
        str(row.get("side")),
    )


def _freeze_parent(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if str(receipt.get("boundary_utc")) != FROZEN_BOUNDARY_UTC:
        raise RuntimeError("FROZEN_BOUNDARY_DRIFT")
    boundary_ms = int(datetime.fromisoformat(FROZEN_BOUNDARY_UTC.replace("Z", "+00:00")).timestamp() * 1000)
    w123_end = boundary_ms + 3 * 86_400_000
    rows = [
        copy.deepcopy(x)
        for x in (receipt.get("trades") or [])
        if boundary_ms <= int(x.get("entry_ts")) < w123_end
        and int(x.get("exit_ts")) <= FROZEN_LAST_POST_BOUNDARY_TS
    ]
    out = copy.deepcopy(dict(receipt))
    out["trades"] = rows
    out["completed_trades"] = len(rows)
    out["frozen_observation"] = {
        "run_id": FROZEN_OBSERVATION_RUN_ID,
        "boundary_utc": FROZEN_BOUNDARY_UTC,
        "last_post_boundary_ts": FROZEN_LAST_POST_BOUNDARY_TS,
        "rule": "same W1-W3 entries whose outcomes were observable at immutable original-fresh observation horizon",
    }
    return out


def _freeze_child(parent_frozen: Mapping[str, Any], child_current: Mapping[str, Any]) -> dict[str, Any]:
    parent_rows = { _identity(x): x for x in (parent_frozen.get("trades") or []) }
    child_rows_current = { _identity(x): x for x in (child_current.get("trades") or []) }
    retained = []
    geometry_mismatch = []
    for key, prow in parent_rows.items():
        crow = child_rows_current.get(key)
        if crow is None:
            continue
        # Momentum is admission-only. Retained trade geometry/outcome must be identical to parent.
        for field in ("entry", "exit", "entry_ts", "exit_ts", "side", "reason", "net_bps", "gross_bps", "realized_cost_bps"):
            a, b = prow.get(field), crow.get(field)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9):
                    geometry_mismatch.append(f"{key}:{field}:{a}!={b}")
            elif a != b:
                geometry_mismatch.append(f"{key}:{field}:{a}!={b}")
        retained.append(copy.deepcopy(crow))
    if geometry_mismatch:
        raise RuntimeError("CHILD_PARENT_GEOMETRY_DRIFT:" + "|".join(geometry_mismatch[:8]))
    out = copy.deepcopy(dict(child_current))
    out["trades"] = retained
    out["completed_trades"] = len(retained)
    out["frozen_parent_identity_count"] = len(parent_rows)
    out["frozen_observation_run_id"] = FROZEN_OBSERVATION_RUN_ID
    return out


def _matches_expected(m: Mapping[str, Any]) -> bool:
    for key, expected in EXPECTED_PARENT.items():
        actual = m.get(key)
        if not isinstance(actual, (int, float)):
            return False
        if key == "trades":
            if int(actual) != int(expected):
                return False
        elif not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-9):
            return False
    return True


def run(output: Path) -> dict[str, Any]:
    cache: dict[str, dict[str, Any]] = {}
    original_fetch = exact.v1.fetch_execution_snapshot

    def cached_fetch(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
        if symbol not in cache:
            cache[symbol] = copy.deepcopy(original_fetch(symbol, authority))
        return copy.deepcopy(cache[symbol])

    output.parent.mkdir(parents=True, exist_ok=True)
    parent_path = output.parent / "trend_rider_parent_current_receipt.json"
    child_path = output.parent / "trend_rider_momentum_child_current_receipt.json"
    old_fetch = exact.v1.fetch_execution_snapshot
    try:
        exact.v1.fetch_execution_snapshot = cached_fetch
        parent_current = _run_exact(parent_path, child=False)
        child_current = _run_exact(child_path, child=True)
    finally:
        exact.v1.fetch_execution_snapshot = old_fetch

    parent_frozen = _freeze_parent(parent_current)
    child_frozen = _freeze_child(parent_frozen, child_current)
    parent_audit = w123.run(parent_frozen)
    child_audit = w123.run(child_frozen)
    p = parent_audit["aggregate"]
    c = child_audit["aggregate"]
    invariant = child_policy.invariant_receipt()

    parent_anchor_match = _matches_expected(p)
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
        "child_policy_is_momentum_only": str(child_current.get("policy_path") or "") == str(CHILD_POLICY.relative_to(ROOT)),
        "child_is_subset_of_frozen_parent": child_ids.issubset(parent_ids),
        "config_values_identical": invariant["config_values_identical"],
        "config_sha_identical": invariant["config_sha_identical"],
        "one_axis_only": invariant["one_axis_only"],
        "threshold_sweep": invariant["threshold_sweep"],
        "best_horizon_selection": invariant["best_horizon_selection"],
        "post_outcome_trade_deletion": invariant["post_outcome_trade_deletion"],
    }
    direct_ab = bool(
        parent_anchor_match
        and all(bool(v) for k, v in direct_integrity.items() if k not in {"frozen_observation_run_id", "threshold_sweep", "best_horizon_selection", "post_outcome_trade_deletion"})
        and direct_integrity["threshold_sweep"] is False
        and direct_integrity["best_horizon_selection"] is False
        and direct_integrity["post_outcome_trade_deletion"] is False
    )

    retention = (float(c.get("trades") or 0) / float(p.get("trades") or 1)) * 100.0 if float(p.get("trades") or 0) > 0 else None
    deltas = {
        "win_rate": v1._metric_delta(p, c, "win_rate"),
        "net_expectancy_bps": v1._metric_delta(p, c, "net_expectancy_bps"),
        "net_pnl_bps": v1._metric_delta(p, c, "net_pnl_bps"),
        "profit_factor": v1._metric_delta(p, c, "profit_factor"),
        "payoff": v1._metric_delta(p, c, "payoff"),
        "drawdown_bps": v1._metric_delta(p, c, "drawdown_bps", lower_better=True),
        "trades": v1._metric_delta(p, c, "trades"),
        "trade_retention_pct": {"parent": 100.0, "child": retention, "delta_child_minus_parent": None if retention is None else retention - 100.0, "improvement": None, "lower_is_better": False},
    }
    expectancy_improved = v1._gt(c, p, "net_expectancy_bps")
    robustness_improved = bool(v1._gt(c, p, "profit_factor") or v1._gt(c, p, "payoff") or v1._lt(c, p, "drawdown_bps"))
    child_positive_economics = bool(child_audit.get("economics_gate_pass"))
    retention_gate = bool(retention is not None and retention >= 60.0)
    screen_pass = bool(direct_ab and expectancy_improved and robustness_improved and child_positive_economics and retention_gate)

    if not parent_anchor_match:
        state = "HOLD_FROZEN_PARENT_W123_AUTHORITY_MISMATCH"
    elif not direct_ab:
        state = "HOLD_MOMENTUM_FROZEN_W123_DIRECT_AB_INTEGRITY"
    elif screen_pass:
        state = "PASS_MOMENTUM_FROZEN_W123_DEVELOPMENT_SCREEN_PENDING_H4_H5"
    elif not retention_gate:
        state = "FAIL_MOMENTUM_FROZEN_W123_RETENTION_BELOW_60PCT"
    else:
        state = "FAIL_MOMENTUM_FROZEN_W123_DEVELOPMENT_SCREEN"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "frozen_observation_authority": {
            "run_id": FROZEN_OBSERVATION_RUN_ID,
            "issue_comment_id": 5364074212,
            "boundary_utc": FROZEN_BOUNDARY_UTC,
            "last_post_boundary_ts": FROZEN_LAST_POST_BOUNDARY_TS,
            "expected_parent": EXPECTED_PARENT,
        },
        "external_evidence_ids": list(child_policy.EXTERNAL_EVIDENCE_IDS),
        "parameter_provenance": child_policy.PARAMETER_PROVENANCE,
        "momentum_transform": child_policy.MOMENTUM_TRANSFORM,
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
        "next_if_fail": "EMA_SLOPE_REVERSAL_EXIT_ONLY",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = v1._sha(result)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    inv = child_policy.invariant_receipt()
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["changed_axis"] == AXIS
    assert inv["momentum_threshold"] == 0.0
    assert EXPECTED_PARENT["trades"] == 22
    assert math.isclose(float(EXPECTED_PARENT["win_rate"]), 13 / 22, rel_tol=0.0, abs_tol=1e-15)
    assert FROZEN_OBSERVATION_RUN_ID == 32436283144
    print("PASS_A1_TREND_RIDER_MOMENTUM_FROZEN_W123_AB_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_momentum_frozen_w123_ab_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "direct_ab": r["direct_same_frozen_original_fresh_w123_parent_child_ab_receipt_present"],
        "screen_pass": r["development_screen"]["pass"],
        "parent": r["parent_w123"]["aggregate"],
        "child": r["child_w123"]["aggregate"],
        "deltas": r["metric_deltas"],
        "retention_pct": r["trade_retention_pct"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
