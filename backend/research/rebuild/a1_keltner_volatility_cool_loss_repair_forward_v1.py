#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_keltner_h4_h5_hardening_v1 as hardener
from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "backend/research/rebuild/keltner_trend_volatility_cool_child_policy_v1.py"
PREREG = ROOT / "backend/research/rebuild/a1_keltner_volatility_cool_loss_repair_prereg_v1.json"
MIN_TRADES = 25
SCHEMA = "zel.a1.keltner.volatility_cool_loss_repair.forward.v3"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
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
    prereg = read(PREREG)
    boundary = str(prereg["fresh_boundary_utc"])
    out.parent.mkdir(parents=True, exist_ok=True)
    shadow_path = out.parent / "_keltner_fresh_shadow.json"
    base, fastpath = run_terminal_shadow(
        strategy_id="keltner_trend",
        policy_path=POLICY,
        fresh_boundary_utc=boundary,
        out=shadow_path,
    )
    try:
        if str(base.get("policy_path") or "") != str(POLICY.relative_to(ROOT)):
            raise RuntimeError("KELTNER_COOL_POLICY_MISMATCH")
        if list(base.get("integrity_defects") or []):
            raise RuntimeError("KELTNER_COOL_INTEGRITY_DEFECT")
        if int(base.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("KELTNER_COOL_LOOKAHEAD_DEFECT")
        trades = [dict(x) for x in (base.get("trades") or [])]
        row = dict(base)
        row.update({
            "schema_version": SCHEMA,
            "candidate_id": prereg["candidate_id"],
            "changed_axis": prereg["changed_axis"],
            "fresh_boundary_utc": boundary,
            "completed_trades": len(trades),
            "trades": trades,
            "metrics": metrics(trades),
            "sample_gap_to_25": max(0, MIN_TRADES - len(trades)),
            "minimum_fresh_trades": MIN_TRADES,
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
            "h4_state": "NOT_RUN_MIN_SAMPLE",
            "h5_state": "NOT_RUN_MIN_SAMPLE",
            "hardening_receipt": None,
        })
        row["receipt_sha256"] = ev.stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})

        source_state = str((row.get("source_quality_gate") or {}).get("state") or "")
        if source_state == "FAIL":
            row["state"] = "HOLD_FRESH_SOURCE_QUALITY"
            row["next"] = "REPAIR_SOURCE_ONLY_NO_STRATEGY_CHANGE"
        elif len(trades) < MIN_TRADES:
            row["state"] = "WAIT_FRESH_25"
            row["next"] = "CONTINUE_HOURLY_FRESH_COLLECTION"
        else:
            with tempfile.TemporaryDirectory(prefix="keltner_auto_hardening_") as td:
                candidate_path = Path(td) / "candidate.json"
                hardening_path = Path(td) / "hardening.json"
                candidate_path.write_text(json.dumps(row, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
                hardening = hardener.run(candidate_path, hardening_path)
            row["hardening_receipt"] = hardening
            row["h4_state"] = str((hardening.get("h4_receipt") or {}).get("state") or "")
            row["h5_state"] = str((hardening.get("h5_receipt") or {}).get("state") or "")
            if hardening.get("state") == "PASS_HARDENING_EVIDENCE":
                row["state"] = "PASS_FRESH_KELTNER_HARDENING"
                row["next"] = "A2_COST_REVALIDATION_THEN_A3_FRESH_DURABILITY"
            else:
                row["state"] = "HOLD_FRESH_KELTNER_HARDENING"
                row["next"] = "PRESERVE_EVIDENCE_AND_ROUTE_NEXT_DISTINCT_PREENTRY_AXIS"

        row["receipt_sha256"] = ev.stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
        out.write_text(json.dumps(row, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return row
    finally:
        if shadow_path.exists():
            shadow_path.unlink()


def self_test() -> int:
    prereg = read(PREREG)
    assert prereg["fresh_boundary_utc"] == "2026-08-23T07:15:00Z"
    assert prereg["numeric_threshold_sweep"] is False
    assert MIN_TRADES == 25
    print("PASS_A1_KELTNER_VOLATILITY_COOL_LOSS_REPAIR_FORWARD_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_volatility_cool_loss_repair_forward_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    row = run(args.out)
    print(json.dumps({
        "state": row["state"],
        "completed_trades": row["completed_trades"],
        "sample_gap_to_25": row["sample_gap_to_25"],
        "h4_state": row["h4_state"],
        "h5_state": row["h5_state"],
        "next": row["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
