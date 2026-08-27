#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_top5_additive_entry_union_v1 import evaluate, metrics, trade_key
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
SCHEMA = "zel.a1.trendrider.8125.donor_subset_extract.v1"


def read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def payoff(rows: list[Mapping[str, Any]]) -> float | None:
    wins = [float(x["net_bps"]) for x in rows if float(x["net_bps"]) > 0]
    losses = [-float(x["net_bps"]) for x in rows if float(x["net_bps"]) < 0]
    if not wins or not losses:
        return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def strict(parent: list[dict[str, Any]], subset: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    r = evaluate({"strategy_id":"trend_rider","trades":parent},{"strategy_id":"trend_rider","trades":subset})
    cp = payoff(parent)
    cc = payoff(parent + subset)
    payoff_ok = cp is None or (cc is not None and cc >= cp)
    checks = dict(r.get("checks") or {})
    checks["combined_payoff_non_decrease"] = payoff_ok
    return all(bool(v) for v in checks.values()), {"receipt":r,"parent_payoff":cp,"combined_payoff":cc,"checks":checks}


def session(t: Mapping[str, Any]) -> str:
    h = datetime.fromtimestamp(int(t["signal_ts"])/1000, tz=timezone.utc).hour
    if h < 8: return "APAC"
    if h < 16: return "EU"
    return "US"


def persistence3(t: Mapping[str, Any], bars: list[dict[str, Any]]) -> bool:
    idx = {int(b["ts_ms"]): i for i,b in enumerate(bars)}
    i = idx.get(int(t["signal_ts"]))
    if i is None or i < 3:
        return False
    closes = [float(bars[j]["close"]) for j in range(i-3, i+1)]
    ds = [closes[j]-closes[j-1] for j in range(1,4)]
    return all(x > 0 for x in ds) if str(t["side"]) == "long" else all(x < 0 for x in ds)


def keylist(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [list(trade_key(x)) for x in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_8125_donor_subset_extract_v1.json"))
    args = ap.parse_args()

    parent_doc = read(PARENT)
    parent = [dict(x) for x in parent_doc.get("trades") or []]
    if len(parent) != 16 or abs(float(parent_doc["metrics"]["win_rate"])-0.8125) > 1e-12:
        raise RuntimeError("EXACT16_PARENT_AUTHORITY_MISMATCH")

    current = rebuild_current()
    donor = [dict(x) for x in current.get("trades") or []]
    if len(donor) != 12:
        raise RuntimeError(f"CURRENT12_EXPECTED:{len(donor)}")
    pkeys = {trade_key(x) for x in parent}
    distinct = [x for x in donor if trade_key(x) not in pkeys]
    if len(distinct) != 8:
        raise RuntimeError(f"DISTINCT8_EXPECTED:{len(distinct)}")

    oracle = []
    for n in range(1, len(distinct)+1):
        for comb in itertools.combinations(distinct, n):
            subset = [dict(x) for x in comb]
            ok, detail = strict(parent, subset)
            if ok:
                oracle.append({
                    "T":len(subset),
                    "keys":keylist(subset),
                    "added_metrics":metrics(subset),
                    "combined_metrics":detail["receipt"]["combined_metrics"],
                    "combined_payoff":detail["combined_payoff"],
                })
    oracle.sort(key=lambda x:(x["T"],x["combined_metrics"]["net_pnl_bps"]), reverse=True)

    bars_by = {s:[dict(x) for x in ev.fetch_bars(s,"1h",1000)] for s in sorted({str(x["symbol"]) for x in distinct})}
    attrib=[]
    for t in distinct:
        attrib.append({
            "key":list(trade_key(t)),
            "symbol":t["symbol"],
            "side":t["side"],
            "session":session(t),
            "signal_hour_utc":datetime.fromtimestamp(int(t["signal_ts"])/1000,tz=timezone.utc).hour,
            "persistence3":persistence3(t,bars_by[str(t["symbol"])]),
            "net_bps":float(t["net_bps"]),
            "reason":t.get("reason"),
        })

    # Fixed, entry-observable discovery menu. No numeric threshold sweep.
    gates=[]
    fixed_specs=[]
    for sym in sorted({str(x["symbol"]) for x in distinct}):
        fixed_specs.append((f"SYMBOL_EQ_{sym}", lambda x,sym=sym: str(x["symbol"])==sym))
    for ss in ("APAC","EU","US"):
        fixed_specs.append((f"SESSION_EQ_{ss}", lambda x,ss=ss: session(x)==ss))
    fixed_specs.append(("PREENTRY_3BAR_DIRECTIONAL_PERSISTENCE", lambda x: persistence3(x,bars_by[str(x["symbol"])])))

    for name,pred in fixed_specs:
        subset=[x for x in distinct if pred(x)]
        if not subset:
            continue
        ok,detail=strict(parent,subset)
        gates.append({
            "gate":name,
            "selected_T":len(subset),
            "keys":keylist(subset),
            "strict_all_metric_pass":ok,
            "added_metrics":metrics(subset),
            "combined_metrics":detail["receipt"]["combined_metrics"],
            "combined_payoff":detail["combined_payoff"],
            "failed_checks":[k for k,v in detail["checks"].items() if not v],
        })
    gates.sort(key=lambda x:(x["strict_all_metric_pass"],x["selected_T"],x["combined_metrics"]["net_pnl_bps"]), reverse=True)

    best_gate = next((x for x in gates if x["strict_all_metric_pass"]), None)
    result={
        "schema_version":SCHEMA,
        "state":"PASS_HISTORICAL_DISCOVERY_GATE_FOUND" if best_gate else ("HOLD_ORACLE_ONLY_NO_CAUSAL_GATE" if oracle else "HOLD_NO_NONDEGRADING_SUBSET_IN_CURRENT12"),
        "strategy_id":"trend_rider",
        "parent_T":16,
        "parent_metrics":metrics(parent),
        "parent_payoff":payoff(parent),
        "current12_T":12,
        "overlap_T":4,
        "distinct_donor_T":8,
        "distinct_attribution":attrib,
        "oracle_non_degrading_subset_count":len(oracle),
        "oracle_best":oracle[0] if oracle else None,
        "oracle_is_promotion_evidence":False,
        "fixed_entry_observable_gate_results":gates,
        "best_historical_discovery_gate":best_gate,
        "historical_discovery_promotable":False,
        "fresh_prospective_confirmation_required":True,
        "parent_immutable":True,
        "selection_authority":False,
        "promotion_authority":False,
        "execution_authority":"NONE",
        "order_authority":"BLOCKED",
        "live_trade_authority":"BLOCKED",
        "action":"hold",
        "next":"FREEZE_BEST_CAUSAL_GATE_AND_REQUIRE_FRESH_PROSPECTIVE_T" if best_gate else "ADD_NEW_ENTRY_OBSERVABLE_AXIS_ONLY; DO_NOT_CHERRY_PICK_ORACLE_ROWS",
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({
        "state":result["state"],"oracle_count":len(oracle),"oracle_best_T":oracle[0]["T"] if oracle else 0,
        "best_gate":best_gate["gate"] if best_gate else None,"best_gate_T":best_gate["selected_T"] if best_gate else 0,
    },sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
