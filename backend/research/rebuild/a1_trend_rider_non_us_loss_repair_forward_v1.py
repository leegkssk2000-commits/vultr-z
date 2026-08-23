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
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact
from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "backend/research/rebuild/trend_rider_transition_freshness_non_us_child_policy_v1.py"
PREREG = ROOT / "backend/research/rebuild/a1_trend_rider_non_us_loss_repair_prereg_v1.json"
MIN_TRADES = 25
SCHEMA = "zel.a1.trend_rider.non_us_loss_repair.forward.v2"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    gross = [float(x["gross_bps"]) for x in trades]
    net = [float(x["net_bps"]) for x in trades]
    wins = [x for x in net if x > 0]
    losses = [-x for x in net if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    return {
        "trade_count": len(trades),
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": sum(net) / len(net) if net else None,
        "net_profit_factor": ev.profit_factor(gp, gl),
        "net_payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
        "win_rate": len(wins) / len(net) if net else None,
        "max_drawdown_bps": ev.max_drawdown(net),
    }


def run(out: Path) -> dict[str, Any]:
    prereg = _read(PREREG)
    boundary = str(prereg["fresh_boundary_utc"])
    with tempfile.TemporaryDirectory(prefix="trend_rider_non_us_forward_") as td:
        td_path = Path(td)
        base_path = td_path / "fresh_child.json"
        base, fastpath = run_terminal_shadow(
            strategy_id="trend_rider",
            policy_path=POLICY,
            fresh_boundary_utc=boundary,
            out=base_path,
        )

        if str(base.get("policy_path") or "") != str(POLICY.relative_to(ROOT)):
            raise RuntimeError("NON_US_CHILD_POLICY_MISMATCH")
        if list(base.get("integrity_defects") or []):
            raise RuntimeError("NON_US_CHILD_INTEGRITY_DEFECT")
        if int(base.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("NON_US_CHILD_LOOKAHEAD_DEFECT")
        trades = [dict(x) for x in (base.get("trades") or [])]
        if any(str(base.get("boundary_utc") or "") != boundary for _ in [0]):
            raise RuntimeError("FRESH_BOUNDARY_MISMATCH")

        candidate = dict(base)
        candidate.update({
            "schema_version": SCHEMA,
            "candidate_id": prereg["candidate_id"],
            "changed_axis": prereg["changed_axis"],
            "fresh_boundary_utc": boundary,
            "completed_trades": len(trades),
            "trades": trades,
            "metrics": _metrics(trades),
            "preboundary_outcomes_counted": False,
            "preboundary_data_feature_warmup_only": True,
            "fresh_boundary_shadow_replay": fastpath,
            "canonical_exact25_ledger_mutation": False,
            "strategy_parameters_changed": False,
            "thresholds_changed": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "protected_mutations": 0,
            "sample_gap_to_25": max(0, MIN_TRADES - len(trades)),
            "prereg_policy_blob_sha": prereg["policy_blob_sha"],
            "prereg_policy_freeze_commit": prereg["policy_freeze_commit"],
            "prereg_receipt_sha256": ev.stable_sha(prereg),
        })

        h4_state = "NOT_RUN_MIN_SAMPLE"
        h5_state = "NOT_RUN_MIN_SAMPLE"
        hardening = None
        source_state = str((candidate.get("source_quality_gate") or {}).get("state") or "")
        if source_state == "FAIL":
            state = "HOLD_FRESH_SOURCE_QUALITY"
            nxt = "REPAIR_SOURCE_ONLY_NO_STRATEGY_CHANGE"
        elif len(trades) < MIN_TRADES:
            state = "WAIT_FRESH_25"
            nxt = "CONTINUE_HOURLY_FRESH_COLLECTION"
        else:
            candidate["receipt_sha256"] = ev.stable_sha({k: v for k, v in candidate.items() if k != "receipt_sha256"})
            candidate_path = td_path / "fresh_candidate.json"
            candidate_path.write_text(json.dumps(candidate, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            hard_path = td_path / "hardening.json"
            subprocess.run([
                sys.executable, "-m", "backend.research.rebuild.a1_trend_rider_h4_h5_hardening_v1",
                "--receipt", str(candidate_path), "--out", str(hard_path),
            ], check=True)
            hardening = _read(hard_path)
            h4_state = str((hardening.get("h4_receipt") or {}).get("state") or "")
            h5_state = str((hardening.get("h5_receipt") or {}).get("state") or "")
            if hardening.get("state") == "PASS_HARDENING_EVIDENCE":
                state = "PASS_FRESH_NON_US_HARDENING"
                nxt = "COMPARE_AGAINST_UNMODIFIED_TRANSITION_INCUMBENT_THEN_A2_COST_REVALIDATION"
            else:
                state = "HOLD_FRESH_NON_US_HARDENING"
                nxt = "PRESERVE_EVIDENCE_AND_ROUTE_NEXT_DISTINCT_PREENTRY_AXIS"

        candidate.update({
            "state": state,
            "minimum_fresh_trades": MIN_TRADES,
            "h4_state": h4_state,
            "h5_state": h5_state,
            "hardening_receipt": hardening,
            "next": nxt,
        })
        candidate["receipt_sha256"] = ev.stable_sha({k: v for k, v in candidate.items() if k != "receipt_sha256"})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(candidate, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return candidate


def self_test() -> int:
    prereg = _read(PREREG)
    assert prereg["changed_axis"] == "FROZEN_H5_US_SESSION_EXCLUSION_ONLY"
    assert prereg["fresh_boundary_utc"] == "2026-08-23T08:00:00Z"
    assert prereg["preboundary_outcomes_counted"] is False
    assert prereg["numeric_threshold_sweep"] is False
    print("PASS_A1_TREND_RIDER_NON_US_LOSS_REPAIR_FORWARD_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_non_us_loss_repair_forward_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "completed_trades": r["completed_trades"],
        "sample_gap_to_25": r["sample_gap_to_25"],
        "h4_state": r["h4_state"],
        "h5_state": r["h5_state"],
        "fastpath": r["fresh_boundary_shadow_replay"],
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
