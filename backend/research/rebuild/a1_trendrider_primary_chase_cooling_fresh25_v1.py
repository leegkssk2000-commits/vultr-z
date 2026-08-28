#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any, Mapping

ROOT=Path(__file__).resolve().parents[3]
R=ROOT/"backend/research/rebuild"
CONTRACT=R/"a1_trendrider_primary_chase_cooling_fresh25_contract_v1.json"
PARENT=R/"a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
FRESH2=R/"a1_trendrider_8125_fresh2_source_v1.json"
LOSS=R/"a1_recent_loss_cluster_actionable_latest.json"
TOP5=R/"a1_top5_latest_only_ssot_v1.json"
SCHEMA="zel.a1.trendrider.primary.chase_cooling_fresh25.v1"
EPS=1e-9

def read(p:Path)->dict[str,Any]:
    v=json.loads(p.read_text())
    if not isinstance(v,dict): raise RuntimeError(f"OBJECT_REQUIRED:{p}")
    return v
def stable(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode()).hexdigest()
def key(x:Mapping[str,Any])->tuple[str,int,int,str]:
    return str(x["symbol"]),int(x["signal_ts"]),int(x["entry_ts"]),str(x["side"])
def metrics(rows:list[Mapping[str,Any]])->dict[str,Any]:
    vals=[float(x["net_bps"]) for x in rows]
    if not vals:return {"trades":0,"net_pnl_bps":0.0,"net_expectancy_bps":None,"profit_factor":None,"profit_factor_unbounded":False,"win_rate":None,"drawdown_bps":0.0}
    wins=[x for x in vals if x>0]; losses=[-x for x in vals if x<0]; gp=sum(wins); gl=sum(losses); eq=peak=dd=0.0
    for v in vals: eq+=v; peak=max(peak,eq); dd=max(dd,peak-eq)
    return {"trades":len(vals),"net_pnl_bps":sum(vals),"net_expectancy_bps":sum(vals)/len(vals),"profit_factor":gp/gl if gl else None,"profit_factor_unbounded":bool(gp>0 and not gl),"win_rate":len(wins)/len(vals),"drawdown_bps":dd}
def payoff(rows:list[Mapping[str,Any]])->float|None:
    w=[float(x["net_bps"]) for x in rows if float(x["net_bps"])>0]; l=[-float(x["net_bps"]) for x in rows if float(x["net_bps"])<0]
    return None if not w or not l else (sum(w)/len(w))/(sum(l)/len(l))
def ge(a:float|None,b:float|None)->bool:return a is not None and b is not None and float(a)+EPS>=float(b)
def le(a:float|None,b:float|None)->bool:return a is not None and b is not None and float(a)<=float(b)+EPS
def strict(parent:list[dict[str,Any]],added:list[dict[str,Any]]):
    pm,am,cm=metrics(parent),metrics(added),metrics(parent+added); pp,cp=payoff(parent),payoff(parent+added)
    c={"combined_wr_non_decrease":ge(cm["win_rate"],pm["win_rate"]),"combined_pnl_non_decrease":ge(cm["net_pnl_bps"],pm["net_pnl_bps"]),"combined_expectancy_non_decrease":ge(cm["net_expectancy_bps"],pm["net_expectancy_bps"]),"combined_pf_non_decrease":bool(cm["profit_factor_unbounded"]) or ge(cm["profit_factor"],pm["profit_factor"]),"combined_payoff_non_decrease":pp is None or ge(cp,pp),"combined_dd_non_increase":le(cm["drawdown_bps"],pm["drawdown_bps"]),"added_wr_at_least_parent":ge(am["win_rate"],pm["win_rate"]),"added_expectancy_at_least_parent":ge(am["net_expectancy_bps"],pm["net_expectancy_bps"]),"added_pf_at_least_parent":bool(am["profit_factor_unbounded"]) or ge(am["profit_factor"],pm["profit_factor"]),"added_pnl_positive":float(am["net_pnl_bps"] or 0)>0}
    return all(c.values()),c,am,cm,cp
