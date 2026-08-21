#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as v1
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as v2
from backend.research.rebuild import trend_rider_first_confirmation_policy_v1 as policy
from backend.research.rebuild.a1_exact25_survivor_gate_v1 import stable_sha


POLICY_PATH = Path(policy.__file__).resolve()


def enforce_policy_ownership(receipt: dict[str, Any]) -> dict[str, Any]:
    """Apply intent-declared no-pyramiding and two-bar cooldown semantics.

    The generic economics loop evaluates each closed bar independently. This
    challenger additionally owns the policy's explicit execution semantics so
    overlapping entries cannot inflate its sample or PnL.
    """
    interval_ms = 3_600_000
    cooldown_bars = 2
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    blocked_until: dict[str, int] = {}
    for trade in sorted(receipt.get("trades") or [], key=lambda x: (str(x["symbol"]), int(x["entry_ts"]))):
        symbol = str(trade["symbol"])
        if int(trade["entry_ts"]) <= blocked_until.get(symbol, -1):
            rejected.append({"intent_sha": trade["intent_sha"], "reason": "PYRAMIDING_OR_COOLDOWN_BLOCK", "symbol": symbol})
            continue
        kept.append(trade)
        blocked_until[symbol] = int(trade["exit_ts"]) + cooldown_bars * interval_ms
    kept.sort(key=lambda x: (int(x["entry_ts"]), str(x["symbol"])))
    values = [float(x["net_bps"]) for x in kept]
    gross = [float(x["gross_bps"]) for x in kept]
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    receipt["raw_completed_trades_before_policy_ownership"] = int(receipt.get("completed_trades") or 0)
    receipt["trades"] = kept
    receipt["completed_trades"] = len(kept)
    receipt["intent_count"] = len(kept)
    receipt["metrics"] = {
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "net_profit_factor": v1.profit_factor(gp, gl),
        "net_payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_bps": v1.max_drawdown(values),
    }
    receipt["state"] = "WAIT_FRESH_PROSPECTIVE_DATA" if not kept else "A1_REBUILT_ECONOMICS_ACTIVE"
    receipt["policy_fidelity"] = {
        "state": "PASS_POLICY_OWNERSHIP_ENFORCED",
        "pyramiding": False,
        "cooldown_bars": cooldown_bars,
        "one_entry_per_transition": True,
        "raw_trade_count": len(kept) + len(rejected),
        "admitted_trade_count": len(kept),
        "rejected_trade_count": len(rejected),
        "rejected_intents_sha256": stable_sha(rejected),
    }
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--boundary-utc")
    parser.add_argument("--mode", choices=("development", "prospective"), required=True)
    args = parser.parse_args()

    ledger = json.loads(v1.LEDGER_PATH.read_text())
    original_boundary = str(ledger["strategies"]["trend_rider"]["prospective_boundary_utc"])
    boundary = args.boundary_utc or original_boundary
    if args.mode == "prospective" and not args.boundary_utc:
        raise RuntimeError("PROSPECTIVE_BOUNDARY_REQUIRED")
    ledger["strategies"]["trend_rider"]["prospective_boundary_utc"] = boundary
    ledger["strategies"]["trend_rider"]["status"] = "ACTIVE"

    original_load_policy = v1.load_policy
    original_ledger_path = v1.LEDGER_PATH
    with tempfile.TemporaryDirectory(prefix="trend-rider-challenger-") as tmp:
        ledger_path = Path(tmp) / "ledger.json"
        ledger_path.write_text(json.dumps(ledger, sort_keys=True))

        def load_policy(_: str, __: dict[str, Any]):
            return policy, POLICY_PATH, v1.git_blob_sha(POLICY_PATH)

        v1.load_policy = load_policy
        v1.LEDGER_PATH = ledger_path
        old_argv = sys.argv
        try:
            sys.argv = [
                "a1_exact25_generic_evaluator_v2",
                "--strategy-id", "trend_rider",
                "--symbols", args.symbols,
                "--out", args.out,
            ]
            v2.main()
        finally:
            sys.argv = old_argv
            v1.load_policy = original_load_policy
            v1.LEDGER_PATH = original_ledger_path

    output_path = Path(args.out)
    receipt = enforce_policy_ownership(json.loads(output_path.read_text()))
    receipt.update({
        "schema_version": "zel.a1.trend_rider.first_confirmation_economics.v1",
        "challenger_id": "trend_rider_first_confirmation_v1",
        "parent_strategy_id": "trend_rider",
        "evaluation_mode": args.mode,
        "original_parent_boundary_utc": original_boundary,
        "prospective_boundary_utc": boundary if args.mode == "prospective" else None,
        "changed_axis": "signal_transition_timing",
        "parameter_sweep": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    })
    receipt["receipt_sha256"] = stable_sha({k: value for k, value in receipt.items() if k != "receipt_sha256"})
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print("A1_TREND_RIDER_FIRST_CONFIRMATION=" + json.dumps({
        "mode": args.mode,
        "state": receipt.get("state"),
        "completed_trades": receipt.get("completed_trades"),
        "metrics": receipt.get("metrics"),
        "receipt_sha256": receipt.get("receipt_sha256"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
