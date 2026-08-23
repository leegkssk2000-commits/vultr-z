#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import a2_forward_cost_turnover_v1 as a2
from backend.research.prep import a3_exact25_forward_durability_v3 as a3
from backend.research.rebuild import a1_trend_rider_transition_freshness_frozen_w123_ab_v1 as tr_ab

ROOT = Path(__file__).resolve().parents[3]
TRENDMA = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_long_fresh25_latest.json"
KELTNER = ROOT / "backend/research/rebuild/a1_regime_ema21_reclaim_fresh_latest.json"
A3_CONTEXT = ROOT / "backend/research/prep/a3_prospective_context_latest.json"
TOP3 = (
    "trend_rider_transition_freshness",
    "trend_ma_macd_chase_atr_up_long_good_v1",
    "regime_ema21_reclaim_v1",
)
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}


def stable(value: Any) -> str:
    return a3.stable_sha(value)


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def metrics(receipt: Mapping[str, Any]) -> dict[str, Any]:
    m = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    trades = [x for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    n = int(receipt.get("completed_trades") or m.get("completed_trades") or len(trades) or 0)
    net = m.get("net_pnl_bps", receipt.get("net_pnl_bps"))
    exp = m.get("net_expectancy_bps", receipt.get("net_expectancy_bps"))
    pf = m.get("net_profit_factor", m.get("profit_factor", receipt.get("profit_factor")))
    wr = m.get("win_rate", receipt.get("win_rate"))
    if net is None and trades:
        net = sum(float(x.get("net_bps") or 0.0) for x in trades)
    if exp is None and net is not None and n:
        exp = float(net) / n
    if pf is None and trades:
        gp = sum(max(0.0, float(x.get("net_bps") or 0.0)) for x in trades)
        gl = -sum(min(0.0, float(x.get("net_bps") or 0.0)) for x in trades)
        pf = gp / gl if gl > 0 else None
    if wr is None and trades:
        wr = sum(float(x.get("net_bps") or 0.0) > 0 for x in trades) / len(trades)
    return {
        "completed_trades": n,
        "win_rate": wr,
        "net_pnl_bps": net,
        "net_expectancy_bps": exp,
        "profit_factor": pf,
    }


def hardening_pass(receipt: Mapping[str, Any]) -> bool:
    hard = receipt.get("hardening_receipt") if isinstance(receipt.get("hardening_receipt"), Mapping) else {}
    return str(hard.get("state") or "") == "PASS_HARDENING_EVIDENCE"


def a1_status(receipt: Mapping[str, Any], *, explicit_hardening: Mapping[str, Any] | None = None) -> dict[str, Any]:
    m = metrics(receipt)
    completed = int(m["completed_trades"] or 0)
    source = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), Mapping) else {}
    defects = list(receipt.get("integrity_defects") or [])
    lookahead = int(receipt.get("leakage_lookahead") or 0)
    hard = dict(explicit_hardening or {})
    if not hard:
        hr = receipt.get("hardening_receipt")
        hard = dict(hr) if isinstance(hr, Mapping) else {}

    blockers: list[str] = []
    if completed < 25:
        blockers.append(f"FRESH_TRADES:{completed}<25")
    if source.get("state") != "PASS":
        blockers.append(f"SOURCE_QUALITY:{source.get('state')}")
    if defects:
        blockers.append(f"INTEGRITY_DEFECTS:{len(defects)}")
    if lookahead != 0:
        blockers.append(f"LOOKAHEAD:{lookahead}")
    if m["net_pnl_bps"] is None or float(m["net_pnl_bps"]) <= 0:
        blockers.append(f"NET_PNL_BPS:{m['net_pnl_bps']}")
    if m["net_expectancy_bps"] is None or float(m["net_expectancy_bps"]) <= 0:
        blockers.append(f"EXPECTANCY_BPS:{m['net_expectancy_bps']}")
    if m["profit_factor"] is None or float(m["profit_factor"]) < 1.0:
        blockers.append(f"PROFIT_FACTOR:{m['profit_factor']}")
    if hard.get("state") != "PASS_HARDENING_EVIDENCE":
        blockers.append(f"HARDENING:{hard.get('state') or 'NOT_RUN'}")

    passed = not blockers
    return {
        "state": "PASS_A1_PROFITABILITY_SURVIVOR" if passed else ("WAIT_A1_PROFITABILITY_SURVIVOR" if completed < 25 else "HOLD_A1_PROFITABILITY_SURVIVOR"),
        "pass": passed,
        "metrics": m,
        "hardening_state": hard.get("state"),
        "h4_state": (hard.get("h4_receipt") or {}).get("state") if isinstance(hard.get("h4_receipt"), Mapping) else receipt.get("h4_state"),
        "h5_state": (hard.get("h5_receipt") or {}).get("state") if isinstance(hard.get("h5_receipt"), Mapping) else receipt.get("h5_state"),
        "blockers": blockers,
    }


