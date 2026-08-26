#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research import production_economic_guard_v1 as guard
from backend.research.rebuild import a1_finalist_sample_stall_no_idle_router_v1 as base

SCHEMA = "zel.a1.finalist.sample_stall.no_idle.guarded.v1"


def _guarded_comparison(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base.comparison(parent, child))
    verdict = guard.evaluate(parent, child)
    result["production_economic_guard"] = verdict
    result["pre_guard_development_prereg_eligible"] = bool(result.get("development_prereg_eligible"))
    result["development_prereg_eligible"] = bool(result.get("development_prereg_eligible") and verdict["pass"])
    result["incumbent_state_action"] = verdict["incumbent_state_action"]
    result["fresh25_state_action"] = verdict["fresh25_state_action"]
    return result


def run(out: Path) -> dict[str, Any]:
    original = base.comparison
    try:
        base.comparison = _guarded_comparison
        result = dict(base.run(out))
    finally:
        base.comparison = original
    result["schema_version"] = SCHEMA
    result["production_economic_guard_enabled"] = True
    result["production_economic_guard_rules"] = [
        "ZERO_TRADE_CHILD_HARD_FAIL",
        "TRADE_COUNT_DECREASE_HARD_FAIL",
        "ZERO_TRADE_DD_IMPROVEMENT_INVALID",
        "PNL_AND_EXPECTANCY_BOTH_WORSE_HARD_FAIL",
        "REJECT_PRESERVES_INCUMBENT_AND_FRESH25_STATE",
    ]
    result["incumbent_collectors_continue_on_child_reject"] = True
    result["fresh25_reset_on_child_reject"] = False
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = base.stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    parent = {"completed_trades": 9, "net_pnl_bps": 900.0, "net_expectancy_bps": 100.0, "max_drawdown_bps": 300.0}
    zero = {"completed_trades": 0, "net_pnl_bps": 0.0, "net_expectancy_bps": None, "max_drawdown_bps": 0.0}
    comp = _guarded_comparison(parent, zero)
    assert comp["development_prereg_eligible"] is False
    assert comp["production_economic_guard"]["hard_fail"] is True
    assert comp["production_economic_guard"]["zero_trade_dd_improvement_invalid"] is True
    assert comp["incumbent_state_action"] == "PRESERVE_UNCHANGED"
    assert comp["fresh25_state_action"] == "PRESERVE_UNCHANGED"
    print("PASS_A1_FINALIST_NO_IDLE_PRODUCTION_GUARD_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_sample_stall_no_idle_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result.get("state"),
        "guard": result.get("production_economic_guard_enabled"),
        "routes": {x["strategy_id"]: x["state"] for x in result.get("targets", [])},
        "receipt": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
