#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_keltner_long_only_economic_v1 as lo

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "backend/research/rebuild/a1_keltner_long_only_fresh_prereg_v1.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
POLICY = ROOT / "backend/research/rebuild/breakout_policy_batch_v1.py"
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def pf_nonworse(child: float | None, parent: float | None) -> bool:
    if parent is None:
        return child is None or (isinstance(child, (int, float)) and float(child) >= 1.0)
    if child is None:
        return True
    return float(child) >= float(parent)


def replay_from_frozen_boundary(prereg: dict[str, Any]) -> dict[str, Any]:
    ledger = read(LEDGER)
    shadow = json.loads(json.dumps(ledger))
    sid = str(prereg["strategy_id"])
    entry = (shadow.get("strategies") or {}).get(sid)
    if not isinstance(entry, dict):
        raise RuntimeError("KELTNER_LEDGER_ENTRY_REQUIRED")
    entry["status"] = "ACTIVE"
    entry["prospective_boundary_utc"] = str(prereg["fresh_boundary_utc"])

    original_ledger = ev.LEDGER_PATH
    original_argv = list(sys.argv)
    with tempfile.TemporaryDirectory(prefix="keltner_long_only_fresh_") as td:
        temp_ledger = Path(td) / "ledger.json"
        receipt_path = Path(td) / "fresh_parent.json"
        temp_ledger.write_text(json.dumps(shadow, sort_keys=True), encoding="utf-8")
        try:
            ev.LEDGER_PATH = temp_ledger
            sys.argv = [
                "a1_exact25_generic_evaluator_v1.py",
                "--strategy-id", sid,
                "--symbols", ",".join(str(x) for x in prereg["symbols"]),
                "--out", str(receipt_path),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                ev.main()
            return read(receipt_path)
        finally:
            ev.LEDGER_PATH = original_ledger
            sys.argv = original_argv


def run() -> dict[str, Any]:
    prereg = read(PREREG)
    defects: list[str] = []

    if prereg.get("candidate_id") != "keltner_long_only_v1":
        defects.append("CANDIDATE_ID_MISMATCH")
    if prereg.get("strategy_id") != "keltner_trend":
        defects.append("STRATEGY_ID_MISMATCH")
    if prereg.get("changed_axis") != "SIDE_ADMISSION_LONG_ONLY":
        defects.append("CHANGED_AXIS_MISMATCH")
    if ev.git_blob_sha(POLICY) != str(prereg.get("parent_policy_blob_sha") or ""):
        defects.append("FROZEN_PARENT_POLICY_BLOB_MISMATCH")

    if defects:
        result = {
            "schema_version": "zel.a1.keltner.long_only.fresh.v1",
            "state": "HOLD_KELTNER_LONG_ONLY_FRESH_PREREG_INTEGRITY",
            "candidate_id": prereg.get("candidate_id"),
            "strategy_id": prereg.get("strategy_id"),
            "fresh_boundary_utc": prereg.get("fresh_boundary_utc"),
            "integrity_defects": sorted(set(defects)),
            "research_only": True,
            **AUTH,
        }
        result["receipt_sha256"] = ev.stable_sha(result)
        return result

    parent_receipt = replay_from_frozen_boundary(prereg)
    defects.extend(str(x) for x in (parent_receipt.get("integrity_defects") or []))
    if int(parent_receipt.get("leakage_lookahead") or 0) != 0:
        defects.append("UPSTREAM_LOOKAHEAD_NONZERO")
    if str(parent_receipt.get("boundary_utc") or "") != str(prereg["fresh_boundary_utc"]):
        defects.append("FRESH_BOUNDARY_MISMATCH")
    if str(parent_receipt.get("policy_path") or "") != str(prereg["parent_policy_path"]):
        defects.append("PARENT_POLICY_PATH_MISMATCH")
    if str(parent_receipt.get("policy_sha") or "") != str(prereg["parent_policy_blob_sha"]):
        defects.append("PARENT_POLICY_SHA_MISMATCH")

    rows = [dict(x) for x in (parent_receipt.get("trades") or [])]
    ids = [str(x.get("intent_sha") or "") for x in rows]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        defects.append("TRADE_ID_MISSING_OR_DUPLICATE")

    longs = [x for x in rows if str(x.get("side")) == "long"]
    shorts = [x for x in rows if str(x.get("side")) == "short"]
    parent = lo.metrics(rows)
    child = lo.metrics(longs)
    short_diag = lo.metrics(shorts)
    distinct_symbols = sorted({str(x.get("symbol") or "") for x in longs if x.get("symbol")})

    min_trades = int(prereg["minimum_fresh_long_trades"])
    min_symbols = int(prereg["minimum_distinct_symbols"])
    sample_ready = len(longs) >= min_trades
    symbol_ready = len(distinct_symbols) >= min_symbols

    net_pnl_positive = bool(child["net_pnl_bps"] is not None and float(child["net_pnl_bps"]) > 0)
    net_exp_positive = bool(child["net_expectancy_bps"] is not None and float(child["net_expectancy_bps"]) > 0)
    pnl_improved = bool(
        child["net_pnl_bps"] is not None and parent["net_pnl_bps"] is not None
        and float(child["net_pnl_bps"]) > float(parent["net_pnl_bps"])
    )
    expectancy_improved = bool(
        child["net_expectancy_bps"] is not None and parent["net_expectancy_bps"] is not None
        and float(child["net_expectancy_bps"]) > float(parent["net_expectancy_bps"])
    )
    wr_nonworse = bool(
        child["win_rate"] is not None and parent["win_rate"] is not None
        and float(child["win_rate"]) >= float(parent["win_rate"])
    )
    pf_ok = pf_nonworse(child["profit_factor"], parent["profit_factor"])
    dd_nonworse = bool(
        child["canonical_sequence_max_drawdown_bps"] is not None
        and parent["canonical_sequence_max_drawdown_bps"] is not None
        and float(child["canonical_sequence_max_drawdown_bps"]) <= float(parent["canonical_sequence_max_drawdown_bps"])
    )

    gate = {
        "minimum_fresh_long_trades": min_trades,
        "minimum_distinct_symbols": min_symbols,
        "sample_ready": sample_ready,
        "distinct_symbol_ready": symbol_ready,
        "net_pnl_positive": net_pnl_positive,
        "net_expectancy_positive": net_exp_positive,
        "net_pnl_vs_parent_strictly_improved": pnl_improved,
        "net_expectancy_vs_parent_strictly_improved": expectancy_improved,
        "win_rate_vs_parent_nonworse": wr_nonworse,
        "profit_factor_vs_parent_nonworse": pf_ok,
        "canonical_drawdown_vs_parent_nonworse": dd_nonworse,
    }
    fresh_pass = sample_ready and symbol_ready and not defects and all(
        gate[k] for k in (
            "net_pnl_positive",
            "net_expectancy_positive",
            "net_pnl_vs_parent_strictly_improved",
            "net_expectancy_vs_parent_strictly_improved",
            "win_rate_vs_parent_nonworse",
            "profit_factor_vs_parent_nonworse",
            "canonical_drawdown_vs_parent_nonworse",
        )
    )

    if defects:
        state = "HOLD_KELTNER_LONG_ONLY_FRESH_INTEGRITY"
        nxt = "REPAIR_SOURCE_OR_LINEAGE_ONLY"
    elif not sample_ready or not symbol_ready:
        state = "WAIT_KELTNER_LONG_ONLY_FRESH_25"
        nxt = "CONTINUE_HOURLY_FRESH_COLLECTION_AND_PARALLEL_RESEARCH"
    elif fresh_pass:
        state = "PASS_KELTNER_LONG_ONLY_FRESH_OOS_ECONOMICS"
        nxt = "RUN_IDENTITY_SPECIFIC_H4_H5_THEN_A2_A3"
    else:
        state = "HOLD_KELTNER_LONG_ONLY_FRESH_NO_UPGRADE"
        nxt = "PRESERVE_RESULT_AND_ROUTE_NEXT_DISTINCT_AXIS"

    result = {
        "schema_version": "zel.a1.keltner.long_only.fresh.v1",
        "state": state,
        "next": nxt,
        "candidate_id": str(prereg["candidate_id"]),
        "strategy_id": str(prereg["strategy_id"]),
        "changed_axis": str(prereg["changed_axis"]),
        "fresh_boundary_utc": str(prereg["fresh_boundary_utc"]),
        "freeze_commit": str(prereg["freeze_commit"]),
        "parent_policy_blob_sha": str(prereg["parent_policy_blob_sha"]),
        "completed_parent_trades": len(rows),
        "completed_fresh_long_trades": len(longs),
        "completed_fresh_short_trades": len(shorts),
        "sample_gap_to_25": max(0, min_trades - len(longs)),
        "distinct_long_symbols": distinct_symbols,
        "parent": parent,
        "long_only": child,
        "short_only_diagnostic": short_diag,
        "delta_long_minus_parent": {
            "completed_trades": len(longs) - len(rows),
            "net_pnl_bps": (float(child["net_pnl_bps"]) - float(parent["net_pnl_bps"])) if rows else 0.0,
            "net_expectancy_bps": (
                float(child["net_expectancy_bps"]) - float(parent["net_expectancy_bps"])
                if child["net_expectancy_bps"] is not None and parent["net_expectancy_bps"] is not None else None
            ),
            "win_rate": (
                float(child["win_rate"]) - float(parent["win_rate"])
                if child["win_rate"] is not None and parent["win_rate"] is not None else None
            ),
            "canonical_sequence_max_drawdown_bps": (
                float(child["canonical_sequence_max_drawdown_bps"]) - float(parent["canonical_sequence_max_drawdown_bps"])
            ),
        },
        "gate": gate,
        "fresh_economic_pass": fresh_pass,
        "identity_specific_hardening_required": True,
        "promotion_claim": False,
        "canonical_ledger_mutated": False,
        "preboundary_outcomes_counted": False,
        "preboundary_data_feature_warmup_only": True,
        "source": parent_receipt.get("source"),
        "execution_snapshots": parent_receipt.get("execution_snapshots"),
        "trades": longs,
        "short_trades_diagnostic": shorts,
        "integrity_defects": sorted(set(defects)),
        "leakage_lookahead": int(parent_receipt.get("leakage_lookahead") or 0),
        "research_only": True,
        **AUTH,
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    return result


def self_test() -> int:
    prereg = read(PREREG)
    assert prereg["fresh_boundary_utc"] == "2026-08-24T17:30:00Z"
    assert prereg["minimum_fresh_long_trades"] == 25
    assert prereg["minimum_distinct_symbols"] == 3
    assert prereg["contract"]["numeric_threshold_sweep"] is False
    assert prereg["contract"]["post_outcome_threshold_fitting"] is False
    assert prereg["contract"]["short_entries_suppressed"] is True
    assert pf_nonworse(None, 2.0) is True
    assert pf_nonworse(2.0, 1.5) is True
    assert pf_nonworse(1.0, 1.5) is False
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_KELTNER_LONG_ONLY_FRESH_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/a1_keltner_long_only_fresh_latest.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "parent_trades": result.get("completed_parent_trades"),
        "long_trades": result.get("completed_fresh_long_trades"),
        "short_trades": result.get("completed_fresh_short_trades"),
        "gap": result.get("sample_gap_to_25"),
        "parent": result.get("parent"),
        "long_only": result.get("long_only"),
        "delta": result.get("delta_long_minus_parent"),
        "gate": result.get("gate"),
        "next": result.get("next"),
        "defects": result.get("integrity_defects"),
    }, sort_keys=True))
    return 2 if result.get("integrity_defects") else 0


if __name__ == "__main__":
    raise SystemExit(main())
