#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,hashlib,math
from datetime import datetime,timezone
from pathlib import Path

def metrics(rows):
 vals=[float(x['net_bps']) for x in rows]; wins=[x for x in vals if x>0];loss=[-x for x in vals if x<0]
 gp=sum(wins);gl=sum(loss);aw=gp/len(wins) if wins else None;al=gl/len(loss) if loss else None
 eq=peak=dd=0.0
 for x in vals:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
 return {'trades':len(vals),'net_pnl_bps':sum(vals),'net_expectancy_bps':sum(vals)/len(vals) if vals else None,'profit_factor':gp/gl if gl>0 else None,'payoff':aw/al if aw is not None and al not in (None,0) else None,'win_rate':len(wins)/len(vals) if vals else None,'drawdown_bps':dd}
def passed(m):return m['trades']>0 and m['net_pnl_bps']>0 and m['net_expectancy_bps']>0 and (m['profit_factor'] is None or m['profit_factor']>=1) and (m['payoff'] is None or m['payoff']>=1)
def run(receipt):
 assert receipt['strategy_id']=='trend_rider';b=datetime.fromisoformat(receipt['boundary_utc'].replace('Z','+00:00'));bms=int(b.timestamp()*1000);day=86_400_000
 rows=receipt['trades'];wins={}
 for n in range(3):
  a=bms+n*day;z=bms+(n+1)*day; rs=[x for x in rows if a<=int(x['entry_ts'])<z];wins[f'W{n+1}']=metrics(rs)
 all3=[x for x in rows if bms<=int(x['entry_ts'])<bms+3*day];ma=metrics(all3)
 gate=all(passed(wins[k]) for k in ('W1','W2','W3')) and len(all3)>=10
 r={'schema_version':'zel.a1_trend_rider_fresh_w123_audit.v1','strategy_id':'trend_rider','policy_sha':receipt['policy_sha'],'config_sha':receipt['config_sha'],'boundary_utc':receipt['boundary_utc'],'window_rule':'three_fixed_24h_windows_immediately_after_preexisting_prospective_boundary','parameter_sweep':False,'W1':wins['W1'],'W2':wins['W2'],'W3':wins['W3'],'aggregate':ma,'economics_gate_pass':gate,'negative_controls':'PENDING_H4','fragility':'PENDING_H5','survivor_gate':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--receipt',required=True);p.add_argument('--out',default='out/a1_trend_rider_fresh_w123_audit_v1.json');a=p.parse_args();r=run(json.load(open(a.receipt)));Path(a.out).parent.mkdir(exist_ok=True);Path(a.out).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_TREND_RIDER_FRESH_W123_AUDIT_V1='+json.dumps(r,sort_keys=True))
