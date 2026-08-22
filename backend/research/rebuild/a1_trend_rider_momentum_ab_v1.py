#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact
from backend.research.rebuild import a1_trend_rider_fresh_w123_audit_v1 as w123
from backend.research.rebuild import trend_rider_momentum_child_policy_v1 as child_policy

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
CHILD_POLICY = ROOT / "backend/research/rebuild/trend_rider_momentum_child_policy_v1.py"
SCHEMA = "zel.a1_trend_rider_momentum_direct_ab.v1"
BASELINE_IDENTITY = "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
AXIS = "MOMENTUM_CONFIRMATION_OWNER_ONLY"
KNOWN_PARENT_TRADES = 22
KNOWN_PARENT_WIN_RATE = 13.0 / 22.0


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


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
    with tempfile.TemporaryDirectory(prefix="trend_rider_momentum_ab_") as td:
        inv = Path(td) / "inventory.json"
        inv.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        old_inventory = exact.v1.INVENTORY_PATH
        old_argv = sys.argv[:]
        try:
            exact.v1.INVENTORY_PATH = inv
            sys.argv = [
                old_argv[0],
                "--strategy-id", "trend_rider",
                "--out", str(out),
                "--terminal-replay",
            ]
            exact.main()
        finally:
            exact.v1.INVENTORY_PATH = old_inventory
            sys.argv = old_argv
    return _read(out)


def _metric_delta(parent: Mapping[str, Any], child: Mapping[str, Any], key: str, *, lower_better: bool = False) -> dict[str, Any]:
    p = parent.get(key); c = child.get(key)
    if not isinstance(p, (int, float)) or not isinstance(c, (int, float)) or not math.isfinite(float(p)) or not math.isfinite(float(c)):
        return {"parent": p, "child": c, "delta_child_minus_parent": None, "improvement": None, "lower_is_better": lower_better}
    delta = float(c) - float(p)
    improvement = -delta if lower_better else delta
    return {
        "parent": float(p),
        "child": float(c),
        "delta_child_minus_parent": delta,
        "improvement": improvement,
        "lower_is_better": lower_better,
    }


def _gt(child: Mapping[str, Any], parent: Mapping[str, Any], key: str) -> bool:
    c, p = child.get(key), parent.get(key)
    return isinstance(c, (int, float)) and isinstance(p, (int, float)) and math.isfinite(float(c)) and math.isfinite(float(p)) and float(c) > float(p)


def _lt(child: Mapping[str, Any], parent: Mapping[str, Any], key: str) -> bool:
    c, p = child.get(key), parent.get(key)
    return isinstance(c, (int, float)) and isinstance(p, (int, float)) and math.isfinite(float(c)) and math.isfinite(float(p)) and float(c) < float(p)


