#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
MIN_TRADES = 25
SCHEMA = "zel.a1.keltner.parent_hardening_router.v1"


def _read(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return row


def run(out: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="keltner-parent-hardening-") as td:
        work = Path(td)
        candidate_path = work / "keltner_parent.json"
        cp = subprocess.run([
            sys.executable, "-m", "backend.research.rebuild.a1_exact25_generic_evaluator_v2",
            "--strategy-id", "keltner_trend",
            "--out", str(candidate_path),
            "--terminal-replay",
        ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if cp.returncode != 0 or not candidate_path.is_file():
            raise RuntimeError("KELTNER_PARENT_TERMINAL_REPLAY_FAILED:" + (cp.stderr or cp.stdout)[-1200:])
        candidate = _read(candidate_path)
        completed = int(candidate.get("completed_trades") or 0)
        if str(candidate.get("strategy_id") or "") != "keltner_trend":
            raise RuntimeError("KELTNER_PARENT_ID_MISMATCH")
        if list(candidate.get("integrity_defects") or []):
            raise RuntimeError("KELTNER_PARENT_INTEGRITY_DEFECT")
        if int(candidate.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("KELTNER_PARENT_LOOKAHEAD_DEFECT")

        result: dict[str, Any] = {
            "schema_version": SCHEMA,
            "strategy_id": "keltner_trend",
            "candidate_id": candidate.get("candidate_id") or "keltner_trend_parent",
            "completed_trades": completed,
            "minimum_hardening_trades": MIN_TRADES,
            "sample_gap": max(0, MIN_TRADES - completed),
            "win_rate": (candidate.get("metrics") or {}).get("win_rate", candidate.get("win_rate")),
            "net_pnl_bps": (candidate.get("metrics") or {}).get("net_pnl_bps", candidate.get("net_pnl_bps")),
            "net_expectancy_bps": (candidate.get("metrics") or {}).get("net_expectancy_bps", candidate.get("net_expectancy_bps")),
            "profit_factor": (candidate.get("metrics") or {}).get("net_profit_factor", candidate.get("profit_factor")),
            "candidate_receipt_sha256": candidate.get("receipt_sha256"),
            "prospective_boundary_utc": candidate.get("prospective_boundary_utc") or candidate.get("boundary_utc"),
            "source_quality_state": (candidate.get("source_quality_gate") or {}).get("state"),
            "integrity_defects": [],
            "leakage_lookahead": 0,
            "canonical_ledger_mutation": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
        }
        if completed < MIN_TRADES:
            result.update({
                "state": "WAIT_KELTNER_PARENT_HARDENING_25",
                "h4_state": "NOT_RUN_MIN_SAMPLE",
                "h5_state": "NOT_RUN_MIN_SAMPLE",
                "hardening_receipt": None,
                "next": "CONTINUE_FRESH_PARENT_COLLECTION",
            })
        else:
            hard_path = work / "hardening.json"
            hp = subprocess.run([
                sys.executable, "-m", "backend.research.rebuild.a1_keltner_h4_h5_hardening_v1",
                "--receipt", str(candidate_path), "--out", str(hard_path),
            ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if hp.returncode != 0 or not hard_path.is_file():
                raise RuntimeError("KELTNER_H4_H5_EXECUTION_FAILED:" + (hp.stderr or hp.stdout)[-1200:])
            hard = _read(hard_path)
            h4 = str((hard.get("h4_receipt") or {}).get("state") or "")
            h5 = str((hard.get("h5_receipt") or {}).get("state") or "")
            passed = hard.get("state") == "PASS_HARDENING_EVIDENCE"
            result.update({
                "state": "PASS_KELTNER_PARENT_HARDENING" if passed else "HOLD_KELTNER_PARENT_HARDENING",
                "h4_state": h4,
                "h5_state": h5,
                "hardening_receipt": hard,
                "next": "A2_COST_REVALIDATION_THEN_A3" if passed else "DECOMPOSE_FAILED_H4_H5_AND_PRESERVE_PARENT_EDGE",
            })
        result["receipt_sha256"] = ev.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return result


def self_test() -> int:
    assert MIN_TRADES == 25
    print("PASS_A1_KELTNER_PARENT_HARDENING_ROUTER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_parent_hardening_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"], "trades": r["completed_trades"], "wr": r["win_rate"],
        "net_pnl_bps": r["net_pnl_bps"], "h4": r["h4_state"], "h5": r["h5_state"], "next": r["next"]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
