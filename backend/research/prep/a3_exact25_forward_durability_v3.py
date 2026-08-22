from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/prep/a3_durability_contract_v1.json"
HARDENING = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
TAXONOMY = ROOT / "backend/research/prep/a3_regime_taxonomy_v1.json"
READY = ROOT / "backend/research/prep/A3_PREP_READY_v1.json"
AUTH = {"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0,"action":"hold"}


def read(path: Path) -> dict[str, Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value

def stable_sha(value: Any) -> str: return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode()).hexdigest()
def dt_ms(value: str)->int: return int(datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc).timestamp()*1000)
def finite(x: Any)->float|None:
    if x is None or isinstance(x,bool): return None
    try:v=float(x)
    except Exception:return None
    return v if v==v and abs(v)!=float("inf") else None

def validate_contract(contract:Mapping[str,Any],hardening:Mapping[str,Any])->None:
    if contract.get("state")!="PASS_A3_DURABILITY_CONTRACT_SEALED" or contract.get("sealed_before_activation") is not True: raise RuntimeError("A3_DURABILITY_CONTRACT_NOT_SEALED")
    if (contract.get("derivation") or {}).get("outcomes_used_to_choose_thresholds") is not False or (contract.get("derivation") or {}).get("new_alpha_thresholds_created") is not False: raise RuntimeError("A3_OUTCOME_TUNED_CONTRACT_FORBIDDEN")
    h5=hardening.get("h5_concentration_fragility") or {}; c=contract.get("concentration_fragility_gate") or {}
    if float(c.get("maximum_single_regime_profit_share"))!=float(h5.get("maximum_single_regime_profit_share")):raise RuntimeError("A3_H5_REGIME_DRIFT")
    if float(c.get("maximum_single_symbol_profit_share"))!=float(h5.get("maximum_single_symbol_profit_share")):raise RuntimeError("A3_H5_SYMBOL_DRIFT")
    if float(c.get("maximum_top10_trade_profit_share"))!=float(h5.get("maximum_top10_trade_profit_share")):raise RuntimeError("A3_H5_TOP10_DRIFT")
    if float(c.get("minimum_leave_one_group_out_net_R"))!=float(h5.get("minimum_leave_one_group_out_net_R")):raise RuntimeError("A3_H5_LOGO_DRIFT")

def classify(ctx:Mapping[str,Any])->dict[str,str]:
    trend=float(ctx["trend_strength"]);vol=float(ctx["realized_vol_pct"]);spread=float(ctx["spread_bps"]);depth=float(ctx["depth_usdt"]);fund=float(ctx["funding_8h_pct"]);oi=float(ctx["oi_change_pct"]);hour=int(ctx["session_utc_hour"])
    trend_state="TREND_STRONG" if trend>=0.6 else "TREND_WEAK" if trend<=0.25 else "TREND_MID"
    vol_state="VOL_HIGH" if vol>=1.5 else "VOL_LOW" if vol<=0.5 else "VOL_MID"
    liquidity_state="LIQ_THIN" if spread>=8 or depth<250000 else "LIQ_DEEP" if spread<=2 and depth>=1000000 else "LIQ_MID"
    funding_oi_state="CROWDED_LONG" if fund>=0.03 and oi>=2 else "CROWDED_SHORT" if fund<=-0.03 and oi<=-2 else "POSITIONING_NEUTRAL"
    session_state="ASIA" if 0<=hour<8 else "EU" if 8<=hour<16 else "US"
    return {"trend_state":trend_state,"vol_state":vol_state,"liquidity_state":liquidity_state,"funding_oi_state":funding_oi_state,"session_state":session_state,"regime":"|".join((trend_state,vol_state,liquidity_state,funding_oi_state))}

def _capture_completed_ms(row:Mapping[str,Any])->int:
    raw=row.get("capture_completed_at_ms")
    if raw is None: raw=row.get("snapshot_capture_completed_at_ms")
    try:return int(raw or 0)
    except Exception:return 0

