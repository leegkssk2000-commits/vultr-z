#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import signal,metrics,HOLD
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS

def sma(rs,i,n):
 if i+1<n:return None
 return sum(float(rs[j]['close']) for j in range(i-n+1,i+1))/n

def collect():
 rows=[]
 for sym in SYMBOLS:
  rs,_=prior_bars(sym); i=200
  while i<len(rs)-HOLD-1:
   side=signal(rs,i)
   if side is None:i+=1;continue
   ei=i+1; xi=ei+HOLD-1; ep=float(rs[ei]['open']); xp=float(rs[xi]['close']); gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   ma=sma(rs,i,200); pma=sma(rs,i-1,200); c=float(rs[i]['close'])
   aligned=bool(ma is not None and pma is not None and ((side=='long' and c>ma and ma>pma) or (side=='short' and c<ma and ma<pma)))
   rows.append({'symbol':sym,'side':side,'gross_bps':gross,'entry_ts':int(rs[ei]['ts']),'sma200_aligned':aligned})
   i=xi+1
 return sorted(rows,key=lambda x:x['entry_ts'])

def m(rows):return metrics([x['gross_bps'] for x in rows])

def run():
 rows=collect(); cut=len(rows)//2; w3=rows[cut:]
 groups={}
 for sym in SYMBOLS:
  for side in ('long','short'):
   for aligned in (True,False):
    k=f'{sym}|{side}|sma200_aligned={str(aligned).lower()}'
    rr=[x for x in w3 if x['symbol']==sym and x['side']==side and x['sma200_aligned']==aligned]
    groups[k]=m(rr) if rr else {'trades':0}
 by_align={str(v).lower():m([x for x in w3 if x['sma200_aligned']==v]) for v in (True,False)}
 by_symbol={s:m([x for x in w3 if x['symbol']==s]) for s in SYMBOLS}
 by_side={s:m([x for x in w3 if x['side']==s]) for s in ('long','short')}
 r={'schema_version':'zel.a1_gen2_4h_range_atr_w3_diagnose.v1','diagnostic_only':True,'w3_metrics':m(w3),'by_symbol':by_symbol,'by_side':by_side,'by_sma200_alignment':by_align,'cross_groups':groups,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_w3_diagnose_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_W3_DIAG_V1='+json.dumps(r,sort_keys=True))