def target(doc:Mapping[str,Any])->dict[str,Any]:
    for x in doc.get("targets") or []:
        if isinstance(x,Mapping) and x.get("strategy_id")=="trend_rider":return dict(x)
    raise RuntimeError("TREND_RIDER_LOSS_TARGET_MISSING")
def validate(c,p,f,l,t):
    core=dict(c); supplied=str(core.pop("receipt_sha256",""))
    if c.get("state")!="FROZEN_PRIMARY_CHASE_COOLING_FRESH25_CONTRACT" or supplied!=stable(core):raise RuntimeError("PRIMARY_CHASE_CONTRACT_INVALID")
    h=c["historical_strict_ceiling_diagnostic"]
    if p.get("receipt_sha256")!=h["parent_receipt_sha256"] or f.get("receipt_sha256")!=h["fresh2_receipt_sha256"]:raise RuntimeError("PRIMARY_FROZEN_SOURCE_CHANGED")
    if len(p.get("trades") or [])!=16 or len(f.get("trades") or [])!=2:raise RuntimeError("PRIMARY_FROZEN_COUNTS_CHANGED")
    rt=target(l); cause=rt.get("actionable_root_cause") or {}
    if cause.get("axis")!="CHASE_ATR" or rt.get("recommended_route")!="PREREGISTER_PREENTRY_STRUCTURAL_CHILD:CHASE_ATR:BORROW_EXISTING_CAUSAL_GEOMETRY_ONLY":raise RuntimeError("PRIMARY_ROOT_CAUSE_CHANGED")
    if int(rt.get("leakage_lookahead") or 0)!=0 or rt.get("post_outcome_threshold_sweep") is not False or rt.get("integrity_defects"):raise RuntimeError("PRIMARY_ROOT_CAUSE_INTEGRITY_INVALID")
    pr=next((dict(x) for x in t.get("top5") or [] if isinstance(x,Mapping) and x.get("rank")==1 and x.get("strategy_id")=="trend_rider"),None)
    if not pr:raise RuntimeError("PRIMARY_TOP5_ROW_MISSING")
    if int((pr.get("latest_strict_ceiling") or {}).get("T") or 0)!=24 or int((pr.get("fresh_to_25") or {}).get("T_needed") or 0)!=1:raise RuntimeError("PRIMARY_STRICT24_SSOT_CHANGED")
    if abs(float((pr["fresh_to_25"]).get("reference_min_winner_bps") or 0)-float(h["reference_required_one_unseen_winner_bps"]))>EPS:raise RuntimeError("PRIMARY_REFERENCE_WINNER_CHANGED")
    return rt,pr
