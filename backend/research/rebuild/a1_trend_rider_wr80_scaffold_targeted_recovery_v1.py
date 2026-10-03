#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as exact
from backend.research.rebuild import trend_policy_batch_v1 as canonical
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
        eq += float(r["net_bps"]); peak=max(peak,eq); worst=max(worst,peak-eq)
    return worst


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals=[float(r["net_bps"]) for r in rows]; wins=sum(x>0 for x in vals); losses=sum(x<0 for x in vals)
    return {"trades":len(rows),"wins":wins,"losses":losses,"win_rate":wins/len(rows) if rows else None,
            "net_pnl_bps":sum(vals),"net_expectancy_bps":sum(vals)/len(rows) if rows else None,"max_drawdown_bps":max_dd(rows)}


def session(ts: int) -> str:
    h=datetime.fromtimestamp(ts/1000,tz=timezone.utc).hour
    return "APAC" if h<8 else "EU" if h<16 else "US"


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def true_ranges(bars: list[dict[str, Any]]) -> list[float]:
    out=[]; prev=None
    for b in bars:
        h=float(b["high"]); l=float(b["low"]); c=float(b["close"])
        out.append(h-l if prev is None else max(h-l,abs(h-prev),abs(l-prev))); prev=c
    return out


def wilder_series(trs: list[float], length: int) -> list[float | None]:
    out:[float|None]=[None]*len(trs)
    if len(trs)<length: return out
    cur=sum(trs[:length])/length; out[length-1]=cur
    for i in range(length,len(trs)):
        cur=((length-1)*cur+trs[i])/length; out[i]=cur
    return out


def st_gap_atr_series(bars: list[dict[str, Any]]) -> list[float | None]:
    """Linear-time semantic equivalent of trend_policy_batch_v1 st_gap_atr for eligible bars."""
    if not bars: return []
    trs=true_ranges(bars); atr14=wilder_series(trs,14)
    st_atr:[float|None]=[None]*len(bars); cur10=None
    for i in range(len(bars)):
        if i<9: st_atr[i]=sum(trs[:i+1])/(i+1)
        elif i==9: cur10=sum(trs[:10])/10; st_atr[i]=cur10
        else:
            assert cur10 is not None; cur10=(9*cur10+trs[i])/10; st_atr[i]=cur10
    h0=float(bars[0]["high"]); l0=float(bars[0]["low"]); line=(h0+l0)/2.0
    final_upper=line; final_lower=line; prev_line=line; prev_close=float(bars[0]["close"])
    st=[line]
    for i in range(1,len(bars)):
        a=float(st_atr[i]); h=float(bars[i]["high"]); l=float(bars[i]["low"]); c=float(bars[i]["close"])
        hl2=(h+l)/2.0; upper=hl2+3.0*a; lower=hl2-3.0*a
        final_upper=upper if upper<final_upper or prev_close>final_upper else final_upper
        final_lower=lower if lower>final_lower or prev_close<final_lower else final_lower
        if prev_line==final_upper:
            line=final_upper if c<=final_upper else final_lower
        else:
            line=final_lower if c>=final_lower else final_upper
        st.append(line); prev_line=line; prev_close=c
    gaps:[float|None]=[None]*len(bars)
    for i,a in enumerate(atr14):
        if a is not None and float(a)>0: gaps[i]=abs(float(bars[i]["close"])-st[i])/float(a)
    return gaps


def parity_self_test() -> None:
    bars=[]; p=100.0
    for i in range(80):
        o=p; c=p*(1.0+(0.002 if i%5 else -0.001)); h=max(o,c)*1.003; l=min(o,c)*0.997
        bars.append({"ts_ms":i*3_600_000,"open":o,"high":h,"low":l,"close":c,"volume":1000+i}); p=c
    fast=st_gap_atr_series(bars)
    cfg=canonical.TrendPolicyConfig()
    now=int(bars[-1]["ts_ms"])
    a=canonical.compute_trend_rider_feature(bars,symbol="BTC-USDT",now_ts_ms=now,config=cfg)
    b=canonical.compute_trend_rider_feature(bars[:-1],symbol="BTC-USDT",now_ts_ms=int(bars[-2]["ts_ms"]),config=cfg)
    assert fast[-1] is not None and fast[-2] is not None
    assert math.isclose(float(fast[-1]),float(a.values["st_gap_atr"]),rel_tol=0.0,abs_tol=1e-12)
    assert math.isclose(float(fast[-2]),float(b.values["st_gap_atr"]),rel_tol=0.0,abs_tol=1e-12)


