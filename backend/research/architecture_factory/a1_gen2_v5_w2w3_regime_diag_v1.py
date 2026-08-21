#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib,statistics
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_exhaustion_repair_v3 import signal as signal_v3
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import atr
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars
HOLD=6

def collect(rs,sym):
 out=[];i=50
 while i<len(rs)-HOLD-1:
  s=signal_v3(rs,i)
  if s is None or (sym=='ETH-USDT' and s!='short'):i+=1;continue
  ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);g=(xp/ep-1)*10000*(1 if s=='long' else -1)
  a=atr(rs,i,14); c=float(rs[i]['close']); vm=sum(float(x['volume']) for x in rs[i-19:i+1])/20
  rp=(float(rs[i]['high'])-float(rs[i]['low']))/c if c else 0
  out.append({'gross_bps':g,'entry_ts':int(rs[ei]['ts']),'atr_pct':a/c if a and c else 0,'vol_ratio':float(rs[i]['volume'])/vm if vm else 0,'range_pct':rp,'atr_accel':(a/atr(rs,i-1,14)) if a and atr(rs,i-1,14) else 0});i=xi+1
 return out

def stats(rows):
 r={}
 for f in ('atr_pct','vol_ratio','range_pct','atr_accel'):
  allv=[x[f] for x in rows];win=[x[f] for x in rows if x['gross_bps']>14];loss=[x[f] for x in rows if x['gross_bps']<=14]
  r[f]={'median':statistics.median(allv) if allv else None,'win_median':statistics.median(win) if win else None,'loss_median':statistics.median(loss) if loss else None}
 return r

def run():
 rows=[]
 for sym in SYMBOLS:
  rs,_=prior_bars(sym);rows+=collect(rs,sym)
 rows=sorted(rows,key=lambda x:x['entry_ts']);cut=len(rows)//2;w2=rows[:cut];w3=rows[cut:]
 r={'schema_version':'zel.a1_gen2_v5_w2w3_regime_diag.v1','W2':{'trades':len(w2),'features':stats(w2)},'W3':{'trades':len(w3),'features':stats(w3)},'diagnostic_only':True,'selection_authority':False,'promotion_authority':False}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_v5_w2w3_regime_diag_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_V5_W2W3_REGIME_DIAG_V1='+json.dumps(r,sort_keys=True))
