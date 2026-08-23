#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
POLICY = ROOT / "backend/research/rebuild/trend_rider_transition_freshness_non_us_child_policy_v1.py"
PREREG = ROOT / "backend/research/rebuild/a1_trend_rider_non_us_loss_repair_prereg_v1.json"
MIN_TRADES = 25
SCHEMA = "zel.a1.trend_rider.non_us_loss_repair.forward.v1"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _parse_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


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


def _run_child(out: Path) -> dict[str, Any]:
    inventory = _read(INVENTORY)
    inventory["strategies"]["trend_rider"]["policy_owner"] = str(POLICY.relative_to(ROOT))
    with tempfile.TemporaryDirectory(prefix="trend_rider_non_us_shadow_") as td:
        inv = Path(td) / "inventory.json"
        inv.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        old_inventory = exact.v1.INVENTORY_PATH
        old_argv = sys.argv[:]
        try:
            exact.v1.INVENTORY_PATH = inv
            sys.argv = [old_argv[0], "--strategy-id", "trend_rider", "--out", str(out), "--terminal-replay"]
            exact.main()
        finally:
            exact.v1.INVENTORY_PATH = old_inventory
            sys.argv = old_argv
    return _read(out)


def _fresh_source(base: dict[str, Any], boundary_ms: int) -> dict[str, Any]:
    source = base.get("source") if isinstance(base.get("source"), dict) else {}
    interval = str(source.get("interval") or "1h")
    rows = []
    symbols = [str(x.get("symbol")) for x in (source.get("symbols") or []) if isinstance(x, dict) and x.get("symbol")]
    for symbol in sorted(set(symbols or ["BTC-USDT", "ETH-USDT"])):
        bars = ev.fetch_bars(symbol, interval, 1000)
        post = [x for x in bars if int(x["ts_ms"]) >= boundary_ms]
        rows.append({
            "symbol": symbol,
            "bars_total": len(bars),
            "bars_post_boundary": len(post),
            "first_post_boundary_ts": int(post[0]["ts_ms"]) if post else None,
            "last_post_boundary_ts": int(post[-1]["ts_ms"]) if post else None,
        })
    return {"endpoint": source.get("endpoint", "/openApi/swap/v3/quote/klines"), "interval": interval, "symbols": rows}


def run(out: Path) -> dict[str, Any]:
    prereg = _read(PREREG)
    boundary = str(prereg["fresh_boundary_utc"])
    boundary_ms = _parse_ms(boundary)
    with tempfile.TemporaryDirectory(prefix="trend_rider_non_us_forward_") as td:
        base_path = Path(td) / "all_child.json"
        base = _run_child(base_path)

        if str(base.get("policy_path") or "") != str(POLICY.relative_to(ROOT)):
            raise RuntimeError("NON_US_CHILD_POLICY_MISMATCH")
        if list(base.get("integrity_defects") or []):
            raise RuntimeError("NON_US_CHILD_INTEGRITY_DEFECT")
        if int(base.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("NON_US_CHILD_LOOKAHEAD_DEFECT")
        if (base.get("terminal_replay") or {}).get("canonical_ledger_mutated") is not False:
            raise RuntimeError("CANONICAL_LEDGER_MUTATION_GUARD")

        fresh = [dict(x) for x in (base.get("trades") or []) if int(x.get("signal_ts") or 0) >= boundary_ms]
        fresh.sort(key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
        source = _fresh_source(base, boundary_ms)
        candidate = dict(base)
        candidate.update({
            "schema_version": SCHEMA,
            "candidate_id": prereg["candidate_id"],
            "changed_axis": prereg["changed_axis"],
            "boundary_utc": boundary,
            "fresh_boundary_utc": boundary,
            "source": source,
            "trades": fresh,
            "completed_trades": len(fresh),
            "metrics": _metrics(fresh),
            "preboundary_outcomes_counted": False,
            "preboundary_data_feature_warmup_only": True,
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
        })
        candidate["source_quality_gate"] = exact.source_quality_gate(candidate)
        candidate["sample_gap_to_25"] = max(0, MIN_TRADES - len(fresh))
        candidate["prereg_policy_blob_sha"] = prereg["policy_blob_sha"]
        candidate["prereg_policy_freeze_commit"] = prereg["policy_freeze_commit"]
        candidate["prereg_receipt_sha256"] = ev.stable_sha(prereg)

        h4_state = "NOT_RUN_MIN_SAMPLE"
        h5_state = "NOT_RUN_MIN_SAMPLE"
        hardening = None
        source_state = str((candidate.get("source_quality_gate") or {}).get("state") or "")
        if source_state == "FAIL":
            state = "HOLD_FRESH_SOURCE_QUALITY"
            nxt = "REPAIR_SOURCE_ONLY_NO_STRATEGY_CHANGE"
        elif len(fresh) < MIN_TRADES:
            state = "WAIT_FRESH_25"
            nxt = "CONTINUE_HOURLY_FRESH_COLLECTION"
        else:
            candidate["receipt_sha256"] = ev.stable_sha({k: v for k, v in candidate.items() if k != "receipt_sha256"})
            candidate_path = Path(td) / "fresh_candidate.json"
            candidate_path.write_text(json.dumps(candidate, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            hard_path = Path(td) / "hardening.json"
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
    print("PASS_A1_TREND_RIDER_NON_US_LOSS_REPAIR_FORWARD_V1_SELF_TEST")
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
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
