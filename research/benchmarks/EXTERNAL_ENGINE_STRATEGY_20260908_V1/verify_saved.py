"""Read-only standard-library verification; cannot import or run either engine."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SCOPE='EXTERNAL_ENGINE_STRATEGY_20260908_V1'
BUDGET='research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/BUDGET.json'
RUNS=['BREAK_DEV2025','BREAK_SEEN2026','HERACLES_DEV2025','HERACLES_SEEN2026']
OLD_BUDGET_BLOB='a2dbe0a859f3e27bb8c7780fc7c94225cf676f3e'
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def require(x,msg):
    if not x:raise ValueError(msg)
def near(a,b):return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-7)
def validate_record(r):
    ts=r['normalized_trades'];m=r['metrics'];closed=[t for t in ts if t['closed']]
    require(len({t['origin'] for t in ts})==len(ts),'DUPLICATE_ORIGIN')
    require(m['closed']==len(closed) and m['open']==len(ts)-len(closed),'COUNTS')
    require(m['wins']==sum(t['net_bps']>0 for t in closed),'WINS')
    require(near(m['terminal_net'],sum(t['net_bps'] for t in ts)),'TERMINAL_NET')
    require(near(m['terminal_cost2'],sum(t['cost2_bps'] for t in ts)),'TERMINAL_COST2')
    require(near(m['closed_net']+m['open_mark'],m['terminal_net']),'OPEN_ACCOUNTING')
    for t in ts:
        require(t['entry_ts']<=t['exit_ts_lower']<=t['exit_ts'],'TIME_ORDER')
        require(near(t['gross_bps'],(t['exit_price']/t['entry_price']-1)*10000),'PRICE_RETURN')
        require(near(t['net_bps'],t['gross_bps']-t['cost_bps']),'COST_DOUBLECOUNT')
        require(near(t['cost2_bps'],t['gross_bps']-2*t['cost_bps']),'COST2_DOUBLECOUNT')
        require(t['reason']!='force_exit' or not t['closed'],'FAKE_COMPLETED_FORCE_EXIT')
    peak=dd=0
    for _,v in m['equity4h']:peak=max(peak,v);dd=max(dd,peak-v)
    require(near(dd,m['mark4h_DD']),'MARKED_DD')
    require(near(m['equity4h'][-1][1],m['terminal_net']),'FINAL_EQUITY')
def verify():
    spec=json.loads((HERE/'SPEC.json').read_bytes());seal=spec.pop('receipt_sha256')
    require(seal==digest(spec),'SPEC_SEAL')
    for p,h in spec['scientific_files'].items():require(hashlib.sha256((HERE/p).read_bytes()).hexdigest()==h,'SCIENTIFIC_CODE_CHANGED:'+p)
    raw=(HERE/'UPSTREAM_Heracles.py').read_bytes()
    require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==spec['source_blob'],'UPSTREAM_SOURCE_CHANGED')
    for n,name in enumerate(RUNS,69):
        attempt=json.loads((HERE/'attempts'/f'{name}.json').read_bytes())
        receipt=json.loads((HERE/'receipts'/f'{name}.json').read_bytes());raw=(HERE/'results'/f'{name}.json').read_bytes()
        require(attempt['actual_experiment_ordinal']==n and receipt['ordinal']==n,'ORDINAL')
        require(attempt['specification_sha256']==receipt['specification_sha256']==seal,'SPEC_BINDING')
        require(receipt['status']=='COMPLETED' and receipt['result_sha256']==hashlib.sha256(raw).hexdigest(),'RECEIPT_RESULT')
        r=json.loads(raw);require(r['engine_dependencies']==spec['engine_dependencies'],'ENGINE_CODE_IDENTITY');validate_record(r)
        parent=ROOT/'research/development_evidence/FOCUSED_REPAIR_20260907_V1/BR2'/f"{r['period']}.json.gz"
        require(hashlib.sha256(parent.read_bytes()).hexdigest()==r['saved_native_file_sha256'],'SAVED_CONTROL_CHANGED')
    current=json.loads((ROOT/BUDGET).read_bytes())
    b=json.loads((HERE/'EXECUTED_BUDGET.json').read_bytes());a=b['external_benchmark_allocation']
    require(current['external_benchmark_allocation']==a,'SCOPE_ALLOCATION_CHANGED')
    require(current['cumulative_actual']>=48 and current['cumulative_actual_evaluations']>=72,'COUNTERS_REGRESSED')
    require([t for t in current['trials'] if t.get('scope')==SCOPE]==[t for t in b['trials'] if t.get('scope')==SCOPE],'SCOPE_TRIALS_CHANGED')
    require(a['used']==a['completed']==4 and a['status']=='COMPLETED','INCOMPLETE_ALLOCATION')
    require((b['cumulative_actual'],b['cumulative_actual_evaluations'])==(48,72),'EXECUTED_TOTAL_COUNTS')
    old=deepcopy(b);old.pop('external_benchmark_allocation')
    old['trials']=[t for t in old['trials'] if t.get('scope')!=SCOPE]
    old['candidate_trials']=[t for t in old['candidate_trials'] if t.get('scope')!=SCOPE]
    old['cumulative_actual']=47;old['cumulative_actual_evaluations']=68
    raw=(json.dumps(old,sort_keys=True,indent=2)+'\n').encode()
    require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==OLD_BUDGET_BLOB,'PROTECTED_BUDGET_HISTORY_CHANGED')
    return {'status':'FOUR_STORED_RESULTS_VERIFIED','economic_replays':0,'formal_credit':0,'old_budget_preserved':True}
if __name__=='__main__':print(json.dumps(verify()))