def _context_index(context:Mapping[str,Any])->dict[str,list[dict[str,Any]]]:
    rows=[]
    for row in context.get("rows") or []:
        if not isinstance(row,Mapping) or row.get("valid_for_a3") is not True: continue
        cap=_capture_completed_ms(row);cut=int(row.get("bar_feature_cutoff_ts_ms") or 0);sym=str(row.get("symbol") or "")
        if cap<=0 or cut<=0 or not sym: continue
        x=dict(row);x["capture_completed_at_ms"]=cap;x["labels"]=classify(x);rows.append(x)
    by=defaultdict(list)
    for x in sorted(rows,key=lambda r:(str(r["symbol"]),int(r["capture_completed_at_ms"]))):by[str(x["symbol"])].append(x)
    return dict(by)
def join_trade(trade:Mapping[str,Any],by:Mapping[str,list[dict[str,Any]]],stale_ms:int)->tuple[dict[str,Any]|None,str|None]:
    entry=int(trade["entry_ts"]);sym=str(trade["symbol"]);eligible=[x for x in by.get(sym,[]) if int(x["capture_completed_at_ms"])<=entry and int(x["bar_feature_cutoff_ts_ms"])<=entry]
    if not eligible:return None,"NO_CAUSAL_CONTEXT"
    ctx=max(eligible,key=lambda x:int(x["capture_completed_at_ms"]));age=entry-int(ctx["capture_completed_at_ms"])
    if age<0:return None,"FUTURE_CONTEXT"
    if age>stale_ms:return None,f"STALE_CONTEXT:{age}>{stale_ms}"
    out={**dict(trade),"context_capture_completed_at_ms":ctx["capture_completed_at_ms"],"context_bar_feature_cutoff_ts_ms":ctx["bar_feature_cutoff_ts_ms"],"context_age_ms":age,**ctx["labels"]};return out,None

def net_r(t:Mapping[str,Any])->float:return float(t["net_bps"])/100.0
def _pf(vals:list[float])->float|None:
    gp=sum(x for x in vals if x>0);gl=-sum(x for x in vals if x<0);return gp/gl if gl>0 else None
def _payoff(vals:list[float])->float|None:
    w=[x for x in vals if x>0];l=[-x for x in vals if x<0];return (sum(w)/len(w))/(sum(l)/len(l)) if w and l else None
def aggregate(rows:list[dict[str,Any]],key:str)->dict[str,Any]:
    groups={}
    for r in rows:groups.setdefault(str(r[key]),[]).append(r)
    return {g:{"trades":len(rs),"net_R":sum(net_r(x) for x in rs),"expectancy_R":sum(net_r(x) for x in rs)/len(rs),"profit_factor":_pf([net_r(x) for x in rs]),"payoff":_payoff([net_r(x) for x in rs])} for g,rs in sorted(groups.items())}
def _group_key(r:Mapping[str,Any],dim:str)->str:
    if dim=="regime":return str(r["regime"])
    if dim=="session":return str(r["session_state"])
    if dim=="window":return datetime.fromtimestamp(int(r["entry_ts"])/1000,tz=timezone.utc).strftime("%Y-%m-%d")
    return str(r[dim])
