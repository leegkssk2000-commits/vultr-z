#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.research.rebuild import a1_trend_rider_transition_freshness_frozen_w123_ab_v1 as ab
from backend.research.rebuild import a1_trend_rider_momentum_ab_v1 as helper

SCHEMA = "zel.a1_trend_rider_transition_freshness_hardening_router.v1"
MIN_PROFIT_PILOT_TRADES = 10
MIN_CERT_PILOT_TRADES = 12
MIN_HARDENING_TRADES = 25
CHILD_POLICY = "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py"


def _write(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row["receipt_sha256"] = helper._sha(row)
    path.write_text(json.dumps(row, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(out: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="trend_rider_transition_hardening_") as td:
        td_path = Path(td)
        child_path = td_path / "transition_child_current.json"
        hardening_path = td_path / "transition_child_h4_h5.json"
        child = ab._run_exact(child_path, child=True)

        if child.get("strategy_id") != "trend_rider":
            raise RuntimeError("STRATEGY_ID_MISMATCH")
        if str(child.get("policy_path") or "") != CHILD_POLICY:
            raise RuntimeError("TRANSITION_CHILD_POLICY_MISMATCH")
        if child.get("execution_authority") != "NONE" or child.get("order_authority") != "BLOCKED" or child.get("live_trade_authority") != "BLOCKED":
            raise RuntimeError("AUTHORITY_BOUNDARY_VIOLATION")
        if list(child.get("integrity_defects") or []):
            raise RuntimeError("CHILD_INTEGRITY_DEFECT")
        if int(child.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("CHILD_LOOKAHEAD_DEFECT")

        completed = int(child.get("completed_trades") or 0)
        base = {
            "schema_version": SCHEMA,
            "strategy_id": "trend_rider",
            "changed_axis": "TRANSITION_FRESHNESS_REENTRY_SUPPRESSION_ONLY",
            "policy_path": CHILD_POLICY,
            "completed_trades": completed,
            "minimum_profit_pilot_trades": MIN_PROFIT_PILOT_TRADES,
            "minimum_cert_pilot_trades": MIN_CERT_PILOT_TRADES,
            "minimum_hardening_trades": MIN_HARDENING_TRADES,
            "profit_pilot_sample_met": completed >= MIN_PROFIT_PILOT_TRADES,
            "cert_pilot_sample_met": completed >= MIN_CERT_PILOT_TRADES,
            "strict_hardening_sample_met": completed >= MIN_HARDENING_TRADES,
            "strict_reference_only": True,
            "blocks_top3_profit_a2_a3_pilot": False,
            "primary_progress_route": "A1_TOP3_PROFITABILITY_TWO_LANE_ROUTER_V4",
            "strict_reference_contract": "25T_H4_H5_CONTINUES_IN_PARALLEL_AND_DOES_NOT_RESET_OR_BLOCK_10T_12T_PILOT_ROUTE",
            "sample_gap": max(0, MIN_HARDENING_TRADES - completed),
            "pilot_sample_gap": max(0, MIN_CERT_PILOT_TRADES - completed),
            "child_current_receipt_sha256": child.get("receipt_sha256"),
            "child_current_metrics": child.get("metrics"),
            "source_quality_state": (child.get("source_quality_gate") or {}).get("state") if isinstance(child.get("source_quality_gate"), dict) else None,
            "integrity_defects": list(child.get("integrity_defects") or []),
            "leakage_lookahead": int(child.get("leakage_lookahead") or 0),
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
        }

        if completed < MIN_HARDENING_TRADES:
            base.update({
                "state": "WAIT_TRANSITION_FRESHNESS_H4_H5_MIN_SAMPLE",
                "h4_state": "NOT_RUN_MIN_SAMPLE",
                "h5_state": "NOT_RUN_MIN_SAMPLE",
                "next": "COLLECT_STRICT_REFERENCE_IN_PARALLEL__DO_NOT_BLOCK_TOP3_V4_PILOT",
            })
            _write(out, base)
            return base

        cmd = [
            sys.executable,
            "-m",
            "backend.research.rebuild.a1_trend_rider_h4_h5_hardening_v1",
            "--receipt",
            str(child_path),
            "--out",
            str(hardening_path),
        ]
        subprocess.run(cmd, check=True)
        hardening = json.loads(hardening_path.read_text(encoding="utf-8"))
        base.update({
            "state": "PASS_TRANSITION_FRESHNESS_HARDENING" if hardening.get("state") == "PASS_HARDENING_EVIDENCE" else "HOLD_TRANSITION_FRESHNESS_HARDENING",
            "h4_state": (hardening.get("h4_receipt") or {}).get("state"),
            "h5_state": (hardening.get("h5_receipt") or {}).get("state"),
            "hardening_receipt": hardening,
            "next": "A2_COST_REVALIDATION_THEN_A3_FRESH_DURABILITY" if hardening.get("state") == "PASS_HARDENING_EVIDENCE" else "PRESERVE_EVIDENCE_AND_ROUTE_TO_DISTINCT_CAUSAL_AXIS",
        })
        _write(out, base)
        return base


def self_test() -> int:
    assert MIN_PROFIT_PILOT_TRADES == 10
    assert MIN_CERT_PILOT_TRADES == 12
    assert MIN_HARDENING_TRADES == 25
    assert MIN_PROFIT_PILOT_TRADES < MIN_CERT_PILOT_TRADES < MIN_HARDENING_TRADES
    assert CHILD_POLICY.endswith("trend_rider_transition_freshness_child_policy_v1.py")
    print("PASS_A1_TREND_RIDER_TRANSITION_FRESHNESS_HARDENING_ROUTER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_transition_freshness_hardening_router_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    row = run(args.out)
    print("A1_TREND_RIDER_TRANSITION_HARDENING=" + json.dumps({
        "state": row["state"],
        "completed_trades": row["completed_trades"],
        "minimum_profit_pilot_trades": row["minimum_profit_pilot_trades"],
        "minimum_cert_pilot_trades": row["minimum_cert_pilot_trades"],
        "minimum_hardening_trades": row["minimum_hardening_trades"],
        "pilot_sample_gap": row["pilot_sample_gap"],
        "sample_gap": row["sample_gap"],
        "blocks_top3_profit_a2_a3_pilot": row["blocks_top3_profit_a2_a3_pilot"],
        "h4_state": row["h4_state"],
        "h5_state": row["h5_state"],
        "next": row["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
