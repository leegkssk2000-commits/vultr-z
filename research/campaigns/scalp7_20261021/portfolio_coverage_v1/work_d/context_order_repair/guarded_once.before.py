"""Single bounded continuation of this invocation, not a new service/schedule.
Wait for the existing GitHub global-heavy holder; never cancel or displace it.
"""
from pathlib import Path
from datetime import datetime,timezone
import fcntl,gzip,hashlib,io,json,os,subprocess,sys,time,urllib.parse,urllib.request
S=Path(__file__).resolve().parent
API='https://api.github.com/repos/leegkssk2000-commits/vultr-z'
GROUP='a1-global-heavy-economic-evaluator-v1'
PY='/home/z/z/venv/bin/python'
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def emit(state,**kw):
    entry={'at_utc':now(),'state':state,'pid':os.getpid(),**kw}
    with (S/'GUARD_EVENTS.jsonl').open('a') as f:f.write(json.dumps(entry,ensure_ascii=False)+'\n')
    (S/'GUARD_STATUS.tmp').write_text(json.dumps(entry,indent=2)+'\n');os.replace(S/'GUARD_STATUS.tmp',S/'GUARD_STATUS.json')
    print(json.dumps(entry,ensure_ascii=False),flush=True)
def request(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'zel-existing-coordinator-bounded-gate'}),timeout=15))
def busy_runs():
    busy=[];observations=[]
    for status in ['in_progress','pending','waiting']:
        response=request(API+'/actions/runs?status='+status+'&per_page=100')
        if response['total_count']>len(response['workflow_runs']):raise RuntimeError('CAPACITY_LIST_INCOMPLETE')
        for row in response['workflow_runs']:
            path=row['path'].split('@')[0];spec=request(API+'/contents/'+path+'?ref='+row['head_sha'])
            import base64
            text=base64.b64decode(spec['content']).decode()
            isheavy=GROUP in text
            item={k:row[k] for k in ['id','name','status','head_sha']};item['global_heavy']=isheavy
            observations.append(item)
            if isheavy:busy.append(item)
    return busy,observations

def run_cached():
    import pandas as pd
    import run_handoff as runner
    cache=json.loads((S/'INPUT_CACHE.json').read_text())
    def frames():
        output={};original=json.loads((runner.BASE/'CHRONO_SOURCE_BINDING.json').read_text())
        for symbol,record in cache['symbols'].items():
            raw=(S/record['path']).read_bytes()
            if sha(raw)!=record['sha256']:raise ValueError('INPUT_CACHE_CHANGED')
            f=pd.read_csv(io.BytesIO(raw),compression='gzip',float_precision='round_trip')
            digest=sha(f.to_csv(index=False).encode())
            if digest!=record['csv_sha256'] or digest!=original[symbol]['full_csv_sha256']:raise ValueError('ORIGINAL_PRICE_PARITY_FAILED')
            if len(f)!=17519:raise ValueError('INCOMPLETE_FULL_PREFIX')
            output[symbol]=f
        return output
    runner.previous.full_frames=frames
    runner.run()