def concentration_gate(rows:list[dict[str,Any]],contract:Mapping[str,Any])->tuple[dict[str,Any],list[str]]:
    c=contract["concentration_fragility_gate"];positives=[max(0.0,net_r(r)) for r in rows];total=sum(positives);fail=[];shares={}
    for dim,limit_name in (("regime","maximum_single_regime_profit_share"),("symbol","maximum_single_symbol_profit_share")):
        sums=defaultdict(float)
        for r,p in zip(rows,positives):sums[_group_key(r,dim)]+=p
        mx=max(sums.values(),default=0.0)/total if total>0 else 1.0;shares[dim]=mx
        if mx>float(c[limit_name]):fail.append(f"{dim.upper()}_PROFIT_SHARE:{mx}>{c[limit_name]}")
    top10=sum(sorted(positives,reverse=True)[:10])/total if total>0 else 1.0;shares["top10_trade"]=top10
    if top10>float(c["maximum_top10_trade_profit_share"]):fail.append(f"TOP10_PROFIT_SHARE:{top10}>{c['maximum_top10_trade_profit_share']}")
    logo={}
    for dim in c["required_dimensions"]:
        keys=sorted({_group_key(r,dim) for r in rows});logo[dim]={}
        for k in keys:
            remain=[r for r in rows if _group_key(r,dim)!=k];v=sum(net_r(r) for r in remain);logo[dim][k]=v
            if v<float(c["minimum_leave_one_group_out_net_R"]):fail.append(f"LEAVE_ONE_{dim.upper()}:{k}:{v}<0")
    return {"profit_shares":shares,"leave_one_group_out_net_R":logo},fail

def evaluate(receipt:Mapping[str,Any],a2:Mapping[str,Any],context:Mapping[str,Any])->dict[str,Any]:
    contract=read(CONTRACT);hardening=read(HARDENING);taxonomy=read(TAXONOMY);ready=read(READY);validate_contract(contract,hardening)
    cid=str(receipt.get("strategy_id") or "")
    if not cid or a2.get("candidate_id")!=cid or a2.get("state")!="PASS_A2_COST_TURNOVER":raise RuntimeError("A2_PASS_IDENTITY_REQUIRED")
    if receipt.get("source_quality_gate",{}).get("state")!="PASS" or list(receipt.get("integrity_defects") or []) or int(receipt.get("leakage_lookahead") or 0)!=0:raise RuntimeError("A3_RECEIPT_INTEGRITY_REQUIRED")
    activation=dt_ms(contract["activation_boundary_utc"]);trades=[dict(x) for x in receipt.get("trades") or [] if isinstance(x,Mapping) and int(x.get("entry_ts") or 0)>=activation]
    min_n=int(contract["prospective_cohort"]["minimum_causally_matched_trades"]);stale_ms=int(taxonomy["input_contract"]["stale_after_ms"]);by=_context_index(context);joined=[];unmatched=[]
    for t in trades:
        row,reason=join_trade(t,by,stale_ms)
        if row is not None:joined.append(row)
        else:unmatched.append({"symbol":t.get("symbol"),"entry_ts":t.get("entry_ts"),"reason":reason})
    coverage={"prospective_trade_count":len(trades),"causally_matched_trade_count":len(joined),"unmatched_trade_count":len(unmatched),"match_fraction":len(joined)/len(trades) if trades else 0.0,"minimum_required":min_n}
    blockers=[];failures=[];state="WAIT_A3_PROSPECTIVE_SAMPLE"
    if len(joined)<min_n:blockers.append(f"CAUSALLY_MATCHED_SAMPLE:{len(joined)}<{min_n}")
    if trades and len(joined)!=len(trades):blockers.append(f"A3_CAUSAL_COVERAGE:{len(joined)}/{len(trades)}<1.0")
    if len(joined)>=min_n and len(joined)==len(trades):
        vals=[net_r(r) for r in joined];g=contract["global_economic_gate"];net=sum(vals);exp=net/len(vals);pf=_pf(vals);pay=_payoff(vals)
        if not net>float(g["minimum_net_R"]):failures.append(f"NET_R:{net}<=0")
        if not exp>float(g["minimum_expectancy_R"]):failures.append(f"EXPECTANCY_R:{exp}<=0")
        if pf is None or pf<float(g["minimum_profit_factor"]):failures.append(f"PF:{pf}<1")
        if pay is None or pay<float(g["minimum_payoff_ratio"]):failures.append(f"PAYOFF:{pay}<1")
        concentration,cfail=concentration_gate(joined,contract);failures+=cfail;state="PASS_A3_GLOBAL_DURABILITY" if not failures else "FAIL_A3_GLOBAL_DURABILITY"
    else:
        vals=[net_r(r) for r in joined];net=sum(vals);exp=net/len(vals) if vals else None;pf=_pf(vals) if vals else None;pay=_payoff(vals) if vals else None;concentration={}
        if len(joined)>=min_n and len(joined)!=len(trades):state="HOLD_A3_CAUSAL_COVERAGE"
    economics={"net_R":net,"expectancy_R":exp,"profit_factor":pf,"payoff_ratio":pay,"trade_count":len(joined)}
    result={"schema_version":"zel.a3_exact25_forward_durability.v3","stage":"A3","state":state,"candidate_id":cid,"activation_boundary_utc":contract["activation_boundary_utc"],
        "contract_sha256":stable_sha(contract),"hardening_policy_sha256":stable_sha(hardening),"taxonomy_sha256":stable_sha(taxonomy),"a3_ready_sha256":stable_sha(ready),
        "prospective_only":True,"outcome_threshold_retune":False,"coverage":coverage,"economics":economics,"concentration_fragility":concentration,
        "joined_trades":joined,"unmatched_trades":unmatched,
        "regime_performance":{name:aggregate(joined,name) for name in ("trend_state","vol_state","liquidity_state","session_state","funding_oi_state")},
        "entry_time_regime_owner":None,"explicit_regime_owner_pass_enabled":False,"global_durability_pass":state=="PASS_A3_GLOBAL_DURABILITY",
        "blockers":blockers,"failures":failures,
        "next_required_action":"ACCUMULATE_PROSPECTIVE_CAUSAL_A3_EVIDENCE" if state.startswith(("WAIT_","HOLD_")) else "ROUTE_PASS_TO_S_GRADE" if state.startswith("PASS_") else "ROUTE_FAIL_TO_BOUNDED_REDESIGN_OR_SYNTHESIS",
        **AUTH}
    result["receipt_sha256"]=stable_sha({k:v for k,v in result.items() if k!="receipt_sha256"});return result