def run(out: Path) -> dict[str, Any]:
    fx=read(FIXTURE); rows=[dict(r) for r in fx["rows"]]
    if len(rows)!=24 or int(fx["trade_count"])!=24: raise RuntimeError("FROZEN_CONTEXT_COUNT_MISMATCH")
    parent_m=metrics(rows)
    if abs(float(parent_m["net_pnl_bps"])-24812.448723667734)>1e-6: raise RuntimeError("FROZEN_PARENT_PNL_MISMATCH")
    if abs(float(parent_m["win_rate"])-(14/24))>1e-12: raise RuntimeError("FROZEN_PARENT_WR_MISMATCH")
    scaffold=[r for r in rows if session(int(r["signal_ts"]))!="US"]; scaffold_m=metrics(scaffold)
    if len(scaffold)!=15 or abs(float(scaffold_m["win_rate"])-0.8)>1e-12: raise RuntimeError("WR80_SCAFFOLD_REPRO_FAIL")
    if abs(float(scaffold_m["net_pnl_bps"])-21196.60152461874)>1e-6: raise RuntimeError("WR80_SCAFFOLD_PNL_REPRO_FAIL")

    retained=[]; decisions=[]; defects=[]; bars_meta={}
    for symbol in sorted({str(r["symbol"]) for r in rows}):
        bars=exact.fetch_bars(symbol,"1h",1000); idx={int(b["ts_ms"]):i for i,b in enumerate(bars)}; gaps=st_gap_atr_series(bars)
        bars_meta[symbol]={"bars":len(bars),"first_ts":int(bars[0]["ts_ms"]) if bars else None,"last_ts":int(bars[-1]["ts_ms"]) if bars else None}
        for r in [x for x in rows if x["symbol"]==symbol]:
            ts=int(r["signal_ts"]); i=idx.get(ts); sess=session(ts)
            if i is None or i<64 or gaps[i] is None or gaps[i-1] is None:
                defects.append(f"{symbol}:{ts}:BAR_OR_WARMUP_MISSING"); continue
            strengthening=float(gaps[i])>float(gaps[i-1]); us_reentry=bool(sess=="US" and strengthening); keep=bool(sess!="US" or us_reentry)
            if keep: retained.append(r)
            decisions.append({"symbol":symbol,"signal_ts":ts,"side":str(r["side"]),"net_bps":float(r["net_bps"]),"session":sess,
                              "retained":keep,"st_gap_atr_current":float(gaps[i]),"st_gap_atr_prior_closed_bar":float(gaps[i-1]),
                              "st_gap_atr_strengthening":strengthening,"us_strength_reentry_allowed":us_reentry})

    rm=metrics(retained)
    state="HOLD_TARGETED_REPLAY_INTEGRITY" if defects else ("PASS_WR_SCAFFOLD_PNL_RECOVERY" if (rm["win_rate"] is not None and float(rm["win_rate"])>=0.8 and float(rm["net_pnl_bps"])>float(scaffold_m["net_pnl_bps"])) else "HOLD_WR80_SCAFFOLD_TRY_NEXT_PNL_RECOVERY_AXIS")
    result={"schema_version":"zel.a1.trend_rider.wr80_scaffold_targeted_recovery.v2","state":state,"strategy_id":"trend_rider",
            "trigger_run_id":int(fx["trigger_run_id"]),"reproduction_artifact_run_id":int(fx["reproduction_artifact_run_id"]),
            "method":"IMMUTABLE_24_TRADE_OVERLAY_PREENTRY_TARGETED_REPLAY_LINEAR_ST_GAP_PARITY",
            "parent_context":parent_m,"parked_wr80_scaffold":scaffold_m,"recovery_candidate":rm,
            "deltas_vs_scaffold":{"win_rate_pp":None if rm["win_rate"] is None else 100*(float(rm["win_rate"])-0.8),"net_pnl_bps":float(rm["net_pnl_bps"])-float(scaffold_m["net_pnl_bps"]),"max_drawdown_bps":float(rm["max_drawdown_bps"])-float(scaffold_m["max_drawdown_bps"]),"trades":int(rm["trades"])-15},
            "pnl_gap_to_parent_bps":float(parent_m["net_pnl_bps"])-float(rm["net_pnl_bps"]),"retained_trade_count":len(retained),
            "re_admitted_us":[d for d in decisions if d["session"]=="US" and d["retained"]],"blocked_us":[d for d in decisions if d["session"]=="US" and not d["retained"]],
            "decisions":decisions,"bars":bars_meta,"integrity_defects":defects,"historical_regression_is_promotion_evidence":False,"fresh_25_h4_h5_still_required":True,
            "scaffold_must_not_be_discarded_if_this_axis_fails":True,"next":"PREREGISTER_RECOVERY_CHILD_FRESH25_THEN_H4_H5" if state=="PASS_WR_SCAFFOLD_PNL_RECOVERY" else "KEEP_WR80_SCAFFOLD_AND_ROUTE_NEXT_DISTINCT_US_REENTRY_MECHANISM",
            "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0}
    result["receipt_sha256"]=stable(result); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"state":state,"scaffold":scaffold_m,"recovery":rm,"delta":result["deltas_vs_scaffold"],"re_admitted_us":result["re_admitted_us"],"next":result["next"]},sort_keys=True,allow_nan=False)); return result


def self_test() -> int:
    fx=read(FIXTURE); assert fx["trade_count"]==24 and fx["trigger_run_id"]==32623644328
    assert session(15*3600*1000)=="EU" and session(16*3600*1000)=="US"
    assert child.AXIS=="NON_US_SCAFFOLD_PLUS_US_ST_GAP_ATR_STRENGTHENING_REENTRY"; parity_self_test()
    print("PASS_A1_TREND_RIDER_WR80_SCAFFOLD_TARGETED_RECOVERY_V2_SELF_TEST"); return 0


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--out",type=Path,default=Path("out/a1_trend_rider_wr80_scaffold_targeted_recovery_latest.json")); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test: return self_test()
    run(a.out); return 0

if __name__=="__main__": raise SystemExit(main())
