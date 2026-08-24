#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
STRATEGY_ID = "keltner_trend"
SYMBOLS = "BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,LINK-USDT,DOGE-USDT"
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def stable_sha(value: Any) -> str:
    return ev.stable_sha(value)


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def max_exit_bucket_dd(rows: list[dict[str, Any]]) -> float:
    buckets: dict[int, float] = defaultdict(float)
    for row in rows:
        buckets[int(row["exit_ts"])] += float(row["net_bps"])
    equity = peak = dd = 0.0
    for _, pnl in sorted(buckets.items()):
        equity += pnl
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in rows]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    return {
        "completed_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(rows) if rows else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(rows) if rows else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "canonical_sequence_max_drawdown_bps": ev.max_drawdown(vals),
        "exit_bucket_max_drawdown_bps": max_exit_bucket_dd(rows),
        "largest_loss_bps": min(vals) if vals else None,
    }


def replay_parent() -> dict[str, Any]:
    ledger = read(LEDGER)
    shadow = json.loads(json.dumps(ledger))
    entry = (shadow.get("strategies") or {}).get(STRATEGY_ID)
    if not isinstance(entry, dict):
        raise RuntimeError("KELTNER_LEDGER_ENTRY_REQUIRED")
    if not entry.get("prospective_boundary_utc"):
        raise RuntimeError("KELTNER_PROSPECTIVE_BOUNDARY_REQUIRED")
    entry["status"] = "ACTIVE"

    original_ledger = ev.LEDGER_PATH
    original_argv = list(sys.argv)
    with tempfile.TemporaryDirectory(prefix="keltner_long_only_") as td:
        temp_ledger = Path(td) / "ledger.json"
        receipt_path = Path(td) / "keltner.json"
        temp_ledger.write_text(json.dumps(shadow, sort_keys=True), encoding="utf-8")
        try:
            ev.LEDGER_PATH = temp_ledger
            sys.argv = [
                "a1_exact25_generic_evaluator_v1.py",
                "--strategy-id", STRATEGY_ID,
                "--symbols", SYMBOLS,
                "--out", str(receipt_path),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                ev.main()
            return read(receipt_path)
        finally:
            ev.LEDGER_PATH = original_ledger
            sys.argv = original_argv


def validate_parent(receipt: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    if receipt.get("strategy_id") != STRATEGY_ID:
        defects.append("STRATEGY_ID_MISMATCH")
    if list(receipt.get("integrity_defects") or []):
        defects.append("UPSTREAM_INTEGRITY_DEFECT")
    if int(receipt.get("leakage_lookahead") or 0) != 0:
        defects.append("UPSTREAM_LOOKAHEAD_NONZERO")
    trades = list(receipt.get("trades") or [])
    if len(trades) < 12:
        defects.append("PARENT_MIN_SAMPLE_NOT_MET")
    got_symbols = sorted({str(x.get("symbol") or "") for x in trades})
    expected = sorted(x.strip() for x in SYMBOLS.split(","))
    if got_symbols != expected:
        defects.append("LIQUID6_COMPLETED_SYMBOL_SET_MISMATCH")
    ids = [str(x.get("intent_sha") or "") for x in trades]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        defects.append("TRADE_ID_MISSING_OR_DUPLICATE")
    for row in trades:
        if str(row.get("side")) not in ("long", "short"):
            defects.append("INVALID_SIDE")
            break
        if not math.isfinite(float(row.get("net_bps"))):
            defects.append("NONFINITE_NET_BPS")
            break
        if int(row.get("exit_ts") or 0) < int(row.get("entry_ts") or 0):
            defects.append("INVALID_TRADE_INTERVAL")
            break
    return sorted(set(defects))


def run() -> dict[str, Any]:
    receipt = replay_parent()
    defects = validate_parent(receipt)
    if defects:
        result = {
            "schema_version": "zel.a1.keltner.long_only_economic.v1",
            "state": "HOLD_KELTNER_LONG_ONLY_PARENT_INTEGRITY",
            "strategy_id": STRATEGY_ID,
            "integrity_defects": defects,
            "research_only": True,
            **AUTH,
        }
        result["receipt_sha256"] = stable_sha(result)
        return result

    parent_rows = [dict(x) for x in receipt["trades"]]
    child_rows = [x for x in parent_rows if str(x["side"]) == "long"]
    short_rows = [x for x in parent_rows if str(x["side"]) == "short"]
    parent = metrics(parent_rows)
    child = metrics(child_rows)
    short = metrics(short_rows)

    min_sample = len(child_rows) >= 12
    pnl_improved = float(child["net_pnl_bps"]) > float(parent["net_pnl_bps"])
    expectancy_improved = float(child["net_expectancy_bps"]) > float(parent["net_expectancy_bps"])
    canonical_dd_nonworse = float(child["canonical_sequence_max_drawdown_bps"]) <= float(parent["canonical_sequence_max_drawdown_bps"])
    exit_bucket_dd_nonworse = float(child["exit_bucket_max_drawdown_bps"]) <= float(parent["exit_bucket_max_drawdown_bps"])
    pf_nonworse = (
        child["profit_factor"] is not None
        and parent["profit_factor"] is not None
        and float(child["profit_factor"]) >= float(parent["profit_factor"])
    )
    economic_pass = all((min_sample, pnl_improved, expectancy_improved, canonical_dd_nonworse, exit_bucket_dd_nonworse, pf_nonworse))

    result = {
        "schema_version": "zel.a1.keltner.long_only_economic.v1",
        "state": "PASS_KELTNER_LONG_ONLY_ECONOMIC_COUNTERFACTUAL" if economic_pass else "HOLD_KELTNER_LONG_ONLY_NO_ECONOMIC_UPGRADE",
        "strategy_id": STRATEGY_ID,
        "candidate_id": "keltner_long_only_v1",
        "scope": "CURRENT_PROSPECTIVE_PARENT_RETROSPECTIVE_SIDE_ABLATION_ONLY",
        "changed_axis": "SIDE_ADMISSION_LONG_ONLY",
        "contract": {
            "entry_signal_geometry_changed": False,
            "long_entry_set_changed": False,
            "short_entries_suppressed": True,
            "exit_geometry_changed": False,
            "stop_changed": False,
            "timeout_changed": False,
            "cost_model_changed": False,
            "numeric_threshold_sweep": False,
            "post_outcome_threshold_fitting": False,
            "same_parent_receipt_for_parent_and_child": True,
        },
        "parent_receipt_sha256": receipt.get("receipt_sha256"),
        "parent": parent,
        "long_only": child,
        "short_only_diagnostic": short,
        "delta_long_minus_parent": {
            "completed_trades": int(child["completed_trades"]) - int(parent["completed_trades"]),
            "net_pnl_bps": float(child["net_pnl_bps"]) - float(parent["net_pnl_bps"]),
            "net_expectancy_bps": float(child["net_expectancy_bps"]) - float(parent["net_expectancy_bps"]),
            "canonical_sequence_max_drawdown_bps": float(child["canonical_sequence_max_drawdown_bps"]) - float(parent["canonical_sequence_max_drawdown_bps"]),
            "exit_bucket_max_drawdown_bps": float(child["exit_bucket_max_drawdown_bps"]) - float(parent["exit_bucket_max_drawdown_bps"]),
        },
        "gate": {
            "minimum_long_completed_trades": 12,
            "minimum_sample_met": min_sample,
            "net_pnl_strictly_improved": pnl_improved,
            "net_expectancy_strictly_improved": expectancy_improved,
            "canonical_dd_nonworse": canonical_dd_nonworse,
            "exit_bucket_dd_nonworse": exit_bucket_dd_nonworse,
            "profit_factor_nonworse": pf_nonworse,
            "economic_pass": economic_pass,
        },
        "fresh_oos_required_before_any_runtime_use": True,
        "promotion_claim": False,
        "integrity_defects": [],
        "research_only": True,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> int:
    rows = [
        {"entry_ts": 1, "exit_ts": 3, "side": "long", "net_bps": 100.0},
        {"entry_ts": 2, "exit_ts": 3, "side": "short", "net_bps": -50.0},
        {"entry_ts": 4, "exit_ts": 5, "side": "long", "net_bps": 20.0},
    ]
    m = metrics(rows)
    assert m["completed_trades"] == 3 and m["net_pnl_bps"] == 70.0
    assert m["exit_bucket_max_drawdown_bps"] == 0.0
    long = metrics([x for x in rows if x["side"] == "long"])
    assert long["net_pnl_bps"] == 120.0 and long["losses"] == 0
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_KELTNER_LONG_ONLY_ECONOMIC_V1_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="out/a1_keltner_long_only_economic_latest.json")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    result = run()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "parent": result.get("parent"),
        "long_only": result.get("long_only"),
        "short_only_diagnostic": result.get("short_only_diagnostic"),
        "delta": result.get("delta_long_minus_parent"),
        "gate": result.get("gate"),
        "integrity_defects": result.get("integrity_defects"),
    }, sort_keys=True))
    return 2 if result.get("integrity_defects") else 0


if __name__ == "__main__":
    raise SystemExit(main())
