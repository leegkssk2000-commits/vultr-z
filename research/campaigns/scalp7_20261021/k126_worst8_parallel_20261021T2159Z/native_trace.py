"""Observe frozen native pending-HG state. Exact incumbent parity, no new rule."""
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
from datetime import datetime,timezone
from collections import Counter
import sys,json,io,hashlib,inspect,math,fcntl,os
import pandas as pd
S=Path(__file__).resolve().parent
STAGE=Path('/home/z/z/runtime/k126_pullback_structure_failure_20261021_v1')
sys.path.insert(0,str(STAGE));import structural_failure as a
from backend.research.rebuild import scalp7_source_data_v2 as source, scalp7_rolling_context_v2 as context
h=a.h
def sha(b):return hashlib.sha256(b).hexdigest()
def enc(v):return (json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
def key(r):return (r['symbol'],int(r['side']),int(r['signal_ts_ms']))
def stamp(ts):return datetime.fromtimestamp(ts/1000,timezone.utc).isoformat()
def main():
 if (S/'NATIVE_TRACE.json').exists():raise ValueError('TRACE_ALREADY_EXISTS')
 # Existing capacity/locks only; no daemon, queue, owner mutation, or new economics.
 sys.path.append('/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1')
 import guard_exact_allocation_once as cap
 cap.original.S=S;cap.original.REQUESTS=0
 busy,evidence=cap.live_capacity();local=cap.original.local_busy()
 if busy or local:
  print('CAPACITY_BUSY_READ_ONLY_TRACE_NOT_RUN',json.dumps({'busy':busy,'local':local}));return
 lock=(h.BASE/'paired.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 cache=Path('/home/z/z/runtime/k_winner_handoff_20261021T1230Z');meta=json.loads((cache/'INPUT_CACHE.json').read_bytes());frames={}
 for sym in source.SYMBOLS:
  r=meta['symbols'][sym];raw=(cache/r['path']).read_bytes();assert sha(raw)==r['sha256']
  frames[sym]=pd.read_csv(io.BytesIO(raw),compression='gzip',float_precision='round_trip')
 windows=json.loads((h.REPO/'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json').read_bytes())['windows']
 bound,fits=context.bind_context(frames,context.cross_features(frames),windows)
 summary=json.loads((STAGE/'SUMMARY.json').read_bytes());assert sha(json.dumps(fits,sort_keys=True,separators=(',',':')).encode())==summary['context_fit_sha256']
 costs=json.loads((h.REPO/'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_bytes())['costs_bps']
 from ops.scalp7_benchmark_observer_v1 import HGObserver
 # The native observer receives per-symbol before/after state and admission.
 observations=[]
 control=a.ExitComparison(True).build()(bound,costs,windows,benchmark_observations=observations)
 actual=[r for r in control['trades'] if r['partition']=='rolling']
 saved=json.loads((STAGE/'ROWS.json').read_bytes())['raw_trades']
 assert actual==saved,'OBSERVER_CHANGED_INCUMBENT'
 assert len(actual)==126
 fields=Counter(k for r in observations for k in r)
 print('OBS_FIELDS',dict(fields));print('EXAMPLE',json.dumps(observations[-1],ensure_ascii=False)[:6000])
 targets={key(r) for r in saved}
 print('OBS_N',len(observations),'ALL126_PARITY',True)
 selected=[]
 for r in observations:
  if any(r.get('symbol')==k[0] and int(r.get('signal_open_ts_ms',-1))+1800000==k[2] for k in targets):selected.append(r)
 # Keep all prior events for targeted symbols as provenance, no outcome-guided exclusions.
 import gzip
 with (S/'NATIVE_OBSERVATIONS_ALL.json.gz').open('xb') as f:f.write(gzip.compress(enc(observations),mtime=0))
 report={'at_utc':datetime.now(timezone.utc).isoformat(),'classification':'EXACT_INCUMBENT_NATIVE_OBSERVER_NO_NEW_POLICY','same126_raw_rows_exact':True,'source_module':h.k.__file__,'source_sha256':sha(Path(h.k.__file__).read_bytes()),'observation_count':len(observations),'targeted_entry_observations':selected,'new_rule_comparisons':0,'source_policy_changed':False,'capacity_evidence':evidence}
 with (S/'NATIVE_TRACE.json').open('xb') as f:f.write(enc(report))
 print('TARGET_OBS',json.dumps(selected[:2],ensure_ascii=False)[:7000]);print('DONE',len(selected))
if __name__=='__main__':main()
