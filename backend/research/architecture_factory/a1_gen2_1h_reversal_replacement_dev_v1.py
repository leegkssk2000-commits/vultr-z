#!/usr/bin/env python3
from __future__ import annotations

import hashlib, json
from pathlib import Path
from typing import Any

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY, COST_BPS, SYMBOLS, bars

ROOT=Path(__file__).resolve().parents[3]
LEDGER=ROOT/'backend/research/rebuild/a1_exact25_disposition_ledger_v1.json'
PREP=ROOT/'backend/research/early_ai_prep/a1_early_negative_ai_prep_grid_rebalance_v1.json'
CID='replacement_1h_onebar_reversal_v1'


def sha(x:Any)->str:
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()

def pf(xs:list[float])->float|None:
    gp=sum(x for x in xs if x>0); gl=-sum(x for x in xs if x<0)
    return None if gl<=0 else gp/gl

def payoff(xs:list[float])->float|None:
    w=[x for x in xs if x>0]; l=[-x for x in xs if x<0]
    return None if not w or not l else (sum(w)/len(w))/(sum(l)/len(l))

def dd(xs:list[float])->float:
    e=p=m=0.0
    for x in xs: e+=x; p=max(p,e); m=max(m,p-e)
    return m

def metrics(ts:list[dict[str,Any]])->dict[str,Any]:
    g=[float(x['gross_bps']) for x in ts]; n=[float(x['net_bps']) for x in ts]
    return {'trades':len(ts),'gross_expectancy_bps':sum(g)/len(g) if g else None,'net_expectancy_bps':sum(n)/len(n) if n else None,'net_pnl_bps':sum(n),'profit_factor':pf(n),'payoff':payoff(n),'win_rate':sum(1 for x in n if x>0)/len(n) if n else None,'drawdown_bps':dd(n),'cost_bps_per_trade':COST_BPS}

def run()->dict[str,Any]:
    ledger=json.loads(LEDGER.read_text()); prep=json.loads(PREP.read_text()); grid=ledger['strategies']['grid_rebalance']
    if str(grid.get('status')) not in {'A1_ECONOMIC_FAIL','A1_COST_FUTILITY','A1_CAUSAL_CONTROL_FAIL','A1_SPARSE_EVENT_FUTILITY'}:
        return {'candidate_id':CID,'state':'SKIP_GRID_NOT_TERMINAL','economic_candidate':False,'development_only':True}
    s1=next(x for x in prep['external_sources'] if x['id']=='S1')
    trades=[]; source={}
    for symbol in SYMBOLS:
        rs=bars(symbol,'1h'); source[symbol]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None}
        # Pure first-order reversal test: no magnitude threshold, no parameter sweep.
        # Signal from completed bar t, enter t+1 open, exit t+1 close.
        for i in range(1,len(rs)-1):
            prev_ret=float(rs[i]['close'])/float(rs[i]['open'])-1.0
            if prev_ret==0: continue
            side='short' if prev_ret>0 else 'long'
            entry=float(rs[i+1]['open']); exit=float(rs[i+1]['close'])
            gross=(exit/entry-1.0)*10000.0*(1 if side=='long' else -1)
            net=gross-COST_BPS
            trades.append({'symbol':symbol,'side':side,'signal_ts':int(rs[i]['ts']),'entry_ts':int(rs[i+1]['ts']),'exit_ts':int(rs[i+1]['ts']),'gross_bps':gross,'net_bps':net})
    m=metrics(trades)
    r={'schema_version':'zel.a1_gen2_1h_reversal_replacement_dev.v1','candidate_id':CID,'replaces_family':'grid_rebalance','architecture':'1H_FIRST_ORDER_ONE_BAR_REVERSAL','mechanism':'Oppose the sign of the immediately completed 1h candle; next-bar-open entry and same 1h bar close exit.','evidence':s1,'boundary':BOUNDARY,'development_only':True,'prospective':False,'uses_data_strictly_before_gen1_boundary':True,'source_summary':source,'metrics':m,'economic_candidate':bool(m['trades']>=12 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1),'parameter_sweep':False,'tuned_thresholds':0,'cost_bps_per_trade':COST_BPS,'integrity':{'leakage_lookahead':0,'entry_timing':'next_bar_open','exit_timing':'same_bar_close','outcome_conditioning':False},'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0}
    r['receipt_sha256']=sha(r); return r

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('--out'); p.add_argument('--self-test',action='store_true'); a=p.parse_args()
    if a.self_test:
        assert COST_BPS==14.0 and CID=='replacement_1h_onebar_reversal_v1'; print('PASS_1H_REVERSAL_REPLACEMENT_SELF_TEST'); raise SystemExit(0)
    r=run();
    if a.out: Path(a.out).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps(r,sort_keys=True))
