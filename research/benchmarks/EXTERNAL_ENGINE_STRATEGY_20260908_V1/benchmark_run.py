"""Finite external benchmark; unchanged external matcher, no tuning or market API.
Raw engine prices, normalized research costs and convention differences remain
separate. All data are already-used DEV, not independent validation.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import pandas as pd
import ft_offline as ft
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
REL=str(HERE.relative_to(ROOT))
BUDGET='research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/BUDGET.json'
BRANCH='research/external-engine-strategy-benchmark-v1'
SCOPE='EXTERNAL_ENGINE_STRATEGY_20260908_V1'
PERIODS={'DEV2025':(1734595200000,1766995200000),'SEEN2026':(1778198400000,1788566400000)}
ROW_SHA={'DEV2025':'3cb1bbeb6166a1ae3b32bb9a832faeee579a5d208ecfbfd4bf86004786c70e3a','SEEN2026':'406e72401bec107c31ac17fd9742489f5980ca411b0f848613692fd2d00d29af'}
COST_SHA='e7b29de0b1810d14e02847917e951301f4d9a30da190ed7c6fc4cafbca581020'
RUNS=[('BREAK',p) for p in PERIODS]+[('HERACLES',p) for p in PERIODS]

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(x):return hashlib.sha256(canonical(x)).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise RuntimeError('WRITE_ONCE_EXISTS:'+str(path))
    with path.open('xb') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
def gzread(path):return json.loads(gzip.decompress(path.read_bytes()))
def checked(cmd):return subprocess.check_output(cmd,cwd=ROOT,text=True,timeout=60).strip()
def persist(message):
    checked(['git','add',REL,BUDGET])
    paths=checked(['git','diff','--cached','--name-only']).splitlines()
    if any(p!=BUDGET and not p.startswith(REL+'/') for p in paths):raise RuntimeError('UNSCOPED_WRITE')
    if not paths:return
    checked(['git','commit','-m',message+' [skip ci]'])
    checked(['git','push','origin','HEAD:refs/heads/'+BRANCH])
    remote=checked(['git','ls-remote','origin','refs/heads/'+BRANCH]).split()[0]
    if remote!=checked(['git','rev-parse','HEAD']):raise RuntimeError('REMOTE_READBACK_MISMATCH')

def engine_dependencies():
    import freqtrade.optimize.backtesting as bt
    import freqtrade.strategy.interface as si
    import freqtrade.resolvers.strategy_resolver as sr
    return {Path(m.__file__).name:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (bt,si,sr)}

def cost(entry,exit_,binding):
    n=max(0,int(exit_)//28800000-int(entry)//28800000)
    return max(20.,sum(float(binding[k]) for k in ('fee_bps','spread_bps','impact_bps'))+n*float(binding['funding_p95_per_settlement_bps']))

def reference_class(source):
    raw=source.read_bytes()
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!='b69656b76ee142c0945dbb0229a19d67d5516215':raise RuntimeError('EXTERNAL_SOURCE_DRIFT')
    spec=importlib.util.spec_from_file_location('pinned_heracles',source)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    class HeraclesSourceAge(mod.Heracles):
        """Only PIT age eligibility outside unchanged upstream rule."""
        def populate_entry_trend(self,dataframe,metadata):
            df=super().populate_entry_trend(dataframe,metadata)
            start=self.config['verified_history_start'].get(metadata['pair'])
            if start is None:raise RuntimeError('AGE_SOURCE_REQUIRED')
            dates=df.date.map(lambda d:int(d.timestamp()*1000))
            df.loc[dates+ft.BAR<start+100*86400000,'enter_long']=0
            return df
    return HeraclesSourceAge

def frame(rows):
    return pd.DataFrame({'date':pd.to_datetime([r['bar_open_ts'] for r in rows],unit='ms',utc=True),
       **{k:[r[k] for r in rows] for k in ('open','high','low','close','volume')}})

def normalize_engine(raw,packet,end):
    out=[]
    for r in raw:
        symbol=r['pair'].replace('/','-');entry=int(pd.Timestamp(r['open_date']).timestamp()*1000)
        ex=int(pd.Timestamp(r['close_date']).timestamp()*1000);reason=r['exit_reason']
        opened=reason=='force_exit'
        # Engine force-close remains an unresolved position; final actual known
        # close is valuation, not a fill. Intrabar time has a whole-bar bound.
        price=float(packet['rows_by'][symbol][-1]['close']) if opened else float(r['close_rate'])
        intrabar=not opened and reason in ('roi','stop_loss','trailing_stop_loss')
        lower=end if opened else ex;upper=end if opened else min(end,ex+ft.BAR) if intrabar else ex
        gross=(price/float(r['open_rate'])-1)*10000
        c=cost(entry,upper,packet['costs'][symbol]);cl=cost(entry,lower,packet['costs'][symbol])
        out.append({'symbol':symbol,'origin':f'{symbol}:{entry}','entry_ts':entry,
          'entry_price':float(r['open_rate']),'exit_ts':upper,'exit_ts_lower':lower,
          'exit_price':price,'closed':not opened,'reason':reason,'gross_bps':gross,
          'cost_bps':c,'net_bps':gross-c,'cost2_bps':gross-2*c,
          'cost_lower_bps':cl,'net_upper_bps':gross-cl,'intrabar_time_unobserved':intrabar})
    return out

def normalize_saved(v):
    out=[]
    for t in v['trades']:
        out.append({'symbol':t['symbol'],'origin':f'{t["symbol"]}:{t["entry_ts"]}',
          'entry_ts':t['entry_ts'],'entry_price':t['entry_price'],'exit_ts':t['exit_ts'],
          'exit_ts_lower':t['exit_ts'],'exit_price':t['exit_price'],'closed':True,
          'reason':'ZEL_H6_HELD_CLOSE','gross_bps':t['gross_bps'],'net_bps':t['net_bps'],
          'cost2_bps':t['cost2x_net_bps'],'cost_bps':t['cost_bps']})
    for t in v['open_observations']:
        out.append({'symbol':t['symbol'],'origin':f'{t["symbol"]}:{t["entry_ts"]}',
          'entry_ts':t['entry_ts'],'entry_price':t['entry_price'],'exit_ts':t['mark_ts'],
          'exit_ts_lower':t['mark_ts'],'exit_price':t['mark_price'],'closed':False,
          'reason':'ZEL_OPEN_MARK','gross_bps':t['gross_mark_bps'],
          'net_bps':t['hypothetical_liquidation_net_mark_bps'],
          'cost2_bps':t['hypothetical_liquidation_cost2x_net_mark_bps'],
          'cost_bps':t['hypothetical_liquidation_cost_bps']})
    return out

def metrics(trades,packet,start,end):
    closed=[t for t in trades if t['closed']];wins=[t['net_bps'] for t in closed if t['net_bps']>0]
    losses=[-t['net_bps'] for t in closed if t['net_bps']<0]
    marks={s:{r['bar_close_ts']:r['close'] for r in rows} for s,rows in packet['rows_by'].items()}
    curve=[];peak=dd=0.
    for ts in sorted(set(t for m in marks.values() for t in m if start<t<=end)):
        eq=0.
        for t in trades:
            if t['entry_ts']>=ts:continue
            if t['closed'] and t['exit_ts']<=ts:eq+=t['net_bps']
            else:eq+=(marks[t['symbol']][ts]/t['entry_price']-1)*10000-cost(t['entry_ts'],ts,packet['costs'][t['symbol']])
        peak=max(peak,eq);dd=max(dd,peak-eq);curve.append([ts,eq])
    return {'closed':len(closed),'open':len(trades)-len(closed),'wins':len(wins),
      'win_rate':len(wins)/len(closed) if closed else None,
      'payoff':(sum(wins)/len(wins))/(sum(losses)/len(losses)) if wins and losses else None,
      'PF':sum(wins)/sum(losses) if losses else None,
      'closed_net':sum(t['net_bps'] for t in closed),
      'open_mark':sum(t['net_bps'] for t in trades if not t['closed']),
      'terminal_net':sum(t['net_bps'] for t in trades),'terminal_cost2':sum(t['cost2_bps'] for t in trades),
      'mark4h_DD':dd,'exposure_symbol_days':sum((t['exit_ts']-t['entry_ts'])/86400000 for t in trades),
      'by_symbol':{s:sum(t['net_bps'] for t in trades if t['symbol']==s) for s in packet['rows_by']},
      'intrabar_time_uncertain':sum(t.get('intrabar_time_unobserved',False) for t in trades),
      'net_upper_due_only_to_time_cost':sum(t.get('net_upper_bps',t['net_bps']) for t in trades),
      'equity4h':curve}

def compare(v,engine,signals,start,end):
    raw={(s,int(d.timestamp()*1000)+ft.BAR) for s,df in signals.items() for d,x in zip(df.date,df.enter_long.fillna(0)) if x and start<=int(d.timestamp()*1000)+ft.BAR<end}
    original={(r['symbol'],r['signal_ts']) for r in v['events'] if start<=r['signal_ts']<end}
    ours={t['origin']:t for t in normalize_saved(v)};other={t['origin']:t for t in engine}
    common=sorted(set(ours)&set(other));mismatches=[]
    for k in common:
        changed={f:[ours[k][f],other[k][f]] for f in ('entry_price','exit_ts','exit_price','closed','cost_bps') if (ours[k][f]!=other[k][f] if isinstance(ours[k][f],bool) else not math.isclose(float(ours[k][f]),float(other[k][f]),rel_tol=1e-12,abs_tol=1e-12))}
        if changed:mismatches.append({'origin':k,'changes':changed})
    return {'raw_signals_native':len(original),'raw_signals_external':len(raw),
      'raw_signal_symmetric_difference':sorted(original^raw),'common_entries':len(common),
      'native_only_entries':sorted(set(ours)-set(other)),
      'external_only_entries':sorted(set(other)-set(ours)),
      'mismatched_common_entries':len(mismatches),'first_mismatches':mismatches[:10],
      'declared_convention_deltas':['ZEL_H6_CLOSE_VS_FT_NEXT_OPEN','FT_NO_LAST_BAR_ENTRY','FT_FORCE_EXIT_REPORTED_AS_OPEN_FINAL_CLOSE_MARK','UNCONSTRAINED_ANALYTICAL_PRECISION_NOT_FUTURES_EXECUTION']}

def run_one(kind,period,inputs):
    packet=gzread(inputs/(period+'.json.gz'));start,end=PERIODS[period]
    if sha(packet['rows_by'])!=ROW_SHA[period] or sha(packet['costs'])!=COST_SHA:raise RuntimeError('INPUT_DRIFT')
    frames={s.replace('-','/'):frame(rows) for s,rows in packet['rows_by'].items()}
    klass=ft.BreakV2Port if kind=='BREAK' else reference_class(inputs/'Heracles.py')
    result,signals=ft.run_frame(klass,frames,start,end,Path('/tmp/benchmark-'+kind+'-'+period),{s.replace('-','/'):v for s,v in packet['history_start'].items()})
    raw=json.loads(result['results'].to_json(orient='records',date_format='iso',double_precision=15))
    trades=normalize_engine(raw,packet,end)
    if any(t['entry_ts']<start or t['entry_ts']>=end for t in trades):raise RuntimeError('ENTRY_OUTSIDE_APPROVED_PERIOD')
    savedpath=ROOT/'research/development_evidence/FOCUSED_REPAIR_20260907_V1/BR2'/f'{period}.json.gz'
    parent=gzread(savedpath)['views']['V2']
    signal_rows={s.replace('/','-'):json.loads(df[['date','enter_long']].fillna({'enter_long':0}).to_json(orient='records',date_format='iso')) for s,df in signals.items()}
    report={'kind':kind,'period':period,'raw_engine_trades':raw,'normalized_trades':trades,
      'signals':signal_rows,'metrics':metrics(trades,packet,start,end),
      'saved_native_metrics':metrics(normalize_saved(parent),packet,start,end),
      'resolved_parameters':result['resolved_parameters'],'engine_dependencies':engine_dependencies(),
      'saved_native_file_sha256':hashlib.sha256(savedpath.read_bytes()).hexdigest(),
      'engine_rejected_signals':result['rejected_signals'],'formal_credit':0,'independent':False}
    if kind=='BREAK':report['parity']=compare(parent,trades,{s.replace('/','-'):df for s,df in signals.items()},start,end)
    return report

def make_report():
    docs=[json.loads((HERE/'results'/f'{k}_{p}.json').read_bytes()) for k,p in RUNS if (HERE/'results'/f'{k}_{p}.json').exists()]
    rows=[]
    for p in PERIODS:
        d=next((x for x in docs if x['period']==p),None)
        if d:
            for label,m in [('ZEL_Break_V2_SAVED',d['saved_native_metrics'])]+[(x['kind'],x['metrics']) for x in docs if x['period']==p]:
                fmt=lambda x:'NA' if x is None else f'{x:.3f}'
                rows.append('|'+ '|'.join([p,label,f"{m['closed']}/{m['open']}",fmt(100*m['win_rate']) if m['win_rate'] is not None else 'NA',fmt(m['payoff']),fmt(m['PF']),fmt(m['terminal_net']),fmt(m['terminal_cost2']),fmt(m['mark4h_DD'])])+'|')
    text=['# Actual external engine / strategy benchmark','',
      'All monetary values are equal-notional trade-bps, not account returns. USED_DEV only.',
      'Costs: original20bps floor/absolute funding proxy; same price paths repriced at2x, not ROI re-optimized at2x.',
      'External ROI/SL are stock4h-candle assumptions. Intrabar time is unobserved; conservative bar-close funding debit applied. Forced engine terminal exits are OPEN marks, not wins.',
      'Heracles rule and published loaded parameters unchanged; point-in-time100day verified-source-history age filter is an explicit adaptation of the source recommendation.',
      'Offline SPOT matching applied to existing BingX futures price data is an analytical experiment, NOT certified futures support or a live strategy.',
      '4h DD uses the same new4h-close valuation for native/external; never compare it as identical to old dailyDD.','',
      '|Period|Strategy|Closed/open|WR%|Payoff|PF|Terminal net|Allcost2|4h marked DD|','|---|---|---:|---:|---:|---:|---:|---:|---:|']+rows
    for d in docs:
        if 'parity' in d:text+=['',f"## {d['period']} actual engine differences",'```json',json.dumps(d['parity'],indent=2),'```']
    text+=['','No D/D2/KR3 promotion or removal. No parameter sweep, new market collection, paid AI, unused OOS or live orders.',
      'Remote closure/CI/merge status is separate. A failed or incompatible benchmark is not proof all external systems fail.','']
    (HERE/'REPORT.md').write_text('\n'.join(text))

def execute(inputs):
    budgetpath=ROOT/BUDGET;budget=json.loads(budgetpath.read_bytes())
    if (budget['cumulative_actual'],budget['cumulative_actual_evaluations'])!=(47,68) or 'external_benchmark_allocation' in budget:raise RuntimeError('EXISTING_BUDGET_OR_BENCHMARK_RECOVER_FIRST')
    # Identity checks happen before any claim or empirical evaluation.
    for period in PERIODS:
        packet=gzread(inputs/(period+'.json.gz'))
        if sha(packet['rows_by'])!=ROW_SHA[period] or sha(packet['costs'])!=COST_SHA:raise RuntimeError('INPUT_PREFLIGHT_DRIFT')
    spec={'scope':SCOPE,'runs':RUNS,'max_evaluations':4,'max_new_external_references':1,
      'source_commit':'7f91ff52bb664423ae673092a6a18d76c50c2c29','source_blob':'b69656b76ee142c0945dbb0229a19d67d5516215',
      'engine_version':importlib.metadata.version('freqtrade'),'ta_version':importlib.metadata.version('ta'),
      'engine_dependencies':engine_dependencies(),'data_hashes':ROW_SHA,'cost_sha256':COST_SHA,
      'scientific_files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'ft_offline.py',Path(__file__))},
      'calendar':PERIODS,'age_days':100,'fee_per_side':.0005,'stake_notional':1000,'leverage':1,
      'initial_counts':[47,68],'prepared_files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir() if p.is_file()},
      'scope_md_sha256':hashlib.sha256((HERE/'SCOPE.md').read_bytes()).hexdigest(),
      'cost_fill_conventions':'See normalize_engine/metrics and SCOPE. Engine prices retained; same-path repricing; intrabar upper-close funding bound; force_exit retained OPEN.',
      'future_validation':'NONE_USED_DEV_ONLY','promotion':False}
    spec['receipt_sha256']=sha(spec);write(HERE/'SPEC.json',spec)
    (HERE/'ENVIRONMENT.txt').write_text(checked([sys.executable,'-m','pip','freeze'])+'\n')
    (HERE/'UPSTREAM_Heracles.py').write_bytes((inputs/'Heracles.py').read_bytes())
    (HERE/'LICENSE.external').write_bytes((inputs/'LICENSE.external').read_bytes())
    persist('benchmark: freeze source engine data and conventions before outcomes')
    for index,(kind,period) in enumerate(RUNS):
        ordinal=69+index;name=f'{kind}_{period}'
        if kind=='HERACLES' and index==2:
            budget['cumulative_actual']=48
            budget.setdefault('candidate_trials',[]).append({'candidate':'EXTERNAL_HERACLES_SOURCE_PINNED_REFERENCE','ordinal':48,'first_evaluation':ordinal,'scope':SCOPE,'reference_only':True})
        attempt={'scope':SCOPE,'run':name,'actual_experiment_ordinal':ordinal,'status':'RESERVED_BEFORE_EXTERNAL_ENGINE',
          'classification':'EXISTING_BREAK_EXTERNAL_ENGINE_COMPARISON' if kind=='BREAK' else 'EXTERNAL_SOURCE_STRATEGY_REFERENCE',
          'new_candidate':kind=='HERACLES' and index==2,'retry_allowed':False,
          'runtime_run_id':os.environ.get('GITHUB_RUN_ID'),'started_ns':time.time_ns(),'specification_sha256':spec['receipt_sha256']}
        write(HERE/'attempts'/f'{name}.json',attempt)
        budget['cumulative_actual_evaluations']=ordinal;budget['trials'].append(attempt)
        budget['external_benchmark_allocation']={'scope':SCOPE,'max_executions':4,'used':index+1,'completed':index,'status':'RUNNING','no_retry':True}
        budgetpath.write_text(json.dumps(budget,sort_keys=True,indent=2)+'\n')
        persist('benchmark: reserve actual ordinal '+str(ordinal)+' before compute')
        print('ACTUAL_ECONOMIC_BEGIN',name,ordinal,flush=True)
        try:
            result=run_one(kind,period,inputs);write(HERE/'results'/f'{name}.json',result)
            write(HERE/'receipts'/f'{name}.json',{'status':'COMPLETED','run':name,'ordinal':ordinal,'result_sha256':hashlib.sha256((HERE/'results'/f'{name}.json').read_bytes()).hexdigest(),'specification_sha256':spec['receipt_sha256']})
            budget['external_benchmark_allocation'].update(completed=index+1,status='COMPLETED' if index==3 else 'PARTIAL')
            budgetpath.write_text(json.dumps(budget,sort_keys=True,indent=2)+'\n');make_report()
            persist('benchmark: preserve actual '+name+' result without rerun')
            print('ACTUAL_ECONOMIC_COMPLETED',name,{k:v for k,v in result['metrics'].items() if k!='equity4h'},flush=True)
        except BaseException as exc:
            write(HERE/'failures'/f'{name}.json',{'status':'FAILED_OR_UNKNOWN_CONSUMED','error_type':type(exc).__name__,'error':str(exc),'retry_allowed':False})
            make_report();persist('benchmark: preserve failed or uncertain consumed attempt');raise

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--input',type=Path,required=True);args=a.parse_args();execute(args.input)
