"""Verify preserved execution evidence only. No market/FT import or replay."""
import argparse,gzip,hashlib,json,math
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
FROZEN=HERE.parent/'D2_HLHB_FREQTRADE_2026_7_V1'
START,END=1778198400000,1788566400000
KINDS={'D2':77,'HLHB':78}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def require(ok,msg):
    if not ok:raise ValueError(msg)
def close(x,y):return math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-7)
def validate_rows(result):
    ts=result['normalized_trades'];m=result['metrics']
    require(len({t['origin'] for t in ts})==len(ts),'DUPLICATE_ORIGIN')
    closed=[t for t in ts if t['closed']]
    wins=[t['net_bps'] for t in closed if t['net_bps']>0]
    losses=[-t['net_bps'] for t in closed if t['net_bps']<0]
    for t in ts:
        require(START<=t['entry_ts']<END and t['entry_ts']<=t['exit_ts']<=END,'INVALID_CALENDAR')
        require(close(t['gross_bps'],(t['exit_price']/t['entry_price']-1)*10000),'PRICE_GROSS_MISMATCH')
        require(close(t['net_bps'],t['gross_bps']-t['cost_bps']),'NET_MISMATCH')
        require(close(t['cost2_bps'],t['gross_bps']-2*t['cost_bps']),'COST2_MISMATCH')
        require(t['closed'] or (t['reason']=='force_exit' and t['exit_ts']==END),'OPEN_MARK_SEMANTICS')
    require((m['closed'],m['open'],m['wins'],m['losses'])==(len(closed),len(ts)-len(closed),len(wins),len(losses)),'COUNTS_MISMATCH')
    expected={'terminal_net':sum(t['net_bps'] for t in ts),'terminal_cost2':sum(t['cost2_bps'] for t in ts),
              'closed_net':sum(t['net_bps'] for t in closed),'open_mark':sum(t['net_bps'] for t in ts if not t['closed']),
              'gross_total_bps':sum(t['gross_bps'] for t in ts),'cost_total_bps':sum(t['cost_bps'] for t in ts),
              'win_rate':len(wins)/len(closed) if closed else None,
              'PF':sum(wins)/sum(losses) if losses else None,
              'payoff':(sum(wins)/len(wins))/(sum(losses)/len(losses)) if wins and losses else None}
    for k,x in expected.items():
        require(m[k] is None if x is None else close(m[k],x),'METRIC_MISMATCH:'+k)
    for curvekey,terminalkey,ddkey in [('equity4h','terminal_net','mark4h_DD'),('equity4h_cost2','terminal_cost2','mark4h_cost2_DD')]:
        curve=m[curvekey];require(curve[-1][0]==END and close(curve[-1][1],m[terminalkey]),'FINAL_MARK_MISMATCH')
        peak=dd=0.
        for stamp,equity in curve:
            require(START<stamp<=END,'CURVE_CALENDAR');peak=max(peak,equity);dd=max(dd,peak-equity)
        require(close(dd,m[ddkey]),'CURVE_DD_MISMATCH')
    if 'parity' in result:
        p=result['parity']
        for key in ['signal_differences','entry_differences','reference_differences','callback_errors']:
            require(not p[key],'D2_UNRESOLVED_'+key.upper())
    return {'closed':m['closed'],'open':m['open'],'terminal_net':m['terminal_net'],'cost2':m['terminal_cost2']}

def verify(root=HERE,expected_manifest_sha=None):
    root=Path(root);repo=root.parents[2];frozen=root.parent/FROZEN.name
    manifest_raw=(root/'FINAL_HASHES.json').read_bytes()
    if expected_manifest_sha:require(sha(manifest_raw)==expected_manifest_sha,'MANIFEST_DRIFT')
    manifest=json.loads(manifest_raw)
    for name,digest in manifest.items():require(sha((root/name).read_bytes())==digest,'FILE_DRIFT:'+name)
    spec=read(root/'SPEC.json')
    for name,digest in spec['files_sha256'].items():require(sha((repo/name).read_bytes())==digest,'FROZEN_CODE_DRIFT:'+name)
    require(sha((frozen/'BUDGET.json').read_bytes())==spec['old_budget_sha256'],'OLD_BUDGET_DRIFT')
    require(sha((frozen/'SPEC.json').read_bytes())==spec['old_spec_sha256'],'OLD_SPEC_DRIFT')
    budget=read(root/'BUDGET.json');a=budget['calendar_repair_allocation']
    require((a['used'],a['started'],a['completed'],a['failed'],a['remaining'])==(2,2,2,0,0),'ALLOCATION_NOT_COMPLETED')
    projection=deepcopy(budget);projection.pop('calendar_repair_allocation');new_trials=projection['trials'][-2:]
    projection['trials']=projection['trials'][:-2];projection['cumulative_actual_evaluations']-=2
    require(projection==read(frozen/'BUDGET.json'),'PRIOR_HISTORY_CHANGED')
    require([t['actual_experiment_ordinal'] for t in new_trials]==[77,78],'WRONG_NEW_ORDINALS')
    out={}
    for kind,ordinal in KINDS.items():
        target=root/'results'/kind;r=read(target/'RECEIPT.json');claim=read(root/'attempts'/f'{kind}.json');start=read(target/'LOCAL_START.json')
        require(r['status']=='COMPLETED' and r['ordinal']==ordinal,'RUN_NOT_COMPLETED')
        require(r['spec_sha256']==sha((root/'SPEC.json').read_bytes())==claim['spec_sha256'],'SPEC_IDENTITY')
        require(start['claim_commit']==start['remote_readback_sha']==r['claim_commit'],'REMOTE_CLAIM_IDENTITY')
        raw=(target/'RESULT.json.gz').read_bytes();engine=(target/'RAW_ENGINE.json.gz').read_bytes()
        require(sha(raw)==r['result_sha256'] and sha(engine)==r['raw_sha256'],'RESULT_RECEIPT_DRIFT')
        result=json.loads(gzip.decompress(raw));out[kind]=validate_rows(result)
    return {'status':'TWO_CORRECTED_SEEN_RESULTS_VERIFIED_NO_REPLAY','candidates':budget['cumulative_actual'],
            'evaluations':budget['cumulative_actual_evaluations'],'new_valid':2,'prior_failures_preserved':2,'results':out,'economic_replays':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);x=p.parse_args()
    print(json.dumps(verify(expected_manifest_sha=x.manifest_sha256),indent=2))
