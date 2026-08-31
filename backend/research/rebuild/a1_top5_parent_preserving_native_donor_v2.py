#!/usr/bin/env python3
from __future__ import annotations
import argparse,bisect,json,math,statistics
from pathlib import Path
from typing import Any,Mapping
from backend.research.rebuild import a1_top5_parent_preserving_component_transplant_v1 as v1

ROOT=Path(__file__).resolve().parents[3]
CONTRACT=ROOT/'backend/research/contracts/a1_top5_parent_preserving_native_donor_v2.json'
PARENTS=ROOT/'backend/research/rebuild/a1_production_highwr_rolling_closed_latest.json'
OUT=ROOT/'backend/research/rebuild/a1_top5_parent_preserving_native_donor_v2_latest.json'
LANES=('keltner_trend_main','supertrend_pullback_main')

def read(p:Path)->dict[str,Any]:
    x=json.loads(p.read_text());
    if not isinstance(x,dict): raise RuntimeError('OBJECT_REQUIRED')
    return x

def table(rows:list[dict[str,float]])->tuple[list[int],list[dict[str,bool]]]:
    ts,base=v1.feature_table(rows)
    c=[float(x['close']) for x in rows]
    e20=v1.ema(c,20); e50=v1.ema(c,50)
    ret=[None]+[(c[i]/c[i-1]-1.0) if c[i-1] else None for i in range(1,len(c))]
    out=[]
    for i,b in enumerate(base):
        r20=[float(x) for x in ret[max(1,i-19):i+1] if x is not None]
        sd=statistics.pstdev(r20) if len(r20)>=20 else None
        mom15=bool(ret[i] is not None and sd not in (None,0) and e20[i] is not None and e50[i] is not None and float(ret[i])>0 and abs(float(ret[i]))>=1.5*float(sd) and float(e20[i])>float(e50[i]))
        out.append({'KELTNER_RECLAIM':bool(b['KELTNER_RECLAIM']),'SUPERTREND_MOMENTUM_1P50':mom15})
    return ts,out

def flags(trades:list[Mapping[str,Any]])->dict[str,dict[str,bool]]:
    by={}
    for t in trades: by.setdefault(str(t['symbol']),[]).append(t)
    out={}
    for sym,tt in by.items():
        mx=max(int(x['signal_ts']) for x in tt)
        bars=v1.req(sym,mx+v1.TF_MS); ts,ft=table(bars)
        for t in tt:
            j=bisect.bisect_right(ts,int(t['signal_ts'])-v1.TF_MS)-1
            f=ft[j] if j>=0 else {'KELTNER_RECLAIM':False,'SUPERTREND_MOMENTUM_1P50':False}
            out[str(t['closed_trade_id'])]=f
    return out

def gate(parent:Mapping[str,Any],child:Mapping[str,Any],kept:int,total:int,cfg:Mapping[str,Any])->dict[str,Any]:
    need=max(int(cfg['minimum_kept_T']),math.ceil(total*float(cfg['minimum_retention_ratio'])))
    pp=v1.pf_score(parent); cp=v1.pf_score(child)
    pe=float(parent.get('net_expectancy_bps') or 0); ce=float(child.get('net_expectancy_bps') or -1e30)
    pd=float(parent.get('drawdown_bps') or 0); cd=float(child.get('drawdown_bps') or 0)
    dims={'net_expectancy_bps':ce>pe,'profit_factor':cp>pp,'drawdown_bps':cd<pd}
    ok=kept>=need and float(child.get('net_pnl_bps') or 0)>0 and ce>pe and sum(dims.values())>=int(cfg['improvement_dimensions_required'])
    return {'pass':ok,'minimum_kept_T_effective':need,'retention_ratio':kept/total if total else 0,'dimensions':dims,'improvement_count':sum(dims.values()),'net_expectancy_delta_bps':ce-pe,'drawdown_reduction_bps':pd-cd,'profit_factor_delta':(cp-pp if cp<1e29 and pp<1e29 else None)}

def run(out:Path)->dict[str,Any]:
    c=read(CONTRACT); src=read(PARENTS)
    if c['state']!='PREREGISTERED_BEFORE_NATIVE_DONOR_RESULTS': raise RuntimeError('CONTRACT_STATE')
    lanes={}
    for lane_id in LANES:
        trades=[dict(x) for x in src['lanes'][lane_id]['closed_trades']]
        pm=v1.metrics(trades); f=flags(trades); cell=c['cells'][lane_id]
        kept=[t for t in trades if f[str(t['closed_trade_id'])][cell['predicate']]]
        cm=v1.metrics(kept); g=gate(pm,cm,len(kept),len(trades),c['gate'])
        lanes[lane_id]={'original_parent_preserved':True,'parent_T':len(trades),'parent_metrics':pm,'cell_id':cell['cell_id'],'predicate':cell['predicate'],'donor_source_T_not_consumed':cell['donor_source_T'],'kept_T':len(kept),'rejected_T':len(trades)-len(kept),'child_metrics':cm,'gate':g,'selected_for_fresh_freeze':bool(g['pass']),'formal_g4_credit_T':0,'formal_g5_credit_T':0,'kept_trade_ids':[str(x['closed_trade_id']) for x in kept]}
    r={'schema_version':'zel.a1.top5.parent_preserving_native_donor.receipt.v2','state':'PASS_NATIVE_DONOR_PARENT_REPLAY_COMPLETE','contract_path':str(CONTRACT.relative_to(ROOT)),'lanes':lanes,'whole_development_population_consumed':False,'threshold_sweep':False,'post_result_retune':False,'parent_exit_mutation_count':0,'cost_rededuction_count':0,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
    r['receipt_sha256']=v1.sha(r); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({k:{'parent_T':x['parent_T'],'parent':x['parent_metrics'],'cell':x['cell_id'],'kept_T':x['kept_T'],'child':x['child_metrics'],'pass':x['gate']['pass']} for k,x in lanes.items()},sort_keys=True)); return r

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=OUT);a=p.parse_args();run(a.out)
if __name__=='__main__':main()
