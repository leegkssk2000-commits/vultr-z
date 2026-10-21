"""Independent arithmetic on saved rows only; never replays market prices."""
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict
import gzip,hashlib,json,math
S=Path(__file__).resolve().parent
BASE=Path('/home/z/z/runtime/k_winner_timeout_20261021T1142Z')
def sha(b):return hashlib.sha256(b).hexdigest()
def write(n,v):
    b=(json.dumps(v,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    with (S/n).open('xb') as f:f.write(b)
def metric(rows,m):
    gains=loss=total=0.;cohorts=defaultdict(float);current=[];runs=[]
    for t in sorted(rows,key=lambda v:(v['outcome_available_ts_ms'],v['symbol'],v['entry_ts_ms'])):
        value=t['gross_bps']-m*t['cost_bps'];total+=value
        if value>0:gains+=value
        elif value<0:loss-=value
        cohorts[t['outcome_available_ts_ms']]+=value
        if value<0:current.append(value)
        elif current:runs.append(current);current=[]
    if current:runs.append(current)
    eq=peak=dd=0.
    for stamp,value in sorted(cohorts.items()):eq+=value;peak=max(peak,eq);dd=max(dd,peak-eq)
    return {'T':len(rows),'Net_bps':total,'PF':gains/loss if loss else None,'DD_bps':dd,'MaxLossStreak':max(map(len,runs),default=0),'worst_loss_run_bps':min(map(sum,runs),default=0.)}
def main():
    result=json.loads((S/'SUMMARY.json').read_bytes());raw=(S/'ROWS.json').read_bytes()
    if sha(raw)!=result['rows_sha256']:raise ValueError('RESULT_ROWS_HASH_CHANGED')
    rows=json.loads(raw);base=json.loads((BASE/'CHRONO_ROWS.json').read_bytes())['carry_scenario_trades']
    checks={}
    for label,data in [('baseline',base),('child',rows['trades'])]:
        if len({(t['symbol'],t['side'],t['signal_ts_ms']) for t in data})!=len(data):raise ValueError('DUPLICATE_TRADE')
        for t in data:
            if abs(t['net_bps']-(t['gross_bps']-t['cost_bps']))>1e-8:raise ValueError('ROW_ARITHMETIC')
            if not t['signal_ts_ms']<=t['entry_ts_ms']<=t['exit_ts_ms']<=t['outcome_available_ts_ms']:raise ValueError('TIMING')
        for m in (1,2):
            got=metric(data,m);expected=result[label][f'cost{m}x']
            for k,v in got.items():
                if v is None:
                    if expected[k] is not None:raise ValueError('NULL_PF_MISMATCH')
                elif not math.isclose(float(v),float(expected[k]),rel_tol=0,abs_tol=1e-7):raise ValueError('SUMMARY_MISMATCH:'+label+':'+k)
            checks[label+f'_cost{m}x']=got
    pairs=json.loads((S/'PAIRED_ALL126.json').read_bytes())
    if len(pairs['paired'])+len(pairs['unresolved'])!=126:raise ValueError('PAIRED_COVERAGE')
    for p in pairs['paired']:
        e=p['first_failure']
        if e and not e['signal_available_ts_ms']<=p['baseline']['entry_ts_ms']<=e['first_failure_available_ts_ms']:raise ValueError('FAILURE_TIME_NONCAUSAL')
        if p['child']['reason']=='K126_REVERSAL_BAR_FAILURE_NEXT_OPEN':
            if e is None or p['child']['exit_ts_ms']!=e['first_failure_close_ts_ms']:raise ValueError('NEXT_OPEN_BOUNDARY')
    audit={'at_utc':datetime.now(timezone.utc).isoformat(),'checks':checks,'all_saved_trade_cost_arithmetic_exact':True,'unique_keys':True,'causal_timestamps':True,
      'all126_same_entries_accounted':True,'original_control126_exact':json.loads((S/'CONTROL_PARITY.json').read_text())['exact126_rows'],
      'summary_sha256':sha((S/'SUMMARY.json').read_bytes()),'rows_sha256':sha(raw),'new_price_replays':0,'account_returns':False}
    write('ARITHMETIC_AUDIT.json',audit)
    for name in ['ROWS.json','PAIRED_ALL126.json']:
        with (S/(name+'.gz')).open('xb') as f:f.write(gzip.compress((S/name).read_bytes(),mtime=0))
    lines=['# K126 post-entry reversal-bar failure: actual paired and chronological comparison','',
      'Completed UTC: '+result['at_utc'],'Disposition: '+result['disposition'],
      'Baseline retained: 308bd2deb7acaaacf1adb582206e78262d72c9d1.',
      'Classification: ACTUAL_USED_DEV_EXIT_ONLY_COMPARISON. Equal-notional trade-bps, not account returns.',
      '', '## Predeclared rule',
      'For a long, a completed close below the original reversal-signal low (short: above high) schedules an exit at the actual next open. Wicks alone do not qualify. Existing protective stops, gap fills and already-due exits take precedence. Entry, original risk, fee-BE, partial, scratch and positive25/50bar winner extension remain fixed. This is a source-motivated internal translation, not an author-exact certified rule. No fitted cutoff or sweep.',
      '', '|Metric|Incumbent K126|New exit rule|','|---|---:|---:|']
    for m in (1,2):
        for k in ['T','Net_bps','PF','WR_pct','MaxLossStreak','worst_loss_run_bps','DD_bps']:
            a=result['baseline'][f'cost{m}x'][k];b=result['child'][f'cost{m}x'][k]
            lines.append(f'|{k} cost{m}x|{a:.8f}|{b:.8f}|')
    lines+=['','## Failure onset versus later loss: ALL126 paired entries (not final chronology)',json.dumps(result['paired'],ensure_ascii=False,indent=2),
      'Original worst8 paired sum delta1x: '+str(result['original_worst8']['paired_delta1x']),
      'Original worst8 changed entries: '+str(result['original_worst8']['paired_changed_T']),
      '', '## Full chronological opportunity and winner effects',json.dumps({k:result[k] for k in ['attribution','cohorts','removed','added','child_unresolved','child_boundary_excluded']},ensure_ascii=False,indent=2),
      '', '## Limits',
      'The first bar failure marker is a hypothesis, not proof that a full trend is invalid. Recovery winners are included. Paired improvements are not added to overlapping new opportunities; final results come from the native state/admission/occupancy chronology.',
      'Same245-day usedDEV and original365-day context. No independentOOS, live fills, NAV/MTM drawdown, or verified historical funding. Reference1x/2x costs plus previously disclosed extra-holding reserve. No currentShadow/order/production change; reserved S/C comparisons unspent.',
      'Sources and scope in SOURCE_APPLICATION.md; prepared before the real run at34df33538653d14fea12c56473782eb776068b22. Original module hashes, six prices and context, and disabled126 rows exactly checked.',
      'Artifacts: SUMMARY.json, ROWS.json.gz, PAIRED_ALL126.json.gz, ARITHMETIC_AUDIT.json, CONTROL_PARITY.json, FREEZE.json, EXECUTION.log.']
    with (S/'RESULT.md').open('x') as f:f.write('\n'.join(lines)+'\n')
    import store_result
    receipt=store_result.persist('completion')
    import owner_record
    owner_record.update('TERMINAL',{'result_commit':receipt['commit'],'result_path':receipt['path']+'/RESULT.md','completed_at_utc':result['at_utc'],'disposition':result['disposition'],'summary_sha256':audit['summary_sha256'],'independent_arithmetic':True,'retained_incumbent':'308bd2deb7acaaacf1adb582206e78262d72c9d1','reserved_S_consumed':0,'reserved_C_consumed':0})
    print('AUDIT_COMPLETE',json.dumps(audit),flush=True)
if __name__=='__main__':main()
