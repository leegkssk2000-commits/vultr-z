#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as d


def session(ts_ms: int) -> str:
    h=datetime.fromtimestamp(ts_ms/1000,tz=timezone.utc).hour
    return 'APAC' if h < 8 else ('EU' if h < 14 else 'US')


def run(out: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix='trend_rider_loss_fast_') as td:
        receipt=d._run_receipt('trend_rider', Path(td)/'trend_rider.json')
    rows=[dict(x) for x in receipt.get('trades',[]) if isinstance(x,dict)]
    rows.sort(key=lambda x:(int(x.get('entry_ts') or 0),int(x.get('exit_ts') or 0)))
    for x in rows:
        x['session']=session(int(x.get('signal_ts') or x.get('entry_ts') or 0))
        x['hold_bars']=max(0.0,(int(x.get('exit_ts') or 0)-int(x.get('entry_ts') or 0))/3_600_000)
        gross=abs(float(x.get('gross_bps') or 0.0)); cost=float(x.get('realized_cost_bps') or 0.0)
        x['cost_to_abs_gross']=cost/max(gross,1e-9)
    streak=[]
    for x in reversed(rows):
        if float(x.get('net_bps') or 0.0)<=0: streak.append(x)
        else: break
    streak.reverse(); prior=rows[:-len(streak)] if streak else rows[:]
    hypotheses=[]
    for dim in ('symbol','side','session','reason'):
        if not streak: continue
        val,n=Counter(str(x.get(dim)) for x in streak).most_common(1)[0]
        ss=n/len(streak); ps=(sum(1 for x in prior if str(x.get(dim))==val)/len(prior)) if prior else 0.0
        hypotheses.append({'axis':dim.upper(),'value':val,'loss_streak_share':ss,'prior_share':ps,'delta_share':ss-ps,'score':max(0.0,ss-ps)*math.log2(2+len(streak))})
    for key in ('hold_bars','realized_cost_bps','cost_to_abs_gross'):
        a=[float(x[key]) for x in streak if x.get(key) is not None]; b=[float(x[key]) for x in prior if float(x.get('net_bps') or 0)>0 and x.get(key) is not None]
        if not a or not b: continue
        am=sum(a)/len(a); bm=sum(b)/len(b); rel=(am-bm)/max(abs(bm),1e-9)
        hypotheses.append({'axis':key.upper(),'loss_streak_mean':am,'winner_mean':bm,'relative_delta':rel,'score':min(3.0,abs(rel))*math.log2(2+len(streak))/2})
    hypotheses.sort(key=lambda x:(-float(x.get('score') or 0),str(x['axis'])))
    root=hypotheses[0] if hypotheses else None
    if len(streak)<3: route='NO_STREAK_TRIGGER_CONTINUE_COLLECTION'
    elif root and root['axis'] in {'SYMBOL','SIDE','SESSION'}: route=f"PREREGISTER_CONTEXT_CHILD:{root['axis']}:{root.get('value')}"
    elif root and root['axis']=='REASON': route=f"PREREGISTER_EXIT_GEOMETRY_CHILD:{root.get('value')}"
    elif root: route=f"PREREGISTER_DISTINCT_CAUSAL_CHILD:{root['axis']}"
    else: route='LOSS_STREAK_NO_DISCRIMINATING_AXIS'
    row={
        'schema_version':'zel.a1.trend_rider.loss_cluster_fast.v2','strategy_id':'trend_rider',
        'completed_trades':len(rows),'current_loss_streak':len(streak),'loss_streak_net_bps':sum(float(x.get('net_bps') or 0) for x in streak),
        'loss_streak_trades':[{k:x.get(k) for k in ('symbol','side','signal_ts','entry_ts','exit_ts','reason','gross_bps','realized_cost_bps','net_bps','session','hold_bars','cost_to_abs_gross')} for x in streak],
        'ranked_causal_hypotheses':hypotheses[:7],'recommended_route':route,
        'incumbent_mutated':False,'post_outcome_threshold_sweep':False,'fresh_child_boundary_required':len(streak)>=3,
        'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','protected_mutations':0,
    }
    row['receipt_sha256']=d.sha(row)
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(row,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
    return row


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,default=Path('out/a1_trend_rider_loss_cluster_fast_latest.json')); args=ap.parse_args(); r=run(args.out)
    print(json.dumps({'completed_trades':r['completed_trades'],'loss_streak':r['current_loss_streak'],'route':r['recommended_route'],'top':r['ranked_causal_hypotheses'][:5]},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
