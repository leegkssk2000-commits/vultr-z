#!/usr/bin/env python3
from __future__ import annotations
import json, statistics
from datetime import datetime, timezone
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_incumbent_hardening_v1 as inc
import backend.research.architecture_factory.a1_gen2_prospective_data_v1 as prospective

BOUNDARY_ISO='2026-08-20T19:49:13Z'
BOUNDARY_MS=int(datetime.fromisoformat(BOUNDARY_ISO.replace('Z','+00:00')).timestamp()*1000)
MIN_TRADES=20
MIN_SYMBOLS=2
MAX_DD_MULTIPLE_VS_DEV=1.50
DEV_DD_BPS=3149.2984443634814


def metrics(a):
 n=len(a)
 return {'trades':n,'net_expectancy_bps':sum(a)/n if n else None,'net_pnl_bps':sum(a),'profit_factor':inc.econ._pf(a) if n else None,'payoff':inc.econ._payoff(a) if n else None,'win_rate':sum(x>0 for x in a)/n if n else None,'drawdown_bps':inc.econ._dd(a) if n else 0.0}


def run(output:Path):
 t=inc.trades(prospective.bars)
 veto={id(x) for x in t if x['side']=='long' and x['above'] and x['shock_atr']>=1.0}
 kept=[x for x in t if id(x) not in veto]
 stress=set()
 for x in sorted(kept,key=lambda z:z['signal_ts']):
  if x['symbol']!='ETH-USDT' or x['above']:
   continue
  prior=[z for z in kept if z['symbol']==x['symbol'] and z['exit_ts']<x['signal_ts'] and z['n']<0]
  if len(prior)>=10:
   losses=[abs(z['n']) for z in prior]
   if sum(losses[-5:])/5.0>statistics.median(losses):
    stress.add(id(x))
 def val(x): return x['n']*(inc.W if id(x) in stress else 1.0)
 fresh=[x for x in kept if x['signal_ts']>BOUNDARY_MS]
 fm=metrics([val(x) for x in fresh])
 symbols=sorted({x['symbol'] for x in fresh})
 mature=fm['trades']>=MIN_TRADES and len(symbols)>=MIN_SYMBOLS
 econ_pass=bool(mature and fm['net_expectancy_bps'] is not None and fm['net_expectancy_bps']>0 and fm['profit_factor'] is not None and fm['profit_factor']>1 and fm['drawdown_bps']<=DEV_DD_BPS*MAX_DD_MULTIPLE_VS_DEV)
 if not mature: state='WAIT_FRESH_SAMPLE'
 elif econ_pass: state='PASS_PROSPECTIVE_REPLAY'
 else: state='FAIL_PROSPECTIVE_REPLAY'
 r={'schema_version':'zel.a1_gen2_fresh_boundary_replay.v1','data_plane':'PROSPECTIVE_CLOSED_BARS','development_cutoff_reused':False,'candidate_id':'atr_long_veto_eth_stress075','boundary_iso':BOUNDARY_ISO,'boundary_ms':BOUNDARY_MS,'frozen_rule':True,'threshold_sweep':False,'future_information_used':False,'fresh_trade_count':fm['trades'],'fresh_symbols':symbols,'minimum_gate':{'trades':MIN_TRADES,'symbols':MIN_SYMBOLS,'max_dd_multiple_vs_dev':MAX_DD_MULTIPLE_VS_DEV},'fresh_metrics':fm,'mature':mature,'prospective_pass':econ_pass,'state':state,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('FRESH_BOUNDARY_REPLAY='+json.dumps(r,sort_keys=True)); return r

if __name__=='__main__': run(Path('out/a1_gen2_fresh_boundary_replay_v1.json'))
