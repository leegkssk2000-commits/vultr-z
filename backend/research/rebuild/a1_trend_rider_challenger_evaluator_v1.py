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
    receipt = json.loads(output_path.read_text())
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
