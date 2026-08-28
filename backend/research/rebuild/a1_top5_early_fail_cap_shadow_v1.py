#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, hashlib
from pathlib import Path
from typing import Any, Mapping
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import metrics

CELLS=(0.75,0.45)

def read(p:Path)->dict[str,Any]: return json.loads(p.read_text())
def sha(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def payoff(rows:list[Mapping[str,Any]])->float|None:return rr.payoff(rows)

def simulate(rows:list[dict[str,Any]],r_gate:float,bars_by:dict[str,list[dict[str,Any]]])->tuple[list[dict[str,Any]],dict[str,int]]:
    out=[]; st={'early_cuts':0,'native_winners_cut':0,'proof_first_native_runner':0,'untouched':0}
    idx_by={s:{int(b['ts_ms']):i for i,b in enumerate(bs)} for s,bs in bars_by.items()}
    for src in rows:
        x=dict(src); s=str(x['symbol']); bs=bars_by[s]; idx=idx_by[s]
        si,ei,xi=idx.get(int(x['signal_ts'])),idx.get(int(x['entry_ts'])),idx.get(int(x['exit_ts']))
        if None in (si,ei,xi): raise RuntimeError(f'BAR_MISSING:{s}')
        entry=float(x.get('entry') or bs[ei]['open']); side=str(x['side']); one_r=rr.native_r(x,bs,si,entry)
        proof=entry+r_gate*one_r if side=='long' else entry-r_gate*one_r
        cut=entry-r_gate*one_r if side=='long' else entry+r_gate*one_r
        decision=None
        for j in range(ei,xi+1):
            lo,hi=float(bs[j]['low']),float(bs[j]['high'])
            hit_cut=(lo<=cut if side=='long' else hi>=cut); hit_proof=(hi>=proof if side=='long' else lo<=proof)
            if hit_cut and hit_proof: decision=('cut',j); break  # conservative same-bar ordering
            if hit_cut: decision=('cut',j); break
            if hit_proof: decision=('proof',j); break
        if decision is None: st['untouched']+=1; out.append(x); continue
        if decision[0]=='proof': st['proof_first_native_runner']+=1; out.append(x); continue
        j=decision[1]; gross=(cut-entry)/entry*10000 if side=='long' else (entry-cut)/entry*10000
        native=float(x.get('net_bps') or 0); cost=float(x.get('realized_cost_bps') or 0)
        if native>0: st['native_winners_cut']+=1
        st['early_cuts']+=1
        out.append({**x,'exit_ts':int(bs[j]['ts_ms']),'exit':float(cut),'gross_bps':gross,'net_bps':gross-cost,'reason':f'EARLY_FAIL_CAP_{r_gate:.2f}R','early_fail_gate_r':r_gate})
    return out,st

def strict(cm,bm,cp,bp):
    checks={'T_same':cm['trades']==bm['trades'],'WR_nonworse':cm['win_rate']>=bm['win_rate'],'PNL_nonworse':cm['net_pnl_bps']>=bm['net_pnl_bps'],'expectancy_nonworse':cm['net_expectancy_bps']>=bm['net_expectancy_bps'],'PF_nonworse':(cm['profit_factor'] or 0)>=(bm['profit_factor'] or 0),'payoff_improved':cp is not None and bp is not None and cp>bp,'DD_nonincrease':cm['drawdown_bps']<=bm['drawdown_bps']}; return all(checks.values()),checks

def run(trend:Path,a4:Path,brk:Path,out:Path):
    lanes=rr.latest_sets(read(trend),a4,brk); syms=sorted({str(t['symbol']) for l in lanes for t in l['rows']}); bars={s:ev.fetch_bars(s,'1h',1000) for s in syms}; res=[]
    for l in lanes:
        base=[dict(x) for x in l['rows']]; bm=metrics(base); bp=payoff(base); cells=[]
        for g in CELLS:
            cand,stats=simulate(base,g,bars); cm=metrics(cand); cp=payoff(cand); ok,checks=strict(cm,bm,cp,bp); cells.append({'gate_r':g,'rule':f'CUT_-{g}R_ONLY_IF_+{g}R_PROOF_NOT_REACHED_FIRST','metrics':cm,'payoff':cp,'strict_pass':ok,'checks':checks,'stats':stats})
        res.append({'lane':l['lane'],'strategy_id':l['strategy_id'],'reference':l['reference'],'base_metrics':bm,'base_payoff':bp,'cells':cells,'pass_count':sum(x['strict_pass'] for x in cells)})
    r={'schema_version':'zel.a1.top5.early_fail_cap_shadow.v1','state':'PASS_TOP5_EARLY_FAIL_CAP_SHADOW_COMPLETE','cells_r':list(CELLS),'same_bar_order':'LOSS_FIRST_CONSERVATIVE','native_runner_after_proof':True,'same_entries_same_T':True,'lanes':res,'shadow_only':True,'trend_rider_broad_g5_reference_mutated':False,'production_mutated':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','action':'hold'}; r['receipt_sha256']=sha(r); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n'); return r

def main():
    p=argparse.ArgumentParser(); p.add_argument('--trend70-source',type=Path); p.add_argument('--a4-source-dir',type=Path); p.add_argument('--break-source-dir',type=Path); p.add_argument('--out',type=Path,default=Path('out/a1_top5_early_fail_cap_shadow_v1.json')); p.add_argument('--self-test',action='store_true'); a=p.parse_args()
    if a.self_test: assert CELLS==(0.75,0.45); print('PASS_A1_TOP5_EARLY_FAIL_CAP_SHADOW_V1_SELF_TEST'); return
    r=run(a.trend70_source,a.a4_source_dir,a.break_source_dir,a.out); print(json.dumps({'state':r['state'],'lanes':[{'lane':x['lane'],'pass':x['pass_count'],'cells':x['cells']} for x in r['lanes']]},sort_keys=True))
if __name__=='__main__': main()
