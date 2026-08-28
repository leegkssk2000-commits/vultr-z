#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any, Mapping
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import metrics

ROOT=Path(__file__).resolve().parents[3]
COST=ROOT/'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
CAPS=(0.75,0.45)
SCHEMA='zel.a1.top5.native_runner_loss_cap_shadow.v1'

def read(p:Path)->dict[str,Any]:
    x=json.loads(p.read_text())
    if not isinstance(x,dict): raise RuntimeError(f'OBJECT_REQUIRED:{p}')
    return x

def stable(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()

def key(x:Mapping[str,Any])->tuple[Any,...]:
    return (x.get('symbol'),int(x.get('signal_ts') or 0),int(x.get('entry_ts') or 0),x.get('side'))

def loss_cap_rows(rows:list[dict[str,Any]],cap_r:float,bars_by:Mapping[str,list[dict[str,Any]]])->tuple[list[dict[str,Any]],dict[str,int]]:
    out=[]; stats={'capped':0,'native_winner_capped':0,'native_loser_capped':0,'unchanged':0}
    idx_by={s:{int(b['ts_ms']):i for i,b in bars} for s,bars in bars_by.items()}
    for src in rows:
        row=dict(src); sym=str(row['symbol']); bars=bars_by[sym]; idx=idx_by[sym]
        si=idx.get(int(row['signal_ts'])); ei=idx.get(int(row['entry_ts'])); xi=idx.get(int(row['exit_ts']))
        if si is None or ei is None or xi is None: raise RuntimeError(f'ROW_BAR_MISSING:{sym}:{key(row)}')
        entry=float(row.get('entry') or bars[ei]['open']); side=str(row['side']); one_r=rr.native_r(row,bars,si,entry)
        stop=entry-cap_r*one_r if side=='long' else entry+cap_r*one_r
        hit_i=None
        for j in range(ei,xi+1):
            lo=float(bars[j]['low']); hi=float(bars[j]['high'])
            hit=(lo<=stop if side=='long' else hi>=stop)
            if hit:
                hit_i=j; break
        if hit_i is None:
            stats['unchanged']+=1; out.append(row); continue
        gross=(stop-entry)/entry*10000 if side=='long' else (entry-stop)/entry*10000
        # Conservative: retain the native realized cost even when the cap exits earlier.
        cost=float(row.get('realized_cost_bps') or 0.0)
        native_net=float(row.get('net_bps') or 0.0)
        capped={**row,'exit_ts':int(bars[hit_i]['ts_ms']),'exit':float(stop),'gross_bps':float(gross),'net_bps':float(gross-cost),'realized_cost_bps':cost,'reason':f'LOSS_CAP_{cap_r:.2f}R','loss_cap_r':cap_r,'native_exit_preserved':False}
        stats['capped']+=1
        if native_net>0: stats['native_winner_capped']+=1
        else: stats['native_loser_capped']+=1
        out.append(capped)
    return out,stats

def strict(cm:Mapping[str,Any],bm:Mapping[str,Any],cp:float|None,bp:float|None)->tuple[bool,dict[str,bool]]:
    wr0=float(bm.get('win_rate') or 0.0)
    checks={
      'T_same':int(cm.get('trades') or 0)==int(bm.get('trades') or 0),
      'WR_retention_80pct':float(cm.get('win_rate') or 0.0)+1e-12>=0.8*wr0,
      'PNL_nondecrease':float(cm.get('net_pnl_bps') or 0.0)>=float(bm.get('net_pnl_bps') or 0.0),
      'expectancy_nondecrease':float(cm.get('net_expectancy_bps') or 0.0)>=float(bm.get('net_expectancy_bps') or 0.0),
      'PF_nondecrease':float(cm.get('profit_factor') or 0.0)>=float(bm.get('profit_factor') or 0.0),
      'payoff_improved':cp is not None and bp is not None and cp>bp,
      'DD_nonincrease':float(cm.get('drawdown_bps') or 1e30)<=float(bm.get('drawdown_bps') or 0.0),
    }
    return all(checks.values()),checks

def score(cm:Mapping[str,Any],cp:float|None)->float:
    return float(cm.get('net_expectancy_bps') or -1e18)*max(float(cm.get('profit_factor') or 0),0)*max(float(cp or 0),0)/max(float(cm.get('drawdown_bps') or 1e30),1)

def run(trend_path:Path,a4dir:Path,breakdir:Path,out:Path)->dict[str,Any]:
    trend=read(trend_path)
    lanes=rr.latest_sets(trend,a4dir,breakdir)
    syms=sorted({str(t['symbol']) for lane in lanes for t in lane['rows']})
    bars_by={s:ev.fetch_bars(s,'1h',1000) for s in syms}
    results=[]
    for lane in lanes:
        base=[dict(x) for x in lane['rows']]; bm=metrics(base); bp=rr.payoff(base); cells=[]
        for cap in CAPS:
            cand,cap_stats=loss_cap_rows(base,cap,bars_by); cm=metrics(cand); cp=rr.payoff(cand); ok,checks=strict(cm,bm,cp,bp)
            cells.append({'loss_cap_r':cap,'upside_exit':'NATIVE_RUNNER_UNCHANGED_UNLESS_LOSS_CAP_HIT_FIRST','metrics':cm,'payoff':cp,'strict_pass':ok,'checks':checks,'cap_stats':cap_stats,'score':score(cm,cp)})
        cells.sort(key=lambda x:(not x['strict_pass'],-x['score']))
        results.append({**{k:lane[k] for k in ('lane','strategy_id','reference')},'base_metrics':bm,'base_payoff':bp,'cells':cells,'pass_count':sum(1 for x in cells if x['strict_pass']),'best':cells[0]})
    r={'schema_version':SCHEMA,'state':'PASS_TOP5_NATIVE_RUNNER_LOSS_CAP_SHADOW_COMPLETE','loss_caps_r':list(CAPS),'objective':'KEEP_NATIVE_UPSIDE_RUNNER_AND_CUT_LOSSES_EARLIER','fixed_tp_forbidden':True,'T_policy':'SAME_ENTRIES_SAME_T','wr_retention_floor_ratio':0.8,'lanes':results,'shadow_only':True,'trend_rider_broad_g5_reference_mutated':False,'adoption_for_trend_rider_broad_forbidden_until_g5_window_complete':True,'production_mutated':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','action':'hold'}
    r['receipt_sha256']=stable(r); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n'); return r

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--trend70-source',type=Path); ap.add_argument('--a4-source-dir',type=Path); ap.add_argument('--break-source-dir',type=Path); ap.add_argument('--out',type=Path,default=Path('out/a1_top5_native_runner_loss_cap_shadow_v1.json')); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:
        assert CAPS==(0.75,0.45); print('PASS_A1_TOP5_NATIVE_RUNNER_LOSS_CAP_SHADOW_V1_SELF_TEST'); return 0
    if None in (a.trend70_source,a.a4_source_dir,a.break_source_dir): raise SystemExit('sources required')
    r=run(a.trend70_source,a.a4_source_dir,a.break_source_dir,a.out); print(json.dumps({'state':r['state'],'lanes':[{'lane':x['lane'],'T':x['base_metrics']['trades'],'pass':x['pass_count'],'best':x['best']} for x in r['lanes']]},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
