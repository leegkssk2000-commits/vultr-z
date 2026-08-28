#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.a1.top6.trend_ma_macd.rebound_qualifier.v1"


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def trades_of(metrics: Mapping[str, Any]) -> int:
    return int(metrics.get("trades") or metrics.get("completed_trades") or 0)


def parent_trade_count(parent: Mapping[str, Any]) -> int:
    if parent.get("completed_trades") is not None:
        return int(parent["completed_trades"])
    metrics = parent.get("metrics") if isinstance(parent.get("metrics"), Mapping) else {}
    t = trades_of(metrics)
    if t:
        return t
    rows = parent.get("trades")
    return len(rows) if isinstance(rows, list) else 0


def run(parent_path: Path, rebound_path: Path, out: Path) -> dict[str, Any]:
    parent = read(parent_path)
    rebound = read(rebound_path)
    if parent.get("strategy_id") != "trend_ma_macd" or rebound.get("strategy_id") != "trend_ma_macd":
        raise RuntimeError("TREND_MA_MACD_IDENTITY_REQUIRED")

    parent_t = parent_trade_count(parent)
    native = rebound.get("native") if isinstance(rebound.get("native"), Mapping) else {}
    native_metrics = native.get("metrics") if isinstance(native.get("metrics"), Mapping) else {}
    native_t = trades_of(native_metrics)
    parent_boundary = str(parent.get("boundary_utc") or "")
    rebound_boundary = str(rebound.get("boundary_utc") or "")

    checks = {
        "strategy_identity_same": True,
        "parent_T_equals_rebound_native_T": parent_t > 0 and parent_t == native_t,
        "boundary_same": bool(parent_boundary) and parent_boundary == rebound_boundary,
        "parent_execution_blocked": parent.get("execution_authority") in (None, "NONE"),
        "parent_order_blocked": parent.get("order_authority") in (None, "BLOCKED"),
        "rebound_execution_blocked": rebound.get("execution_authority") == "NONE",
        "rebound_order_blocked": rebound.get("order_authority") == "BLOCKED",
        "rebound_live_blocked": rebound.get("live_trade_authority") == "BLOCKED",
    }
    lineage_ok = all(checks.values())
    metric_pass = rebound.get("state") == "PASS_TOP6_STRUCTURAL_REBOUND_CANDIDATE"
    eligible = bool(lineage_ok and metric_pass)

    if not lineage_ok:
        state = "HOLD_TOP6_LINEAGE_COMPARATOR_MISMATCH"
        next_step = "REBUILD_SINGLE_COMPARATOR_THEN_RETEST"
    elif metric_pass:
        state = "QUEUE_TOP6_FRESH_OOS_VALIDATION"
        next_step = "FRESH_PROSPECTIVE_OOS_ONLY"
    else:
        state = "ROUTE_TREND_MA_MACD_TO_C_MATERIAL"
        next_step = "C_GRADE_DONOR_NURSERY"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_ma_macd",
        "parent_T": parent_t,
        "rebound_native_T": native_t,
        "parent_boundary_utc": parent_boundary,
        "rebound_boundary_utc": rebound_boundary,
        "lineage_checks": checks,
        "lineage_comparator_pass": lineage_ok,
        "metric_rebound_pass": metric_pass,
        "eligible_for_fresh_validation": eligible,
        "false_pass_fail_closed": not lineage_ok,
        "next": next_step,
        "production_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--rebound", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top6_trend_ma_macd_rebound_qualifier_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        assert trades_of({"trades": 25}) == 25
        print("PASS_A1_TOP6_TREND_MA_MACD_REBOUND_QUALIFIER_V1_SELF_TEST")
        return 0
    if args.parent is None or args.rebound is None:
        raise SystemExit("--parent and --rebound required")
    r = run(args.parent, args.rebound, args.out)
    print(json.dumps({"state": r["state"], "parent_T": r["parent_T"], "native_T": r["rebound_native_T"], "eligible": r["eligible_for_fresh_validation"], "next": r["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