def run()->dict[str,Any]:
    c,p,f,l,t=map(read,(CONTRACT,PARENT,FRESH2,LOSS,TOP5)); rt,pr=validate(c,p,f,l,t); h=c["historical_strict_ceiling_diagnostic"]; b=int(c["preregistered_root_cause"]["boundary_ms"])
    parent=[dict(x) for x in p["trades"]]; fixed=[dict(x) for x in f["trades"]]+[dict(x) for x in h["oracle_donor_rows"]]
    ks=[key(x) for x in parent+fixed]
    if len(ks)!=len(set(ks)):raise RuntimeError("PRIMARY_FIXED_BASELINE_DUPLICATE_KEY")
    ledger=[dict(x) for x in rt.get("preentry_trade_ledger") or []]; post=sorted([x for x in ledger if int(x.get("signal_ts") or 0)>b],key=key); acc=[x for x in post if x.get("chase_cooling_or_flat") is True]; rej=[x for x in post if x.get("chase_cooling_or_flat") is not True]
    if any(key(x) in set(ks) for x in acc):raise RuntimeError("PRIMARY_POST_BOUNDARY_OVERLAP")
    sp,checks,am,cm,cp=strict(parent,fixed+acc); fresh=bool(acc) and int(cm["trades"])>=25; passed=fresh and sp
    state,nxt=("WAIT_PRIMARY_CHASE_COOLING_FRESH_T","COLLECT_POST_BOUNDARY_CHASE_COOLING_T") if not acc else (("PASS_PRIMARY_STRICT25_CAUSAL_CONFIRMATION_CANDIDATE","INDEPENDENT_REVIEW_BEFORE_SSOT_SURVIVOR_UPDATE") if passed else ("HOLD_PRIMARY_CHASE_COOLING_FRESH_ECONOMIC","KEEP_PARENT_LOCKED_AND_DO_NOT_DELETE_ACCEPTED_T"))
    out={"schema_version":SCHEMA,"state":state,"strategy_id":"trend_rider","lane_id":"trend_rider_primary_wr8125","changed_axis":"PREENTRY_CHASE_COOLING_OR_FLAT_ONLY","contract_receipt_sha256":c["receipt_sha256"],"latest_loss_receipt_sha256":l.get("receipt_sha256"),"latest_target_receipt_sha256":rt.get("receipt_sha256"),"top5_state":t.get("state"),"historical_strict_ceiling_T":int(pr["latest_strict_ceiling"]["T"]),"reference_required_one_unseen_winner_bps":h["reference_required_one_unseen_winner_bps"],"boundary_ms":b,"boundary_utc":c["preregistered_root_cause"]["boundary_utc"],"raw_post_boundary_T":len(post),"fresh_accepted_T":len(acc),"fresh_rejected_T":len(rej),"fresh_accepted_rows":[{k:x.get(k) for k in ("symbol","signal_ts","entry_ts","exit_ts","side","net_bps","chase_atr","prior_chase_atr","chase_cooling_or_flat","reason")} for x in acc],"fresh_rejected_keys":[list(key(x)) for x in rej],"fixed_diagnostic_added_T":len(fixed),"combined_T":cm["trades"],"strict_all_metric_pass":sp,"strict_checks":checks,"added_metrics":am,"combined_metrics":cm,"combined_payoff":cp,"causal_fresh_confirmation_ready":fresh,"strict25_causal_candidate_pass":passed,"historical_oracle_is_promotion_evidence":False,"same_sample_root_cause_is_promotion_evidence":False,"all_accepted_post_boundary_trades_append_only":True,"post_outcome_trade_deletion":False,"old_history_union":False,"numeric_threshold_sweep":False,"floating_compare_epsilon":EPS,"production_mutated":False,"top5_ssot_mutated":False,"g5_broad_mutated":False,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","action":"hold","next":nxt}
    out["receipt_sha256"]=stable(out); return out
def self_test()->int:
    c=read(CONTRACT); assert c["borrowed_existing_causal_geometry"]["numeric_threshold_added"] is False and c["borrowed_existing_causal_geometry"]["threshold_sweep"] is False
    r=run(); assert r["old_history_union"] is False and r["numeric_threshold_sweep"] is False and r["selection_authority"] is False and r["promotion_authority"] is False and r["execution_authority"]=="NONE" and r["order_authority"]=="BLOCKED" and r["live_trade_authority"]=="BLOCKED"
    assert all(int(x["signal_ts"])>int(r["boundary_ms"]) for x in r["fresh_accepted_rows"])
    print("PASS_A1_TRENDRIDER_PRIMARY_CHASE_COOLING_FRESH25_V1_SELF_TEST"); print(json.dumps({k:r[k] for k in ("state","raw_post_boundary_T","fresh_accepted_T","combined_T","strict_all_metric_pass","next")},sort_keys=True)); return 0
def main()->int:
    a=argparse.ArgumentParser(); a.add_argument("--out",type=Path,default=Path("out/a1_trendrider_primary_chase_cooling_fresh25_v1.json")); a.add_argument("--self-test",action="store_true"); x=a.parse_args()
    if x.self_test:return self_test()
    r=run(); x.out.parent.mkdir(parents=True,exist_ok=True); x.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+"\n"); print(json.dumps({k:r[k] for k in ("state","raw_post_boundary_T","fresh_accepted_T","combined_T","strict_all_metric_pass","next","receipt_sha256")},sort_keys=True)); return 0
if __name__=="__main__":raise SystemExit(main())
