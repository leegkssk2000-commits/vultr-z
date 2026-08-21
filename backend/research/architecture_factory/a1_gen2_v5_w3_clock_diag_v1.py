#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from datetime import datetime,timezone
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_ownership_repair_v5 import owned
from backend.research.architecture_factory.a1_gen2_4h_range_atr_exhaustion_repair_v3 import collect as collect_v3,m
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars

def run():
 rows=[]
 for sym in SYMBOLS:
  prs,_=prior_bars(sym);rows+=owned(collect_v3(prs,sym))
 rows=sorted(rows,key=lambda x:x['entry_ts']);cut=len(rows)//2;w2=rows[:cut];w3=rows[cut:]
 def by_hour(xs):
  out={}
  for h in (0,4,8,12,16,20):
   z=[x for x in xs if datetime.fromtimestamp(x['entry_ts']/1000,tz=timezone.utc).hour==h];out[str(h)]=m(z)
  return out
 def by_hour_side(xs):
  out={}
  for h in (0,4,8,12,16,20):
   for s in ('long','short'):
    z=[x for x in xs if datetime.fromtimestamp(x['entry_ts']/1000,tz=timezone.utc).hour==h and x['side']==s];out[f'{h}_{s}']=m(z)
  return out
 r={'schema_version':'zel.a1_gen2_v5_w3_clock_diag.v1','diagnostic_only':True,'W2':m(w2),'W3':m(w3),'W2_by_hour':by_hour(w2),'W3_by_hour':by_hour(w3),'W3_by_hour_side':by_hour_side(w3),'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_v5_w3_clock_diag_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_V5_W3_CLOCK_DIAG_V1='+json.dumps(r,sort_keys=True))
# trigger
