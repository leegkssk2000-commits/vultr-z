#!/usr/bin/env python3
from __future__ import annotations
import argparse,bisect,csv,gzip,hashlib,importlib.util,json,math,sys
from pathlib import Path
from statistics import fmean
from typing import Any

SYMS=("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","LINKUSDT"); WINS=("W1","W2","W3")

def csha(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def loadmod(p):
 s=importlib.util.spec_from_file_location("momo_replay",p); m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; s.loader.exec_module(m); return m

def bars(p,T):
 out=[]
 with gzip.open(p,"rt",newline="") as h:
  for r in csv.DictReader(h):
   b=T(int(r["timestamp_ms"]),*[float(r[k]) for k in ("open","high","low","close","volume")]); b.validate(); out.append(b)
 if any(b.ts<=a.ts for a,b in zip(out,out[1:])): raise ValueError(f"bad ts {p}")
 return out

def met(ts):
 v=[t["net_R"] for t in ts]; w=[x for x in v if x>0]; l=[x for x in v if x<0]
 pf=sum(w)/abs(sum(l)) if l else (999. if w else 0.); aw=fmean(w) if w else 0.; al=abs(fmean(l)) if l else 0.; po=aw/al if al else (999. if aw else 0.)
 e=pk=dd=0.
 for x in v: e+=x; pk=max(pk,e); dd=max(dd,pk-e)
 ids=[t["trade_id"] for t in ts]; sc={}
 for t in ts: sc[t["symbol"]]=sc.get(t["symbol"],0)+1
 return {"trades":len(v),"win_rate_pct":100*len(w)/len(v) if v else 0.,"net_R":sum(v),"profit_factor":pf,"expectancy_R":fmean(v) if v else 0.,"payoff":po,"max_DD_R":dd,"max_symbol_trade_share_pct":100*max(sc.values(),default=0)/len(v) if v else 0.,"errors":0,"duplicates":len(ids)-len(set(ids)),"censored_open":0,"unknown_exit":0}

def gate(x): return x["trades"]>=60 and x["net_R"]>0 and x["profit_factor"]>=1 and x["expectancy_R"]>0 and x["payoff"]>=1 and not any(x[k] for k in ("errors","duplicates","censored_open","unknown_exit"))
def cfg(M,e,r): return M.Config(int(e["regime_lookback"]),float(e["directional_efficiency_min"]),int(e["breakout_lookback"]),float(e["breakout_buffer_atr"]),float(e["expansion_atr_multiple"]),float(e["relative_volume_min"]),float(r["stop_atr_multiple"]),float(r["target_r"]),int(r["max_hold_bars"]),float(r["expected_move_to_cost_min"]))

def signals(M,root,win,C,cost,cut=0.):
 out={}; rs=max(C.regime_lookback,15); ss=max(C.breakout_lookback+2,22)
 for s in SYMS:
  x=bars(root/f"market/5m/{win}/{s}.csv.gz",M.Bar); z=bars(root/f"market/15m/{win}/{s}.csv.gz",M.Bar); zt=[b.ts for b in z]; q=[]
  for i in range(ss-1,len(x)-C.max_hold_bars-3):
   j=bisect.bisect_right(zt,x[i].ts-600000)
   if j<rs: continue
   d=M.decide_long(z[max(0,j-rs):j],x[i-ss+1:i+1],C,cost)
   if d.action!="long": continue
   quality=float(d.expected_move_to_cost or 0)*float(d.relative_volume or 0)
   risk=float(d.entry_reference or 0)-float(d.stop_price or 0)
   if quality>=cut and risk>0:q.append({"symbol":s,"i":i,"signal_ts":x[i].ts,"risk":risk,"target_r":C.target_r,"hold":C.max_hold_bars,"quality":quality})
  out[s]=q
 return out

def sim(M,root,win,S,cost,delay=0,rev=False):
 out=[]; side="short" if rev else "long"
 for s in SYMS:
  x=bars(root/f"market/5m/{win}/{s}.csv.gz",M.Bar); free=0
  for g in S[s]:
   ei=g["i"]+1+delay
   if ei<free or ei>=len(x):continue
   en=x[ei].open; r=g["risk"]; st=en+r if rev else en-r; tp=en-g["target_r"]*r if rev else en+g["target_r"]*r; last=min(len(x)-1,ei+g["hold"]-1); ex=last; px=x[last].close; why="TIMEOUT"
   for k in range(ei,last+1):
    bh=x[k].high>=st if rev else x[k].low<=st; th=x[k].low<=tp if rev else x[k].high>=tp
    if bh: ex=k;px=st;why="STOP_FIRST";break
    if th: ex=k;px=tp;why="TARGET";break
   gross=((en-px) if rev else (px-en))/r; cr=en*(cost/100)/r
   tid=hashlib.sha256(f"{win}|{s}|{side}|{g['signal_ts']}|{x[ei].ts}|{x[ex].ts}|{delay}".encode()).hexdigest()
   out.append({"trade_id":tid,"window":win,"symbol":s,"side":side,"signal_ts":g["signal_ts"],"entry_ts":x[ei].ts,"exit_ts":x[ex].ts,"net_R":gross-cr,"gross_R":gross,"cost_R":cr,"exit_reason":why,"quality":g["quality"]}); free=ex+1
 return sorted(out,key=lambda t:(t["entry_ts"],t["symbol"],t["trade_id"]))

def evaluate(M,root,win,e,r,cut,cost,delay=0,rev=False):
 C=cfg(M,e,r);C.validate();S=signals(M,root,win,C,cost,cut);T=sim(M,root,win,S,cost,delay,rev);return met(T),T

def riskset(plan,n):
 keys=("stop_atr_multiple","target_r","max_hold_bars","expected_move_to_cost_min");seen=set();out=[]
 for t in plan["trials"]:
  f=tuple(t[k] for k in keys)
  if f in seen:continue
  seen.add(f);out.append({k:t[k] for k in keys})
  if len(out)>=n:break
 return out

def w1cut(M,root,e,r,cost):
 C=cfg(M,e,r);C.validate();A=signals(M,root,"W1",C,cost,0.);qs=sorted(g["quality"] for v in A.values() for g in v)
 if not qs:return {"quality_cutoff":None,"retention_pct":0.,"metrics":met([]),"hard_gate_pass":False,"path":[]}
 full=len(sim(M,root,"W1",A,cost));prevn=0.;prevt=0;sel=None;path=[]
 for d in range(1,11):
  cut=qs[int(math.floor((len(qs)-1)*max(0.,1-d/10)))];F={s:[g for g in A[s] if g["quality"]>=cut] for s in SYMS};mm=met(sim(M,root,"W1",F,cost));dt=mm["trades"]-prevt;inc=(mm["net_R"]-prevn)/dt if dt>0 else 0.;ret=100*mm["trades"]/full if full else 0.;row={"retained_deciles":d,"quality_cutoff":cut,"retention_pct":ret,"incremental_expectancy_R":inc,"metrics":mm};path.append(row)
  if inc<=0:break
  sel=row;prevn=mm["net_R"];prevt=mm["trades"]
 if sel is None:sel=path[0]
 return {"quality_cutoff":sel["quality_cutoff"],"retention_pct":sel["retention_pct"],"metrics":sel["metrics"],"hard_gate_pass":sel["retention_pct"]>=60 and gate(sel["metrics"]),"path":path}

def main():
 a=argparse.ArgumentParser();a.add_argument("--inputs",type=Path,required=True);a.add_argument("--event-study",type=Path,required=True);a.add_argument("--repo-root",type=Path,required=True);a.add_argument("--output",type=Path,required=True);o=a.parse_args();o.output.mkdir(parents=True,exist_ok=True)
 src=o.repo_root/"backend/research/momentum_breakout_continuation_v1.py"; plan=json.loads((o.repo_root/"backend/research/zel_scalp_momentum_generation1_trial_plan_v1.json").read_text());ctl=json.loads((o.repo_root/"backend/research/zel_scalp_momentum_replay_control_plan_v1.json").read_text());man=json.loads((o.inputs/"materialized_manifest.json").read_text());cost=json.loads((o.inputs/"cost_binding.json").read_text());ev=json.loads((o.event_study/"momentum_event_study_receipt.json").read_text());M=loadmod(src)
 base={"schema_version":"zel.scalp.momentum.staged_replay.v1","strategy_id":"momentum_breakout_continuation_v1","input_manifest_receipt_sha256":man["manifest_receipt_sha256"],"event_study_receipt_sha256":ev["receipt_sha256"],"integrity":{"future_information":0,"errors":0,"duplicates":0,"censored_open":0,"unknown_exit":0,"protected_mutations":0},"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED"}
 def finish(x):x["receipt_sha256"]=csha(x);(o.output/"momentum_staged_replay_receipt.json").write_text(json.dumps(x,indent=2,sort_keys=True)+"\n");print(json.dumps({k:x.get(k) for k in ("state","survivor","failure_stage","selected_entry_config_id","selected_risk_config_id")},sort_keys=True))
 if man.get("state")!="PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS":raise SystemExit("materialization mismatch")
 if ev["state"]!="PASS_EVENT_STUDY_EDGE_FOUND":return finish(base|{"state":"PASS_REPLAY_SKIPPED_EVENT_STUDY_NO_EDGE","survivor":False,"selected_entry_config_id":None,"selected_risk_config_id":None,"action":"route_change"})
 c=float(cost["all_in_cost_pct"]);fixed=ctl["staged_search"][0]["fixed_parameters"];emap={t["config_id"]:t for t in ev["trials"]};s1=[]
 for cid in ev["passing_config_ids"]:
  e=emap[cid]["entry_parameters"];q=w1cut(M,o.inputs,e,fixed,c);s1.append({"config_id":cid,"entry_parameters":e,"quality_cutoff":q["quality_cutoff"],"retention_pct":q["retention_pct"],"metrics":q["metrics"],"hard_gate_pass":q["hard_gate_pass"],"marginal_expectancy_path":q["path"]})
 p1=sorted([x for x in s1 if x["hard_gate_pass"]],key=lambda x:(x["metrics"]["net_R"],x["metrics"]["profit_factor"],x["metrics"]["payoff"]),reverse=True)
 if not p1:return finish(base|{"state":"PASS_REPLAY_COMPLETE_NO_SURVIVOR","survivor":False,"failure_stage":"S1_ENTRY_STRUCTURE","s1_results":s1,"selected_entry_config_id":None,"selected_risk_config_id":None,"action":"route_change"})
 se=p1[0];s2=[]
 for i,r in enumerate(riskset(plan,int(ctl["staged_search"][1]["maximum_trials"])),1):
  mm,_=evaluate(M,o.inputs,"W1",se["entry_parameters"],r,float(se["quality_cutoff"]),c);s2.append({"config_id":f"S2-{i:03d}","risk_parameters":r,"metrics":mm,"hard_gate_pass":gate(mm)})
 p2=sorted([x for x in s2 if x["hard_gate_pass"]],key=lambda x:(x["metrics"]["net_R"],x["metrics"]["profit_factor"],x["metrics"]["payoff"]),reverse=True)
 if not p2:return finish(base|{"state":"PASS_REPLAY_COMPLETE_NO_SURVIVOR","survivor":False,"failure_stage":"S2_RISK_EXIT","s1_results":s1,"s2_results":s2,"selected_entry_config_id":se["config_id"],"selected_risk_config_id":None,"action":"route_change"})
 sr=p2[0];fm={};led={}
 for w in WINS:fm[w],led[w]=evaluate(M,o.inputs,w,se["entry_parameters"],sr["risk_parameters"],float(se["quality_cutoff"]),c);(o.output/f"selected_{w}_trades.json").write_text(json.dumps(led[w],indent=2,sort_keys=True)+"\n")
 stress={}
 for name,cc,delay in (("DOUBLE_ALL_IN_COST",2*c,0),("P95_FUNDING",c+float(cost["funding_horizon_pct"]),0),("PLUS_ONE_BAR_DELAY",c,1)):
  stress[name]={}
  for w in WINS:
   mm,_=evaluate(M,o.inputs,w,se["entry_parameters"],sr["risk_parameters"],float(se["quality_cutoff"]),cc,delay);stress[name][w]=mm|{"hard_gate_pass":gate(mm)}
 rev,_=evaluate(M,o.inputs,"W1",se["entry_parameters"],sr["risk_parameters"],float(se["quality_cutoff"]),c,0,True)
 gates={"baseline_W1_W2_W3":all(gate(fm[w]) for w in WINS),"stress":all(stress[n][w]["hard_gate_pass"] for n in stress for w in WINS),"symbol_concentration":all(fm[w]["max_symbol_trade_share_pct"]<=50 for w in WINS),"adjacent_parameter_stability":len(p2)>=2,"negative_controls":not gate(rev)};sur=all(gates.values());alltr=[t for w in WINS for t in led[w]];dup=len(alltr)-len({t["trade_id"] for t in alltr})
 if dup:raise SystemExit(f"duplicate trades {dup}")
 finish(base|{"state":"PASS_REPLAY_COMPLETE_SURVIVOR" if sur else "PASS_REPLAY_COMPLETE_NO_SURVIVOR","survivor":sur,"selected_entry_config_id":se["config_id"],"selected_entry_parameters":se["entry_parameters"],"selected_quality_cutoff":se["quality_cutoff"],"selected_risk_config_id":sr["config_id"],"selected_risk_parameters":sr["risk_parameters"],"s1_results":s1,"s2_results":s2,"frozen_metrics":fm,"stress":stress,"controls":{"NO_SIGNAL_PLACEBO":{"trades":0,"net_R":0.},"DIRECTION_REVERSAL_W1":rev},"gates":gates,"action":"hold" if sur else "route_change"})
if __name__=="__main__":main()
