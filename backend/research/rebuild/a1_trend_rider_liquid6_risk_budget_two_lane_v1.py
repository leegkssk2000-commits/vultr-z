#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_top3_profitability_two_lane_router_v2 as v2
from backend.research.rebuild import a1_top3_profitability_two_lane_router_v4 as v4
from backend.research.rebuild.a1_exact25_survivor_gate_v1 import stable_sha


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/rebuild/a1_top3_two_lane_contract_v1.json"
CONTEXT = ROOT / "backend/research/prep/a3_forward_context_ledger_v2.json"
IDENTITY = "trend_rider_first_confirmation_liquid6_long_only_risk_budget_v1"


def evaluate(receipt_path: Path, out: Path) -> dict[str, Any]:
    contract = v2.read(CONTRACT)
    v2.validate_contract(contract)
    context = v2.read(CONTEXT)
    receipt = v2.read(receipt_path)
    if receipt.get("candidate_id") != IDENTITY:
        raise RuntimeError("LIQUID6_RISK_BUDGET_IDENTITY_MISMATCH")
    budget = receipt.get("portfolio_risk_budget") or {}
    if budget.get("state") != "PASS_FIXED_NON_OUTCOME_FITTED_RISK_BUDGET":
        raise RuntimeError("FIXED_RISK_BUDGET_REQUIRED")
    row = v4.candidate(IDENTITY, receipt, None, context, contract)
    result = {
        "schema_version": "zel.a1.trend_rider.liquid6_risk_budget_two_lane.v1",
        "state": "PASS_A3_PILOT_SURVIVOR" if row["pilot_survivor"] else "ACTIVE_AUTO_ROUTE_TO_A3",
        "candidate": row,
        "profit_lane_pass_count": int(row["profit_lane"]["pass"] is True),
        "certification_pilot_a1_pass_count": int(row["certification_pilot"]["pass"] is True),
        "a2_pilot_pass_count": int(row["a2_pilot"].get("pass") is True),
        "a3_pilot_pass_count": int(row["a3_pilot"].get("pass") is True),
        "pilot_survivor_count": int(row["pilot_survivor"] is True),
        "strict_global_gate_mutation": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "next": row["next"],
    }
    result["receipt_sha256"] = stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    contract = v2.read(CONTRACT)
    v2.validate_contract(contract)
    assert contract["profit_lane"]["minimum_completed_trades"] == 10
    assert contract["certification_pilot_lane"]["h4_deferred_fallback"]["minimum_completed_trades"] == 12
    assert contract["certification_pilot_lane"]["a3_pilot"]["minimum_causally_matched_trades"] == 12
    print("PASS_TREND_RIDER_LIQUID6_RISK_BUDGET_TWO_LANE_V1")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_liquid6_risk_budget_two_lane_v1.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if args.receipt is None:
        raise RuntimeError("RECEIPT_REQUIRED")
    result = evaluate(args.receipt, args.out)
    print("A1_TREND_RIDER_LIQUID6_TWO_LANE=" + json.dumps({
        "state": result["state"],
        "profit": result["candidate"]["profit_lane"]["state"],
        "cert": result["candidate"]["certification_pilot"]["state"],
        "a2": result["candidate"]["a2_pilot"]["state"],
        "a3": result["candidate"]["a3_pilot"]["state"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

