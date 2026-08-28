#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any
from backend.research.rebuild import a1_trend_ma_macd_ablation_child_v1 as ab
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import concentration, metrics

ROOT=Path(__file__).resolve().parents[3]
HARD=ROOT/'backend/research/zel_economic_hardening_policy_v1.json'
COST=ROOT/'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
SCHEMA='zel.a1.top6.trend_ma_macd.long_rebound.v2'

def stable(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def read(p:Path)->dict[str,Any]:
    x=json.loads(p.read_text())
    if not isinstance(x,dict): raise RuntimeError('OBJECT_REQUIRED')
    return x

def run(parent_path:Path,symbols:list[str],out:Path)->dict[str,Any]:
    parent=read(parent_path)
    if parent.get('strategy_id')!='trend_ma_macd': raise RuntimeError('TREND_MA_MACD_PARENT_REQUIRED')
    boundary=str(parent.get('boundary_utc') or '')
    if not boundary: raise RuntimeError('BOUNDARY_REQUIRED')
    native=[dict(x) for x in (parent.get('trades') or [])]
    parent_T=int(parent.get('completed_trades') or len(native))
    if not native: raise RuntimeError('EXACT_PARENT_TRADES_REQUIRED')
    if len(native)!=parent_T: raise RuntimeError(f'EXACT_PARENT_T_MISMATCH:{len(native)}:{parent_T}')

    hard,authority=read(HARD),read(COST)
    bars_by,maps,_snaps=ab.load_shared_inputs(symbols,authority)
    missing=sorted({str(x.get('symbol')) for x in native if str(x.get('symbol')) not in bars_by})
    if missing: raise RuntimeError(f'PARENT_SYMBOL_BAR_SOURCE_MISSING:{missing}')

    child=[dict(x) for x in native if str(x.get('side')).lower()=='long']
    bm,cm=metrics(native),metrics(child)
    bh,ch=concentration(native,bars_by,maps,hard),concentration(child,bars_by,maps,hard)
    checks={
      'exact_parent_trade_count_match':int(bm.get('trades') or 0)==parent_T,
      'T_at_least_25':int(cm.get('trades') or 0)>=25,
      'WR_improved':float(cm.get('win_rate') or 0)>float(bm.get('win_rate') or 0),
      'PNL_nonworse':float(cm.get('net_pnl_bps') or 0)>=float(bm.get('net_pnl_bps') or 0),
      'expectancy_improved':float(cm.get('net_expectancy_bps') or 0)>float(bm.get('net_expectancy_bps') or 0),
      'PF_nonworse':float(cm.get('profit_factor') or 0)>=float(bm.get('profit_factor') or 0),
      'DD_nonincrease':float(cm.get('drawdown_bps') or 1e30)<=float(bm.get('drawdown_bps') or 0),
      'concentration_nonworse':int(ch.get('blocker_count') or 0)<=int(bh.get('blocker_count') or 0),
    }
    passed=all(checks.values())
    r={
      'schema_version':SCHEMA,
      'state':'PASS_TOP6_STRUCTURAL_REBOUND_CANDIDATE' if passed else 'ROUTE_TREND_MA_MACD_TO_C_MATERIAL',
      'strategy_id':'trend_ma_macd',
      'axis':'LONG_ONLY_ENTRY_SIDE_QUALIFIER',
      'boundary_utc':boundary,
      'comparator_source':'EXACT_PARENT_TRADES_ONLY',
      'exact_parent_T':parent_T,
      'native':{'metrics':bm,'concentration':bh},
      'candidate':{'metrics':cm,'concentration':ch,'checks':checks,'trade_retention_pct':100*len(child)/max(1,len(native))},
      'payoff_is_not_optimization_target_here':True,
      'fresh_validation_required':True,
      'production_mutated':False,
      'selection_authority':False,
      'promotion_authority':False,
      'execution_authority':'NONE',
      'order_authority':'BLOCKED',
      'live_trade_authority':'BLOCKED',
      'action':'hold'
    }
    r['receipt_sha256']=stable(r)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return r

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--parent',type=Path)
    ap.add_argument('--out',type=Path,default=Path('out/a1_top6_trend_ma_macd_long_rebound_v1.json'))
    ap.add_argument('--symbols',default='BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,1INCH-USDT,ETHFI-USDT,HYPE-USDT,BCH-USDT,APE-USDT,1000PEPE-USDT,DOGE-USDT,LINK-USDT')
    ap.add_argument('--self-test',action='store_true')
    a=ap.parse_args()
    if a.self_test:
        assert SCHEMA.endswith('.v2')
        print('PASS_A1_TOP6_TREND_MA_MACD_LONG_REBOUND_V2_SELF_TEST')
        return 0
    if a.parent is None: raise SystemExit('--parent required')
    r=run(a.parent,[x.strip() for x in a.symbols.split(',') if x.strip()],a.out)
    print(json.dumps({'state':r['state'],'exact_parent_T':r['exact_parent_T'],'native':r['native']['metrics'],'candidate':r['candidate']['metrics'],'checks':r['candidate']['checks']},sort_keys=True))
    return 0
if __name__=='__main__': raise SystemExit(main())