def run(output: Path) -> dict[str, Any]:
    cache: dict[str, dict[str, Any]] = {}
    original_fetch = exact.v1.fetch_execution_snapshot

    def cached_fetch(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
        if symbol not in cache:
            cache[symbol] = copy.deepcopy(original_fetch(symbol, authority))
        return copy.deepcopy(cache[symbol])

    parent_path = output.parent / "trend_rider_parent_exact_receipt.json"
    child_path = output.parent / "trend_rider_momentum_child_exact_receipt.json"
    old_fetch = exact.v1.fetch_execution_snapshot
    try:
        exact.v1.fetch_execution_snapshot = cached_fetch
        parent_receipt = _run_exact(parent_path, child=False)
        child_receipt = _run_exact(child_path, child=True)
    finally:
        exact.v1.fetch_execution_snapshot = old_fetch

    parent_audit = w123.run(parent_receipt)
    child_audit = w123.run(child_receipt)
    p = parent_audit["aggregate"]
    c = child_audit["aggregate"]
    invariant = child_policy.invariant_receipt()

    parent_anchor_match = bool(
        int(p.get("trades") or 0) == KNOWN_PARENT_TRADES
        and isinstance(p.get("win_rate"), (int, float))
        and abs(float(p["win_rate"]) - KNOWN_PARENT_WIN_RATE) <= 1e-12
    )
    direct_integrity = {
        "same_boundary": parent_receipt.get("boundary_utc") == child_receipt.get("boundary_utc"),
        "same_config_sha": parent_receipt.get("config_sha") == child_receipt.get("config_sha"),
        "same_source": parent_receipt.get("source") == child_receipt.get("source"),
        "same_execution_snapshots": parent_receipt.get("execution_snapshots") == child_receipt.get("execution_snapshots"),
        "same_cost_authority_sha256": parent_receipt.get("cost_authority_sha256") == child_receipt.get("cost_authority_sha256"),
        "parent_policy_is_canonical": str(parent_receipt.get("policy_path") or "") == "backend/research/rebuild/trend_policy_batch_v1.py",
        "child_policy_is_momentum_only": str(child_receipt.get("policy_path") or "") == str(CHILD_POLICY.relative_to(ROOT)),
        "config_values_identical": invariant["config_values_identical"],
        "config_sha_identical": invariant["config_sha_identical"],
        "one_axis_only": invariant["one_axis_only"],
        "threshold_sweep": invariant["threshold_sweep"],
        "best_horizon_selection": invariant["best_horizon_selection"],
        "post_outcome_trade_deletion": invariant["post_outcome_trade_deletion"],
        "parent_anchor_22_trades_59_09pct": parent_anchor_match,
    }
    direct_ab = bool(
        all(bool(v) for k, v in direct_integrity.items() if k not in {"threshold_sweep", "best_horizon_selection", "post_outcome_trade_deletion"})
        and direct_integrity["threshold_sweep"] is False
        and direct_integrity["best_horizon_selection"] is False
        and direct_integrity["post_outcome_trade_deletion"] is False
    )

    retention = (float(c.get("trades") or 0) / float(p.get("trades") or 1)) * 100.0 if float(p.get("trades") or 0) > 0 else None
    deltas = {
        "win_rate": _metric_delta(p, c, "win_rate"),
        "net_expectancy_bps": _metric_delta(p, c, "net_expectancy_bps"),
        "net_pnl_bps": _metric_delta(p, c, "net_pnl_bps"),
        "profit_factor": _metric_delta(p, c, "profit_factor"),
        "payoff": _metric_delta(p, c, "payoff"),
        "drawdown_bps": _metric_delta(p, c, "drawdown_bps", lower_better=True),
        "trades": _metric_delta(p, c, "trades"),
        "trade_retention_pct": {"parent": 100.0, "child": retention, "delta_child_minus_parent": None if retention is None else retention - 100.0, "improvement": None, "lower_is_better": False},
    }

    expectancy_improved = _gt(c, p, "net_expectancy_bps")
    robustness_improved = bool(_gt(c, p, "profit_factor") or _gt(c, p, "payoff") or _lt(c, p, "drawdown_bps"))
    child_positive_economics = bool(child_audit.get("economics_gate_pass"))
    screen_pass = bool(direct_ab and expectancy_improved and robustness_improved and child_positive_economics)

    if not parent_anchor_match:
        state = "HOLD_PARENT_FRESH_W123_59PCT_ANCHOR_MISMATCH"
    elif not direct_ab:
        state = "HOLD_MOMENTUM_DIRECT_AB_INTEGRITY"
    elif screen_pass:
        state = "PASS_MOMENTUM_DIRECT_AB_DEVELOPMENT_SCREEN_PENDING_H4_H5"
    else:
        state = "FAIL_MOMENTUM_DIRECT_AB_DEVELOPMENT_SCREEN"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "external_evidence_ids": list(child_policy.EXTERNAL_EVIDENCE_IDS),
        "parameter_provenance": child_policy.PARAMETER_PROVENANCE,
        "momentum_transform": child_policy.MOMENTUM_TRANSFORM,
        "parent_known_anchor": {"trades": KNOWN_PARENT_TRADES, "win_rate": KNOWN_PARENT_WIN_RATE},
        "parent_w123": parent_audit,
        "child_w123": child_audit,
        "metric_deltas": deltas,
        "trade_retention_pct": retention,
        "direct_same_original_fresh_w123_parent_child_ab_receipt_present": direct_ab,
        "direct_integrity": direct_integrity,
        "development_screen": {
            "parent_anchor_match": parent_anchor_match,
            "child_w123_economics_gate_pass": child_positive_economics,
            "net_expectancy_improved": expectancy_improved,
            "robustness_improved_pf_or_payoff_or_drawdown": robustness_improved,
            "pass": screen_pass,
        },
        "numeric_development_delta_vs_59pct_baseline_claim_allowed": bool(direct_ab),
        "survivor_improvement_claim_allowed": False,
        "next_if_pass": "H4_NEGATIVE_CONTROLS_THEN_H5_FRAGILITY_THEN_FRESH_PROSPECTIVE_VALIDATION",
        "next_if_fail": "EMA_SLOPE_REVERSAL_EXIT_ONLY",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = _sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    inv = child_policy.invariant_receipt()
    assert inv["config_sha_identical"] is True and inv["config_values_identical"] is True
    assert inv["changed_axis"] == AXIS
    assert inv["momentum_threshold"] == 0.0
    p = {"win_rate": 0.5, "net_expectancy_bps": 10.0, "profit_factor": 2.0, "payoff": 1.5, "drawdown_bps": 100.0, "trades": 20}
    c = {"win_rate": 0.6, "net_expectancy_bps": 11.0, "profit_factor": 2.1, "payoff": 1.4, "drawdown_bps": 90.0, "trades": 15}
    assert _gt(c, p, "net_expectancy_bps") and _gt(c, p, "profit_factor") and _lt(c, p, "drawdown_bps")
    assert _metric_delta(p, c, "drawdown_bps", lower_better=True)["improvement"] == 10.0
    assert abs(KNOWN_PARENT_WIN_RATE - 0.5909090909090909) < 1e-15
    print("PASS_A1_TREND_RIDER_MOMENTUM_DIRECT_AB_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_momentum_ab_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "direct_ab": r["direct_same_original_fresh_w123_parent_child_ab_receipt_present"],
        "screen_pass": r["development_screen"]["pass"],
        "parent": r["parent_w123"]["aggregate"],
        "child": r["child_w123"]["aggregate"],
        "deltas": r["metric_deltas"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
