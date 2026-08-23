#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as exact
from backend.research.rebuild import trend_rider_transition_freshness_non_us_strength_reentry_child_policy_v1 as child

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "backend/research/rebuild/trend_rider_trigger32623644328_incumbent_context_v1.json"


def read(path: Path) -> dict[str, Any]:
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise RuntimeError("OBJECT_REQUIRED")
    return v


def max_dd(rows: list[dict[str, Any]]) -> float:
    eq=peak=worst=0.0
    for r in rows:
        eq += float(r["net_bps"])
        peak=max(peak,eq); worst=max(worst,peak-eq)
    return worst


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals=[float(r["net_bps"]) for r in rows]
    wins=sum(x>0 for x in vals); losses=sum(x<0 for x in vals)
    return {
        "trades":len(rows),"wins":wins,"losses":losses,
        "win_rate":wins/len(rows) if rows else None,
        "net_pnl_bps":sum(vals),
        "net_expectancy_bps":sum(vals)/len(rows) if rows else None,
        "max_drawdown_bps":max_dd(rows),
    }


def session(ts: int) -> str:
    h=datetime.fromtimestamp(ts/1000,tz=timezone.utc).hour
    return "APAC" if h<8 else "EU" if h<16 else "US"


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def run(out: Path) -> dict[str, Any]:
    fx=read(FIXTURE); rows=[dict(r) for r in fx["rows"]]
    if len(rows)!=24 or int(fx["trade_count"])!=24: raise RuntimeError("FROZEN_CONTEXT_COUNT_MISMATCH")
    parent_m=metrics(rows)
    if abs(float(parent_m["net_pnl_bps"])-24812.448723667734)>1e-6: raise RuntimeError("FROZEN_PARENT_PNL_MISMATCH")
    if abs(float(parent_m["win_rate"])-(14/24))>1e-12: raise RuntimeError("FROZEN_PARENT_WR_MISMATCH")

    scaffold=[r for r in rows if session(int(r["signal_ts"]))!="US"]
    scaffold_m=metrics(scaffold)
    if len(scaffold)!=15 or abs(float(scaffold_m["win_rate"])-0.8)>1e-12: raise RuntimeError("WR80_SCAFFOLD_REPRO_FAIL")
    if abs(float(scaffold_m["net_pnl_bps"])-21196.60152461874)>1e-6: raise RuntimeError("WR80_SCAFFOLD_PNL_REPRO_FAIL")

    retained=[]; decisions=[]; defects=[]; bars_meta={}
    for symbol in sorted({str(r["symbol"]) for r in rows}):
        bars=exact.fetch_bars(symbol,"1h",1000)
        idx={int(b["ts_ms"]):i for i,b in enumerate(bars)}
        wanted=[r for r in rows if r["symbol"]==symbol]
        bars_meta[symbol]={"bars":len(bars),"first_ts":int(bars[0]["ts_ms"]) if bars else None,"last_ts":int(bars[-1]["ts_ms"]) if bars else None}
        for r in wanted:
            ts=int(r["signal_ts"]); i=idx.get(ts)
            if i is None or i<64:
                defects.append(f"{symbol}:{ts}:BAR_OR_WARMUP_MISSING"); continue
            f=child.compute_trend_rider_feature(bars[:i+1],symbol=symbol,now_ts_ms=ts)
            v=dict(f.values); side=str(r["side"])
            incumbent_ok=bool(v.get("incumbent_long_confirm") if side=="long" else v.get("incumbent_short_confirm"))
            child_ok=bool(v.get("long_confirm") if side=="long" else v.get("short_confirm"))
            if not incumbent_ok: defects.append(f"{symbol}:{ts}:INCUMBENT_IDENTITY_MISMATCH")
            if child_ok: retained.append(r)
            decisions.append({
                "symbol":symbol,"signal_ts":ts,"side":side,"net_bps":float(r["net_bps"]),
                "session":v.get("session"),"incumbent_ok":incumbent_ok,"retained":child_ok,
                "st_gap_atr_current":v.get("st_gap_atr_current"),
                "st_gap_atr_prior_closed_bar":v.get("st_gap_atr_prior_closed_bar"),
                "st_gap_atr_strengthening":v.get("st_gap_atr_strengthening"),
                "us_strength_reentry_allowed":v.get("us_strength_reentry_allowed"),
            })

    if defects: state="HOLD_TARGETED_REPLAY_INTEGRITY"
    else:
        rm=metrics(retained)
        state="PASS_WR_SCAFFOLD_PNL_RECOVERY" if (rm["win_rate"] is not None and float(rm["win_rate"])>=0.8 and float(rm["net_pnl_bps"])>float(scaffold_m["net_pnl_bps"])) else "HOLD_WR80_SCAFFOLD_TRY_NEXT_PNL_RECOVERY_AXIS"
    rm=metrics(retained)
    result={
        "schema_version":"zel.a1.trend_rider.wr80_scaffold_targeted_recovery.v1",
        "state":state,
        "strategy_id":"trend_rider",
        "trigger_run_id":int(fx["trigger_run_id"]),
        "reproduction_artifact_run_id":int(fx["reproduction_artifact_run_id"]),
        "method":"IMMUTABLE_24_TRADE_OVERLAY_PREENTRY_TARGETED_REPLAY",
        "parent_context":parent_m,
        "parked_wr80_scaffold":scaffold_m,
        "recovery_candidate":rm,
        "deltas_vs_scaffold":{
            "win_rate_pp":None if rm["win_rate"] is None else 100*(float(rm["win_rate"])-0.8),
            "net_pnl_bps":float(rm["net_pnl_bps"])-float(scaffold_m["net_pnl_bps"]),
            "max_drawdown_bps":float(rm["max_drawdown_bps"])-float(scaffold_m["max_drawdown_bps"]),
            "trades":int(rm["trades"])-15,
        },
        "pnl_gap_to_parent_bps":float(parent_m["net_pnl_bps"])-float(rm["net_pnl_bps"]),
        "retained_trade_count":len(retained),
        "re_admitted_us": [d for d in decisions if d["session"]=="US" and d["retained"]],
        "blocked_us": [d for d in decisions if d["session"]=="US" and not d["retained"]],
        "decisions":decisions,
        "bars":bars_meta,
        "integrity_defects":defects,
        "historical_regression_is_promotion_evidence":False,
        "fresh_25_h4_h5_still_required":True,
        "scaffold_must_not_be_discarded_if_this_axis_fails":True,
        "next":"PREREGISTER_RECOVERY_CHILD_FRESH25_THEN_H4_H5" if state=="PASS_WR_SCAFFOLD_PNL_RECOVERY" else "KEEP_WR80_SCAFFOLD_AND_ROUTE_NEXT_DISTINCT_US_REENTRY_MECHANISM",
        "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0,
    }
    result["receipt_sha256"]=stable(result)
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"state":state,"scaffold":scaffold_m,"recovery":rm,"delta":result["deltas_vs_scaffold"],"re_admitted_us":result["re_admitted_us"],"next":result["next"]},sort_keys=True,allow_nan=False))
    return result


def self_test() -> int:
    fx=read(FIXTURE); assert fx["trade_count"]==24; assert fx["trigger_run_id"]==32623644328
    assert session(15*3600*1000)=="EU" and session(16*3600*1000)=="US"
    print("PASS_A1_TREND_RIDER_WR80_SCAFFOLD_TARGETED_RECOVERY_V1_SELF_TEST"); return 0


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--out",type=Path,default=Path("out/a1_trend_rider_wr80_scaffold_targeted_recovery_latest.json")); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    return self_test() if a.self_test else (run(a.out) and 0)

if __name__=="__main__": raise SystemExit(main())