def report():
    data=json.loads((S/'SUMMARY.json').read_text());raw=(S/'ROWS.json').read_bytes()
    if sha(raw)!=data['rows_sha256']:raise ValueError('FINAL_ROWS_HASH')
    rows=json.loads(raw)['carry_scenario_trades'];metrics=data['child_metrics']
    for m in [1,2]:
        value=sum(float(t['gross_bps'])-m*float(t['cost_bps']) for t in rows)
        if abs(value-metrics['cost'+str(m)+'x']['Net_bps'])>1e-7:raise ValueError('SUM_AUDIT_FAILED')
    audit={'at_utc':now(),'trades':len(rows),'net1x2x_recomputed':True,'summary_sha256':sha((S/'SUMMARY.json').read_bytes()),'rows_sha256':sha(raw),'new_backtests':0}
    (S/'ARITHMETIC_AUDIT.json').open('x').write(json.dumps(audit,indent=2)+'\n')
    (S/'ROWS.json.gz').open('xb').write(gzip.compress(raw,mtime=0))
    lines=['# Keltner stage2: fresh-signal handoff during conditional extension','',
      'Completed UTC: '+data['completed_at_utc'],
      'Classification: ACTUAL_USED_DEV_CHRONOLOGICAL_COMPARISON_NOT_OOS_NOT_ACCOUNT_RETURN',
      'Disposition: '+data['disposition'],'',
      'One frozen change: after the original25-bar deadline and observed2R qualification, an eligible same-direction native signal can close the old remaining position and start one new ordinary position at the next open. No concurrent pyramiding. Full cost model charged to each trade. Existing25/50 cap and protected lifecycle unchanged.','',
      '|Metric|Prior126 extension|New handoff|','|---|---:|---:|']
    for field,label in [('T','Trades'),('Net_bps','Net1x trade-bps'),('PF','PF1x'),('WR_pct','WR1x pct'),('DD_bps','DD1x trade-bps'),('MaxLossStreak','Loss streak1x')]:
        a=data['prior126_metrics']['cost1x'][field];b=data['child_metrics']['cost1x'][field];lines.append(f'|{label}|{a:.8f}|{b:.8f}|')
    for field,label in [('Net_bps','Net2x trade-bps'),('PF','PF2x'),('DD_bps','DD2x trade-bps'),('MaxLossStreak','Loss streak2x')]:
        a=data['prior126_metrics']['cost2x'][field];b=data['child_metrics']['cost2x'][field];lines.append(f'|{label}|{a:.8f}|{b:.8f}|')
    lines+=['',f"Net delta1x {data['net_delta1x']:.8f}; delta2x {data['net_delta2x']:.8f} trade-bps.",
      f"Handoffs {data['handoff_count']}; unresolved {data['child_unresolved']}; boundary excluded {data['child_boundary_excluded']}.",
      '', '## Opportunity accounting',json.dumps({k:data[k] for k in ['recovered_vs128_keys','lost_vs126','added_vs126','cohorts','changed_common_trades']},ensure_ascii=False,indent=2),
      '', '## Limits and preservation',
      '- The old126T positive extension is immutable; an inferior child is rejected rather than replacing it.',
      '- Full original signal/state/rejection chronology, fees, missed/reintroduced trades and extra carry scenario included; not selected-winner recovery.',
      '- Same245-day usedDEV and original365-day indicator/context prefix. Source hashes and context-fit parity confirmed; disabled adapter reproduces126T exactly.',
      '- Historical funding, real execution latency, MTM/account drawdown and independentOOS remain unverified; summed trade-bps are not account percent.',
      '- No activeShadow/root strategy/workflow/OWNER/CHECKPOINT mutation, no tokens, marketAPI, paidAPI, orders or deployment. ReservedS comparison untouched.',
      '- Separately joined all128 entry-time OHLC/EMA20/ADX fields; this is input reconstruction, not a newly successful loss filter.',
      '- No parameter sweep. Current user approved this one additional missed-opportunity mechanism.',
      '- Existing other global-heavy work was allowed to terminate; no cancellation or preemption.',
      '', 'Source result commit308bd2deb7acaaacf1adb582206e78262d72c9d1; new freeze68e4b995419aea62e6362c01f8a54fd3455c556fde444f8877e8cf9547244b1a.']
    (S/'RESULT.md').open('x').write('\n'.join(lines)+'\n')
    import persist_addonly
    persist_addonly.persist('completion')

def main():
    lock=(S/'invocation.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (S/'SUMMARY.json').exists():emit('ALREADY_COMPLETE_NO_REPLAY');return
    if (S/'STARTED.json').exists():raise RuntimeError('PARTIAL_ALREADY_STARTED_REVIEW_NOT_RETRY')
    deadline=time.monotonic()+2400
    emit('WAITING_SHARED_HEAVY',known_holder=39600071418,economic_started=False,wait_bound_seconds=2400)
    while time.monotonic()<deadline:
        busy,all_runs=busy_runs()
        if busy:
            emit('WAITING_SHARED_HEAVY',holders=busy,economic_started=False)
            time.sleep(60);continue
        emit('CAPACITY_CLEAR_START_ONCE',observed_runs=all_runs,economic_started=False)
        log=(S/'EXECUTION.log').open('x')
        rc=subprocess.run([PY,'-u','-B',str(S/'guarded_once.py'),'execute-cached'],stdout=log,stderr=subprocess.STDOUT,timeout=600,
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')).returncode
        log.close()
        if rc:emit('EXECUTION_FAILED_NO_BLIND_RETRY',exit_code=rc);return
        emit('ECONOMIC_COMPARISON_COMPLETE',summary_sha256=sha((S/'SUMMARY.json').read_bytes()),economic_started=True)
        report();emit('COMPLETE_STORED',economic_started=True);return
    emit('WAIT_BOUND_REACHED_NO_ECONOMIC_START',economic_started=False)
if __name__=='__main__':
    try:
        if len(sys.argv)>1 and sys.argv[1]=='execute-cached':run_cached()
        else:main()
    except Exception as exc:
        emit('HOLD',error=type(exc).__name__,message=str(exc),no_automatic_retry=True)
        raise
