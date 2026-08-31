#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_entry_transplant_replay_v1 as base
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child_eval

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_partial_donor_transplant_v1.json"
ORIG_CONTRACT = ROOT / "backend/research/contracts/a1_top5_entry_transplant_replay_v1.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
INTERVAL_MS = 14_400_000


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pf_improved(child: Mapping[str, Any], parent: Mapping[str, Any]) -> bool:
    c, p = child.get("profit_factor"), parent.get("profit_factor")
    if c is None:
        return False
    if p is None:
        return True
    return float(c) > float(p)


def screen_ok(cell: Mapping[str, Any], gate: Mapping[str, Any]) -> tuple[bool, dict[str, bool]]:
    m, p = cell["metrics"], cell["parent_metrics"]
    checks = {
        "sample": int(m.get("trades") or 0) >= int(gate["minimum_closed_T"]),
        "retention": float(cell.get("retention_pct") or 0.0) >= float(gate["minimum_retention_pct"]),
        "net_positive": float(m.get("net_pnl_bps") or 0.0) > 0.0,
        "expectancy_improved": m.get("net_expectancy_bps") is not None and p.get("net_expectancy_bps") is not None and float(m["net_expectancy_bps"]) > float(p["net_expectancy_bps"]),
        "pf_or_dd_improved": pf_improved(m, p) or float(m.get("drawdown_bps") or 0.0) < float(p.get("drawdown_bps") or 0.0),
    }
    return all(checks.values()), checks


def main(args: argparse.Namespace) -> None:
    contract = read(CONTRACT)
    if contract.get("state") != "PREREGISTERED_PARTIAL_DONOR_TRANSPLANT_SCREEN":
        raise RuntimeError("CONTRACT_STATE_DRIFT")

    original_contract = read(ORIG_CONTRACT)
    top5 = read(TOP5)
    freeze = read(V2_FREEZE)
    trend30 = read(Path(args.trend30_source))
    a4_dir = Path(args.a4_source_dir)
    a4 = {
        "keltner_trend": read(a4_dir / "keltner_trend_exact_parent.json"),
        "supertrend_pullback": read(a4_dir / "supertrend_pullback_exact_parent.json"),
    }
    break_source = read(Path(args.break_source_dir) / "break_and_continue_exact_parent.json")

    parents = base.parent_sets(original_contract, top5, trend30, a4, break_source)
    parents = [p for p in parents if p["lane_id"] in set(contract["recipients"])]
    archs = base.architectures(original_contract, freeze)
    donors = contract["donors"]
    archs = [a for a in archs if a["architecture_id"] in donors]

    rows = [r for p in parents for r in p["rows"]]
    min_signal = min(int(r["signal_ts"]) for r in rows)
    max_signal = max(int(r["signal_ts"]) for r in rows)
    symbols = sorted({str(r["symbol"]) for r in rows})
    bars_by_symbol = {s: child_eval._bars(s, "4h", min_signal, max_signal + INTERVAL_MS) for s in symbols}

    engines: dict[tuple[str, str], Any] = {}
    for arch in archs:
        for symbol, bars in bars_by_symbol.items():
            _, engine = child_eval._features(bars, arch["spec"])
            engine.validate(str(arch["spec"]["entry_rule"]))
            engines[(arch["architecture_id"], symbol)] = engine

    cells: list[dict[str, Any]] = []
    for parent in parents:
        parent_rows = [dict(x) for x in parent["rows"]]
        pm = base.metric_plus(parent_rows)
        for arch in archs:
            donor = donors[arch["architecture_id"]]
            if donor["source_lane"] == parent["lane_id"]:
                continue
            allow = set(donor.get("symbol_allow") or [])
            accepted: list[dict[str, Any]] = []
            rejected: list[dict[str, Any]] = []
            for row in parent_rows:
                symbol = str(row["symbol"])
                if allow and symbol not in allow:
                    rejected.append(dict(row))
                    continue
                ok, _ = base.architecture_accepts(row, bars_by_symbol[symbol], engines[(arch["architecture_id"], symbol)], arch["spec"])
                (accepted if ok else rejected).append(dict(row))
            m = base.metric_plus(accepted)
            retention = (len(accepted) / len(parent_rows) * 100.0) if parent_rows else 0.0
            cell = {
                "parent_lane_id": parent["lane_id"],
                "donor_id": arch["architecture_id"],
                "donor_source_lane": donor["source_lane"],
                "symbol_allow": sorted(allow),
                "mode": "ADD_ONLY",
                "parent_metrics": pm,
                "metrics": m,
                "retention_pct": retention,
                "accepted_T": len(accepted),
                "rejected_T": len(rejected),
                "delta": {
                    "net_pnl_bps": base.delta(m, pm, "net_pnl_bps"),
                    "net_expectancy_bps": base.delta(m, pm, "net_expectancy_bps"),
                    "profit_factor": base.delta(m, pm, "profit_factor"),
                    "drawdown_bps": base.delta(m, pm, "drawdown_bps"),
                },
                "accepted_trade_keys": [list(base.trade_key(x)) for x in accepted],
                "parent_exit_mutated": False,
                "new_trade_admission": False,
                "cost_rededucted": False,
            }
            ok, checks = screen_ok(cell, contract["screen_gate"])
            cell["checks"] = checks
            cell["screen_pass"] = ok
            cell["decision"] = "PROMISING_FOR_EXTENDED_3M_6M_MATCHED_REPLAY" if ok else "DROP_CHILD_KEEP_PARENT"
            cells.append(cell)

    expected = 9
    if len(cells) != expected:
        raise RuntimeError(f"CELL_COUNT_DRIFT:{len(cells)}:{expected}")
    promising = [c for c in cells if c["screen_pass"]]
    promising.sort(key=lambda c: (
        -float(c["metrics"].get("net_expectancy_bps") or -1e30),
        -float(c["metrics"].get("profit_factor") or -1e30),
        float(c["metrics"].get("drawdown_bps") or 0.0),
    ))

    result = {
        "schema_version": "zel.a1.top5.g4.partial_donor_transplant.receipt.v1",
        "state": "PASS_PARTIAL_DONOR_SCREEN_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "primary_deferred": True,
        "cell_count": len(cells),
        "promising_count": len(promising),
        "promising": promising,
        "cells": cells,
        "fresh_g4_credit": 0,
        "formal_g5_credit": 0,
        "next": "RUN_PROMISING_CELLS_ON_EXTENDED_3M_6M_MATCHED_PARENT_HISTORY",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "promising_count": len(promising), "promising": [[x["parent_lane_id"], x["donor_id"]] for x in promising]}, sort_keys=True))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--trend30-source", required=True)
    ap.add_argument("--a4-source-dir", required=True)
    ap.add_argument("--break-source-dir", required=True)
    ap.add_argument("--out", required=True)
    main(ap.parse_args())
