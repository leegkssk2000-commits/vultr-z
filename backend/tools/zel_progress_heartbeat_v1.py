from __future__ import annotations
import argparse,hashlib,json,math
from datetime import datetime,timezone
from pathlib import Path
from statistics import median

def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(canon(v).encode()).hexdigest()
def build(a):
 if a.total<=0 or not 0<=a.completed<=a.total:raise ValueError('INVALID_COUNTS')
 durations=[float(x) for x in a.durations.split(',') if x.strip()] if a.durations else []
 durations=[x for x in durations if math.isfinite(x) and x>=0]
 eta=round(median(durations)*(a.total-a.completed),3) if len(durations)>=3 and a.completed<a.total else None
 d={'schema_version':'zel.progress.heartbeat.v1','pipeline_id':a.pipeline,'stage_id':a.stage,'run_id':a.run_id,'source_sha':a.source_sha,'started_at':a.started_at,'heartbeat_at':datetime.now(timezone.utc).isoformat(),'unit_kind':a.unit_kind,'total_units':a.total,'completed_units':a.completed,'progress_pct':round(100*a.completed/a.total,3),'current_unit':a.current,'error_count':a.errors,'state':a.state,'eta_seconds':eta,'action':'block' if a.state=='FAIL' else 'hold','next':a.next}
 d['receipt_sha256']=sha(d);return d
def main():
 p=argparse.ArgumentParser();p.add_argument('--pipeline',default='selftest');p.add_argument('--stage',default='1m');p.add_argument('--run-id',default='1');p.add_argument('--source-sha',default='a'*64);p.add_argument('--started-at',default='2026-08-01T00:00:00+00:00');p.add_argument('--unit-kind',default='strategy_window');p.add_argument('--total',type=int,default=75);p.add_argument('--completed',type=int,default=5);p.add_argument('--current',default='test');p.add_argument('--errors',type=int,default=0);p.add_argument('--state',default='RUNNING');p.add_argument('--next',default='continue');p.add_argument('--durations',default='9,10,11');p.add_argument('--out');a=p.parse_args();d=build(a)
 if a.out:Path(a.out).write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'state':'PASS_PROGRESS_HEARTBEAT','progress_pct':d['progress_pct'],'eta_seconds':d['eta_seconds'],'receipt':d['receipt_sha256']},sort_keys=True))
if __name__=='__main__':main()