def self_test()->int:
    contract=read(CONTRACT);hardening=read(HARDENING);validate_contract(contract,hardening)
    assert contract["activation_boundary_utc"]=="2026-08-21T18:00:00Z"
    assert contract["prospective_cohort"]["minimum_causally_matched_trades"]==25
    assert _group_key({"entry_ts":1787331600000},"window")=="2026-08-21"
    assert classify({"trend_strength":0.4,"realized_vol_pct":1.2,"spread_bps":9,"depth_usdt":200000,"funding_8h_pct":0.04,"oi_change_pct":4,"session_utc_hour":17})["session_state"]=="US"
    collector_row={"valid_for_a3":True,"snapshot_capture_completed_at_ms":1000000,"bar_feature_cutoff_ts_ms":900000,"symbol":"BTC-USDT","trend_strength":0.4,"realized_vol_pct":1.2,"spread_bps":1.5,"depth_usdt":1500000,"funding_8h_pct":0.0,"oi_change_pct":0.1,"session_utc_hour":12}
    idx=_context_index({"rows":[collector_row]})
    assert idx["BTC-USDT"][0]["capture_completed_at_ms"]==1000000
    joined,reason=join_trade({"entry_ts":1000100,"symbol":"BTC-USDT"},idx,1000)
    assert reason is None and joined is not None and joined["context_capture_completed_at_ms"]==1000000
    print("PASS_A3_EXACT25_FORWARD_DURABILITY_V3_SELF_TEST");return 0

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--receipt",type=Path);ap.add_argument("--a2",type=Path);ap.add_argument("--context",type=Path);ap.add_argument("--output",type=Path,default=Path("out/a3_exact25_forward_durability_v3.json"));ap.add_argument("--self-test",action="store_true");args=ap.parse_args()
    if args.self_test:return self_test()
    if not args.receipt or not args.a2 or not args.context:raise SystemExit("--receipt --a2 --context required")
    result=evaluate(read(args.receipt),read(args.a2),read(args.context));args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"coverage":result["coverage"],"economics":result["economics"],"failures":result["failures"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True));return 0

if __name__=="__main__":raise SystemExit(main())