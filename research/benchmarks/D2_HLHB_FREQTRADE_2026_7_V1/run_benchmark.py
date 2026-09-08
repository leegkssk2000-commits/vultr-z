"""One reserved actual engine run; all native evidence is comparison-only.

No native replay or external market IO. Canonical already-used prefixes are
accepted only at frozen D2 hashes. Failed runs are consumed, never auto-retried.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import traceback
import accounting as a
from D2Independent import D2Independent
import offline_engine as ft

SCOPE='ZEL_EXTERNAL_ENGINE_STRATEGY_BENCHMARK_AFTER_PR1218_V1'
PERIODS={'DEV2025':(1734595200000,1766995200000),'SEEN2026':(1778198400000,1788566400000)}
ROW_SHA={'DEV2025':'3cb1bbeb6166a1ae3b32bb9a832faeee579a5d208ecfbfd4bf86004786c70e3a',
         'SEEN2026':'406e72401bec107c31ac17fd9742489f5980ca411b0f848613692fd2d00d29af'}
POLICY_SHA={'DEV2025':'d686c9bbcee0515d265d66ea789221b078ecb9aaeafd6c7070810a4a66775552',
            'SEEN2026':'dc08e55afdb1fbf2b952bf9baed3a25a2ebcf7c1b3abed4e0b97f73e5d8ce031'}

def json_default(x):
    if hasattr(x,'isoformat'):return x.isoformat()
    if isinstance(x,Path):return str(x)
    if hasattr(x,'item'):return x.item()
    if hasattr(x,'value'):return x.value
    raise TypeError(type(x).__name__)

def encoded(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False,default=json_default).encode()
def digest(x):return hashlib.sha256(encoded(x)).hexdigest()
def load(path):return json.loads(Path(path).read_bytes())
def gzload(path):return json.loads(gzip.decompress(Path(path).read_bytes()))
def write_once(path,value):
    import os
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(encoded(value));f.flush();os.fsync(f.fileno())
    return hashlib.sha256(path.read_bytes()).hexdigest()

def compare(native, raw, normalized, audit, packet):
    expected={(r['symbol'],int(r['signal_index'])) for r in native['events']}
    actual={(p.replace('/','-'),int(r['signal_index'])) for p,x in audit['pairs'].items() for r in x['raw_signals']}
    signal_diff=[{'symbol':s,'index':i,'signal_available_ts':packet['rows_by'][s][i]['bar_close_ts'],
                  'native':(s,i) in expected,'external':(s,i) in actual} for s,i in sorted(expected^actual)]
    nt={(t['symbol'],int(t.get('original_signal_index',t['signal_index']))):t for t in native['trades']+native['open_observations']}
    et={}
    for r,t in zip(raw,normalized):
        tag=str(r.get('enter_tag') or '')
        if not tag.startswith('d2:'):raise ValueError('D2_ORIGIN_TAG_MISSING')
        key=(t['symbol'],int(tag.split(':')[1]));et[key]=t
    entry_diff=[];exit_diff=[];cost_diff=[]
    for key in sorted(set(nt)|set(et),key=lambda k:(packet['rows_by'][k[0]][k[1]]['bar_close_ts'],k)):
        n,e=nt.get(key),et.get(key);s,i=key
        item={'symbol':s,'origin_index':i,'signal_available_ts':packet['rows_by'][s][i]['bar_close_ts']}
        if n is None or e is None:
            entry_diff.append({**item,'native_present':n is not None,'external_present':e is not None});continue
        ec={f:[n[f],e[f]] for f in ('entry_ts','entry_price') if n[f]!=e[f]}
        if ec:entry_diff.append({**item,'changes':ec})
        nc='exit_ts' in n
        xp=n['exit_price'] if nc else n['mark_price'];xt=n['exit_ts'] if nc else n['mark_ts']
        xc={f:[x,y] for f,x,y in [('closed',nc,e['closed']),('exit_ts',xt,e['exit_ts']),('exit_price',xp,e['exit_price'])] if x!=y}
        if xc:exit_diff.append({**item,'changes':xc,'native_reason':n.get('exit_reason',n.get('censor_reason')),'external_reason':e['reason']})
        cv=n['cost_bps'] if nc else n['hypothetical_liquidation_cost_bps']
        if cv!=e['cost_bps']:cost_diff.append({**item,'native_cost_bps':cv,'external_cost_bps':e['cost_bps']})
    nr={(r['symbol'],r['reference_signal_index']):r for r in native['reference_opportunities']}
    er={(p.replace('/','-'),r['reference_signal_index']):r for p,x in audit['pairs'].items() for r in x['reference_opportunities']}
    refdiff=[]
    for key in sorted(set(nr)|set(er)):
        n,e=nr.get(key),er.get(key)
        if n is None or e is None:refdiff.append({'key':key,'native_present':n is not None,'external_present':e is not None});continue
        changes={f:[n.get(f),e.get(f)] for f in ('entry_index','release_index','release_ts','phase','model_selected') if n.get(f)!=e.get(f)}
        if changes:refdiff.append({'key':key,'changes':changes})
    return {'order':['signal','entry_actual_occupancy','reference_reservation','exit_or_mark','common_cost'],
      'raw_signals_native':len(expected),'raw_signals_external':len(actual),'signal_differences':signal_diff,
      'entries_native':len(nt),'entries_external':len(et),'common_origins':len(set(nt)&set(et)),
      'entry_differences':entry_diff,'reference_differences':refdiff,'exit_differences':exit_diff,'cost_differences':cost_diff,
      'callback_errors':audit['callback_errors'],
      'scope':'Independent implementation on USED_DEV, not OOS; native saved trades never fed to adapter',
      'known_semantics':['NATIVE_TIMEOUT_CLOSE_VS_FT_FOLLOWING_OPEN','FT_FORBIDS_LAST_BAR_ENTRY','FORCE_EXIT_RETAINED_OPEN_MARK']}

def execute(kind,period,inputs,output,claim):
    here=Path(__file__).resolve().parent;output=Path(output);inputs=Path(inputs)
    spec=load(here/'SPEC.json');reservation=load(claim)
    if importlib.metadata.version('freqtrade')!='2026.7':raise RuntimeError('ENGINE_VERSION_DRIFT')
    if reservation.get('scope')!=SCOPE or reservation.get('run')!=kind+'_'+period or not reservation.get('remote_readback_commit'):
        raise RuntimeError('DURABLE_RESERVATION_REQUIRED')
    if reservation['spec_sha256']!=hashlib.sha256((here/'SPEC.json').read_bytes()).hexdigest():raise RuntimeError('SPEC_DRIFT')
    for name,expected in spec['scientific_sha256'].items():
        if hashlib.sha256((here/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('CODE_DRIFT:'+name)
    packet=gzload(inputs/(period+'.json.gz'))
    if digest(packet['rows_by'])!=ROW_SHA[period] or digest(packet['policy'])!=POLICY_SHA[period]:raise RuntimeError('D2_INPUT_POLICY_DRIFT')
    a.verify_cost_binding(packet['costs'])
    if packet['policy']['data_ref']!='6d6335d1c9ad7ecb1e9597da85c2eb87635561e1':raise RuntimeError('SOURCE_REF_DRIFT')
    start,end=PERIODS[period]
    write_once(output/'LOCAL_START.json',{'run':kind+'_'+period,'started_at':datetime.now(timezone.utc),'claim':reservation,'retry':False})
    try:
        frames={s.replace('-','/'):ft.frame(rows) for s,rows in packet['rows_by'].items()}
        klass=D2Independent if kind=='D2' else ft.external_class(here/'hlhb.py')
        result,signals,audit,resolved,config,markets=ft.run_frame(klass,frames,start,end,output/'engine')
        dfraw=result['results']
        raw=dfraw.astype(object).where(dfraw.notna(),None).to_dict(orient='records')
        # Save raw unmodified engine output before common-cost accounting.
        write_once(output/'RAW_ENGINE.json',{'trades':raw,'resolved':resolved,'config':config,'metadata':markets,'audit':audit})
        if audit and (audit['callback_errors'] or len(audit['entries'])!=len(raw)):
            raise RuntimeError('D2_CALLBACK_ERRORS_OR_ENTRY_ACCOUNTING')
        normalized=a.normalize_engine(raw,packet,end)
        if any(t['entry_ts']<start or t['entry_ts']>=end for t in normalized):raise RuntimeError('ENTRY_OUTSIDE_APPROVED_PERIOD')
        signal_rows={p:[{'bar_open_ts':int(row['date'].timestamp()*1000),'signal_available_ts':int(row['date'].timestamp()*1000)+ft.BAR,
                          'enter_long':int(row.get('enter_long',0) or 0)} for row in df.fillna({'enter_long':0}).to_dict('records') if int(row.get('enter_long',0) or 0)] for p,df in signals.items()}
        report={'run':kind+'_'+period,'scope':SCOPE,'period':period,'engine_version':'2026.7','formal_credit':0,'independent':False,
          'signals':signal_rows,'normalized_trades':normalized,'metrics':a.metrics(normalized,packet,start,end),'resolved':resolved,
          'ft_native_accounting':{'profit_abs_sum_including_force_exit':sum(float(r['profit_abs']) for r in raw),
             'profit_ratio_sum_including_force_exit':sum(float(r['profit_ratio']) for r in raw),
             'fee_per_side':.0005,'stake_usdt':1000,'wallet_usdt':1_000_000_000,
             'funding':'NOT_MODELED_IN_SPOT_MATCHER; NOT_KNOWN_ZERO_ACTUAL_FUNDING'},
          'raw_result_sha256':hashlib.sha256((output/'RAW_ENGINE.json').read_bytes()).hexdigest()}
        if kind=='D2':
            native=gzload(inputs/'reference'/'Results'/period/'RESULT.json.gz')
            report['parity']=compare(native,raw,normalized,audit,packet)
        h=write_once(output/'RESULT.json',report)
        write_once(output/'RECEIPT.json',{'status':'COMPLETED','run':kind+'_'+period,'result_sha256':h,
                                        'spec_sha256':reservation['spec_sha256'],'ordinal':reservation['ordinal']})
        print(json.dumps({'run':report['run'],'metrics':{k:v for k,v in report['metrics'].items() if k!='equity4h'},'resolved':resolved},default=json_default))
    except BaseException as exc:
        write_once(output/'FAILURE.json',{'status':'FAILED_CONSUMED','run':kind+'_'+period,'type':type(exc).__name__,
                                        'message':str(exc),'traceback':traceback.format_exc(),'retry_allowed':False})
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kind',choices=['D2','HLHB'],required=True);p.add_argument('--period',choices=list(PERIODS),required=True)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--claim',type=Path,required=True)
    args=p.parse_args();execute(args.kind,args.period,args.inputs,args.output,args.claim)
