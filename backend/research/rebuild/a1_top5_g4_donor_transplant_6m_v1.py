#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from backend.research.rebuild import a1_top5_entry_transplant_replay_v1 as base
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child_eval
ROOT=Path(__file__).resolve().parents[3]
FREEZE=ROOT/'backend/research/contracts/a1_top5_replacement_child_freeze_v2.json'
ORIG=ROOT/'backend/research/contracts/a1_top5_entry_transplant_replay_v1.json'
INTERVAL_MS=14_400_000
DONOR_SCOPE={
 'break_replacement_breakout50_long_4h_h6_v2':{'source':'break_and_continue_main','allow':{'HYPE-USDT','LINK-USDT'}},
 'keltner_replacement_trend_pull_long_4h_h12_v2':{'source':'keltner_trend_main','allow':set()},
 'supertrend_replacement_highvol_mom_long_4h_h12_v2':{'source':'supertrend_pullback_main','allow':{'BTC-USDT','LINK-USDT'}},
}

def rd(p): return json.loads(Path(p).read_text())
def gate(m,p,ret):
    pfm=m.get('profit_factor'); pfp=p.get('profit_factor')
    pf_ok=(pfm is not None and (pfp is None or float(pfm)>float(pfp)))
    dd_ok=float(m.get('drawdown_bps') or 0)<float(p.get('drawdown_bps') or 0)
    checks={
      'T12':int(m.get('trades') or 0)>=12,
      'ret25':ret>=25.0,
      'net_pos':float(m.get('net_pnl_bps') or 0)>0,
      'exp_up':m.get('net_expectancy_bps') is not None and p.get('net_expectancy_bps') is not None and float(m['net_expectancy_bps'])>float(p['net_expectancy_bps']),
      'pf_or_dd_up':pf_ok or dd_ok,
    }
    return all(checks.values()),checks

def main(a):
    parents={x['lane_id']:x for x in map(rd,[a.break_json,a.keltner_json,a.supertrend_json])}
    contract=rd(ORIG); freeze=rd(FREEZE); archs={x['architecture_id']:x for x in base.architectures(contract,freeze)}
    allrows=[t for p in parents.values() for t in p['trades']]
    min_ts=min(int(x['signal_ts']) for x in allrows); max_ts=max(int(x['signal_ts']) for x in allrows)
    symbols=sorted({x['symbol'] for x in allrows})
    bars={s:child_eval._bars(s,'4h',min_ts,max_ts+INTERVAL_MS) for s in symbols}
    engines={}
    for aid,arch in archs.items():
      if aid not in DONOR_SCOPE: continue
      for s,b in bars.items():
        _,e=child_eval._features(b,arch['spec']); e.validate(str(arch['spec']['entry_rule'])); engines[(aid,s)]=e
    cells=[]
    for pl,p in parents.items():
      rows=[dict(x) for x in p['trades']]; pm=base.metric_plus(rows)
      for aid,scope in DONOR_SCOPE.items():
        if scope['source']==pl: continue
        acc=[]
        for r in rows:
          s=r['symbol']
          if scope['allow'] and s not in scope['allow']: continue
          ok,_=base.architecture_accepts(r,bars[s],engines[(aid,s)],archs[aid]['spec'])
          if ok: acc.append(r)
        m=base.metric_plus(acc); ret=(len(acc)/len(rows)*100) if rows else 0
        ok,checks=gate(m,pm,ret)
        cells.append({'parent_lane_id':pl,'donor_id':aid,'accepted_T':len(acc),'retention_pct':ret,'parent_metrics':pm,'metrics':m,'checks':checks,'pass_6m_transplant':ok,'decision':'TRANSPLANT_CANDIDATE' if ok else 'DROP_CHILD_KEEP_PARENT'})
    winners=[x for x in cells if x['pass_6m_transplant']]
    out={'state':'PASS_6M_DONOR_TRANSPLANT_REPLAY_COMPLETE','observed_at_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'cell_count':len(cells),'winner_count':len(winners),'winners':winners,'cells':cells,'fresh_g4_credit':0,'formal_g5_credit':0,'primary_deferred':True,'broad_deferred':True}
    Path(a.out).write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'state':out['state'],'winner_count':len(winners),'winners':[[x['parent_lane_id'],x['donor_id']] for x in winners]},sort_keys=True))
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--break-json',required=True); p.add_argument('--keltner-json',required=True); p.add_argument('--supertrend-json',required=True); p.add_argument('--out',required=True); main(p.parse_args())