def transition(receipt: Mapping[str, Any]) -> dict[str, Any]:
    row = {
        "schema_version": "zel.a1.top3_profitability_transition.v1",
        "state": "PASS_A1_CAUSAL_READY_FOR_A2",
        "candidate_id": str(receipt["strategy_id"]),
        "tiering": {
            "a1_tier": "A1_SURVIVOR",
            "a2_entry_allowed": True,
            "activation": {"mode": "FRESH_PROSPECTIVE_PROFITABILITY"},
        },
        "evidence": {"lineage": {"candidate_receipt_sha256": receipt.get("receipt_sha256")}},
        **AUTH,
    }
    row["receipt_sha256"] = stable(row)
    return row


def run_a2_a3(receipt: Mapping[str, Any], a1: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    if a1.get("pass") is not True:
        return None, None, []
    errors: list[str] = []
    try:
        a2_row = a2.evaluate(transition(receipt), receipt)
    except Exception as exc:
        return None, None, [f"A2_RUNTIME:{type(exc).__name__}:{exc}"]
    if a2_row.get("state") != "PASS_A2_COST_TURNOVER":
        return a2_row, None, errors
    try:
        a3_row = a3.evaluate(receipt, a2_row, context)
    except Exception as exc:
        return a2_row, None, [f"A3_RUNTIME:{type(exc).__name__}:{exc}"]
    return a2_row, a3_row, errors


def trend_rider_current(tmp: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    child_path = tmp / "trend_rider_transition_child.json"
    hard_path = tmp / "trend_rider_hardening.json"
    child = tr_ab._run_exact(child_path, child=True)
    if int(child.get("completed_trades") or 0) < 25:
        return child, {"state": "NOT_RUN_MIN_SAMPLE"}
    subprocess.run([
        sys.executable,
        "-m",
        "backend.research.rebuild.a1_trend_rider_h4_h5_hardening_v1",
        "--receipt", str(child_path),
        "--out", str(hard_path),
    ], check=True)
    hard = read(hard_path)
    return child, hard


def candidate_row(identity: str, receipt: Mapping[str, Any], hard: Mapping[str, Any] | None, context: Mapping[str, Any]) -> dict[str, Any]:
    a1 = a1_status(receipt, explicit_hardening=hard)
    a2_row, a3_row, runtime_errors = run_a2_a3(receipt, a1, context)
    a2_state = a2_row.get("state") if a2_row else "NOT_RUN_A1_REQUIRED"
    a3_state = a3_row.get("state") if a3_row else "NOT_RUN_A2_REQUIRED"
    survivor = a1["pass"] and a2_state == "PASS_A2_COST_TURNOVER" and a3_state == "PASS_A3_GLOBAL_DURABILITY"
    blockers = list(a1["blockers"])
    if a1["pass"] and a2_state != "PASS_A2_COST_TURNOVER":
        blockers.append(f"A2:{a2_state}")
    if a2_state == "PASS_A2_COST_TURNOVER" and a3_state != "PASS_A3_GLOBAL_DURABILITY":
        blockers.append(f"A3:{a3_state}")
    blockers.extend(runtime_errors)
    return {
        "identity": identity,
        "strategy_id": receipt.get("strategy_id"),
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "a1": a1,
        "a2_state": a2_state,
        "a2": a2_row,
        "a3_state": a3_state,
        "a3": a3_row,
        "economic_survivor": survivor,
        "blockers": blockers,
        "next": "SURVIVOR_READY_FOR_G4_COUNT" if survivor else "FIX_ONLY_CURRENT_GATE_BLOCKER_OR_ACCUMULATE_EXISTING_FRESH_EVIDENCE",
        **AUTH,
    }


def run(out: Path) -> dict[str, Any]:
    context = read(A3_CONTEXT)
    with tempfile.TemporaryDirectory(prefix="top3_profitability_") as td:
        tr_receipt, tr_hard = trend_rider_current(Path(td))
        trendma = read(TRENDMA)
        keltner = read(KELTNER)

        rows = [
            candidate_row(TOP3[0], tr_receipt, tr_hard, context),
            candidate_row(TOP3[1], trendma, None, context),
            candidate_row(TOP3[2], keltner, None, context),
        ]

    a1_count = sum(x["a1"]["pass"] for x in rows)
    a2_count = sum(x["a2_state"] == "PASS_A2_COST_TURNOVER" for x in rows)
    a3_count = sum(x["a3_state"] == "PASS_A3_GLOBAL_DURABILITY" for x in rows)
    survivor_count = sum(x["economic_survivor"] for x in rows)
    result = {
        "schema_version": "zel.a1.top3_profitability_survivor_router.v1",
        "state": "PASS_TOP3_ECONOMIC_SURVIVORS_READY" if survivor_count >= 2 else "HOLD_TOP3_ECONOMIC_SURVIVORS_INCOMPLETE",
        "profitability_first": True,
        "top3_only": True,
        "top3_identities": list(TOP3),
        "new_strategy_generation_enabled": False,
        "new_filter_generation_enabled": False,
        "infrastructure_pass_never_counts_as_survivor": True,
        "retrospective_discovery_never_counts_as_survivor": True,
        "a1_pass_count": a1_count,
        "a2_pass_count": a2_count,
        "a3_pass_count": a3_count,
        "economic_survivor_count": survivor_count,
        "g4_minimum_survivors": 2,
        "candidates": rows,
        "next": "ENTER_G4_WITH_2_TO_3_SURVIVORS" if survivor_count >= 2 else "KEEP_TOP3_FIXED_AND_ADVANCE_ONLY_THEIR_CURRENT_A1_A2_A3_BLOCKERS",
        **AUTH,
    }
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert len(TOP3) == 3 and len(set(TOP3)) == 3
    fake = {
        "completed_trades": 25,
        "metrics": {"net_pnl_bps": 100.0, "net_expectancy_bps": 4.0, "net_profit_factor": 1.2, "win_rate": 0.52},
        "source_quality_gate": {"state": "PASS"},
        "integrity_defects": [], "leakage_lookahead": 0,
    }
    p = a1_status(fake, explicit_hardening={"state": "PASS_HARDENING_EVIDENCE"})
    assert p["pass"] is True and p["state"] == "PASS_A1_PROFITABILITY_SURVIVOR"
    q = a1_status({**fake, "completed_trades": 24}, explicit_hardening={"state": "PASS_HARDENING_EVIDENCE"})
    assert q["pass"] is False and q["state"].startswith("WAIT_")
    print("PASS_A1_TOP3_PROFITABILITY_SURVIVOR_ROUTER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_top3_profitability_survivor_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    row = run(args.out)
    print("TOP3_PROFITABILITY=" + json.dumps({
        "state": row["state"],
        "A1": row["a1_pass_count"],
        "A2": row["a2_pass_count"],
        "A3": row["a3_pass_count"],
        "survivors": row["economic_survivor_count"],
        "candidates": [{"id": x["identity"], "A1": x["a1"]["state"], "A2": x["a2_state"], "A3": x["a3_state"], "blockers": x["blockers"][:4]} for x in row["candidates"]],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
